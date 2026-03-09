"""Combatant snapshot — shared abstraction for Actor, MonsterEntry, and future types."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from chronicle_weaver_ai.compendium.models import MonsterEntry
from chronicle_weaver_ai.models import Actor

DurationType = Literal["rounds", "until_end_of_turn", "instant", "persistent"]

SUPPORTED_CONDITIONS: frozenset[str] = frozenset({"prone", "poisoned", "stunned"})


@dataclass(frozen=True)
class Condition:
    """A status effect carried by a combatant.

    duration_type controls how tick_condition_durations handles this condition:
      "rounds"            — remaining_rounds decrements each tick; removed when it hits 0.
      "until_end_of_turn" — removed on the next tick.
      "instant"           — already resolved; tick leaves it unchanged.
      "persistent"        — never removed by ticking; must be removed explicitly.
    remaining_rounds is only meaningful when duration_type == "rounds".
    """

    condition_name: str  # must be in SUPPORTED_CONDITIONS for v0
    source: str  # e.g. "spell.hold_person", "attack.club", "manual"
    duration_type: DurationType
    remaining_rounds: int | None = None


@dataclass(frozen=True)
class CombatantSnapshot:
    """Immutable snapshot of one combatant for use in combat resolution.

    Works for player actors, monsters, NPCs, allies, and summons.
    All fields that are absent for a given source type default to safe empty values.
    """

    combatant_id: str
    display_name: str
    source_type: str  # "actor" | "monster"
    source_id: str
    armor_class: int | None
    hit_points: int | None
    max_hit_points: int | None = None
    abilities: dict[str, int] = field(default_factory=dict)
    resources: dict[str, int] = field(default_factory=dict)
    proficiency_bonus: int | None = None
    compendium_refs: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    conditions: tuple[Condition, ...] = field(default_factory=tuple)


def combatant_from_actor(actor: Actor) -> CombatantSnapshot:
    """Build a CombatantSnapshot from a player-character Actor sheet."""
    compendium_refs = (
        list(actor.equipped_weapon_ids)
        + list(actor.known_spell_ids)
        + list(actor.feature_ids)
        + list(actor.item_ids)
    )
    return CombatantSnapshot(
        combatant_id=actor.actor_id,
        display_name=actor.name,
        source_type="actor",
        source_id=actor.actor_id,
        armor_class=actor.armor_class,
        hit_points=actor.hit_points,
        max_hit_points=actor.max_hit_points,
        abilities=dict(actor.abilities),
        resources=dict(actor.resources),
        proficiency_bonus=actor.proficiency_bonus,
        compendium_refs=compendium_refs,
    )


def apply_damage(target: CombatantSnapshot, damage_total: int) -> CombatantSnapshot:
    """Return updated snapshot with damage applied; hit_points floors at zero.

    If hit_points is None (unknown), the snapshot is returned unchanged.
    """
    if target.hit_points is None:
        return target
    new_hp = max(0, target.hit_points - damage_total)
    return replace(target, hit_points=new_hp)


def apply_healing(
    target: CombatantSnapshot,
    healing_amount: int,
) -> CombatantSnapshot:
    """Return updated snapshot with healing applied; hit_points caps at max_hit_points.

    If hit_points is None (unknown), the snapshot is returned unchanged.
    healing_amount is floored at zero so negative values are treated as no-ops.
    """
    if target.hit_points is None:
        return target
    amount = max(0, healing_amount)
    new_hp = target.hit_points + amount
    if target.max_hit_points is not None:
        new_hp = min(new_hp, target.max_hit_points)
    return replace(target, hit_points=new_hp)


def combatant_from_monster_entry(entry: MonsterEntry) -> CombatantSnapshot:
    """Build a CombatantSnapshot from a compendium MonsterEntry."""
    return CombatantSnapshot(
        combatant_id=entry.id,
        display_name=entry.name,
        source_type="monster",
        source_id=entry.id,
        armor_class=entry.armor_class,
        hit_points=entry.hit_points,
        abilities=dict(entry.abilities),
        compendium_refs=[entry.id],
        metadata={"creature_type": entry.creature_type, "size": entry.size},
    )
