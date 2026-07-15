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
STARTUP_GRACE_SECONDS = float(os.environ.get("STARTUP_GRACE_SECONDS", "5"))
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
LOGGER = logging.getLogger(__name__)


def parse_float(payload: str) -> float | None:
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            for key in ("value", "state", "pressure", "temperature", "humidity", "distance", "count"):
                if key in parsed:
                    value = parsed[key]
                    if value in (None, "unavailable", "unknown", ""):
                        return None
                    return float(value)
            return None
        if parsed is None:
            return None
        return float(parsed)
    except (ValueError, TypeError, json.JSONDecodeError):
        LOGGER.warning("Could not parse numeric MQTT payload: %s", payload)
        return None


from inference.ml_predictor import MLPredictor

# Base scores per predicted thermal severity class, aligned with the
# recalibrated rule scale where score >= 65 means ECCC warning criteria met
# or imminent (roadmap §4.6).
THERMAL_SEVERITY = {
    0: ("none", 0),
    1: ("mild", 35),
    2: ("moderate", 65),
    3: ("severe", 90),
}


def apply_multiclass_thermal_prediction(prediction, model_result, risk_attr: str, severity_attr: str, label: str) -> None:
    if not isinstance(model_result, dict):
        return
    severity_class = int(model_result.get("class", 0))
    severity, base_score = THERMAL_SEVERITY.get(severity_class, THERMAL_SEVERITY[0])
    probability = float(model_result.get("probability", 0.0))
    if severity == "none":
        return
    current_score = getattr(prediction, risk_attr)
    setattr(prediction, risk_attr, max(current_score, min(100, int(round(base_score + probability * 10)))))
    setattr(prediction, severity_attr, severity)
    prediction.explanation += f" (ML {label}: {severity})"

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
        if topic == "ha_bridge/feedback/weather_brain":
            try:
                feedback = json.loads(payload)
                LOGGER.info(f"Received feedback: {feedback}")
                if feedback.get("label") not in ("none", "", None):
                    import threading
                    def autonomous_retrain():
                        LOGGER.info("Starting autonomous retraining sequence on Pi...")
                        try:
                            # 1. Save feedback event to a dataset. hazard and
                            # severity let training apply the label to that
                            # hazard's target only (roadmap §4.2).
                            feedback_file = Path("data/processed/feedback_dataset.csv")
                            is_new = not feedback_file.exists()
                            with feedback_file.open("a", encoding="utf-8") as f:
                                if is_new:
                                    f.write("timestamp,label,hazard,severity,notes\n")
                                f.write(
                                    f"{feedback['timestamp']},{feedback['label']},"
                                    f"{feedback.get('hazard', '')},{feedback.get('severity', '')},"
                                    f"\"{feedback.get('notes', '')}\"\n"
                                )

                            # 2. Run the training script (it will load the feedback dataset in the future)
                            import subprocess
                            subprocess.run(["python", "-m", "training.train_models"], check=True)
                            
                            # 3. Reload the predictor models live
                            predictor._load_models()
                            LOGGER.info("Autonomous retraining complete. New models loaded live.")
                        except Exception as e:
                            LOGGER.error(f"Autonomous retraining failed: {e}")
                    
                    threading.Thread(target=autonomous_retrain, daemon=True).start()
            except json.JSONDecodeError:
                pass
            return
            
        field = topic_to_field.get(topic)
        if not field:
            return
        current_values[field] = parse_float(payload)

    topics_to_subscribe = list(topic_to_field) + ["ha_bridge/feedback/weather_brain"]
    mqtt_client.connect(on_message=on_message, topics=topics_to_subscribe)
    publish_discovery(mqtt_client, config.mqtt)
    if STARTUP_GRACE_SECONDS > 0:
        LOGGER.info("Waiting %.1f seconds for retained MQTT inputs", STARTUP_GRACE_SECONDS)
        time.sleep(STARTUP_GRACE_SECONDS)

    last_publish = 0.0
    try:
        while running:
            now = time.time()
            if now - last_publish >= config.runtime.publish_interval_seconds:
                snapshot = WeatherSnapshot(timestamp=datetime.now(timezone.utc), **current_values)
                store.add(snapshot)
                maybe_write_snapshot(config.runtime.snapshot_path, snapshot, config.runtime.write_snapshots_jsonl)
                ml_result = predictor.predict(snapshot, store)
                ml_probs = ml_result.probabilities
                prediction = score_weather(snapshot, store, config.risk_thresholds)

                if ml_result.degraded:
                    # Some models were skipped for missing/unimputable inputs;
                    # don't let the published confidence claim otherwise.
                    prediction.confidence = min(prediction.confidence, 60)
                    prediction.explanation += (
                        f" (ML degraded: skipped {', '.join(ml_result.skipped_models)})"
                    )
                if ml_probs:
                    LOGGER.info(f"ML Model Probabilities: {ml_probs}")
                    # Blend the ML predictions into the rule-based prediction
                    if "convective_risk" in ml_probs and ml_probs["convective_risk"] > 0.5:
                        prediction.storm_risk_1h = max(prediction.storm_risk_1h, int(ml_probs["convective_risk"] * 100))
                        prediction.explanation += " (Enhanced by ML Convective Model)"
                    if "wind_1h" in ml_probs and ml_probs["wind_1h"] > 0.5:
                        prediction.wind_risk_1h = max(prediction.wind_risk_1h, int(ml_probs["wind_1h"] * 100))
                        prediction.explanation += " (Enhanced by ML Wind Model)"
                    if "storm_24h" in ml_probs and isinstance(ml_probs["storm_24h"], float):
                        prediction.storm_risk_24h = max(
                            prediction.storm_risk_24h, int(ml_probs["storm_24h"] * 100)
                        )
                        prediction.explanation += " (Enhanced by ML 24h Storm Model)"
                    apply_multiclass_thermal_prediction(
                        prediction, ml_probs.get("heat_disturbance_24h"), "heat_risk_24h", "heat_severity", "heat"
                    )
                    apply_multiclass_thermal_prediction(
                        prediction, ml_probs.get("cold_disturbance_24h"), "cold_risk_24h", "cold_severity", "cold"
                    )
                
                publish_prediction(
                    mqtt_client,
                    config.mqtt,
                    prediction,
                    log_path=config.runtime.predictions_path
                    if config.runtime.write_predictions_jsonl
                    else None,
                )
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
