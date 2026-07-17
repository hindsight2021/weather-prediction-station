"""Weather command console backend.

Subscribes to the retained Weather Brain MQTT topics (prediction, raw sensor
inputs, forecast summary, verification, AI forecast) and serves:

- ``/``          the atmospheric command console single-page app
- ``/fire``      the fire-warden tracking console
- ``/api/state`` aggregated weather state (cache + log tails + scoreboard)
- ``/api/fires`` NB wildfire map data (county burn polygons + active fires),
                 fetched from the GNB ERD feeds and cached — no third-party
                 map embeds anywhere.

Runs as its own docker-compose service (`console`) beside the prediction
engine; Home Assistant embeds the pages in dashboard iframes, so everything
stays same-origin and needs no HA credentials.
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
LATITUDE = float(os.environ.get("WEATHER_LATITUDE", "45.9636"))
LONGITUDE = float(os.environ.get("WEATHER_LONGITUDE", "-66.6431"))

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
PREDICTIONS_PATH = DATA_DIR / "predictions.jsonl"
SNAPSHOTS_PATH = DATA_DIR / "weather_snapshots.jsonl"
SCOREBOARD_PATH = DATA_DIR / "verification" / "scoreboard.json"

STATIC_DIR = Path(__file__).resolve().parent / "static"

TOPIC_STATE = "weather_brain/prediction/state"
TOPIC_STATUS = "weather_brain/status"
TOPIC_AI_FORECAST = "weather_brain/ai_forecast/state"
# Raw live inputs straight off the broker: wind direction, forecast summary
# fields, lightning — richer and fresher than the snapshot tail.
INPUT_TOPIC_PREFIXES = ("ha_bridge/", "lightning/", "radar/")

FIRE_CACHE_TTL_SECONDS = 600

# ---- Home Assistant bridge for the overview page --------------------------
# The overview console surfaces HA entities (persons, AC, cameras, calendar)
# through this backend so the page stays same-origin. Token comes from .env
# (same one ha-bridge uses); nothing HA-side is exposed beyond the whitelist.
HA_TOKEN = os.environ.get("HA_TOKEN", "")
HA_URL = os.environ.get(
    "HA_HTTP_URL",
    os.environ.get("HA_WS_URL", "ws://homeassistant.local:8123/api/websocket")
    .replace("ws://", "http://").replace("wss://", "https://")
    .replace("/api/websocket", ""),
)

OVERVIEW_ENTITIES = [
    "device_tracker.mikes_iphone", "device_tracker.chris_iphone",
    "climate.main_floor_ac", "climate.bedroom_ac", "climate.basement_ac",
    "alarm_control_panel.blink_ihomecamera", "input_boolean.enhanced_security",
    "sensor.mail_amazon_packages_delivered", "sensor.mail_intelcom_delivered",
    "sensor.mail_canada_post_delivered", "sensor.gas_station_regular_gas",
    "sensor.speedtest_download", "sensor.speedtest_upload", "sensor.speedtest_ping",
    "sensor.exchange_rate_1_btc",
    "sensor.average_main_floor_temp", "sensor.pws_main_floor_humidity",
    "sensor.average_basement_temp", "sensor.pws_basement_humidity",
    "sensor.average_bedroom_temperature",
    "sensor.fredericton_warnings", "sensor.fredericton_watches",
    "sensor.fredericton_statements", "sensor.fredericton_summary",
    "sensor.fredericton_current_condition", "sensor.fredericton_uv_index",
]
OVERVIEW_CALENDARS = [
    "calendar.m_boudreau87_gmail_com", "calendar.mikes_events",
    "calendar.work3", "calendar.birthdays_2",
]
CAMERA_ENTITIES = {
    "portrait": "camera.weather_gpt_image",
    "door": "camera.blink_front_door",
    "bell": "camera.front_door",  # Blink doorbell
    "drive": "camera.blink_driveway",
    "yard": "camera.blink_back_door",
}
# Only these HA services may be called from the page.
SERVICE_WHITELIST = {
    ("climate", "set_temperature"),
    ("climate", "set_hvac_mode"),
    ("input_boolean", "toggle"),
}

_ha_camera_cache: dict[str, tuple[float, bytes, str]] = {}
_ha_lock = threading.Lock()

app = Flask(__name__, static_folder=None)

_cache: dict[str, object] = {
    "prediction": None,
    "availability": "unknown",
    "ai_forecast": None,
    "inputs": {},
}
_cache_lock = threading.Lock()

_fire_cache: dict[str, object] = {"data": None, "fetched_monotonic": 0.0}
_fire_lock = threading.Lock()


def _parse_input_payload(payload: str) -> float | str | None:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        parsed = payload
    if isinstance(parsed, dict):
        parsed = parsed.get("value")
    if parsed in (None, "", "unavailable", "unknown"):
        return None
    try:
        return float(parsed)
    except (TypeError, ValueError):
        return str(parsed)


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
        elif message.topic.startswith(INPUT_TOPIC_PREFIXES):
            _cache["inputs"][message.topic] = _parse_input_payload(payload)  # type: ignore[index]


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
            for prefix in INPUT_TOPIC_PREFIXES:
                c.subscribe(prefix + "#")

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
        "heat_risk_24h", "cold_risk_24h", "confidence",
    ]
    env_fields = [
        "temperature_c", "humidex", "pressure_hpa", "wind_gust_kmh",
        "wind_speed_kmh", "rain_rate_mm_h", "humidity_pct",
    ]

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
        inputs = dict(_cache["inputs"])  # type: ignore[arg-type]
    return jsonify(
        {
            "now": datetime.now(timezone.utc).isoformat(),
            "home": {"lat": LATITUDE, "lon": LONGITUDE},
            "availability": availability,
            "prediction": prediction,
            "ai_forecast": ai_forecast,
            "inputs": inputs,
            "history": build_history(),
            "verification": load_scoreboard(),
        }
    )


@app.route("/api/fires")
def api_fires():
    now = time.monotonic()
    with _fire_lock:
        if _fire_cache["data"] is not None and now - float(_fire_cache["fetched_monotonic"]) < FIRE_CACHE_TTL_SECONDS:
            return jsonify(_fire_cache["data"])
    try:
        from app.environmental import fetch_fire_map_data

        data = fetch_fire_map_data(LATITUDE, LONGITUDE)
        with _fire_lock:
            _fire_cache["data"] = data
            _fire_cache["fetched_monotonic"] = now
        return jsonify(data)
    except Exception as exc:  # noqa: BLE001 - serve stale data over an error page
        LOGGER.warning("Fire data fetch failed: %s", exc)
        with _fire_lock:
            if _fire_cache["data"] is not None:
                stale = dict(_fire_cache["data"])  # type: ignore[arg-type]
                stale["stale"] = True
                return jsonify(stale)
    return jsonify({"error": "fire data unavailable"}), 503


def _ha_get(path: str, timeout: float = 12.0):
    import requests

    return requests.get(
        f"{HA_URL}{path}",
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
        timeout=timeout,
    )


@app.route("/api/ha/overview")
def api_ha_overview():
    if not HA_TOKEN:
        return jsonify({"error": "HA_TOKEN not configured"}), 503
    try:
        states = {}
        response = _ha_get("/api/states")
        response.raise_for_status()
        wanted = set(OVERVIEW_ENTITIES)
        for entity in response.json():
            if entity["entity_id"] in wanted:
                states[entity["entity_id"]] = {
                    "state": entity.get("state"),
                    "attributes": {
                        k: v for k, v in (entity.get("attributes") or {}).items()
                        if k in ("friendly_name", "temperature", "current_temperature",
                                 "hvac_modes", "unit_of_measurement", "hvac_action")
                    },
                }

        events = []
        start = datetime.now(timezone.utc)
        end = start + timedelta(days=7)
        from urllib.parse import quote

        for calendar in OVERVIEW_CALENDARS:
            try:
                cal = _ha_get(
                    f"/api/calendars/{calendar}"
                    f"?start={quote(start.isoformat())}&end={quote(end.isoformat())}",
                    timeout=8,
                )
                if cal.status_code == 200:
                    for event in cal.json():
                        events.append({
                            "summary": event.get("summary"),
                            "start": (event.get("start") or {}).get("dateTime")
                            or (event.get("start") or {}).get("date"),
                            "all_day": "date" in (event.get("start") or {}),
                        })
            except Exception:  # noqa: BLE001 - one broken calendar shouldn't kill the page
                continue
        events = sorted((e for e in events if e["start"]), key=lambda e: e["start"])[:6]

        return jsonify({"states": states, "events": events, "cameras": list(CAMERA_ENTITIES)})
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("HA overview fetch failed: %s", exc)
        return jsonify({"error": str(exc)}), 502


@app.route("/api/ha/camera/<name>")
def api_ha_camera(name: str):
    entity = CAMERA_ENTITIES.get(name)
    if entity is None or not HA_TOKEN:
        return jsonify({"error": "unknown camera"}), 404
    now = time.monotonic()
    with _ha_lock:
        cached = _ha_camera_cache.get(name)
        if cached and now - cached[0] < 55:
            return app.response_class(cached[1], mimetype=cached[2])
    try:
        response = _ha_get(f"/api/camera_proxy/{entity}", timeout=15)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "image/jpeg")
        with _ha_lock:
            _ha_camera_cache[name] = (now, response.content, content_type)
        return app.response_class(response.content, mimetype=content_type)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Camera proxy failed for %s: %s", entity, exc)
        with _ha_lock:
            cached = _ha_camera_cache.get(name)
        if cached:
            return app.response_class(cached[1], mimetype=cached[2])
        return jsonify({"error": "camera unavailable"}), 502


@app.route("/api/ha/service", methods=["POST"])
def api_ha_service():
    from flask import request as flask_request

    if not HA_TOKEN:
        return jsonify({"error": "HA_TOKEN not configured"}), 503
    body = flask_request.get_json(silent=True) or {}
    domain, service = str(body.get("domain", "")), str(body.get("service", ""))
    if (domain, service) not in SERVICE_WHITELIST:
        return jsonify({"error": "service not allowed"}), 403
    try:
        import requests

        response = requests.post(
            f"{HA_URL}/api/services/{domain}/{service}",
            headers={"Authorization": f"Bearer {HA_TOKEN}"},
            json=body.get("data") or {},
            timeout=12,
        )
        response.raise_for_status()
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("HA service call failed: %s", exc)
        return jsonify({"error": str(exc)}), 502


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/overview")
def overview():
    return send_from_directory(STATIC_DIR, "overview.html")


@app.route("/fire")
def fire():
    return send_from_directory(STATIC_DIR, "fire.html")


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
            "rain_risk_1h": 85, "lightning_risk_1h": 55, "confidence": 84,
            "level": "watch",
            "explanation": "pressure falling -2.1 hPa over 3h; forecast rain chance 80% within 1h; lightning signal active; radar precipitation nearby",
            "heat_risk_24h": 38, "cold_risk_24h": 0,
            "heat_severity": "mild", "cold_severity": "none",
            "rain_risk_24h": 92, "wind_risk_24h": 58,
            "imminent_event": "rain", "imminent_minutes": 35,
            "imminent_summary": "Rain expected in about 35 minutes",
            "official_alert_level": "advisory",
            "official_alert_summary": "Severe thunderstorm watch in effect",
            "storm_risk_48h": 61, "storm_risk_72h": 44,
            "air_quality_risk_24h": 55, "air_quality_risk_48h": 40,
            "smoke_risk_24h": 24, "aqhi_current": 6, "aqhi_forecast_max_24h": 7,
            "nb_burn_status": "no_burn", "nb_burn_category": 1,
            "active_fires_nearby": 3, "nearest_fire_km": 42.7,
            "ml_status": "ML active: convective_risk, storm_24h, wind_1h",
            "model_accuracy": "storm_24h: Brier 0.041, AUC 0.87",
            "last_trained": (now - timedelta(days=2)).isoformat(),
        }
        _cache["ai_forecast"] = {
            "generated_at": now.isoformat(),
            "model": "weather-brain-ml + ha-assist",
            "forecast": (
                "SYNOPSIS: Falling pressure and elevated humidity mark an approaching "
                "disturbance; the storm models hold a 74 percent 24-hour signal with "
                "convective energy peaking late evening.\n\nNEXT 24H: Showers become "
                "likely within the hour, with embedded thunderstorms after 20:00. "
                "Gusts near 50 km/h in the strongest cells. Smoke from three regional "
                "fires keeps AQHI elevated at 6.\n\n24-72H OUTLOOK: Slow clearing "
                "Thursday as pressure recovers; Friday trends warm and dry. Nothing "
                "in the 72-hour window approaches warning criteria."
            ),
        }
        _cache["inputs"] = {
            "ha_bridge/atlas/wind_direction": 285.0,
            "ha_bridge/atlas/wind_speed_kmh": 18.0,
            "ha_bridge/atlas/rain_total": 6.4,
            "ha_bridge/forecast/precip_probability_1h": 80.0,
            "ha_bridge/forecast/precip_probability_6h": 70.0,
            "ha_bridge/forecast/precip_probability_24h": 60.0,
            "ha_bridge/forecast/wind_gust_max_24h": 52.0,
            "lightning/local/distance_km": 24.0,
            "radar/nearby/precip": 1.0,
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
                "confidence": max(30, min(92, 75 + 10 * math.sin(phase * 0.7) + random.uniform(-3, 3))),
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
                "wind_speed_kmh": max(0, 10 + 8 * math.sin(phase * 1.3 + 2) + random.uniform(-2, 2)),
                "humidity_pct": min(100, max(20, 60 + 20 * math.sin(phase + 2) + random.uniform(-2, 2))),
                "rain_rate_mm_h": max(0, 2.5 * math.sin(phase * 1.1 + 1)) if i > 200 else 0,
            }) + "\n")

    # Synthetic fire picture (counties as simple boxes so the map renders).
    def box(lon0, lat0, lon1, lat1):
        return {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]}

    with _fire_lock:
        _fire_cache["data"] = {
            "fetched_at": now.isoformat(),
            "home": {"lat": LATITUDE, "lon": LONGITUDE},
            "counties": [
                {"name": "York", "category": 1, "geometry": box(-67.6, 45.6, -66.4, 46.6)},
                {"name": "Sunbury", "category": 2, "geometry": box(-66.4, 45.6, -65.8, 46.3)},
                {"name": "Carleton", "category": 1, "geometry": box(-68.0, 46.0, -67.3, 46.8)},
                {"name": "Charlotte", "category": 3, "geometry": box(-67.3, 45.0, -66.6, 45.6)},
                {"name": "Queens", "category": 2, "geometry": box(-66.4, 45.5, -65.6, 46.1)},
                {"name": "Kings", "category": 3, "geometry": box(-66.2, 45.2, -65.3, 45.8)},
                {"name": "Victoria", "category": 1, "geometry": box(-68.0, 46.4, -67.0, 47.2)},
            ],
            "fires": [
                {"name": "Cranberry Lake", "lat": 46.31, "lon": -66.19, "stage": "OC", "size_ha": 210.0, "detected": "2026-07-14", "distance_km": 42.7},
                {"name": "Juniper Ridge", "lat": 46.55, "lon": -67.15, "stage": "BH", "size_ha": 65.0, "detected": "2026-07-12", "distance_km": 74.9},
                {"name": "Meductic", "lat": 45.99, "lon": -67.47, "stage": "UC", "size_ha": 6.5, "detected": "2026-07-15", "distance_km": 64.4},
                {"name": "Salmon River", "lat": 46.11, "lon": -65.63, "stage": "EX", "size_ha": 12.0, "detected": "2026-07-08", "distance_km": 79.5},
            ],
            "york_burn_category": 1,
            "york_burn_status": "no_burn",
            "active_fire_count": 3,
            "nearest_active_km": 42.7,
        }
        _fire_cache["fetched_monotonic"] = time.monotonic() + 10 ** 9  # never expires in demo


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
