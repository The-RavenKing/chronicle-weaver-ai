"""Tests for Encounter Management Milestone.

Covers: remove_from_order, end_turn (with defeat-skipping), is_encounter_over,
goblin-AI turn, and encounter termination via CLI spawn command.
"""

from __future__ import annotations

import dataclasses

from typer.testing import CliRunner

from chronicle_weaver_ai.cli import app
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.encounter import (
    EncounterState,
    create_encounter,
    current_combatant,
    end_turn,
    get_combatant,
    is_encounter_over,
    mark_defeated,
    remove_from_order,
    update_combatant,
)
from chronicle_weaver_ai.rules import apply_damage
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot


# ── Helpers ───────────────────────────────────────────────────────────────────


def _snap(
    combatant_id: str,
    source_type: str = "monster",
    dex: int = 10,
    hp: int = 10,
    ac: int = 12,
) -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id=combatant_id,
        display_name=combatant_id,
        source_type=source_type,
        source_id=combatant_id,
        armor_class=ac,
        hit_points=hp,
        abilities={"dex": dex},
    )


def _make_encounter(combatants: list[CombatantSnapshot]) -> EncounterState:
    """Create encounter with fixed equal-initiative entropy (alphabetical tie-break)."""
    n = len(combatants)
    provider = FixedEntropyDiceProvider(tuple(5 for _ in range(n)))
    return create_encounter("enc.test", combatants, provider)


# ── remove_from_order ─────────────────────────────────────────────────────────


def test_remove_from_order_removes_combatant() -> None:
    """remove_from_order must drop the id from combatant_ids."""
    combatants = [_snap("a"), _snap("b"), _snap("c")]
    encounter = _make_encounter(combatants)

    updated = remove_from_order(encounter, "b")

    assert "b" not in updated.turn_order.combatant_ids
    assert len(updated.turn_order.combatant_ids) == 2


def test_remove_from_order_unknown_id_is_noop() -> None:
    """Removing an id not in the order returns the encounter unchanged."""
    combatants = [_snap("a"), _snap("b")]
    encounter = _make_encounter(combatants)

    updated = remove_from_order(encounter, "x")

    assert updated.turn_order.combatant_ids == encounter.turn_order.combatant_ids


def test_remove_from_order_before_current_decrements_index() -> None:
    """Removing a combatant before current_turn_index shifts index back by 1."""
    # alphabetical: a < b < c  → order is [a, b, c] with equal initiative
    combatants = [_snap("a"), _snap("b"), _snap("c")]
    encounter = _make_encounter(combatants)

    # Advance so current is index 2 (c)
    encounter = dataclasses.replace(
        encounter,
        turn_order=dataclasses.replace(encounter.turn_order, current_turn_index=2),
    )
    assert encounter.turn_order.combatant_ids[2] == "c"

    # Remove "a" (index 0), before current (2)
    updated = remove_from_order(encounter, "a")

    assert updated.turn_order.current_turn_index == 1  # was 2, shifted back by 1
    assert current_combatant(updated.turn_order) == "c"


def test_remove_from_order_after_current_leaves_index_unchanged() -> None:
    """Removing a combatant after current_turn_index must not shift index."""
    combatants = [_snap("a"), _snap("b"), _snap("c")]
    encounter = _make_encounter(combatants)

    # current is at index 0 (a); remove "c" (index 2)
    assert encounter.turn_order.current_turn_index == 0
    updated = remove_from_order(encounter, "c")

    assert updated.turn_order.current_turn_index == 0
    assert current_combatant(updated.turn_order) == "a"


def test_remove_from_order_current_combatant_clamps_index() -> None:
    """Removing the last combatant in the list while it's current clamps index."""
    combatants = [_snap("a"), _snap("b"), _snap("c")]
    encounter = _make_encounter(combatants)

    # Advance to last combatant (index 2 == "c")
    encounter = dataclasses.replace(
        encounter,
        turn_order=dataclasses.replace(encounter.turn_order, current_turn_index=2),
    )

    # Remove "c" — was at index 2, new list has length 2, so index clamps to 1
    updated = remove_from_order(encounter, "c")

    assert updated.turn_order.current_turn_index == 1
    assert "c" not in updated.turn_order.combatant_ids


# ── end_turn ──────────────────────────────────────────────────────────────────


def test_end_turn_advances_to_next_alive_combatant() -> None:
    """end_turn must advance past any defeated combatants."""
    combatants = [_snap("a"), _snap("b"), _snap("c")]
    encounter = _make_encounter(combatants)

    # Defeat "b" (index 1)
    encounter = mark_defeated(encounter, "b")

    # current is "a" (index 0); after end_turn it should skip "b" and land on "c"
    updated = end_turn(encounter)

    assert current_combatant(updated.turn_order) == "c"
    assert updated.turn_order.current_round == 1  # no wrap


def test_end_turn_wraps_and_increments_round() -> None:
    """end_turn wraps to round start and increments current_round."""
    combatants = [_snap("a"), _snap("b")]
    encounter = _make_encounter(combatants)

    # Advance to last index (b)
    encounter = dataclasses.replace(
        encounter,
        turn_order=dataclasses.replace(encounter.turn_order, current_turn_index=1),
    )
    assert current_combatant(encounter.turn_order) == "b"

    updated = end_turn(encounter)

    assert current_combatant(updated.turn_order) == "a"
    assert updated.turn_order.current_round == 2


def test_end_turn_resets_turn_budget() -> None:
    """end_turn must reset current_turn_budget to a fresh full budget."""
    combatants = [_snap("a"), _snap("b")]
    encounter = _make_encounter(combatants)

    # Exhaust budget
    exhausted = dataclasses.replace(
        encounter.turn_order.current_turn_budget,
        action=False,
        bonus_action=False,
    )
    encounter = dataclasses.replace(
        encounter,
        turn_order=dataclasses.replace(
            encounter.turn_order, current_turn_budget=exhausted
        ),
    )
    assert not encounter.turn_order.current_turn_budget.action

    updated = end_turn(encounter)

    assert updated.turn_order.current_turn_budget.action is True
    assert updated.turn_order.current_turn_budget.bonus_action is True


def test_end_turn_skips_multiple_defeated_in_a_row() -> None:
    """end_turn must skip several consecutive defeated combatants."""
    combatants = [_snap("a"), _snap("b"), _snap("c"), _snap("d")]
    encounter = _make_encounter(combatants)

    # Defeat b and c (indices 1 and 2)
    encounter = mark_defeated(encounter, "b")
    encounter = mark_defeated(encounter, "c")

    # current = "a" (index 0), next alive should be "d"
    updated = end_turn(encounter)

    assert current_combatant(updated.turn_order) == "d"


def test_end_turn_wraps_skipping_defeated_increments_round() -> None:
    """end_turn must increment round when wrap crosses a defeated combatant."""
    combatants = [_snap("a"), _snap("b"), _snap("c")]
    encounter = _make_encounter(combatants)

    # Defeat "a" (index 0)
    encounter = mark_defeated(encounter, "a")

    # Move current to "c" (index 2)
    encounter = dataclasses.replace(
        encounter,
        turn_order=dataclasses.replace(encounter.turn_order, current_turn_index=2),
    )

    # end_turn from "c" must wrap, skip defeated "a", land on "b", new round
    updated = end_turn(encounter)

    assert current_combatant(updated.turn_order) == "b"
    assert updated.turn_order.current_round == 2


def test_end_turn_all_defeated_returns_unchanged() -> None:
    """end_turn must return encounter unchanged when every combatant is defeated."""
    combatants = [_snap("a"), _snap("b")]
    encounter = _make_encounter(combatants)
    encounter = mark_defeated(encounter, "a")
    encounter = mark_defeated(encounter, "b")

    updated = end_turn(encounter)

    # State unchanged
    assert (
        updated.turn_order.current_turn_index == encounter.turn_order.current_turn_index
    )
    assert updated.turn_order.current_round == encounter.turn_order.current_round


# ── is_encounter_over ─────────────────────────────────────────────────────────


def test_is_encounter_over_false_at_start() -> None:
    """Freshly created encounter must not be over."""
    combatants = [
        _snap("pc.fighter", source_type="actor"),
        _snap("m.goblin", source_type="monster"),
    ]
    encounter = _make_encounter(combatants)

    assert is_encounter_over(encounter) is False


def test_is_encounter_over_true_when_all_monsters_defeated() -> None:
    """Encounter is over when every monster is in defeated_ids."""
    combatants = [
        _snap("pc.fighter", source_type="actor"),
        _snap("m.goblin1", source_type="monster"),
        _snap("m.goblin2", source_type="monster"),
    ]
    encounter = _make_encounter(combatants)
    encounter = mark_defeated(encounter, "m.goblin1")
    encounter = mark_defeated(encounter, "m.goblin2")

    assert is_encounter_over(encounter) is True


def test_is_encounter_over_true_when_all_actors_defeated() -> None:
    """Encounter is over when every actor is in defeated_ids."""
    combatants = [
        _snap("pc.fighter", source_type="actor"),
        _snap("pc.wizard", source_type="actor"),
        _snap("m.goblin", source_type="monster"),
    ]
    encounter = _make_encounter(combatants)
    encounter = mark_defeated(encounter, "pc.fighter")
    encounter = mark_defeated(encounter, "pc.wizard")

    assert is_encounter_over(encounter) is True


def test_is_encounter_over_false_when_one_monster_survives() -> None:
    """Encounter is not over while at least one combatant on each side is alive."""
    combatants = [
        _snap("pc.fighter", source_type="actor"),
        _snap("m.goblin1", source_type="monster"),
        _snap("m.goblin2", source_type="monster"),
    ]
    encounter = _make_encounter(combatants)
    encounter = mark_defeated(encounter, "m.goblin1")

    assert is_encounter_over(encounter) is False


def test_is_encounter_over_monsters_only_is_never_over() -> None:
    """All-monster encounter is never 'over' by actor-defeat (no actors present)."""
    combatants = [
        _snap("m.a", source_type="monster"),
        _snap("m.b", source_type="monster"),
    ]
    encounter = _make_encounter(combatants)
    encounter = mark_defeated(encounter, "m.a")

    # One monster alive — neither side fully defeated
    assert is_encounter_over(encounter) is False


# ── Full defeat pipeline ───────────────────────────────────────────────────────


def test_defeat_pipeline_apply_damage_mark_remove() -> None:
    """apply_damage → mark_defeated → remove_from_order: full defeat pipeline."""
    combatants = [
        _snap("pc.fighter", source_type="actor", hp=28, ac=16),
        _snap("m.goblin", source_type="monster", hp=7, ac=13),
    ]
    encounter = _make_encounter(combatants)

    goblin = get_combatant(encounter, "m.goblin")
    damaged = apply_damage(goblin, 10)  # overkill
    encounter = update_combatant(encounter, damaged)
    encounter = mark_defeated(encounter, "m.goblin")
    encounter = remove_from_order(encounter, "m.goblin")

    assert get_combatant(encounter, "m.goblin").hit_points == 0
    assert "m.goblin" in encounter.defeated_ids
    assert "m.goblin" not in encounter.turn_order.combatant_ids
    assert is_encounter_over(encounter) is True


# ── CLI spawn command ──────────────────────────────────────────────────────────


def test_cli_spawn_goblin_runs_to_completion() -> None:
    """demo --spawn goblin must run a full encounter and print a result line."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "demo",
            "--spawn",
            "goblin",
            "--seed",
            "42",
            "--compendium-root",
            "compendiums",
        ],
    )
    assert result.exit_code == 0, result.output
    output = result.output
    # Must print the encounter header
    assert "vs" in output
    # Must print a final result: victory, defeat, or round limit
    assert any(
        word in output.lower() for word in ("victory", "defeat", "round", "defeated")
    )


def test_cli_spawn_goblin_shows_initiative_order() -> None:
    """demo --spawn goblin must print the initiative order."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "demo",
            "--spawn",
            "goblin",
            "--seed",
            "1",
            "--compendium-root",
            "compendiums",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "initiative order" in result.output.lower()


def test_cli_spawn_unknown_monster_exits_nonzero() -> None:
    """demo --spawn with an unknown monster name must exit with non-zero code."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "demo",
            "--spawn",
            "dragon_lord_of_doom",
            "--seed",
            "1",
            "--compendium-root",
            "compendiums",
        ],
    )
    assert result.exit_code != 0
