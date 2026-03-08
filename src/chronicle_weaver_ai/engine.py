"""Engine orchestration for one deterministic input cycle."""

from __future__ import annotations

import os
from dataclasses import replace

from chronicle_weaver_ai.dice import (
    LocalCSPRNGDiceProvider,
    roll_d20,
    roll_d20_record_from_entropy,
)
from chronicle_weaver_ai.drand_stub import (
    DEFAULT_DRAND_BASE_URL,
    DrandBeacon,
    DrandClientError,
    DrandHTTPClient,
)
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.models import (
    ActionCategory,
    CombatState,
    TurnBudget,
    DiceProvider,
    DiceRollRecord,
    EngineConfig,
    EngineOutput,
    Event,
    GameMode,
    GameState,
    Intent,
    IntentResult,
    Mechanic,
    can_spend_action,
    PlayerInput,
    can_speak,
    can_use_bonus_action,
    can_use_object_interaction,
    can_use_reaction,
    JSONValue,
    mark_spoken,
    new_turn_budget,
    spend_action,
    spend_bonus_action,
    spend_object_interaction,
    spend_reaction,
)
from chronicle_weaver_ai.state_machine import transition


class Engine:
    """Coordinates input routing, transition, mechanics, and event logging."""

    def __init__(
        self,
        intent_router: IntentRouter | None = None,
        event_store: InMemoryEventStore | None = None,
        dice_provider: DiceProvider | None = None,
        config: EngineConfig | None = None,
        combat_entropy_pool_size: int | None = None,
        drand_client: DrandHTTPClient | None = None,
    ) -> None:
        resolved_config = config or EngineConfig()
        if combat_entropy_pool_size is not None:
            resolved_config = replace(
                resolved_config,
                combat_entropy_pool_size=combat_entropy_pool_size,
            )
        if resolved_config.combat_entropy_pool_size < 1:
            raise ValueError("combat_entropy_pool_size must be >= 1")
        self.intent_router = intent_router or IntentRouter()
        self.event_store = event_store or InMemoryEventStore()
        self.dice_provider = dice_provider or LocalCSPRNGDiceProvider()
        self.config = resolved_config
        self._drand_base_url = _resolve_drand_base_url(self.config)
        self.drand_client = drand_client or DrandHTTPClient(
            base_url=self._drand_base_url,
            timeout_seconds=self.config.drand_timeout_seconds,
        )

    def process_input(
        self,
        state: GameState,
        text: str,
        intent_result: IntentResult | None = None,
    ) -> tuple[GameState, EngineOutput]:
        """Process one player input into deterministic events and new state."""
        player_input = PlayerInput(text=text)
        resolved_intent = intent_result or self.intent_router.route(
            text=player_input.text, current_mode=state.mode
        )

        resolved_intent, next_turn_budget = _consume_turn_budget(
            state=state,
            intent_result=resolved_intent,
        )
        new_mode = transition(state.mode, resolved_intent)

        prefetched_round: int | None = None
        prefetched_values: list[int] | None = None
        prefetched_initiative: list[str] | None = None
        prefetched_source: str | None = None
        prefetched_fallback_reason: str | None = None
        prefetched_drand_error: str | None = None
        prefetched_rounds_used: list[int] | None = None
        prefetched_beacons: list[dict[str, JSONValue]] | None = None
        combat_turn_budget_payload: dict[str, JSONValue] | None = None

        if next_turn_budget is not None:
            combat_turn_budget_payload = _turn_budget_to_payload(next_turn_budget)

        dice_roll: DiceRollRecord | None = None
        if (
            resolved_intent.mechanic == Mechanic.COMBAT_ROLL
            and new_mode == GameMode.COMBAT
        ):
            current_combat = state.combat
            if current_combat is None:
                prefetched_round = 1
                (
                    prefetched_source,
                    prefetched_values,
                    prefetched_fallback_reason,
                    prefetched_drand_error,
                    prefetched_rounds_used,
                    prefetched_beacons,
                ) = _prefetch_entropy_for_round(
                    dice_provider=self.dice_provider,
                    drand_client=self.drand_client if self.config.use_drand else None,
                    pool_size=self.config.combat_entropy_pool_size,
                    max_drand_rounds=self.config.drand_max_rounds,
                    drand_base_url=self._drand_base_url,
                    drand_disabled=_is_drand_disabled(),
                )
                prefetched_initiative = ["player", "enemy"]
            elif not current_combat.entropy_pool:
                prefetched_round = current_combat.round_number + 1
                (
                    prefetched_source,
                    prefetched_values,
                    prefetched_fallback_reason,
                    prefetched_drand_error,
                    prefetched_rounds_used,
                    prefetched_beacons,
                ) = _prefetch_entropy_for_round(
                    dice_provider=self.dice_provider,
                    drand_client=self.drand_client if self.config.use_drand else None,
                    pool_size=self.config.combat_entropy_pool_size,
                    max_drand_rounds=self.config.drand_max_rounds,
                    drand_base_url=self._drand_base_url,
                    drand_disabled=_is_drand_disabled(),
                )
                prefetched_initiative = (
                    list(current_combat.initiative_order)
                    if current_combat.initiative_order
                    else ["player", "enemy"]
                )

            if prefetched_values is not None:
                entropy_value = prefetched_values[0]
            elif current_combat is not None and current_combat.entropy_pool:
                entropy_value = current_combat.entropy_pool[0]
            else:
                raise RuntimeError("combat attack needs available entropy")

            dice_roll = roll_d20_record_from_entropy(
                entropy=entropy_value,
                provider="prefetched_pool",
            )

        events = _build_events(
            state=state,
            player_input=player_input,
            intent_result=resolved_intent,
            new_mode=new_mode,
            prefetched_round=prefetched_round,
            prefetched_values=prefetched_values,
            prefetched_initiative=prefetched_initiative,
            prefetched_source=prefetched_source,
            prefetched_fallback_reason=prefetched_fallback_reason,
            prefetched_drand_error=prefetched_drand_error,
            prefetched_rounds_used=prefetched_rounds_used,
            prefetched_beacons=prefetched_beacons,
            drand_base_url=self._drand_base_url,
            dice_roll=dice_roll,
            combat_turn_budget=combat_turn_budget_payload,
        )
        for event in events:
            self.event_store.append(event)

        new_state = state
        for event in events:
            new_state = reduce_state(new_state, event)
        narrative = _narrative_stub(
            intent_result=resolved_intent,
            previous_mode=state.mode,
            new_mode=new_state.mode,
            dice_roll=dice_roll,
        )
        output = EngineOutput(
            intent=resolved_intent.intent,
            mechanic=resolved_intent.mechanic,
            previous_mode=state.mode,
            new_mode=new_state.mode,
            dice_roll=dice_roll,
            narrative=narrative,
            events=tuple(events),
        )
        return new_state, output


def reduce_state(state: GameState, event: Event) -> GameState:
    """Pure reducer used by replay and direct engine updates."""
    if isinstance(event.timestamp, (int, float)):
        logical_time = max(state.logical_time, int(event.timestamp))
    else:
        logical_time = state.logical_time
    next_state = replace(state, logical_time=logical_time)
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
        combat = next_state.combat
        raw_turn_budget = event.payload.get("combat_turn_budget")
        if raw_turn_budget is not None and combat is not None:
            parsed_budget = _turn_budget_from_payload(raw_turn_budget)
            if parsed_budget is not None:
                combat = replace(combat, turn_budget=parsed_budget)
        return replace(
            next_state,
            combat=combat,
            mode=target_mode,
            turn=next_state.turn + 1,
        )
    if event.event_type == "entropy_prefetched":
        round_raw = event.payload.get("round", 1)
        if isinstance(round_raw, int):
            round_number = round_raw
        else:
            round_number = int(str(round_raw))

        values_raw = event.payload.get("values", [])
        if isinstance(values_raw, list):
            entropy_pool = []
            for value in values_raw:
                parsed_value = _parse_int_value(value)
                if parsed_value is not None:
                    entropy_pool.append(parsed_value)
        else:
            entropy_pool = []

        initiative_raw = event.payload.get("initiative_order", ["player", "enemy"])
        if isinstance(initiative_raw, list):
            initiative_order = [str(item) for item in initiative_raw]
        else:
            initiative_order = ["player", "enemy"]
        source_raw = event.payload.get("source")
        entropy_source = str(source_raw) if source_raw is not None else None
        fallback_raw = event.payload.get("fallback_reason")
        entropy_fallback_reason = (
            str(fallback_raw) if fallback_raw is not None else None
        )

        combat = CombatState(
            round_number=round_number,
            turn_index=0,
            initiative_order=initiative_order,
            entropy_pool=entropy_pool,
            entropy_source=entropy_source,
            entropy_fallback_reason=entropy_fallback_reason,
        )
        return replace(next_state, combat=combat)
    if event.event_type == "dice_roll":
        value_payload = event.payload.get("value")
        if isinstance(value_payload, int):
            roll_value = value_payload
        else:
            roll_value = int(str(value_payload))
        combat = next_state.combat
        if combat is not None:
            next_pool = list(combat.entropy_pool)
            if next_pool:
                next_pool.pop(0)
            combat = replace(
                combat,
                turn_index=combat.turn_index + 1,
                entropy_pool=next_pool,
                turn_budget=new_turn_budget(),
            )
        return replace(next_state, last_roll=roll_value, combat=combat)
    if event.event_type == "combat_disengaged":
        return replace(next_state, combat=None)
    return next_state


def _build_events(
    state: GameState,
    player_input: PlayerInput,
    intent_result: IntentResult,
    new_mode: GameMode,
    prefetched_round: int | None,
    prefetched_values: list[int] | None,
    prefetched_initiative: list[str] | None,
    prefetched_source: str | None,
    prefetched_fallback_reason: str | None,
    prefetched_drand_error: str | None,
    prefetched_rounds_used: list[int] | None,
    prefetched_beacons: list[dict[str, JSONValue]] | None,
    drand_base_url: str,
    dice_roll: DiceRollRecord | None,
    combat_turn_budget: dict[str, JSONValue] | None,
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
                "target": intent_result.target,
                "entry_id": intent_result.entry_id,
                "entry_kind": intent_result.entry_kind,
                "entry_name": intent_result.entry_name,
                "action_category": intent_result.action_category,
                "action_cost": intent_result.action_cost,
                "confidence": intent_result.confidence,
                "provider_used": intent_result.provider_used,
                "is_valid": intent_result.is_valid,
            },
            timestamp=timestamp,
        )
    )

    if (
        intent_result.mechanic == Mechanic.DISENGAGE
        and state.mode == GameMode.COMBAT
        and new_mode == GameMode.EXPLORATION
    ):
        timestamp += 1
        events.append(
            Event(
                event_type="combat_disengaged",
                payload={"intent": intent_result.intent, "from_mode": state.mode},
                timestamp=timestamp,
            )
        )

    timestamp += 1
    transition_payload: dict[str, JSONValue] = {
        "from_mode": state.mode,
        "to_mode": new_mode,
    }
    if combat_turn_budget is not None:
        transition_payload["combat_turn_budget"] = combat_turn_budget
    events.append(
        Event(
            event_type="mode_transition",
            payload=transition_payload,
            timestamp=timestamp,
        )
    )

    if prefetched_values is not None and prefetched_round is not None:
        payload: dict[str, JSONValue] = {
            "round": prefetched_round,
            "initiative_order": prefetched_initiative or ["player", "enemy"],
            "source": prefetched_source or "local",
            "drand_base_url": drand_base_url,
            "rounds_used": prefetched_rounds_used or [],
            "beacons": prefetched_beacons or [],
            "values": list(prefetched_values),
        }
        if prefetched_fallback_reason is not None:
            payload["fallback_reason"] = prefetched_fallback_reason
        if prefetched_drand_error is not None:
            payload["drand_error"] = prefetched_drand_error

        timestamp += 1
        events.append(
            Event(
                event_type="entropy_prefetched",
                payload=payload,
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


def _consume_turn_budget(
    state: GameState,
    intent_result: IntentResult,
) -> tuple[IntentResult, TurnBudget | None]:
    """Apply one deterministic turn-budget consumption for the current input."""
    combat = state.combat
    if combat is None:
        return intent_result, None

    if intent_result.intent == Intent.UNKNOWN:
        return intent_result, combat.turn_budget

    if not intent_result.is_valid:
        return intent_result, combat.turn_budget

    budget = combat.turn_budget
    action_cost = (intent_result.action_cost or "").strip().lower()
    if action_cost in {"action", "bonus_action", "reaction"}:
        return _consume_by_action_cost(
            budget=budget,
            intent_result=intent_result,
            action_cost=action_cost,
        )

    category = intent_result.action_category
    if category == ActionCategory.PRIMARY_ACTION:
        if not can_spend_action(budget):
            return (
                _reject_because_unavailable(
                    intent_result,
                    "primary action budget already spent",
                ),
                budget,
            )
        spent_budget, _ = spend_action(budget)
        return intent_result, spent_budget

    if category == ActionCategory.OBJECT_INTERACTION:
        if not can_use_object_interaction(budget):
            return (
                _reject_because_unavailable(
                    intent_result,
                    "object interaction already used this turn",
                ),
                budget,
            )
        spent_budget, _ = spend_object_interaction(budget)
        return intent_result, spent_budget

    if category == ActionCategory.BRIEF_SPEECH:
        if not can_speak(budget):
            return (
                _reject_because_unavailable(
                    intent_result,
                    "speech already used this turn",
                ),
                budget,
            )
        spent_budget, _ = mark_spoken(budget)
        return intent_result, spent_budget

    if category == ActionCategory.FREE_OBSERVATION:
        return intent_result, budget

    return intent_result, budget


def _reject_because_unavailable(
    intent_result: IntentResult,
    reason: str,
) -> IntentResult:
    rationale = f"{intent_result.rationale}; {reason}"
    return IntentResult(
        intent=intent_result.intent,
        mechanic=Mechanic.CLARIFY,
        confidence=intent_result.confidence,
        rationale=rationale,
        target=intent_result.target,
        entry_id=intent_result.entry_id,
        entry_kind=intent_result.entry_kind,
        entry_name=intent_result.entry_name,
        provider_used=intent_result.provider_used,
        is_valid=False,
        action_category=intent_result.action_category,
        action_cost=intent_result.action_cost,
    )


def _consume_by_action_cost(
    budget: TurnBudget,
    intent_result: IntentResult,
    action_cost: str,
) -> tuple[IntentResult, TurnBudget]:
    if action_cost == "action":
        if not can_spend_action(budget):
            return (
                _reject_because_unavailable(
                    intent_result, "action already spent this turn"
                ),
                budget,
            )
        spent_budget, _ = spend_action(budget)
        return intent_result, spent_budget
    if action_cost == "bonus_action":
        if not can_use_bonus_action(budget):
            return (
                _reject_because_unavailable(
                    intent_result, "bonus action already spent this turn"
                ),
                budget,
            )
        spent_budget, _ = spend_bonus_action(budget)
        return intent_result, spent_budget
    if action_cost == "reaction":
        if not can_use_reaction(budget):
            return (
                _reject_because_unavailable(
                    intent_result, "reaction already spent this turn"
                ),
                budget,
            )
        spent_budget, _ = spend_reaction(budget)
        return intent_result, spent_budget
    return intent_result, budget


def _turn_budget_to_payload(budget: TurnBudget) -> dict[str, JSONValue]:
    return {
        "action": budget.action,
        "bonus_action": budget.bonus_action,
        "reaction": budget.reaction,
        "movement_remaining": budget.movement_remaining,
        "object_interaction": budget.object_interaction,
        "speech": budget.speech,
    }


def _turn_budget_from_payload(raw: object) -> TurnBudget | None:
    if not isinstance(raw, dict):
        return None

    action = raw.get("action")
    bonus_action = raw.get("bonus_action")
    reaction = raw.get("reaction")
    movement_remaining = raw.get("movement_remaining")
    object_interaction = raw.get("object_interaction")
    speech = raw.get("speech")

    if not isinstance(action, bool):
        return None
    if not isinstance(bonus_action, bool):
        return None
    if not isinstance(reaction, bool):
        return None
    if not isinstance(movement_remaining, int):
        return None
    if not isinstance(object_interaction, bool):
        return None
    if not isinstance(speech, bool):
        return None

    return TurnBudget(
        action=action,
        bonus_action=bonus_action,
        reaction=reaction,
        movement_remaining=movement_remaining,
        object_interaction=object_interaction,
        speech=speech,
    )


def _narrative_stub(
    intent_result: IntentResult,
    previous_mode: GameMode,
    new_mode: GameMode,
    dice_roll: DiceRollRecord | None,
) -> str:
    if (
        previous_mode == GameMode.COMBAT
        and new_mode == GameMode.CONTESTED
        and intent_result.intent in {Intent.TALK, Intent.SEARCH}
    ):
        return "Action requires clarification during combat."
    if intent_result.mechanic == Mechanic.DISENGAGE:
        return "You disengage and leave combat."
    if intent_result.mechanic == Mechanic.CLARIFY:
        return "Action is ambiguous. Please clarify your intent."
    if intent_result.mechanic == Mechanic.COMBAT_ROLL and dice_roll is not None:
        return f"Combat roll resolved deterministically: d20={dice_roll.value}."
    if intent_result.mechanic == Mechanic.NARRATE_ONLY:
        return f"Action acknowledged: {intent_result.intent.value}."
    return "No narrative available."


def _prefetch_entropy_values(provider: DiceProvider, count: int) -> list[int]:
    values: list[int] = []
    while len(values) < count:
        entropy = provider.next_u32()
        if roll_d20(entropy) is not None:
            values.append(entropy)
    return values


def _prefetch_entropy_for_round(
    dice_provider: DiceProvider,
    drand_client: DrandHTTPClient | None,
    pool_size: int,
    max_drand_rounds: int,
    drand_base_url: str,
    drand_disabled: bool,
) -> tuple[
    str, list[int], str | None, str | None, list[int], list[dict[str, JSONValue]]
]:
    if drand_disabled:
        local_values = _prefetch_entropy_values(dice_provider, pool_size)
        return "local", local_values, "disabled", None, [], []

    if drand_client is not None:
        try:
            values, rounds_used, beacons = _prefetch_entropy_values_from_drand(
                drand_client=drand_client,
                count=pool_size,
                max_rounds=max_drand_rounds,
            )
            return "drand", values, None, None, rounds_used, beacons
        except DrandClientError as exc:
            local_values = _prefetch_entropy_values(dice_provider, pool_size)
            return (
                "local",
                local_values,
                exc.reason,
                _short_error_message(str(exc)),
                [],
                [],
            )
        except TimeoutError as exc:
            local_values = _prefetch_entropy_values(dice_provider, pool_size)
            return (
                "local",
                local_values,
                "timeout",
                _short_error_message(str(exc)),
                [],
                [],
            )
        except ValueError as exc:
            local_values = _prefetch_entropy_values(dice_provider, pool_size)
            return (
                "local",
                local_values,
                "bad_response",
                _short_error_message(str(exc)),
                [],
                [],
            )
        except Exception as exc:
            # Local fallback is deterministic because chosen u32 values are recorded.
            local_values = _prefetch_entropy_values(dice_provider, pool_size)
            return (
                "local",
                local_values,
                "network_error",
                _short_error_message(str(exc)),
                [],
                [],
            )

    local_values = _prefetch_entropy_values(dice_provider, pool_size)
    return "local", local_values, None, None, [], []


def _prefetch_entropy_values_from_drand(
    drand_client: DrandHTTPClient,
    count: int,
    max_rounds: int,
) -> tuple[list[int], list[int], list[dict[str, JSONValue]]]:
    if max_rounds < 1:
        raise RuntimeError("max_rounds must be >= 1")

    latest = drand_client.latest()
    values: list[int] = []
    rounds_used: list[int] = []
    beacons: list[dict[str, JSONValue]] = []

    for offset in range(max_rounds):
        beacon = latest if offset == 0 else drand_client.by_round(latest.round + offset)
        rounds_used.append(beacon.round)
        beacons.append(_beacon_to_payload(beacon))
        for entropy in _entropy_from_randomness_hex(beacon.randomness):
            if roll_d20(entropy) is not None:
                values.append(entropy)
                if len(values) >= count:
                    return values[:count], rounds_used, beacons

    raise DrandClientError(
        "bad_response", "drand did not yield enough accepted entropy"
    )


def _entropy_from_randomness_hex(randomness_hex: str) -> list[int]:
    try:
        data = bytes.fromhex(randomness_hex)
    except ValueError as exc:
        raise DrandClientError("bad_response", "randomness is not valid hex") from exc
    values: list[int] = []
    for start in range(0, len(data) - 3, 4):
        values.append(int.from_bytes(data[start : start + 4], byteorder="big"))
    return values


def _beacon_to_payload(beacon: DrandBeacon) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {
        "round": beacon.round,
        "randomness": beacon.randomness,
        "signature": beacon.signature,
    }
    return payload


def _parse_int_value(raw: JSONValue) -> int | None:
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _resolve_drand_base_url(config: EngineConfig) -> str:
    if config.drand_base_url:
        return config.drand_base_url
    return os.environ.get("DRAND_BASE_URL", DEFAULT_DRAND_BASE_URL)


def _is_drand_disabled() -> bool:
    raw = os.environ.get("DRAND_DISABLED", "")
    return raw.strip().lower() in {"1", "true"}


def _short_error_message(message: str, limit: int = 120) -> str:
    stripped = " ".join(message.split())
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3] + "..."
