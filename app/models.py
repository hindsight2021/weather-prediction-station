from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class WeatherSnapshot:
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    temperature_c: float | None = None
    humidex: float | None = None
    wind_chill_c: float | None = None
    humidity_pct: float | None = None
    pressure_hpa: float | None = None
    wind_speed_kmh: float | None = None
    wind_gust_kmh: float | None = None
    rain_rate_mm_h: float | None = None
    daily_rain_mm: float | None = None
    local_lightning_distance_km: float | None = None
    local_lightning_count_30m: float | None = None
    internet_lightning_count_30m: float | None = None
    radar_precip_nearby: float | None = None
    forecast_precip_probability_1h: float | None = None
    forecast_precip_probability_6h: float | None = None
    forecast_precip_probability_24h: float | None = None
    forecast_precip_mm_1h: float | None = None
    forecast_precip_mm_24h: float | None = None
    forecast_wind_gust_max_1h: float | None = None
    forecast_wind_gust_max_24h: float | None = None
    forecast_next_precip_minutes: float | None = None
    forecast_next_severe_minutes: float | None = None
    forecast_severe_condition_24h: float | None = None
    forecast_source_count: float | None = None

    def as_dict(self) -> dict[str, float | str | None]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "temperature_c": self.temperature_c,
            "humidex": self.humidex,
            "wind_chill_c": self.wind_chill_c,
            "humidity_pct": self.humidity_pct,
            "pressure_hpa": self.pressure_hpa,
            "wind_speed_kmh": self.wind_speed_kmh,
            "wind_gust_kmh": self.wind_gust_kmh,
            "rain_rate_mm_h": self.rain_rate_mm_h,
            "daily_rain_mm": self.daily_rain_mm,
            "local_lightning_distance_km": self.local_lightning_distance_km,
            "local_lightning_count_30m": self.local_lightning_count_30m,
            "internet_lightning_count_30m": self.internet_lightning_count_30m,
            "radar_precip_nearby": self.radar_precip_nearby,
            "forecast_precip_probability_1h": self.forecast_precip_probability_1h,
            "forecast_precip_probability_6h": self.forecast_precip_probability_6h,
            "forecast_precip_probability_24h": self.forecast_precip_probability_24h,
            "forecast_precip_mm_1h": self.forecast_precip_mm_1h,
            "forecast_precip_mm_24h": self.forecast_precip_mm_24h,
            "forecast_wind_gust_max_1h": self.forecast_wind_gust_max_1h,
            "forecast_wind_gust_max_24h": self.forecast_wind_gust_max_24h,
            "forecast_next_precip_minutes": self.forecast_next_precip_minutes,
            "forecast_next_severe_minutes": self.forecast_next_severe_minutes,
            "forecast_severe_condition_24h": self.forecast_severe_condition_24h,
            "forecast_source_count": self.forecast_source_count,
        }


@dataclass
class Prediction:
    storm_risk_1h: int
    storm_risk_24h: int
    wind_risk_1h: int
    rain_risk_1h: int
    lightning_risk_1h: int
    confidence: int
    level: str
    explanation: str
    heat_risk_24h: int = 0
    cold_risk_24h: int = 0
    heat_severity: str = "none"
    cold_severity: str = "none"
    rain_risk_24h: int = 0
    wind_risk_24h: int = 0
    imminent_event: str = "none"
    imminent_minutes: int = -1
    imminent_summary: str = "No imminent weather event detected."

    def as_dict(self) -> dict[str, int | str]:
        return {
            "storm_risk_1h": self.storm_risk_1h,
            "storm_risk_24h": self.storm_risk_24h,
            "wind_risk_1h": self.wind_risk_1h,
            "rain_risk_1h": self.rain_risk_1h,
            "lightning_risk_1h": self.lightning_risk_1h,
            "confidence": self.confidence,
            "level": self.level,
            "explanation": self.explanation,
            "heat_risk_24h": self.heat_risk_24h,
            "cold_risk_24h": self.cold_risk_24h,
            "heat_severity": self.heat_severity,
            "cold_severity": self.cold_severity,
            "rain_risk_24h": self.rain_risk_24h,
            "wind_risk_24h": self.wind_risk_24h,
            "imminent_event": self.imminent_event,
            "imminent_minutes": self.imminent_minutes,
            "imminent_summary": self.imminent_summary,
        }
