from __future__ import annotations

import json

from app import ha_bridge


class FakeMqttClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, bool]] = []

    def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        self.messages.append((topic, payload, retain))


def test_wind_gust_bridge_uses_live_eccc_gust_sensor() -> None:
    # 2026-07-05 audit: the Atlas station has no gust entity; ECCC METAR gust
    # is the closest real one. The nonexistent Atlas gust must stay unmapped.
    assert ha_bridge.ENTITY_TO_TOPIC["sensor.fredericton_wind_gust"] == "ha_bridge/atlas/wind_gust_kmh"
    assert "sensor.ihome_atlas_wind_gust" not in ha_bridge.ENTITY_TO_TOPIC


def test_bridge_uses_validated_atlas_and_rain_entities() -> None:
    assert ha_bridge.ENTITY_TO_TOPIC["sensor.ihome_atlas_temperature"] == "ha_bridge/atlas/temperature_c"
    assert ha_bridge.ENTITY_TO_TOPIC["sensor.rain_5_minute_delta"] == "ha_bridge/atlas/rain_rate"


def test_lightning_distance_is_converted_from_miles() -> None:
    client = FakeMqttClient()
    ha_bridge.publish_state(client, "sensor.lightning_detector_storm_distance", "10")
    topic, payload, retain = client.messages[0]
    assert topic == "lightning/local/distance_km"
    assert abs(float(payload) - 16.0934) < 1e-6
    assert retain


def test_condition_text_maps_to_precip_flag() -> None:
    client = FakeMqttClient()
    ha_bridge.publish_state(client, "sensor.fredericton_current_condition", "Light Rainshower")
    assert client.messages == [("radar/nearby/precip", "1", True)]
    client2 = FakeMqttClient()
    ha_bridge.publish_state(client2, "sensor.fredericton_current_condition", "Sunny")
    assert client2.messages == [("radar/nearby/precip", "0", True)]


def test_rain_delta_is_converted_to_hourly_rate() -> None:
    client = FakeMqttClient()
    ha_bridge.publish_state(client, "sensor.rain_5_minute_delta", "2")
    assert client.messages == [("ha_bridge/atlas/rain_rate", "24.0", True)]


def test_thermal_bridge_uses_live_derived_sensors() -> None:
    assert ha_bridge.ENTITY_TO_TOPIC["sensor.humidex"] == "ha_bridge/derived/humidex"
    assert ha_bridge.ENTITY_TO_TOPIC["sensor.wind_chill"] == "ha_bridge/derived/wind_chill_c"


def test_publish_state_clears_unavailable_retained_value() -> None:
    client = FakeMqttClient()

    ha_bridge.publish_state(client, "sensor.fredericton_wind_gust", "unknown")

    assert client.messages == [
        ("ha_bridge/atlas/wind_gust_kmh", json.dumps({"value": None, "state": "unavailable"}), True)
    ]
