from app.ha_bridge import (
    LIGHTNING_COUNT_ENTITY,
    LIGHTNING_DISTANCE_ENTITY,
    LightningActivityTracker,
)


def test_retained_distance_does_not_activate_on_startup() -> None:
    tracker = LightningActivityTracker(active_seconds=1800)

    tracker.prime("89", "22")

    assert tracker.active_until == 0
    assert not tracker.expired(now=9999)


def test_new_strike_activates_then_expires_distance() -> None:
    tracker = LightningActivityTracker(active_seconds=1800)
    tracker.prime("89", "22")

    assert tracker.observe(LIGHTNING_COUNT_ENTITY, "90", now=100) == "22.0"
    assert not tracker.expired(now=1899)
    assert tracker.expired(now=1900)
    assert not tracker.expired(now=1901)


def test_unchanged_or_reset_counter_does_not_activate() -> None:
    tracker = LightningActivityTracker(active_seconds=1800)
    tracker.prime("89", "22")

    assert tracker.observe(LIGHTNING_COUNT_ENTITY, "89", now=100) is None
    assert tracker.observe(LIGHTNING_COUNT_ENTITY, "0", now=100) is None


def test_distance_update_is_cached_for_next_strike() -> None:
    tracker = LightningActivityTracker(active_seconds=1800)
    tracker.prime("89", "22")

    assert tracker.observe(LIGHTNING_DISTANCE_ENTITY, "7", now=100) is None
    assert tracker.observe(LIGHTNING_COUNT_ENTITY, "90", now=101) == "7.0"

