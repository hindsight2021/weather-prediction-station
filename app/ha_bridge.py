import asyncio
import json
import logging
import os
import paho.mqtt.client as mqtt
import websockets

from app.forecast import summarize_hourly_forecasts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
LOGGER = logging.getLogger(__name__)

HA_WS = os.environ.get("HA_WS_URL", "ws://homeassistant.local:8123/api/websocket")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USERNAME", "")
MQTT_PASS = os.environ.get("MQTT_PASSWORD", "")
WEATHER_ENTITIES = tuple(
    entity.strip()
    for entity in os.environ.get(
        "HA_WEATHER_ENTITIES", "weather.fredericton,weather.ihome"
    ).split(",")
    if entity.strip()
)

ENTITY_TO_TOPIC = {
    "sensor.pws_outdoor_temperature": "ha_bridge/atlas/temperature_c",
    "sensor.humidex": "ha_bridge/derived/humidex",
    "sensor.wind_chill": "ha_bridge/derived/wind_chill_c",
    "sensor.pws_outdoor_humidity": "ha_bridge/atlas/humidity_pct",
    "sensor.ihome_wind_speed": "ha_bridge/atlas/wind_speed_kmh",
    "sensor.wind_gust_average": "ha_bridge/atlas/wind_gust_kmh",
    "sensor.daily_rain": "ha_bridge/atlas/rain_total",
    "sensor.rain_5_minute_delta": "ha_bridge/atlas/rain_rate",
    "sensor.fredericton_barometric_pressure": "ha_bridge/fredericton/pressure_hpa",
}

ENTITY_MULTIPLIERS = {
    # Convert a five-minute accumulation to an hourly rate.
    "sensor.rain_5_minute_delta": 12.0,
}

INVALID_STATES = {"unavailable", "unknown", None}


def mqtt_payload_for_state(state):
    if state in INVALID_STATES:
        return json.dumps({"value": None, "state": "unavailable"})
    return state


def publish_state(mqtt_client, entity_id, state):
    topic = ENTITY_TO_TOPIC[entity_id]
    payload = mqtt_payload_for_state(state)
    if state not in INVALID_STATES and entity_id in ENTITY_MULTIPLIERS:
        try:
            payload = str(float(state) * ENTITY_MULTIPLIERS[entity_id])
        except (TypeError, ValueError):
            payload = mqtt_payload_for_state(None)
    mqtt_client.publish(topic, payload, retain=True)


def publish_forecast_summary(mqtt_client, response):
    summary = summarize_hourly_forecasts(response)
    for field, value in summary.items():
        mqtt_client.publish(
            f"ha_bridge/forecast/{field.removeprefix('forecast_')}",
            json.dumps({"value": value}),
            retain=True,
        )
    return summary

def setup_mqtt():
    client = mqtt.Client(client_id="ha_bridge_service", protocol=mqtt.MQTTv5)
    if MQTT_USER and MQTT_PASS:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    return client

async def ha_ws_loop(mqtt_client):
    while True:
        try:
            async with websockets.connect(HA_WS, max_size=10*1024*1024) as ws:
                # 1. Wait for auth_required
                await ws.recv()
                # 2. Send auth
                await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
                auth_resp = json.loads(await ws.recv())
                if auth_resp.get("type") != "auth_ok":
                    LOGGER.error("HA Auth failed: %s", auth_resp)
                    await asyncio.sleep(10)
                    continue
                LOGGER.info("Connected to Home Assistant WebSocket")

                # 3. Subscribe to state changes
                await ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
                
                # Fetch initial states to prime the pump
                await ws.send(json.dumps({"id": 2, "type": "get_states"}))

                request_id = 2
                pending_forecasts = set()

                async def request_forecasts():
                    nonlocal request_id
                    request_id += 1
                    pending_forecasts.add(request_id)
                    await ws.send(json.dumps({
                        "id": request_id,
                        "type": "call_service",
                        "domain": "weather",
                        "service": "get_forecasts",
                        "service_data": {"type": "hourly"},
                        "target": {"entity_id": list(WEATHER_ENTITIES)},
                        "return_response": True,
                    }))

                await request_forecasts()

                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=900)
                    except asyncio.TimeoutError:
                        await request_forecasts()
                        continue
                    msg = json.loads(raw)
                    if msg.get("id") == 2 and msg.get("type") == "result":
                        states = msg.get("result", [])
                        seen_entities = set()
                        for s in states:
                            eid = s.get("entity_id")
                            if eid in ENTITY_TO_TOPIC:
                                seen_entities.add(eid)
                                val = s.get("state")
                                try:
                                    publish_state(mqtt_client, eid, val)
                                    LOGGER.info("Initial state %s: %s", eid, val)
                                except Exception as e:
                                    LOGGER.error("Error publishing initial state: %s", e)
                        for eid in set(ENTITY_TO_TOPIC) - seen_entities:
                            try:
                                publish_state(mqtt_client, eid, None)
                                LOGGER.warning("Entity %s missing from HA state list; cleared %s", eid, ENTITY_TO_TOPIC[eid])
                            except Exception as e:
                                LOGGER.error("Error clearing missing entity state: %s", e)

                    elif msg.get("id") in pending_forecasts and msg.get("type") == "result":
                        pending_forecasts.discard(msg.get("id"))
                        result = msg.get("result", {}) or {}
                        response = result.get("response", {}) if isinstance(result, dict) else {}
                        summary = publish_forecast_summary(mqtt_client, response)
                        LOGGER.info("Published hourly forecast summary: %s", summary)

                    elif msg.get("type") == "event" and msg.get("event", {}).get("event_type") == "state_changed":
                        event_data = msg["event"]["data"]
                        eid = event_data.get("entity_id")
                        if eid in WEATHER_ENTITIES:
                            await request_forecasts()
                        if eid in ENTITY_TO_TOPIC:
                            new_state = event_data.get("new_state", {}).get("state")
                            try:
                                publish_state(mqtt_client, eid, new_state)
                                LOGGER.info("State changed %s: %s", eid, new_state)
                            except Exception as e:
                                LOGGER.error("Error publishing state change: %s", e)

        except websockets.exceptions.ConnectionClosed:
            LOGGER.warning("HA WebSocket closed. Reconnecting...")
            await asyncio.sleep(5)
        except Exception as e:
            LOGGER.error("HA WebSocket error: %s", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    mqtt_client = setup_mqtt()
    try:
        asyncio.run(ha_ws_loop(mqtt_client))
    except KeyboardInterrupt:
        pass
    finally:
        mqtt_client.loop_stop()
