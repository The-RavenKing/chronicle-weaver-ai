"""Event store append and replay tests."""

from chronicle_weaver_ai.engine import reduce_state
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.models import Event, GameMode, GameState, Intent, Mechanic


def test_append_and_list_events_order() -> None:
    store = InMemoryEventStore()
    first = Event(
        event_type="player_input", payload={"text": "attack goblin"}, timestamp=1
    )
    second = Event(
        event_type="mode_transition",
        payload={"from_mode": GameMode.EXPLORATION, "to_mode": GameMode.COMBAT},
        timestamp=2,
    )
    store.append(first)
    store.append(second)
    assert store.list_events() == [first, second]


def test_replay_is_deterministic() -> None:
    store = InMemoryEventStore()
    initial_state = GameState()
    store.append(
        Event(event_type="player_input", payload={"text": "attack goblin"}, timestamp=1)
    )
    store.append(
        Event(
            event_type="intent_resolved",
            payload={"intent": Intent.ATTACK, "mechanic": Mechanic.COMBAT_ROLL},
            timestamp=2,
        )
    )
    store.append(
        Event(
            event_type="mode_transition",
            payload={"from_mode": GameMode.EXPLORATION, "to_mode": GameMode.COMBAT},
            timestamp=3,
        )
    )
    first = store.replay(initial_state, reduce_state)
    second = store.replay(initial_state, reduce_state)
    assert first == second
    assert first.mode == GameMode.COMBAT
