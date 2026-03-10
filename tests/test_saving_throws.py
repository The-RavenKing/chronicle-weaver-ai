"""Tests for ability saving throws."""

from __future__ import annotations

from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot, roll_saving_throw


def _snap(dex: int = 14, proficiency_bonus: int = 2) -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id="pc.test",
        display_name="Tester",
        source_type="actor",
        source_id="pc.test",
        armor_class=15,
        hit_points=20,
        abilities={"str": 10, "dex": dex, "con": 12, "int": 10, "wis": 10, "cha": 10},
        proficiency_bonus=proficiency_bonus,
    )


def test_saving_throw_success_meets_dc() -> None:
    # DEX 14 → mod=+2; roll=10 → total=12 ≥ DC 12 → success
    provider = FixedEntropyDiceProvider((9,))  # d20=10
    result = roll_saving_throw(_snap(dex=14), "dex", dc=12, dice_provider=provider)
    assert result.success is True
    assert result.total == 12


def test_saving_throw_failure_below_dc() -> None:
    # DEX 14 → mod=+2; roll=5 → total=7 < DC 12 → failure
    provider = FixedEntropyDiceProvider((4,))  # d20=5
    result = roll_saving_throw(_snap(dex=14), "dex", dc=12, dice_provider=provider)
    assert result.success is False
    assert result.total == 7


def test_saving_throw_proficiency_adds_bonus() -> None:
    # DEX 14 → mod=+2; proficiency=+2; roll=5 → total=9 < DC 12 without prof
    # with prof: 5+2+2=9 still fails... use higher roll
    provider = FixedEntropyDiceProvider((7,))  # d20=8 → 8+2+2=12 → success
    result = roll_saving_throw(
        _snap(dex=14, proficiency_bonus=2),
        "dex",
        dc=12,
        dice_provider=provider,
        proficient_saves=frozenset({"dex"}),
    )
    assert result.proficiency_applied is True
    assert result.total == 12
    assert result.success is True


def test_saving_throw_no_proficiency_without_set() -> None:
    provider = FixedEntropyDiceProvider((9,))  # d20=10
    result = roll_saving_throw(_snap(dex=14), "dex", dc=12, dice_provider=provider)
    assert result.proficiency_applied is False


def test_saving_throw_case_insensitive_ability() -> None:
    provider = FixedEntropyDiceProvider((9,))
    result = roll_saving_throw(_snap(dex=14), "DEX", dc=10, dice_provider=provider)
    assert result.ability == "dex"


def test_saving_throw_unknown_ability_uses_10_score() -> None:
    # unknown ability defaults to score=10 → modifier=0
    provider = FixedEntropyDiceProvider((9,))  # d20=10
    result = roll_saving_throw(_snap(), "cha", dc=10, dice_provider=provider)
    assert result.ability_modifier == 0
    assert result.total == 10
