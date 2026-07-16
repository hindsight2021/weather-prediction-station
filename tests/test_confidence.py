from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.feature_builder import SnapshotStore
from app.models import WeatherSnapshot
from app.risk_rules import score_weather

THRESHOLDS: dict[str, float] = {}
BASE = datetime(2026, 7, 16, 15, 0, tzinfo=timezone.utc)


def _full_snapshot(offset_hours: float = 0.0) -> WeatherSnapshot:
    return WeatherSnapshot(
        timestamp=BASE + timedelta(hours=offset_hours),
        temperature_c=22.0, humidity_pct=60.0, pressure_hpa=1013.0,
        wind_speed_kmh=10.0, wind_gust_kmh=18.0, rain_rate_mm_h=0.0,
        humidex=24.0, local_lightning_distance_km=60.0, radar_precip_nearby=0.0,
        forecast_precip_probability_24h=20.0, forecast_wind_gust_max_24h=30.0,
        forecast_source_count=2.0,
    )


def test_confidence_is_capped_below_100_even_with_perfect_inputs() -> None:
    store = SnapshotStore(maxlen=500)
    for hour in range(-48, 1):
        store.add(_full_snapshot(hour / 4))
    prediction = score_weather(_full_snapshot(), store, THRESHOLDS)
    assert prediction.confidence <= 92


def test_confidence_degrades_with_missing_inputs_and_no_history() -> None:
    store = SnapshotStore(maxlen=10)
    sparse = WeatherSnapshot(timestamp=BASE, temperature_c=20.0)
    store.add(sparse)
    prediction = score_weather(sparse, store, THRESHOLDS)
    assert prediction.confidence < 45


def test_confidence_rewards_more_data() -> None:
    sparse_store = SnapshotStore(maxlen=10)
    sparse = WeatherSnapshot(timestamp=BASE, temperature_c=20.0, humidity_pct=50.0)
    sparse_store.add(sparse)
    sparse_conf = score_weather(sparse, sparse_store, THRESHOLDS).confidence

    rich_store = SnapshotStore(maxlen=500)
    for hour in range(-24, 1):
        rich_store.add(_full_snapshot(hour / 4))
    rich_conf = score_weather(_full_snapshot(), rich_store, THRESHOLDS).confidence

    assert rich_conf > sparse_conf


def test_nearest_fire_flows_to_prediction() -> None:
    store = SnapshotStore(maxlen=10)
    snapshot = WeatherSnapshot(
        timestamp=BASE, temperature_c=20.0,
        active_fires_nearby=2.0, nearest_fire_km=37.5, nb_burn_category=2.0,
    )
    store.add(snapshot)
    prediction = score_weather(snapshot, store, THRESHOLDS)
    assert prediction.nearest_fire_km == 37.5
    assert prediction.nb_burn_category == 2
    assert prediction.as_dict()["nearest_fire_km"] == 37.5
