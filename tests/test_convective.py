from __future__ import annotations

from datetime import datetime, timezone

from app.environmental import parse_convective
from app.feature_builder import SnapshotStore
from app.models import WeatherSnapshot
from app.risk_rules import _convective_potential, score_weather

THRESHOLDS = {
    "wind_gust_watch_kmh": 45.0,
    "wind_gust_warning_kmh": 65.0,
    "rain_rate_watch_mm_h": 4.0,
    "rain_rate_warning_mm_h": 10.0,
    "lightning_nearby_km": 25.0,
}


def _open_meteo(cape, cin, li, hour="12") -> dict:
    return {
        "hourly": {
            "time": [f"2026-07-23T{h:02d}:00" for h in range(24)],
            "cape": [cape] * 24,
            "convective_inhibition": [cin] * 24,
            "lifted_index": [li] * 24,
        }
    }


def test_parse_convective_picks_current_hour() -> None:
    data = {
        "hourly": {
            "time": ["2026-07-23T11:00", "2026-07-23T12:00", "2026-07-23T13:00"],
            "cape": [100.0, 2400.0, 300.0],
            "convective_inhibition": [10.0, 5.0, 60.0],
            "lifted_index": [1.0, -6.0, 0.5],
        }
    }
    now = datetime(2026, 7, 23, 12, 30, tzinfo=timezone.utc)
    result = parse_convective(data, now)
    assert result == {"cape": 2400.0, "convective_inhibition": 5.0, "lifted_index": -6.0}


def test_parse_convective_falls_back_and_skips_missing() -> None:
    data = {"hourly": {"time": ["2026-07-23T00:00"], "cape": [None], "lifted_index": [-3.0]}}
    now = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)  # 09:00 absent -> index 0
    result = parse_convective(data, now)
    # cape is None (skipped), convective_inhibition absent, lifted_index present.
    assert result == {"lifted_index": -3.0}


def test_parse_convective_empty_response_is_safe() -> None:
    assert parse_convective({}, datetime.now(timezone.utc)) == {}


def test_convective_potential_high_when_unstable_and_uncapped() -> None:
    score, label = _convective_potential(cape=2500.0, cin=0.0, lifted_index=-6.0)
    assert label == "strong"
    assert score >= 60.0


def test_convective_potential_suppressed_by_strong_cap() -> None:
    capped, _ = _convective_potential(cape=2500.0, cin=300.0, lifted_index=-6.0)
    uncapped, _ = _convective_potential(cape=2500.0, cin=0.0, lifted_index=-6.0)
    assert capped < uncapped
    assert capped == 0.0  # CIN >= 250 fully suppresses


def test_convective_potential_zero_without_fields() -> None:
    assert _convective_potential(None, None, None) == (0.0, "none")


def test_instability_raises_storm_risk_and_explains() -> None:
    base = datetime(2026, 7, 23, 18, 0, tzinfo=timezone.utc)
    store = SnapshotStore(maxlen=10)
    quiet = WeatherSnapshot(timestamp=base, temperature_c=28.0, humidity_pct=60.0, pressure_hpa=1010.0)
    store.add(quiet)
    without = score_weather(quiet, store, THRESHOLDS)

    unstable = WeatherSnapshot(
        timestamp=base, temperature_c=28.0, humidity_pct=60.0, pressure_hpa=1010.0,
        cape=2600.0, convective_inhibition=10.0, lifted_index=-6.0,
    )
    store2 = SnapshotStore(maxlen=10)
    store2.add(unstable)
    with_convective = score_weather(unstable, store2, THRESHOLDS)

    assert with_convective.storm_risk_1h > without.storm_risk_1h
    assert "convective instability" in with_convective.explanation


def test_no_convective_fields_leaves_score_unchanged() -> None:
    # A snapshot with no CAPE/LI must score exactly as before the feature existed.
    base = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    store = SnapshotStore(maxlen=10)
    snapshot = WeatherSnapshot(
        timestamp=base, temperature_c=20.0, humidity_pct=55.0, pressure_hpa=1015.0,
        wind_gust_kmh=10.0, rain_rate_mm_h=0.0, radar_precip_nearby=0.0,
    )
    store.add(snapshot)
    prediction = score_weather(snapshot, store, THRESHOLDS)
    assert prediction.storm_risk_1h < 40
    assert "convective" not in prediction.explanation
