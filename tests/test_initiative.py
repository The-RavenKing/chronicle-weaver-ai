"""Tests for initiative rolling and encounter turn order (Milestone: Initiative + Turn Order v0)."""

from __future__ import annotations

from chronicle_weaver_ai.dice import FixedEntropyDiceProvider, SeededDiceProvider
from chronicle_weaver_ai.encounter import (
    advance_turn,
    current_combatant,
    start_encounter,
)
from chronicle_weaver_ai.models import new_turn_budget
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot


# ── Helpers ───────────────────────────────────────────────────────────────────


def _snap(combatant_id: str, dex: int = 10) -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id=combatant_id,
        display_name=combatant_id,
        source_type="monster",
        source_id=combatant_id,
        armor_class=None,
        hit_points=None,
        abilities={"dex": dex},
    )


# ── Initiative ordering ───────────────────────────────────────────────────────


def test_initiative_ordering_is_high_to_low() -> None:
    """Combatant with higher initiative total must appear first in combatant_ids."""
    # entropy 19 → d20 = (19 % 20) + 1 = 20 (high roll, goes first)
    # entropy  0 → d20 = (0  % 20) + 1 =  1 (low roll, goes second)
    provider = FixedEntropyDiceProvider((19, 0))
    combatants = [_snap("slow", dex=10), _snap("fast", dex=10)]
    order = start_encounter("enc1", combatants, provider)

    # slow rolled first (entropy=19 → d20=20), fast rolled second (entropy=0 → d20=1)
    assert order.combatant_ids[0] == "slow"
    assert order.combatant_ids[1] == "fast"
    assert order.initiative_rolls["slow"].d20_value == 20
    assert order.initiative_rolls["fast"].d20_value == 1


def test_initiative_ordering_is_deterministic() -> None:
    """Same seed produces identical initiative order across calls."""
    combatants = [_snap("goblin_a"), _snap("goblin_b"), _snap("fighter")]
    order_a = start_encounter("enc", combatants, SeededDiceProvider(42))
    order_b = start_encounter("enc", combatants, SeededDiceProvider(42))

    assert order_a.combatant_ids == order_b.combatant_ids
    for cid in ("goblin_a", "goblin_b", "fighter"):
        assert (
            order_a.initiative_rolls[cid].total == order_b.initiative_rolls[cid].total
        )


def test_initiative_tiebreak_by_dex_modifier_desc() -> None:
    """When initiative totals are equal, higher DEX modifier wins."""
    # Both get entropy=5 → d20 = (5 % 20) + 1 = 6
    # low_dex:  dex=10 → mod=0  → total = 6 + 0 = 6
    # high_dex: dex=14 → mod=+2 → total = 6 + 2 = 8  ← must go first
    # Actually with equal d20 but different dex the totals differ — let me recalculate.
    # To get equal totals with different dex mods we need different d20 rolls that cancel.
    # low_dex  (dex=10, mod=0):  needs d20=8  → entropy = 7  (7%20+1=8),  total=8
    # high_dex (dex=14, mod=+2): needs d20=6  → entropy = 5  (5%20+1=6),  total=8
    # Both total=8; high_dex mod=+2 > low_dex mod=0 → high_dex wins
    low_dex = _snap("low_dex", dex=10)
    high_dex = _snap("high_dex", dex=14)
    provider = FixedEntropyDiceProvider(
        (7, 5)
    )  # low_dex rolls first (d20=8), high_dex second (d20=6)
    order = start_encounter("enc_tie", [low_dex, high_dex], provider)

    assert order.initiative_rolls["low_dex"].total == 8
    assert order.initiative_rolls["high_dex"].total == 8
    assert order.combatant_ids[0] == "high_dex"
    assert order.combatant_ids[1] == "low_dex"


def test_initiative_tiebreak_by_combatant_id_asc() -> None:
    """When total and DEX modifier are equal, alphabetically earlier id wins."""
    # Both get same d20 and same dex → same total and same modifier
    # entropy=5 → d20=6, dex=10 → mod=0 for both → total=6 for both
    alpha = _snap("alpha", dex=10)
    zebra = _snap("zebra", dex=10)
    provider = FixedEntropyDiceProvider((5, 5))
    order = start_encounter("enc_alpha", [zebra, alpha], provider)

    assert (
        order.initiative_rolls["alpha"].total == order.initiative_rolls["zebra"].total
    )
    assert (
        order.initiative_rolls["alpha"].dex_modifier
        == order.initiative_rolls["zebra"].dex_modifier
    )
    assert order.combatant_ids[0] == "alpha"
    assert order.combatant_ids[1] == "zebra"


# ── Turn progression ──────────────────────────────────────────────────────────


def test_advance_turn_increments_index() -> None:
    """advance_turn moves current_turn_index forward by one."""
    provider = FixedEntropyDiceProvider((1, 2, 3))
    combatants = [_snap("a"), _snap("b"), _snap("c")]
    order = start_encounter("enc", combatants, provider)

    assert order.current_turn_index == 0
    assert order.current_round == 1

    order = advance_turn(order)
    assert order.current_turn_index == 1
    assert order.current_round == 1

    order = advance_turn(order)
    assert order.current_turn_index == 2
    assert order.current_round == 1


def test_advance_turn_wraps_and_increments_round() -> None:
    """After the last combatant, index wraps to 0 and round increments."""
    provider = FixedEntropyDiceProvider((1, 2))
    combatants = [_snap("x"), _snap("y")]
    order = start_encounter("enc", combatants, provider)

    order = advance_turn(order)  # index 0 → 1
    assert order.current_turn_index == 1
    assert order.current_round == 1

    order = advance_turn(order)  # index 1 → wrap → 0, round 1 → 2
    assert order.current_turn_index == 0
    assert order.current_round == 2


def test_turn_budget_resets_on_advance() -> None:
    """After advancing turn, current_turn_budget is a fresh full budget."""
    provider = FixedEntropyDiceProvider((1, 2))
    combatants = [_snap("a"), _snap("b")]
    order = start_encounter("enc", combatants, provider)

    # Manually deplete the budget by replacing it
    import dataclasses

    exhausted = dataclasses.replace(
        order.current_turn_budget,
        action=False,
        bonus_action=False,
        reaction=False,
        movement_remaining=0,
        object_interaction=False,
        speech=False,
    )
    order = dataclasses.replace(order, current_turn_budget=exhausted)
    assert not order.current_turn_budget.action

    advanced = advance_turn(order)
    fresh = new_turn_budget()
    assert advanced.current_turn_budget.action == fresh.action
    assert advanced.current_turn_budget.bonus_action == fresh.bonus_action
    assert advanced.current_turn_budget.reaction == fresh.reaction
    assert advanced.current_turn_budget.movement_remaining == fresh.movement_remaining
    assert advanced.current_turn_budget.object_interaction == fresh.object_interaction
    assert advanced.current_turn_budget.speech == fresh.speech


def test_current_combatant_returns_active_id() -> None:
    """current_combatant returns the combatant_id at current_turn_index."""
    provider = FixedEntropyDiceProvider((19, 0))
    combatants = [_snap("fast", dex=10), _snap("slow", dex=10)]
    order = start_encounter("enc", combatants, provider)

    # fast gets entropy=19 → d20=20, slow gets entropy=0 → d20=1 → fast goes first
    assert current_combatant(order) == "fast"
    order = advance_turn(order)
    assert current_combatant(order) == "slow"
