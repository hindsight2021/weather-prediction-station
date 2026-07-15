from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
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
        "rain_risk_24h": {"name": "Weather Brain Rain Risk 24h", "unit": "%", "icon": "mdi:weather-rainy"},
        "wind_risk_24h": {"name": "Weather Brain Wind Risk 24h", "unit": "%", "icon": "mdi:weather-windy-variant"},
        "lightning_risk_1h": {"name": "Weather Brain Lightning Risk 1h", "unit": "%", "icon": "mdi:weather-lightning"},
        "heat_risk_24h": {"name": "Weather Brain Heat Risk 24h", "unit": "%", "icon": "mdi:thermometer-alert"},
        "cold_risk_24h": {"name": "Weather Brain Cold Risk 24h", "unit": "%", "icon": "mdi:snowflake-alert"},
        "confidence": {"name": "Weather Brain Confidence", "unit": "%", "icon": "mdi:brain"},
        "storm_risk_48h": {"name": "Weather Brain Storm Risk 48h", "unit": "%", "icon": "mdi:weather-lightning"},
        "storm_risk_72h": {"name": "Weather Brain Storm Risk 72h", "unit": "%", "icon": "mdi:weather-lightning"},
        "air_quality_risk_24h": {"name": "Weather Brain Air Quality Risk 24h", "unit": "%", "icon": "mdi:air-filter"},
        "air_quality_risk_48h": {"name": "Weather Brain Air Quality Risk 48h", "unit": "%", "icon": "mdi:air-filter"},
        "smoke_risk_24h": {"name": "Weather Brain Wildfire Smoke Risk", "unit": "%", "icon": "mdi:smoke"},
        "aqhi_current": {"name": "Weather Brain AQHI Current", "unit": "AQHI", "icon": "mdi:air-filter"},
        "aqhi_forecast_max_24h": {"name": "Weather Brain AQHI Forecast 24h", "unit": "AQHI", "icon": "mdi:air-filter"},
        "active_fires_nearby": {"name": "Weather Brain Active Fires Within 150 km", "unit": "fires", "icon": "mdi:fire-alert"},
    }

    for key, meta in sensors.items():
        topic = f"{settings.discovery_prefix}/sensor/weather_brain/{key}/config"
        payload: dict[str, Any] = {
            "name": meta["name"],
            "unique_id": f"weather_brain_{key}",
            "default_entity_id": f"sensor.weather_brain_{key}",
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
        "heat_severity": {"name": "Weather Brain Heat Severity", "icon": "mdi:thermometer-lines"},
        "cold_severity": {"name": "Weather Brain Cold Severity", "icon": "mdi:snowflake-thermometer"},
        "imminent_event": {"name": "Weather Brain Imminent Event", "icon": "mdi:alert-decagram"},
        "imminent_summary": {"name": "Weather Brain Imminent Summary", "icon": "mdi:timeline-alert"},
        "official_alert_level": {"name": "Weather Brain ECCC Alert Level", "icon": "mdi:shield-alert"},
        "official_alert_summary": {"name": "Weather Brain ECCC Alert", "icon": "mdi:alert-box"},
        "nb_burn_status": {"name": "Weather Brain York County Burn Status", "icon": "mdi:campfire"},
    }
    for key, meta in text_sensors.items():
        topic = f"{settings.discovery_prefix}/sensor/weather_brain/{key}/config"
        payload = {
            "name": meta["name"],
            "unique_id": f"weather_brain_{key}",
            "default_entity_id": f"sensor.weather_brain_{key}",
            "state_topic": settings.state_topic,
            "availability_topic": settings.availability_topic,
            "value_template": f"{{{{ value_json.{key} }}}}",
            "icon": meta["icon"],
            "device": _device_payload(),
        }
        client.publish_text(topic, json.dumps(payload), retain=True)

    # Daily AI long-range forecast: filed to its own retained topic by the
    # scheduled analyst run. State = generated_at timestamp; the full 24-72h
    # text rides in attributes (HA states are capped at 255 chars).
    topic = f"{settings.discovery_prefix}/sensor/weather_brain/ai_forecast/config"
    payload = {
        "name": "Weather Brain AI Long-Range Forecast",
        "unique_id": "weather_brain_ai_forecast",
        "default_entity_id": "sensor.weather_brain_ai_forecast",
        "state_topic": "weather_brain/ai_forecast/state",
        "value_template": "{{ value_json.generated_at }}",
        "json_attributes_topic": "weather_brain/ai_forecast/state",
        "device_class": "timestamp",
        "icon": "mdi:crystal-ball",
        "device": _device_payload(),
    }
    client.publish_text(topic, json.dumps(payload), retain=True)

    topic = f"{settings.discovery_prefix}/sensor/weather_brain/imminent_minutes/config"
    payload = {
        "name": "Weather Brain Imminent Event ETA",
        "unique_id": "weather_brain_imminent_minutes",
        "default_entity_id": "sensor.weather_brain_imminent_event_eta",
        "state_topic": settings.state_topic,
        "availability_topic": settings.availability_topic,
        "value_template": "{{ value_json.imminent_minutes }}",
        "unit_of_measurement": "min",
        "icon": "mdi:timer-alert",
        "state_class": "measurement",
        "device": _device_payload(),
    }
    client.publish_text(topic, json.dumps(payload), retain=True)


def publish_prediction(
    client: WeatherMqttClient,
    settings: MqttSettings,
    prediction: Prediction,
    log_path: str | None = None,
) -> None:
    client.publish_json(settings.state_topic, prediction.as_dict(), retain=True)
    if log_path:
        log_prediction(prediction, log_path)


def log_prediction(prediction: Prediction, log_path: str) -> None:
    """Append the published prediction to the verification log (roadmap §3.2)."""
    record: dict[str, Any] = {"timestamp": datetime.now(timezone.utc).isoformat()}
    record.update(prediction.as_dict())
    target = Path(log_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _device_payload() -> dict[str, str]:
    return {
        "identifiers": "kcr_weather_brain",
        "name": "KCR Weather Brain",
        "manufacturer": "Kingsclear Studios",
        "model": "Local MQTT Weather Intelligence Sidecar",
    }
