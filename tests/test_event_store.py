"""Event store append and replay tests."""

import pytest

from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.engine import Engine
from chronicle_weaver_ai.engine import reduce_state
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.models import (
    EngineConfig,
    Event,
    GameMode,
    GameState,
    Intent,
    Mechanic,
)


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


def test_event_round_trip_dict_schema() -> None:
    event = Event(
        event_type="mode_transition",
        payload={"from_mode": GameMode.EXPLORATION, "to_mode": GameMode.COMBAT},
        timestamp=3,
    )
    raw = event.to_dict()
    assert raw["type"] == "mode_transition"
    assert raw["ts"] == 3
    parsed = Event.from_dict(raw)
    assert parsed == Event(
        event_type="mode_transition",
        payload={"from_mode": "exploration", "to_mode": "combat"},
        timestamp=3,
    )


def test_save_load_jsonl_replay_determinism(tmp_path) -> None:
    live_store = InMemoryEventStore()
    engine = Engine(
        event_store=live_store,
        dice_provider=FixedEntropyDiceProvider((42, 43, 44)),
        config=EngineConfig(use_drand=False),
    )
    live_state = GameState()
    for text in ["attack goblin", "attack goblin", "flee"]:
        live_state, _ = engine.process_input(state=live_state, text=text)

    path = tmp_path / "session.jsonl"
    live_store.save_jsonl(str(path))

    replay_store = InMemoryEventStore()
    loaded_events = replay_store.load_jsonl(str(path))
    replayed_state = replay_store.replay(GameState(), reduce_state)

    assert len(loaded_events) == len(live_store.list_events())
    assert replayed_state.mode == GameMode.EXPLORATION
    assert replayed_state == live_state


def test_replay_preserves_combat_round_and_turn(tmp_path) -> None:
    live_store = InMemoryEventStore()
    engine = Engine(
        event_store=live_store,
        dice_provider=FixedEntropyDiceProvider((21, 22, 23, 24)),
        config=EngineConfig(use_drand=False),
    )
    live_state = GameState()
    for text in ["attack goblin", "attack goblin"]:
        live_state, _ = engine.process_input(state=live_state, text=text)

    path = tmp_path / "combat.jsonl"
    live_store.save_jsonl(str(path))

    replay_store = InMemoryEventStore()
    replay_store.load_jsonl(str(path))
    replayed_state = replay_store.replay(GameState(), reduce_state)

    assert replayed_state.mode == live_state.mode == GameMode.COMBAT
    assert replayed_state.combat is not None
    assert live_state.combat is not None
    assert replayed_state.combat.round_number == live_state.combat.round_number
    assert replayed_state.combat.turn_index == live_state.combat.turn_index


def test_load_jsonl_invalid_line_raises_clear_error(tmp_path) -> None:
    path = tmp_path / "invalid.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON at line 1"):
        InMemoryEventStore().load_jsonl(str(path))
