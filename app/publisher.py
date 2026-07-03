from __future__ import annotations

import json
from typing import Any

from app.config import MqttSettings
from app.mqtt_client import WeatherMqttClient
from app.models import Prediction


def publish_discovery(client: WeatherMqttClient, settings: MqttSettings) -> None:
    sensors = {
        "storm_risk_1h": {"name": "Weather Brain Storm Risk 1h", "unit": "%", "icon": "mdi:weather-lightning-rainy"},
        "storm_risk_24h": {"name": "Weather Brain Storm Risk 24h", "unit": "%", "icon": "mdi:weather-partly-lightning"},
        "wind_risk_1h": {"name": "Weather Brain Wind Risk 1h", "unit": "%", "icon": "mdi:weather-windy"},
        "rain_risk_1h": {"name": "Weather Brain Rain Risk 1h", "unit": "%", "icon": "mdi:weather-pouring"},
        "lightning_risk_1h": {"name": "Weather Brain Lightning Risk 1h", "unit": "%", "icon": "mdi:weather-lightning"},
        "confidence": {"name": "Weather Brain Confidence", "unit": "%", "icon": "mdi:brain"},
    }

    for key, meta in sensors.items():
        topic = f"{settings.discovery_prefix}/sensor/weather_brain/{key}/config"
        payload: dict[str, Any] = {
            "name": meta["name"],
            "unique_id": f"weather_brain_{key}",
            "state_topic": settings.state_topic,
            "availability_topic": settings.availability_topic,
            "value_template": f"{{{{ value_json.{key} }}}}",
            "unit_of_measurement": meta["unit"],
            "icon": meta["icon"],
            "state_class": "measurement",
            "device": _device_payload(),
        }
        client.publish_text(topic, json.dumps(payload), retain=True)

    text_sensors = {
        "level": {"name": "Weather Brain Alert Level", "icon": "mdi:alert"},
        "explanation": {"name": "Weather Brain Explanation", "icon": "mdi:text-box-search"},
    }
    for key, meta in text_sensors.items():
        topic = f"{settings.discovery_prefix}/sensor/weather_brain/{key}/config"
        payload = {
            "name": meta["name"],
            "unique_id": f"weather_brain_{key}",
            "state_topic": settings.state_topic,
            "availability_topic": settings.availability_topic,
            "value_template": f"{{{{ value_json.{key} }}}}",
            "icon": meta["icon"],
            "device": _device_payload(),
        }
        client.publish_text(topic, json.dumps(payload), retain=True)


def publish_prediction(client: WeatherMqttClient, settings: MqttSettings, prediction: Prediction) -> None:
    client.publish_json(settings.state_topic, prediction.as_dict(), retain=True)


def _device_payload() -> dict[str, str]:
    return {
        "identifiers": "kcr_weather_brain",
        "name": "KCR Weather Brain",
        "manufacturer": "Kingsclear Studios",
        "model": "Local MQTT Weather Intelligence Sidecar",
    }
