"""Narration request/response models."""

from __future__ import annotations

from dataclasses import dataclass, field

from chronicle_weaver_ai.memory.context_models import ContextBundle
from chronicle_weaver_ai.models import JSONValue


@dataclass(frozen=True)
class ActionResult:
    """Latest resolved action metadata for narrative rendering only."""

    intent: str
    mechanic: str
    dice_roll: int | None
    mode_from: str | None
    mode_to: str | None
    action_category: str = "primary_action"
    resolved_action: dict[str, JSONValue] | None = None


@dataclass(frozen=True)
class SceneState:
    """Minimal scene context for narrator grounding.

    description_stub is a short, GM-supplied flavour line (never LLM-invented).
    combatants_present contains display names of participants known to be in scene.
    environment_tags are short descriptors (e.g. "dim_light", "rain") the narrator
    may reference for atmosphere.
    """

    scene_id: str
    description_stub: str
    combat_active: bool
    combatants_present: list[str] = field(default_factory=list)
    environment_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EncounterContext:
    """Turn-order and condition snapshot passed to the narrator for grounding.

    attacker_conditions and target_conditions are pre-rendered strings
    (e.g. "prone (2 rounds remaining)") so this model has no dependency on
    the rules package.
    """

    current_round: int
    acting_combatant: str  # display name of the combatant whose turn it is
    turn_order: list[str]  # display names in initiative order, high to low
    attacker_conditions: list[str] = field(default_factory=list)
    target_conditions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NarrationRequest:
    """Input to narrator adapters."""

    context: ContextBundle
    action: ActionResult
    scene: SceneState | None = None
    encounter_context: EncounterContext | None = None


@dataclass(frozen=True)
class NarrationResponse:
    """Narrator output text and provider metadata."""

    text: str
    provider: str
    model: str
