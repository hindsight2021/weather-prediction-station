from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.feature_builder import SnapshotStore
from app.models import WeatherSnapshot
from features.transforms import (
    CONVECTIVE_FEATURES,
    FEATURES,
    build_inference_row,
    model_feature_columns,
)
from training.train_models import train_model


def test_features_contract_stays_surface_only() -> None:
    # The canonical FEATURES list must not silently gain convective columns;
    # backward compatibility for existing models depends on it.
    for column in CONVECTIVE_FEATURES:
        assert column not in FEATURES


def test_model_feature_columns_adds_convective_when_present() -> None:
    without = model_feature_columns(FEATURES)
    assert without == FEATURES

    with_conv = model_feature_columns(FEATURES + ["cape", "lifted_index", "unrelated"])
    assert with_conv == FEATURES + ["cape", "lifted_index"]
    # Order is stable and convective columns come last.
    assert with_conv[: len(FEATURES)] == FEATURES


def test_build_inference_row_always_supplies_convective_keys() -> None:
    store = SnapshotStore(maxlen=10)
    snap = WeatherSnapshot(
        timestamp=datetime(2026, 7, 23, 18, 0, tzinfo=timezone.utc),
        temperature_c=25.0, humidity_pct=60.0, wind_speed_kmh=10.0, pressure_hpa=1008.0,
        cape=1800.0, convective_inhibition=20.0, lifted_index=-4.0,
    )
    store.add(snap)
    row = build_inference_row(snap, store)
    assert row["cape"] == 1800.0
    assert row["lifted_index"] == -4.0
    # Present as keys even when the snapshot lacks them.
    bare = WeatherSnapshot(timestamp=snap.timestamp, temperature_c=25.0)
    store2 = SnapshotStore(maxlen=10)
    store2.add(bare)
    bare_row = build_inference_row(bare, store2)
    assert bare_row["cape"] is None
    assert "convective_inhibition" in bare_row


def _training_frame(n: int = 300, with_cape: bool = True, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = {feature: rng.normal(0, 1, n) for feature in FEATURES}
    frame = pd.DataFrame(data)
    if with_cape:
        cape = rng.normal(500, 300, n)
        frame["cape"] = cape
        frame["convective_inhibition"] = rng.normal(30, 10, n)
        frame["lifted_index"] = rng.normal(0, 2, n)
        # Target correlates with instability so the extra columns matter.
        y = ((cape > 700) | (frame["lifted_index"] < -1)).astype(int)
    else:
        y = (frame[FEATURES[0]] > 0).astype(int)
    frame["target"] = y
    return frame


def test_training_uses_convective_columns_and_tolerates_nan() -> None:
    frame = _training_frame(with_cape=True)
    # A few NaN CAPE gaps must not break the gradient-boosted fit.
    frame.loc[frame.index[:5], "cape"] = np.nan
    model_features = model_feature_columns(frame.columns)
    assert "cape" in model_features

    model = train_model(frame[model_features], frame["target"], calibrate=False)
    probs = model.predict_proba(frame[model_features])
    assert probs.shape == (len(frame), 2)


def test_training_falls_back_to_surface_only_without_cape() -> None:
    frame = _training_frame(with_cape=False)
    model_features = model_feature_columns(frame.columns)
    assert model_features == FEATURES
