"""Engine integration tests for one deterministic input."""

from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.engine import Engine
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.models import GameMode, GameState, Intent, Mechanic


def test_attack_goblin_triggers_combat_roll_and_logs_events() -> None:
    store = InMemoryEventStore()
    provider = FixedEntropyDiceProvider((42,))
    engine = Engine(event_store=store, dice_provider=provider)
    new_state, output = engine.process_input(state=GameState(), text="attack goblin")

    assert output.intent == Intent.ATTACK
    assert output.mechanic == Mechanic.COMBAT_ROLL
    assert output.dice_roll is not None
    assert output.dice_roll.value == (42 % 20) + 1
    assert new_state.mode == GameMode.COMBAT
    assert len(store.list_events()) == 4
