"""Deterministic rules resolution from actor sheet + compendium entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from chronicle_weaver_ai.compendium import (
    FeatureEntry,
    MonsterAction,
    SpellEntry,
    WeaponEntry,
)
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot
from chronicle_weaver_ai.models import (
    Actor,
    TurnBudget,
    ability_modifier,
    can_spend_action,
    can_use_bonus_action,
    can_use_reaction,
)

ActionCost = Literal["action", "bonus_action", "reaction", "passive", "none"]


@dataclass(frozen=True)
class ResolvedWeaponAttack:
    action_kind: Literal["attack"]
    entry_id: str
    entry_name: str
    attack_ability_used: str
    attack_bonus_total: int
    damage_formula: str
    action_cost: Literal["action"]
    action_available: bool
    explanation: str


@dataclass(frozen=True)
class ResolvedSpellCast:
    action_kind: Literal["cast_spell"]
    entry_id: str
    entry_name: str
    action_cost: ActionCost
    action_available: bool
    auto_hit: bool
    attack_type: str | None
    save_ability: str | None
    effect_summary: str
    can_cast: bool
    reason: str | None
    slot_level_used: int | None


@dataclass(frozen=True)
class ResolvedFeatureUse:
    action_kind: Literal["use_feature"]
    entry_id: str
    entry_name: str
    action_cost: ActionCost
    action_available: bool
    can_use: bool
    usage_key: str | None
    remaining_uses: int | None
    effect_summary: str
    reason: str | None


def resolve_weapon_attack(
    actor: Actor,
    weapon_entry: WeaponEntry,
    turn_budget: TurnBudget | None = None,
) -> ResolvedWeaponAttack:
    """Resolve attack math from sheet + weapon entry without rolling."""

    attack_ability = (weapon_entry.attack_ability or "str").lower()
    ability_score = actor.abilities.get(attack_ability, 10)
    ability_mod = ability_modifier(ability_score)
    magic_bonus = weapon_entry.magic_bonus or 0
    intrinsic_damage_bonus = weapon_entry.damage_bonus or 0
    proficient = (
        weapon_entry.proficient_required
        and weapon_entry.id in actor.equipped_weapon_ids
    )
    proficiency_bonus = actor.proficiency_bonus if proficient else 0
    attack_bonus_total = ability_mod + proficiency_bonus + magic_bonus
    damage_formula = _build_damage_formula(
        base=weapon_entry.damage or "0",
        ability_mod=ability_mod,
        intrinsic_bonus=intrinsic_damage_bonus,
    )
    action_available = _is_action_cost_available("action", turn_budget)
    explanation = (
        f"{weapon_entry.name}: {attack_ability.upper()} mod {ability_mod:+d}, "
        f"proficiency {proficiency_bonus:+d}, magic {magic_bonus:+d}."
    )
    return ResolvedWeaponAttack(
        action_kind="attack",
        entry_id=weapon_entry.id,
        entry_name=weapon_entry.name,
        attack_ability_used=attack_ability,
        attack_bonus_total=attack_bonus_total,
        damage_formula=damage_formula,
        action_cost="action",
        action_available=action_available,
        explanation=explanation,
    )


def resolve_spell_cast(
    actor: Actor,
    spell_entry: SpellEntry,
    turn_budget: TurnBudget | None = None,
) -> ResolvedSpellCast:
    """Resolve cast availability + metadata from sheet + spell entry."""

    action_cost = _normalize_action_cost(spell_entry.action_type)
    action_available = _is_action_cost_available(action_cost, turn_budget)
    if spell_entry.id not in actor.known_spell_ids:
        return ResolvedSpellCast(
            action_kind="cast_spell",
            entry_id=spell_entry.id,
            entry_name=spell_entry.name,
            action_cost=action_cost,
            action_available=action_available,
            auto_hit=spell_entry.auto_hit,
            attack_type=spell_entry.attack_type,
            save_ability=spell_entry.save_ability,
            effect_summary=spell_entry.effect_summary,
            can_cast=False,
            reason="spell is not known by actor",
            slot_level_used=None,
        )

    slot_level_used = _choose_spell_slot_level(
        actor=actor, spell_level=spell_entry.level
    )
    if spell_entry.level > 0 and slot_level_used is None:
        return ResolvedSpellCast(
            action_kind="cast_spell",
            entry_id=spell_entry.id,
            entry_name=spell_entry.name,
            action_cost=action_cost,
            action_available=action_available,
            auto_hit=spell_entry.auto_hit,
            attack_type=spell_entry.attack_type,
            save_ability=spell_entry.save_ability,
            effect_summary=spell_entry.effect_summary,
            can_cast=False,
            reason="no spell slot available",
            slot_level_used=None,
        )

    if not action_available:
        return ResolvedSpellCast(
            action_kind="cast_spell",
            entry_id=spell_entry.id,
            entry_name=spell_entry.name,
            action_cost=action_cost,
            action_available=action_available,
            auto_hit=spell_entry.auto_hit,
            attack_type=spell_entry.attack_type,
            save_ability=spell_entry.save_ability,
            effect_summary=spell_entry.effect_summary,
            can_cast=False,
            reason=f"turn budget does not allow {action_cost}",
            slot_level_used=slot_level_used,
        )

    return ResolvedSpellCast(
        action_kind="cast_spell",
        entry_id=spell_entry.id,
        entry_name=spell_entry.name,
        action_cost=action_cost,
        action_available=action_available,
        auto_hit=spell_entry.auto_hit,
        attack_type=spell_entry.attack_type,
        save_ability=spell_entry.save_ability,
        effect_summary=spell_entry.effect_summary,
        can_cast=True,
        reason=None,
        slot_level_used=slot_level_used,
    )


def resolve_feature_use(
    actor: Actor,
    feature_entry: FeatureEntry,
    turn_budget: TurnBudget | None = None,
) -> ResolvedFeatureUse:
    """Resolve feature usage availability from sheet + feature entry."""

    action_cost = _normalize_action_cost(feature_entry.action_type)
    action_available = _is_action_cost_available(action_cost, turn_budget)
    usage_key = feature_entry.usage_key
    remaining_uses = actor.resources.get(usage_key, 0) if usage_key else None

    if feature_entry.id not in actor.feature_ids:
        return ResolvedFeatureUse(
            action_kind="use_feature",
            entry_id=feature_entry.id,
            entry_name=feature_entry.name,
            action_cost=action_cost,
            action_available=action_available,
            can_use=False,
            usage_key=usage_key,
            remaining_uses=remaining_uses,
            effect_summary=feature_entry.effect_summary,
            reason="feature is not known by actor",
        )

    if usage_key is not None and remaining_uses is not None and remaining_uses <= 0:
        return ResolvedFeatureUse(
            action_kind="use_feature",
            entry_id=feature_entry.id,
            entry_name=feature_entry.name,
            action_cost=action_cost,
            action_available=action_available,
            can_use=False,
            usage_key=usage_key,
            remaining_uses=remaining_uses,
            effect_summary=feature_entry.effect_summary,
            reason=f"resource '{usage_key}' is depleted",
        )

    if not action_available:
        return ResolvedFeatureUse(
            action_kind="use_feature",
            entry_id=feature_entry.id,
            entry_name=feature_entry.name,
            action_cost=action_cost,
            action_available=action_available,
            can_use=False,
            usage_key=usage_key,
            remaining_uses=remaining_uses,
            effect_summary=feature_entry.effect_summary,
            reason=f"turn budget does not allow {action_cost}",
        )

    return ResolvedFeatureUse(
        action_kind="use_feature",
        entry_id=feature_entry.id,
        entry_name=feature_entry.name,
        action_cost=action_cost,
        action_available=action_available,
        can_use=True,
        usage_key=usage_key,
        remaining_uses=remaining_uses,
        effect_summary=feature_entry.effect_summary,
        reason=None,
    )


@dataclass(frozen=True)
class ResolvedMonsterAttack:
    action_kind: Literal["monster_attack"]
    action_name: str
    attacker_combatant_id: str
    attacker_name: str
    attack_bonus_total: int
    damage_formula: str
    target_count: int
    target_armor_class: int | None
    explanation: str


def resolve_monster_action(
    attacker: CombatantSnapshot,
    action: MonsterAction,
    target: CombatantSnapshot | None = None,
) -> ResolvedMonsterAttack:
    """Resolve a monster's weapon-like action; no dice rolled here."""
    target_armor_class = target.armor_class if target is not None else None
    return ResolvedMonsterAttack(
        action_kind="monster_attack",
        action_name=action.name,
        attacker_combatant_id=attacker.combatant_id,
        attacker_name=attacker.display_name,
        attack_bonus_total=action.attack_bonus,
        damage_formula=action.damage_formula,
        target_count=action.target_count,
        target_armor_class=target_armor_class,
        explanation=(
            f"{attacker.display_name}: {action.name}, "
            f"attack +{action.attack_bonus}, {action.damage_formula}."
        ),
    )


def _build_damage_formula(base: str, ability_mod: int, intrinsic_bonus: int) -> str:
    parts: list[str] = [base]
    if ability_mod != 0:
        parts.append(_signed_int(ability_mod))
    if intrinsic_bonus != 0:
        parts.append(_signed_int(intrinsic_bonus))
    return " ".join(parts)


def _signed_int(value: int) -> str:
    if value >= 0:
        return f"+{value}"
    return str(value)


def _normalize_action_cost(action_type: str) -> ActionCost:
    normalized = action_type.strip().lower()
    if normalized in {"action", "bonus_action", "reaction", "passive", "none"}:
        return cast(ActionCost, normalized)
    return "action"


def _is_action_cost_available(cost: ActionCost, turn_budget: TurnBudget | None) -> bool:
    if turn_budget is None:
        return True
    if cost == "action":
        return can_spend_action(turn_budget)
    if cost == "bonus_action":
        return can_use_bonus_action(turn_budget)
    if cost == "reaction":
        return can_use_reaction(turn_budget)
    return True


def _choose_spell_slot_level(actor: Actor, spell_level: int) -> int | None:
    if spell_level <= 0:
        return 0
    candidate_levels = sorted(
        level for level, remaining in actor.spell_slots.items() if remaining > 0
    )
    for slot_level in candidate_levels:
        if slot_level >= spell_level:
            return slot_level
    return None
