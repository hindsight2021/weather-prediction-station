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

# NOTE on this mapping (2026-07-05 accuracy audit, done live on the Pi):
#
# sensor.ihome_atlas_wind_gust and sensor.ihome_atlas_rain_rate referenced in the
# original mapping DO NOT EXIST in this Home Assistant instance. The Atlas station
# only exposes instantaneous wind_speed and cumulative rain_total -- no gust, no rate.
# That silently forced wind_risk_1h and rain_risk_1h to 0 forever, regardless of
# actual conditions. Fixed below using the closest real, live entities:
#   - wind gust    -> sensor.fredericton_wind_gust (Environment Canada METAR gust, real km/h)
#   - rain rate    -> sensor.rain_5_minute_delta (mm/5min) x12 -> approx mm/h
#   - lightning    -> sensor.lightning_detector_storm_distance (mi) x1.60934 -> km
#   - radar/precip -> sensor.fredericton_current_condition, text-matched to a 0/1 flag
#                     (EC's observed condition text, NOT true radar reflectivity -- there
#                     is no numeric local radar/precip sensor in this HA instance today)
#
# local_lightning_count_30m / internet_lightning_count_30m are intentionally left
# unmapped. The only "count" sensors available (sensor.lightning_map_lightning_counter,
# sensor.daily_lightning) are cumulative/total_increasing, not 30-minute rolling windows.
# Wiring a monotonic counter into a "_30m" field would make lightning risk ratchet up
# and never come back down -- worse for a safety system than leaving the field null,
# which the risk engine already handles by just not scoring that sub-component.

ENTITY_TO_TOPIC = {
    "sensor.ihome_atlas_temperature": "ha_bridge/atlas/temperature_c",
    "sensor.ihome_atlas_humidity": "ha_bridge/atlas/humidity_pct",
    "sensor.ihome_atlas_wind_speed": "ha_bridge/atlas/wind_speed_kmh",
    "sensor.ihome_atlas_wind_direction": "ha_bridge/atlas/wind_direction",
    "sensor.ihome_atlas_rain_total": "ha_bridge/atlas/rain_total",
    "sensor.humidex": "ha_bridge/derived/humidex",
    "sensor.wind_chill": "ha_bridge/derived/wind_chill_c",
    "sensor.fredericton_barometric_pressure": "ha_bridge/fredericton/pressure_hpa",
    "sensor.fredericton_wind_gust": "ha_bridge/atlas/wind_gust_kmh",
    "sensor.rain_5_minute_delta": "ha_bridge/atlas/rain_rate",  # transformed below (x12 -> mm/h)
    "sensor.lightning_detector_storm_distance": "lightning/local/distance_km",  # transformed (mi -> km)
    "sensor.fredericton_current_condition": "radar/nearby/precip",  # transformed (text -> 0/1)
}

RAIN_CONDITION_KEYWORDS = ("rain", "shower", "drizzle", "snow", "thunder", "storm", "flurr")


def _transform_rain_rate(raw_value: str) -> str:
    # Five-minute accumulation (mm) to an hourly rate (mm/h).
    return str(float(raw_value) * 12.0)


def _transform_lightning_distance(raw_value: str) -> str:
    return str(float(raw_value) * 1.60934)


def _transform_precip_flag(raw_value: str) -> str:
    text = raw_value.lower()
    return "1" if any(keyword in text for keyword in RAIN_CONDITION_KEYWORDS) else "0"


TOPIC_TRANSFORMS = {
    "ha_bridge/atlas/rain_rate": _transform_rain_rate,
    "lightning/local/distance_km": _transform_lightning_distance,
    "radar/nearby/precip": _transform_precip_flag,
}

INVALID_STATES = {"unavailable", "unknown", None}


def mqtt_payload_for_state(state):
    if state in INVALID_STATES:
        return json.dumps({"value": None, "state": "unavailable"})
    return state


def publish_state(mqtt_client, entity_id, state):
    topic = ENTITY_TO_TOPIC[entity_id]
    payload = mqtt_payload_for_state(state)
    transform = TOPIC_TRANSFORMS.get(topic)
    if state not in INVALID_STATES and transform is not None:
        try:
            payload = transform(state)
        except (TypeError, ValueError) as exc:
            LOGGER.warning("Transform failed for %s value=%r: %s", topic, state, exc)
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
