"""Deterministic rules resolver behavior for actor + compendium inputs."""

from __future__ import annotations

from pathlib import Path

from chronicle_weaver_ai.compendium import (
    CompendiumStore,
    FeatureEntry,
    SpellEntry,
    WeaponEntry,
)
from chronicle_weaver_ai.models import Actor, TurnBudget
from chronicle_weaver_ai.rules.resolver import (
    resolve_feature_use,
    resolve_spell_cast,
    resolve_weapon_attack,
)


def _core_store() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


def _longsword(store: CompendiumStore) -> WeaponEntry:
    entry = store.get_by_id("w.longsword")
    assert isinstance(entry, WeaponEntry)
    return entry


def _magic_missile(store: CompendiumStore) -> SpellEntry:
    entry = store.get_by_id("s.magic_missile")
    assert isinstance(entry, SpellEntry)
    return entry


def _second_wind(store: CompendiumStore) -> FeatureEntry:
    entry = store.get_by_id("f.second_wind")
    assert isinstance(entry, FeatureEntry)
    return entry


def test_resolve_longsword_attack_bonus_total() -> None:
    store = _core_store()
    fighter = Actor(
        actor_id="pc.fighter",
        name="Fighter",
        class_name="fighter",
        level=3,
        proficiency_bonus=2,
        abilities={
            "str": 16,
            "dex": 12,
            "con": 14,
            "int": 8,
            "wis": 10,
            "cha": 10,
        },
        equipped_weapon_ids=["w.longsword"],
        feature_ids=["f.second_wind"],
        resources={"second_wind_uses": 1},
    )

    result = resolve_weapon_attack(fighter, _longsword(store))

    assert result.action_kind == "attack"
    assert result.entry_id == "w.longsword"
    assert result.attack_ability_used == "str"
    assert result.attack_bonus_total == 6
    assert result.action_cost == "action"
    assert result.action_available is True


def test_resolve_longsword_damage_formula_includes_ability_and_intrinsic_bonus() -> (
    None
):
    store = _core_store()
    fighter = Actor(
        actor_id="pc.fighter",
        name="Fighter",
        proficiency_bonus=2,
        abilities={
            "str": 16,
            "dex": 10,
            "con": 10,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        equipped_weapon_ids=["w.longsword"],
    )

    result = resolve_weapon_attack(fighter, _longsword(store))

    assert result.damage_formula == "1d8 +3 +1"


def test_resolve_magic_missile_castable_when_known_and_slot_available() -> None:
    store = _core_store()
    wizard = Actor(
        actor_id="pc.wizard",
        name="Wizard",
        class_name="wizard",
        level=3,
        proficiency_bonus=2,
        abilities={
            "str": 8,
            "dex": 14,
            "con": 12,
            "int": 16,
            "wis": 12,
            "cha": 10,
        },
        known_spell_ids=["s.magic_missile"],
        spell_slots={1: 2},
    )

    result = resolve_spell_cast(wizard, _magic_missile(store))

    assert result.action_kind == "cast_spell"
    assert result.action_cost == "action"
    assert result.auto_hit is True
    assert result.can_cast is True
    assert result.reason is None
    assert result.slot_level_used == 1


def test_resolve_second_wind_usage_from_resources() -> None:
    store = _core_store()
    feature = _second_wind(store)
    fighter_ready = Actor(
        actor_id="pc.fighter.ready",
        name="Fighter Ready",
        feature_ids=["f.second_wind"],
        resources={"second_wind_uses": 1},
    )
    fighter_empty = Actor(
        actor_id="pc.fighter.empty",
        name="Fighter Empty",
        feature_ids=["f.second_wind"],
        resources={"second_wind_uses": 0},
    )

    ready = resolve_feature_use(fighter_ready, feature)
    empty = resolve_feature_use(fighter_empty, feature)

    assert ready.action_cost == "bonus_action"
    assert ready.can_use is True
    assert ready.remaining_uses == 1
    assert empty.action_cost == "bonus_action"
    assert empty.can_use is False
    assert empty.remaining_uses == 0
    assert empty.reason == "resource 'second_wind_uses' is depleted"


def test_resolver_respects_turn_budget_for_action_cost() -> None:
    store = _core_store()
    wizard = Actor(
        actor_id="pc.wizard",
        name="Wizard",
        known_spell_ids=["s.magic_missile"],
        spell_slots={1: 1},
    )

    budget = TurnBudget(action=False, bonus_action=True, reaction=True)
    result = resolve_spell_cast(wizard, _magic_missile(store), turn_budget=budget)

    assert result.action_available is False
    assert result.can_cast is False
    assert result.reason == "turn budget does not allow action"
