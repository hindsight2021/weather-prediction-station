from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class WeatherSnapshot:
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    temperature_c: float | None = None
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

    def as_dict(self) -> dict[str, float | str | None]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "temperature_c": self.temperature_c,
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
        }
