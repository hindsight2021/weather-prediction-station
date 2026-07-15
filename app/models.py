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
    forecast_temp_min_24h: float | None = None
    forecast_temp_max_24h: float | None = None
    official_alert_severity: float | None = None
    official_alert_count: float | None = None
    aqhi_current: float | None = None
    aqhi_forecast_max_24h: float | None = None
    aqhi_forecast_max_48h: float | None = None
    smoke_risk: float | None = None
    nb_burn_category: float | None = None
    active_fires_nearby: float | None = None
    forecast_precip_probability_48h: float | None = None
    forecast_precip_probability_72h: float | None = None
    forecast_wind_gust_max_48h: float | None = None
    forecast_wind_gust_max_72h: float | None = None
    forecast_severe_condition_48h: float | None = None
    forecast_severe_condition_72h: float | None = None

    def as_dict(self) -> dict[str, float | str | None]:
        result = {
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
        for key in (
            "forecast_temp_min_24h", "forecast_temp_max_24h", "official_alert_severity",
            "official_alert_count", "aqhi_current", "aqhi_forecast_max_24h",
            "aqhi_forecast_max_48h", "smoke_risk", "nb_burn_category", "active_fires_nearby",
            "forecast_precip_probability_48h", "forecast_precip_probability_72h",
            "forecast_wind_gust_max_48h", "forecast_wind_gust_max_72h",
            "forecast_severe_condition_48h", "forecast_severe_condition_72h",
        ):
            result[key] = getattr(self, key)
        return result


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
    storm_risk_48h: int = 0
    storm_risk_72h: int = 0
    air_quality_risk_24h: int = 0
    air_quality_risk_48h: int = 0
    smoke_risk_24h: int = 0
    aqhi_current: int = 0
    aqhi_forecast_max_24h: int = 0
    official_alert_level: str = "none"
    official_alert_summary: str = "No active ECCC alert."
    nb_burn_status: str = "unknown"
    active_fires_nearby: int = 0

    def as_dict(self) -> dict[str, int | str]:
        result = {
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
        for key in (
            "storm_risk_48h", "storm_risk_72h", "air_quality_risk_24h", "air_quality_risk_48h",
            "smoke_risk_24h", "aqhi_current", "aqhi_forecast_max_24h", "official_alert_level",
            "official_alert_summary", "nb_burn_status", "active_fires_nearby",
        ):
            result[key] = getattr(self, key)
        return result
