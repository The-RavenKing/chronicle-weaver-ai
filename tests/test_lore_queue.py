"""Tests for lore queue and lorebook persistence."""

import json

from chronicle_weaver_ai.lore.store import (
    LoreQueueStore,
    LorebookStore,
    build_queue_items_from_scribe,
)
from chronicle_weaver_ai.lore.normalize import entity_id, player_entity
from chronicle_weaver_ai.scribe.models import (
    EntityCandidate,
    FactCandidate,
    RelationCandidate,
    ScribeResult,
    SessionSummary,
)


def _scribe_result() -> ScribeResult:
    return ScribeResult(
        summary=SessionSummary(text="Recent summary: Player intent: attack"),
        entities=[EntityCandidate(name="goblin", kind="unknown", count=2)],
        facts=[FactCandidate(type="intent", text="Player intent: attack", ts=2)],
    )


def test_queue_ids_are_deterministic_for_same_input() -> None:
    result = _scribe_result()
    first = build_queue_items_from_scribe(result, source_session="session-a")
    second = build_queue_items_from_scribe(result, source_session="session-a")
    assert [item.id for item in first] == [item.id for item in second]


def test_queue_append_list_approve_and_lorebook_write(tmp_path) -> None:
    queue_path = tmp_path / "review_queue.jsonl"
    lore_path = tmp_path / "lorebook.json"

    queue_store = LoreQueueStore()
    lore_store = LorebookStore()
    items = build_queue_items_from_scribe(_scribe_result(), source_session="session-a")
    queue_store.append_items(str(queue_path), items)

    pending_before = queue_store.list_items(str(queue_path), status="pending")
    assert len(pending_before) == 2

    target = next(item for item in pending_before if item.kind == "entity")
    lore_store.add_entity(str(lore_path), target.payload)
    approved = queue_store.mark_approved(str(queue_path), target.id)
    assert approved.status == "approved"

    pending_after = queue_store.list_items(str(queue_path), status="pending")
    assert len(pending_after) == 1
    all_items = queue_store.list_items(str(queue_path), status=None)
    assert len(all_items) == 2
    assert any(item.id == target.id and item.status == "approved" for item in all_items)

    lorebook = lore_store.load(str(lore_path))
    assert len(lorebook.entities) == 1
    assert lorebook.entities[0]["name"] == "goblin"


def test_queue_append_skips_existing_ids(tmp_path) -> None:
    queue_path = tmp_path / "review_queue.jsonl"
    queue_store = LoreQueueStore()
    items = build_queue_items_from_scribe(_scribe_result(), source_session="session-a")

    first_new, first_skipped = queue_store.append_items(str(queue_path), items)
    second_new, second_skipped = queue_store.append_items(str(queue_path), items)

    assert (first_new, first_skipped) == (2, 0)
    assert (second_new, second_skipped) == (0, 2)

    all_items = queue_store.list_items(str(queue_path), status=None)
    ids = [item.id for item in all_items]
    assert len(all_items) == 2
    assert len(ids) == len(set(ids))


def test_lorebook_load_migrates_legacy_entities_without_ids(tmp_path) -> None:
    lore_path = tmp_path / "lorebook.json"
    with open(lore_path, "w", encoding="utf-8") as handle:
        json.dump(
            {"entities": [{"name": "Goblin", "kind": "npc"}], "facts": []}, handle
        )

    lorebook = LorebookStore().load(str(lore_path))

    assert len(lorebook.entities) == 1
    migrated = lorebook.entities[0]
    assert migrated["name"] == "goblin"
    assert migrated["kind"] == "npc"
    assert isinstance(migrated["entity_id"], str)
    assert len(migrated["entity_id"]) == 12
    assert migrated["aliases"] == []


def test_lorebook_add_entity_dedupes_by_canonical_entity_id(tmp_path) -> None:
    lore_path = tmp_path / "lorebook.json"
    store = LorebookStore()

    store.add_entity(str(lore_path), {"name": "Goblin", "kind": "npc", "count": 1})
    store.add_entity(str(lore_path), {"name": "goblins", "kind": "npc", "count": 2})

    lorebook = store.load(str(lore_path))
    assert len(lorebook.entities) == 1
    entity = lorebook.entities[0]
    assert entity["name"] == "goblin"
    assert entity["count"] == 3
    assert entity["aliases"] == []


def test_queue_appends_relation_candidates_and_dedupes(tmp_path) -> None:
    queue_path = tmp_path / "review_queue.jsonl"
    queue_store = LoreQueueStore()
    player_id = str(player_entity()["entity_id"])
    goblin_id = entity_id("goblin", "npc")
    result = ScribeResult(
        summary=SessionSummary(text="x"),
        entities=[],
        facts=[],
        relations=[
            RelationCandidate(
                subject_entity_id=player_id,
                predicate="attacked",
                object_entity_id=goblin_id,
                subject_name="player",
                object_name="goblin",
                evidence={"event_type": "intent_resolved", "event_ts": 2},
                ts_first_seen=2,
                ts_last_seen=2,
            )
        ],
    )
    items = build_queue_items_from_scribe(result, source_session="session-r")
    assert len(items) == 1
    assert items[0].kind == "relation"
    assert items[0].id.startswith("relation:")

    first_new, first_skipped = queue_store.append_items(str(queue_path), items)
    second_new, second_skipped = queue_store.append_items(str(queue_path), items)
    assert (first_new, first_skipped) == (1, 0)
    assert (second_new, second_skipped) == (0, 1)


def test_relation_queue_id_is_deterministic_for_same_input() -> None:
    player_id = str(player_entity()["entity_id"])
    goblin_id = entity_id("goblin", "unknown")
    result = ScribeResult(
        summary=SessionSummary(text="x"),
        entities=[],
        facts=[],
        relations=[
            RelationCandidate(
                subject_entity_id=player_id,
                predicate="attacked",
                object_entity_id=goblin_id,
                subject_name="player",
                object_name="goblin",
                evidence={"event_type": "intent_resolved", "event_ts": 2},
                ts_first_seen=2,
                ts_last_seen=2,
            )
        ],
    )
    first = build_queue_items_from_scribe(result, source_session="session-r")
    second = build_queue_items_from_scribe(result, source_session="session-r")
    assert first[0].id == second[0].id


def test_lorebook_add_relation_persists_and_updates_last_seen(tmp_path) -> None:
    lore_path = tmp_path / "lorebook.json"
    store = LorebookStore()
    player_id = str(player_entity()["entity_id"])
    goblin_id = entity_id("goblin", "npc")
    relation = {
        "subject_entity_id": player_id,
        "predicate": "attacked",
        "object_entity_id": goblin_id,
        "evidence": {"event_type": "intent_resolved", "event_ts": 2},
        "ts_first_seen": 2,
        "ts_last_seen": 2,
    }

    store.add_relation(str(lore_path), relation)
    relation_later = dict(relation)
    relation_later["ts_last_seen"] = 7
    store.add_relation(str(lore_path), relation_later)

    lorebook = store.load(str(lore_path))
    assert len(lorebook.relations) == 1
    relation_row = lorebook.relations[0]
    assert relation_row["predicate"] == "attacked"
    assert relation_row["ts_first_seen"] == 2
    assert relation_row["ts_last_seen"] == 7
    entity_ids = {str(entity["entity_id"]) for entity in lorebook.entities}
    assert player_id in entity_ids
    assert goblin_id in entity_ids
