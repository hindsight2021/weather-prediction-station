from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import Prediction
from app.publisher import log_prediction
from verification.hazards import HAZARDS, observed_event
from verification.outcome_logger import alert_active_in_window, parse_cap_document
from verification.score import (
    SnapshotIndex,
    brier,
    build_scoreboard,
    contingency,
    reliability_bins,
)

BASE = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def iso(offset_hours: float) -> str:
    return (BASE + timedelta(hours=offset_hours)).isoformat()


def test_brier_known_values() -> None:
    assert brier([(1.0, 1), (0.0, 0)]) == 0.0
    assert brier([(0.5, 1), (0.5, 0)]) == 0.25
    assert brier([(0.7, 1)]) == pytest.approx(0.09)
    assert brier([]) is None


def test_reliability_bins_group_by_decile() -> None:
    pairs = [(0.05, 0), (0.05, 0), (0.95, 1), (1.0, 1)]
    bins = reliability_bins(pairs)
    assert bins[0]["n"] == 2
    assert bins[0]["observed_frequency"] == 0.0
    assert bins[9]["n"] == 2  # 0.95 and the p == 1.0 edge case
    assert bins[9]["observed_frequency"] == 1.0


def test_contingency_pod_far_csi() -> None:
    pairs = [(0.9, 1), (0.9, 0), (0.1, 1), (0.1, 0)]
    table = contingency(pairs, 0.4)
    assert table == {
        "tp": 1, "fp": 1, "fn": 1, "tn": 1,
        "pod": 0.5, "far": 0.5, "csi": pytest.approx(1 / 3),
    }


def test_observed_event_wind_and_rain_thresholds() -> None:
    # ECCC advisory-level gust event (>= 50 km/h)
    assert observed_event("wind_1h", [{"wind_gust_kmh": 55.0}])
    assert not observed_event("wind_1h", [{"wind_gust_kmh": 40.0}])
    assert observed_event("rain_1h", [{"rain_rate_mm_h": 1.2}])
    assert not observed_event("rain_1h", [{"rain_rate_mm_h": 0.0}])
    assert observed_event("heat_24h", [{"humidex": 37.0}])
    assert not observed_event("heat_24h", [{"humidex": 34.0}])


def test_alert_active_in_window() -> None:
    alert = {"onset": iso(1), "expires": iso(3)}
    assert alert_active_in_window(alert, BASE, BASE + timedelta(hours=2))
    assert not alert_active_in_window(alert, BASE - timedelta(hours=5), BASE - timedelta(hours=4))


def test_parse_cap_document_filters_by_area() -> None:
    xml = """<?xml version='1.0' encoding='UTF-8'?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>test-alert-1</identifier>
  <sent>2026-07-01T12:00:00-00:00</sent>
  <status>Actual</status>
  <msgType>Alert</msgType>
  <info>
    <language>en-CA</language>
    <event>thunderstorm</event>
    <severity>Moderate</severity>
    <urgency>Expected</urgency>
    <certainty>Likely</certainty>
    <headline>severe thunderstorm watch in effect</headline>
    <onset>2026-07-01T12:00:00-00:00</onset>
    <expires>2026-07-01T18:00:00-00:00</expires>
    <area><areaDesc>Fredericton and southern York County</areaDesc></area>
    <area><areaDesc>Moncton and southeast New Brunswick</areaDesc></area>
  </info>
  <info>
    <language>fr-CA</language>
    <event>orages</event>
    <area><areaDesc>Fredericton et le sud du comté d'York</areaDesc></area>
  </info>
</alert>"""
    rows = parse_cap_document(xml, ("fredericton",))
    assert len(rows) == 1
    row = rows[0]
    assert row["identifier"] == "test-alert-1"
    assert row["hazard"] == "storm"
    assert row["areas"] == ["Fredericton and southern York County"]

    assert parse_cap_document(xml, ("saint john",)) == []


def test_log_prediction_appends_timestamped_jsonl(tmp_path: Path) -> None:
    prediction = Prediction(
        storm_risk_1h=10, storm_risk_24h=20, wind_risk_1h=30, rain_risk_1h=40,
        lightning_risk_1h=0, confidence=80, level="normal", explanation="test",
    )
    log_path = tmp_path / "predictions.jsonl"
    log_prediction(prediction, str(log_path))
    log_prediction(prediction, str(log_path))

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record["rain_risk_1h"] == 40
    assert "timestamp" in record


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_build_scoreboard_end_to_end_with_known_brier(tmp_path: Path) -> None:
    # Two rain_1h predictions: p=0.8 followed by observed rain (outcome 1),
    # p=0.2 followed by dry weather (outcome 0) -> Brier = (0.04+0.04)/2 = 0.04.
    predictions = [
        {"timestamp": iso(0), "rain_risk_1h": 80},
        {"timestamp": iso(2), "rain_risk_1h": 20},
    ]
    snapshots = [
        {"timestamp": iso(-1), "rain_rate_mm_h": 0.0},
        {"timestamp": iso(0.5), "rain_rate_mm_h": 2.0},
        {"timestamp": iso(2.5), "rain_rate_mm_h": 0.0},
        {"timestamp": iso(3.5), "rain_rate_mm_h": 0.0},
    ]
    predictions_path = tmp_path / "predictions.jsonl"
    snapshots_path = tmp_path / "snapshots.jsonl"
    alerts_path = tmp_path / "alerts.jsonl"
    _write_jsonl(predictions_path, predictions)
    _write_jsonl(snapshots_path, snapshots)

    scoreboard = build_scoreboard(
        predictions_path=predictions_path,
        snapshots_path=snapshots_path,
        alerts_path=alerts_path,
        window_days=None,
    )
    rain = next(h for h in scoreboard["hazards"] if h["hazard"] == "rain_1h")
    assert rain["n"] == 2
    assert rain["event_rate"] == 0.5
    assert rain["brier"] == pytest.approx(0.04)
    # Climatology reference predicts the 0.5 base rate every time -> 0.25.
    assert rain["brier_climatology"] == pytest.approx(0.25)
    assert rain["brier_skill_vs_climatology"] == pytest.approx(1 - 0.04 / 0.25)
    assert rain["advisory_tier"] == {
        "tp": 1, "fp": 0, "fn": 0, "tn": 1, "pod": 1.0, "far": 0.0, "csi": 1.0,
    }


def test_scoreboard_skips_windows_not_covered_by_snapshots(tmp_path: Path) -> None:
    predictions = [{"timestamp": iso(0), "rain_risk_1h": 80}]
    # Snapshot log ends before the 1h window closes -> nothing scoreable.
    snapshots = [{"timestamp": iso(0.25), "rain_rate_mm_h": 0.0}]
    predictions_path = tmp_path / "predictions.jsonl"
    snapshots_path = tmp_path / "snapshots.jsonl"
    _write_jsonl(predictions_path, predictions)
    _write_jsonl(snapshots_path, snapshots)

    scoreboard = build_scoreboard(
        predictions_path=predictions_path,
        snapshots_path=snapshots_path,
        alerts_path=tmp_path / "alerts.jsonl",
        window_days=None,
    )
    rain = next(h for h in scoreboard["hazards"] if h["hazard"] == "rain_1h")
    assert rain["n"] == 0
    assert rain["brier"] is None


def test_storm_hazard_uses_alert_labels(tmp_path: Path) -> None:
    predictions = [
        {"timestamp": iso(0), "storm_risk_24h": 90},
        {"timestamp": iso(30), "storm_risk_24h": 10},
    ]
    # Snapshot coverage must span both 24h windows.
    snapshots = [{"timestamp": iso(h), "rain_rate_mm_h": 0.0} for h in range(0, 56, 6)]
    alerts = [
        {
            "identifier": "a1", "status": "Actual", "hazard": "storm",
            "event": "thunderstorm", "onset": iso(6), "expires": iso(9),
        }
    ]
    predictions_path = tmp_path / "predictions.jsonl"
    snapshots_path = tmp_path / "snapshots.jsonl"
    alerts_path = tmp_path / "alerts.jsonl"
    _write_jsonl(predictions_path, predictions)
    _write_jsonl(snapshots_path, snapshots)
    _write_jsonl(alerts_path, alerts)

    scoreboard = build_scoreboard(
        predictions_path=predictions_path,
        snapshots_path=snapshots_path,
        alerts_path=alerts_path,
        window_days=None,
    )
    storm = next(h for h in scoreboard["hazards"] if h["hazard"] == "storm_24h")
    assert storm["n"] == 2
    # Alert active inside the first window only: Brier = (0.01 + 0.01)/2.
    assert storm["brier"] == pytest.approx(0.01)


def test_observed_storm_from_convective_signature() -> None:
    # Heavy rain, damaging wind, or local lightning each count as an observed
    # storm, matching the training proxy_storm_event definition.
    assert observed_event("storm_1h", [{"rain_rate_mm_h": 12.0}])
    assert observed_event("storm_24h", [{"wind_gust_kmh": 70.0}])
    assert observed_event("storm_1h", [{"local_lightning_distance_km": 8.0}])
    assert observed_event("storm_1h", [{"local_lightning_count_30m": 2.0}])
    # A muggy but quiet hour is not a storm.
    assert not observed_event(
        "storm_1h", [{"rain_rate_mm_h": 1.0, "wind_gust_kmh": 20.0}]
    )


def test_storm_hazard_credits_observed_events_without_an_alert(tmp_path: Path) -> None:
    # No CAP alert, but the station observes heavy rain inside the first
    # window -> the obs source must fire so storm is scoreable on its own.
    predictions = [
        {"timestamp": iso(0), "storm_risk_24h": 90},
        {"timestamp": iso(30), "storm_risk_24h": 10},
    ]
    snapshots = [{"timestamp": iso(h), "rain_rate_mm_h": 0.0} for h in range(0, 56, 6)]
    snapshots.append({"timestamp": iso(6), "rain_rate_mm_h": 15.0})  # storm in window 1
    predictions_path = tmp_path / "predictions.jsonl"
    snapshots_path = tmp_path / "snapshots.jsonl"
    _write_jsonl(predictions_path, predictions)
    _write_jsonl(snapshots_path, sorted(snapshots, key=lambda r: r["timestamp"]))

    scoreboard = build_scoreboard(
        predictions_path=predictions_path,
        snapshots_path=snapshots_path,
        alerts_path=tmp_path / "alerts.jsonl",  # no alerts file
        window_days=None,
    )
    storm = next(h for h in scoreboard["hazards"] if h["hazard"] == "storm_24h")
    assert storm["n"] == 2
    # Observed storm in window 1 only: Brier = (0.1^2 + 0.1^2)/2 = 0.01.
    assert storm["brier"] == pytest.approx(0.01)


def test_storm_1h_has_a_forecast_baseline(tmp_path: Path) -> None:
    predictions = [{"timestamp": iso(0), "storm_risk_1h": 70}]
    snapshots = [
        {"timestamp": iso(-0.1), "forecast_next_severe_minutes": 30, "rain_rate_mm_h": 0.0},
        {"timestamp": iso(0.5), "rain_rate_mm_h": 12.0},  # storm occurs
        {"timestamp": iso(1.5), "rain_rate_mm_h": 0.0},
    ]
    predictions_path = tmp_path / "predictions.jsonl"
    snapshots_path = tmp_path / "snapshots.jsonl"
    _write_jsonl(predictions_path, predictions)
    _write_jsonl(snapshots_path, snapshots)

    scoreboard = build_scoreboard(
        predictions_path=predictions_path,
        snapshots_path=snapshots_path,
        alerts_path=tmp_path / "alerts.jsonl",
        window_days=None,
    )
    storm = next(h for h in scoreboard["hazards"] if h["hazard"] == "storm_1h")
    # A severe signal 30 min out -> forecast reference probability 1.0, and a
    # storm did occur, so the forecast baseline now exists and is perfect here.
    assert storm["n_forecast_reference"] == 1
    assert storm["brier_forecast"] == pytest.approx(0.0)


def test_every_hazard_maps_to_a_prediction_field() -> None:
    prediction_fields = set(
        Prediction(
            storm_risk_1h=0, storm_risk_24h=0, wind_risk_1h=0, rain_risk_1h=0,
            lightning_risk_1h=0, confidence=0, level="normal", explanation="",
        ).as_dict()
    )
    for spec in HAZARDS:
        assert spec.prediction_field in prediction_fields
