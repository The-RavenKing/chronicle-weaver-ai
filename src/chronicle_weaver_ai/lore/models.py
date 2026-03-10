"""Lore review queue and lorebook models."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from chronicle_weaver_ai.models import JSONValue


@dataclass(frozen=True)
class LoreEntity:
    """Canonical lore entity record."""

    entity_id: str
    name: str
    kind: str
    aliases: list[str] = field(default_factory=list)
    count: int = 1


@dataclass(frozen=True)
class LoreRelation:
    """Canonical lore relation edge."""

    relation_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    evidence: dict[str, JSONValue] = field(default_factory=dict)
    ts_first_seen: int = 0
    ts_last_seen: int = 0


@dataclass(frozen=True)
class LoreQueueItem:
    """Append-only review queue entry."""

    id: str
    kind: str
    payload: dict[str, JSONValue]
    status: str
    source_session: str
    ts: int


@dataclass(frozen=True)
class Lorebook:
    """Minimal file-based lorebook."""

    entities: list[dict[str, JSONValue]]
    facts: list[dict[str, JSONValue]]
    relations: list[dict[str, JSONValue]] = field(default_factory=list)


@dataclass(frozen=True)
class ConflictReport:
    """Describes a detected conflict between an incoming queue item and the lorebook.

    item_id        — queue item ID that caused the conflict.
    conflict_type  — 'name_mismatch' | 'kind_mismatch' | 'duplicate_name'.
    description    — human-readable explanation.
    existing_value — current value in the lorebook.
    incoming_value — value in the incoming queue item.
    """

    item_id: str
    conflict_type: str
    description: str
    existing_value: str
    incoming_value: str
