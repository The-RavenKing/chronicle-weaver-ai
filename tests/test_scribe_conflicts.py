"""Tests for scribe conflict detection.

Covers:
- No conflicts for unknown entities
- name_mismatch when entity_id already in lorebook with different name
- kind_mismatch when entity_id already in lorebook with different kind
- duplicate_name when a different entity_id shares the same name
- Multiple conflicts reported per item
- Non-entity queue items are skipped
- Empty lorebook yields no conflicts
- check_conflicts convenience method on LoreQueueStore
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from chronicle_weaver_ai.lore.models import Lorebook, LoreQueueItem
from chronicle_weaver_ai.lore.store import LoreQueueStore, detect_conflicts


def _entity_item(
    item_id: str,
    entity_id: str,
    name: str,
    kind: str,
    status: str = "pending",
) -> LoreQueueItem:
    return LoreQueueItem(
        id=item_id,
        kind="entity",
        payload={"entity_id": entity_id, "name": name, "kind": kind},
        status=status,
        source_session="s1",
        ts=1,
    )


def _fact_item(item_id: str, text: str) -> LoreQueueItem:
    return LoreQueueItem(
        id=item_id,
        kind="fact",
        payload={"text": text},
        status="pending",
        source_session="s1",
        ts=1,
    )


def _lorebook(*entities: dict) -> Lorebook:
    return Lorebook(entities=list(entities), facts=[], relations=[])


# ── no conflicts ──────────────────────────────────────────────────────────────


def test_no_conflicts_empty_lorebook():
    item = _entity_item("i1", "e.goblin", "Goblin", "npc")
    reports = detect_conflicts([item], _lorebook())
    assert reports == []


def test_no_conflicts_known_matching_entity():
    item = _entity_item("i1", "e.goblin", "Goblin", "npc")
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})
    reports = detect_conflicts([item], lorebook)
    assert reports == []


def test_no_conflicts_new_entity():
    item = _entity_item("i1", "e.wizard", "Merlin", "npc")
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})
    reports = detect_conflicts([item], lorebook)
    assert reports == []


# ── name_mismatch ─────────────────────────────────────────────────────────────


def test_name_mismatch_detected():
    item = _entity_item("i1", "e.goblin", "Hobgoblin", "npc")
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})
    reports = detect_conflicts([item], lorebook)
    assert len(reports) == 1
    assert reports[0].conflict_type == "name_mismatch"
    assert reports[0].item_id == "i1"
    assert reports[0].existing_value == "Goblin"
    assert reports[0].incoming_value == "Hobgoblin"


def test_name_mismatch_case_insensitive_no_conflict():
    item = _entity_item("i1", "e.goblin", "goblin", "npc")
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})
    reports = detect_conflicts([item], lorebook)
    assert reports == []


# ── kind_mismatch ─────────────────────────────────────────────────────────────


def test_kind_mismatch_detected():
    item = _entity_item("i1", "e.goblin", "Goblin", "location")
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})
    reports = detect_conflicts([item], lorebook)
    assert len(reports) == 1
    assert reports[0].conflict_type == "kind_mismatch"
    assert reports[0].existing_value == "npc"
    assert reports[0].incoming_value == "location"


def test_name_and_kind_both_mismatch():
    item = _entity_item("i1", "e.goblin", "Cave Troll", "monster")
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})
    reports = detect_conflicts([item], lorebook)
    types = {r.conflict_type for r in reports}
    assert "name_mismatch" in types
    assert "kind_mismatch" in types


# ── duplicate_name ────────────────────────────────────────────────────────────


def test_duplicate_name_different_id():
    item = _entity_item("i1", "e.new_goblin", "Goblin", "npc")
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})
    reports = detect_conflicts([item], lorebook)
    assert len(reports) == 1
    assert reports[0].conflict_type == "duplicate_name"
    assert reports[0].existing_value == "e.goblin"
    assert reports[0].incoming_value == "e.new_goblin"


def test_duplicate_name_case_insensitive():
    item = _entity_item("i1", "e.other", "goblin", "npc")
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})
    reports = detect_conflicts([item], lorebook)
    assert any(r.conflict_type == "duplicate_name" for r in reports)


# ── non-entity items skipped ──────────────────────────────────────────────────


def test_fact_items_not_checked():
    item = _fact_item("i1", "Goblin attacked the inn.")
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})
    reports = detect_conflicts([item], lorebook)
    assert reports == []


def test_mixed_items_only_entity_checked():
    entity_item = _entity_item("i1", "e.goblin", "Hobgoblin", "npc")
    fact_item = _fact_item("i2", "Something happened.")
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})
    reports = detect_conflicts([entity_item, fact_item], lorebook)
    assert len(reports) == 1
    assert reports[0].item_id == "i1"


# ── check_conflicts convenience method ────────────────────────────────────────


def test_check_conflicts_via_store():
    lorebook = _lorebook({"entity_id": "e.goblin", "name": "Goblin", "kind": "npc"})

    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        # Write item directly to queue file
        with open(queue_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "i1",
                        "kind": "entity",
                        "payload": {
                            "entity_id": "e.goblin",
                            "name": "Troll",
                            "kind": "npc",
                        },
                        "status": "pending",
                        "source_session": "s1",
                        "ts": 1,
                    }
                )
                + "\n"
            )
        store = LoreQueueStore()
        reports = store.check_conflicts(queue_path, lorebook)

    assert len(reports) == 1
    assert reports[0].conflict_type == "name_mismatch"
