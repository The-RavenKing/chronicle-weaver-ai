"""Lore Scribe output models."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from chronicle_weaver_ai.models import JSONValue


@dataclass(frozen=True)
class SessionSummary:
    """Deterministic rolling session summary."""

    text: str


@dataclass(frozen=True)
class EntityCandidate:
    """Candidate entity extracted from event logs."""

    name: str
    kind: str
    count: int


@dataclass(frozen=True)
class FactCandidate:
    """Structured fact candidate extracted from events."""

    type: str
    text: str
    ts: int


@dataclass(frozen=True)
class RelationCandidate:
    """Structured relation candidate extracted from events."""

    subject_entity_id: str
    predicate: str
    object_entity_id: str
    subject_name: str
    object_name: str
    evidence: dict[str, JSONValue]
    ts_first_seen: int
    ts_last_seen: int


@dataclass(frozen=True)
class ScribeResult:
    """Full lore-scribe extraction result."""

    summary: SessionSummary
    entities: list[EntityCandidate]
    facts: list[FactCandidate]
    relations: list[RelationCandidate] = field(default_factory=list)
