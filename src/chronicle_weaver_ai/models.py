"""Core deterministic data models for Chronicle Weaver."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class GameMode(str, Enum):
    """High-level game mode controlled by deterministic FSM rules."""

    EXPLORATION = "exploration"
    COMBAT = "combat"
    CONTESTED = "contested"


class Intent(str, Enum):
    """Supported routed intents."""

    ATTACK = "attack"
    TALK = "talk"
    SEARCH = "search"
    DISENGAGE = "disengage"
    UNKNOWN = "unknown"


class Mechanic(str, Enum):
    """Backend mechanic selection; never delegated to an LLM."""

    COMBAT_ROLL = "combat_roll"
    DISENGAGE = "disengage"
    NARRATE_ONLY = "narrate_only"
    CLARIFY = "clarify"


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
    is_valid: bool = True


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
class GameState:
    """Minimal state required for this vertical slice."""

    mode: GameMode = GameMode.EXPLORATION
    turn: int = 0
    logical_time: int = 0
    last_input: str = ""
    last_intent: Intent = Intent.UNKNOWN
    last_mechanic: Mechanic = Mechanic.CLARIFY
    last_roll: int | None = None


@dataclass(frozen=True)
class Event:
    """Serializable event with logical timestamp and payload."""

    event_type: str
    payload: dict[str, object]
    timestamp: int


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
