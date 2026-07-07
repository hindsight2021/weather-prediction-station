from __future__ import annotations

import json

from app.config import MqttSettings
from app.models import Prediction
from app.publisher import publish_discovery, publish_prediction


class FakeMqttClient:
    def __init__(self) -> None:
        self.text_messages: list[tuple[str, str, bool]] = []
        self.json_messages: list[tuple[str, dict[str, object], bool]] = []

    def publish_text(self, topic: str, payload: str, retain: bool = False) -> None:
        self.text_messages.append((topic, payload, retain))

    def publish_json(self, topic: str, payload: dict[str, object], retain: bool = False) -> None:
        self.json_messages.append((topic, payload, retain))


def settings() -> MqttSettings:
    return MqttSettings(
        host="localhost",
        port=1883,
        username=None,
        password=None,
        client_id="test-weather-brain",
        discovery_prefix="homeassistant",
        state_topic="weather_brain/prediction/state",
        availability_topic="weather_brain/status",
    )


def test_publish_discovery_creates_numeric_and_text_sensors() -> None:
    client = FakeMqttClient()

    publish_discovery(client, settings())  # type: ignore[arg-type]

    topics = {topic for topic, _payload, _retain in client.text_messages}
    assert "homeassistant/sensor/weather_brain/storm_risk_1h/config" in topics
    assert "homeassistant/sensor/weather_brain/heat_risk_24h/config" in topics
    assert "homeassistant/sensor/weather_brain/cold_severity/config" in topics
    assert "homeassistant/sensor/weather_brain/explanation/config" in topics
    assert len(client.text_messages) == 12

    storm_payload = next(
        json.loads(payload)
        for topic, payload, _retain in client.text_messages
        if topic.endswith("storm_risk_1h/config")
    )
    assert storm_payload["state_topic"] == "weather_brain/prediction/state"
    assert storm_payload["state_class"] == "measurement"
    assert storm_payload["unique_id"] == "weather_brain_storm_risk_1h"


def test_publish_prediction_uses_state_topic_and_retains_payload() -> None:
    client = FakeMqttClient()
    prediction = Prediction(
        storm_risk_1h=72,
        storm_risk_24h=61,
        wind_risk_1h=44,
        rain_risk_1h=58,
        lightning_risk_1h=80,
        confidence=76,
        level="watch",
        explanation="test explanation",
        heat_risk_24h=70,
        heat_severity="moderate",
    )

    publish_prediction(client, settings(), prediction)  # type: ignore[arg-type]

    assert client.json_messages == [("weather_brain/prediction/state", prediction.as_dict(), True)]
