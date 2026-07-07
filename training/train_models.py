#!/usr/bin/env python3
"""Train machine learning models for weather prediction using the processed ECCC dataset."""

import argparse
import logging
import pickle
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score

LOGGER = logging.getLogger("train_models")

DEFAULT_DATASET = Path("data/processed/weather_features.csv.gz")
DEFAULT_MODELS_DIR = Path("models")

FEATURES = [
    "temp_c",
    "dew_point_c",
    "rel_hum_pct",
    "wind_speed_kmh",
    "station_pressure_hpa",
    "dew_point_spread_c",
    "temp_c_delta_3h",
    "temp_c_delta_6h",
    "station_pressure_hpa_delta_3h",
    "station_pressure_hpa_delta_6h",
    "wind_speed_kmh_rolling_mean_3h",
    "wind_speed_kmh_rolling_std_3h",
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos"
]

TARGETS = {
    "convective_risk": {"target": "proxy_convective_risk_now", "kind": "binary"},
    "wind_1h": {"target": "proxy_wind_event_1h", "kind": "binary"},
    "storm_24h": {"target": "proxy_storm_event_24h", "kind": "binary"},
    "heat_disturbance_24h": {"target": "proxy_heat_disturbance_24h", "kind": "multiclass"},
    "cold_disturbance_24h": {"target": "proxy_cold_disturbance_24h", "kind": "multiclass"},
}

def load_data(path: Path) -> pd.DataFrame:
    LOGGER.info(f"Loading dataset from {path}")
    return pd.read_csv(path)


def _future_window_max(values: pd.Series, hours: int) -> pd.Series:
    return values.shift(-1).iloc[::-1].rolling(window=hours, min_periods=1).max().iloc[::-1]


def _future_window_min(values: pd.Series, hours: int) -> pd.Series:
    return values.shift(-1).iloc[::-1].rolling(window=hours, min_periods=1).min().iloc[::-1]


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

    result["proxy_heat_disturbance_24h"] = 0
    result.loc[future_heat >= 30.0, "proxy_heat_disturbance_24h"] = 1
    result.loc[future_heat >= 35.0, "proxy_heat_disturbance_24h"] = 2
    result.loc[future_heat >= 40.0, "proxy_heat_disturbance_24h"] = 3

    result["proxy_cold_disturbance_24h"] = 0
    result.loc[future_cold <= -10.0, "proxy_cold_disturbance_24h"] = 1
    result.loc[future_cold <= -20.0, "proxy_cold_disturbance_24h"] = 2
    result.loc[future_cold <= -30.0, "proxy_cold_disturbance_24h"] = 3

    return result.drop(columns=["_thermal_heat_source", "_thermal_cold_source", "_thermal_station"], errors="ignore")

def train_model(X_train: pd.DataFrame, y_train: pd.Series) -> HistGradientBoostingClassifier:
    clf = HistGradientBoostingClassifier(
        max_iter=100,
        learning_rate=0.1,
        max_depth=5,
        random_state=42
    )
    clf.fit(X_train, y_train)
    return clf

def evaluate_model(clf, X_test, y_test, name: str):
    preds = clf.predict(X_test)
    probs = clf.predict_proba(X_test)
    
    LOGGER.info(f"--- Evaluation for {name} ---")
    if len(y_test.unique()) > 1:
        if len(clf.classes_) > 2:
            auc = roc_auc_score(y_test, probs, multi_class="ovr")
        else:
            auc = roc_auc_score(y_test, probs[:, 1])
        LOGGER.info(f"ROC AUC: {auc:.3f}")
    LOGGER.info("\n" + classification_report(y_test, preds))

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
    
    # -------------------------------------------------------------
    # Autonomous Feedback Loop: Apply HA feedback corrections
    # -------------------------------------------------------------
    feedback_file = args.dataset.parent / "feedback_dataset.csv"
    if feedback_file.exists():
        try:
            LOGGER.info(f"Applying autonomous feedback corrections from {feedback_file}")
            feedback_df = pd.read_csv(feedback_file)
            # Ensure timestamps align
            df['timestamp_dt'] = pd.to_datetime(df['timestamp'], utc=True)
            for _, row in feedback_df.iterrows():
                fb_time = pd.to_datetime(row['timestamp'], utc=True)
                label = row['label']
                # Find the closest row within 1 hour
                time_diffs = (df['timestamp_dt'] - fb_time).abs()
                if time_diffs.min() <= pd.Timedelta(hours=1):
                    closest_idx = time_diffs.idxmin()
                    if label == "false_alarm":
                        LOGGER.info(f"Applying false_alarm correction at {fb_time}")
                        for target in TARGETS.values():
                            col = target["target"]
                            if pd.notna(df.at[closest_idx, col]):
                                df.at[closest_idx, col] = 0.0
                    elif label == "correct_prediction" or "warning" in label:
                        LOGGER.info(f"Applying positive event correction at {fb_time}")
                        for target in TARGETS.values():
                            col = target["target"]
                            if pd.notna(df.at[closest_idx, col]):
                                df.at[closest_idx, col] = 1.0
        except Exception as e:
            LOGGER.error(f"Failed to apply feedback dataset: {e}")
    # -------------------------------------------------------------
    
    # Drop rows with missing features
    df = df.dropna(subset=FEATURES)
    
    X = df[FEATURES]
    
    args.models_dir.mkdir(parents=True, exist_ok=True)
    
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
            
        X_train, X_test, y_train, y_test = train_test_split(X_valid, y_valid, test_size=0.2, random_state=42)
        
        clf = train_model(X_train, y_train)
        evaluate_model(clf, X_test, y_test, model_name)
        
        model_path = args.models_dir / f"{model_name}.pkl"
        with open(model_path, "wb") as f:
            pickle.dump({
                "model": clf,
                "features": FEATURES,
                "target": target_col,
                "kind": kind,
                "version": "1.0"
            }, f)
        LOGGER.info(f"Saved {model_name} model to {model_path}\n")

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
