Exit code: 0
Wall time: 0.6 seconds
Output:
import asyncio
import json
import logging
import os
import time
import paho.mqtt.client as mqtt
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
LOGGER = logging.getLogger(__name__)

HA_WS = os.environ.get("HA_WS_URL", "ws://homeassistant.local:8123/api/websocket")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USERNAME", "")
MQTT_PASS = os.environ.get("MQTT_PASSWORD", "")
LIGHTNING_ACTIVE_SECONDS = int(os.environ.get("LIGHTNING_ACTIVE_SECONDS", "1800"))

LIGHTNING_DISTANCE_ENTITY = "sensor.lightning_detector_storm_distance"
LIGHTNING_COUNT_ENTITY = "sensor.lightning_detector_total_strikes"
LIGHTNING_DISTANCE_TOPIC = "lightning/local/distance_km"

# NOTE on this mapping (2026-07-05 accuracy audit):
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
    "sensor.fredericton_barometric_pressure": "ha_bridge/fredericton/pressure_hpa",
    "sensor.fredericton_wind_gust": "ha_bridge/atlas/wind_gust_kmh",
    "sensor.rain_5_minute_delta": "ha_bridge/atlas/rain_rate",  # transformed below (x12 -> mm/h)
    "sensor.fredericton_current_condition": "radar/nearby/precip",  # transformed (text -> 0/1)
}

# Transform applied to a raw HA state value before publishing, keyed by target topic.
# Anything not listed here is forwarded as-is (original behavior).
RAIN_CONDITION_KEYWORDS = ("rain", "shower", "drizzle", "snow", "thunder", "storm", "flurr")


def _transform_rain_rate(raw_value: str) -> str:
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


def apply_transform(topic: str, raw_value: str) -> str | None:
    transform = TOPIC_TRANSFORMS.get(topic)
    if transform is None:
        return raw_value
    try:
        return transform(raw_value)
    except (TypeError, ValueError) as exc:
        LOGGER.warning("Transform failed for %s value=%r: %s", topic, raw_value, exc)
        return None


def setup_mqtt():
    client = mqtt.Client(client_id="ha_bridge_service", protocol=mqtt.MQTTv5)
    if MQTT_USER and MQTT_PASS:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    return client


def publish_value(mqtt_client, topic: str, val: str) -> None:
    transformed = apply_transform(topic, val)
    if transformed is None:
        return
    mqtt_client.publish(topic, transformed, retain=True)
    LOGGER.info("Published %s: %s (raw=%s)", topic, transformed, val)


class LightningActivityTracker:
    """Turn the detector's retained last distance into a time-bounded signal.

    The Acurite distance entity keeps the distance of the last strike indefinitely.
    Only an increment of its cumulative strike counter proves a new strike occurred.
    """

    def __init__(self, active_seconds: int = LIGHTNING_ACTIVE_SECONDS) -> None:
        self.active_seconds = active_seconds
        self.last_count: int | None = None
        self.last_distance_mi: str | None = None
        self.active_until = 0.0

    def prime(self, count: str | None, distance_mi: str | None) -> None:
        self.last_count = self._parse_count(count)
        self.last_distance_mi = self._valid_distance(distance_mi)

    def observe(self, entity_id: str, value: str | None, now: float | None = None) -> str | None:
        if entity_id == LIGHTNING_DISTANCE_ENTITY:
            self.last_distance_mi = self._valid_distance(value)
            return None
        if entity_id != LIGHTNING_COUNT_ENTITY:
            return None

        new_count = self._parse_count(value)
        previous_count = self.last_count
        self.last_count = new_count
        if new_count is None or previous_count is None or new_count <= previous_count:
            return None
        if self.last_distance_mi is None:
            LOGGER.warning("New lightning strike count received without a valid distance")
            return None

        self.active_until = (now if now is not None else time.monotonic()) + self.active_seconds
        return self.last_distance_mi

    def expired(self, now: float | None = None) -> bool:
        current = now if now is not None else time.monotonic()
        if self.active_until and current >= self.active_until:
            self.active_until = 0.0
            return True
        return False

    @staticmethod
    def _parse_count(value: str | None) -> int | None:
        try:
            return int(float(value)) if value not in (None, "unknown", "unavailable") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _valid_distance(value: str | None) -> str | None:
        try:
            return str(float(value)) if value not in (None, "unknown", "unavailable") else None
        except (TypeError, ValueError):
            return None


def clear_lightning_signal(mqtt_client) -> None:
    mqtt_client.publish(LIGHTNING_DISTANCE_TOPIC, "", retain=True)
    LOGGER.info("Cleared inactive lightning distance signal")


async def ha_ws_loop(mqtt_client):
    lightning = LightningActivityTracker()
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
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    except asyncio.TimeoutError:
                        if lightning.expired():
                            clear_lightning_signal(mqtt_client)
                        continue
                    if lightning.expired():
                        clear_lightning_signal(mqtt_client)
                    if msg.get("id") == 2 and msg.get("type") == "result":
                        states = msg.get("result", [])
                        state_by_entity = {s.get("entity_id"): s.get("state") for s in states}
                        lightning.prime(
                            state_by_entity.get(LIGHTNING_COUNT_ENTITY),
                            state_by_entity.get(LIGHTNING_DISTANCE_ENTITY),
                        )
                        # A startup snapshot cannot prove the retained distance is recent.
                        clear_lightning_signal(mqtt_client)
                        for s in states:
                            eid = s.get("entity_id")
                            if eid in ENTITY_TO_TOPIC:
                                val = s.get("state")
                                try:
                                    if val not in ("unavailable", "unknown"):
                                        publish_value(mqtt_client, ENTITY_TO_TOPIC[eid], val)
                                except Exception as e:
                                    LOGGER.error("Error publishing initial state: %s", e)

                    elif msg.get("type") == "event" and msg.get("event", {}).get("event_type") == "state_changed":
                        event_data = msg["event"]["data"]
                        eid = event_data.get("entity_id")
                        new_state = event_data.get("new_state", {}).get("state")
                        lightning_distance = lightning.observe(eid, new_state)
                        if lightning_distance is not None:
                            publish_value(mqtt_client, LIGHTNING_DISTANCE_TOPIC, lightning_distance)
                        if eid in ENTITY_TO_TOPIC:
                            try:
                                if new_state not in ("unavailable", "unknown"):
                                    publish_value(mqtt_client, ENTITY_TO_TOPIC[eid], new_state)
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

