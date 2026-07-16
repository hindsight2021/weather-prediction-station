"""Replace the Fire & Air view (lovelace-weather) and the Overview Home V2 view
(default lovelace) — with full backups first."""
import asyncio
import json
from datetime import datetime
from pathlib import Path

import websockets

TOKEN = Path(r"C:\Users\mboud\.hass_token").read_text(encoding="utf-8").strip()
WS = "ws://homeassistant.local:8123/api/websocket"
BACKUP_DIR = Path(r"Y:\Codex\projects\weather-prediction-station\home-assistant\backups")

CONSOLE = "http://192.168.1.118:8126"

FIRE_VIEW = {
    "title": "Fire & Air",
    "path": "fire-air",
    "icon": "mdi:fire-alert",
    "type": "panel",
    "cards": [
        {"type": "iframe", "url": f"{CONSOLE}/fire", "aspect_ratio": "100%"}
    ],
}

# ---- Overview: one page, 9.7" iPad landscape (1024x768), no scrolling ----
def chip_tpl(content, icon, color=None, tap_entity=None):
    chip = {"type": "template", "content": content, "icon": icon}
    if color:
        chip["icon_color"] = color
    if tap_entity:
        chip["tap_action"] = {"action": "more-info"}
        chip["entity"] = tap_entity
    return chip


OVERVIEW_VIEW = {
    "title": "Home V2",
    "theme": "noctis",
    "type": "sections",
    "max_columns": 3,
    "badges": [],
    "sections": [
        # ---------- column 1: weather + prediction ----------
        {
            "type": "grid",
            "column_span": 1,
            "cards": [
                {
                    "type": "custom:mushroom-chips-card",
                    "alignment": "justify",
                    "chips": [
                        {"type": "template", "entity": "sensor.weather_brain_alert_level",
                         "content": "{{ states('sensor.weather_brain_alert_level') | upper }}",
                         "icon": "mdi:shield-alert",
                         "icon_color": "{% set l = states('sensor.weather_brain_alert_level') %}{% if l == 'warning' %}red{% elif l == 'watch' %}orange{% elif l == 'advisory' %}amber{% else %}teal{% endif %}",
                         "tap_action": {"action": "more-info"}},
                        {"type": "template", "entity": "sensor.weather_brain_confidence",
                         "content": "{{ states('sensor.weather_brain_confidence') }}% conf",
                         "icon": "mdi:brain", "icon_color": "brown"},
                        {"type": "template", "entity": "sensor.fredericton_warnings",
                         "content": "EC {{ states('sensor.fredericton_warnings') }}⚠",
                         "icon": "mdi:alert", "icon_color": "{% if states('sensor.fredericton_warnings')|int(0) > 0 %}red{% else %}grey{% endif %}"},
                    ],
                },
                {
                    "type": "weather-forecast",
                    "entity": "weather.home_weather_station",
                    "name": "Kingsclear",
                    "show_forecast": False,
                },
                {
                    "type": "custom:mushroom-chips-card",
                    "alignment": "justify",
                    "chips": [
                        chip_tpl("Storm {{ states('sensor.weather_brain_storm_risk_24h') }}%", "mdi:weather-lightning", "orange", "sensor.weather_brain_storm_risk_24h"),
                        chip_tpl("Rain {{ states('sensor.weather_brain_rain_risk_24h') }}%", "mdi:weather-pouring", "blue", "sensor.weather_brain_rain_risk_24h"),
                        chip_tpl("Wind {{ states('sensor.weather_brain_wind_risk_24h') }}%", "mdi:weather-windy", "green", "sensor.weather_brain_wind_risk_24h"),
                    ],
                },
                {
                    "type": "custom:mushroom-template-card",
                    "entity": "sensor.weather_brain_ai_forecast",
                    "primary": "Weather Brain outlook (24–72h)",
                    "secondary": "{{ (state_attr('sensor.weather_brain_ai_forecast','forecast') or 'Daily briefing pending.') | replace('SYNOPSIS:','') | trim | truncate(180, true, '…') }}",
                    "icon": "mdi:crystal-ball",
                    "icon_color": "teal",
                    "multiline_secondary": True,
                    "tap_action": {"action": "more-info"},
                },
                {
                    "type": "conditional",
                    "conditions": [{"condition": "state", "entity": "sensor.weather_brain_imminent_event", "state_not": "none"}],
                    "card": {
                        "type": "custom:mushroom-template-card",
                        "entity": "sensor.weather_brain_imminent_summary",
                        "primary": "⚠ {{ states('sensor.weather_brain_imminent_summary') }}",
                        "icon": "mdi:clock-alert", "icon_color": "red",
                    },
                },
            ],
        },
        # ---------- column 2: fire, air, people, house ----------
        {
            "type": "grid",
            "column_span": 1,
            "cards": [
                {
                    "type": "custom:mushroom-template-card",
                    "entity": "sensor.weather_brain_nb_burn_category",
                    "primary": "{% set c = states('sensor.weather_brain_nb_burn_category')|int(0) %}{% if c == 1 %}Burning prohibited{% elif c == 2 %}Evening burns only{% elif c == 3 %}Burning permitted{% else %}Burn status unknown{% endif %}",
                    "secondary": "{{ states('sensor.weather_brain_active_fires_within_150_km') }} fires ≤150 km · nearest {{ states('sensor.weather_brain_nearest_fire_km') }} km",
                    "icon": "mdi:fire-alert",
                    "icon_color": "{% set c = states('sensor.weather_brain_nb_burn_category')|int(0) %}{% if c == 1 %}red{% elif c == 2 %}amber{% elif c == 3 %}green{% else %}grey{% endif %}",
                    "tap_action": {"action": "navigate", "navigation_path": "/lovelace-weather/fire-air"},
                },
                {
                    "type": "custom:mushroom-chips-card",
                    "alignment": "justify",
                    "chips": [
                        chip_tpl("AQHI {{ states('sensor.weather_brain_aqhi_current') }}", "mdi:lungs",
                                 "{% if states('sensor.weather_brain_aqhi_current')|int(0) >= 7 %}red{% elif states('sensor.weather_brain_aqhi_current')|int(0) >= 4 %}amber{% else %}green{% endif %}",
                                 "sensor.weather_brain_aqhi_current"),
                        chip_tpl("Smoke {{ states('sensor.weather_brain_wildfire_smoke_risk') }}%", "mdi:smoke", "grey", "sensor.weather_brain_wildfire_smoke_risk"),
                        chip_tpl("Air 24h {{ states('sensor.weather_brain_air_quality_risk_24h') }}%", "mdi:air-filter", "blue-grey", "sensor.weather_brain_air_quality_risk_24h"),
                    ],
                },
                {
                    "type": "horizontal-stack",
                    "cards": [
                        {"type": "custom:mushroom-person-card", "name": "Mike", "icon": "mdi:horse-human", "entity": "device_tracker.mikes_iphone"},
                        {"type": "custom:mushroom-person-card", "entity": "device_tracker.chris_iphone", "name": "Chris", "icon": "mdi:chef-hat"},
                    ],
                },
                {
                    "type": "horizontal-stack",
                    "cards": [
                        {"type": "custom:mushroom-template-card", "primary": "Main", "secondary": "{{ states('sensor.average_main_floor_temp') }}°C · {{ states('sensor.pws_main_floor_humidity') }}%", "icon": ""},
                        {"type": "custom:mushroom-template-card", "primary": "Bsmt", "secondary": "{{ states('sensor.average_basement_temp') }}°C · {{ states('sensor.pws_basement_humidity') }}%", "icon": ""},
                        {"type": "custom:mushroom-template-card", "primary": "Bed", "secondary": "{{ states('sensor.average_bedroom_temperature') }}°C", "icon": ""},
                    ],
                },
                {
                    "type": "custom:mushroom-alarm-control-panel-card",
                    "entity": "alarm_control_panel.blink_ihomecamera",
                    "states": ["armed_away"],
                    "name": "Blink Cameras",
                    "layout": "horizontal",
                },
            ],
        },
        # ---------- column 3: climate + cameras + calendar + utility ----------
        {
            "type": "grid",
            "column_span": 1,
            "cards": [
                {
                    "type": "custom:tabbed-card",
                    "styles": {"--mdc-theme-primary": "orange", "--mdc-tab-text-label-color-default": "white", "--mdc-typography-button-font-size": "10px"},
                    "tabs": [
                        {"attributes": {"label": "Main"}, "card": {"type": "custom:mushroom-climate-card", "entity": "climate.main_floor_ac", "icon": "mdi:air-conditioner", "layout": "horizontal", "collapsible_controls": True, "hvac_modes": ["auto", "heat", "cool", "fan_only", "dry", "off"], "show_temperature_control": True}},
                        {"attributes": {"label": "Bed"}, "card": {"type": "custom:mushroom-climate-card", "entity": "climate.bedroom_ac", "icon": "mdi:air-conditioner", "layout": "horizontal", "collapsible_controls": True, "hvac_modes": ["auto", "heat", "cool", "fan_only", "dry", "off"], "show_temperature_control": True}},
                        {"attributes": {"label": "Bsmt"}, "card": {"type": "custom:mushroom-climate-card", "entity": "climate.basement_ac", "icon": "mdi:air-conditioner", "layout": "horizontal", "collapsible_controls": True, "hvac_modes": ["auto", "heat", "cool", "fan_only", "dry", "off"], "show_temperature_control": True}},
                    ],
                },
                {
                    "type": "custom:mushroom-chips-card",
                    "alignment": "justify",
                    "chips": [
                        chip_tpl("Amazn {{ states('sensor.mail_amazon_packages_delivered') }}", "mdi:package-variant", "{% if states('sensor.mail_amazon_packages_delivered')|int(0) > 0 %}green{% else %}grey{% endif %}", "sensor.mail_amazon_packages_delivered"),
                        chip_tpl("IntCom {{ states('sensor.mail_intelcom_delivered') }}", "mdi:truck-delivery", "{% if states('sensor.mail_intelcom_delivered')|int(0) > 0 %}green{% else %}grey{% endif %}", "sensor.mail_intelcom_delivered"),
                        chip_tpl("Post {{ states('sensor.mail_canada_post_delivered') }}", "mdi:mailbox", "{% if states('sensor.mail_canada_post_delivered')|int(0) > 0 %}green{% else %}grey{% endif %}", "sensor.mail_canada_post_delivered"),
                    ],
                },
                {
                    "type": "custom:mushroom-chips-card",
                    "alignment": "justify",
                    "chips": [
                        chip_tpl("Gas {{ states('sensor.gas_station_regular_gas_2') }}", "mdi:gas-station", "amber", "sensor.gas_station_regular_gas_2"),
                        {"type": "entity", "entity": "input_boolean.enhanced_security", "icon": "mdi:home-lock"},
                        chip_tpl("↓{{ states('sensor.speedtest_download') | round(0) }} ↑{{ states('sensor.speedtest_upload') | round(0) }}", "mdi:speedometer", "blue", "sensor.speedtest_download"),
                    ],
                },
                {
                    "type": "conditional",
                    "conditions": [{"condition": "state", "entity": "media_player.android_4", "state": "playing"}],
                    "card": {"type": "custom:mini-media-player", "entity": "media_player.android_4", "artwork": "full-cover", "info": "scroll", "replace_mute": "stop"},
                },
                {
                    "type": "custom:tabbed-card",
                    "styles": {"--mdc-theme-primary": "white", "--mdc-tab-text-label-color-default": "grey", "--mdc-typography-button-font-size": "10px"},
                    "tabs": [
                        {"attributes": {"label": "Door"}, "card": {"type": "picture-entity", "entity": "camera.blink_front_door"}},
                        {"attributes": {"label": "Drive"}, "card": {"type": "picture-entity", "entity": "camera.blink_driveway"}},
                        {"attributes": {"label": "Yard"}, "card": {"type": "picture-entity", "entity": "camera.blink_back_door"}},
                    ],
                },
                {
                    "type": "custom:atomic-calendar-revive",
                    "firstDayOfWeek": 1,
                    "maxDaysToShow": 3,
                    "maxEventCount": 4,
                    "disableEventLink": True,
                    "disableLocationLink": True,
                    "refreshInterval": 60,
                    "showWeekDay": True,
                    "entities": [
                        "calendar.m_boudreau87_gmail_com", "calendar.mikes_events",
                        "calendar.calendar_2", "calendar.calendar_3", "calendar.work",
                    ],
                },
            ],
        },
    ],
    "cards": [
        {
            "type": "custom:meteoalarm-card",
            "integration": "env_canada",
            "entities": [{"entity": "sensor.fredericton_watches"}, {"entity": "sensor.fredericton_warnings"}],
            "override_headline": False,
            "hide_when_no_warning": True,
        },
    ],
}


# HA section columns are fixed-width (~330px + gaps): a 1024px iPad fits only
# two and wraps -> scrolling. A panel view with one horizontal-stack of three
# vertical-stacks divides the width evenly at ANY size: guaranteed one page.
_columns = [section["cards"] for section in OVERVIEW_VIEW["sections"]]
_columns[0].insert(0, OVERVIEW_VIEW["cards"][0])  # meteoalarm (hidden when quiet)
OVERVIEW_VIEW = {
    "title": "Home V2",
    "theme": OVERVIEW_VIEW["theme"],
    "type": "panel",
    "cards": [
        {
            "type": "horizontal-stack",
            "cards": [{"type": "vertical-stack", "cards": column} for column in _columns],
        }
    ],
}


async def main() -> None:
    async with websockets.connect(WS, max_size=20 * 1024 * 1024) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        assert json.loads(await ws.recv()).get("type") == "auth_ok"
        msg_id = 0

        async def call(payload: dict) -> dict:
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, **payload}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == msg_id:
                    return r

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        # --- fire view in lovelace-weather ---
        weather_cfg = (await call({"type": "lovelace/config", "url_path": "lovelace-weather"}))["result"]
        (BACKUP_DIR / f"lovelace-weather-{stamp}.json").write_text(json.dumps(weather_cfg, indent=1), encoding="utf-8")
        for i, view in enumerate(weather_cfg.get("views", [])):
            if view.get("path") == "fire-air":
                weather_cfg["views"][i] = FIRE_VIEW
                break
        saved = await call({"type": "lovelace/config/save", "url_path": "lovelace-weather", "config": weather_cfg})
        print("fire view saved:", saved.get("success"))

        # --- overview Home V2 (view index 2) in default dashboard ---
        main_cfg = (await call({"type": "lovelace/config"}))["result"]
        (BACKUP_DIR / f"lovelace-default-{stamp}.json").write_text(json.dumps(main_cfg, indent=1), encoding="utf-8")
        views = main_cfg.get("views", [])
        assert views[2].get("title") == "Home V2", f"view 2 is {views[2].get('title')} — aborting"
        views[2] = OVERVIEW_VIEW
        saved = await call({"type": "lovelace/config/save", "config": main_cfg})
        print("overview saved:", saved.get("success"))


asyncio.run(main())
