"""Deterministic finite state machine transitions."""

from __future__ import annotations

from chronicle_weaver_ai.models import GameMode, Intent, IntentResult, Mechanic


AMBIGUOUS_CONFIDENCE_THRESHOLD = 0.5


def transition(current_mode: GameMode, intent_result: IntentResult) -> GameMode:
    """Return the next game mode from current mode and resolved intent."""
    if current_mode == GameMode.EXPLORATION and intent_result.intent == Intent.ATTACK:
        return GameMode.COMBAT

    if current_mode == GameMode.COMBAT and intent_result.intent == Intent.ATTACK:
        return GameMode.COMBAT

    if current_mode == GameMode.COMBAT and intent_result.intent == Intent.DISENGAGE:
        return GameMode.EXPLORATION

    if current_mode == GameMode.COMBAT and intent_result.intent in {
        Intent.TALK,
        Intent.SEARCH,
    }:
        return GameMode.CONTESTED

    if current_mode == GameMode.CONTESTED:
        if intent_result.intent == Intent.ATTACK:
            return GameMode.COMBAT
        if intent_result.intent == Intent.DISENGAGE:
            return GameMode.EXPLORATION
        if _is_ambiguous(intent_result):
            return GameMode.CONTESTED
        return GameMode.EXPLORATION

    if _is_ambiguous(intent_result):
        return GameMode.CONTESTED

    return current_mode


def _is_ambiguous(intent_result: IntentResult) -> bool:
    return (
        intent_result.mechanic == Mechanic.CLARIFY
        or intent_result.confidence < AMBIGUOUS_CONFIDENCE_THRESHOLD
        or not intent_result.is_valid
    )
