"""Deterministic compendium loaders and lookup helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Iterable, Sequence

from chronicle_weaver_ai.models import JSONValue

from .models import (
    CompendiumEntry,
    EntryKind,
    FeatureEntry,
    ItemEntry,
    MonsterEntry,
    SpellEntry,
    WeaponEntry,
)


CORE_5E_DIR = "core_5e"
CAMPAIGN_DIR = "campaign"
HOMEBREW_DIR = "homebrew"


class CompendiumLoadError(ValueError):
    """Raised when a compendium file or entry cannot be parsed."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


def normalize_compendium_text(raw_text: str) -> str:
    """Normalize free text into deterministic compendium matching form."""

    lowered = raw_text.strip().lower().replace("-", " ")
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", normalized).strip()


def compact_compendium_text(raw_text: str) -> str:
    """Normalize and remove spaces for compound-word tolerant matching."""

    return normalize_compendium_text(raw_text).replace(" ", "")


def resolve_compendium_roots(base_path: str | Path) -> list[Path]:
    """Resolve expected compendium roots from a base path.

    If a directory contains the three expected subdirectories, those are used in
    priority order: core_5e -> campaign -> homebrew.
    Otherwise, the path itself is used as a single compendium root.
    """
    root = Path(base_path)
    if not root.exists():
        raise CompendiumLoadError(str(root), "compendium root does not exist")

    candidates = [root / CORE_5E_DIR, root / CAMPAIGN_DIR, root / HOMEBREW_DIR]
    discovered = [candidate for candidate in candidates if candidate.exists()]
    if discovered:
        return discovered
    if root.is_dir():
        return [root]
    raise CompendiumLoadError(str(root), "compendium root is not a directory")


class CompendiumStore:
    """Load and query compendium entries with deterministic overrides."""

    def __init__(self) -> None:
        self._entries: dict[str, CompendiumEntry] = {}

    def load(self, roots: Sequence[str | Path]) -> dict[str, CompendiumEntry]:
        """Load entries from one or more roots and return the merged entry map."""
        entries: dict[str, CompendiumEntry] = {}
        for root in roots:
            for path in _iter_json_files(Path(root)):
                raw_entries = _load_json_entries(path)
                for raw in raw_entries:
                    entry = _parse_entry(raw, path=path)
                    entries[entry.id] = entry
        self._entries = entries
        return dict(entries)

    def get_by_id(self, entry_id: str) -> CompendiumEntry | None:
        """Return a single entry by id."""
        return self._entries.get(entry_id)

    def find_by_name(self, name: str) -> list[CompendiumEntry]:
        """Return entries whose name matches case-insensitively."""
        normalized_name = name.casefold()
        matches = [
            entry
            for entry in self._entries.values()
            if entry.name.casefold() == normalized_name
        ]
        return sorted(matches, key=lambda entry: entry.id)

    def list_by_kind(self, kind: str | EntryKind) -> list[CompendiumEntry]:
        """Return entries for one kind."""
        kind_normalized = kind.strip().lower()
        matches = [
            entry for entry in self._entries.values() if entry.kind == kind_normalized
        ]
        return sorted(matches, key=lambda entry: entry.id)

    @property
    def entries(self) -> list[CompendiumEntry]:
        """Return all loaded entries sorted by identifier."""
        return sorted(self._entries.values(), key=lambda entry: entry.id)


def _iter_json_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return ()
    if root.is_file():
        if root.suffix.lower() == ".json":
            return (root,)
        return ()
    return tuple(
        sorted((entry for entry in root.rglob("*.json") if entry.is_file()), key=str)
    )


def _load_json_entries(path: Path) -> list[dict[str, JSONValue]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CompendiumLoadError(str(path), f"cannot read JSON: {exc}") from exc

    if isinstance(raw, dict):
        return [_coerce_mapping(raw, path)]
    if isinstance(raw, list):
        values: list[dict[str, JSONValue]] = []
        for index, entry in enumerate(raw):
            if isinstance(entry, dict):
                values.append(_coerce_mapping(entry, path, index=index))
            else:
                raise CompendiumLoadError(
                    str(path),
                    f"expected object at list index {index}, got {type(entry).__name__}",
                )
        return values
    raise CompendiumLoadError(
        str(path),
        f"top-level JSON must be object or list, got {type(raw).__name__}",
    )


def _coerce_mapping(
    raw: Mapping[object, object],
    path: Path,
    index: int | None = None,
) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise CompendiumLoadError(
                _location(path, index),
                "JSON object keys must be strings",
            )
        payload[key] = _coerce_json_value(value, path=path, index=index)
    return payload


def _coerce_json_value(
    value: object,
    *,
    path: Path,
    index: int | None = None,
) -> JSONValue:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_coerce_json_value(item, path=path, index=index) for item in value]
    if isinstance(value, dict):
        return _coerce_mapping(value, path=path, index=index)
    raise CompendiumLoadError(
        _location(path, index),
        f"invalid JSON payload type '{type(value).__name__}'",
    )


def _parse_entry(raw: dict[str, JSONValue], path: Path) -> CompendiumEntry:
    entry_id = _as_str(raw.get("id"), "id", path)
    name = _as_str(raw.get("name"), "name", path)
    kind = _as_str(raw.get("kind"), "kind", path).strip().lower()
    description = _as_str(raw.get("description"), "description", path)
    tags = _as_str_list(raw.get("tags"), "tags", path)
    aliases = _as_str_list(raw.get("aliases"), "aliases", path, default=[])
    source_path = str(path)

    if kind == "weapon":
        return WeaponEntry(
            id=entry_id,
            name=name,
            kind=kind,
            description=description,
            tags=tags,
            aliases=aliases,
            source_path=source_path,
            damage=_as_optional_str(raw.get("damage"), "damage", path),
            damage_type=_as_optional_str(raw.get("damage_type"), "damage_type", path),
            properties=_as_str_list(
                raw.get("properties"), "properties", path, default=[]
            ),
            attack_ability=_as_optional_str(
                raw.get("attack_ability"), "attack_ability", path, default=None
            ),
            magic_bonus=_as_optional_int(
                raw.get("magic_bonus"), "magic_bonus", path, default=None
            ),
            proficient_required=_as_bool(
                raw.get("proficient_required"),
                "proficient_required",
                path,
                default=True,
            ),
            damage_bonus=_as_optional_int(
                raw.get("damage_bonus"), "damage_bonus", path, default=None
            ),
            versatile_damage=_as_optional_str(
                raw.get("versatile_damage"), "versatile_damage", path, default=None
            ),
        )
    if kind == "spell":
        return SpellEntry(
            id=entry_id,
            name=name,
            kind=kind,
            description=description,
            tags=tags,
            aliases=aliases,
            source_path=source_path,
            level=_as_int(raw.get("level"), "level", path, default=0),
            school=_as_str(raw.get("school"), "school", path, default=""),
            casting_time=_as_str(
                raw.get("casting_time"), "casting_time", path, default=""
            ),
            range=_as_str(raw.get("range"), "range", path, default=""),
            components=_as_str_list(
                raw.get("components"),
                "components",
                path,
                default=[],
            ),
            duration=_as_str(raw.get("duration"), "duration", path, default=""),
            action_type=_as_str(
                raw.get("action_type"), "action_type", path, default="action"
            ),
            scaling_basis=_as_optional_str(
                raw.get("scaling_basis"), "scaling_basis", path, default=None
            ),
            attack_type=_as_optional_str(
                raw.get("attack_type"), "attack_type", path, default=None
            ),
            save_ability=_as_optional_str(
                raw.get("save_ability"), "save_ability", path, default=None
            ),
            auto_hit=_as_bool(raw.get("auto_hit"), "auto_hit", path, default=False),
            effect_summary=_as_str(
                raw.get("effect_summary"),
                "effect_summary",
                path,
                default=description,
            ),
        )
    if kind == "item":
        return ItemEntry(
            id=entry_id,
            name=name,
            kind=kind,
            description=description,
            tags=tags,
            aliases=aliases,
            source_path=source_path,
            item_type=_as_str(raw.get("item_type"), "item_type", path, default=""),
        )
    if kind == "feature":
        return FeatureEntry(
            id=entry_id,
            name=name,
            kind=kind,
            description=description,
            tags=tags,
            aliases=aliases,
            source_path=source_path,
            feature_type=_as_str(
                raw.get("feature_type"),
                "feature_type",
                path,
                default="",
            ),
            action_type=_as_str(
                raw.get("action_type"), "action_type", path, default="action"
            ),
            usage_key=_as_optional_str(raw.get("usage_key"), "usage_key", path),
            effect_summary=_as_str(
                raw.get("effect_summary"),
                "effect_summary",
                path,
                default=description,
            ),
        )
    if kind == "monster":
        return MonsterEntry(
            id=entry_id,
            name=name,
            kind=kind,
            description=description,
            tags=tags,
            aliases=aliases,
            source_path=source_path,
            size=_as_str(raw.get("size"), "size", path, default=""),
            creature_type=_as_str(
                raw.get("creature_type"), "creature_type", path, default=""
            ),
            armor_class=_as_optional_int(
                raw.get("armor_class"), "armor_class", path, default=None
            ),
            hit_points=_as_optional_int(
                raw.get("hit_points"), "hit_points", path, default=None
            ),
        )
    raise CompendiumLoadError(
        str(path),
        f"invalid kind '{kind}', expected one of: weapon, spell, item, feature, monster",
    )


def _as_str_list(
    value: object,
    field_name: str,
    path: Path,
    *,
    default: list[str] | None = None,
) -> list[str]:
    if value is None:
        if default is not None:
            return list(default)
        raise CompendiumLoadError(str(path), f"missing required field '{field_name}'")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise CompendiumLoadError(
        str(path),
        f"invalid '{field_name}', expected list of strings",
    )


def _as_str(
    value: object,
    field_name: str,
    path: Path,
    *,
    default: str | None = None,
) -> str:
    if value is None:
        if default is not None:
            return default
        raise CompendiumLoadError(str(path), f"missing required field '{field_name}'")
    if isinstance(value, str):
        return value
    raise CompendiumLoadError(
        str(path),
        f"invalid '{field_name}', expected string",
    )


def _as_int(
    value: object,
    field_name: str,
    path: Path,
    *,
    default: int | None = None,
) -> int:
    if value is None:
        if default is not None:
            return default
        raise CompendiumLoadError(str(path), f"missing required field '{field_name}'")
    if isinstance(value, bool):
        raise CompendiumLoadError(str(path), f"invalid '{field_name}', expected int")
    if isinstance(value, int):
        return value
    raise CompendiumLoadError(str(path), f"invalid '{field_name}', expected int")


def _as_optional_int(
    value: object,
    field_name: str,
    path: Path,
    *,
    default: int | None = None,
) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        raise CompendiumLoadError(
            str(path), f"invalid '{field_name}', expected int|null"
        )
    if isinstance(value, int):
        return value
    raise CompendiumLoadError(str(path), f"invalid '{field_name}', expected int|null")


def _as_optional_str(
    value: object,
    field_name: str,
    path: Path,
    *,
    default: str | None = None,
) -> str | None:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    raise CompendiumLoadError(
        str(path),
        f"invalid '{field_name}', expected string|null",
    )


def _as_bool(
    value: object,
    field_name: str,
    path: Path,
    *,
    default: bool | None = None,
) -> bool:
    if value is None:
        if default is not None:
            return default
        raise CompendiumLoadError(str(path), f"missing required field '{field_name}'")
    if isinstance(value, bool):
        return value
    raise CompendiumLoadError(str(path), f"invalid '{field_name}', expected bool")


def _location(path: Path, index: int | None) -> str:
    if index is None:
        return str(path)
    return f"{path}:{index}"
