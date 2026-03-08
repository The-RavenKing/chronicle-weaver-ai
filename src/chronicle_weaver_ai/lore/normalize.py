"""Canonical lore normalization helpers."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from chronicle_weaver_ai.models import JSONValue

_SPACES = re.compile(r"\s+")


def normalize_name(text: str) -> str:
    """Normalize entity-like names for canonical identity."""
    normalized = _SPACES.sub(" ", text.strip().lower())
    if normalized.startswith("the "):
        normalized = normalized[4:].strip()
    if normalized.endswith("s") and len(normalized) > 3:
        normalized = normalized[:-1]
    return normalized


def entity_id(name: str, kind: str) -> str:
    """Deterministic canonical entity id from normalized name and kind."""
    normalized_name = normalize_name(name)
    normalized_kind = normalize_name(kind)
    digest = hashlib.sha256(
        f"{normalized_kind}:{normalized_name}".encode("utf-8")
    ).hexdigest()
    return digest[:12]


def fact_id(text: str) -> str:
    """Deterministic fact id from normalized fact text."""
    normalized = _SPACES.sub(" ", text.strip().lower())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:12]


def relation_id(subject_entity_id: str, predicate: str, object_entity_id: str) -> str:
    """Deterministic relation id from canonical edge triplet."""
    digest = hashlib.sha256(
        f"{subject_entity_id}|{predicate.strip().lower()}|{object_entity_id}".encode(
            "utf-8"
        )
    ).hexdigest()
    return digest[:12]


def player_entity() -> dict[str, JSONValue]:
    """Canonical player entity record used for graph relations."""
    return canonicalize_entity_record({"name": "player", "kind": "pc", "count": 1})


def canonicalize_entity_record(raw: dict[str, JSONValue]) -> dict[str, JSONValue]:
    """Canonicalize loose lore entity payload into stable deterministic fields."""
    raw_name = str(raw.get("name", "")).strip() or "unknown"
    raw_kind = str(raw.get("kind", "unknown")).strip() or "unknown"

    canonical_name = normalize_name(raw_name)
    canonical_kind = normalize_name(raw_kind)

    raw_id = raw.get("entity_id")
    canonical_id = (
        raw_id
        if isinstance(raw_id, str) and raw_id
        else entity_id(canonical_name, canonical_kind)
    )

    aliases = _normalize_aliases(raw.get("aliases"), canonical_name)
    raw_count = raw.get("count", 1)
    count = _to_positive_int(raw_count)

    return {
        "entity_id": canonical_id,
        "name": canonical_name,
        "kind": canonical_kind,
        "aliases": aliases,
        "count": count,
    }


def _normalize_aliases(value: Any, canonical_name: str) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized_aliases = {
        normalized
        for entry in value
        if isinstance(entry, str)
        for normalized in [normalize_name(entry)]
        if normalized and normalized != canonical_name
    }
    return sorted(normalized_aliases)


def _to_positive_int(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return max(1, value)
    try:
        return max(1, int(str(value)))
    except ValueError:
        return 1
