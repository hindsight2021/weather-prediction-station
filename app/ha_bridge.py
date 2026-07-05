import asyncio
import json
import logging
import os
import paho.mqtt.client as mqtt
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
LOGGER = logging.getLogger(__name__)

HA_WS = os.environ.get("HA_WS_URL", "ws://192.168.1.105:8123/api/websocket")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

MQTT_HOST = os.environ.get("MQTT_HOST", "192.168.1.105")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USERNAME", "mosquitto")
MQTT_PASS = os.environ.get("MQTT_PASSWORD", "rodeo101")

ENTITY_TO_TOPIC = {
    "sensor.ihome_atlas_temperature": "ha_bridge/atlas/temperature_c",
    "sensor.ihome_atlas_humidity": "ha_bridge/atlas/humidity_pct",
    "sensor.ihome_atlas_wind_speed": "ha_bridge/atlas/wind_speed_kmh",
    "sensor.ihome_atlas_wind_direction": "ha_bridge/atlas/wind_direction",
    "sensor.ihome_atlas_wind_gust": "ha_bridge/atlas/wind_gust_kmh",
    "sensor.ihome_atlas_rain_total": "ha_bridge/atlas/rain_total",
    "sensor.ihome_atlas_rain_rate": "ha_bridge/atlas/rain_rate",
    "sensor.fredericton_barometric_pressure": "ha_bridge/fredericton/pressure_hpa",
}

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

                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == 2 and msg.get("type") == "result":
                        states = msg.get("result", [])
                        for s in states:
                            eid = s.get("entity_id")
                            if eid in ENTITY_TO_TOPIC:
                                val = s.get("state")
                                try:
                                    if val not in ("unavailable", "unknown"):
                                        mqtt_client.publish(ENTITY_TO_TOPIC[eid], val, retain=True)
                                        LOGGER.info("Initial state %s: %s", eid, val)
                                except Exception as e:
                                    LOGGER.error("Error publishing initial state: %s", e)

                    elif msg.get("type") == "event" and msg.get("event", {}).get("event_type") == "state_changed":
                        event_data = msg["event"]["data"]
                        eid = event_data.get("entity_id")
                        if eid in ENTITY_TO_TOPIC:
                            new_state = event_data.get("new_state", {}).get("state")
                            try:
                                if new_state not in ("unavailable", "unknown"):
                                    mqtt_client.publish(ENTITY_TO_TOPIC[eid], new_state, retain=True)
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
