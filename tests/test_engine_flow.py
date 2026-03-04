"""Engine integration tests for one deterministic input."""

from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.engine import Engine
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.models import GameMode, GameState, Intent, Mechanic


def test_attack_goblin_triggers_combat_roll_and_logs_events() -> None:
    store = InMemoryEventStore()
    provider = FixedEntropyDiceProvider((42,))
    engine = Engine(event_store=store, dice_provider=provider)
    initial_state = GameState()

    state_1, output_1 = engine.process_input(state=initial_state, text="attack goblin")
    assert output_1.intent == Intent.ATTACK
    assert output_1.mechanic == Mechanic.COMBAT_ROLL
    assert output_1.dice_roll is not None
    assert state_1.mode == GameMode.COMBAT

    state_2, output_2 = engine.process_input(state=state_1, text="attack goblin")
    assert output_2.intent == Intent.ATTACK
    assert output_2.mechanic == Mechanic.COMBAT_ROLL
    assert output_2.dice_roll is not None
    assert state_2.mode == GameMode.COMBAT

    state_3, output_3 = engine.process_input(state=state_2, text="flee")
    assert output_3.intent == Intent.DISENGAGE
    assert output_3.mechanic == Mechanic.DISENGAGE
    assert output_3.dice_roll is None
    assert state_3.mode == GameMode.EXPLORATION

    event_types = [event.event_type for event in store.list_events()]
    assert "combat_disengaged" in event_types
    assert len(store.list_events()) == 12
