"""Hazard definitions shared by outcome derivation and scoring.

Each hazard names the prediction field it verifies, the forecast horizon, and
how ground truth is derived from station snapshots and archived ECCC alerts.
Event thresholds mirror ECCC public criteria where one exists; the citation is
noted beside each value.
"""

from __future__ import annotations

from dataclasses import dataclass

# ECCC wind warning criterion: sustained >= 70 km/h or gusts >= 90 km/h.
WIND_SUSTAINED_WARNING_KMH = 70.0
WIND_GUST_WARNING_KMH = 90.0
# Secondary advisory-level wind event used for verification volume (roadmap §4.5).
WIND_GUST_ADVISORY_KMH = 50.0

# Any measurable rain within the window counts as a rain event; 0.2 mm/h
# filters gauge noise from the tipping-bucket 5-minute delta feed.
RAIN_EVENT_MM_H = 0.2

# ECCC humidex-based heat warning criterion for New Brunswick: humidex >= 36.
HEAT_HUMIDEX_WARNING = 36.0
# ECCC extreme cold warning criterion for NB: wind chill <= -30 for >= 2h.
COLD_WIND_CHILL_WARNING_C = -30.0

# Lightning within this range is treated as a local lightning event.
LIGHTNING_NEARBY_KM = 25.0
# A local strike counts as a real event only when corroborated (this many
# strikes in the 30-min window, an internet-network detection, or radar precip
# nearby). The AcuRite 6045M false-triggers on EMI, so an isolated single
# strike must not fabricate a ground-truth event. Mirrors the live engine's
# lightning_local_corroboration_min_count (config/weather_brain.yaml).
LIGHTNING_CORROBORATION_MIN_COUNT = 2.0

# Observed convective-storm signature. Mirrors the training proxy_storm_event
# target (training/build_features.py) so training, live scoring, and
# verification finally agree on what "a storm" is: a thunderstorm (local
# lightning), heavy rain, or damaging wind. Previously storm hazards verified
# against CAP alerts ALONE -- a handful of ultra-rare positives that made the
# Brier score meaningless and left storm_1h with no forecast baseline at all.
STORM_RAIN_MM_H = 10.0  # roadmap storm precip threshold / rain_rate_warning
STORM_WIND_GUST_KMH = 65.0  # wind_gust_warning_kmh

# Published risk scores are 0-100; tiers mirror app/risk_rules.py levels.
TIER_THRESHOLDS = {"advisory": 40, "watch": 60, "warning": 80}

# Substrings (lowercased) matched against CAP <event> to bucket alerts.
ALERT_EVENT_TO_HAZARD = {
    "thunderstorm": "storm",
    "tornado": "storm",
    "wind": "wind",
    "rain": "rain",
    "heat": "heat",
    "cold": "cold",
    "winter storm": "storm",
}


@dataclass(frozen=True)
class HazardSpec:
    name: str
    prediction_field: str
    horizon_hours: int
    # snapshot-derived outcome ("obs"), alert-derived ("alert"), or both
    # (event occurs if either source fires).
    sources: tuple[str, ...]
    alert_hazard: str | None = None
    forecast_reference_field: str | None = None


HAZARDS: tuple[HazardSpec, ...] = (
    HazardSpec("rain_1h", "rain_risk_1h", 1, ("obs",),
               forecast_reference_field="forecast_precip_probability_1h"),
    HazardSpec("rain_24h", "rain_risk_24h", 24, ("obs",),
               forecast_reference_field="forecast_precip_probability_24h"),
    HazardSpec("wind_1h", "wind_risk_1h", 1, ("obs",),
               forecast_reference_field="forecast_wind_gust_max_1h"),
    HazardSpec("wind_24h", "wind_risk_24h", 24, ("obs",),
               forecast_reference_field="forecast_wind_gust_max_24h"),
    HazardSpec("storm_1h", "storm_risk_1h", 1, ("obs", "alert"), alert_hazard="storm",
               forecast_reference_field="forecast_next_severe_minutes"),
    HazardSpec("storm_24h", "storm_risk_24h", 24, ("obs", "alert"), alert_hazard="storm",
               forecast_reference_field="forecast_severe_condition_24h"),
    HazardSpec("heat_24h", "heat_risk_24h", 24, ("obs", "alert"), alert_hazard="heat"),
    HazardSpec("cold_24h", "cold_risk_24h", 24, ("obs", "alert"), alert_hazard="cold"),
    HazardSpec("lightning_1h", "lightning_risk_1h", 1, ("obs",)),
)


def observed_event(hazard: str, window_snapshots: list[dict]) -> bool:
    """Did the hazard's observation-based event occur in these snapshots?"""

    def values(field: str) -> list[float]:
        return [float(s[field]) for s in window_snapshots if s.get(field) is not None]

    if hazard.startswith("rain"):
        return any(v >= RAIN_EVENT_MM_H for v in values("rain_rate_mm_h"))
    if hazard.startswith("wind"):
        return (
            any(v >= WIND_GUST_ADVISORY_KMH for v in values("wind_gust_kmh"))
            or any(v >= WIND_SUSTAINED_WARNING_KMH for v in values("wind_speed_kmh"))
        )
    if hazard.startswith("heat"):
        return any(v >= HEAT_HUMIDEX_WARNING for v in values("humidex"))
    if hazard.startswith("cold"):
        return any(v <= COLD_WIND_CHILL_WARNING_C for v in values("wind_chill_c"))
    if hazard.startswith("lightning"):
        return _lightning_observed(values)
    if hazard.startswith("storm"):
        return (
            _lightning_observed(values)
            or any(v >= STORM_RAIN_MM_H for v in values("rain_rate_mm_h"))
            or any(v >= STORM_WIND_GUST_KMH for v in values("wind_gust_kmh"))
            or any(v >= WIND_SUSTAINED_WARNING_KMH for v in values("wind_speed_kmh"))
        )
    return False


def _lightning_observed(values) -> bool:
    local_strike = any(v <= LIGHTNING_NEARBY_KM for v in values("local_lightning_distance_km"))
    multi_strike = any(
        v >= LIGHTNING_CORROBORATION_MIN_COUNT for v in values("local_lightning_count_30m")
    )
    internet = any(v > 0 for v in values("internet_lightning_count_30m"))
    radar = any(v > 0 for v in values("radar_precip_nearby"))
    # A burst of strikes or an independent network detection is a real event on
    # its own; a single local strike needs radar corroboration to count.
    if multi_strike or internet:
        return True
    return local_strike and radar


def hazard_for_alert_event(event: str) -> str | None:
    lowered = (event or "").lower()
    for needle, hazard in ALERT_EVENT_TO_HAZARD.items():
        if needle in lowered:
            return hazard
    return None
