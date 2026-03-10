"""Tests for Scribe approval workflow.

Covers:
- mark_approved sets status to approved
- mark_rejected sets status to rejected (new method)
- Re-marking already-approved/rejected items
- Approving unknown ID raises ValueError
- list_items filters by status
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from chronicle_weaver_ai.lore.store import LoreQueueStore


def _write_queue(path: str, items: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")


def _sample_item(
    item_id: str = "item1",
    kind: str = "entity",
    status: str = "pending",
) -> dict:
    return {
        "id": item_id,
        "kind": kind,
        "payload": {"name": "Goblin King", "kind": "npc"},
        "status": status,
        "source_session": "session1",
        "ts": 1000.0,
    }


# ── mark_approved ─────────────────────────────────────────────────────────────


def test_mark_approved_sets_status():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        _write_queue(queue_path, [_sample_item("item1", status="pending")])

        store = LoreQueueStore()
        result = store.mark_approved(queue_path, "item1")
        assert result.status == "approved"

        items = store.list_items(queue_path, status=None)
        assert items[0].status == "approved"


def test_mark_approved_unknown_id_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        _write_queue(queue_path, [_sample_item("item1")])

        store = LoreQueueStore()
        with pytest.raises(ValueError, match="item2"):
            store.mark_approved(queue_path, "item2")


# ── mark_rejected (new) ────────────────────────────────────────────────────────


def test_mark_rejected_sets_status():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        _write_queue(queue_path, [_sample_item("item1", status="pending")])

        store = LoreQueueStore()
        result = store.mark_rejected(queue_path, "item1")
        assert result.status == "rejected"

        items = store.list_items(queue_path, status=None)
        assert items[0].status == "rejected"


def test_mark_rejected_unknown_id_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        _write_queue(queue_path, [_sample_item("item1")])

        store = LoreQueueStore()
        with pytest.raises(ValueError, match="missing"):
            store.mark_rejected(queue_path, "missing")


def test_mark_rejected_does_not_affect_other_items():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        _write_queue(
            queue_path,
            [
                _sample_item("item1", status="pending"),
                _sample_item("item2", kind="fact", status="pending"),
            ],
        )

        store = LoreQueueStore()
        store.mark_rejected(queue_path, "item1")

        items = store.list_items(queue_path, status=None)
        item_map = {item.id: item for item in items}
        assert item_map["item1"].status == "rejected"
        assert item_map["item2"].status == "pending"


# ── list_items filtering ───────────────────────────────────────────────────────


def test_list_items_pending_filters_correctly():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        _write_queue(
            queue_path,
            [
                _sample_item("a", status="pending"),
                _sample_item("b", status="approved"),
                _sample_item("c", status="rejected"),
                _sample_item("d", status="pending"),
            ],
        )

        store = LoreQueueStore()
        pending = store.list_items(queue_path, status="pending")
        assert len(pending) == 2
        assert all(item.status == "pending" for item in pending)


def test_list_items_none_returns_all():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        _write_queue(
            queue_path,
            [
                _sample_item("a", status="pending"),
                _sample_item("b", status="approved"),
                _sample_item("c", status="rejected"),
            ],
        )

        store = LoreQueueStore()
        all_items = store.list_items(queue_path, status=None)
        assert len(all_items) == 3


def test_list_items_approved_filters_correctly():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        _write_queue(
            queue_path,
            [
                _sample_item("a", status="approved"),
                _sample_item("b", status="pending"),
            ],
        )

        store = LoreQueueStore()
        approved = store.list_items(queue_path, status="approved")
        assert len(approved) == 1
        assert approved[0].id == "a"


# ── re-marking items ───────────────────────────────────────────────────────────


def test_can_approve_already_approved_item():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        _write_queue(queue_path, [_sample_item("item1", status="approved")])

        store = LoreQueueStore()
        result = store.mark_approved(queue_path, "item1")
        assert result.status == "approved"


def test_can_reject_already_rejected_item():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = str(Path(tmpdir) / "queue.jsonl")
        _write_queue(queue_path, [_sample_item("item1", status="rejected")])

        store = LoreQueueStore()
        result = store.mark_rejected(queue_path, "item1")
        assert result.status == "rejected"
