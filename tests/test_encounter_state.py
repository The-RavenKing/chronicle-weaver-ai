"""Tests for EncounterState (Milestone: Multi-Combatant Encounter State v0)."""

from __future__ import annotations

import json
from pathlib import Path

from chronicle_weaver_ai.compendium import CompendiumStore, MonsterEntry
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.encounter import (
    EncounterState,
    create_encounter,
    get_combatant,
    mark_defeated,
    update_combatant,
)
from chronicle_weaver_ai.rules import apply_damage, combatant_from_monster_entry
from chronicle_weaver_ai.rules import resolve_monster_action
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "encounter_party_vs_goblin.json"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_fixture_combatants() -> list[CombatantSnapshot]:
    raw = json.loads(FIXTURE_PATH.read_text())
    result: list[CombatantSnapshot] = []
    for c in raw["combatants"]:
        result.append(
            CombatantSnapshot(
                combatant_id=c["combatant_id"],
                display_name=c["display_name"],
                source_type=c["source_type"],
                source_id=c["source_id"],
                armor_class=c["armor_class"],
                hit_points=c["hit_points"],
                abilities=c["abilities"],
            )
        )
    return result


def _fixture_encounter() -> EncounterState:
    """Create a deterministic encounter from the party-vs-goblin fixture."""
    combatants = _load_fixture_combatants()
    provider = FixedEntropyDiceProvider((10, 5, 15))  # one d20 per combatant
    raw = json.loads(FIXTURE_PATH.read_text())
    return create_encounter(raw["encounter_id"], combatants, provider)


def _compendium_store() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


# ── Encounter state creation ──────────────────────────────────────────────────


def test_create_encounter_populates_all_combatants() -> None:
    """create_encounter must register all three combatants keyed by id."""
    encounter = _fixture_encounter()

    assert isinstance(encounter, EncounterState)
    assert encounter.encounter_id == "enc.party_vs_goblin"
    assert encounter.active is True
    assert len(encounter.combatants) == 3
    assert "pc.fighter.sample" in encounter.combatants
    assert "pc.wizard.sample" in encounter.combatants
    assert "m.goblin" in encounter.combatants


def test_create_encounter_sets_round_one_and_ordered_ids() -> None:
    """Turn order must start at round 1, index 0, with combatant_ids populated."""
    encounter = _fixture_encounter()

    assert encounter.turn_order.current_round == 1
    assert encounter.turn_order.current_turn_index == 0
    assert len(encounter.turn_order.combatant_ids) == 3
    # All combatants must appear in turn order
    assert set(encounter.turn_order.combatant_ids) == set(encounter.combatants.keys())


def test_create_encounter_defeated_ids_starts_empty() -> None:
    """No combatant should be defeated at encounter start."""
    encounter = _fixture_encounter()
    assert encounter.defeated_ids == frozenset()


# ── get_combatant ─────────────────────────────────────────────────────────────


def test_get_combatant_returns_correct_snapshot() -> None:
    """get_combatant must return the snapshot whose combatant_id matches."""
    encounter = _fixture_encounter()

    goblin = get_combatant(encounter, "m.goblin")
    assert goblin.combatant_id == "m.goblin"
    assert goblin.display_name == "Goblin"
    assert goblin.hit_points == 7
    assert goblin.armor_class == 13

    fighter = get_combatant(encounter, "pc.fighter.sample")
    assert fighter.combatant_id == "pc.fighter.sample"
    assert fighter.hit_points == 28


def test_get_combatant_raises_key_error_for_unknown_id() -> None:
    """get_combatant must raise KeyError when the id is not in the encounter."""
    import pytest

    encounter = _fixture_encounter()
    with pytest.raises(KeyError, match="not found"):
        get_combatant(encounter, "m.dragon")


# ── update_combatant ──────────────────────────────────────────────────────────


def test_update_combatant_replaces_snapshot() -> None:
    """update_combatant must return encounter with the new snapshot in place."""
    encounter = _fixture_encounter()

    goblin = get_combatant(encounter, "m.goblin")
    damaged_goblin = apply_damage(goblin, 5)
    updated = update_combatant(encounter, damaged_goblin)

    # Returned encounter has reduced HP
    assert get_combatant(updated, "m.goblin").hit_points == 2
    # Original encounter is unchanged (frozen / immutable)
    assert get_combatant(encounter, "m.goblin").hit_points == 7
    # Other combatants are untouched
    assert get_combatant(updated, "pc.fighter.sample").hit_points == 28


# ── mark_defeated ─────────────────────────────────────────────────────────────


def test_mark_defeated_adds_combatant_to_defeated_ids() -> None:
    """mark_defeated must add the combatant_id to defeated_ids."""
    encounter = _fixture_encounter()

    updated = mark_defeated(encounter, "m.goblin")

    assert "m.goblin" in updated.defeated_ids
    assert "pc.fighter.sample" not in updated.defeated_ids
    # Original is unchanged
    assert encounter.defeated_ids == frozenset()


def test_mark_defeated_is_additive() -> None:
    """Calling mark_defeated twice must accumulate both ids."""
    encounter = _fixture_encounter()

    updated = mark_defeated(encounter, "m.goblin")
    updated = mark_defeated(updated, "pc.wizard.sample")

    assert updated.defeated_ids == {"m.goblin", "pc.wizard.sample"}


# ── Resolution within encounter context ──────────────────────────────────────


def test_resolve_action_within_encounter_context() -> None:
    """Resolving a monster action should use attacker/target from encounter state."""
    store = _compendium_store()
    goblin_entry = store.get_by_id("m.goblin")
    assert isinstance(goblin_entry, MonsterEntry)

    # Build encounter from compendium snapshot + fighter
    goblin_snap = combatant_from_monster_entry(goblin_entry)
    fighter_snap = CombatantSnapshot(
        combatant_id="pc.fighter.sample",
        display_name="Sample Fighter",
        source_type="actor",
        source_id="pc.fighter.sample",
        armor_class=16,
        hit_points=28,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 10, "cha": 10},
    )
    provider = FixedEntropyDiceProvider((8, 12))
    encounter = create_encounter("enc.test", [goblin_snap, fighter_snap], provider)

    # Pull attacker and target from the encounter (the canonical source of truth)
    attacker = get_combatant(encounter, "m.goblin")
    target = get_combatant(encounter, "pc.fighter.sample")

    scimitar = goblin_entry.actions[0]
    resolved = resolve_monster_action(attacker, scimitar, target)

    assert resolved.action_kind == "monster_attack"
    assert resolved.attacker_combatant_id == "m.goblin"
    assert resolved.attacker_name == "Goblin"
    assert resolved.target_armor_class == 16  # sourced from encounter, not a constant
    assert resolved.attack_bonus_total == 4
    assert resolved.damage_formula == "1d6 +2"


def test_damage_applied_and_defeat_tracked_through_encounter() -> None:
    """apply_damage + update_combatant + mark_defeated form the full defeat pipeline."""
    encounter = _fixture_encounter()

    goblin = get_combatant(encounter, "m.goblin")
    # Overkill damage
    damaged = apply_damage(goblin, 20)
    encounter = update_combatant(encounter, damaged)
    encounter = mark_defeated(encounter, "m.goblin")

    assert get_combatant(encounter, "m.goblin").hit_points == 0
    assert "m.goblin" in encounter.defeated_ids
    assert encounter.active is True  # encounter itself still active (other combatants)
