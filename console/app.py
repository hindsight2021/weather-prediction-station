"""Weather command console backend.

Subscribes to the retained Weather Brain MQTT topics and serves a single-page
LCARS console plus a JSON aggregation endpoint. Runs as its own docker-compose
service (`console`) beside the prediction engine; Home Assistant embeds the
page in a dashboard iframe, so this stays same-origin for its own API and
needs no HA credentials.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

LOGGER = logging.getLogger("console")

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USERNAME", "")
MQTT_PASS = os.environ.get("MQTT_PASSWORD", "")
CONSOLE_PORT = int(os.environ.get("CONSOLE_PORT", "8126"))

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
PREDICTIONS_PATH = DATA_DIR / "predictions.jsonl"
SNAPSHOTS_PATH = DATA_DIR / "weather_snapshots.jsonl"
SCOREBOARD_PATH = DATA_DIR / "verification" / "scoreboard.json"

STATIC_DIR = Path(__file__).resolve().parent / "static"

TOPIC_STATE = "weather_brain/prediction/state"
TOPIC_STATUS = "weather_brain/status"
TOPIC_AI_FORECAST = "weather_brain/ai_forecast/state"

app = Flask(__name__, static_folder=None)

_cache: dict[str, object] = {"prediction": None, "availability": "unknown", "ai_forecast": None}
_cache_lock = threading.Lock()


def _on_message(client, userdata, message) -> None:
    payload = message.payload.decode("utf-8", errors="replace")
    with _cache_lock:
        if message.topic == TOPIC_STATE:
            try:
                _cache["prediction"] = json.loads(payload)
            except json.JSONDecodeError:
                LOGGER.warning("Bad prediction payload")
        elif message.topic == TOPIC_STATUS:
            _cache["availability"] = payload
        elif message.topic == TOPIC_AI_FORECAST:
            try:
                _cache["ai_forecast"] = json.loads(payload)
            except json.JSONDecodeError:
                _cache["ai_forecast"] = {"forecast": payload}


def start_mqtt() -> None:
    import paho.mqtt.client as mqtt

    def run() -> None:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="kcr-weather-console")
        if MQTT_USER and MQTT_PASS:
            client.username_pw_set(MQTT_USER, MQTT_PASS)
        client.on_message = _on_message

        def on_connect(c, u, flags, reason_code, properties):
            LOGGER.info("Console connected to MQTT (%s)", reason_code)
            for topic in (TOPIC_STATE, TOPIC_STATUS, TOPIC_AI_FORECAST):
                c.subscribe(topic)

        client.on_connect = on_connect
        while True:
            try:
                client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
                client.loop_forever(retry_first_connection=True)
            except Exception as exc:  # noqa: BLE001 - keep retrying forever
                LOGGER.warning("MQTT connection failed: %s; retrying in 10s", exc)
                time.sleep(10)

    threading.Thread(target=run, daemon=True).start()


def _tail_jsonl(path: Path, max_lines: int = 900) -> list[dict]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_lines * 400))
            raw = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows: list[dict] = []
    for line in raw.splitlines()[1:] if size > max_lines * 400 else raw.splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-max_lines:]


def _parse_ts(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def build_history(hours: int = 24) -> dict:
    """Risk + environment series for the trend charts, last `hours` hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    risk_fields = [
        "storm_risk_1h", "rain_risk_1h", "wind_risk_1h", "lightning_risk_1h",
        "heat_risk_24h", "cold_risk_24h",
    ]
    env_fields = ["temperature_c", "humidex", "pressure_hpa", "wind_gust_kmh", "rain_rate_mm_h"]

    risks: list[dict] = []
    for row in _tail_jsonl(PREDICTIONS_PATH):
        timestamp = _parse_ts(row.get("timestamp"))
        if timestamp is None or timestamp < cutoff:
            continue
        point = {"t": timestamp.isoformat()}
        point.update({field: row.get(field) for field in risk_fields})
        risks.append(point)

    environment: list[dict] = []
    for row in _tail_jsonl(SNAPSHOTS_PATH):
        timestamp = _parse_ts(row.get("timestamp"))
        if timestamp is None or timestamp < cutoff:
            continue
        point = {"t": timestamp.isoformat()}
        point.update({field: row.get(field) for field in env_fields})
        environment.append(point)

    return {"risks": risks, "environment": environment}


def load_scoreboard() -> dict | None:
    if not SCOREBOARD_PATH.exists():
        return None
    try:
        return json.loads(SCOREBOARD_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@app.route("/api/state")
def api_state():
    with _cache_lock:
        prediction = _cache["prediction"]
        availability = _cache["availability"]
        ai_forecast = _cache["ai_forecast"]
    return jsonify(
        {
            "now": datetime.now(timezone.utc).isoformat(),
            "availability": availability,
            "prediction": prediction,
            "ai_forecast": ai_forecast,
            "history": build_history(),
            "verification": load_scoreboard(),
        }
    )


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(STATIC_DIR, filename)


def seed_demo_data() -> None:
    """CONSOLE_DEMO=1: populate the cache and log files with representative
    data so the UI can be designed/QA'd without a live broker."""
    import math
    import random

    random.seed(41153)
    now = datetime.now(timezone.utc)
    with _cache_lock:
        _cache["availability"] = "online"
        _cache["prediction"] = {
            "storm_risk_1h": 68, "storm_risk_24h": 74, "wind_risk_1h": 42,
            "rain_risk_1h": 85, "lightning_risk_1h": 55, "confidence": 91,
            "level": "watch",
            "explanation": "pressure falling -2.1 hPa over 3h; forecast rain chance 80% within 1h; lightning signal active; radar precipitation nearby",
            "heat_risk_24h": 38, "cold_risk_24h": 0,
            "heat_severity": "mild", "cold_severity": "none",
            "rain_risk_24h": 92, "wind_risk_24h": 58,
            "imminent_event": "rain", "imminent_minutes": 35,
            "imminent_summary": "Rain expected in about 35 minutes",
            "official_alert_level": "advisory",
            "official_alert_summary": "Severe thunderstorm watch in effect",
        }
        _cache["ai_forecast"] = {
            "generated_at": now.isoformat(),
            "model": "claude",
            "forecast": (
                "SYNOPSIS: A vigorous shortwave trough crossing the St. John River valley "
                "tonight will drive a broken line of thunderstorms through Kingsclear between "
                "20:00 and 23:00 ADT, with torrential downbursts and gusts near 70 km/h in the "
                "strongest cells.\n\nNEXT 24H: Storm risk peaks this evening, easing after "
                "midnight. Rainfall totals 15-25 mm, locally 40 mm under training cells. "
                "Winds veer northwest by dawn.\n\n24-72H OUTLOOK: High pressure builds "
                "Thursday with sunshine and a dry northwest flow, highs near 24. A weak warm "
                "front brushes the region Friday night with patchy showers; the weekend trends "
                "warmer and more humid, humidex approaching 33 by Sunday afternoon — below "
                "warning criteria but worth monitoring for Monday."
            ),
        }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with PREDICTIONS_PATH.open("w", encoding="utf-8") as handle:
        for i in range(288):
            t = now - timedelta(minutes=5 * (288 - i))
            phase = i / 288 * math.tau
            handle.write(json.dumps({
                "timestamp": t.isoformat(),
                "storm_risk_1h": max(0, min(100, 30 + 35 * math.sin(phase * 1.4) + random.uniform(-6, 6))),
                "rain_risk_1h": max(0, min(100, 45 + 40 * math.sin(phase * 1.1 + 1) + random.uniform(-5, 5))),
                "wind_risk_1h": max(0, min(100, 25 + 18 * math.sin(phase * 2 + 2) + random.uniform(-4, 4))),
                "lightning_risk_1h": max(0, min(100, 20 + 30 * max(0, math.sin(phase * 1.7 + 4)) + random.uniform(-4, 4))),
                "heat_risk_24h": max(0, min(100, 30 + 10 * math.sin(phase + 5) + random.uniform(-3, 3))),
                "cold_risk_24h": 0,
            }) + "\n")
    with SNAPSHOTS_PATH.open("w", encoding="utf-8") as handle:
        for i in range(288):
            t = now - timedelta(minutes=5 * (288 - i))
            phase = i / 288 * math.tau
            handle.write(json.dumps({
                "timestamp": t.isoformat(),
                "temperature_c": 21 + 6 * math.sin(phase - 1.2) + random.uniform(-0.4, 0.4),
                "humidex": 25 + 7 * math.sin(phase - 1.1) + random.uniform(-0.5, 0.5),
                "pressure_hpa": 1009 - 4 * (i / 288) + 1.2 * math.sin(phase * 3) + random.uniform(-0.2, 0.2),
                "wind_gust_kmh": max(0, 18 + 14 * math.sin(phase * 1.3 + 2) + random.uniform(-3, 3)),
                "rain_rate_mm_h": max(0, 2.5 * math.sin(phase * 1.1 + 1)) if i > 200 else 0,
            }) + "\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if os.environ.get("CONSOLE_DEMO") == "1":
        LOGGER.info("CONSOLE_DEMO=1 — serving synthetic data")
        seed_demo_data()
    else:
        start_mqtt()
    app.run(host="0.0.0.0", port=CONSOLE_PORT)


if __name__ == "__main__":
    main()
