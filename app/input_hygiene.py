"""Freshness/retention hygiene for transient MQTT inputs.

Some inputs are *event-driven and short-lived* — a lightning strike report is
only meaningful for a few tens of minutes, and an MQTT broker will happily
re-deliver the last retained strike on every reconnect. The console already
learned this the hard way (see the "don't let stale/retained lightning reports
latch the storm scene" hotfix): the AcuRite 6045M false-triggers on EMI from
the well pump, and a single stale distance reading kept "thunderstorm
conditions" on screen indefinitely.

The prediction engine has the same exposure but higher stakes: a stale
``local_lightning_distance_km`` inflates the *published* storm/lightning score
AND, once logged, fabricates a lightning "event" in the verification ground
truth (verification/hazards.py). Garbage on both sides of the comparison is a
direct hit to the Brier score.

Policy, mirroring the console:
- Retained MQTT deliveries never earn a freshness stamp (they are historical
  replays), so they are treated as already-expired for transient fields.
- A transient field is only trusted for ``ttl_seconds`` after the last *live*
  message; past that it reverts to None rather than lingering forever.

Non-transient inputs (temperature, pressure, ...) are slow-moving state and are
deliberately left untouched: the last good reading is the right fallback there.
"""

from __future__ import annotations

# Event-driven inputs whose meaning decays with age. Kept deliberately narrow:
# only fields that represent a transient event, not slow-moving state.
TRANSIENT_INPUT_FIELDS: frozenset[str] = frozenset(
    {
        "local_lightning_distance_km",
        "local_lightning_count_30m",
        "internet_lightning_count_30m",
        "radar_precip_nearby",
    }
)

# Default freshness window for transient inputs, matching the console's guard.
DEFAULT_TRANSIENT_TTL_SECONDS = 2700.0  # 45 minutes


def prune_stale_transient_inputs(
    values: dict[str, float | None],
    live_received_at: dict[str, float],
    now: float,
    ttl_seconds: float = DEFAULT_TRANSIENT_TTL_SECONDS,
    fields: frozenset[str] = TRANSIENT_INPUT_FIELDS,
) -> dict[str, float | None]:
    """Return a copy of ``values`` with expired transient fields set to None.

    A transient field is expired when it has no recorded *live* receipt time
    (only ever arrived retained, or never arrived) or its last live receipt is
    older than ``ttl_seconds``. ``live_received_at`` holds the monotonic clock
    reading of the last non-retained message per field; ``now`` is the current
    reading of the same clock.
    """
    pruned = dict(values)
    for field in fields:
        if pruned.get(field) is None:
            continue
        received_at = live_received_at.get(field)
        if received_at is None or (now - received_at) > ttl_seconds:
            pruned[field] = None
    return pruned
