"""Equipment management — equip/unequip and AC derivation.

All helpers are pure functions that return new immutable Actor instances.
No game state is mutated in place.
"""

from __future__ import annotations

from dataclasses import replace

from chronicle_weaver_ai.compendium.models import ArmorEntry
from chronicle_weaver_ai.compendium.store import CompendiumStore
from chronicle_weaver_ai.models import Actor, ability_modifier


def equip_weapon(actor: Actor, weapon_id: str) -> Actor:
    """Return a new Actor with *weapon_id* placed at the front of equipped_weapon_ids.

    If the weapon is already equipped it is moved to the front (main-hand slot).
    Other currently equipped weapons are preserved in order.
    """
    remaining = [wid for wid in actor.equipped_weapon_ids if wid != weapon_id]
    return replace(actor, equipped_weapon_ids=[weapon_id] + remaining)


def unequip_weapon(actor: Actor, weapon_id: str) -> Actor:
    """Return a new Actor with *weapon_id* removed from equipped_weapon_ids.

    If the weapon is not currently equipped the actor is returned unchanged.
    """
    if weapon_id not in actor.equipped_weapon_ids:
        return actor
    remaining = [wid for wid in actor.equipped_weapon_ids if wid != weapon_id]
    return replace(actor, equipped_weapon_ids=remaining)


def equip_armor(actor: Actor, armor_id: str) -> Actor:
    """Return a new Actor with *armor_id* set as the equipped armor."""
    return replace(actor, equipped_armor_id=armor_id)


def unequip_armor(actor: Actor) -> Actor:
    """Return a new Actor with no armor equipped."""
    return replace(actor, equipped_armor_id=None)


def derive_armor_class(actor: Actor, compendium_store: CompendiumStore) -> int | None:
    """Derive the effective AC from the actor's equipped armor.

    If no armor is equipped, falls back to *actor.armor_class* (static value).

    AC calculation by armor_type:
      "heavy"  — base only (no DEX modifier applied).
      "medium" — base + min(DEX modifier, max_dex_bonus or 2).
      "light"  — base + DEX modifier (capped by max_dex_bonus if set).
      "natural"— same as "light".

    If the equipped_armor_id is not found in the store, falls back to
    *actor.armor_class*.
    """
    if actor.equipped_armor_id is None:
        return actor.armor_class

    entry = compendium_store.get_by_id(actor.equipped_armor_id)
    if not isinstance(entry, ArmorEntry):
        return actor.armor_class

    dex_mod = ability_modifier(actor.abilities.get("dex", 10))

    if entry.armor_type == "heavy":
        return entry.armor_class_base

    cap = entry.max_dex_bonus if entry.max_dex_bonus is not None else None

    if entry.armor_type == "medium":
        # Medium armor caps DEX bonus at 2 (or max_dex_bonus if explicitly set).
        effective_cap = cap if cap is not None else 2
        return entry.armor_class_base + min(dex_mod, effective_cap)

    # light / natural: full DEX, optionally capped
    effective_dex = min(dex_mod, cap) if cap is not None else dex_mod
    return entry.armor_class_base + effective_dex
