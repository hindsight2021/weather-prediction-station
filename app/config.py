from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MqttSettings:
    host: str
    port: int
    username: str | None
    password: str | None
    client_id: str
    discovery_prefix: str
    state_topic: str
    availability_topic: str


@dataclass(frozen=True)
class RuntimeSettings:
    publish_interval_seconds: int
    snapshot_history_limit: int
    write_snapshots_jsonl: bool
    snapshot_path: str
    write_predictions_jsonl: bool
    predictions_path: str


@dataclass(frozen=True)
class AppConfig:
    mqtt: MqttSettings
    input_topics: dict[str, str]
    risk_thresholds: dict[str, float]
    runtime: RuntimeSettings


def load_config() -> AppConfig:
    config_path = Path(os.environ.get("CONFIG_PATH", "/app/config/weather_brain.yaml"))
    with config_path.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle)

    mqtt_raw = raw.get("mqtt", {})
    runtime_raw = raw.get("runtime", {})

    mqtt = MqttSettings(
        host=os.environ.get("MQTT_HOST", mqtt_raw.get("host", "localhost")),
        port=int(os.environ.get("MQTT_PORT", mqtt_raw.get("port", 1883))),
        username=os.environ.get("MQTT_USERNAME") or mqtt_raw.get("username"),
        password=os.environ.get("MQTT_PASSWORD") or mqtt_raw.get("password"),
        client_id=mqtt_raw.get("client_id", "kcr-weather-brain"),
        discovery_prefix=mqtt_raw.get("discovery_prefix", "homeassistant"),
        state_topic=mqtt_raw.get("state_topic", "weather_brain/prediction/state"),
        availability_topic=mqtt_raw.get("availability_topic", "weather_brain/status"),
    )

    runtime = RuntimeSettings(
        publish_interval_seconds=int(runtime_raw.get("publish_interval_seconds", 300)),
        snapshot_history_limit=int(runtime_raw.get("snapshot_history_limit", 2016)),
        write_snapshots_jsonl=bool(runtime_raw.get("write_snapshots_jsonl", True)),
        snapshot_path=runtime_raw.get("snapshot_path", "/app/data/weather_snapshots.jsonl"),
        write_predictions_jsonl=bool(runtime_raw.get("write_predictions_jsonl", True)),
        predictions_path=runtime_raw.get("predictions_path", "/app/data/predictions.jsonl"),
    )

    return AppConfig(
        mqtt=mqtt,
        input_topics=dict(raw.get("input_topics", {})),
        risk_thresholds={k: float(v) for k, v in raw.get("risk_thresholds", {}).items()},
        runtime=runtime,
    )
