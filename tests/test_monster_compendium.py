"""Tests for monster compendium integration (Milestone: Monster Compendium v0)."""

from __future__ import annotations

from pathlib import Path

from chronicle_weaver_ai.compendium import CompendiumStore, MonsterEntry
from chronicle_weaver_ai.rules import (
    CombatantSnapshot,
    ResolvedMonsterAttack,
    combatant_from_monster_entry,
    resolve_monster_action,
)


def _store() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


def _goblin(store: CompendiumStore) -> MonsterEntry:
    entry = store.get_by_id("m.goblin")
    assert isinstance(entry, MonsterEntry)
    return entry


# ── Compendium loading ────────────────────────────────────────────────────────


def test_monster_compendium_entry_loads() -> None:
    """Goblin entry must load with all new schema fields populated correctly."""
    store = _store()
    goblin = _goblin(store)

    assert goblin.id == "m.goblin"
    assert goblin.name == "Goblin"
    assert goblin.kind == "monster"
    assert goblin.armor_class == 13
    assert goblin.hit_points == 7
    assert goblin.speed == 30
    assert goblin.challenge_rating == "1/4"

    # Abilities
    assert goblin.abilities["str"] == 8
    assert goblin.abilities["dex"] == 14
    assert goblin.abilities["con"] == 10
    assert goblin.abilities["int"] == 10
    assert goblin.abilities["wis"] == 8
    assert goblin.abilities["cha"] == 8

    # Actions
    assert len(goblin.actions) == 2
    scimitar = goblin.actions[0]
    assert scimitar.name == "Scimitar"
    assert scimitar.attack_bonus == 4
    assert scimitar.damage_formula == "1d6 +2"
    assert scimitar.target_count == 1
    assert scimitar.damage_type == "slashing"

    shortbow = goblin.actions[1]
    assert shortbow.name == "Shortbow"
    assert shortbow.attack_bonus == 4
    assert shortbow.damage_formula == "1d6 +2"
    assert shortbow.damage_type == "piercing"


# ── Combatant snapshot ────────────────────────────────────────────────────────


def test_goblin_combatant_snapshot_works() -> None:
    """combatant_from_monster_entry must populate abilities from the rich entry."""
    store = _store()
    goblin = _goblin(store)
    snap = combatant_from_monster_entry(goblin)

    assert isinstance(snap, CombatantSnapshot)
    assert snap.combatant_id == "m.goblin"
    assert snap.display_name == "Goblin"
    assert snap.source_type == "monster"
    assert snap.source_id == "m.goblin"
    assert snap.armor_class == 13
    assert snap.hit_points == 7
    assert snap.abilities["dex"] == 14
    assert snap.abilities["str"] == 8
    assert snap.proficiency_bonus is None  # monsters don't carry proficiency_bonus


# ── Monster action resolver ───────────────────────────────────────────────────


def test_monster_action_resolves_against_player_combatant() -> None:
    """resolve_monster_action must return correct static attack metadata."""
    store = _store()
    goblin = _goblin(store)
    attacker = combatant_from_monster_entry(goblin)

    target = CombatantSnapshot(
        combatant_id="pc.fighter",
        display_name="Fighter",
        source_type="actor",
        source_id="pc.fighter",
        armor_class=16,
        hit_points=28,
    )

    scimitar = goblin.actions[0]
    resolved = resolve_monster_action(attacker, scimitar, target)

    assert isinstance(resolved, ResolvedMonsterAttack)
    assert resolved.action_kind == "monster_attack"
    assert resolved.action_name == "Scimitar"
    assert resolved.attacker_combatant_id == "m.goblin"
    assert resolved.attacker_name == "Goblin"
    assert resolved.attack_bonus_total == 4
    assert resolved.damage_formula == "1d6 +2"
    assert resolved.target_count == 1
    assert resolved.target_armor_class == 16  # sourced from target combatant


def test_monster_action_resolves_without_target() -> None:
    """resolve_monster_action must work when no target is supplied."""
    store = _store()
    goblin = _goblin(store)
    attacker = combatant_from_monster_entry(goblin)

    resolved = resolve_monster_action(
        attacker, goblin.actions[1]
    )  # Shortbow, no target

    assert resolved.action_name == "Shortbow"
    assert resolved.target_armor_class is None
    assert resolved.attack_bonus_total == 4
