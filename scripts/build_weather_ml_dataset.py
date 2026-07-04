#!/usr/bin/env python3
"""Build an ML-ready hourly weather feature dataset from downloaded raw files.

The builder currently supports ECCC hourly bulk CSVs. It normalizes columns,
de-duplicates station timestamps, creates time-window features, and creates proxy
target columns so model code can be tested before official alert-label ingestion
is added.

Example:
    python scripts/build_weather_ml_dataset.py
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd


LOGGER = logging.getLogger("build_weather_ml_dataset")

DEFAULT_ECCC_RAW_DIR = Path("data/raw/eccc/hourly")
DEFAULT_OUTPUT_PATH = Path("data/processed/weather_features.csv.gz")

COLUMN_ALIASES = {
    "station_name": ["Station Name", "Station", "Name"],
    "climate_id": ["Climate ID"],
    "datetime": ["Date/Time (LST)", "Date/Time (Local Standard Time)", "Date/Time", "Date"],
    "temp_c": ["Temp (°C)", "Temperature (°C)", "Temp"],
    "dew_point_c": ["Dew Point Temp (°C)", "Dew Point (°C)", "Dew Point Temp"],
    "rel_hum_pct": ["Rel Hum (%)", "Relative Humidity (%)", "Rel Hum"],
    "wind_dir_10s_deg": ["Wind Dir (10s deg)", "Wind Direction (10s deg)", "Wind Dir"],
    "wind_speed_kmh": ["Wind Spd (km/h)", "Wind Speed (km/h)", "Wind Spd"],
    "visibility_km": ["Visibility (km)", "Visibility"],
    "station_pressure_kpa": ["Stn Press (kPa)", "Station Pressure (kPa)", "Stn Press"],
    "humidex": ["Hmdx", "Humidex"],
    "wind_chill": ["Wind Chill"],
    "weather": ["Weather"],
}

NUMERIC_COLUMNS = [
    "temp_c",
    "dew_point_c",
    "rel_hum_pct",
    "wind_dir_10s_deg",
    "wind_speed_kmh",
    "visibility_km",
    "station_pressure_kpa",
    "humidex",
    "wind_chill",
]

FEATURE_BASE_COLUMNS = [
    "temp_c",
    "dew_point_c",
    "rel_hum_pct",
    "wind_speed_kmh",
    "station_pressure_hpa",
    "dew_point_spread_c",
]


def _first_existing_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {str(column).strip().lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        column = normalized.get(candidate.lower())
        if column is not None:
            return column
    return None


def _clean_numeric(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    cleaned = cleaned.replace({"": np.nan, "nan": np.nan, "NaN": np.nan, "M": np.nan, "NA": np.nan})
    return pd.to_numeric(cleaned, errors="coerce")


def normalize_eccc_file(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    output = pd.DataFrame()

    for canonical_name, aliases in COLUMN_ALIASES.items():
        source_column = _first_existing_column(frame, aliases)
        if source_column is not None:
            output[canonical_name] = frame[source_column]

    if "datetime" not in output:
        raise ValueError(f"{path} is missing a usable Date/Time column")

    output["timestamp"] = pd.to_datetime(output["datetime"], errors="coerce")
    output = output.drop(columns=["datetime"])

    if "station_name" not in output:
        output["station_name"] = path.parent.name
    if "climate_id" not in output:
        output["climate_id"] = ""

    output["source_file"] = str(path)
    output["source"] = "eccc_hourly"

    for column in NUMERIC_COLUMNS:
        if column in output:
            output[column] = _clean_numeric(output[column])
        else:
            output[column] = np.nan

    output["station_pressure_hpa"] = output["station_pressure_kpa"] * 10.0
    output["dew_point_spread_c"] = output["temp_c"] - output["dew_point_c"]
    output["wind_dir_deg"] = output["wind_dir_10s_deg"] * 10.0

    return output.dropna(subset=["timestamp"])


def load_eccc_directory(raw_dir: Path) -> pd.DataFrame:
    paths = sorted(raw_dir.glob("**/*.csv"))
    if not paths:
        raise FileNotFoundError(
            f"No ECCC hourly CSV files found under {raw_dir}. "
            "Run scripts/download_eccc_hourly.py first."
        )

    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            frame = normalize_eccc_file(path)
        except Exception as exc:
            LOGGER.warning("Skipping %s: %s", path, exc)
            continue
        if not frame.empty:
            frames.append(frame)

    if not frames:
        raise RuntimeError(f"No usable ECCC hourly rows found under {raw_dir}")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["station_name", "timestamp"])
    combined = combined.drop_duplicates(subset=["station_name", "timestamp"], keep="last")
    return combined


def add_time_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    timestamp = pd.to_datetime(result["timestamp"])

    result["hour"] = timestamp.dt.hour
    result["month"] = timestamp.dt.month
    result["dayofyear"] = timestamp.dt.dayofyear

    result["hour_sin"] = np.sin(2.0 * math.pi * result["hour"] / 24.0)
    result["hour_cos"] = np.cos(2.0 * math.pi * result["hour"] / 24.0)
    result["month_sin"] = np.sin(2.0 * math.pi * result["month"] / 12.0)
    result["month_cos"] = np.cos(2.0 * math.pi * result["month"] / 12.0)
    result["dayofyear_sin"] = np.sin(2.0 * math.pi * result["dayofyear"] / 366.0)
    result["dayofyear_cos"] = np.cos(2.0 * math.pi * result["dayofyear"] / 366.0)

    return result


def add_window_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result = result.sort_values(["station_name", "timestamp"])

    grouped = result.groupby("station_name", group_keys=False)

    for column in FEATURE_BASE_COLUMNS:
        if column not in result:
            continue
        for hours in (1, 3, 6, 24):
            result[f"{column}_delta_{hours}h"] = grouped[column].diff(hours)
            result[f"{column}_rolling_mean_{hours}h"] = grouped[column].transform(
                lambda values, window=hours: values.rolling(window=window, min_periods=1).mean()
            )
            result[f"{column}_rolling_std_{hours}h"] = grouped[column].transform(
                lambda values, window=hours: values.rolling(window=window, min_periods=2).std()
            )

    result["rapid_pressure_drop_3h"] = result["station_pressure_hpa_delta_3h"] <= -3.0
    result["very_humid"] = result["rel_hum_pct"] >= 85.0
    result["low_dew_point_spread"] = result["dew_point_spread_c"] <= 2.0
    result["windy"] = result["wind_speed_kmh"] >= 40.0

    return result


def add_proxy_targets(frame: pd.DataFrame) -> pd.DataFrame:
    """Create bootstrapping labels until official ECCC alert labels are merged.

    These are not substitutes for real alert labels. They let us test the model
    pipeline and discover feature problems before alert-history ingestion exists.
    """

    result = frame.copy()
    grouped = result.groupby("station_name", group_keys=False)

    result["proxy_wind_event_1h"] = grouped["wind_speed_kmh"].shift(-1) >= 50.0
    result["proxy_wind_event_24h"] = grouped["wind_speed_kmh"].transform(
        lambda values: values.shift(-1).rolling(window=24, min_periods=1).max()
    ) >= 50.0

    pressure_drop_signal = result["station_pressure_hpa_delta_3h"] <= -3.0
    humid_signal = result["rel_hum_pct"] >= 85.0
    dew_point_signal = result["dew_point_spread_c"] <= 3.0
    wind_signal = result["wind_speed_kmh"] >= 35.0

    result["proxy_convective_risk_now"] = pressure_drop_signal & humid_signal & dew_point_signal
    result["proxy_storm_event_1h"] = grouped["proxy_convective_risk_now"].shift(-1).fillna(False) | grouped[
        "windy"
    ].shift(-1).fillna(False)
    result["proxy_storm_event_24h"] = grouped["proxy_storm_event_1h"].transform(
        lambda values: values.shift(-1).rolling(window=24, min_periods=1).max()
    ).fillna(False)
    result["proxy_weather_risk_score"] = (
        pressure_drop_signal.astype(int) * 30
        + humid_signal.astype(int) * 15
        + dew_point_signal.astype(int) * 20
        + wind_signal.astype(int) * 35
    ).clip(0, 100)

    return result


def build_dataset(eccc_raw_dir: Path) -> pd.DataFrame:
    frame = load_eccc_directory(eccc_raw_dir)
    frame = add_time_features(frame)
    frame = add_window_features(frame)
    frame = add_proxy_targets(frame)
    return frame.sort_values(["station_name", "timestamp"])


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eccc-raw-dir", type=Path, default=DEFAULT_ECCC_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--sample", type=int, default=0, help="Optional row limit for quick local checks.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    dataset = build_dataset(args.eccc_raw_dir)
    if args.sample > 0:
        dataset = dataset.head(args.sample)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.output, index=False)
    LOGGER.info("Wrote %d rows and %d columns to %s", len(dataset), len(dataset.columns), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
