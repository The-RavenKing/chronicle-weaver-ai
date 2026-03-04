"""Deterministic intent routing with keyword-first classification."""

from __future__ import annotations

from chronicle_weaver_ai.models import GameMode, Intent, IntentResult, Mechanic


class StubLLMClassifier:
    """Deterministic classifier stub returning structured fallback output."""

    def classify(self, normalized_text: str) -> IntentResult:
        token_count = len(normalized_text.split())
        if not normalized_text or token_count < 2:
            return IntentResult(
                intent=Intent.UNKNOWN,
                mechanic=Mechanic.CLARIFY,
                confidence=0.2,
                rationale="input too short for deterministic routing",
                is_valid=False,
            )
        return IntentResult(
            intent=Intent.UNKNOWN,
            mechanic=Mechanic.CLARIFY,
            confidence=0.3,
            rationale="no keyword route matched",
            is_valid=False,
        )


class IntentRouter:
    """Keyword-first intent router with deterministic fallback stub."""

    def __init__(self, classifier: StubLLMClassifier | None = None) -> None:
        self._classifier = classifier or StubLLMClassifier()

    def route(self, text: str, current_mode: GameMode) -> IntentResult:
        normalized = text.strip().lower()
        keyword_result = self._route_keywords(normalized)
        if keyword_result is None:
            result = self._classifier.classify(normalized)
        else:
            result = keyword_result
        return self._validate(result, current_mode)

    def _route_keywords(self, normalized: str) -> IntentResult | None:
        if not normalized:
            return None

        if "end combat" in normalized:
            return IntentResult(
                intent=Intent.DISENGAGE,
                mechanic=Mechanic.NARRATE_ONLY,
                confidence=0.95,
                rationale="matched keyword: end combat",
            )

        combat_keywords = ("attack", "strike", "hit")
        talk_keywords = ("talk", "speak")
        search_keywords = ("search", "look", "inspect")
        disengage_keywords = ("flee", "run", "escape")

        if _contains_any(normalized, combat_keywords):
            return IntentResult(
                intent=Intent.ATTACK,
                mechanic=Mechanic.COMBAT_ROLL,
                confidence=0.95,
                rationale="matched combat keyword",
            )

        if _contains_any(normalized, talk_keywords):
            return IntentResult(
                intent=Intent.TALK,
                mechanic=Mechanic.NARRATE_ONLY,
                confidence=0.9,
                rationale="matched talk keyword",
            )

        if _contains_any(normalized, search_keywords):
            return IntentResult(
                intent=Intent.SEARCH,
                mechanic=Mechanic.NARRATE_ONLY,
                confidence=0.9,
                rationale="matched search keyword",
            )

        if _contains_any(normalized, disengage_keywords):
            return IntentResult(
                intent=Intent.DISENGAGE,
                mechanic=Mechanic.NARRATE_ONLY,
                confidence=0.9,
                rationale="matched disengage keyword",
            )

        return None

    def _validate(self, result: IntentResult, current_mode: GameMode) -> IntentResult:
        # Minimal validation for this slice: searching during combat becomes contested.
        if current_mode == GameMode.COMBAT and result.intent == Intent.SEARCH:
            return IntentResult(
                intent=result.intent,
                mechanic=Mechanic.CLARIFY,
                confidence=0.4,
                rationale="search during combat needs clarification",
                is_valid=False,
            )
        return result


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
