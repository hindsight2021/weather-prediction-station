from __future__ import annotations

from app.input_hygiene import (
    DEFAULT_TRANSIENT_TTL_SECONDS,
    TRANSIENT_INPUT_FIELDS,
    prune_stale_transient_inputs,
)


def _values(**overrides: float | None) -> dict[str, float | None]:
    base: dict[str, float | None] = {
        "temperature_c": 21.0,
        "pressure_hpa": 1008.0,
        "local_lightning_distance_km": 8.0,
        "local_lightning_count_30m": 3.0,
        "internet_lightning_count_30m": 12.0,
        "radar_precip_nearby": 1.0,
    }
    base.update(overrides)
    return base


def test_fresh_live_transient_input_is_kept() -> None:
    now = 10_000.0
    received = {field: now - 60.0 for field in TRANSIENT_INPUT_FIELDS}
    pruned = prune_stale_transient_inputs(_values(), received, now)
    assert pruned["local_lightning_distance_km"] == 8.0
    assert pruned["radar_precip_nearby"] == 1.0


def test_stale_live_transient_input_is_dropped() -> None:
    now = 10_000.0
    # Last live report is older than the TTL for every transient field.
    received = {field: now - DEFAULT_TRANSIENT_TTL_SECONDS - 1.0 for field in TRANSIENT_INPUT_FIELDS}
    pruned = prune_stale_transient_inputs(_values(), received, now)
    for field in TRANSIENT_INPUT_FIELDS:
        assert pruned[field] is None


def test_retained_only_transient_input_is_dropped() -> None:
    # A value present with no live receipt stamp was only ever delivered
    # retained (a broker replay) — it must not be trusted.
    now = 10_000.0
    pruned = prune_stale_transient_inputs(_values(), {}, now)
    assert pruned["local_lightning_distance_km"] is None
    assert pruned["local_lightning_count_30m"] is None


def test_non_transient_inputs_are_never_pruned() -> None:
    now = 10_000.0
    pruned = prune_stale_transient_inputs(_values(), {}, now)
    assert pruned["temperature_c"] == 21.0
    assert pruned["pressure_hpa"] == 1008.0


def test_boundary_at_exactly_ttl_is_kept() -> None:
    now = 10_000.0
    received = {"local_lightning_distance_km": now - DEFAULT_TRANSIENT_TTL_SECONDS}
    pruned = prune_stale_transient_inputs(
        {"local_lightning_distance_km": 8.0}, received, now
    )
    # Exactly at the TTL is still fresh; only strictly older is dropped.
    assert pruned["local_lightning_distance_km"] == 8.0


def test_none_transient_input_stays_none_without_error() -> None:
    now = 10_000.0
    pruned = prune_stale_transient_inputs(
        {"local_lightning_distance_km": None}, {}, now
    )
    assert pruned["local_lightning_distance_km"] is None


def test_input_is_copied_not_mutated() -> None:
    now = 10_000.0
    original = _values()
    prune_stale_transient_inputs(original, {}, now)
    # The caller's dict is untouched; only the returned copy is pruned.
    assert original["local_lightning_distance_km"] == 8.0
