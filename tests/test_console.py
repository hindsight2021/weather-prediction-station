from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import console.app as console_app


def test_api_state_aggregates_cache_and_logs(tmp_path, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    predictions = tmp_path / "predictions.jsonl"
    snapshots = tmp_path / "weather_snapshots.jsonl"
    predictions.write_text(
        json.dumps({"timestamp": (now - timedelta(hours=1)).isoformat(), "storm_risk_1h": 40}) + "\n",
        encoding="utf-8",
    )
    snapshots.write_text(
        json.dumps({"timestamp": (now - timedelta(hours=1)).isoformat(), "temperature_c": 21.5}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(console_app, "PREDICTIONS_PATH", predictions)
    monkeypatch.setattr(console_app, "SNAPSHOTS_PATH", snapshots)
    monkeypatch.setattr(console_app, "SCOREBOARD_PATH", tmp_path / "missing.json")
    with console_app._cache_lock:
        console_app._cache["prediction"] = {"storm_risk_1h": 40, "level": "normal"}
        console_app._cache["availability"] = "online"

    client = console_app.app.test_client()
    response = client.get("/api/state")
    assert response.status_code == 200
    body = response.get_json()
    assert body["availability"] == "online"
    assert body["prediction"]["level"] == "normal"
    assert len(body["history"]["risks"]) == 1
    assert body["history"]["environment"][0]["temperature_c"] == 21.5
    assert body["verification"] is None


def test_index_serves_console_page() -> None:
    client = console_app.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"Kingsclear Atmospheric Intelligence" in response.data
