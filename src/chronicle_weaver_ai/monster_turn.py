"""Deterministic monster AI: action selection and full turn execution.

v0 policy — use the first listed action; target the first non-defeated actor.

Monster actions go through the same resolver pipeline as player actions:
  select_monster_action → resolve_monster_action → roll_d20_record
  → roll_damage_formula → apply_damage → update_combatant / mark_defeated.

All randomness is provided by the caller's DiceProvider.
No state is mutated in place; every function returns new immutable objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chronicle_weaver_ai.compendium.models import MonsterEntry
from chronicle_weaver_ai.dice import DiceProvider, roll_d20_record, roll_damage_formula
from chronicle_weaver_ai.encounter import (
    EncounterState,
    current_combatant,
    get_combatant,
    mark_defeated,
    update_combatant,
)
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot, apply_damage
from chronicle_weaver_ai.rules.resolver import (
    ResolvedMonsterAttack,
    resolve_monster_action,
)


@dataclass(frozen=True)
class MonsterTurnResult:
    """Structured, immutable outcome of one monster turn.

    All attack / damage fields are None when the monster had no valid action or
    target.  ``hit`` and damage fields are None on a miss.
    ``target_defeated`` is True only when target HP reaches 0 this turn.
    """

    combatant_id: str
    action_name: str
    target_id: str | None
    resolved_attack: ResolvedMonsterAttack | None
    # Attack roll — None when no attack was attempted
    attack_roll: int | None
    attack_total: int | None
    hit: bool | None
    # Damage — populated only on a hit
    damage_total: int | None
    damage_rolls: list[int] = field(default_factory=list)
    target_hp_before: int | None = None
    target_hp_after: int | None = None
    target_defeated: bool = False


def select_monster_action(
    monster_entry: MonsterEntry,
    attacker: CombatantSnapshot,
    target: CombatantSnapshot | None,
) -> ResolvedMonsterAttack | None:
    """Choose and resolve the first available monster action against target.

    v0 policy: always pick ``monster_entry.actions[0]`` (compendium convention
    lists melee before ranged).  Returns None when the monster has no actions
    or there is no valid target.
    """
    if not monster_entry.actions or target is None:
        return None
    action = monster_entry.actions[0]
    return resolve_monster_action(attacker, action, target)


def run_monster_turn(
    encounter: EncounterState,
    monster_entry: MonsterEntry,
    dice_provider: DiceProvider,
) -> tuple[EncounterState, MonsterTurnResult]:
    """Execute a full deterministic monster turn.

    Pipeline
    --------
    1. Identify the active monster from ``encounter.turn_order``.
    2. Target selection: first non-defeated actor (v0 policy).
    3. Select and resolve the monster action (no dice yet).
    4. Roll d20 attack via ``dice_provider``.
    5. On a hit: roll damage and apply HP changes.
    6. If target HP reaches 0: call ``mark_defeated``.
    7. Return (updated_encounter, MonsterTurnResult).

    The encounter returned is a new immutable object; the input is unchanged.
    """
    active_id = current_combatant(encounter.turn_order)
    monster_snap = get_combatant(encounter, active_id)

    # v0 target selection: first non-defeated actor in insertion order
    target_id: str | None = next(
        (
            cid
            for cid, snap in encounter.combatants.items()
            if snap.source_type == "actor" and cid not in encounter.defeated_ids
        ),
        None,
    )
    target: CombatantSnapshot | None = (
        encounter.combatants[target_id] if target_id is not None else None
    )

    resolved = select_monster_action(monster_entry, monster_snap, target)

    # No valid action or no living target — skip turn cleanly
    if resolved is None or target is None or target_id is None:
        no_action_name = (
            monster_entry.actions[0].name if monster_entry.actions else "(none)"
        )
        return encounter, MonsterTurnResult(
            combatant_id=active_id,
            action_name=no_action_name,
            target_id=None,
            resolved_attack=None,
            attack_roll=None,
            attack_total=None,
            hit=None,
            damage_total=None,
        )

    # ── Attack roll ──────────────────────────────────────────────────────────
    attack_record = roll_d20_record(dice_provider)
    attack_total = attack_record.value + resolved.attack_bonus_total
    hit = target.armor_class is not None and attack_total >= target.armor_class

    # ── Damage on hit ────────────────────────────────────────────────────────
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

    result = MonsterTurnResult(
        combatant_id=active_id,
        action_name=resolved.action_name,
        target_id=target_id,
        resolved_attack=resolved,
        attack_roll=attack_record.value,
        attack_total=attack_total,
        hit=hit,
        damage_total=damage_total,
        damage_rolls=damage_rolls,
        target_hp_before=hp_before,
        target_hp_after=hp_after,
        target_defeated=target_defeated,
    )
    return encounter, result
