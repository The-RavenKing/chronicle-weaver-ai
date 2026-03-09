"""Core deterministic data models for Chronicle Weaver."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from collections.abc import Sequence
from typing import Any
from typing import Protocol

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | Sequence["JSONValue"] | dict[str, "JSONValue"]
JSONObject = dict[str, JSONValue]
JSONArray = Sequence["JSONValue"]


class GameMode(str, Enum):
    """High-level game mode controlled by deterministic FSM rules."""

    EXPLORATION = "exploration"
    COMBAT = "combat"
    CONTESTED = "contested"


class Intent(str, Enum):
    """Supported routed intents."""

    ATTACK = "attack"
    CAST_SPELL = "cast_spell"
    USE_ITEM = "use_item"
    USE_FEATURE = "use_feature"
    TALK = "talk"
    SEARCH = "search"
    DISENGAGE = "disengage"
    OBJECT_INTERACTION = "interact"
    UNKNOWN = "unknown"


class Mechanic(str, Enum):
    """Backend mechanic selection; never delegated to an LLM."""

    COMBAT_ROLL = "combat_roll"
    DISENGAGE = "disengage"
    NARRATE_ONLY = "narrate_only"
    CLARIFY = "clarify"


class ActionCategory(str, Enum):
    """High-level action economy bucket used by intent/action handling."""

    PRIMARY_ACTION = "primary_action"
    BRIEF_SPEECH = "brief_speech"
    OBJECT_INTERACTION = "object_interaction"
    FREE_OBSERVATION = "free_observation_note"


@dataclass(frozen=True)
class TurnBudget:
    """Per-combat-turn resource availability and movement allowance."""

    action: bool = True
    bonus_action: bool = True
    reaction: bool = True
    movement_remaining: int = 30
    object_interaction: bool = True
    speech: bool = True


@dataclass(frozen=True)
class Actor:
    """Minimal actor sheet used by deterministic rules resolution."""

    actor_id: str
    name: str
    class_name: str | None = None
    species_name: str | None = None
    level: int = 1
    proficiency_bonus: int = 2
    abilities: dict[str, int] = field(
        default_factory=lambda: {
            "str": 10,
            "dex": 10,
            "con": 10,
            "int": 10,
            "wis": 10,
            "cha": 10,
        }
    )
    equipped_weapon_ids: list[str] = field(default_factory=list)
    known_spell_ids: list[str] = field(default_factory=list)
    feature_ids: list[str] = field(default_factory=list)
    item_ids: list[str] = field(default_factory=list)
    spell_slots: dict[int, int] = field(default_factory=dict)
    resources: dict[str, int] = field(default_factory=dict)
    armor_class: int | None = None
    hit_points: int | None = None
    max_hit_points: int | None = None


def ability_modifier(score: int) -> int:
    """Return standard d20 ability modifier for a raw ability score."""

    return (score - 10) // 2


def can_spend_action(budget: TurnBudget) -> bool:
    """Return whether the action slot is available this turn."""

    return budget.action


def spend_action(budget: TurnBudget) -> tuple[TurnBudget, bool]:
    """Spend a standard action if available."""

    if not can_spend_action(budget):
        return budget, False
    return replace(budget, action=False), True


def can_use_bonus_action(budget: TurnBudget) -> bool:
    """Return whether the bonus action is available this turn."""

    return budget.bonus_action


def spend_bonus_action(budget: TurnBudget) -> tuple[TurnBudget, bool]:
    """Spend a bonus action if available."""

    if not can_use_bonus_action(budget):
        return budget, False
    return replace(budget, bonus_action=False), True


def can_use_reaction(budget: TurnBudget) -> bool:
    """Return whether reaction spending is available this turn."""

    return budget.reaction


def spend_reaction(budget: TurnBudget) -> tuple[TurnBudget, bool]:
    """Spend the reaction if available."""

    if not can_use_reaction(budget):
        return budget, False
    return replace(budget, reaction=False), True


def can_use_object_interaction(budget: TurnBudget) -> bool:
    """Return whether an object interaction can be used this turn."""

    return budget.object_interaction


def spend_object_interaction(budget: TurnBudget) -> tuple[TurnBudget, bool]:
    """Spend object-interaction usage for this turn."""

    if not can_use_object_interaction(budget):
        return budget, False
    return replace(budget, object_interaction=False), True


def can_speak(budget: TurnBudget) -> bool:
    """Return whether a brief speech action is available this turn."""

    return budget.speech


def mark_spoken(budget: TurnBudget) -> tuple[TurnBudget, bool]:
    """Consume one speech opportunity for this turn."""

    if not can_speak(budget):
        return budget, False
    return replace(budget, speech=False), True


def new_turn_budget() -> TurnBudget:
    """Create a fresh combat turn budget."""

    return TurnBudget()


@dataclass(frozen=True)
class PlayerInput:
    """Raw player input wrapper."""

    text: str


@dataclass(frozen=True)
class IntentResult:
    """Intent routing result and validation status."""

    intent: Intent
    mechanic: Mechanic
    confidence: float
    rationale: str
    target: str | None = None
    entry_id: str | None = None
    entry_kind: str | None = None
    entry_name: str | None = None
    provider_used: str = "rules"
    is_valid: bool = True
    action_category: ActionCategory = ActionCategory.PRIMARY_ACTION
    action_cost: str | None = None


@dataclass(frozen=True)
class DiceRollRecord:
    """Recorded d20 roll metadata for deterministic logging."""

    sides: int
    entropy: int
    accepted_entropy: int
    value: int
    attempts: int
    provider: str


@dataclass(frozen=True)
class CombatState:
    """Combat-only sub-state used for deterministic round/turn tracking."""

    round_number: int
    turn_index: int
    initiative_order: list[str] = field(default_factory=list)
    entropy_pool: list[int] = field(default_factory=list)
    entropy_source: str | None = None
    entropy_fallback_reason: str | None = None
    turn_budget: TurnBudget = field(default_factory=new_turn_budget)


@dataclass(frozen=True)
class EngineConfig:
    """Engine runtime configuration for deterministic mechanics."""

    combat_entropy_pool_size: int = 8
    use_drand: bool = True
    drand_base_url: str | None = None
    drand_max_rounds: int = 5
    drand_timeout_seconds: float = 2.0


@dataclass(frozen=True)
class GameState:
    """Minimal state required for this vertical slice."""

    mode: GameMode = GameMode.EXPLORATION
    turn: int = 0
    logical_time: int = 0
    last_input: str = ""
    last_intent: Intent = Intent.UNKNOWN
    last_mechanic: Mechanic = Mechanic.CLARIFY
    last_roll: int | None = None
    combat: CombatState | None = None


@dataclass(frozen=True)
class Event:
    """Serializable event with logical timestamp and payload."""

    event_type: str
    payload: dict[str, JSONValue]
    timestamp: int | float | str | None

    def to_dict(self) -> dict[str, JSONValue]:
        """Convert event to JSON-serializable dict for JSONL storage."""
        return {
            "type": self.event_type,
            "payload": _to_json_value(self.payload),
            "ts": _to_json_value(self.timestamp),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Event:
        """Parse an event from dict payload loaded from JSON."""
        if not isinstance(raw, dict):
            raise ValueError("event must be a JSON object")

        type_raw = raw.get("type", raw.get("event_type"))
        if not isinstance(type_raw, str) or not type_raw:
            raise ValueError("event.type must be a non-empty string")

        payload_raw = raw.get("payload", {})
        if not isinstance(payload_raw, dict):
            raise ValueError("event.payload must be an object")
        payload = _to_json_value(payload_raw)
        if not isinstance(payload, dict):
            raise ValueError("event.payload must be an object")

        ts_raw = raw.get("ts", raw.get("timestamp", 0))
        ts_value = _to_json_value(ts_raw)
        if not isinstance(ts_value, (str, int, float)) and ts_value is not None:
            raise ValueError("event.ts must be string, number, or null")

        return cls(event_type=type_raw, payload=payload, timestamp=ts_value)


@dataclass(frozen=True)
class EngineOutput:
    """Structured output for one processed input."""

    intent: Intent
    mechanic: Mechanic
    previous_mode: GameMode
    new_mode: GameMode
    dice_roll: DiceRollRecord | None
    narrative: str
    events: tuple[Event, ...]


class DiceProvider(Protocol):
    """Entropy source for deterministic dice mapping."""

    source: str

    def next_u32(self) -> int:
        """Return a value in the range [0, 2**32 - 1]."""
        ...


def _to_json_value(value: Any) -> JSONValue:
    """Coerce supported values into JSON-compatible structures."""
    if isinstance(value, Enum):
        return _to_json_value(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_to_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            result[key] = _to_json_value(item)
        return result
    raise ValueError(f"unsupported JSON value type: {type(value).__name__}")
