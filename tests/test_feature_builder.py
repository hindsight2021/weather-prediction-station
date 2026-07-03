from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.feature_builder import SnapshotStore
from app.models import WeatherSnapshot


def test_pressure_delta_uses_closest_snapshot_to_requested_window() -> None:
    base = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    store = SnapshotStore(maxlen=10)
    store.add(WeatherSnapshot(timestamp=base, pressure_hpa=1012.0))
    store.add(WeatherSnapshot(timestamp=base + timedelta(minutes=30), pressure_hpa=1010.0))
    store.add(WeatherSnapshot(timestamp=base + timedelta(hours=1), pressure_hpa=1008.5))

    assert store.pressure_delta(1) == -3.5


def test_recent_max_values_ignore_old_snapshots() -> None:
    base = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    store = SnapshotStore(maxlen=10)
    store.add(WeatherSnapshot(timestamp=base, wind_gust_kmh=99.0, rain_rate_mm_h=20.0))
    store.add(WeatherSnapshot(timestamp=base + timedelta(minutes=40), wind_gust_kmh=45.0, rain_rate_mm_h=4.5))
    store.add(WeatherSnapshot(timestamp=base + timedelta(minutes=50), wind_gust_kmh=52.0, rain_rate_mm_h=6.0))

    assert store.max_wind_gust(30) == 52.0
    assert store.max_rain_rate(30) == 6.0
