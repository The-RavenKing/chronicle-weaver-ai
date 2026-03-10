"""Spell effect resolution — AoE targeting and concentration management.

AoE spells (target_type="area") roll saving throws for every valid target in the
encounter and deal full or half damage deterministically.

Concentration
-------------
A combatant can concentrate on at most one spell at a time.  Starting a new
concentration spell automatically drops the previous one.  Taking damage while
concentrating requires a CON saving throw (DC = max(10, damage // 2)); failure
drops concentration.

Usage
-----
from chronicle_weaver_ai.rules.spell_effects import (
    resolve_aoe_spell,
    begin_concentration,
    check_concentration,
    AoeSpellResult,
    AoeTargetResult,
)
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chronicle_weaver_ai.encounter import EncounterState

from chronicle_weaver_ai.compendium.models import SpellEntry
from chronicle_weaver_ai.dice import DiceProvider, roll_damage_formula
from chronicle_weaver_ai.models import ability_modifier
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot, apply_damage
from chronicle_weaver_ai.rules.combatant import roll_saving_throw


@dataclass(frozen=True)
class AoeTargetResult:
    """Outcome for a single target hit by an AoE spell."""

    combatant_id: str
    display_name: str
    save_roll: int
    save_total: int
    save_dc: int
    saved: bool
    damage_dealt: int
    hp_before: int
    hp_after: int
    defeated: bool


@dataclass(frozen=True)
class AoeSpellResult:
    """Aggregate result for an AoE spell cast."""

    spell_id: str
    spell_name: str
    damage_formula: str
    base_damage: int  # rolled once, applied to all
    save_ability: str
    save_dc: int
    target_results: list[AoeTargetResult] = field(default_factory=list)


def resolve_aoe_spell(
    encounter: EncounterState,
    caster_snap: CombatantSnapshot,
    spell_entry: SpellEntry,
    dice_provider: DiceProvider,
    *,
    target_enemy_type: str = "monster",
) -> tuple[EncounterState, AoeSpellResult]:
    """Roll damage once and apply DEX saves for every living enemy combatant.

    Parameters
    ----------
    encounter          — current encounter state.
    caster_snap        — snapshot of the caster (for save DC calculation).
    spell_entry        — the spell being cast (must have save_ability set).
    dice_provider      — entropy source.
    target_enemy_type  — source_type of combatants to target ("monster" for players
                         targeting enemies, or "actor" for monsters targeting players).

    Returns
    -------
    (updated_encounter, AoeSpellResult)
    """
    # Lazy import to avoid circular dependency: encounter → rules → spell_effects → encounter
    from chronicle_weaver_ai.encounter import mark_defeated, update_combatant

    # Roll damage once for the whole area
    damage_formula = _extract_damage_formula(spell_entry)
    dmg_roll = roll_damage_formula(damage_formula, dice_provider)
    base_damage = dmg_roll.damage_total

    # Calculate spell save DC: 8 + proficiency + spell_casting_ability (INT assumed)
    prof = caster_snap.proficiency_bonus or 2
    int_mod = ability_modifier(caster_snap.abilities.get("int", 10))
    save_dc = 8 + prof + int_mod
    save_ability = spell_entry.save_ability or "dex"

    # Determine proficient saves for caster (none — this is the targets' save)
    target_results: list[AoeTargetResult] = []

    for combatant_id, snap in list(encounter.combatants.items()):
        if snap.source_type != target_enemy_type:
            continue
        if combatant_id in encounter.defeated_ids:
            continue
        if snap.hit_points is None or snap.hit_points <= 0:
            continue

        # Roll saving throw for this target
        save_result = roll_saving_throw(
            snap=snap,
            ability=save_ability,
            dc=save_dc,
            dice_provider=dice_provider,
        )
        saved = save_result.success

        # Half on save, full on fail
        damage_dealt = base_damage // 2 if saved else base_damage

        hp_before = snap.hit_points
        damaged = apply_damage(snap, damage_dealt)
        encounter = update_combatant(encounter, damaged)

        defeated = False
        if damaged.hit_points == 0 and snap.source_type == "monster":
            encounter = mark_defeated(encounter, combatant_id)
            defeated = True

        target_results.append(
            AoeTargetResult(
                combatant_id=combatant_id,
                display_name=snap.display_name,
                save_roll=save_result.roll,
                save_total=save_result.total,
                save_dc=save_dc,
                saved=saved,
                damage_dealt=damage_dealt,
                hp_before=hp_before,
                hp_after=damaged.hit_points or 0,
                defeated=defeated,
            )
        )

    result = AoeSpellResult(
        spell_id=spell_entry.id,
        spell_name=spell_entry.name,
        damage_formula=damage_formula,
        base_damage=base_damage,
        save_ability=save_ability,
        save_dc=save_dc,
        target_results=target_results,
    )
    return encounter, result


def begin_concentration(
    snap: CombatantSnapshot,
    spell_id: str,
) -> CombatantSnapshot:
    """Set *snap* as concentrating on *spell_id*, dropping any previous concentration."""
    return replace(snap, concentration_spell_id=spell_id)


def drop_concentration(snap: CombatantSnapshot) -> CombatantSnapshot:
    """Remove concentration from *snap*."""
    return replace(snap, concentration_spell_id=None)


def check_concentration(
    snap: CombatantSnapshot,
    damage_taken: int,
    dice_provider: DiceProvider,
) -> tuple[CombatantSnapshot, bool]:
    """Check whether *snap* maintains concentration after taking *damage_taken*.

    DC = max(10, damage_taken // 2).  On failure, concentration is dropped.

    Returns (updated_snap, maintained).
    """
    if snap.concentration_spell_id is None:
        return snap, True  # Not concentrating — always succeeds

    dc = max(10, damage_taken // 2)
    result = roll_saving_throw(
        snap=snap,
        ability="con",
        dc=dc,
        dice_provider=dice_provider,
        proficient_saves=None,
    )
    if result.success:
        return snap, True
    return drop_concentration(snap), False


def _extract_damage_formula(spell_entry: SpellEntry) -> str:
    """Extract a usable damage formula from a spell's effect_summary or id."""
    # Try to extract a dice expression from effect_summary (e.g. "8d6 fire damage")
    import re

    match = re.search(r"\d+d\d+(?:[+-]\d+)?", spell_entry.effect_summary)
    if match:
        return match.group(0)
    # Fallback: derive from spell level (1d6 per level)
    dice_count = max(1, spell_entry.level)
    return f"{dice_count}d6"


__all__ = [
    "AoeSpellResult",
    "AoeTargetResult",
    "resolve_aoe_spell",
    "begin_concentration",
    "drop_concentration",
    "check_concentration",
]
