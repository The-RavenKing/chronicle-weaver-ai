"""Tests for condition system (Milestone: Conditions + Status Effects v0)."""

from __future__ import annotations

from chronicle_weaver_ai.rules import (
    Condition,
    CombatantSnapshot,
    SUPPORTED_CONDITIONS,
    add_condition,
    remove_condition,
    tick_condition_durations,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _snap() -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id="m.goblin",
        display_name="Goblin",
        source_type="monster",
        source_id="m.goblin",
        armor_class=13,
        hit_points=7,
    )


def _prone(rounds: int = 2) -> Condition:
    return Condition(
        condition_name="prone",
        source="attack.trip",
        duration_type="rounds",
        remaining_rounds=rounds,
    )


def _poisoned_persistent() -> Condition:
    return Condition(
        condition_name="poisoned",
        source="spell.poison_cloud",
        duration_type="persistent",
        remaining_rounds=None,
    )


def _stunned_eot() -> Condition:
    return Condition(
        condition_name="stunned",
        source="feature.stunning_strike",
        duration_type="until_end_of_turn",
        remaining_rounds=None,
    )


# ── Supported conditions ──────────────────────────────────────────────────────


def test_supported_conditions_set_contains_expected_names() -> None:
    """SUPPORTED_CONDITIONS must contain the v0 required set."""
    assert "prone" in SUPPORTED_CONDITIONS
    assert "poisoned" in SUPPORTED_CONDITIONS
    assert "stunned" in SUPPORTED_CONDITIONS


# ── add_condition ─────────────────────────────────────────────────────────────


def test_add_condition_appears_on_snapshot() -> None:
    """add_condition must append the condition to the snapshot's conditions tuple."""
    snap = _snap()
    assert snap.conditions == ()

    updated = add_condition(snap, _prone())
    assert len(updated.conditions) == 1
    assert updated.conditions[0].condition_name == "prone"
    assert updated.conditions[0].remaining_rounds == 2


def test_add_condition_replaces_duplicate_name() -> None:
    """Adding a condition whose name already exists must replace, not stack."""
    snap = add_condition(_snap(), _prone(rounds=3))
    snap = add_condition(snap, _prone(rounds=1))  # replace with shorter duration

    assert len(snap.conditions) == 1
    assert snap.conditions[0].remaining_rounds == 1


def test_add_multiple_distinct_conditions() -> None:
    """Multiple distinct conditions must all appear on the snapshot."""
    snap = _snap()
    snap = add_condition(snap, _prone())
    snap = add_condition(snap, _poisoned_persistent())
    snap = add_condition(snap, _stunned_eot())

    names = {c.condition_name for c in snap.conditions}
    assert names == {"prone", "poisoned", "stunned"}


# ── remove_condition ──────────────────────────────────────────────────────────


def test_remove_condition_by_name() -> None:
    """remove_condition must strip all conditions matching the given name."""
    snap = add_condition(_snap(), _prone())
    snap = add_condition(snap, _poisoned_persistent())

    cleaned = remove_condition(snap, "prone")
    names = {c.condition_name for c in cleaned.conditions}
    assert "prone" not in names
    assert "poisoned" in names


def test_remove_condition_no_op_when_absent() -> None:
    """remove_condition must return an equivalent snapshot if name is not present."""
    snap = add_condition(_snap(), _prone())
    result = remove_condition(snap, "stunned")
    assert result.conditions == snap.conditions


# ── tick_condition_durations ──────────────────────────────────────────────────


def test_tick_decrements_rounds_duration() -> None:
    """tick_condition_durations must decrement remaining_rounds by 1."""
    snap = add_condition(_snap(), _prone(rounds=3))
    ticked = tick_condition_durations(snap)

    assert len(ticked.conditions) == 1
    assert ticked.conditions[0].remaining_rounds == 2


def test_tick_removes_expired_rounds_condition() -> None:
    """A rounds condition at remaining_rounds=1 must be removed after one tick."""
    snap = add_condition(_snap(), _prone(rounds=1))
    ticked = tick_condition_durations(snap)

    assert ticked.conditions == ()


def test_tick_removes_until_end_of_turn_condition() -> None:
    """until_end_of_turn conditions must be removed by tick_condition_durations."""
    snap = add_condition(_snap(), _stunned_eot())
    ticked = tick_condition_durations(snap)

    assert ticked.conditions == ()


def test_tick_leaves_persistent_condition_unchanged() -> None:
    """persistent conditions must survive tick_condition_durations untouched."""
    snap = add_condition(_snap(), _poisoned_persistent())
    ticked = tick_condition_durations(snap)

    assert len(ticked.conditions) == 1
    assert ticked.conditions[0].condition_name == "poisoned"
    assert ticked.conditions[0].duration_type == "persistent"


def test_tick_leaves_instant_condition_unchanged() -> None:
    """instant conditions must survive tick_condition_durations untouched."""
    instant = Condition(
        condition_name="prone",
        source="spell.grease",
        duration_type="instant",
        remaining_rounds=None,
    )
    snap = add_condition(_snap(), instant)
    ticked = tick_condition_durations(snap)

    assert len(ticked.conditions) == 1
    assert ticked.conditions[0].duration_type == "instant"


def test_tick_handles_mixed_conditions() -> None:
    """tick must expire time-limited conditions while preserving persistent ones."""
    snap = _snap()
    snap = add_condition(snap, _prone(rounds=1))  # will expire
    snap = add_condition(snap, _stunned_eot())  # will expire
    snap = add_condition(snap, _poisoned_persistent())  # survives

    ticked = tick_condition_durations(snap)

    names = {c.condition_name for c in ticked.conditions}
    assert names == {"poisoned"}
