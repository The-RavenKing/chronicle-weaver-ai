"""In-memory deterministic event store."""

from __future__ import annotations

import json
from collections.abc import Callable

from chronicle_weaver_ai.models import Event, GameState


class InMemoryEventStore:
    """In-memory event store for deterministic append and replay."""

    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(self, event: Event) -> None:
        """Append one event."""
        self._events.append(event)

    def list_events(self) -> list[Event]:
        """Return events in append order."""
        return list(self._events)

    def replay(
        self,
        initial_state: GameState,
        reducer: Callable[[GameState, Event], GameState],
    ) -> GameState:
        """Replay all events through reducer and return final state."""
        state = initial_state
        for event in self._events:
            state = reducer(state, event)
        return state

    def save_jsonl(self, path: str) -> None:
        """Write all current events to a JSONL file."""
        with open(path, "w", encoding="utf-8") as handle:
            for event in self._events:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False))
                handle.write("\n")

    def load_jsonl(self, path: str) -> list[Event]:
        """Load events from JSONL and replace current in-memory state."""
        loaded: list[Event] = []
        with open(path, "r", encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON at line {index}: {exc.msg}"
                    ) from exc
                try:
                    loaded.append(Event.from_dict(raw))
                except ValueError as exc:
                    raise ValueError(f"Invalid event at line {index}: {exc}") from exc
        self._events = loaded
        return self.list_events()
