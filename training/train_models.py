#!/usr/bin/env python3
"""Train machine learning models for weather prediction using the processed ECCC dataset.

Safety gate: a freshly trained model only replaces the live model file if it
does not score worse than the model currently in production, evaluated on the
same chronological holdout. This prevents a single noisy feedback submission
from pushing a regressed model straight into the live severe-weather sensors.
The gate compares Brier score (lower is better — the roadmap's headline
metric); the first model ever trained for a target is accepted as baseline.
"""

import argparse
import json
import logging
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, classification_report, roc_auc_score

from features.transforms import CONVECTIVE_FEATURES, FEATURES

LOGGER = logging.getLogger("train_models")

DEFAULT_DATASET = Path("data/processed/weather_features.csv.gz")
DEFAULT_MODELS_DIR = Path("models")

TEST_FRACTION = 0.2

# A candidate must have Brier <= previous Brier + tolerance to be promoted.
BRIER_REGRESSION_TOLERANCE = 0.005

# Probability calibration folds. Each fold must hold both classes, so a target
# needs at least this many minority-class samples before we attempt to
# calibrate; below it we ship the raw model rather than risk a fit failure.
CALIBRATION_FOLDS = 3
MIN_MINORITY_FOR_CALIBRATION = CALIBRATION_FOLDS * 2

TARGETS = {
    "convective_risk": {"target": "proxy_convective_risk_now", "kind": "binary"},
    "wind_1h": {"target": "proxy_wind_event_1h", "kind": "binary"},
    "storm_24h": {"target": "proxy_storm_event_24h", "kind": "binary"},
    "heat_disturbance_24h": {"target": "proxy_heat_disturbance_24h", "kind": "multiclass"},
    "cold_disturbance_24h": {"target": "proxy_cold_disturbance_24h", "kind": "multiclass"},
}

# Which proxy target columns a per-hazard feedback label may touch. A heat
# report must never rewrite the storm/wind/cold targets (roadmap §4.2).
HAZARD_TO_TARGET_COLUMNS = {
    "storm": ["proxy_convective_risk_now", "proxy_storm_event_24h"],
    "wind": ["proxy_wind_event_1h"],
    "heat": ["proxy_heat_disturbance_24h"],
    "cold": ["proxy_cold_disturbance_24h"],
}

MULTICLASS_TARGETS = {"proxy_heat_disturbance_24h", "proxy_cold_disturbance_24h"}

SEVERITY_TO_CLASS = {"mild": 1, "moderate": 2, "severe": 3}

# Legacy single-select labels from the original HA helper, mapped to a hazard
# so old feedback rows keep working.
LEGACY_LABEL_TO_HAZARD = {
    "thunderstorm_warning": "storm",
    "thunderstorm_watch": "storm",
    "winter_storm_warning": "storm",
    "wind_warning": "wind",
    "heat_warning": "heat",
    "cold_warning": "cold",
}


def load_data(path: Path) -> pd.DataFrame:
    LOGGER.info(f"Loading dataset from {path}")
    return pd.read_csv(path)


def _future_window_max(values: pd.Series, hours: int) -> pd.Series:
    return values.shift(-1).iloc[::-1].rolling(window=hours, min_periods=1).max().iloc[::-1]


def _future_window_min(values: pd.Series, hours: int) -> pd.Series:
    return values.shift(-1).iloc[::-1].rolling(window=hours, min_periods=1).min().iloc[::-1]


def _two_day_heat_pattern_dates(station_frame: pd.DataFrame) -> set:
    """Dates that start an ECCC-style two-day heat event.

    ECCC's southern NB heat warning also triggers on two consecutive days with
    Tmax >= 29 C and Tmin >= 16 C even when humidex stays below 36.
    """
    if "temp_c" not in station_frame or station_frame["temp_c"].dropna().empty:
        return set()
    timestamps = pd.to_datetime(station_frame["timestamp"])
    daily = station_frame.assign(_date=timestamps.dt.date).groupby("_date")["temp_c"]
    tmax = daily.max()
    tmin = daily.min()
    hot_day = (tmax >= 29.0) & (tmin >= 16.0)
    return {date for date, flag in (hot_day & hot_day.shift(-1)).items() if flag}


def add_thermal_proxy_targets(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    group_column = "station_name"
    if group_column not in result:
        group_column = "_thermal_station"
        result[group_column] = "local"
    grouped = result.groupby(group_column, group_keys=False)

    humidex = result["humidex"] if "humidex" in result else pd.Series(index=result.index, dtype="float64")
    wind_chill = result["wind_chill"] if "wind_chill" in result else pd.Series(index=result.index, dtype="float64")
    heat_source = humidex.combine_first(result["temp_c"])
    cold_source = wind_chill.combine_first(result["temp_c"])

    result["_thermal_heat_source"] = heat_source
    result["_thermal_cold_source"] = cold_source
    future_heat = grouped["_thermal_heat_source"].transform(lambda values: _future_window_max(values, 24))
    future_cold = grouped["_thermal_cold_source"].transform(lambda values: _future_window_min(values, 24))

    # Class tiers mirror ECCC criteria: 36 is the NB humidex warning
    # criterion; 30 marks "elevated"; 40+ is treated as severe.
    result["proxy_heat_disturbance_24h"] = 0
    result.loc[future_heat >= 30.0, "proxy_heat_disturbance_24h"] = 1
    result.loc[future_heat >= 36.0, "proxy_heat_disturbance_24h"] = 2
    result.loc[future_heat >= 40.0, "proxy_heat_disturbance_24h"] = 3

    # Two-day Tmax>=29/Tmin>=16 pattern also satisfies the ECCC heat warning:
    # hours on the pattern's first day (or the day before) have a warning-level
    # event inside their 24h lookahead window. Needs timestamps to bucket by day.
    if "timestamp" in result:
        dates = pd.to_datetime(result["timestamp"]).dt.date
        for _, station_frame in result.groupby(group_column):
            pattern_dates = _two_day_heat_pattern_dates(station_frame)
            if not pattern_dates:
                continue
            lead_in_dates = pattern_dates | {
                date - timedelta(days=1) for date in pattern_dates
            }
            mask = result.index.isin(station_frame.index) & dates.isin(lead_in_dates)
            result.loc[mask, "proxy_heat_disturbance_24h"] = result.loc[
                mask, "proxy_heat_disturbance_24h"
            ].clip(lower=2)

    # ECCC-style wind chill tiers: -10 / -20 / -30 (extreme cold warning).
    result["proxy_cold_disturbance_24h"] = 0
    result.loc[future_cold <= -10.0, "proxy_cold_disturbance_24h"] = 1
    result.loc[future_cold <= -20.0, "proxy_cold_disturbance_24h"] = 2
    result.loc[future_cold <= -30.0, "proxy_cold_disturbance_24h"] = 3

    return result.drop(columns=["_thermal_heat_source", "_thermal_cold_source", "_thermal_station"], errors="ignore")


def apply_feedback(df: pd.DataFrame, feedback_df: pd.DataFrame) -> pd.DataFrame:
    """Apply HA feedback labels to their own hazard's target column only.

    The original loop set EVERY model's target to 1.0 for any warning label,
    teaching unrelated models that an event occurred and destroying the
    multiclass severity classes. Each feedback row now touches only the
    columns mapped for its hazard, and multiclass targets receive the
    reported severity class, never a blanket 1.0.
    """
    result = df.copy()
    result["timestamp_dt"] = pd.to_datetime(result["timestamp"], utc=True)

    for _, row in feedback_df.iterrows():
        label = str(row.get("label", "") or "")
        hazard = str(row.get("hazard", "") or "").strip().lower()
        severity = str(row.get("severity", "") or "").strip().lower()
        if not hazard:
            hazard = LEGACY_LABEL_TO_HAZARD.get(label, "")
        if hazard not in HAZARD_TO_TARGET_COLUMNS:
            LOGGER.warning("Skipping feedback row without a usable hazard: %s", dict(row))
            continue

        fb_time = pd.to_datetime(row["timestamp"], utc=True)
        time_diffs = (result["timestamp_dt"] - fb_time).abs()
        if time_diffs.min() > pd.Timedelta(hours=1):
            continue
        closest_idx = time_diffs.idxmin()

        is_false_alarm = label.startswith("false_alarm")
        for column in HAZARD_TO_TARGET_COLUMNS[hazard]:
            if column not in result or pd.isna(result.at[closest_idx, column]):
                continue
            if column in MULTICLASS_TARGETS:
                value = 0 if is_false_alarm else SEVERITY_TO_CLASS.get(severity, 2)
            else:
                value = 0.0 if is_false_alarm else 1.0
            LOGGER.info(
                "Feedback %s/%s at %s -> %s=%s", label, hazard, fb_time, column, value
            )
            result.at[closest_idx, column] = value

    return result.drop(columns=["timestamp_dt"])


def chronological_split(df: pd.DataFrame, test_fraction: float = TEST_FRACTION) -> pd.Series:
    """Boolean test mask: the last `test_fraction` of each station's timeline.

    A shuffled random split leaks temporally-autocorrelated rows between train
    and test and inflates every metric; evaluation must be chronological.
    (Any future CV should use sklearn's TimeSeriesSplit for the same reason.)
    """
    result = df.copy()
    result["_ts"] = pd.to_datetime(result["timestamp"], utc=True, errors="coerce")
    group_column = "station_name" if "station_name" in result else None
    if group_column is None:
        result["_station"] = "local"
        group_column = "_station"

    test_mask = pd.Series(False, index=result.index)
    for _, station_frame in result.groupby(group_column):
        ordered = station_frame.sort_values("_ts")
        cutoff = int(len(ordered) * (1.0 - test_fraction))
        test_mask.loc[ordered.index[cutoff:]] = True
    return test_mask


def _base_estimator() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=100,
        learning_rate=0.1,
        max_depth=5,
        random_state=42,
    )


def train_model(X_train: pd.DataFrame, y_train: pd.Series, calibrate: bool = True):
    """Train the gradient-boosted classifier, calibrating its probabilities.

    The published risk scores are read as probabilities (verification divides
    them by 100 and scores them with Brier), so a well-ranked but poorly
    calibrated model still scores badly. A Platt/sigmoid calibration wrapper
    maps the raw scores onto observed frequencies; sigmoid is used over
    isotonic because it stays stable with the few storm/wind positives we have.

    Calibration is skipped when a class is too rare to populate every fold, or
    for multiclass thermal targets, in which case the raw model is returned so
    training never fails on sparse data.
    """
    base = _base_estimator()
    if not calibrate:
        base.fit(X_train, y_train)
        return base

    minority = int(y_train.value_counts().min())
    if minority < MIN_MINORITY_FOR_CALIBRATION:
        LOGGER.warning(
            "Only %d minority samples; shipping the raw (uncalibrated) model.",
            minority,
        )
        base.fit(X_train, y_train)
        return base

    # cv=int uses StratifiedKFold, so every fold keeps both classes even when
    # positives are rare. The chronological holdout used for promotion/metrics
    # is a separate, untouched split, so this does not leak the headline score.
    calibrated = CalibratedClassifierCV(base, method="sigmoid", cv=CALIBRATION_FOLDS)
    calibrated.fit(X_train, y_train)
    return calibrated


def multiclass_brier(y_true: pd.Series, probs: np.ndarray, classes: list) -> float:
    """Mean over samples of sum_k (p_k - onehot_k)^2."""
    class_index = {cls: idx for idx, cls in enumerate(classes)}
    onehot = np.zeros_like(probs)
    for row, value in enumerate(y_true):
        onehot[row, class_index[value]] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def evaluate_model(clf, X_test, y_test, name: str) -> dict:
    preds = clf.predict(X_test)
    probs = clf.predict_proba(X_test)
    metrics: dict[str, float] = {}

    LOGGER.info(f"--- Chronological holdout evaluation for {name} ---")
    if len(y_test.unique()) > 1:
        if len(clf.classes_) > 2:
            metrics["roc_auc"] = roc_auc_score(y_test, probs, multi_class="ovr")
        else:
            metrics["roc_auc"] = roc_auc_score(y_test, probs[:, 1])
        LOGGER.info(f"ROC AUC: {metrics['roc_auc']:.3f}")
    if len(clf.classes_) > 2:
        metrics["brier"] = multiclass_brier(y_test, probs, list(clf.classes_))
    else:
        positive_index = list(clf.classes_).index(1) if 1 in clf.classes_ else -1
        metrics["brier"] = float(brier_score_loss(y_test, probs[:, positive_index]))
    LOGGER.info(f"Brier score: {metrics['brier']:.4f}")
    LOGGER.info("\n" + classification_report(y_test, preds))
    return metrics


def load_previous_model(models_dir: Path, model_name: str):
    model_path = models_dir / f"{model_name}.pkl"
    if not model_path.exists():
        return None
    try:
        with model_path.open("rb") as f:
            return pickle.load(f)
    except (pickle.PickleError, OSError, EOFError) as exc:
        LOGGER.warning(f"Could not load previous model {model_name}: {exc}")
        return None


def main(argv: list[str] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    args = parser.parse_args(argv)

    if not args.dataset.exists():
        LOGGER.error(f"Dataset not found at {args.dataset}")
        return 1

    df = load_data(args.dataset)
    df = add_thermal_proxy_targets(df)

    feedback_file = args.dataset.parent / "feedback_dataset.csv"
    if feedback_file.exists():
        try:
            LOGGER.info(f"Applying feedback corrections from {feedback_file}")
            df = apply_feedback(df, pd.read_csv(feedback_file))
        except Exception as e:
            LOGGER.error(f"Failed to apply feedback dataset: {e}")

    # Base surface features are required; drop rows missing any of them. The
    # convective columns are only included when the dataset actually carries
    # non-null values (the ECCC archive has none), and the gradient-boosted
    # trees handle any remaining NaN gaps natively -- so they are NOT part of
    # the dropna subset.
    df = df.dropna(subset=FEATURES)

    convective_present = [
        column
        for column in CONVECTIVE_FEATURES
        if column in df.columns and df[column].notna().any()
    ]
    model_features = FEATURES + convective_present
    if convective_present:
        LOGGER.info("Including convective features: %s", ", ".join(convective_present))

    X = df[model_features]
    test_mask = chronological_split(df)

    args.models_dir.mkdir(parents=True, exist_ok=True)

    promoted: list[str] = []
    rejected: list[str] = []

    for model_name, target in TARGETS.items():
        target_col = target["target"]
        kind = target["kind"]
        LOGGER.info(f"Training model for {model_name}...")

        # Filter out missing targets
        valid_idx = df[target_col].notna()
        X_valid = X[valid_idx]
        y_valid = df.loc[valid_idx, target_col].astype(int)

        if y_valid.sum() == 0:
            LOGGER.warning(f"No positive samples for {target_col}, skipping.")
            continue

        model_test_mask = test_mask[valid_idx]
        X_train, X_test = X_valid[~model_test_mask], X_valid[model_test_mask]
        y_train, y_test = y_valid[~model_test_mask], y_valid[model_test_mask]
        if y_train.nunique() < 2 or len(X_test) == 0:
            LOGGER.warning(f"Not enough chronological train/test data for {target_col}, skipping.")
            continue

        # Calibrate binary hazard probabilities; multiclass thermal targets
        # can leave a class out of a fold, so they train uncalibrated.
        candidate = train_model(X_train, y_train, calibrate=(kind != "multiclass"))
        metrics = evaluate_model(candidate, X_test, y_test, model_name)

        # Promotion gate: re-score the live model on the same chronological
        # holdout; keep it if the candidate's Brier regressed beyond tolerance.
        previous_bundle = load_previous_model(args.models_dir, model_name)
        previous_metrics = None
        if previous_bundle is not None:
            try:
                previous_metrics = evaluate_model(
                    previous_bundle["model"],
                    X_test[previous_bundle["features"]],
                    y_test,
                    f"{model_name} (live model, re-scored on new holdout)",
                )
            except Exception as exc:  # noqa: BLE001 - old pickles may be incompatible
                LOGGER.warning(f"Could not re-score previous {model_name} model: {exc}")

        should_promote = True
        if previous_metrics is not None and previous_metrics.get("brier") is not None:
            if metrics["brier"] > previous_metrics["brier"] + BRIER_REGRESSION_TOLERANCE:
                should_promote = False
                LOGGER.warning(
                    f"REJECTED candidate for {model_name}: Brier {metrics['brier']:.4f} is worse "
                    f"than live {previous_metrics['brier']:.4f} beyond tolerance "
                    f"{BRIER_REGRESSION_TOLERANCE}. Keeping existing live model."
                )

        metrics_record = {
            "model": model_name,
            "target": target_col,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "candidate": metrics,
            "previous": previous_metrics,
            "promoted": should_promote,
            "evaluation": "chronological_holdout",
            "train_rows": int(len(X_train)),
            "test_rows": int(len(X_test)),
        }

        if not should_promote:
            rejected.append(model_name)
            (args.models_dir / f"{model_name}.rejected.json").write_text(
                json.dumps(metrics_record, indent=2), encoding="utf-8"
            )
            continue

        model_path = args.models_dir / f"{model_name}.pkl"
        with open(model_path, "wb") as f:
            pickle.dump({
                "model": candidate,
                "features": model_features,
                "target": target_col,
                "kind": kind,
                "metrics": metrics,
                "evaluation": "chronological_holdout",
                "version": "1.1"
            }, f)
        (args.models_dir / f"{model_name}.metrics.json").write_text(
            json.dumps(metrics_record, indent=2), encoding="utf-8"
        )
        promoted.append(model_name)
        LOGGER.info(f"Promoted {model_name} model to {model_path}\n")

    LOGGER.info(
        f"Training run complete. Promoted: {promoted or 'none'}. "
        f"Rejected (kept previous live model): {rejected or 'none'}."
    )
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
