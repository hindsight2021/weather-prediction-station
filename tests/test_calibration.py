from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier

from training.train_models import (
    MIN_MINORITY_FOR_CALIBRATION,
    train_model,
)


def _separable_binary(n: int = 400, positive_rate: float = 0.3, seed: int = 7):
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < positive_rate).astype(int)
    # A feature that carries real signal plus noise, so calibration has
    # something to map onto observed frequencies.
    x = y + rng.normal(0, 1.0, n)
    X = pd.DataFrame({"f0": x, "f1": rng.normal(0, 1, n)})
    return X, pd.Series(y)


def test_train_model_calibrates_when_enough_positives() -> None:
    X, y = _separable_binary()
    model = train_model(X, y, calibrate=True)
    assert isinstance(model, CalibratedClassifierCV)
    probs = model.predict_proba(X)
    # Valid probability simplex.
    assert probs.shape == (len(X), 2)
    assert np.all(probs >= 0.0) and np.all(probs <= 1.0)
    assert np.allclose(probs.sum(axis=1), 1.0)


def test_train_model_skips_calibration_when_positives_are_too_rare() -> None:
    X, y = _separable_binary(n=200, positive_rate=0.0, seed=1)
    # Inject just a couple of positives -- below the calibration floor.
    y.iloc[:2] = 1
    assert int(y.sum()) < MIN_MINORITY_FOR_CALIBRATION
    model = train_model(X, y, calibrate=True)
    assert isinstance(model, HistGradientBoostingClassifier)


def test_calibrate_false_returns_raw_estimator() -> None:
    X, y = _separable_binary()
    model = train_model(X, y, calibrate=False)
    assert isinstance(model, HistGradientBoostingClassifier)


def test_calibration_does_not_worsen_brier_on_holdout() -> None:
    from sklearn.metrics import brier_score_loss

    X, y = _separable_binary(n=600, seed=3)
    cut = 400
    Xtr, Xte = X.iloc[:cut], X.iloc[cut:]
    ytr, yte = y.iloc[:cut], y.iloc[cut:]

    raw = train_model(Xtr, ytr, calibrate=False)
    cal = train_model(Xtr, ytr, calibrate=True)

    raw_brier = brier_score_loss(yte, raw.predict_proba(Xte)[:, 1])
    cal_brier = brier_score_loss(yte, cal.predict_proba(Xte)[:, 1])
    # Calibration should not meaningfully regress the Brier score.
    assert cal_brier <= raw_brier + 0.02
