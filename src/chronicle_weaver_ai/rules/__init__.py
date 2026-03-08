"""Deterministic rules resolution utilities."""

from .resolver import (
    ResolvedFeatureUse,
    ResolvedSpellCast,
    ResolvedWeaponAttack,
    resolve_feature_use,
    resolve_spell_cast,
    resolve_weapon_attack,
)

__all__ = [
    "ResolvedWeaponAttack",
    "ResolvedSpellCast",
    "ResolvedFeatureUse",
    "resolve_weapon_attack",
    "resolve_spell_cast",
    "resolve_feature_use",
]
