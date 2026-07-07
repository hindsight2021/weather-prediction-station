from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.feature_builder import SnapshotStore
from app.main import parse_float
from app.models import WeatherSnapshot
from app.risk_rules import clamp_score, score_weather


def test_clamp_score_bounds_values() -> None:
    assert clamp_score(-5) == 0
    assert clamp_score(42.4) == 42
    assert clamp_score(42.6) == 43
    assert clamp_score(150) == 100


def test_parse_float_treats_explicit_unavailable_payload_as_missing() -> None:
    assert parse_float('{"value": null, "state": "unavailable"}') is None
    assert parse_float('{"value": "unknown"}') is None


def test_snapshot_store_calculates_pressure_delta() -> None:
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = SnapshotStore(maxlen=10)

    store.add(WeatherSnapshot(timestamp=base_time, pressure_hpa=1012.0))
    store.add(WeatherSnapshot(timestamp=base_time + timedelta(hours=1), pressure_hpa=1009.5))

    assert store.pressure_delta(1) == -2.5


def test_score_weather_returns_warning_for_nearby_lightning_and_gusts() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    store = SnapshotStore(maxlen=10)
    store.add(WeatherSnapshot(timestamp=now - timedelta(hours=1), pressure_hpa=1010.0, wind_gust_kmh=20.0))

    snapshot = WeatherSnapshot(
        timestamp=now,
        temperature_c=26.0,
        humidity_pct=88.0,
        pressure_hpa=1007.0,
        wind_gust_kmh=68.0,
        rain_rate_mm_h=12.0,
        local_lightning_distance_km=12.0,
        local_lightning_count_30m=5,
        internet_lightning_count_30m=10,
        radar_precip_nearby=1.0,
    )
    store.add(snapshot)

    prediction = score_weather(
        snapshot,
        store,
        thresholds={
            "wind_gust_watch_kmh": 45.0,
            "wind_gust_warning_kmh": 65.0,
            "rain_rate_watch_mm_h": 4.0,
            "rain_rate_warning_mm_h": 10.0,
            "lightning_nearby_km": 25.0,
        },
    )

    assert prediction.level == "warning"
    assert prediction.wind_risk_1h >= 90
    assert prediction.rain_risk_1h >= 90
    assert prediction.lightning_risk_1h >= 85
    assert prediction.confidence > 50
    assert "lightning" in prediction.explanation.lower()
