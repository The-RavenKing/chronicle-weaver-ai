"""Engine integration tests for one deterministic input."""

from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.drand_stub import DrandBeacon
from chronicle_weaver_ai.engine import Engine, reduce_state
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.models import (
    EngineConfig,
    GameMode,
    GameState,
    Intent,
    Mechanic,
)


def test_attack_goblin_triggers_combat_roll_and_logs_events() -> None:
    store = InMemoryEventStore()
    provider = FixedEntropyDiceProvider((42,))
    engine = Engine(
        event_store=store,
        dice_provider=provider,
        config=EngineConfig(use_drand=False),
    )
    initial_state = GameState()

    state_1, output_1 = engine.process_input(state=initial_state, text="attack goblin")
    assert output_1.intent == Intent.ATTACK
    assert output_1.mechanic == Mechanic.COMBAT_ROLL
    assert output_1.dice_roll is not None
    assert state_1.mode == GameMode.COMBAT
    assert state_1.combat is not None
    assert state_1.combat.round_number == 1
    assert state_1.combat.turn_index == 1
    assert len(state_1.combat.entropy_pool) == 7

    state_2, output_2 = engine.process_input(state=state_1, text="attack goblin")
    assert output_2.intent == Intent.ATTACK
    assert output_2.mechanic == Mechanic.COMBAT_ROLL
    assert output_2.dice_roll is not None
    assert state_2.mode == GameMode.COMBAT
    assert state_2.combat is not None
    assert state_2.combat.round_number == 1
    assert state_2.combat.turn_index == 2
    assert len(state_2.combat.entropy_pool) == 6

    state_3, output_3 = engine.process_input(state=state_2, text="flee")
    assert output_3.intent == Intent.DISENGAGE
    assert output_3.mechanic == Mechanic.DISENGAGE
    assert output_3.dice_roll is None
    assert state_3.mode == GameMode.EXPLORATION
    assert state_3.combat is None

    event_types = [event.event_type for event in store.list_events()]
    assert "combat_disengaged" in event_types
    assert "entropy_prefetched" in event_types
    assert len(store.list_events()) == 13


def test_empty_pool_starts_new_round_on_next_attack() -> None:
    store = InMemoryEventStore()
    provider = FixedEntropyDiceProvider((10, 11, 12, 13))
    engine = Engine(
        event_store=store,
        dice_provider=provider,
        config=EngineConfig(combat_entropy_pool_size=1, use_drand=False),
    )

    state_1, _ = engine.process_input(state=GameState(), text="attack goblin")
    assert state_1.combat is not None
    assert state_1.combat.round_number == 1
    assert state_1.combat.turn_index == 1
    assert state_1.combat.entropy_pool == []

    state_2, _ = engine.process_input(state=state_1, text="attack goblin")
    assert state_2.combat is not None
    assert state_2.combat.round_number == 2
    assert state_2.combat.turn_index == 1
    assert state_2.combat.entropy_pool == []


class _FakeDrandClient:
    def __init__(self, beacon: DrandBeacon) -> None:
        self._beacon = beacon

    def latest(self) -> DrandBeacon:
        return self._beacon

    def by_round(self, round_number: int) -> DrandBeacon:
        return DrandBeacon(
            round=round_number,
            randomness=self._beacon.randomness,
            signature=self._beacon.signature,
            previous_signature=self._beacon.previous_signature,
        )


class _FailingDrandClient:
    def latest(self) -> DrandBeacon:
        raise RuntimeError("drand unavailable")

    def by_round(self, round_number: int) -> DrandBeacon:
        raise RuntimeError("drand unavailable")


def test_entropy_prefetch_uses_drand_payload_when_available() -> None:
    values = (10).to_bytes(4, "big") + (11).to_bytes(4, "big")
    beacon = DrandBeacon(
        round=100,
        randomness=values.hex(),
        signature="abcd",
        previous_signature="1234",
    )
    store = InMemoryEventStore()
    engine = Engine(
        event_store=store,
        dice_provider=FixedEntropyDiceProvider((99, 98)),
        config=EngineConfig(combat_entropy_pool_size=2, use_drand=True),
        drand_client=_FakeDrandClient(beacon),
    )
    state, _ = engine.process_input(state=GameState(), text="attack goblin")

    prefetched = next(
        event
        for event in store.list_events()
        if event.event_type == "entropy_prefetched"
    )
    assert prefetched.payload["source"] == "drand"
    assert prefetched.payload["drand_base_url"] == "https://api.drand.sh"
    assert prefetched.payload["rounds_used"] == [100]
    assert "fallback_reason" not in prefetched.payload
    assert isinstance(prefetched.payload["values"], list)
    assert len(prefetched.payload["values"]) == 2
    replayed = store.replay(GameState(), reduce_state)
    assert replayed == state


def test_entropy_prefetch_falls_back_to_local_on_drand_error() -> None:
    store = InMemoryEventStore()
    engine = Engine(
        event_store=store,
        dice_provider=FixedEntropyDiceProvider((42, 43, 44)),
        config=EngineConfig(combat_entropy_pool_size=2, use_drand=True),
        drand_client=_FailingDrandClient(),
    )
    state, _ = engine.process_input(state=GameState(), text="attack goblin")
    assert state.combat is not None

    prefetched = next(
        event
        for event in store.list_events()
        if event.event_type == "entropy_prefetched"
    )
    assert prefetched.payload["source"] == "local"
    assert prefetched.payload["fallback_reason"] == "network_error"
    assert prefetched.payload["drand_base_url"] == "https://api.drand.sh"
    assert isinstance(prefetched.payload["values"], list)
    assert len(prefetched.payload["values"]) == 2


def test_entropy_prefetch_uses_disabled_reason_when_env_set(monkeypatch) -> None:
    monkeypatch.setenv("DRAND_DISABLED", "TRUE")
    store = InMemoryEventStore()
    engine = Engine(
        event_store=store,
        dice_provider=FixedEntropyDiceProvider((42, 43, 44)),
        config=EngineConfig(combat_entropy_pool_size=2, use_drand=True),
        drand_client=_FakeDrandClient(
            DrandBeacon(round=1, randomness="0000000a", signature="abcd")
        ),
    )
    state, _ = engine.process_input(state=GameState(), text="attack goblin")
    assert state.combat is not None
    assert state.combat.entropy_source == "local"
    assert state.combat.entropy_fallback_reason == "disabled"

    prefetched = next(
        event
        for event in store.list_events()
        if event.event_type == "entropy_prefetched"
    )
    assert prefetched.payload["source"] == "local"
    assert prefetched.payload["fallback_reason"] == "disabled"


class _TimeoutDrandClient:
    def latest(self) -> DrandBeacon:
        raise TimeoutError("timed out")

    def by_round(self, round_number: int) -> DrandBeacon:
        raise TimeoutError("timed out")


def test_entropy_prefetch_timeout_fallback_reason() -> None:
    store = InMemoryEventStore()
    engine = Engine(
        event_store=store,
        dice_provider=FixedEntropyDiceProvider((42, 43, 44)),
        config=EngineConfig(combat_entropy_pool_size=2, use_drand=True),
        drand_client=_TimeoutDrandClient(),
    )
    state, _ = engine.process_input(state=GameState(), text="attack goblin")
    assert state.combat is not None
    assert state.combat.entropy_fallback_reason == "timeout"

    prefetched = next(
        event
        for event in store.list_events()
        if event.event_type == "entropy_prefetched"
    )
    assert prefetched.payload["source"] == "local"
    assert prefetched.payload["fallback_reason"] == "timeout"


class _MalformedDrandClient:
    def latest(self) -> DrandBeacon:
        return DrandBeacon(round=100, randomness="zzzz", signature="abcd")

    def by_round(self, round_number: int) -> DrandBeacon:
        return DrandBeacon(round=round_number, randomness="zzzz", signature="abcd")


def test_entropy_prefetch_bad_response_fallback_reason() -> None:
    store = InMemoryEventStore()
    engine = Engine(
        event_store=store,
        dice_provider=FixedEntropyDiceProvider((42, 43, 44)),
        config=EngineConfig(combat_entropy_pool_size=2, use_drand=True),
        drand_client=_MalformedDrandClient(),
    )
    state, _ = engine.process_input(state=GameState(), text="attack goblin")
    assert state.combat is not None
    assert state.combat.entropy_fallback_reason == "bad_response"

    prefetched = next(
        event
        for event in store.list_events()
        if event.event_type == "entropy_prefetched"
    )
    assert prefetched.payload["source"] == "local"
    assert prefetched.payload["fallback_reason"] == "bad_response"
