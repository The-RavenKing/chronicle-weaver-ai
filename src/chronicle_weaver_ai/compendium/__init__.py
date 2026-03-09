"""Compendium loading and lookup primitives."""

from __future__ import annotations

from .models import (
    CompendiumEntry,
    EntryKind,
    FeatureEntry,
    ItemEntry,
    MonsterAction,
    MonsterEntry,
    SpellEntry,
    WeaponEntry,
)
from .store import (
    CompendiumLoadError,
    CompendiumStore,
    compact_compendium_text,
    normalize_compendium_text,
    resolve_compendium_roots,
)

__all__ = [
    "CompendiumEntry",
    "EntryKind",
    "WeaponEntry",
    "SpellEntry",
    "ItemEntry",
    "FeatureEntry",
    "MonsterAction",
    "MonsterEntry",
    "CompendiumLoadError",
    "CompendiumStore",
    "normalize_compendium_text",
    "compact_compendium_text",
    "resolve_compendium_roots",
]
