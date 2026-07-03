from __future__ import annotations

from app.feature_builder import SnapshotStore
from app.models import Prediction, WeatherSnapshot


def clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


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

    storm_risk_1h = clamp_score(
        pressure_score * 0.30
        + humidity_score * 0.15
        + wind_risk * 0.15
        + rain_risk * 0.15
        + lightning_risk * 0.20
        + radar_score * 0.20
    )
    storm_risk_24h = clamp_score(storm_risk_1h * 0.65 + pressure_score * 0.35)

    present_fields = sum(
        value is not None
        for value in [
            snapshot.temperature_c,
            snapshot.humidity_pct,
            snapshot.pressure_hpa,
            snapshot.wind_gust_kmh,
            snapshot.rain_rate_mm_h,
            snapshot.local_lightning_distance_km,
            snapshot.radar_precip_nearby,
        ]
    )
    confidence = clamp_score(35 + present_fields * 8)

    level = "normal"
    if storm_risk_1h >= 80 or wind_risk >= 80 or lightning_risk >= 85:
        level = "warning"
    elif storm_risk_1h >= 60 or wind_risk >= 60 or lightning_risk >= 60:
        level = "watch"
    elif storm_risk_1h >= 40:
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

    explanation = "; ".join(explanation_parts) if explanation_parts else "No strong local severe-weather signal detected."

    return Prediction(
        storm_risk_1h=storm_risk_1h,
        storm_risk_24h=storm_risk_24h,
        wind_risk_1h=clamp_score(wind_risk),
        rain_risk_1h=clamp_score(rain_risk),
        lightning_risk_1h=clamp_score(lightning_risk),
        confidence=confidence,
        level=level,
        explanation=explanation,
    )
