"""Tests for expanded conditions: blinded, frightened, charmed, incapacitated, restrained."""

from __future__ import annotations

from chronicle_weaver_ai.rules.combatant import CombatantSnapshot
from chronicle_weaver_ai.rules.conditions import (
    Condition,
    attack_roll_mode,
    is_blocked_by_conditions,
    target_grants_advantage,
)


def _snap(*condition_names: str) -> CombatantSnapshot:
    conditions = tuple(
        Condition(condition_name=name, source="test", duration_type="persistent")
        for name in condition_names
    )
    return CombatantSnapshot(
        combatant_id="pc.test",
        display_name="Tester",
        source_type="actor",
        source_id="pc.test",
        armor_class=15,
        hit_points=20,
        conditions=conditions,
    )


# ── Blocking conditions ───────────────────────────────────────────────────────


def test_incapacitated_blocks_actions() -> None:
    snap = _snap("incapacitated")
    assert is_blocked_by_conditions(snap) is not None


def test_stunned_blocks_actions() -> None:
    snap = _snap("stunned")
    assert is_blocked_by_conditions(snap) is not None


def test_blinded_does_not_block_actions() -> None:
    snap = _snap("blinded")
    assert is_blocked_by_conditions(snap) is None


def test_frightened_does_not_block_actions() -> None:
    snap = _snap("frightened")
    assert is_blocked_by_conditions(snap) is None


# ── Disadvantage on attacks ───────────────────────────────────────────────────


def test_blinded_imposes_disadvantage() -> None:
    assert attack_roll_mode(_snap("blinded")) == "disadvantage"


def test_frightened_imposes_disadvantage() -> None:
    assert attack_roll_mode(_snap("frightened")) == "disadvantage"


def test_restrained_imposes_disadvantage() -> None:
    assert attack_roll_mode(_snap("restrained")) == "disadvantage"


def test_exhausted_imposes_disadvantage() -> None:
    assert attack_roll_mode(_snap("exhausted")) == "disadvantage"


def test_charmed_does_not_impose_disadvantage() -> None:
    assert attack_roll_mode(_snap("charmed")) == "normal"


def test_incapacitated_does_not_impose_disadvantage() -> None:
    # Incapacitated blocks actions but doesn't specifically add attack disadvantage
    assert attack_roll_mode(_snap("incapacitated")) == "normal"


# ── Target grants advantage to attackers ─────────────────────────────────────


def test_prone_target_grants_advantage() -> None:
    assert target_grants_advantage(_snap("prone")) is True


def test_blinded_target_grants_advantage() -> None:
    assert target_grants_advantage(_snap("blinded")) is True


def test_stunned_target_grants_advantage() -> None:
    assert target_grants_advantage(_snap("stunned")) is True


def test_restrained_target_grants_advantage() -> None:
    assert target_grants_advantage(_snap("restrained")) is True


def test_poisoned_does_not_grant_advantage_to_attackers() -> None:
    assert target_grants_advantage(_snap("poisoned")) is False


def test_frightened_does_not_grant_advantage_to_attackers() -> None:
    assert target_grants_advantage(_snap("frightened")) is False


def test_no_conditions_no_advantage() -> None:
    assert target_grants_advantage(_snap()) is False
