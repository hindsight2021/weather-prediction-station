#!/usr/bin/env python3
"""Turn the raw ECCC hourly dataset (training/build_station_dataset.py output)
into the feature table training/train_models.py expects at
data/processed/weather_features.csv.gz.

Proxy label definitions (documented here because they are judgment calls,
not ground truth):

- proxy_convective_risk_now: 1 if the ECCC observed-weather text for that
  hour contains "thunderstorm". This is a nowcast target (is a thunderstorm
  happening right now), matching the "_now" suffix.
- proxy_wind_event_1h: 1 if sustained wind speed in the NEXT hour is
  >= 45 km/h (the same wind_gust_watch_kmh threshold used by the live rule
  engine in config/weather_brain.yaml). Note: ECCC's hourly observations do
  not include gust, only sustained wind speed, so this is a same-quantity
  proxy for "gust" rather than a true gust forecast.
- proxy_storm_event_24h: 1 if ANY hour in the NEXT 24 hours has a
  thunderstorm, >=10mm precipitation in that hour, or sustained wind
  >=65 km/h (the wind_gust_warning_kmh threshold). This is a "storm day
  ahead" target, not a specific-hour prediction.

These thresholds intentionally mirror config/weather_brain.yaml's
risk_thresholds so the ML layer and the rule engine agree on what counts
as severe.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger("build_features")

DEFAULT_INPUT = Path("data/raw/eccc_hourly_fredericton.csv.gz")
DEFAULT_OUTPUT = Path("data/processed/weather_features.csv.gz")

WIND_EVENT_THRESHOLD_KMH = 45.0
STORM_WIND_THRESHOLD_KMH = 65.0
STORM_PRECIP_THRESHOLD_MM = 10.0
STORM_LOOKAHEAD_HOURS = 24

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
    "month_cos",
]


def build_features(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["timestamp"] = pd.to_datetime(df["LOCAL_DATE"])
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"])

    # Reindex onto a complete hourly grid so deltas/rolling stats don't
    # silently bridge real data gaps with the wrong time spacing.
    full_index = pd.date_range(df["timestamp"].min(), df["timestamp"].max(), freq="h")
    df = df.set_index("timestamp").reindex(full_index)
    df.index.name = "timestamp"

    numeric_cols = ["TEMP", "DEW_POINT_TEMP", "RELATIVE_HUMIDITY", "WIND_SPEED", "STATION_PRESSURE", "PRECIP_AMOUNT"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Short gaps (<=2h) are safe to interpolate for continuous sensor fields.
    df[numeric_cols] = df[numeric_cols].interpolate(limit=2, limit_direction="both")

    df["WEATHER_ENG_DESC"] = df["WEATHER_ENG_DESC"].fillna("NA").astype(str)

    df["temp_c"] = df["TEMP"]
    df["dew_point_c"] = df["DEW_POINT_TEMP"]
    df["rel_hum_pct"] = df["RELATIVE_HUMIDITY"]
    df["wind_speed_kmh"] = df["WIND_SPEED"]
    df["station_pressure_hpa"] = df["STATION_PRESSURE"] * 10.0  # kPa -> hPa
    df["dew_point_spread_c"] = df["temp_c"] - df["dew_point_c"]

    df["temp_c_delta_3h"] = df["temp_c"].diff(3)
    df["temp_c_delta_6h"] = df["temp_c"].diff(6)
    df["station_pressure_hpa_delta_3h"] = df["station_pressure_hpa"].diff(3)
    df["station_pressure_hpa_delta_6h"] = df["station_pressure_hpa"].diff(6)

    df["wind_speed_kmh_rolling_mean_3h"] = df["wind_speed_kmh"].rolling(3, min_periods=1).mean()
    df["wind_speed_kmh_rolling_std_3h"] = df["wind_speed_kmh"].rolling(3, min_periods=2).std().fillna(0.0)

    df["hour_sin"] = np.sin(2.0 * np.pi * df.index.hour / 24.0)
    df["hour_cos"] = np.cos(2.0 * np.pi * df.index.hour / 24.0)
    df["month_sin"] = np.sin(2.0 * np.pi * df.index.month / 12.0)
    df["month_cos"] = np.cos(2.0 * np.pi * df.index.month / 12.0)

    is_thunderstorm = df["WEATHER_ENG_DESC"].str.lower().str.contains("thunderstorm")
    df["proxy_convective_risk_now"] = is_thunderstorm.astype(int)

    df["proxy_wind_event_1h"] = (df["wind_speed_kmh"].shift(-1) >= WIND_EVENT_THRESHOLD_KMH).astype(int)
    # Rows at the very end have no "next hour" to check; mark unknown rather than false.
    df.loc[df["wind_speed_kmh"].shift(-1).isna(), "proxy_wind_event_1h"] = np.nan

    severe_now = (
        is_thunderstorm
        | (df["PRECIP_AMOUNT"] >= STORM_PRECIP_THRESHOLD_MM)
        | (df["wind_speed_kmh"] >= STORM_WIND_THRESHOLD_KMH)
    )
    forward_windows = [severe_now.shift(-i) for i in range(1, STORM_LOOKAHEAD_HOURS + 1)]
    forward_any = pd.concat(forward_windows, axis=1)
    df["proxy_storm_event_24h"] = forward_any.max(axis=1)
    # Unknown (not false) wherever the lookahead runs past the end of the data.
    df.loc[forward_any.isna().all(axis=1), "proxy_storm_event_24h"] = np.nan
    df["proxy_storm_event_24h"] = df["proxy_storm_event_24h"].astype("Int64")

    df["timestamp"] = df.index
    output_cols = ["timestamp"] + FEATURES + ["proxy_convective_risk_now", "proxy_wind_event_1h", "proxy_storm_event_24h"]
    return df[output_cols].reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not args.input.exists():
        LOGGER.error("Raw dataset not found at %s. Run training/build_station_dataset.py first.", args.input)
        return 1

    LOGGER.info("Loading raw dataset from %s", args.input)
    raw = pd.read_csv(args.input)

    features = build_features(raw)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(args.output, index=False, compression="gzip")

    positive_counts = {
        "proxy_convective_risk_now": int(features["proxy_convective_risk_now"].sum()),
        "proxy_wind_event_1h": int(features["proxy_wind_event_1h"].sum(skipna=True)),
        "proxy_storm_event_24h": int(features["proxy_storm_event_24h"].sum(skipna=True)),
    }
    LOGGER.info("Wrote %d feature rows to %s", len(features), args.output)
    LOGGER.info("Positive sample counts: %s", positive_counts)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
