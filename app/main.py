from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import load_config
from app.feature_builder import SnapshotStore
from app.models import WeatherSnapshot
from app.mqtt_client import WeatherMqttClient
from app.publisher import publish_discovery, publish_prediction
from app.risk_rules import score_weather

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
LOGGER = logging.getLogger(__name__)


def parse_float(payload: str) -> float | None:
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            for key in ("value", "state", "pressure", "temperature", "humidity", "distance", "count"):
                if key in parsed:
                    return float(parsed[key])
        return float(parsed)
    except (ValueError, TypeError, json.JSONDecodeError):
        LOGGER.warning("Could not parse numeric MQTT payload: %s", payload)
        return None


from inference.ml_predictor import MLPredictor

def main() -> None:
    config = load_config()
    current_values: dict[str, float | None] = {key: None for key in config.input_topics}
    topic_to_field = {topic: field for field, topic in config.input_topics.items()}
    store = SnapshotStore(maxlen=config.runtime.snapshot_history_limit)
    mqtt_client = WeatherMqttClient(config.mqtt)
    predictor = MLPredictor()
    running = True

    def handle_signal(signum: int, frame: object) -> None:
        nonlocal running
        LOGGER.info("Received signal %s", signum)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    def on_message(topic: str, payload: str) -> None:
        field = topic_to_field.get(topic)
        if not field:
            return
        current_values[field] = parse_float(payload)

    mqtt_client.connect(on_message=on_message, topics=list(topic_to_field))
    publish_discovery(mqtt_client, config.mqtt)

    last_publish = 0.0
    try:
        while running:
            now = time.time()
            if now - last_publish >= config.runtime.publish_interval_seconds:
                snapshot = WeatherSnapshot(timestamp=datetime.now(timezone.utc), **current_values)
                store.add(snapshot)
                maybe_write_snapshot(config.runtime.snapshot_path, snapshot, config.runtime.write_snapshots_jsonl)
                ml_probs = predictor.predict(snapshot, store)
                prediction = score_weather(snapshot, store, config.risk_thresholds)
                
                if ml_probs:
                    LOGGER.info(f"ML Model Probabilities: {ml_probs}")
                    # Blend the ML predictions into the rule-based prediction
                    if "convective_risk" in ml_probs and ml_probs["convective_risk"] > 0.5:
                        prediction.storm_risk_1h = max(prediction.storm_risk_1h, int(ml_probs["convective_risk"] * 100))
                        prediction.explanation += " (Enhanced by ML Convective Model)"
                    if "wind_1h" in ml_probs and ml_probs["wind_1h"] > 0.5:
                        prediction.wind_risk_1h = max(prediction.wind_risk_1h, int(ml_probs["wind_1h"] * 100))
                        prediction.explanation += " (Enhanced by ML Wind Model)"
                
                publish_prediction(mqtt_client, config.mqtt, prediction)
                LOGGER.info("Published prediction: %s", prediction.as_dict())
                last_publish = now
            time.sleep(1)
    finally:
        mqtt_client.stop()


def maybe_write_snapshot(path: str, snapshot: WeatherSnapshot, enabled: bool) -> None:
    if not enabled:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot.as_dict()) + "\n")


if __name__ == "__main__":
    main()
