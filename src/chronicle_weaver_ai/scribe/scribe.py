"""Deterministic Lore Scribe v0 extraction pipeline."""

from __future__ import annotations

import re
from collections import Counter

from chronicle_weaver_ai.lore.normalize import entity_id, normalize_name
from chronicle_weaver_ai.models import Event
from chronicle_weaver_ai.scribe.models import (
    EntityCandidate,
    FactCandidate,
    RelationCandidate,
    ScribeResult,
    SessionSummary,
)

_CAPITALIZED_WORD = re.compile(r"\b[A-Z][a-zA-Z']*\b")
_NOUN_KEYWORDS = {"goblin", "innkeeper", "baron", "amulet", "forest", "tavern"}
_PLAYER_NAME = "player"
_PLAYER_KIND = "pc"
_PLAYER_ENTITY_ID = entity_id(_PLAYER_NAME, _PLAYER_KIND)


def run_lore_scribe(events: list[Event], summary_fact_limit: int = 5) -> ScribeResult:
    """Produce deterministic summary, entity candidates, and fact candidates."""
    entity_counts: Counter[str] = Counter()
    facts: list[FactCandidate] = []
    relations_by_key: dict[tuple[str, str, str], RelationCandidate] = {}
    last_input_entities: list[str] = []

    for index, event in enumerate(events):
        ts = _event_ts(event, index)
        if event.event_type == "player_input":
            text = str(event.payload.get("text", ""))
            extracted_entities = _extract_entities_from_text(text)
            last_input_entities = list(extracted_entities)
            for name in extracted_entities:
                entity_counts[name] += 1
        elif event.event_type == "intent_resolved":
            intent = str(event.payload.get("intent", "unknown"))
            facts.append(
                FactCandidate(type="intent", text=f"Player intent: {intent}", ts=ts)
            )
            if intent == "attack":
                target_name = _pick_relation_target(last_input_entities)
                if target_name is not None:
                    target_entity_id = entity_id(target_name, "unknown")
                    key = (_PLAYER_ENTITY_ID, "attacked", target_entity_id)
                    existing = relations_by_key.get(key)
                    if existing is None:
                        relations_by_key[key] = RelationCandidate(
                            subject_entity_id=_PLAYER_ENTITY_ID,
                            predicate="attacked",
                            object_entity_id=target_entity_id,
                            subject_name=_PLAYER_NAME,
                            object_name=target_name,
                            evidence={
                                "event_type": event.event_type,
                                "event_ts": ts,
                            },
                            ts_first_seen=ts,
                            ts_last_seen=ts,
                        )
                    else:
                        relations_by_key[key] = RelationCandidate(
                            subject_entity_id=existing.subject_entity_id,
                            predicate=existing.predicate,
                            object_entity_id=existing.object_entity_id,
                            subject_name=existing.subject_name,
                            object_name=existing.object_name,
                            evidence=existing.evidence,
                            ts_first_seen=existing.ts_first_seen,
                            ts_last_seen=max(existing.ts_last_seen, ts),
                        )
        elif event.event_type == "mode_transition":
            from_mode = str(event.payload.get("from_mode", "unknown"))
            to_mode = str(event.payload.get("to_mode", "unknown"))
            facts.append(
                FactCandidate(
                    type="mode_transition",
                    text=f"Mode changed {from_mode} -> {to_mode}",
                    ts=ts,
                )
            )
        elif event.event_type == "dice_roll":
            value = str(event.payload.get("value", "unknown"))
            facts.append(FactCandidate(type="dice", text=f"Rolled d20={value}", ts=ts))
        elif event.event_type == "entropy_prefetched":
            source = str(event.payload.get("source", "unknown"))
            facts.append(
                FactCandidate(
                    type="entropy",
                    text=f"Entropy source: {source}",
                    ts=ts,
                )
            )

    entities = [
        EntityCandidate(name=name, kind="unknown", count=count)
        for name, count in sorted(
            entity_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    relations = sorted(
        relations_by_key.values(),
        key=lambda relation: (
            relation.subject_entity_id,
            relation.predicate,
            relation.object_entity_id,
        ),
    )
    summary = _build_summary(facts=facts, limit=summary_fact_limit)
    return ScribeResult(
        summary=summary,
        entities=entities,
        facts=facts,
        relations=relations,
    )


def _extract_entities_from_text(text: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    for match in _CAPITALIZED_WORD.findall(text):
        normalized = normalize_name(match)
        if normalized not in seen:
            names.append(normalized)
            seen.add(normalized)

    lower_text = text.lower()
    for keyword in sorted(_NOUN_KEYWORDS):
        if re.search(rf"\b{re.escape(keyword)}s?\b", lower_text):
            normalized = normalize_name(keyword)
            if normalized not in seen:
                names.append(normalized)
                seen.add(normalized)
    return names


def _build_summary(facts: list[FactCandidate], limit: int) -> SessionSummary:
    if not facts:
        return SessionSummary(text="Recent summary: no notable facts.")
    snippet = "; ".join(fact.text for fact in facts[-limit:])
    return SessionSummary(text=f"Recent summary: {snippet}")


def _event_ts(event: Event, fallback: int) -> int:
    raw = event.timestamp
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(float(raw))
        except ValueError:
            return fallback
    return fallback


def _pick_relation_target(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    return sorted(candidates)[0]
