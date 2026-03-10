"""Tests for state snapshot creation and rollback.

Covers:
- create_snapshot captures state and event count
- restore_from_snapshot returns stored state and truncated events
- Rollback discards events after snapshot position
- snapshot_to_dict / snapshot_from_dict round-trip
- Snapshot with empty event list
"""

from __future__ import annotations

from chronicle_weaver_ai.models import Event, GameMode, GameState
from chronicle_weaver_ai.snapshot import (
    create_snapshot,
    restore_from_snapshot,
    snapshot_from_dict,
    snapshot_to_dict,
)


def _state(mode: GameMode = GameMode.EXPLORATION, turn: int = 0) -> GameState:
    return GameState(mode=mode, turn=turn)


def _event(name: str) -> Event:
    return Event(event_type=name, payload={}, timestamp=0)


# ── create_snapshot ───────────────────────────────────────────────────────────


def test_create_snapshot_records_event_count():
    state = _state()
    events = [_event("e1"), _event("e2"), _event("e3")]
    snap = create_snapshot(state, events)
    assert snap.event_count == 3


def test_create_snapshot_stores_state():
    state = _state(mode=GameMode.COMBAT, turn=5)
    snap = create_snapshot(state, [])
    assert snap.state.mode == GameMode.COMBAT
    assert snap.state.turn == 5


def test_create_snapshot_stores_label():
    state = _state()
    snap = create_snapshot(state, [], label="before boss")
    assert snap.label == "before boss"


def test_create_snapshot_with_empty_events():
    state = _state()
    snap = create_snapshot(state, [])
    assert snap.event_count == 0


def test_create_snapshot_created_at_is_positive():
    state = _state()
    snap = create_snapshot(state, [])
    assert snap.created_at > 0


# ── restore_from_snapshot ─────────────────────────────────────────────────────


def test_restore_returns_snapshot_state():
    original_state = _state(mode=GameMode.COMBAT, turn=2)
    events = [_event("e1"), _event("e2")]
    snap = create_snapshot(original_state, events)

    # Add more events after snapshot
    events.append(_event("e3"))
    events.append(_event("e4"))

    restored_state, restored_events = restore_from_snapshot(snap, events)
    assert restored_state.mode == GameMode.COMBAT
    assert restored_state.turn == 2


def test_restore_truncates_events_to_snapshot_count():
    state = _state()
    events = [_event("e1"), _event("e2")]
    snap = create_snapshot(state, events)

    events.extend([_event("e3"), _event("e4"), _event("e5")])
    _, restored_events = restore_from_snapshot(snap, events)
    assert len(restored_events) == 2
    assert restored_events[0].event_type == "e1"
    assert restored_events[1].event_type == "e2"


def test_restore_with_zero_events():
    state = _state()
    snap = create_snapshot(state, [])
    events = [_event("e1"), _event("e2")]
    restored_state, restored_events = restore_from_snapshot(snap, events)
    assert restored_events == []
    assert restored_state == state


def test_restore_does_not_mutate_original_event_list():
    state = _state()
    events = [_event("e1"), _event("e2"), _event("e3")]
    snap = create_snapshot(state, events[:2])
    original_length = len(events)
    restore_from_snapshot(snap, events)
    assert len(events) == original_length  # original list unchanged


# ── Serialisation round-trip ──────────────────────────────────────────────────


def test_snapshot_to_dict_and_back():
    state = _state(mode=GameMode.EXPLORATION, turn=7)
    events = [_event("e1"), _event("e2"), _event("e3")]
    snap = create_snapshot(state, events, label="checkpoint")

    d = snapshot_to_dict(snap)
    restored = snapshot_from_dict(d)

    assert restored.event_count == 3
    assert restored.label == "checkpoint"
    assert restored.state.mode == GameMode.EXPLORATION
    assert restored.state.turn == 7


def test_snapshot_to_dict_contains_required_keys():
    state = _state()
    snap = create_snapshot(state, [])
    d = snapshot_to_dict(snap)
    assert "state" in d
    assert "event_count" in d
    assert "label" in d
    assert "created_at" in d


def test_snapshot_from_dict_combat_mode():
    state = _state(mode=GameMode.COMBAT, turn=3)
    snap = create_snapshot(state, [_event("x")], label="mid-combat")
    d = snapshot_to_dict(snap)
    restored = snapshot_from_dict(d)
    assert restored.state.mode == GameMode.COMBAT
    assert restored.event_count == 1
