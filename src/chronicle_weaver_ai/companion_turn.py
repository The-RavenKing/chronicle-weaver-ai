"""Deterministic companion AI: action selection and full turn execution.

Companion turns mirror the monster_turn pipeline but target enemies (monsters)
rather than allies.  The v0 policy matches monster AI:
  — attack the first non-defeated monster using the first equipped weapon.

Companions use source_type="companion" and have the same Actor-backed stats
as player characters.  They go through the same resolver pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chronicle_weaver_ai.compendium import CompendiumStore, WeaponEntry
from chronicle_weaver_ai.dice import DiceProvider, roll_d20_record, roll_damage_formula
from chronicle_weaver_ai.encounter import (
    EncounterState,
    current_combatant,
    engage,
    get_combatant,
    mark_defeated,
    update_combatant,
)
from chronicle_weaver_ai.models import Actor
from chronicle_weaver_ai.rules.combatant import (
    CombatantSnapshot,
    apply_damage,
    is_dying,
)
from chronicle_weaver_ai.rules.resolver import resolve_weapon_attack


@dataclass(frozen=True)
class CompanionTurnResult:
    """Structured, immutable outcome of one companion turn."""

    combatant_id: str
    companion_name: str
    action_name: str
    target_id: str | None
    # Attack roll — None when no attack was attempted
    attack_roll: int | None
    attack_bonus: int | None
    attack_total: int | None
    target_ac: int | None
    hit: bool | None
    # Damage — populated only on a hit
    damage_total: int | None = None
    damage_rolls: list[int] = field(default_factory=list)
    target_hp_before: int | None = None
    target_hp_after: int | None = None
    target_defeated: bool = False
    skipped_reason: str | None = None  # non-None when the companion couldn't act


def run_companion_turn(
    encounter: EncounterState,
    companion_actor: Actor,
    compendium_store: CompendiumStore,
    dice_provider: DiceProvider,
) -> tuple[EncounterState, CompanionTurnResult]:
    """Execute a full deterministic companion turn.

    Pipeline
    --------
    1. Identify the active companion from ``encounter.turn_order``.
    2. If the companion is dying (HP=0) — skip (death saves handled by the CLI loop).
    3. Target selection: first non-defeated monster (v0 policy).
    4. Weapon selection: first equipped weapon from the Actor sheet.
    5. Roll d20 attack + damage on a hit.
    6. Update encounter state; mark monster defeated if HP reaches 0.
    7. Return (updated_encounter, CompanionTurnResult).
    """
    active_id = current_combatant(encounter.turn_order)
    companion_snap = get_combatant(encounter, active_id)

    def _skip(reason: str) -> tuple[EncounterState, CompanionTurnResult]:
        return encounter, CompanionTurnResult(
            combatant_id=active_id,
            companion_name=companion_snap.display_name,
            action_name="(none)",
            target_id=None,
            attack_roll=None,
            attack_bonus=None,
            attack_total=None,
            target_ac=None,
            hit=None,
            skipped_reason=reason,
        )

    # Dying companions roll death saves on their turn (handled by CLI loop)
    if is_dying(companion_snap):
        return _skip("dying")

    # Weapon selection
    weapon_id = (
        companion_actor.equipped_weapon_ids[0]
        if companion_actor.equipped_weapon_ids
        else None
    )
    if weapon_id is None:
        return _skip("no equipped weapon")

    weapon_entry = compendium_store.get_by_id(weapon_id)
    if not isinstance(weapon_entry, WeaponEntry):
        return _skip(f"weapon '{weapon_id}' not found")

    resolved = resolve_weapon_attack(companion_actor, weapon_entry)

    # Target selection: first living monster
    target_id: str | None = next(
        (
            cid
            for cid, snap in encounter.combatants.items()
            if snap.source_type == "monster" and cid not in encounter.defeated_ids
        ),
        None,
    )
    if target_id is None:
        return _skip("no living monsters")

    target: CombatantSnapshot = encounter.combatants[target_id]

    # Track melee engagement
    encounter = engage(encounter, active_id, target_id)

    # Attack roll
    attack_record = roll_d20_record(dice_provider)
    attack_total = attack_record.value + resolved.attack_bonus_total
    hit = target.armor_class is not None and attack_total >= target.armor_class

    damage_total: int | None = None
    damage_rolls: list[int] = []
    hp_before = target.hit_points
    hp_after = hp_before
    target_defeated = False

    if hit:
        dmg = roll_damage_formula(resolved.damage_formula, dice_provider)
        damage_total = dmg.damage_total
        damage_rolls = list(dmg.damage_rolls)
        damaged = apply_damage(target, damage_total)
        hp_after = damaged.hit_points
        encounter = update_combatant(encounter, damaged)
        if isinstance(hp_after, int) and hp_after == 0:
            target_defeated = True
            encounter = mark_defeated(encounter, target_id)

    return encounter, CompanionTurnResult(
        combatant_id=active_id,
        companion_name=companion_snap.display_name,
        action_name=weapon_entry.name,
        target_id=target_id,
        attack_roll=attack_record.value,
        attack_bonus=resolved.attack_bonus_total,
        attack_total=attack_total,
        target_ac=target.armor_class,
        hit=hit,
        damage_total=damage_total,
        damage_rolls=damage_rolls,
        target_hp_before=hp_before,
        target_hp_after=hp_after,
        target_defeated=target_defeated,
    )
