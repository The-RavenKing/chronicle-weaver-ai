"""Tests for death saving throws and the dying/stable combatant states."""

from __future__ import annotations


from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.rules.combatant import (
    CombatantSnapshot,
    is_dying,
    is_stable,
    roll_death_save,
)


def _dying_actor(
    hp: int = 0, successes: int = 0, failures: int = 0
) -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id="pc.test",
        display_name="Test Fighter",
        source_type="actor",
        source_id="pc.test",
        armor_class=16,
        hit_points=hp,
        death_save_successes=successes,
        death_save_failures=failures,
    )


def _monster_snap() -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id="m.goblin",
        display_name="Goblin",
        source_type="monster",
        source_id="m.goblin",
        armor_class=13,
        hit_points=0,
    )


# ── is_dying ─────────────────────────────────────────────────────────────────


def test_is_dying_true_when_actor_at_zero_hp() -> None:
    snap = _dying_actor(hp=0)
    assert is_dying(snap) is True


def test_is_dying_false_when_actor_has_hp() -> None:
    snap = _dying_actor(hp=5)
    assert is_dying(snap) is False


def test_is_dying_false_for_monster_at_zero_hp() -> None:
    snap = _monster_snap()
    assert is_dying(snap) is False


def test_is_dying_true_for_companion_at_zero_hp() -> None:
    snap = CombatantSnapshot(
        combatant_id="comp.ally",
        display_name="Elara",
        source_type="companion",
        source_id="comp.ally",
        armor_class=14,
        hit_points=0,
    )
    assert is_dying(snap) is True


# ── is_stable ────────────────────────────────────────────────────────────────


def test_is_stable_requires_three_successes() -> None:
    assert is_stable(_dying_actor(hp=0, successes=2)) is False
    assert is_stable(_dying_actor(hp=0, successes=3)) is True


def test_is_stable_false_when_hp_nonzero() -> None:
    assert is_stable(_dying_actor(hp=1, successes=3)) is False


# ── roll_death_save ──────────────────────────────────────────────────────────


def test_roll_death_save_success_on_ten_or_higher() -> None:
    # entropy=9 → d20=10 → success
    provider = FixedEntropyDiceProvider((9,))
    snap = _dying_actor()
    new_snap, result = roll_death_save(snap, provider)
    assert result.outcome == "success"
    assert result.successes_added == 1
    assert result.failures_added == 0
    assert new_snap.death_save_successes == 1
    assert new_snap.death_save_failures == 0


def test_roll_death_save_failure_on_nine_or_lower() -> None:
    # entropy=8 → d20=9 → failure
    provider = FixedEntropyDiceProvider((8,))
    snap = _dying_actor()
    new_snap, result = roll_death_save(snap, provider)
    assert result.outcome == "failure"
    assert result.successes_added == 0
    assert result.failures_added == 1
    assert new_snap.death_save_failures == 1


def test_roll_death_save_nat_20_is_critical_save() -> None:
    # entropy=19 → d20=20 → critical_save (2 successes)
    provider = FixedEntropyDiceProvider((19,))
    snap = _dying_actor()
    new_snap, result = roll_death_save(snap, provider)
    assert result.outcome == "critical_save"
    assert result.successes_added == 2
    assert new_snap.death_save_successes == 2


def test_roll_death_save_nat_1_is_critical_fail() -> None:
    # entropy=0 → d20=1 → critical_fail (2 failures)
    provider = FixedEntropyDiceProvider((0,))
    snap = _dying_actor()
    new_snap, result = roll_death_save(snap, provider)
    assert result.outcome == "critical_fail"
    assert result.failures_added == 2
    assert new_snap.death_save_failures == 2


def test_roll_death_save_three_successes_is_stable() -> None:
    # already 2 successes, roll 10+ → stable
    provider = FixedEntropyDiceProvider((9,))  # d20=10
    snap = _dying_actor(successes=2)
    new_snap, result = roll_death_save(snap, provider)
    assert result.outcome == "stable"
    assert new_snap.death_save_successes == 3


def test_roll_death_save_three_failures_is_dead() -> None:
    # already 2 failures, roll < 10 → dead
    provider = FixedEntropyDiceProvider((0,))  # d20=1 → 2 failures = total 4
    snap = _dying_actor(failures=2)
    new_snap, result = roll_death_save(snap, provider)
    assert result.outcome == "dead"
    assert new_snap.death_save_failures >= 3


def test_roll_death_save_accumulates_across_calls() -> None:
    # 3 failures across multiple calls → dead
    snap = _dying_actor()
    for _ in range(3):
        provider = FixedEntropyDiceProvider((0,))  # d20=1 → 2 failures each
        snap, result = roll_death_save(snap, provider)
        if result.outcome == "dead":
            break
    assert result.outcome == "dead"
