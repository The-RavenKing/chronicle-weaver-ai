"""Deterministic rules resolution utilities."""

from .combatant import (
    Condition,
    CombatantSnapshot,
    DurationType,
    SUPPORTED_CONDITIONS,
    apply_damage,
    combatant_from_actor,
    combatant_from_monster_entry,
)
from .conditions import (
    add_condition,
    remove_condition,
    render_condition,
    tick_condition_durations,
)
from .resolver import (
    ResolvedFeatureUse,
    ResolvedMonsterAttack,
    ResolvedSpellCast,
    ResolvedWeaponAttack,
    resolve_feature_use,
    resolve_monster_action,
    resolve_spell_cast,
    resolve_weapon_attack,
)

__all__ = [
    "Condition",
    "CombatantSnapshot",
    "DurationType",
    "SUPPORTED_CONDITIONS",
    "apply_damage",
    "combatant_from_actor",
    "combatant_from_monster_entry",
    "add_condition",
    "remove_condition",
    "render_condition",
    "tick_condition_durations",
    "ResolvedWeaponAttack",
    "ResolvedSpellCast",
    "ResolvedFeatureUse",
    "ResolvedMonsterAttack",
    "resolve_weapon_attack",
    "resolve_spell_cast",
    "resolve_feature_use",
    "resolve_monster_action",
]
