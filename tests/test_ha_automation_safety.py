from pathlib import Path

import yaml


AUTOMATIONS = Path("home-assistant/packages/weather_brain_automations.yaml")


def test_notifications_only_target_imminent_severe_weather():
    package = yaml.safe_load(AUTOMATIONS.read_text(encoding="utf-8"))
    notification_automations = [
        automation
        for automation in package["automation"]
        if any("notify." in str(action.get("service", "")) for action in automation.get("action", []))
    ]
    assert len(notification_automations) == 1
    automation = notification_automations[0]
    rendered = str(automation)
    assert "weather_brain_alert_level" not in rendered
    assert "severe_weather" in rendered
    assert "weather_brain_imminent_minutes" in rendered
    assert "below" in rendered
    assert "61" in rendered
