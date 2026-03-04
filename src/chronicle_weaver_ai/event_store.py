"""In-memory deterministic event store."""

from __future__ import annotations

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
