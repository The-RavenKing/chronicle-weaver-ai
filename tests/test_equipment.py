"""Tests for M6 — Inventory & Equipment State.

Covers:
- ArmorEntry loading from JSON
- equip_weapon / unequip_weapon helpers
- equip_armor / unequip_armor helpers
- derive_armor_class for all armor types
- combatant_from_actor propagates equipped_armor_id
- campaign persistence round-trip with new fields
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from chronicle_weaver_ai.compendium.models import ArmorEntry
from chronicle_weaver_ai.compendium.store import CompendiumStore
from chronicle_weaver_ai.models import Actor
from chronicle_weaver_ai.rules import (
    combatant_from_actor,
    derive_armor_class,
    equip_armor,
    equip_weapon,
    unequip_armor,
    unequip_weapon,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _base_actor(**kwargs) -> Actor:
    defaults = dict(
        actor_id="hero",
        name="Hero",
        proficiency_bonus=2,
        abilities={"str": 16, "dex": 14, "con": 14, "int": 10, "wis": 10, "cha": 10},
        armor_class=10,
        hit_points=20,
        max_hit_points=28,
    )
    defaults.update(kwargs)
    return Actor(**defaults)


def _store_with_armors() -> CompendiumStore:
    chain_mail = {
        "id": "armor.chain_mail",
        "kind": "armor",
        "name": "Chain Mail",
        "description": "Heavy armor.",
        "tags": ["armor"],
        "armor_class_base": 16,
        "max_dex_bonus": 0,
        "strength_requirement": 13,
        "armor_type": "heavy",
    }
    leather = {
        "id": "armor.leather",
        "kind": "armor",
        "name": "Leather Armor",
        "description": "Light armor.",
        "tags": ["armor"],
        "armor_class_base": 11,
        "max_dex_bonus": None,
        "strength_requirement": None,
        "armor_type": "light",
    }
    scale_mail = {
        "id": "armor.scale_mail",
        "kind": "armor",
        "name": "Scale Mail",
        "description": "Medium armor.",
        "tags": ["armor"],
        "armor_class_base": 14,
        "max_dex_bonus": 2,
        "strength_requirement": None,
        "armor_type": "medium",
    }
    store = CompendiumStore()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "armor_chain_mail.json").write_text(json.dumps(chain_mail))
        (root / "armor_leather.json").write_text(json.dumps(leather))
        (root / "armor_scale_mail.json").write_text(json.dumps(scale_mail))
        store.load([root])
    return store


# ── ArmorEntry loading ────────────────────────────────────────────────────────


def test_armor_entry_loads_from_compendium():
    store = _store_with_armors()
    entry = store.get_by_id("armor.chain_mail")
    assert isinstance(entry, ArmorEntry)
    assert entry.name == "Chain Mail"
    assert entry.armor_class_base == 16
    assert entry.armor_type == "heavy"
    assert entry.max_dex_bonus == 0
    assert entry.strength_requirement == 13


def test_armor_entry_light_armor():
    store = _store_with_armors()
    entry = store.get_by_id("armor.leather")
    assert isinstance(entry, ArmorEntry)
    assert entry.armor_class_base == 11
    assert entry.armor_type == "light"
    assert entry.max_dex_bonus is None


def test_armor_entry_medium_armor():
    store = _store_with_armors()
    entry = store.get_by_id("armor.scale_mail")
    assert isinstance(entry, ArmorEntry)
    assert entry.armor_class_base == 14
    assert entry.armor_type == "medium"
    assert entry.max_dex_bonus == 2


def test_armor_entry_kind_is_armor():
    store = _store_with_armors()
    entry = store.get_by_id("armor.chain_mail")
    assert entry is not None
    assert entry.kind == "armor"


# ── equip_weapon / unequip_weapon ─────────────────────────────────────────────


def test_equip_weapon_adds_to_front():
    actor = _base_actor(equipped_weapon_ids=["w.dagger"])
    updated = equip_weapon(actor, "w.longsword")
    assert updated.equipped_weapon_ids[0] == "w.longsword"
    assert "w.dagger" in updated.equipped_weapon_ids


def test_equip_weapon_moves_existing_to_front():
    actor = _base_actor(equipped_weapon_ids=["w.dagger", "w.longsword"])
    updated = equip_weapon(actor, "w.longsword")
    assert updated.equipped_weapon_ids[0] == "w.longsword"
    assert len(updated.equipped_weapon_ids) == 2


def test_equip_weapon_when_none_equipped():
    actor = _base_actor(equipped_weapon_ids=[])
    updated = equip_weapon(actor, "w.longsword")
    assert updated.equipped_weapon_ids == ["w.longsword"]


def test_unequip_weapon_removes_it():
    actor = _base_actor(equipped_weapon_ids=["w.longsword", "w.dagger"])
    updated = unequip_weapon(actor, "w.longsword")
    assert "w.longsword" not in updated.equipped_weapon_ids
    assert "w.dagger" in updated.equipped_weapon_ids


def test_unequip_weapon_not_present_returns_unchanged():
    actor = _base_actor(equipped_weapon_ids=["w.dagger"])
    updated = unequip_weapon(actor, "w.longsword")
    assert updated.equipped_weapon_ids == ["w.dagger"]


# ── equip_armor / unequip_armor ───────────────────────────────────────────────


def test_equip_armor_sets_id():
    actor = _base_actor()
    updated = equip_armor(actor, "armor.chain_mail")
    assert updated.equipped_armor_id == "armor.chain_mail"


def test_equip_armor_replaces_existing():
    actor = _base_actor(equipped_armor_id="armor.leather")
    updated = equip_armor(actor, "armor.chain_mail")
    assert updated.equipped_armor_id == "armor.chain_mail"


def test_unequip_armor_clears_id():
    actor = _base_actor(equipped_armor_id="armor.chain_mail")
    updated = unequip_armor(actor)
    assert updated.equipped_armor_id is None


def test_unequip_armor_when_already_none_is_safe():
    actor = _base_actor()
    updated = unequip_armor(actor)
    assert updated.equipped_armor_id is None


# ── derive_armor_class ────────────────────────────────────────────────────────


def test_derive_armor_class_no_armor_returns_static_ac():
    store = _store_with_armors()
    actor = _base_actor(armor_class=16)
    assert derive_armor_class(actor, store) == 16


def test_derive_armor_class_heavy_armor_no_dex():
    """Chain mail (heavy): AC = 16, no DEX bonus."""
    store = _store_with_armors()
    # DEX modifier = +2 but heavy armor ignores it
    actor = _base_actor(equipped_armor_id="armor.chain_mail")
    assert derive_armor_class(actor, store) == 16


def test_derive_armor_class_light_armor_full_dex():
    """Leather armor (light, AC 11): AC = 11 + DEX mod."""
    store = _store_with_armors()
    # DEX score 14 → mod +2 → AC = 11 + 2 = 13
    actor = _base_actor(
        equipped_armor_id="armor.leather",
        abilities={"str": 10, "dex": 14},
    )
    assert derive_armor_class(actor, store) == 13


def test_derive_armor_class_medium_armor_caps_dex_at_2():
    """Scale mail (medium, AC 14): AC = 14 + min(DEX mod, 2)."""
    store = _store_with_armors()
    # DEX score 18 → mod +4, capped at 2 → AC = 14 + 2 = 16
    actor = _base_actor(
        equipped_armor_id="armor.scale_mail",
        abilities={"str": 10, "dex": 18},
    )
    assert derive_armor_class(actor, store) == 16


def test_derive_armor_class_medium_armor_low_dex():
    """Scale mail with low DEX: AC = 14 + DEX mod (no cap needed)."""
    store = _store_with_armors()
    # DEX score 8 → mod -1 → AC = 14 + (-1) = 13
    actor = _base_actor(
        equipped_armor_id="armor.scale_mail",
        abilities={"str": 10, "dex": 8},
    )
    assert derive_armor_class(actor, store) == 13


def test_derive_armor_class_unknown_armor_id_fallback():
    """Unknown armor ID falls back to actor.armor_class."""
    store = _store_with_armors()
    actor = _base_actor(armor_class=14, equipped_armor_id="armor.unknown")
    assert derive_armor_class(actor, store) == 14


# ── combatant_from_actor propagation ──────────────────────────────────────────


def test_combatant_from_actor_propagates_equipped_armor_id():
    actor = _base_actor(equipped_armor_id="armor.chain_mail")
    snap = combatant_from_actor(actor)
    assert snap.equipped_armor_id == "armor.chain_mail"


def test_combatant_from_actor_equipped_armor_id_none_by_default():
    actor = _base_actor()
    snap = combatant_from_actor(actor)
    assert snap.equipped_armor_id is None


# ── Campaign persistence round-trip ───────────────────────────────────────────


def test_actor_persistence_round_trip_with_equipped_armor():
    from chronicle_weaver_ai.campaign import actor_from_dict, actor_to_dict

    actor = _base_actor(
        equipped_weapon_ids=["w.longsword"],
        equipped_armor_id="armor.chain_mail",
    )
    d = actor_to_dict(actor)
    assert d["equipped_armor_id"] == "armor.chain_mail"
    restored = actor_from_dict(d)
    assert restored.equipped_armor_id == "armor.chain_mail"


def test_actor_persistence_round_trip_no_armor():
    from chronicle_weaver_ai.campaign import actor_from_dict, actor_to_dict

    actor = _base_actor()
    d = actor_to_dict(actor)
    assert d["equipped_armor_id"] is None
    restored = actor_from_dict(d)
    assert restored.equipped_armor_id is None


def test_combatant_snapshot_persistence_round_trip_with_equipped_armor():
    from chronicle_weaver_ai.campaign import (
        combatant_snapshot_from_dict,
        combatant_snapshot_to_dict,
    )

    actor = _base_actor(equipped_armor_id="armor.leather")
    snap = combatant_from_actor(actor)
    d = combatant_snapshot_to_dict(snap)
    assert d["equipped_armor_id"] == "armor.leather"
    restored = combatant_snapshot_from_dict(d)
    assert restored.equipped_armor_id == "armor.leather"


# ── Sample armor JSON files load correctly ────────────────────────────────────


def test_sample_chain_mail_loads_from_compendiums_dir():
    from pathlib import Path

    store = CompendiumStore()
    root = Path("compendiums/core_5e")
    if not root.exists():
        pytest.skip("compendiums/core_5e not found")
    store.load([root])
    entry = store.get_by_id("armor.chain_mail")
    assert isinstance(entry, ArmorEntry)
    assert entry.armor_class_base == 16
    assert entry.armor_type == "heavy"


def test_sample_leather_armor_loads_from_compendiums_dir():
    from pathlib import Path

    store = CompendiumStore()
    root = Path("compendiums/core_5e")
    if not root.exists():
        pytest.skip("compendiums/core_5e not found")
    store.load([root])
    entry = store.get_by_id("armor.leather")
    assert isinstance(entry, ArmorEntry)
    assert entry.armor_class_base == 11
    assert entry.armor_type == "light"
