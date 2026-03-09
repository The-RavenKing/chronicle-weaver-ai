"""Compendium data models for typed game data loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


EntryKind = Literal["weapon", "spell", "item", "feature", "monster"]


@dataclass(frozen=True)
class CompendiumEntry:
    """Shared base fields for compendium entries."""

    id: str
    name: str
    kind: str
    description: str
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    source_path: str | None = None


@dataclass(frozen=True)
class WeaponEntry(CompendiumEntry):
    """Weapon-specific compendium entry."""

    damage: str | None = None
    damage_type: str | None = None
    properties: list[str] = field(default_factory=list)
    attack_ability: str | None = None
    magic_bonus: int | None = None
    proficient_required: bool = True
    damage_bonus: int | None = None
    versatile_damage: str | None = None


@dataclass(frozen=True)
class SpellEntry(CompendiumEntry):
    """Spell-specific compendium entry."""

    level: int = 0
    school: str = ""
    casting_time: str = ""
    range: str = ""
    components: list[str] = field(default_factory=list)
    duration: str = ""
    action_type: str = "action"
    scaling_basis: str | None = None
    attack_type: str | None = None
    save_ability: str | None = None
    auto_hit: bool = False
    effect_summary: str = ""


@dataclass(frozen=True)
class ItemEntry(CompendiumEntry):
    """Item-specific compendium entry."""

    item_type: str = ""


@dataclass(frozen=True)
class FeatureEntry(CompendiumEntry):
    """Feature-specific compendium entry."""

    feature_type: str = ""
    action_type: str = "action"
    usage_key: str | None = None
    effect_summary: str = ""


@dataclass(frozen=True)
class MonsterAction:
    """A single action available to a monster (weapon-like attack for now)."""

    name: str
    attack_bonus: int
    damage_formula: str
    target_count: int = 1
    damage_type: str = ""


@dataclass(frozen=True)
class MonsterEntry(CompendiumEntry):
    """Monster-specific compendium entry."""

    size: str = ""
    creature_type: str = ""
    armor_class: int | None = None
    hit_points: int | None = None
    speed: int = 0
    abilities: dict[str, int] = field(default_factory=dict)
    actions: list[MonsterAction] = field(default_factory=list)
    challenge_rating: str | None = None


__all__ = [
    "CompendiumEntry",
    "WeaponEntry",
    "SpellEntry",
    "ItemEntry",
    "FeatureEntry",
    "MonsterAction",
    "MonsterEntry",
    "EntryKind",
]
