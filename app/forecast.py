from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SEVERE_CONDITIONS = {
    "hail",
    "lightning",
    "lightning-rainy",
    "pouring",
    "snowy-rainy",
}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "", "unknown", "unavailable") else None
    except (TypeError, ValueError):
        return None


def _when(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def summarize_hourly_forecasts(
    response: dict[str, Any], now: datetime | None = None
) -> dict[str, float]:
    """Reduce HA hourly forecasts to conservative 1h/6h/24h prediction features.

    Each provider is aggregated independently before providers are combined, so
    precipitation totals are not double-counted. Risks use the most cautious
    provider while retaining a source count for confidence scoring.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    provider_summaries: list[dict[str, float]] = []
    for payload in (response or {}).values():
        entries = payload.get("forecast", []) if isinstance(payload, dict) else []
        rows: list[tuple[float, dict[str, Any]]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            timestamp = _when(entry.get("datetime"))
            if timestamp is None:
                continue
            minutes = (timestamp.astimezone(timezone.utc) - now).total_seconds() / 60.0
            if -30 <= minutes <= 24 * 60 + 90:
                rows.append((max(0.0, minutes), entry))
        if not rows:
            continue

        def within(minutes: int) -> list[tuple[float, dict[str, Any]]]:
            # Hourly forecasts are usually stamped at the top of the hour, so
            # the 1h window accepts the next hourly bucket up to 90 minutes away.
            limit = 90 if minutes == 60 else minutes
            return [(offset, entry) for offset, entry in rows if offset <= limit]

        summary: dict[str, float] = {}
        for label, minutes in (("1h", 60), ("6h", 360), ("24h", 1440)):
            window = within(minutes)
            probabilities = [
                value
                for _offset, entry in window
                if (value := _number(entry.get("precipitation_probability"))) is not None
            ]
            precipitation = [
                value
                for _offset, entry in window
                if (value := _number(entry.get("precipitation"))) is not None
            ]
            gusts = [
                value
                for _offset, entry in window
                if (value := _number(entry.get("wind_gust_speed") or entry.get("wind_speed"))) is not None
            ]
            summary[f"forecast_precip_probability_{label}"] = max(probabilities, default=0.0)
            summary[f"forecast_precip_mm_{label}"] = sum(precipitation)
            summary[f"forecast_wind_gust_max_{label}"] = max(gusts, default=0.0)

        temperatures = [
            value
            for _offset, entry in within(1440)
            if (value := _number(entry.get("temperature"))) is not None
        ]
        summary["forecast_temp_min_24h"] = min(temperatures, default=0.0)
        summary["forecast_temp_max_24h"] = max(temperatures, default=0.0)
        precip_offsets = [
            offset
            for offset, entry in rows
            if (_number(entry.get("precipitation_probability")) or 0) >= 50
            or (_number(entry.get("precipitation")) or 0) > 0.1
            or str(entry.get("condition", "")).lower() in SEVERE_CONDITIONS
        ]
        severe_offsets = [
            offset
            for offset, entry in rows
            if str(entry.get("condition", "")).lower() in SEVERE_CONDITIONS
        ]
        summary["forecast_next_precip_minutes"] = min(precip_offsets, default=-1.0)
        summary["forecast_next_severe_minutes"] = min(severe_offsets, default=-1.0)
        summary["forecast_severe_condition_24h"] = 1.0 if severe_offsets else 0.0
        provider_summaries.append(summary)

    if not provider_summaries:
        return {}
    keys = set().union(*(summary.keys() for summary in provider_summaries))
    combined: dict[str, float] = {}
    for key in keys:
        values = [summary[key] for summary in provider_summaries if key in summary]
        if key == "forecast_temp_min_24h":
            combined[key] = min(values)
        elif key.startswith("forecast_next_"):
            valid = [value for value in values if value >= 0]
            combined[key] = min(valid, default=-1.0)
        else:
            combined[key] = max(values)
    combined["forecast_source_count"] = float(len(provider_summaries))
    return combined
