"""Opportunity attacks and reaction economy helpers."""

from __future__ import annotations

from dataclasses import dataclass

from chronicle_weaver_ai.compendium.models import MonsterEntry, WeaponEntry
from chronicle_weaver_ai.compendium.store import CompendiumStore
from chronicle_weaver_ai.dice import roll_d20_record, roll_damage_formula
from chronicle_weaver_ai.models import DiceProvider, ability_modifier
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot, apply_damage


@dataclass(frozen=True)
class OppAttackResult:
    """Recorded outcome of one opportunity attack.

    reactor_id / reactor_name — combatant that made the OA.
    mover_id   / mover_name   — combatant that triggered it by leaving melee range.
    attack_roll                — raw d20 value.
    attack_bonus               — total modifier applied to the roll.
    attack_total               — attack_roll + attack_bonus.
    target_ac                  — AC of the mover (None if unknown).
    hit                        — True if attack_total >= target_ac (or target_ac is None).
    damage_total               — damage dealt; 0 on a miss.
    damage_formula             — formula used for damage; None if no weapon.
    updated_mover              — mover snapshot after damage has been applied.
    """

    reactor_id: str
    reactor_name: str
    mover_id: str
    mover_name: str
    attack_roll: int
    attack_bonus: int
    attack_total: int
    target_ac: int | None
    hit: bool
    damage_total: int
    damage_formula: str | None
    updated_mover: CombatantSnapshot


# ── Internal helpers ──────────────────────────────────────────────────────────


def _attack_bonus_for_actor(
    reactor: CombatantSnapshot,
    weapon_entry: WeaponEntry | None,
) -> int:
    """Calculate melee attack bonus for an actor-type combatant."""
    prof = reactor.proficiency_bonus or 0
    if weapon_entry is not None:
        ability_key = weapon_entry.attack_ability or "str"
        score = reactor.abilities.get(ability_key, 10)
        mod = ability_modifier(score)
        return prof + mod + (weapon_entry.magic_bonus or 0)
    # Unarmed: proficiency + STR
    return prof + ability_modifier(reactor.abilities.get("str", 10))


# ── Core OA resolution ────────────────────────────────────────────────────────


def resolve_opportunity_attack(
    reactor: CombatantSnapshot,
    mover: CombatantSnapshot,
    compendium_store: CompendiumStore,
    dice_provider: DiceProvider,
) -> OppAttackResult:
    """Resolve one opportunity attack from *reactor* against *mover*.

    For actor reactors: searches compendium_refs for the first WeaponEntry and
    builds a STR/DEX + proficiency attack.
    For monster reactors: uses the first listed action's attack_bonus and
    damage_formula.
    Falls back to unarmed strike (1d4, proficiency + STR) when nothing is found.
    """
    weapon_entry: WeaponEntry | None = None
    damage_formula: str | None = None
    attack_bonus = 0

    if reactor.source_type == "monster":
        monster_entry: MonsterEntry | None = None
        for ref in reactor.compendium_refs:
            entry = compendium_store.get_by_id(ref)
            if isinstance(entry, MonsterEntry):
                monster_entry = entry
                break
        if monster_entry is not None and monster_entry.actions:
            action = monster_entry.actions[0]
            attack_bonus = action.attack_bonus
            damage_formula = action.damage_formula
        else:
            attack_bonus = (reactor.proficiency_bonus or 0) + ability_modifier(
                reactor.abilities.get("str", 10)
            )
            damage_formula = "1d4"
    else:
        # Actor: find first WeaponEntry in compendium_refs
        for ref in reactor.compendium_refs:
            entry = compendium_store.get_by_id(ref)
            if isinstance(entry, WeaponEntry):
                weapon_entry = entry
                damage_formula = entry.damage
                break
        attack_bonus = _attack_bonus_for_actor(reactor, weapon_entry)
        if damage_formula is None:
            damage_formula = "1d4"  # unarmed fallback

    # Roll attack
    attack_record = roll_d20_record(dice_provider)
    attack_roll = attack_record.value
    attack_total = attack_roll + attack_bonus
    target_ac = mover.armor_class

    hit = target_ac is None or attack_total >= target_ac
    damage_total = 0
    updated_mover = mover
    if hit and damage_formula is not None:
        dmg = roll_damage_formula(damage_formula, dice_provider)
        damage_total = max(0, dmg.damage_total)
        updated_mover = apply_damage(mover, damage_total)

    return OppAttackResult(
        reactor_id=reactor.combatant_id,
        reactor_name=reactor.display_name,
        mover_id=mover.combatant_id,
        mover_name=mover.display_name,
        attack_roll=attack_roll,
        attack_bonus=attack_bonus,
        attack_total=attack_total,
        target_ac=target_ac,
        hit=hit,
        damage_total=damage_total,
        damage_formula=damage_formula,
        updated_mover=updated_mover,
    )


# ── Encounter-level trigger ───────────────────────────────────────────────────


def trigger_opportunity_attacks(
    encounter: "EncounterState",  # type: ignore[name-defined]  # noqa: F821
    mover_id: str,
    compendium_store: CompendiumStore,
    dice_provider: DiceProvider,
) -> tuple["EncounterState", list[OppAttackResult]]:  # type: ignore[name-defined]  # noqa: F821
    """Fire opportunity attacks from all eligible reactors against *mover_id*.

    A combatant is eligible to make an OA when:
      1. They are currently engaged with the mover (in encounter.engaged_pairs).
      2. They have not yet spent their reaction this round.
      3. They are not in encounter.defeated_ids.

    For each eligible reactor:
      • Their reaction is marked as spent.
      • An opportunity attack is resolved and applied to the mover snapshot.

    Returns the updated encounter (with damage applied and reactions spent) and
    the ordered list of OA results.
    """
    # Late import avoids circular dependency (encounter imports rules.combatant
    # but not rules.reactions).
    from chronicle_weaver_ai.encounter import (
        get_engaged_enemies,
        has_reaction_available,
        mark_defeated,
        spend_combatant_reaction,
        update_combatant,
    )

    results: list[OppAttackResult] = []
    reactor_ids = get_engaged_enemies(encounter, mover_id)

    for reactor_id in reactor_ids:
        if reactor_id in encounter.defeated_ids:
            continue
        if not has_reaction_available(encounter, reactor_id):
            continue

        reactor = encounter.combatants[reactor_id]
        mover = encounter.combatants[mover_id]

        result = resolve_opportunity_attack(
            reactor, mover, compendium_store, dice_provider
        )
        results.append(result)

        # Spend reactor's reaction
        encounter = spend_combatant_reaction(encounter, reactor_id)

        # Apply damage to mover
        encounter = update_combatant(encounter, result.updated_mover)

        # Mark mover defeated if HP hit 0
        if (
            result.updated_mover.hit_points is not None
            and result.updated_mover.hit_points == 0
        ):
            encounter = mark_defeated(encounter, mover_id)

    return encounter, results
