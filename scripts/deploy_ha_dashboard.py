"""Install the Weather Brain and Fire & Air views into Home Assistant Lovelace.

Run inside the ha-bridge container, which already has HA_WS_URL and HA_TOKEN.
The operation is idempotent and preserves every unrelated dashboard view.
"""
from __future__ import annotations

import asyncio
import json
import os

import websockets


def gauge(entity: str, name: str, yellow: int = 40, red: int = 75) -> dict:
    return {"type": "gauge", "entity": entity, "name": name, "min": 0, "max": 100,
            "needle": True, "severity": {"green": 0, "yellow": yellow, "red": red}}


def weather_brain_view() -> dict:
    return {
        "title": "Weather Brain", "path": "weather-brain", "icon": "mdi:brain", "type": "sections",
        "max_columns": 3, "dense_section_placement": True,
        "badges": [
            {"type": "entity", "entity": "sensor.weather_brain_alert_level", "name": "Threat"},
            {"type": "entity", "entity": "sensor.weather_brain_eccc_alert_level", "name": "ECCC"},
            {"type": "entity", "entity": "sensor.weather_brain_confidence", "name": "Confidence"},
            {"type": "entity", "entity": "sensor.weather_brain_imminent_event", "name": "Imminent"},
        ],
        "sections": [
            {"type": "grid", "cards": [
                {"type": "heading", "heading": "TACTICAL WEATHER STATUS", "icon": "mdi:shield-half-full"},
                {"type": "markdown", "content": "## {{ states('sensor.weather_brain_alert_level') | upper }}\n**{{ states('sensor.weather_brain_explanation') }}**\n\n{% if not is_state('sensor.weather_brain_imminent_event','none') %}⏱ **{{ states('sensor.weather_brain_imminent_summary') }}**{% else %}No severe weather is imminent.{% endif %}"},
                gauge("sensor.weather_brain_storm_risk_1h", "Storm · 1 hour"),
                {"type": "tile", "entity": "sensor.weather_brain_imminent_event", "name": "Imminent Event", "vertical": False},
                {"type": "tile", "entity": "sensor.weather_brain_imminent_event_eta", "name": "Event ETA", "vertical": False},
                {"type": "tile", "entity": "sensor.weather_brain_eccc_alert", "name": "Official ECCC Alert", "vertical": False},
            ]},
            {"type": "grid", "cards": [
                {"type": "heading", "heading": "PREDICTIVE HORIZONS", "icon": "mdi:timeline-clock"},
                gauge("sensor.weather_brain_storm_risk_24h", "24 hour", 35, 70),
                gauge("sensor.weather_brain_storm_risk_48h", "48 hour", 35, 70),
                gauge("sensor.weather_brain_storm_risk_72h", "72 hour", 35, 70),
                {"type": "history-graph", "title": "Threat Evolution · 24h", "hours_to_show": 24,
                 "entities": ["sensor.weather_brain_storm_risk_1h", "sensor.weather_brain_storm_risk_24h", "sensor.weather_brain_confidence"]},
            ]},
            {"type": "grid", "cards": [
                {"type": "heading", "heading": "SENSOR FUSION", "icon": "mdi:radar"},
                gauge("sensor.weather_brain_lightning_risk_1h", "Lightning"),
                gauge("sensor.weather_brain_rain_risk_1h", "Rain"),
                gauge("sensor.weather_brain_wind_risk_1h", "Wind"),
                {"type": "entities", "title": "Environmental Intelligence", "show_header_toggle": False,
                 "entities": ["sensor.weather_brain_heat_severity", "sensor.weather_brain_cold_severity",
                              "sensor.weather_brain_aqhi_current", "sensor.weather_brain_wildfire_smoke_risk",
                              "sensor.weather_brain_active_fires_within_150_km"]},
                {"type": "history-graph", "title": "Local Signal History", "hours_to_show": 12,
                 "entities": ["sensor.weather_brain_rain_risk_1h", "sensor.weather_brain_wind_risk_1h", "sensor.weather_brain_lightning_risk_1h"]},
            ]},
        ],
    }


def fire_air_view() -> dict:
    return {
        "title": "Fire & Air", "path": "fire-air", "icon": "mdi:forest-fire", "type": "sections",
        "max_columns": 2, "dense_section_placement": True,
        "badges": [
            {"type": "entity", "entity": "sensor.weather_brain_york_county_burn_status", "name": "York Burn"},
            {"type": "entity", "entity": "sensor.weather_brain_active_fires_within_150_km", "name": "Nearby Fires"},
            {"type": "entity", "entity": "sensor.weather_brain_aqhi_current", "name": "AQHI"},
            {"type": "entity", "entity": "sensor.weather_brain_wildfire_smoke_risk", "name": "Smoke"},
        ],
        "sections": [
            {"type": "grid", "cards": [
                {"type": "heading", "heading": "NEW BRUNSWICK FIRE WATCH", "icon": "mdi:pine-tree-fire"},
                {"type": "markdown", "content": "## {{ states('sensor.weather_brain_york_county_burn_status') | replace('_',' ') | upper }}\n**{{ states('sensor.weather_brain_active_fires_within_150_km') }} active fire(s) within 150 km**\n\nBurn restrictions update daily during fire season. Smoke risk combines AQHI and nearby active-fire intelligence."},
                gauge("sensor.weather_brain_wildfire_smoke_risk", "Smoke Risk", 30, 60),
                {"type": "entities", "title": "Air Quality Forecast", "show_header_toggle": False,
                 "entities": ["sensor.weather_brain_aqhi_current", "sensor.weather_brain_aqhi_forecast_24h",
                              "sensor.weather_brain_air_quality_risk_24h", "sensor.weather_brain_air_quality_risk_48h"]},
                {"type": "history-graph", "title": "Air & Smoke · 72h", "hours_to_show": 72,
                 "entities": ["sensor.weather_brain_aqhi_current", "sensor.weather_brain_wildfire_smoke_risk"]},
            ]},
            {"type": "grid", "cards": [
                {"type": "heading", "heading": "LIVE FIRE MAPS", "icon": "mdi:map-search"},
                {"type": "iframe", "url": "https://cwfis.cfs.nrcan.gc.ca/interactive-map", "aspect_ratio": "100%", "title": "Canada Wildland Fire Map"},
                {"type": "iframe", "url": "https://www.gnb.ca/en/emergency/fire-watch.html", "aspect_ratio": "80%", "title": "New Brunswick Fire Watch"},
                {"type": "markdown", "content": "[Open Canada fire map](https://cwfis.cfs.nrcan.gc.ca/interactive-map) · [Open NB Fire Watch](https://www.gnb.ca/en/emergency/fire-watch.html)\n\n*Maps are authoritative government products. Tap a link if an embedded map is restricted by iOS.*"},
            ]},
        ],
    }


async def command(ws, message: dict, command_id: int) -> dict:
    await ws.send(json.dumps({"id": command_id, **message}))
    response = json.loads(await ws.recv())
    if not response.get("success"):
        raise RuntimeError(response)
    return response.get("result") or {}


async def main() -> None:
    async with websockets.connect(os.environ["HA_WS_URL"], max_size=10 * 1024 * 1024) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": os.environ["HA_TOKEN"]}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant authentication failed")
        config = await command(ws, {"type": "lovelace/config", "url_path": "lovelace-weather"}, 1)
        replacements = {"weather-brain", "weather-brain-lab", "fire-air"}
        views = [view for view in config.get("views", []) if view.get("path") not in replacements]
        # Put command views near the front while preserving every unrelated view.
        views[1:1] = [weather_brain_view(), fire_air_view()]
        config["views"] = views
        await command(ws, {"type": "lovelace/config/save", "url_path": "lovelace-weather", "config": config}, 2)
        print(f"Installed Weather Brain and Fire & Air; preserved {len(views) - 2} existing views")


if __name__ == "__main__":
    asyncio.run(main())
