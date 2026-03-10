"""Tests for Extra Attack (multi-attack) resolver feature."""

from __future__ import annotations

from chronicle_weaver_ai.compendium import (
    CompendiumStore,
    WeaponEntry,
    resolve_compendium_roots,
)
from chronicle_weaver_ai.models import Actor
from chronicle_weaver_ai.rules.resolver import resolve_weapon_attack

_COMPENDIUM_ROOT = "compendiums"


def _store() -> CompendiumStore:
    store = CompendiumStore()
    try:
        roots = resolve_compendium_roots(_COMPENDIUM_ROOT)
        store.load(roots)
    except Exception:
        pass
    return store


def _longsword(store: CompendiumStore) -> WeaponEntry:
    entry = store.get_by_id("w.longsword")
    assert isinstance(entry, WeaponEntry)
    return entry


def _actor(feature_ids: list[str] | None = None) -> Actor:
    return Actor(
        actor_id="pc.fighter",
        name="Fighter",
        level=5,
        proficiency_bonus=3,
        abilities={"str": 18, "dex": 12, "con": 14, "int": 10, "wis": 10, "cha": 10},
        equipped_weapon_ids=["w.longsword"],
        feature_ids=feature_ids or [],
        armor_class=18,
        hit_points=44,
        max_hit_points=44,
    )


def test_default_attack_count_is_one() -> None:
    store = _store()
    resolved = resolve_weapon_attack(_actor(), _longsword(store))
    assert resolved.attack_count == 1


def test_extra_attack_feature_grants_two_attacks() -> None:
    store = _store()
    resolved = resolve_weapon_attack(
        _actor(feature_ids=["f.extra_attack"]), _longsword(store)
    )
    assert resolved.attack_count == 2


def test_extra_attack_reflected_in_explanation() -> None:
    store = _store()
    resolved = resolve_weapon_attack(
        _actor(feature_ids=["f.extra_attack"]), _longsword(store)
    )
    assert "Extra Attack" in resolved.explanation
    assert "2x" in resolved.explanation


def test_extra_attack_compendium_entry_loads() -> None:
    store = _store()
    entry = store.get_by_id("f.extra_attack")
    assert entry is not None
    assert entry.name == "Extra Attack"


def test_new_weapons_load() -> None:
    store = _store()
    for weapon_id in ("w.handaxe", "w.rapier", "w.quarterstaff", "w.light_crossbow"):
        entry = store.get_by_id(weapon_id)
        assert entry is not None, f"{weapon_id} missing from compendium"
        assert isinstance(entry, WeaponEntry)


def test_new_monsters_load() -> None:
    from chronicle_weaver_ai.compendium.models import MonsterEntry

    store = _store()
    for monster_id in ("m.zombie", "m.hobgoblin", "m.bandit", "m.kobold", "m.troll"):
        entry = store.get_by_id(monster_id)
        assert entry is not None, f"{monster_id} missing from compendium"
        assert isinstance(entry, MonsterEntry)


def test_new_spells_load() -> None:
    from chronicle_weaver_ai.compendium import SpellEntry

    store = _store()
    for spell_id in ("s.healing_word", "s.shield", "s.thunderwave"):
        entry = store.get_by_id(spell_id)
        assert entry is not None, f"{spell_id} missing from compendium"
        assert isinstance(entry, SpellEntry)


def test_total_compendium_entry_count() -> None:
    store = _store()
    assert len(store.entries) >= 29
