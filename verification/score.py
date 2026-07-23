"""Join logged predictions with derived outcomes and compute proper scores.

Per hazard and horizon this produces Brier score, reliability bins, and a
POD/FAR/CSI contingency table at the advisory tier, compared against three
references computed from the same logs (roadmap §3.2):

- climatology: the event's base rate in the joined sample
- persistence: event occurred in the equal-length window before the prediction
- raw forecast: the HA/ECCC forecast fields already carried in each snapshot
"""

from __future__ import annotations

import logging
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from pathlib import Path

from verification.hazards import (
    HAZARDS,
    TIER_THRESHOLDS,
    WIND_GUST_ADVISORY_KMH,
    HazardSpec,
    observed_event,
)
from verification.outcome_logger import (
    ALERTS_PATH,
    alert_active_in_window,
    load_jsonl,
    parse_timestamp,
)

LOGGER = logging.getLogger("verification.score")

DEFAULT_PREDICTIONS_PATH = Path("data/predictions.jsonl")
DEFAULT_SNAPSHOTS_PATH = Path("data/weather_snapshots.jsonl")

RELIABILITY_BINS = 10
ADVISORY_PROBABILITY = TIER_THRESHOLDS["advisory"] / 100.0


def brier(pairs: list[tuple[float, int]]) -> float | None:
    """Mean squared error between probability p and binary outcome."""
    if not pairs:
        return None
    return sum((p - outcome) ** 2 for p, outcome in pairs) / len(pairs)


def reliability_bins(pairs: list[tuple[float, int]], bins: int = RELIABILITY_BINS) -> list[dict]:
    result = []
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        members = [
            (p, o) for p, o in pairs if low <= p < high or (index == bins - 1 and p == 1.0)
        ]
        result.append(
            {
                "bin_low": low,
                "bin_high": high,
                "n": len(members),
                "mean_probability": (sum(p for p, _ in members) / len(members)) if members else None,
                "observed_frequency": (sum(o for _, o in members) / len(members)) if members else None,
            }
        )
    return result


def contingency(pairs: list[tuple[float, int]], probability_threshold: float) -> dict:
    tp = sum(1 for p, o in pairs if p >= probability_threshold and o == 1)
    fp = sum(1 for p, o in pairs if p >= probability_threshold and o == 0)
    fn = sum(1 for p, o in pairs if p < probability_threshold and o == 1)
    tn = sum(1 for p, o in pairs if p < probability_threshold and o == 0)
    pod = tp / (tp + fn) if (tp + fn) else None
    far = fp / (fp + tp) if (fp + tp) else None
    csi = tp / (tp + fp + fn) if (tp + fp + fn) else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "pod": pod, "far": far, "csi": csi}


class SnapshotIndex:
    """Time-sorted snapshot log with fast window queries."""

    def __init__(self, snapshots: list[dict]) -> None:
        stamped = []
        for row in snapshots:
            timestamp = parse_timestamp(row.get("timestamp"))
            if timestamp is not None:
                stamped.append((timestamp, row))
        stamped.sort(key=lambda item: item[0])
        self._times = [timestamp for timestamp, _ in stamped]
        self._rows = [row for _, row in stamped]

    def window(self, start: datetime, end: datetime) -> list[dict]:
        """Rows with start < timestamp <= end."""
        lo = bisect_right(self._times, start)
        hi = bisect_right(self._times, end)
        return self._rows[lo:hi]

    def coverage_until(self) -> datetime | None:
        return self._times[-1] if self._times else None

    def value_at(self, timestamp: datetime, field: str) -> float | None:
        index = bisect_left(self._times, timestamp)
        for candidate in (index, index - 1):
            if 0 <= candidate < len(self._rows):
                value = self._rows[candidate].get(field)
                if value is not None:
                    return float(value)
        return None


def forecast_reference_probability(spec: HazardSpec, snapshot_index: SnapshotIndex, at: datetime) -> float | None:
    """Probability implied by the raw HA/ECCC forecast fields at prediction time."""
    if spec.forecast_reference_field is None:
        return None
    value = snapshot_index.value_at(at, spec.forecast_reference_field)
    if value is None:
        return None
    if "precip_probability" in spec.forecast_reference_field:
        return max(0.0, min(1.0, value / 100.0))
    if "wind_gust" in spec.forecast_reference_field:
        return 1.0 if value >= WIND_GUST_ADVISORY_KMH else 0.0
    if "severe_condition" in spec.forecast_reference_field:
        return 1.0 if value > 0 else 0.0
    if "next_severe_minutes" in spec.forecast_reference_field:
        # A severe signal forecast to arrive within the 1h horizon.
        return 1.0 if 0 <= value <= 60 else 0.0
    return None


def event_in_window(
    spec: HazardSpec,
    snapshot_index: SnapshotIndex,
    alerts: list[dict],
    start: datetime,
    end: datetime,
) -> bool:
    occurred = False
    if "obs" in spec.sources:
        occurred = observed_event(spec.name, snapshot_index.window(start, end))
    if not occurred and "alert" in spec.sources and spec.alert_hazard:
        occurred = any(
            alert.get("hazard") == spec.alert_hazard
            and alert.get("status", "Actual") == "Actual"
            and alert_active_in_window(alert, start, end)
            for alert in alerts
        )
    return occurred


def score_hazard(
    spec: HazardSpec,
    predictions: list[dict],
    snapshot_index: SnapshotIndex,
    alerts: list[dict],
    window_days: int | None = 30,
) -> dict:
    coverage_until = snapshot_index.coverage_until()
    pairs: list[tuple[float, int]] = []
    persistence_pairs: list[tuple[float, int]] = []
    forecast_pairs: list[tuple[float, int]] = []

    newest = None
    for row in predictions:
        timestamp = parse_timestamp(row.get("timestamp"))
        if timestamp is None or row.get(spec.prediction_field) is None:
            continue
        newest = timestamp if newest is None or timestamp > newest else newest
    for row in predictions:
        timestamp = parse_timestamp(row.get("timestamp"))
        if timestamp is None or row.get(spec.prediction_field) is None:
            continue
        if window_days is not None and newest is not None and timestamp < newest - timedelta(days=window_days):
            continue
        horizon = timedelta(hours=spec.horizon_hours)
        window_end = timestamp + horizon
        # Only verify windows the snapshot log fully covers.
        if coverage_until is None or window_end > coverage_until:
            continue
        outcome = int(event_in_window(spec, snapshot_index, alerts, timestamp, window_end))
        probability = max(0.0, min(1.0, float(row[spec.prediction_field]) / 100.0))
        pairs.append((probability, outcome))

        previous_event = int(
            event_in_window(spec, snapshot_index, alerts, timestamp - horizon, timestamp)
        )
        persistence_pairs.append((float(previous_event), outcome))

        forecast_probability = forecast_reference_probability(spec, snapshot_index, timestamp)
        if forecast_probability is not None:
            forecast_pairs.append((forecast_probability, outcome))

    base_rate = (sum(o for _, o in pairs) / len(pairs)) if pairs else None
    climatology_pairs = [(base_rate, o) for _, o in pairs] if base_rate is not None else []

    system_brier = brier(pairs)
    climatology_brier = brier(climatology_pairs)
    skill_vs_climatology = None
    if system_brier is not None and climatology_brier not in (None, 0.0):
        skill_vs_climatology = 1.0 - system_brier / climatology_brier

    return {
        "hazard": spec.name,
        "horizon_hours": spec.horizon_hours,
        "n": len(pairs),
        "event_rate": base_rate,
        "brier": system_brier,
        "brier_climatology": climatology_brier,
        "brier_persistence": brier(persistence_pairs),
        "brier_forecast": brier(forecast_pairs),
        "n_forecast_reference": len(forecast_pairs),
        "brier_skill_vs_climatology": skill_vs_climatology,
        "reliability": reliability_bins(pairs),
        "advisory_tier": contingency(pairs, ADVISORY_PROBABILITY),
    }


def build_scoreboard(
    predictions_path: Path = DEFAULT_PREDICTIONS_PATH,
    snapshots_path: Path = DEFAULT_SNAPSHOTS_PATH,
    alerts_path: Path = ALERTS_PATH,
    window_days: int | None = 30,
) -> dict:
    predictions = load_jsonl(predictions_path)
    snapshots = load_jsonl(snapshots_path)
    snapshot_index = SnapshotIndex(snapshots)
    alerts = load_jsonl(alerts_path)
    LOGGER.info(
        "Scoring %d predictions against %d snapshots and %d alert rows",
        len(predictions), len(snapshots), len(alerts),
    )
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "window_days": window_days,
        "predictions_scored_from": str(predictions_path),
        "hazards": [
            score_hazard(spec, predictions, snapshot_index, alerts, window_days)
            for spec in HAZARDS
        ],
    }
