"""Deterministic lore review queue and lorebook persistence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from chronicle_weaver_ai.lore.models import ConflictReport, LoreQueueItem, Lorebook
from chronicle_weaver_ai.lore.normalize import (
    canonicalize_entity_record,
    player_entity,
    relation_id,
)
from chronicle_weaver_ai.models import JSONValue
from chronicle_weaver_ai.scribe.models import ScribeResult


class LoreQueueStore:
    """Append-only JSONL queue with deterministic IDs and status updates."""

    def append_items(self, path: str, items: list[LoreQueueItem]) -> tuple[int, int]:
        existing_ids = self._read_existing_ids(path)
        seen_ids = set(existing_ids)
        new_items: list[LoreQueueItem] = []
        skipped_existing = 0
        for item in items:
            if item.id in seen_ids:
                skipped_existing += 1
                continue
            seen_ids.add(item.id)
            new_items.append(item)

        with open(path, "a", encoding="utf-8") as handle:
            for item in new_items:
                handle.write(json.dumps(_queue_item_to_dict(item), ensure_ascii=False))
                handle.write("\n")
        return len(new_items), skipped_existing

    def list_items(
        self, path: str, status: str | None = "pending"
    ) -> list[LoreQueueItem]:
        items = self._load_all(path)
        if status is None:
            return items
        return [item for item in items if item.status == status]

    def mark_approved(self, path: str, item_id: str) -> LoreQueueItem:
        return self._set_status(path, item_id, "approved")

    def mark_rejected(self, path: str, item_id: str) -> LoreQueueItem:
        """Mark a queue item as rejected (will not be imported to lorebook)."""
        return self._set_status(path, item_id, "rejected")

    def _set_status(self, path: str, item_id: str, new_status: str) -> LoreQueueItem:
        items = self._load_all(path)
        updated: list[LoreQueueItem] = []
        matched: LoreQueueItem | None = None
        for item in items:
            if item.id == item_id:
                updated_item = LoreQueueItem(
                    id=item.id,
                    kind=item.kind,
                    payload=item.payload,
                    status=new_status,
                    source_session=item.source_session,
                    ts=item.ts,
                )
                updated.append(updated_item)
                matched = updated_item
            else:
                updated.append(item)
        if matched is None:
            raise ValueError(f"Queue item id not found: {item_id}")
        self._rewrite(path, updated)
        return matched

    def _load_all(self, path: str) -> list[LoreQueueItem]:
        loaded: list[LoreQueueItem] = []
        with open(path, "r", encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid queue JSON at line {index}: {exc.msg}"
                    ) from exc
                loaded.append(_queue_item_from_dict(raw, index=index))
        return loaded

    def _rewrite(self, path: str, items: list[LoreQueueItem]) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(_queue_item_to_dict(item), ensure_ascii=False))
                handle.write("\n")

    def check_conflicts(
        self, queue_path: str, lorebook: Lorebook, status: str | None = "pending"
    ) -> list[ConflictReport]:
        """Return conflict reports for queue items compared to an existing lorebook."""
        items = self.list_items(queue_path, status=status)
        return detect_conflicts(items, lorebook)

    def _read_existing_ids(self, path: str) -> set[str]:
        queue_path = Path(path)
        if not queue_path.exists():
            return set()
        ids: set[str] = set()
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = json.loads(stripped)
                except json.JSONDecodeError:
                    # Ignore malformed lines for duplicate detection only.
                    continue
                if isinstance(raw, dict):
                    raw_id = raw.get("id")
                    if isinstance(raw_id, str) and raw_id:
                        ids.add(raw_id)
        return ids


def detect_conflicts(
    items: list[LoreQueueItem],
    lorebook: Lorebook,
) -> list[ConflictReport]:
    """Detect conflicts between incoming queue items and an existing lorebook.

    Checks entity items against lorebook.entities for:
    - name_mismatch  — same entity_id but different name
    - kind_mismatch  — same entity_id but different kind
    - duplicate_name — same name maps to a different entity_id

    Returns a list of ConflictReport, one per detected conflict.
    """
    reports: list[ConflictReport] = []

    # Build lookup indices from lorebook entities (dicts)
    by_id: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for ent in lorebook.entities:
        eid = str(ent.get("entity_id", ""))
        ename = str(ent.get("name", "")).lower()
        if eid:
            by_id[eid] = ent  # type: ignore[arg-type]
        if ename:
            by_name[ename] = ent  # type: ignore[arg-type]

    for item in items:
        if item.kind != "entity":
            continue

        entity_id = str(item.payload.get("entity_id", ""))
        incoming_name = str(item.payload.get("name", ""))
        incoming_kind = str(item.payload.get("kind", ""))

        if entity_id and entity_id in by_id:
            existing = by_id[entity_id]
            existing_name = str(existing.get("name", ""))
            existing_kind = str(existing.get("kind", ""))

            if incoming_name and existing_name.lower() != incoming_name.lower():
                reports.append(
                    ConflictReport(
                        item_id=item.id,
                        conflict_type="name_mismatch",
                        description=(
                            f"Entity '{entity_id}': lorebook name '{existing_name}'"
                            f" conflicts with incoming '{incoming_name}'"
                        ),
                        existing_value=existing_name,
                        incoming_value=incoming_name,
                    )
                )
            if incoming_kind and existing_kind != incoming_kind:
                reports.append(
                    ConflictReport(
                        item_id=item.id,
                        conflict_type="kind_mismatch",
                        description=(
                            f"Entity '{entity_id}': lorebook kind '{existing_kind}'"
                            f" conflicts with incoming '{incoming_kind}'"
                        ),
                        existing_value=existing_kind,
                        incoming_value=incoming_kind,
                    )
                )
        elif incoming_name:
            name_lower = incoming_name.lower()
            if name_lower in by_name:
                existing = by_name[name_lower]
                existing_id = str(existing.get("entity_id", ""))
                if existing_id and existing_id != entity_id:
                    reports.append(
                        ConflictReport(
                            item_id=item.id,
                            conflict_type="duplicate_name",
                            description=(
                                f"Name '{incoming_name}' already used by entity"
                                f" '{existing_id}' (incoming id: '{entity_id}')"
                            ),
                            existing_value=existing_id,
                            incoming_value=entity_id,
                        )
                    )

    return reports


class LorebookStore:
    """Minimal JSON lorebook persistence with deterministic de-duplication."""

    def load(self, path: str) -> Lorebook:
        lore_path = Path(path)
        if not lore_path.exists():
            return Lorebook(entities=[], facts=[], relations=[])
        with open(path, "r", encoding="utf-8") as handle:
            try:
                raw = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid lorebook JSON: {exc.msg}") from exc
        if not isinstance(raw, dict):
            raise ValueError("lorebook root must be an object")
        entities_raw = raw.get("entities", [])
        facts_raw = raw.get("facts", [])
        relations_raw = raw.get("relations", [])
        if (
            not isinstance(entities_raw, list)
            or not isinstance(facts_raw, list)
            or not isinstance(relations_raw, list)
        ):
            raise ValueError("lorebook entities/facts/relations must be arrays")
        entities = _canonicalize_entities(
            [entry for entry in entities_raw if isinstance(entry, dict)]
        )
        facts = [entry for entry in facts_raw if isinstance(entry, dict)]
        relations = _canonicalize_relations(
            [entry for entry in relations_raw if isinstance(entry, dict)]
        )
        return Lorebook(entities=entities, facts=facts, relations=relations)

    def save(self, path: str, lorebook: Lorebook) -> None:
        payload = {
            "entities": lorebook.entities,
            "facts": lorebook.facts,
            "relations": lorebook.relations,
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)

    def add_entity(self, path: str, entity: dict[str, JSONValue]) -> None:
        lore = self.load(path)
        canonical = canonicalize_entity_record(entity)
        merged_entities = _merge_entity_list(lore.entities, canonical)
        if merged_entities != lore.entities:
            self.save(
                path,
                Lorebook(
                    entities=merged_entities,
                    facts=lore.facts,
                    relations=lore.relations,
                ),
            )

    def add_fact(self, path: str, fact: dict[str, JSONValue]) -> None:
        lore = self.load(path)
        key = (str(fact.get("type", "")), str(fact.get("text", "")))
        existing = {
            (str(item.get("type", "")), str(item.get("text", "")))
            for item in lore.facts
        }
        if key not in existing:
            lore.facts.append(fact)
            lore.facts.sort(
                key=lambda item: (str(item.get("type", "")), str(item.get("text", "")))
            )
            self.save(path, lore)

    def add_relation(self, path: str, relation: dict[str, JSONValue]) -> None:
        lore = self.load(path)
        canonical = _canonicalize_relation_record(relation)
        merged_relations = _merge_relation_list(lore.relations, canonical)
        merged_entities = _ensure_relation_endpoints(
            entities=lore.entities,
            relation_payload=relation,
            canonical_relation=canonical,
        )
        if merged_relations != lore.relations or merged_entities != lore.entities:
            self.save(
                path,
                Lorebook(
                    entities=merged_entities,
                    facts=lore.facts,
                    relations=merged_relations,
                ),
            )


def build_queue_items_from_scribe(
    result: ScribeResult,
    source_session: str,
) -> list[LoreQueueItem]:
    """Convert deterministic scribe output into queue items."""
    items: list[LoreQueueItem] = []

    for index, entity in enumerate(result.entities):
        payload = asdict(entity)
        ts = index + 1
        items.append(
            LoreQueueItem(
                id=_stable_id(kind="entity", payload=payload, ts=ts),
                kind="entity",
                payload=payload,
                status="pending",
                source_session=source_session,
                ts=ts,
            )
        )

    for fact in result.facts:
        payload = asdict(fact)
        ts = int(fact.ts)
        items.append(
            LoreQueueItem(
                id=_stable_id(kind="fact", payload=payload, ts=ts),
                kind="fact",
                payload=payload,
                status="pending",
                source_session=source_session,
                ts=ts,
            )
        )
    for relation in result.relations:
        payload = asdict(relation)
        relation_key = relation_id(
            subject_entity_id=str(payload["subject_entity_id"]),
            predicate=str(payload["predicate"]),
            object_entity_id=str(payload["object_entity_id"]),
        )
        ts = int(payload["ts_first_seen"])
        items.append(
            LoreQueueItem(
                id=f"relation:{relation_key}",
                kind="relation",
                payload=payload,
                status="pending",
                source_session=source_session,
                ts=ts,
            )
        )
    return items


def _stable_id(kind: str, payload: dict[str, JSONValue], ts: int) -> str:
    normalized = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    digest = hashlib.sha256(f"{kind}|{normalized}|{ts}".encode("utf-8")).hexdigest()
    return digest[:12]


def _queue_item_to_dict(item: LoreQueueItem) -> dict[str, JSONValue]:
    return {
        "id": item.id,
        "kind": item.kind,
        "payload": item.payload,
        "status": item.status,
        "source_session": item.source_session,
        "ts": item.ts,
    }


def _queue_item_from_dict(raw: object, index: int) -> LoreQueueItem:
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid queue item at line {index}: expected object")

    id_raw = raw.get("id")
    kind_raw = raw.get("kind")
    payload_raw = raw.get("payload")
    status_raw = raw.get("status")
    source_raw = raw.get("source_session")
    ts_raw = raw.get("ts")
    if not isinstance(id_raw, str) or not id_raw:
        raise ValueError(f"Invalid queue item at line {index}: missing id")
    if not isinstance(kind_raw, str) or kind_raw not in {"entity", "fact", "relation"}:
        raise ValueError(f"Invalid queue item at line {index}: bad kind")
    if not isinstance(payload_raw, dict):
        raise ValueError(f"Invalid queue item at line {index}: payload must be object")
    if not isinstance(status_raw, str) or status_raw not in {
        "pending",
        "approved",
        "rejected",
    }:
        raise ValueError(f"Invalid queue item at line {index}: bad status")
    if not isinstance(source_raw, str):
        raise ValueError(
            f"Invalid queue item at line {index}: source_session must be text"
        )
    if not isinstance(ts_raw, (int, float)):
        raise ValueError(f"Invalid queue item at line {index}: ts must be numeric")
    return LoreQueueItem(
        id=id_raw,
        kind=kind_raw,
        payload=payload_raw,
        status=status_raw,
        source_session=source_raw,
        ts=int(ts_raw),
    )


def _canonicalize_entities(
    entities: list[dict[str, JSONValue]],
) -> list[dict[str, JSONValue]]:
    by_id: dict[str, dict[str, JSONValue]] = {}
    for entity in entities:
        canonical = canonicalize_entity_record(entity)
        key = str(canonical["entity_id"])
        existing = by_id.get(key)
        if existing is None:
            by_id[key] = canonical
        else:
            by_id[key] = _merge_entity(existing, canonical)
    return [by_id[key] for key in sorted(by_id)]


def _merge_entity_list(
    entities: list[dict[str, JSONValue]],
    incoming: dict[str, JSONValue],
) -> list[dict[str, JSONValue]]:
    canonical_entities = _canonicalize_entities(entities)
    by_id = {
        str(entity["entity_id"]): entity
        for entity in canonical_entities
        if isinstance(entity.get("entity_id"), str)
    }
    key = str(incoming["entity_id"])
    if key in by_id:
        by_id[key] = _merge_entity(by_id[key], incoming)
    else:
        by_id[key] = incoming
    return [by_id[item_id] for item_id in sorted(by_id)]


def _merge_entity(
    left: dict[str, JSONValue],
    right: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    left_count = _to_positive_int(left.get("count"))
    right_count = _to_positive_int(right.get("count"))

    left_name = str(left.get("name", ""))
    right_name = str(right.get("name", ""))
    display_name = (
        min(name for name in [left_name, right_name] if name)
        if (left_name or right_name)
        else "unknown"
    )

    left_kind = str(left.get("kind", "unknown"))
    right_kind = str(right.get("kind", "unknown"))
    kind = min(left_kind, right_kind)

    aliases: set[str] = set()
    for candidate in [left, right]:
        raw_aliases = candidate.get("aliases", [])
        if isinstance(raw_aliases, list):
            for alias in raw_aliases:
                if isinstance(alias, str) and alias:
                    aliases.add(alias)
    for candidate_name in [left_name, right_name]:
        if candidate_name and candidate_name != display_name:
            aliases.add(candidate_name)

    return {
        "entity_id": str(left.get("entity_id") or right.get("entity_id")),
        "name": display_name,
        "kind": kind,
        "aliases": sorted(aliases),
        "count": left_count + right_count,
    }


def _to_positive_int(value: object) -> int:
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return max(1, value)
    try:
        return max(1, int(str(value)))
    except ValueError:
        return 1


def _canonicalize_relations(
    relations: list[dict[str, JSONValue]],
) -> list[dict[str, JSONValue]]:
    by_id: dict[str, dict[str, JSONValue]] = {}
    for relation in relations:
        canonical = _canonicalize_relation_record(relation)
        key = str(canonical["relation_id"])
        existing = by_id.get(key)
        if existing is None:
            by_id[key] = canonical
        else:
            by_id[key] = _merge_relation(existing, canonical)
    return [by_id[key] for key in sorted(by_id)]


def _merge_relation_list(
    relations: list[dict[str, JSONValue]],
    incoming: dict[str, JSONValue],
) -> list[dict[str, JSONValue]]:
    canonical_relations = _canonicalize_relations(relations)
    by_id = {
        str(relation["relation_id"]): relation
        for relation in canonical_relations
        if isinstance(relation.get("relation_id"), str)
    }
    key = str(incoming["relation_id"])
    if key in by_id:
        by_id[key] = _merge_relation(by_id[key], incoming)
    else:
        by_id[key] = incoming
    return [by_id[item_id] for item_id in sorted(by_id)]


def _canonicalize_relation_record(
    raw: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    subject_entity_id = str(raw.get("subject_entity_id", "")).strip()
    predicate = str(raw.get("predicate", "")).strip().lower()
    object_entity_id = str(raw.get("object_entity_id", "")).strip()
    if not subject_entity_id or not predicate or not object_entity_id:
        raise ValueError(
            "relation requires subject_entity_id, predicate, object_entity_id"
        )

    raw_relation_id = raw.get("relation_id")
    canonical_relation_id = (
        str(raw_relation_id)
        if isinstance(raw_relation_id, str) and raw_relation_id
        else relation_id(subject_entity_id, predicate, object_entity_id)
    )
    evidence_raw = raw.get("evidence", {})
    evidence: dict[str, JSONValue]
    if isinstance(evidence_raw, dict):
        evidence = {str(key): value for key, value in evidence_raw.items()}
    else:
        evidence = {}

    ts_first_seen = _to_non_negative_int(raw.get("ts_first_seen"))
    ts_last_seen = _to_non_negative_int(raw.get("ts_last_seen"))
    if ts_last_seen < ts_first_seen:
        ts_last_seen = ts_first_seen

    return {
        "relation_id": canonical_relation_id,
        "subject_entity_id": subject_entity_id,
        "predicate": predicate,
        "object_entity_id": object_entity_id,
        "evidence": evidence,
        "ts_first_seen": ts_first_seen,
        "ts_last_seen": ts_last_seen,
    }


def _merge_relation(
    left: dict[str, JSONValue],
    right: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    left_first = _to_non_negative_int(left.get("ts_first_seen"))
    right_first = _to_non_negative_int(right.get("ts_first_seen"))
    left_last = _to_non_negative_int(left.get("ts_last_seen"))
    right_last = _to_non_negative_int(right.get("ts_last_seen"))
    evidence = left.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}

    return {
        "relation_id": str(left.get("relation_id") or right.get("relation_id")),
        "subject_entity_id": str(
            left.get("subject_entity_id") or right.get("subject_entity_id")
        ),
        "predicate": str(left.get("predicate") or right.get("predicate")),
        "object_entity_id": str(
            left.get("object_entity_id") or right.get("object_entity_id")
        ),
        "evidence": evidence,
        "ts_first_seen": min(left_first, right_first),
        "ts_last_seen": max(left_last, right_last),
    }


def _ensure_relation_endpoints(
    entities: list[dict[str, JSONValue]],
    relation_payload: dict[str, JSONValue],
    canonical_relation: dict[str, JSONValue],
) -> list[dict[str, JSONValue]]:
    merged_entities = _canonicalize_entities(entities)
    player = player_entity()
    merged_entities = _merge_entity_list(merged_entities, player)

    subject_id = str(canonical_relation["subject_entity_id"])
    object_id = str(canonical_relation["object_entity_id"])

    subject_name = _relation_name_or_default(
        relation_payload=relation_payload,
        key="subject_name",
        entity_id_value=subject_id,
    )
    object_name = _relation_name_or_default(
        relation_payload=relation_payload,
        key="object_name",
        entity_id_value=object_id,
    )

    merged_entities = _merge_entity_list(
        merged_entities,
        {
            "entity_id": subject_id,
            "name": subject_name,
            "kind": "unknown",
            "aliases": [],
            "count": 1,
        },
    )
    merged_entities = _merge_entity_list(
        merged_entities,
        {
            "entity_id": object_id,
            "name": object_name,
            "kind": "unknown",
            "aliases": [],
            "count": 1,
        },
    )
    return merged_entities


def _relation_name_or_default(
    relation_payload: dict[str, JSONValue],
    key: str,
    entity_id_value: str,
) -> str:
    raw_name = relation_payload.get(key)
    if isinstance(raw_name, str):
        stripped = raw_name.strip()
        if stripped:
            return stripped.lower()
    return f"unknown:{entity_id_value}"


def _to_non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    try:
        return max(0, int(str(value)))
    except ValueError:
        return 0
