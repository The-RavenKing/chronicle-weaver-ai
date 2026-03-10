"""Combatant snapshot — shared abstraction for Actor, MonsterEntry, and future types."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from chronicle_weaver_ai.compendium.models import MonsterEntry
from chronicle_weaver_ai.models import Actor, DiceProvider, ability_modifier

DurationType = Literal["rounds", "until_end_of_turn", "instant", "persistent"]

SUPPORTED_CONDITIONS: frozenset[str] = frozenset(
    {
        "prone",
        "poisoned",
        "stunned",
        "blinded",
        "frightened",
        "charmed",
        "incapacitated",
        "restrained",
        "exhausted",
    }
)

# Death save constants (D&D 5e rules)
_DEATH_SAVE_DC = 10
_DEATH_SAVE_THRESHOLD = 3


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

    source_type values:
      "actor"     — player character
      "monster"   — enemy creature
      "companion" — allied NPC acting alongside the player

    death_save_successes / death_save_failures — only meaningful when
    hit_points == 0 and source_type is "actor" or "companion".
    Three successes → stable; three failures → dead.
    """

    combatant_id: str
    display_name: str
    source_type: str  # "actor" | "monster" | "companion"
    source_id: str
    armor_class: int | None
    hit_points: int | None
    max_hit_points: int | None = None
    equipped_armor_id: str | None = None
    abilities: dict[str, int] = field(default_factory=dict)
    resources: dict[str, int] = field(default_factory=dict)
    proficiency_bonus: int | None = None
    compendium_refs: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    conditions: tuple[Condition, ...] = field(default_factory=tuple)
    death_save_successes: int = 0
    death_save_failures: int = 0
    # ID of the spell currently being concentrated on (None if not concentrating)
    concentration_spell_id: str | None = None


def combatant_from_actor(actor: Actor, source_type: str = "actor") -> CombatantSnapshot:
    """Build a CombatantSnapshot from a player-character Actor sheet.

    Pass source_type='companion' to create a companion combatant.
    """
    compendium_refs = (
        list(actor.equipped_weapon_ids)
        + list(actor.known_spell_ids)
        + list(actor.feature_ids)
        + list(actor.item_ids)
    )
    return CombatantSnapshot(
        combatant_id=actor.actor_id,
        display_name=actor.name,
        source_type=source_type,
        source_id=actor.actor_id,
        armor_class=actor.armor_class,
        hit_points=actor.hit_points,
        max_hit_points=actor.max_hit_points,
        equipped_armor_id=actor.equipped_armor_id,
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
    Also clears any death save progress if the combatant was dying.
    """
    if target.hit_points is None:
        return target
    amount = max(0, healing_amount)
    new_hp = target.hit_points + amount
    if target.max_hit_points is not None:
        new_hp = min(new_hp, target.max_hit_points)
    return replace(
        target, hit_points=new_hp, death_save_successes=0, death_save_failures=0
    )


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


# ── Death Saving Throws ───────────────────────────────────────────────────────


def is_dying(snap: CombatantSnapshot) -> bool:
    """Return True if the combatant is dying (HP=0, not a monster)."""
    return snap.hit_points == 0 and snap.source_type in ("actor", "companion")


def is_stable(snap: CombatantSnapshot) -> bool:
    """Return True if the combatant has stabilised (3 successes, HP still 0)."""
    return snap.hit_points == 0 and snap.death_save_successes >= _DEATH_SAVE_THRESHOLD


@dataclass(frozen=True)
class DeathSaveResult:
    """Outcome of a single death saving throw roll."""

    roll: int  # raw d20 result
    successes_added: int  # 1 normally, 0 on failure
    failures_added: int  # 1 normally, 2 on nat-1
    new_successes: int
    new_failures: int
    outcome: str  # "success" | "failure" | "critical_save" | "critical_fail" | "stable" | "dead"


def roll_death_save(
    snap: CombatantSnapshot,
    dice_provider: DiceProvider,
) -> tuple[CombatantSnapshot, DeathSaveResult]:
    """Roll a death saving throw for a dying combatant.

    - Natural 20: treat as 2 successes (critical save)
    - Natural 1: treat as 2 failures (critical fail)
    - Roll ≥ 10: 1 success
    - Roll < 10: 1 failure
    - 3+ successes: stable; 3+ failures: dead

    Returns (updated_snapshot, result).
    """
    from chronicle_weaver_ai.dice import roll_d20_record

    record = roll_d20_record(dice_provider)
    roll = record.value

    successes_added = 0
    failures_added = 0

    if roll == 20:
        successes_added = 2
    elif roll == 1:
        failures_added = 2
    elif roll >= _DEATH_SAVE_DC:
        successes_added = 1
    else:
        failures_added = 1

    new_successes = snap.death_save_successes + successes_added
    new_failures = snap.death_save_failures + failures_added

    if new_failures >= _DEATH_SAVE_THRESHOLD:
        outcome = "dead"
    elif new_successes >= _DEATH_SAVE_THRESHOLD:
        outcome = "stable"
    elif roll == 20:
        outcome = "critical_save"
    elif roll == 1:
        outcome = "critical_fail"
    elif successes_added:
        outcome = "success"
    else:
        outcome = "failure"

    new_snap = replace(
        snap,
        death_save_successes=new_successes,
        death_save_failures=new_failures,
    )
    return new_snap, DeathSaveResult(
        roll=roll,
        successes_added=successes_added,
        failures_added=failures_added,
        new_successes=new_successes,
        new_failures=new_failures,
        outcome=outcome,
    )


# ── Saving Throws ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SavingThrowResult:
    """Outcome of a single ability saving throw."""

    ability: str  # e.g. "dex", "con", "wis"
    dc: int
    roll: int
    ability_modifier: int
    proficiency_applied: bool
    total: int
    success: bool


def roll_saving_throw(
    snap: CombatantSnapshot,
    ability: str,
    dc: int,
    dice_provider: DiceProvider,
    proficient_saves: frozenset[str] | None = None,
) -> SavingThrowResult:
    """Roll an ability saving throw for a combatant.

    proficient_saves is the set of abilities the combatant is proficient in
    for saving throws (e.g. frozenset({"str", "con"}) for a fighter).
    If None, no proficiency is applied.
    """
    from chronicle_weaver_ai.dice import roll_d20_record

    record = roll_d20_record(dice_provider)
    roll = record.value

    score = snap.abilities.get(ability.lower(), 10)
    ab_mod = ability_modifier(score)
    prof = snap.proficiency_bonus or 0
    proficient = proficient_saves is not None and ability.lower() in proficient_saves
    total = roll + ab_mod + (prof if proficient else 0)

    return SavingThrowResult(
        ability=ability.lower(),
        dc=dc,
        roll=roll,
        ability_modifier=ab_mod,
        proficiency_applied=proficient,
        total=total,
        success=total >= dc,
    )
