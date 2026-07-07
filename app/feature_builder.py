from __future__ import annotations

from collections import deque
from datetime import timedelta
from statistics import mean, pstdev
from typing import Iterable

from app.models import WeatherSnapshot


class SnapshotStore:
    def __init__(self, maxlen: int) -> None:
        self._snapshots: deque[WeatherSnapshot] = deque(maxlen=maxlen)

    def add(self, snapshot: WeatherSnapshot) -> None:
        self._snapshots.append(snapshot)

    def latest(self) -> WeatherSnapshot | None:
        if not self._snapshots:
            return None
        return self._snapshots[-1]

    def all(self) -> list[WeatherSnapshot]:
        return list(self._snapshots)

    def pressure_delta(self, hours: float) -> float | None:
        return _delta_for_field(self._snapshots, "pressure_hpa", hours)

    def humidity_delta(self, hours: float) -> float | None:
        return _delta_for_field(self._snapshots, "humidity_pct", hours)

    def temp_delta(self, hours: float) -> float | None:
        return _delta_for_field(self._snapshots, "temperature_c", hours)

    def wind_speed_mean(self, hours: float) -> float | None:
        values = _values_since_hours(self._snapshots, "wind_speed_kmh", hours)
        return mean(values) if values else None

    def wind_speed_std(self, hours: float) -> float | None:
        values = _values_since_hours(self._snapshots, "wind_speed_kmh", hours)
        return pstdev(values) if len(values) > 1 else 0.0 if values else None

    def max_wind_gust(self, minutes: int) -> float | None:
        values = _values_since(self._snapshots, "wind_gust_kmh", minutes)
        return max(values) if values else None

    def max_rain_rate(self, minutes: int) -> float | None:
        values = _values_since(self._snapshots, "rain_rate_mm_h", minutes)
        return max(values) if values else None


def _values_since(snapshots: Iterable[WeatherSnapshot], field_name: str, minutes: int) -> list[float]:
    items = list(snapshots)
    if not items:
        return []

    cutoff = items[-1].timestamp - timedelta(minutes=minutes)
    values: list[float] = []
    for item in items:
        value = getattr(item, field_name)
        if item.timestamp >= cutoff and value is not None:
            values.append(float(value))
    return values


def _values_since_hours(snapshots: Iterable[WeatherSnapshot], field_name: str, hours: float) -> list[float]:
    return _values_since(snapshots, field_name, int(hours * 60))


def _delta_for_field(snapshots: Iterable[WeatherSnapshot], field_name: str, hours: float) -> float | None:
    items = list(snapshots)
    if len(items) < 2:
        return None

    latest = items[-1]
    latest_value = getattr(latest, field_name)
    if latest_value is None:
        return None

    target_time = latest.timestamp - timedelta(hours=hours)
    earlier = min(items, key=lambda item: abs(item.timestamp - target_time))
    earlier_value = getattr(earlier, field_name)
    if earlier_value is None:
        return None

    return float(latest_value) - float(earlier_value)
