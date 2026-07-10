from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.feature_builder import SnapshotStore
from app.models import WeatherSnapshot
from app.risk_rules import clamp_score, score_weather


THRESHOLDS = {
    "wind_gust_watch_kmh": 45.0,
    "wind_gust_warning_kmh": 65.0,
    "rain_rate_watch_mm_h": 4.0,
    "rain_rate_warning_mm_h": 10.0,
    "lightning_nearby_km": 25.0,
}


def test_clamp_score_bounds_values() -> None:
    assert clamp_score(-10) == 0
    assert clamp_score(45.2) == 45
    assert clamp_score(150) == 100


def test_score_weather_promotes_warning_for_nearby_lightning_and_gusts() -> None:
    base = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    store = SnapshotStore(maxlen=100)
    store.add(WeatherSnapshot(timestamp=base - timedelta(hours=1), pressure_hpa=1012.0))

    snapshot = WeatherSnapshot(
        timestamp=base,
        temperature_c=24.0,
        humidity_pct=88.0,
        pressure_hpa=1008.0,
        wind_gust_kmh=68.0,
        rain_rate_mm_h=8.0,
        local_lightning_distance_km=12.0,
        local_lightning_count_30m=4.0,
        internet_lightning_count_30m=8.0,
        radar_precip_nearby=1.0,
    )
    store.add(snapshot)

    prediction = score_weather(snapshot, store, THRESHOLDS)

    assert prediction.level == "warning"
    assert prediction.wind_risk_1h == 90
    assert prediction.lightning_risk_1h >= 85
    assert prediction.storm_risk_1h >= 60
    assert "lightning signal active" in prediction.explanation


def test_score_weather_stays_normal_when_inputs_are_quiet() -> None:
    base = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    store = SnapshotStore(maxlen=100)
    store.add(WeatherSnapshot(timestamp=base - timedelta(hours=1), pressure_hpa=1015.0))
    snapshot = WeatherSnapshot(
        timestamp=base,
        temperature_c=20.0,
        humidity_pct=55.0,
        pressure_hpa=1015.2,
        wind_gust_kmh=10.0,
        rain_rate_mm_h=0.0,
        radar_precip_nearby=0.0,
    )
    store.add(snapshot)

    prediction = score_weather(snapshot, store, THRESHOLDS)

    assert prediction.level == "normal"
    assert prediction.storm_risk_1h < 40
    assert prediction.explanation == "No strong local severe-weather signal detected."


def test_score_weather_adds_heat_advisory_from_humidex() -> None:
    base = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    store = SnapshotStore(maxlen=100)
    snapshot = WeatherSnapshot(timestamp=base, temperature_c=30.0, humidex=36.0, humidity_pct=70.0)
    store.add(snapshot)

    prediction = score_weather(snapshot, store, THRESHOLDS)

    assert prediction.level == "watch"
    assert prediction.heat_severity == "moderate"
    assert prediction.heat_risk_24h >= 65


def test_score_weather_adds_cold_warning_from_wind_chill() -> None:
    base = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
    store = SnapshotStore(maxlen=100)
    snapshot = WeatherSnapshot(timestamp=base, temperature_c=-22.0, wind_chill_c=-31.0, humidity_pct=50.0)
    store.add(snapshot)

    prediction = score_weather(snapshot, store, THRESHOLDS)

    assert prediction.level == "warning"
    assert prediction.cold_severity == "severe"
    assert prediction.cold_risk_24h >= 90


def test_current_rain_can_never_publish_zero_risk() -> None:
    snapshot = WeatherSnapshot(rain_rate_mm_h=2.0)
    store = SnapshotStore(maxlen=10)
    store.add(snapshot)
    prediction = score_weather(snapshot, store, THRESHOLDS)
    assert prediction.rain_risk_1h >= 85
    assert prediction.imminent_event == "rain"
    assert prediction.imminent_minutes == 0


def test_hourly_forecast_drives_real_24h_and_imminent_prediction() -> None:
    snapshot = WeatherSnapshot(
        forecast_precip_probability_1h=90,
        forecast_precip_probability_24h=95,
        forecast_precip_mm_1h=3,
        forecast_precip_mm_24h=12,
        forecast_wind_gust_max_24h=70,
        forecast_next_precip_minutes=35,
        forecast_severe_condition_24h=1,
        forecast_source_count=2,
    )
    store = SnapshotStore(maxlen=10)
    store.add(snapshot)
    prediction = score_weather(snapshot, store, THRESHOLDS)
    assert prediction.rain_risk_1h >= 90
    assert prediction.rain_risk_24h >= 95
    assert prediction.wind_risk_24h >= 90
    assert prediction.storm_risk_24h >= 85
    assert prediction.imminent_minutes == 35
    assert prediction.level == "warning"
