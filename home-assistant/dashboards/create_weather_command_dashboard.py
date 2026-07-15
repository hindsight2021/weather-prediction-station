"""Create/refresh the 'Weather Command' HA dashboard with the console iframe."""
import asyncio
import json
from pathlib import Path

import websockets

TOKEN = Path(r"C:\Users\mboud\.hass_token").read_text(encoding="utf-8").strip()
WS = "ws://homeassistant.local:8123/api/websocket"

DASHBOARD = {
    "url_path": "weather-command",
    "title": "Weather Command",
    "icon": "mdi:radar",
    "show_in_sidebar": True,
    "require_admin": False,
}

CONFIG = {
    "views": [
        {
            "title": "Console",
            "path": "console",
            "icon": "mdi:radar",
            "type": "panel",
            "cards": [
                {
                    "type": "iframe",
                    "url": "http://192.168.1.118:8126",
                    "aspect_ratio": "100%",
                }
            ],
        },
        {
            "title": "Entities",
            "path": "entities",
            "icon": "mdi:view-list",
            "cards": [
                {
                    "type": "entities",
                    "title": "Alert & Analysis",
                    "entities": [
                        "sensor.weather_brain_alert_level",
                        "sensor.weather_brain_confidence",
                        "sensor.weather_brain_explanation",
                        "sensor.weather_brain_imminent_summary",
                        "sensor.weather_brain_eccc_alert",
                        "sensor.weather_brain_ai_forecast",
                    ],
                },
                {
                    "type": "entities",
                    "title": "Risks",
                    "entities": [
                        "sensor.weather_brain_storm_risk_1h",
                        "sensor.weather_brain_storm_risk_24h",
                        "sensor.weather_brain_rain_risk_1h",
                        "sensor.weather_brain_rain_risk_24h",
                        "sensor.weather_brain_wind_risk_1h",
                        "sensor.weather_brain_wind_risk_24h",
                        "sensor.weather_brain_lightning_risk_1h",
                        "sensor.weather_brain_heat_risk_24h",
                        "sensor.weather_brain_cold_risk_24h",
                    ],
                },
                {
                    "type": "entities",
                    "title": "Feedback (trains the models)",
                    "entities": [
                        "input_select.weather_brain_feedback_hazard",
                        "input_select.weather_brain_feedback_verdict",
                        "input_select.weather_brain_feedback_severity",
                        "input_text.weather_brain_feedback_notes",
                        "input_button.weather_brain_submit_feedback",
                    ],
                },
            ],
        },
    ]
}


async def main() -> None:
    async with websockets.connect(WS, max_size=10 * 1024 * 1024) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        auth = json.loads(await ws.recv())
        assert auth.get("type") == "auth_ok", auth

        msg_id = 0

        async def call(payload: dict) -> dict:
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, **payload}))
            while True:
                response = json.loads(await ws.recv())
                if response.get("id") == msg_id:
                    return response

        listing = await call({"type": "lovelace/dashboards/list"})
        existing = next(
            (d for d in listing.get("result", []) if d.get("url_path") == DASHBOARD["url_path"]),
            None,
        )
        if existing is None:
            created = await call({"type": "lovelace/dashboards/create", **DASHBOARD})
            assert created.get("success"), created
            print("dashboard created")
        else:
            print("dashboard exists")

        saved = await call(
            {"type": "lovelace/config/save", "url_path": DASHBOARD["url_path"], "config": CONFIG}
        )
        assert saved.get("success"), saved
        print("config saved")


asyncio.run(main())
