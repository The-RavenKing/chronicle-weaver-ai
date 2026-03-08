"""Narration request/response models."""

from __future__ import annotations

from dataclasses import dataclass

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
class NarrationRequest:
    """Input to narrator adapters."""

    context: ContextBundle
    action: ActionResult


@dataclass(frozen=True)
class NarrationResponse:
    """Narrator output text and provider metadata."""

    text: str
    provider: str
    model: str
