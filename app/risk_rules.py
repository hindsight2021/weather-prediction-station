from __future__ import annotations

from app.feature_builder import SnapshotStore
from app.models import Prediction, WeatherSnapshot


def clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _heat_risk(value: float | None, thresholds: dict[str, float]) -> tuple[float, str]:
    """Map humidex to warning proximity, not raw discomfort.

    Score >= 65 means ECCC warning criteria met or imminent. The NB humidex
    warning criterion is 36 (plus multi-day temperature criteria handled by
    training labels), so humidex 35 reads "elevated" (~40), not 65+.
    """
    if value is None:
        return 0.0, "none"
    mild = thresholds.get("heat_humidex_mild", 30.0)
    # ECCC heat warning criterion for New Brunswick: humidex >= 36.
    warning = thresholds.get("heat_humidex_warning", 36.0)
    severe = thresholds.get("heat_humidex_severe", 40.0)
    if value >= severe:
        return min(100.0, 90.0 + (value - severe) * 2.0), "severe"
    if value >= warning:
        return min(89.0, 65.0 + (value - warning) * 6.0), "moderate"
    if value >= mild:
        # Elevated but below the warning criterion: humidex 34 -> 36, 35 -> 40.
        return min(64.0, 20.0 + (value - mild) * 4.0), "mild"
    return max(0.0, (value - 24.0) * 3.0), "none"


def _cold_risk(value: float | None, thresholds: dict[str, float]) -> tuple[float, str]:
    if value is None:
        return 0.0, "none"
    mild = thresholds.get("cold_wind_chill_mild_c", -10.0)
    moderate = thresholds.get("cold_wind_chill_moderate_c", -20.0)
    severe = thresholds.get("cold_wind_chill_severe_c", -30.0)
    if value <= severe:
        return min(100.0, 90.0 + abs(value - severe) * 1.5), "severe"
    if value <= moderate:
        return min(89.0, 65.0 + abs(value - moderate) * 2.5), "moderate"
    if value <= mild:
        return min(64.0, 35.0 + abs(value - mild) * 3.0), "mild"
    return 0.0, "none"


def _convective_potential(
    cape: float | None, cin: float | None, lifted_index: float | None
) -> tuple[float, str]:
    """Instability score (0-100) from CAPE, convective inhibition, and LI.

    Thunderstorms need instability (CAPE / negative lifted index) that is not
    capped off (high CIN suppresses realization). Surface temperature and
    pressure cannot see any of this, so without these fields the score is 0 and
    the storm rules fall back to their previous behaviour.
    """
    if cape is None and lifted_index is None:
        return 0.0, "none"
    # ~2500 J/kg of CAPE saturates the scale; NB rarely exceeds that.
    cape_score = 0.0 if cape is None else min(100.0, max(0.0, cape) / 25.0)
    # Lifted index is stability: negative is unstable. LI <= -4.5 saturates.
    lifted_score = 0.0
    if lifted_index is not None and lifted_index < 0:
        lifted_score = min(100.0, -lifted_index * 22.0)
    potential = 0.6 * cape_score + 0.4 * lifted_score
    # A strong cap (high CIN) holds storms down even with ample CAPE.
    if cin is not None and cin > 50.0:
        potential *= max(0.0, 1.0 - (cin - 50.0) / 200.0)
    if potential >= 60.0:
        return potential, "strong"
    if potential >= 30.0:
        return potential, "moderate"
    if potential >= 10.0:
        return potential, "marginal"
    return potential, "none"


def score_weather(snapshot: WeatherSnapshot, store: SnapshotStore, thresholds: dict[str, float]) -> Prediction:
    pressure_1h = store.pressure_delta(1)
    pressure_3h = store.pressure_delta(3)
    max_gust_30m = store.max_wind_gust(30)
    max_rain_30m = store.max_rain_rate(30)

    pressure_score = 0.0
    if pressure_1h is not None and pressure_1h < 0:
        pressure_score += min(35.0, abs(pressure_1h) * 12.0)
    if pressure_3h is not None and pressure_3h < 0:
        pressure_score += min(30.0, abs(pressure_3h) * 6.0)

    humidity_score = 0.0
    if snapshot.humidity_pct is not None:
        humidity_score = max(0.0, (snapshot.humidity_pct - 70.0) * 0.8)

    wind_risk = 0.0
    gust = snapshot.wind_gust_kmh if snapshot.wind_gust_kmh is not None else max_gust_30m
    if gust is not None:
        watch = thresholds.get("wind_gust_watch_kmh", 45.0)
        warning = thresholds.get("wind_gust_warning_kmh", 65.0)
        if gust >= warning:
            wind_risk = 90.0
        elif gust >= watch:
            wind_risk = 55.0 + (gust - watch) * 1.5
        else:
            wind_risk = max(0.0, gust * 0.7)

    forecast_gust_1h = snapshot.forecast_wind_gust_max_1h
    forecast_gust_24h = snapshot.forecast_wind_gust_max_24h
    forecast_wind_risk_1h = _wind_risk(forecast_gust_1h, thresholds)
    forecast_wind_risk_24h = _wind_risk(forecast_gust_24h, thresholds)
    wind_risk = max(wind_risk, forecast_wind_risk_1h)

    rain_risk = 0.0
    rain_rate = snapshot.rain_rate_mm_h if snapshot.rain_rate_mm_h is not None else max_rain_30m
    if rain_rate is not None:
        watch = thresholds.get("rain_rate_watch_mm_h", 4.0)
        warning = thresholds.get("rain_rate_warning_mm_h", 10.0)
        if rain_rate >= warning:
            rain_risk = 90.0
        elif rain_rate >= watch:
            rain_risk = 50.0 + (rain_rate - watch) * 6.0
        else:
            rain_risk = rain_rate * 8.0
        if rain_rate > 0:
            # A sensor-confirmed event is occurring, so a zero/low "risk" is
            # impossible even when forecast or radar inputs are missing.
            rain_risk = max(rain_risk, 85.0)

    forecast_rain_1h = _forecast_rain_risk(
        snapshot.forecast_precip_probability_1h, snapshot.forecast_precip_mm_1h
    )
    forecast_rain_24h = _forecast_rain_risk(
        snapshot.forecast_precip_probability_24h, snapshot.forecast_precip_mm_24h
    )
    rain_risk = max(rain_risk, forecast_rain_1h)

    lightning_risk = 0.0
    if snapshot.local_lightning_distance_km is not None:
        nearby = thresholds.get("lightning_nearby_km", 25.0)
        if snapshot.local_lightning_distance_km <= nearby:
            lightning_risk += 75.0
        elif snapshot.local_lightning_distance_km <= nearby * 2:
            lightning_risk += 45.0
    if snapshot.local_lightning_count_30m is not None:
        lightning_risk += min(25.0, snapshot.local_lightning_count_30m * 5.0)
    if snapshot.internet_lightning_count_30m is not None:
        lightning_risk += min(20.0, snapshot.internet_lightning_count_30m * 2.0)

    radar_score = 0.0
    if snapshot.radar_precip_nearby is not None and snapshot.radar_precip_nearby > 0:
        radar_score = 35.0

    heat_signal = snapshot.forecast_temp_max_24h
    heat_risk, heat_severity = _heat_risk(heat_signal, thresholds)
    current_heat = snapshot.humidex if snapshot.humidex is not None else snapshot.temperature_c
    current_heat_risk, _current_heat_severity = _heat_risk(current_heat, thresholds)
    if heat_signal is None and current_heat_risk >= 35:
        heat_severity = "ongoing"
    if current_heat is not None and heat_signal is not None and heat_signal <= current_heat + 1.5:
        heat_risk = min(heat_risk, 25.0)
        heat_severity = "ongoing" if current_heat >= thresholds.get("heat_humidex_mild", 30.0) else "none"

    cold_signal = snapshot.wind_chill_c if snapshot.wind_chill_c is not None else snapshot.temperature_c
    min_cold_6h = store.field_min("wind_chill_c", 6)
    if min_cold_6h is not None:
        cold_signal = min(cold_signal if cold_signal is not None else min_cold_6h, min_cold_6h)
    cold_risk, cold_severity = _cold_risk(cold_signal, thresholds)

    convective_potential, convective_label = _convective_potential(
        snapshot.cape, snapshot.convective_inhibition, snapshot.lifted_index
    )

    storm_risk_1h = clamp_score(
        pressure_score * 0.30
        + humidity_score * 0.15
        + wind_risk * 0.15
        + rain_risk * 0.15
        + lightning_risk * 0.20
        + radar_score * 0.20
        + convective_potential * 0.25
    )
    severe_forecast = 100.0 if (snapshot.forecast_severe_condition_24h or 0) > 0 else 0.0
    storm_risk_24h = clamp_score(max(
        severe_forecast * 0.85,
        forecast_rain_24h * 0.40
        + forecast_wind_risk_24h * 0.30
        + pressure_score * 0.20
        + humidity_score * 0.10,
    ))
    alert_rank = int(snapshot.official_alert_severity or 0)
    if alert_rank >= 3:
        storm_risk_1h, storm_risk_24h = max(storm_risk_1h, 90), max(storm_risk_24h, 90)
    elif alert_rank == 2:
        storm_risk_1h, storm_risk_24h = max(storm_risk_1h, 70), max(storm_risk_24h, 75)
    elif alert_rank == 1:
        storm_risk_24h = max(storm_risk_24h, 45)

    # Honest confidence: a probabilistic system should never read 100%.
    # Input availability earns up to 45 pts on a 30-pt base, corroborating
    # forecast sources up to 10, history depth up to 7 — hard cap 92, and
    # main.py caps it further at 60 when ML models are skipped as degraded.
    observed_fields = [
        snapshot.temperature_c,
        snapshot.humidity_pct,
        snapshot.pressure_hpa,
        snapshot.wind_speed_kmh,
        snapshot.wind_gust_kmh,
        snapshot.rain_rate_mm_h,
        snapshot.humidex,
        snapshot.local_lightning_distance_km,
        snapshot.radar_precip_nearby,
        snapshot.forecast_precip_probability_24h,
        snapshot.forecast_wind_gust_max_24h,
    ]
    present_fraction = sum(value is not None for value in observed_fields) / len(observed_fields)
    source_bonus = min(10.0, float(snapshot.forecast_source_count or 0) * 5.0)
    history_bonus = min(7.0, len(store.all()) / 36.0)  # ~3h of 5-min snapshots = full marks
    confidence = clamp_score(min(92.0, 30.0 + present_fraction * 45.0 + source_bonus + history_bonus))

    level = "normal"
    imminent_event, imminent_minutes, imminent_summary = _imminent_event(snapshot, rain_rate)

    if (alert_rank >= 3 or storm_risk_1h >= 80 or wind_risk >= 80 or rain_risk >= 80
            or lightning_risk >= 85 or heat_risk >= 90 or cold_risk >= 90
            or (imminent_event != "none" and 0 <= imminent_minutes <= 60)):
        level = "warning"
    elif alert_rank >= 2 or storm_risk_1h >= 60 or wind_risk >= 60 or lightning_risk >= 60 or heat_risk >= 65 or current_heat_risk >= 65 or cold_risk >= 65:
        level = "watch"
    elif storm_risk_1h >= 40 or heat_risk >= 35 or current_heat_risk >= 35 or cold_risk >= 35:
        level = "advisory"

    explanation_parts: list[str] = []
    if pressure_1h is not None and pressure_1h <= -1.0:
        explanation_parts.append(f"pressure falling {pressure_1h:.1f} hPa over 1h")
    if pressure_3h is not None and pressure_3h <= -2.0:
        explanation_parts.append(f"pressure falling {pressure_3h:.1f} hPa over 3h")
    if gust is not None and gust >= thresholds.get("wind_gust_watch_kmh", 45.0):
        explanation_parts.append(f"gusts near {gust:.0f} km/h")
    if rain_rate is not None and rain_rate >= thresholds.get("rain_rate_watch_mm_h", 4.0):
        explanation_parts.append(f"rain rate {rain_rate:.1f} mm/h")
    if lightning_risk >= 50:
        explanation_parts.append("lightning signal active")
    if radar_score > 0:
        explanation_parts.append("radar precipitation nearby")
    if convective_label != "none":
        detail = []
        if snapshot.cape is not None:
            detail.append(f"CAPE {snapshot.cape:.0f} J/kg")
        if snapshot.lifted_index is not None:
            detail.append(f"LI {snapshot.lifted_index:.1f}")
        suffix = f" ({', '.join(detail)})" if detail else ""
        explanation_parts.append(f"{convective_label} convective instability{suffix}")
    if alert_rank:
        explanation_parts.append(f"active ECCC {('advisory', 'watch', 'warning')[min(3, alert_rank)-1]}")
    if snapshot.forecast_precip_probability_1h is not None:
        explanation_parts.append(
            f"forecast rain chance {snapshot.forecast_precip_probability_1h:.0f}% within 1h"
        )
    if snapshot.forecast_precip_probability_24h is not None:
        explanation_parts.append(
            f"forecast rain chance {snapshot.forecast_precip_probability_24h:.0f}% within 24h"
        )
    if imminent_event != "none":
        explanation_parts.append(imminent_summary)
    if heat_severity != "none" and heat_signal is not None:
        explanation_parts.append(f"{heat_severity} heat signal near {heat_signal:.0f}")
    if cold_severity != "none" and cold_signal is not None:
        explanation_parts.append(f"{cold_severity} cold signal near {cold_signal:.0f}")

    explanation = "; ".join(explanation_parts) if explanation_parts else "No strong local severe-weather signal detected."

    aqhi_24 = int(round(snapshot.aqhi_forecast_max_24h or snapshot.aqhi_current or 0))
    aqhi_48 = int(round(snapshot.aqhi_forecast_max_48h or aqhi_24))
    return Prediction(
        storm_risk_1h=storm_risk_1h,
        storm_risk_24h=storm_risk_24h,
        wind_risk_1h=clamp_score(wind_risk),
        rain_risk_1h=clamp_score(rain_risk),
        lightning_risk_1h=clamp_score(lightning_risk),
        confidence=confidence,
        level=level,
        explanation=explanation,
        heat_risk_24h=clamp_score(heat_risk),
        cold_risk_24h=clamp_score(cold_risk),
        heat_severity=heat_severity,
        cold_severity=cold_severity,
        rain_risk_24h=clamp_score(forecast_rain_24h),
        wind_risk_24h=clamp_score(forecast_wind_risk_24h),
        imminent_event=imminent_event,
        imminent_minutes=imminent_minutes,
        imminent_summary=imminent_summary,
        storm_risk_48h=_outlook_risk(snapshot.forecast_precip_probability_48h, snapshot.forecast_wind_gust_max_48h, snapshot.forecast_severe_condition_48h, thresholds),
        storm_risk_72h=_outlook_risk(snapshot.forecast_precip_probability_72h, snapshot.forecast_wind_gust_max_72h, snapshot.forecast_severe_condition_72h, thresholds),
        air_quality_risk_24h=clamp_score(aqhi_24 * 10),
        air_quality_risk_48h=clamp_score(aqhi_48 * 10),
        smoke_risk_24h=clamp_score(max(snapshot.smoke_risk or 0, (snapshot.active_fires_nearby or 0) * 8)),
        aqhi_current=int(round(snapshot.aqhi_current or 0)),
        aqhi_forecast_max_24h=aqhi_24,
        official_alert_level={0: "none", 1: "advisory", 2: "watch", 3: "warning"}.get(alert_rank, "warning"),
        official_alert_summary="Official ECCC alert active." if alert_rank else "No active ECCC alert.",
        nb_burn_status={1: "no_burn", 2: "restricted_20h_to_08h", 3: "burn_permitted"}.get(int(snapshot.nb_burn_category or 0), "unknown"),
        active_fires_nearby=int(snapshot.active_fires_nearby or 0),
        nearest_fire_km=float(snapshot.nearest_fire_km if snapshot.nearest_fire_km is not None else 999.0),
        nb_burn_category=int(snapshot.nb_burn_category or 0),
    )


def _wind_risk(gust: float | None, thresholds: dict[str, float]) -> float:
    if gust is None:
        return 0.0
    watch = thresholds.get("wind_gust_watch_kmh", 45.0)
    warning = thresholds.get("wind_gust_warning_kmh", 65.0)
    if gust >= warning:
        return 90.0
    if gust >= watch:
        return 55.0 + (gust - watch) * 1.5
    return max(0.0, gust * 0.7)


def _forecast_rain_risk(probability: float | None, amount_mm: float | None) -> float:
    probability_score = max(0.0, min(100.0, probability or 0.0))
    amount_score = 0.0 if amount_mm is None else min(100.0, 40.0 + amount_mm * 10.0)
    return max(probability_score, amount_score)


def _outlook_risk(probability: float | None, gust: float | None, severe: float | None, thresholds: dict[str, float]) -> int:
    """Conservative longer-range outlook; confidence naturally drops with horizon."""
    if (severe or 0) > 0:
        return 80
    return clamp_score((probability or 0) * 0.55 + _wind_risk(gust, thresholds) * 0.45)


def _imminent_event(
    snapshot: WeatherSnapshot, rain_rate: float | None
) -> tuple[str, int, str]:
    if rain_rate is not None and rain_rate > 0:
        return "rain", 0, f"Rain is occurring now at {rain_rate:.1f} mm/h"
    severe = snapshot.forecast_next_severe_minutes
    precip = snapshot.forecast_next_precip_minutes
    if severe is not None and 0 <= severe <= 120:
        minutes = int(round(severe))
        return "severe_weather", minutes, f"Severe-weather signal expected in about {minutes} minutes"
    if precip is not None and 0 <= precip <= 120:
        minutes = int(round(precip))
        return "rain", minutes, f"Rain expected in about {minutes} minutes"
    return "none", -1, "No imminent weather event detected."
