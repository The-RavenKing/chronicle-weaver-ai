"""State snapshot creation and rollback for Chronicle Weaver.

A snapshot captures the deterministic game state at a given event-log
position so that the session can be rewound to that point.

Design notes
------------
- GameState is already an immutable frozen dataclass; snapshots are just a
  thin wrapper adding event-count and timestamp metadata.
- Rollback truncates the event log to the snapshot position and returns the
  stored state directly (no re-derivation needed because the state was
  captured at that exact position).
- Snapshots are JSON-serialisable to support persistence alongside campaign
  files.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from chronicle_weaver_ai.models import Event, GameState


@dataclass(frozen=True)
class StateSnapshot:
    """Immutable snapshot of engine state at a specific event-log position.

    state         — the full GameState at the time of snapshotting.
    event_count   — number of events in the log when snapshot was taken.
                    Rollback truncates the live event list to this length.
    label         — optional human-readable label (e.g. "before boss fight").
    created_at    — unix timestamp (float) when the snapshot was created.
    """

    state: GameState
    event_count: int
    label: str = ""
    created_at: float = field(default_factory=time.time)


def create_snapshot(
    state: GameState,
    events: list[Event],
    label: str = "",
) -> StateSnapshot:
    """Capture the current state and event-log length as an immutable snapshot."""
    return StateSnapshot(
        state=state,
        event_count=len(events),
        label=label,
        created_at=time.time(),
    )


def restore_from_snapshot(
    snapshot: StateSnapshot,
    events: list[Event],
) -> tuple[GameState, list[Event]]:
    """Restore state to the snapshot position by truncating the event log.

    Returns (restored_state, truncated_events).

    The caller should replace their live event list with the returned
    truncated list and use the returned GameState as the new current state.
    Any events appended after the snapshot was created are discarded.
    """
    truncated = events[: snapshot.event_count]
    return snapshot.state, truncated


def snapshot_to_dict(snap: StateSnapshot) -> dict:
    """Serialise a StateSnapshot to a plain JSON-compatible dict."""
    from dataclasses import asdict

    state_dict = asdict(snap.state)
    return {
        "state": state_dict,
        "event_count": snap.event_count,
        "label": snap.label,
        "created_at": snap.created_at,
    }


def snapshot_from_dict(d: dict) -> StateSnapshot:
    """Reconstruct a StateSnapshot from a serialised dict.

    Only the fundamental fields are restored; the GameState is reconstructed
    from its stored dict representation.
    """
    from chronicle_weaver_ai.models import (
        CombatState,
        GameMode,
        Intent,
        Mechanic,
        TurnBudget,
    )

    raw_state = d["state"]
    raw_combat = raw_state.get("combat")
    combat = None
    if raw_combat is not None:
        raw_budget = raw_combat.get("turn_budget") or {}
        budget = TurnBudget(
            action=bool(raw_budget.get("action", True)),
            bonus_action=bool(raw_budget.get("bonus_action", True)),
            reaction=bool(raw_budget.get("reaction", True)),
            movement_remaining=int(raw_budget.get("movement_remaining", 30)),
            object_interaction=bool(raw_budget.get("object_interaction", True)),
            speech=bool(raw_budget.get("speech", True)),
        )
        combat = CombatState(
            round_number=int(raw_combat.get("round_number", 1)),
            turn_index=int(raw_combat.get("turn_index", 0)),
            initiative_order=list(raw_combat.get("initiative_order") or []),
            entropy_pool=list(raw_combat.get("entropy_pool") or []),
            entropy_source=raw_combat.get("entropy_source"),
            entropy_fallback_reason=raw_combat.get("entropy_fallback_reason"),
            turn_budget=budget,
        )

    mode_raw = raw_state.get("mode", "exploration")
    try:
        mode = GameMode(mode_raw)
    except ValueError:
        mode = GameMode.EXPLORATION

    intent_raw = raw_state.get("last_intent", "unknown")
    try:
        last_intent = Intent(intent_raw)
    except ValueError:
        last_intent = Intent.UNKNOWN

    mechanic_raw = raw_state.get("last_mechanic", "clarify")
    try:
        last_mechanic = Mechanic(mechanic_raw)
    except ValueError:
        last_mechanic = Mechanic.CLARIFY

    state = GameState(
        mode=mode,
        turn=int(raw_state.get("turn", 0)),
        logical_time=int(raw_state.get("logical_time", 0)),
        last_input=str(raw_state.get("last_input", "")),
        last_intent=last_intent,
        last_mechanic=last_mechanic,
        last_roll=raw_state.get("last_roll"),
        combat=combat,
    )

    return StateSnapshot(
        state=state,
        event_count=int(d["event_count"]),
        label=str(d.get("label", "")),
        created_at=float(d.get("created_at", 0.0)),
    )
