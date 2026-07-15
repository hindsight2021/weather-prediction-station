"""Feature transforms shared by training and inference (roadmap §4.3).

Training previously used ECCC's measured dew point while inference
approximated it as ``T - (100 - RH) / 5`` — a systematic train/serve skew.
Both sides now derive dew point from temperature and relative humidity with
the Magnus formula, so the model sees the same quantity in both worlds.
"""

from __future__ import annotations

import math
from datetime import datetime

# Magnus formula constants (Alduchov & Eskridge 1996), valid -40..50 C.
_MAGNUS_A = 17.625
_MAGNUS_B = 243.04

# Canonical model feature list. Training and inference both import this;
# nothing else may define its own copy.
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

# Absolute-level features: imputing 0 for these puts inference catastrophically
# out of distribution (a 0 hPa pressure does not exist on Earth). They are
# imputed from the recent snapshot history or the model is skipped entirely.
LEVEL_FEATURES = (
    "temp_c",
    "dew_point_c",
    "rel_hum_pct",
    "wind_speed_kmh",
    "station_pressure_hpa",
    "dew_point_spread_c",
)

# Delta/rolling features: 0 is a sane neutral value ("no recent change").
DELTA_FEATURES = (
    "temp_c_delta_3h",
    "temp_c_delta_6h",
    "station_pressure_hpa_delta_3h",
    "station_pressure_hpa_delta_6h",
    "wind_speed_kmh_rolling_mean_3h",
    "wind_speed_kmh_rolling_std_3h",
)


def magnus_dew_point(temp_c: float | None, rel_hum_pct: float | None) -> float | None:
    """Dew point in Celsius from temperature and relative humidity."""
    if temp_c is None or rel_hum_pct is None:
        return None
    rh = min(100.0, max(0.5, float(rel_hum_pct)))
    gamma = math.log(rh / 100.0) + (_MAGNUS_A * temp_c) / (_MAGNUS_B + temp_c)
    return (_MAGNUS_B * gamma) / (_MAGNUS_A - gamma)


def dew_point_spread(temp_c: float | None, rel_hum_pct: float | None) -> float | None:
    dew_point = magnus_dew_point(temp_c, rel_hum_pct)
    if dew_point is None or temp_c is None:
        return None
    return temp_c - dew_point


def time_features(timestamp: datetime) -> dict[str, float]:
    return {
        "hour_sin": math.sin(2.0 * math.pi * timestamp.hour / 24.0),
        "hour_cos": math.cos(2.0 * math.pi * timestamp.hour / 24.0),
        "month_sin": math.sin(2.0 * math.pi * timestamp.month / 12.0),
        "month_cos": math.cos(2.0 * math.pi * timestamp.month / 12.0),
    }


def build_inference_row(snapshot, store) -> dict[str, float | None]:
    """Assemble the model feature row from a live snapshot + history store.

    Uses the same derivations as the training dataset builder. Missing values
    stay None here; imputation policy lives in the predictor.
    """
    row: dict[str, float | None] = {
        "temp_c": snapshot.temperature_c,
        "dew_point_c": magnus_dew_point(snapshot.temperature_c, snapshot.humidity_pct),
        "rel_hum_pct": snapshot.humidity_pct,
        "wind_speed_kmh": snapshot.wind_speed_kmh,
        "station_pressure_hpa": snapshot.pressure_hpa,
        "dew_point_spread_c": dew_point_spread(snapshot.temperature_c, snapshot.humidity_pct),
        "temp_c_delta_3h": store.temp_delta(3),
        "temp_c_delta_6h": store.temp_delta(6),
        "station_pressure_hpa_delta_3h": store.pressure_delta(3),
        "station_pressure_hpa_delta_6h": store.pressure_delta(6),
        "wind_speed_kmh_rolling_mean_3h": store.wind_speed_mean(3),
        "wind_speed_kmh_rolling_std_3h": store.wind_speed_std(3),
    }
    row.update(time_features(snapshot.timestamp))
    return row
