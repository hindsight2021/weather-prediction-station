from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.feature_builder import SnapshotStore
from app.models import WeatherSnapshot
from app.risk_rules import score_weather
from features.transforms import FEATURES, build_inference_row, magnus_dew_point
from training.train_models import (
    FEATURES as TRAINING_FEATURES,
    apply_feedback,
    add_thermal_proxy_targets,
    chronological_split,
)

THRESHOLDS = {
    "wind_gust_watch_kmh": 45.0,
    "wind_gust_warning_kmh": 65.0,
    "rain_rate_watch_mm_h": 4.0,
    "rain_rate_warning_mm_h": 10.0,
    "lightning_nearby_km": 25.0,
}

BASE = datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc)


# --- roadmap §4.3: shared feature pipeline -----------------------------------

def test_magnus_dew_point_reference_values() -> None:
    # Standard psychrometric reference points.
    assert magnus_dew_point(20.0, 50.0) == pytest.approx(9.3, abs=0.2)
    assert magnus_dew_point(30.0, 80.0) == pytest.approx(26.2, abs=0.3)
    assert magnus_dew_point(20.0, 100.0) == pytest.approx(20.0, abs=0.05)
    assert magnus_dew_point(None, 50.0) is None
    assert magnus_dew_point(20.0, None) is None


def test_training_and_inference_share_one_feature_list() -> None:
    assert TRAINING_FEATURES is FEATURES


def test_inference_row_uses_magnus_not_linear_approximation() -> None:
    store = SnapshotStore(maxlen=10)
    snapshot = WeatherSnapshot(timestamp=BASE, temperature_c=20.0, humidity_pct=50.0)
    store.add(snapshot)
    row = build_inference_row(snapshot, store)
    # Old approximation was T - (100-RH)/5 = 10.0; Magnus gives ~9.3.
    assert row["dew_point_c"] == pytest.approx(9.3, abs=0.2)
    assert set(FEATURES) <= set(row)


# --- roadmap §4.4: no zero-imputation of level features ----------------------

def _quiet_snapshot(offset_hours: float, **overrides) -> WeatherSnapshot:
    defaults = dict(
        timestamp=BASE + timedelta(hours=offset_hours),
        temperature_c=21.0,
        humidity_pct=60.0,
        pressure_hpa=1013.0,
        wind_speed_kmh=10.0,
    )
    defaults.update(overrides)
    return WeatherSnapshot(**defaults)


class _StubModel:
    classes_ = [0, 1]

    def __init__(self) -> None:
        self.seen = None

    def predict_proba(self, frame):
        self.seen = frame
        return [[0.4, 0.6]]


def _predictor_with_stub(tmp_path):
    from inference.ml_predictor import MLPredictor

    predictor = MLPredictor(models_dir=tmp_path / "no_models")
    stub = _StubModel()
    predictor.models = {"wind_1h": stub}
    predictor.model_features = {"wind_1h": list(FEATURES)}
    predictor.model_kinds = {"wind_1h": "binary"}
    return predictor, stub


def test_missing_pressure_is_imputed_from_history_not_zero(tmp_path) -> None:
    predictor, stub = _predictor_with_stub(tmp_path)
    store = SnapshotStore(maxlen=100)
    for hour in range(-6, 0):
        store.add(_quiet_snapshot(hour, pressure_hpa=1010.0 + hour * 0.1))
    current = _quiet_snapshot(0, pressure_hpa=None)
    store.add(current)

    result = predictor.predict(current, store)

    assert not result.degraded
    assert result.probabilities["wind_1h"] == pytest.approx(0.6)
    seen_pressure = float(stub.seen["station_pressure_hpa"].iloc[0])
    assert 1005.0 < seen_pressure < 1015.0  # median of history, never 0.0


def test_unimputable_level_feature_skips_model_and_flags_degraded(tmp_path) -> None:
    predictor, stub = _predictor_with_stub(tmp_path)
    store = SnapshotStore(maxlen=100)
    current = _quiet_snapshot(0, pressure_hpa=None)  # no history to impute from
    store.add(current)

    result = predictor.predict(current, store)

    assert result.degraded
    assert result.skipped_models == ["wind_1h"]
    assert result.probabilities == {}
    assert stub.seen is None


# --- roadmap §4.1: chronological evaluation ----------------------------------

def test_chronological_split_takes_the_tail_per_station() -> None:
    rows = []
    for station in ("A", "B"):
        for hour in range(10):
            rows.append({
                "station_name": station,
                "timestamp": (BASE + timedelta(hours=hour)).isoformat(),
            })
    df = pd.DataFrame(rows)
    mask = chronological_split(df, test_fraction=0.2)
    for station in ("A", "B"):
        station_rows = df[df["station_name"] == station]
        test_times = pd.to_datetime(station_rows[mask.loc[station_rows.index]]["timestamp"])
        train_times = pd.to_datetime(station_rows[~mask.loc[station_rows.index]]["timestamp"])
        assert len(test_times) == 2
        assert test_times.min() > train_times.max()


# --- roadmap §4.2: feedback labels are target-specific -----------------------

def _training_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [(BASE + timedelta(hours=h)).isoformat() for h in range(3)],
            "proxy_convective_risk_now": [1.0, 1.0, 0.0],
            "proxy_storm_event_24h": [1.0, 1.0, 0.0],
            "proxy_wind_event_1h": [0.0, 0.0, 0.0],
            "proxy_heat_disturbance_24h": [0, 1, 3],
            "proxy_cold_disturbance_24h": [0, 0, 0],
        }
    )


def test_false_alarm_for_storm_only_clears_storm_targets() -> None:
    feedback = pd.DataFrame(
        [{"timestamp": BASE.isoformat(), "label": "false_alarm", "hazard": "storm", "severity": ""}]
    )
    result = apply_feedback(_training_frame(), feedback)
    assert result.at[0, "proxy_convective_risk_now"] == 0.0
    assert result.at[0, "proxy_storm_event_24h"] == 0.0
    # Untouched hazards keep their labels.
    assert result.at[0, "proxy_wind_event_1h"] == 0.0
    assert result.at[0, "proxy_heat_disturbance_24h"] == 0


def test_heat_feedback_applies_severity_class_not_binary_one() -> None:
    feedback = pd.DataFrame(
        [{"timestamp": (BASE + timedelta(hours=2)).isoformat(), "label": "missed_event",
          "hazard": "heat", "severity": "severe"}]
    )
    result = apply_feedback(_training_frame(), feedback)
    assert result.at[2, "proxy_heat_disturbance_24h"] == 3
    # A heat report must not teach the storm/wind models an event occurred.
    assert result.at[2, "proxy_storm_event_24h"] == 0.0
    assert result.at[2, "proxy_wind_event_1h"] == 0.0


def test_legacy_labels_map_to_their_hazard_and_unknown_rows_are_skipped() -> None:
    feedback = pd.DataFrame(
        [
            {"timestamp": BASE.isoformat(), "label": "wind_warning", "hazard": "", "severity": ""},
            {"timestamp": BASE.isoformat(), "label": "correct_prediction", "hazard": "", "severity": ""},
        ]
    )
    result = apply_feedback(_training_frame(), feedback)
    assert result.at[0, "proxy_wind_event_1h"] == 1.0
    # The hazardless legacy "correct_prediction" cannot be attributed; nothing
    # else may change.
    assert result.at[0, "proxy_heat_disturbance_24h"] == 0


# --- roadmap §4.5: ECCC-aligned thermal proxies ------------------------------

def test_thermal_targets_use_eccc_humidex_36_criterion() -> None:
    frame = pd.DataFrame(
        {
            "station_name": ["S"] * 3,
            "timestamp": [(BASE + timedelta(hours=h)).isoformat() for h in range(3)],
            "temp_c": [28.0, 28.0, 28.0],
            "humidex": [30.0, 35.0, 37.0],
        }
    )
    result = add_thermal_proxy_targets(frame)
    # Hour 1 sees future max humidex 37 -> class 2 (warning criterion 36).
    assert result["proxy_heat_disturbance_24h"].iloc[1] == 2
    # A 35 humidex alone (hour 2 has no future above it) is not warning-class.
    assert result["proxy_heat_disturbance_24h"].iloc[2] == 0


def test_two_day_temperature_pattern_promotes_heat_class() -> None:
    rows = []
    for day in range(2):
        for hour in range(24):
            timestamp = BASE.replace(hour=0) + timedelta(days=day, hours=hour)
            temp = 18.0 + (14.0 if 10 <= hour <= 18 else 0.0)  # Tmax 32, Tmin 18
            rows.append({
                "station_name": "S",
                "timestamp": timestamp.isoformat(),
                "temp_c": temp,
                "humidex": 33.0,  # below the 36 humidex criterion all along
            })
    result = add_thermal_proxy_targets(pd.DataFrame(rows))
    # Both days satisfy Tmax>=29/Tmin>=16 -> warning-level class despite humidex < 36.
    assert (result["proxy_heat_disturbance_24h"].iloc[:24] >= 2).all()


# --- roadmap §4.6: heat risk reads warning proximity -------------------------

def test_july_afternoon_humidex_34_scores_below_45() -> None:
    # Roadmap acceptance fixture: humidex 34, no forecast triggers ->
    # heat_risk well under 45 (the old curve published 65+ here).
    store = SnapshotStore(maxlen=100)
    snapshot = WeatherSnapshot(
        timestamp=BASE, temperature_c=29.0, humidex=34.0, humidity_pct=55.0,
        forecast_temp_max_24h=34.0,
    )
    store.add(snapshot)
    prediction = score_weather(snapshot, store, THRESHOLDS)
    assert prediction.heat_risk_24h < 45
    # Warm now with nothing hotter coming reads "ongoing", never warning-level.
    assert prediction.heat_severity in ("mild", "ongoing")
    assert prediction.level in ("normal", "advisory")


def test_forecast_above_eccc_criterion_maps_to_warning_proximity() -> None:
    store = SnapshotStore(maxlen=100)
    snapshot = WeatherSnapshot(
        timestamp=BASE, temperature_c=27.0, humidex=30.0, humidity_pct=70.0,
        forecast_temp_max_24h=38.0,
    )
    store.add(snapshot)
    prediction = score_weather(snapshot, store, THRESHOLDS)
    # Heat above the ECCC criterion (36) incoming within 24h -> score >= 65.
    assert prediction.heat_risk_24h >= 65
    assert prediction.heat_severity == "moderate"
