from __future__ import annotations

import json

from app import ha_bridge


class FakeMqttClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, bool]] = []

    def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        self.messages.append((topic, payload, retain))


def test_wind_gust_bridge_uses_live_average_gust_sensor() -> None:
    assert ha_bridge.ENTITY_TO_TOPIC["sensor.wind_gust_average"] == "ha_bridge/atlas/wind_gust_kmh"
    assert "sensor.ihome_atlas_wind_gust" not in ha_bridge.ENTITY_TO_TOPIC


def test_thermal_bridge_uses_live_derived_sensors() -> None:
    assert ha_bridge.ENTITY_TO_TOPIC["sensor.humidex"] == "ha_bridge/derived/humidex"
    assert ha_bridge.ENTITY_TO_TOPIC["sensor.wind_chill"] == "ha_bridge/derived/wind_chill_c"


def test_publish_state_clears_unavailable_retained_value() -> None:
    client = FakeMqttClient()

    ha_bridge.publish_state(client, "sensor.wind_gust_average", "unknown")

    assert client.messages == [
        ("ha_bridge/atlas/wind_gust_kmh", json.dumps({"value": None, "state": "unavailable"}), True)
    ]
