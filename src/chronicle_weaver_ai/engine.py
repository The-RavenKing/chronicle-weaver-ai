"""Engine orchestration for one deterministic input cycle."""

from __future__ import annotations

from dataclasses import replace

from chronicle_weaver_ai.dice import LocalCSPRNGDiceProvider, roll_d20_record
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.models import (
    DiceProvider,
    DiceRollRecord,
    EngineOutput,
    Event,
    GameMode,
    GameState,
    Intent,
    IntentResult,
    Mechanic,
    PlayerInput,
)
from chronicle_weaver_ai.state_machine import transition


class Engine:
    """Coordinates input routing, transition, mechanics, and event logging."""

    def __init__(
        self,
        intent_router: IntentRouter | None = None,
        event_store: InMemoryEventStore | None = None,
        dice_provider: DiceProvider | None = None,
    ) -> None:
        self.intent_router = intent_router or IntentRouter()
        self.event_store = event_store or InMemoryEventStore()
        self.dice_provider = dice_provider or LocalCSPRNGDiceProvider()

    def process_input(
        self, state: GameState, text: str
    ) -> tuple[GameState, EngineOutput]:
        """Process one player input into deterministic events and new state."""
        player_input = PlayerInput(text=text)
        intent_result = self.intent_router.route(
            text=player_input.text, current_mode=state.mode
        )
        new_mode = transition(state.mode, intent_result)

        dice_roll: DiceRollRecord | None = None
        if intent_result.mechanic == Mechanic.COMBAT_ROLL:
            dice_roll = roll_d20_record(self.dice_provider)

        events = _build_events(
            state=state,
            player_input=player_input,
            intent_result=intent_result,
            new_mode=new_mode,
            dice_roll=dice_roll,
        )
        for event in events:
            self.event_store.append(event)

        new_state = state
        for event in events:
            new_state = reduce_state(new_state, event)
        narrative = _narrative_stub(intent_result, dice_roll)
        output = EngineOutput(
            intent=intent_result.intent,
            mechanic=intent_result.mechanic,
            previous_mode=state.mode,
            new_mode=new_state.mode,
            dice_roll=dice_roll,
            narrative=narrative,
            events=tuple(events),
        )
        return new_state, output


def reduce_state(state: GameState, event: Event) -> GameState:
    """Pure reducer used by replay and direct engine updates."""
    next_state = replace(state, logical_time=max(state.logical_time, event.timestamp))
    if event.event_type == "player_input":
        return replace(next_state, last_input=str(event.payload["text"]))
    if event.event_type == "intent_resolved":
        intent_payload = event.payload.get("intent", Intent.UNKNOWN)
        mechanic_payload = event.payload.get("mechanic", Mechanic.CLARIFY)
        intent = (
            intent_payload
            if isinstance(intent_payload, Intent)
            else Intent(str(intent_payload))
        )
        mechanic = (
            mechanic_payload
            if isinstance(mechanic_payload, Mechanic)
            else Mechanic(str(mechanic_payload))
        )
        return replace(
            next_state,
            last_intent=intent,
            last_mechanic=mechanic,
        )
    if event.event_type == "mode_transition":
        target_mode_payload = event.payload.get("to_mode", next_state.mode)
        target_mode = (
            target_mode_payload
            if isinstance(target_mode_payload, GameMode)
            else GameMode(str(target_mode_payload))
        )
        return replace(
            next_state,
            mode=target_mode,
            turn=next_state.turn + 1,
        )
    if event.event_type == "dice_roll":
        value_payload = event.payload.get("value")
        if isinstance(value_payload, int):
            roll_value = value_payload
        else:
            roll_value = int(str(value_payload))
        return replace(next_state, last_roll=roll_value)
    return next_state


def _build_events(
    state: GameState,
    player_input: PlayerInput,
    intent_result: IntentResult,
    new_mode: GameMode,
    dice_roll: DiceRollRecord | None,
) -> list[Event]:
    timestamp = state.logical_time
    events: list[Event] = []

    timestamp += 1
    events.append(
        Event(
            event_type="player_input",
            payload={"text": player_input.text},
            timestamp=timestamp,
        )
    )

    timestamp += 1
    events.append(
        Event(
            event_type="intent_resolved",
            payload={
                "intent": intent_result.intent,
                "mechanic": intent_result.mechanic,
                "confidence": intent_result.confidence,
                "is_valid": intent_result.is_valid,
            },
            timestamp=timestamp,
        )
    )

    timestamp += 1
    events.append(
        Event(
            event_type="mode_transition",
            payload={"from_mode": state.mode, "to_mode": new_mode},
            timestamp=timestamp,
        )
    )

    if dice_roll is not None:
        timestamp += 1
        events.append(
            Event(
                event_type="dice_roll",
                payload={
                    "value": dice_roll.value,
                    "entropy": dice_roll.entropy,
                    "accepted_entropy": dice_roll.accepted_entropy,
                    "attempts": dice_roll.attempts,
                    "provider": dice_roll.provider,
                },
                timestamp=timestamp,
            )
        )
    return events


def _narrative_stub(
    intent_result: IntentResult, dice_roll: DiceRollRecord | None
) -> str:
    if intent_result.mechanic == Mechanic.CLARIFY:
        return "Action is ambiguous. Please clarify your intent."
    if intent_result.mechanic == Mechanic.COMBAT_ROLL and dice_roll is not None:
        return f"Combat roll resolved deterministically: d20={dice_roll.value}."
    if intent_result.mechanic == Mechanic.NARRATE_ONLY:
        return f"Action acknowledged: {intent_result.intent.value}."
    return "No narrative available."
