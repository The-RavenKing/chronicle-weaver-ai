"""Intent routing tests."""

import json

from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.models import GameMode, Intent, Mechanic


def test_keyword_attack_routes_to_combat_roll() -> None:
    router = IntentRouter()
    result = router.route("attack goblin", current_mode=GameMode.EXPLORATION)
    assert result.intent == Intent.ATTACK
    assert result.mechanic == Mechanic.COMBAT_ROLL
    assert result.target == "goblin"
    assert result.provider_used == "rules"
    assert result.is_valid is True
    assert result.confidence >= 0.9


def test_keyword_search_routes_to_narrate_only() -> None:
    router = IntentRouter()
    result = router.route("examine the room", current_mode=GameMode.EXPLORATION)
    assert result.intent == Intent.SEARCH
    assert result.mechanic == Mechanic.NARRATE_ONLY
    assert result.target == "room"
    assert result.provider_used == "rules"


def test_flee_routes_to_disengage() -> None:
    router = IntentRouter()
    result = router.route("run away", current_mode=GameMode.COMBAT)
    assert result.intent == Intent.DISENGAGE
    assert result.mechanic == Mechanic.DISENGAGE
    assert result.target is None
    assert result.provider_used == "rules"


def test_end_combat_routes_to_disengage() -> None:
    router = IntentRouter()
    result = router.route("end combat", current_mode=GameMode.COMBAT)
    assert result.intent == Intent.DISENGAGE
    assert result.mechanic == Mechanic.DISENGAGE


def test_unknown_routes_to_clarify() -> None:
    router = IntentRouter(provider="rules")
    result = router.route("???", current_mode=GameMode.EXPLORATION)
    assert result.intent == Intent.UNKNOWN
    assert result.mechanic == Mechanic.CLARIFY


def test_keyword_talk_extracts_target() -> None:
    router = IntentRouter()
    result = router.route("talk to the innkeeper", current_mode=GameMode.EXPLORATION)
    assert result.intent == Intent.TALK
    assert result.mechanic == Mechanic.NARRATE_ONLY
    assert result.target == "innkeeper"
    assert result.provider_used == "rules"


def test_synonym_sentence_attack_routes_with_mid_confidence() -> None:
    router = IntentRouter()
    result = router.route("I lunge at the goblin", current_mode=GameMode.EXPLORATION)
    assert result.intent == Intent.ATTACK
    assert result.target == "goblin"
    assert result.provider_used == "rules"
    assert result.is_valid is True
    assert result.confidence == 0.75


def test_llm_fallback_parses_json_when_rules_unknown(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_http(
        url: str, payload: dict[str, object], **kwargs: object
    ) -> dict[str, object]:
        assert url.endswith("/v1/chat/completions")
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "intent": "attack",
                                "target": "goblin",
                                "confidence": 0.92,
                            }
                        )
                    }
                }
            ]
        }

    router = IntentRouter(provider="auto", http_post_json=fake_http)
    result = router.route(
        "perhaps we should proceed",
        current_mode=GameMode.EXPLORATION,
    )
    assert result.intent == Intent.ATTACK
    assert result.mechanic == Mechanic.COMBAT_ROLL
    assert result.target == "goblin"
    assert result.provider_used == "openai"


def test_llm_invalid_json_falls_back_to_unknown(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_http(
        url: str, payload: dict[str, object], **kwargs: object
    ) -> dict[str, object]:
        return {"choices": [{"message": {"content": "{not-json"}}]}

    router = IntentRouter(provider="openai", http_post_json=fake_http)
    result = router.route(
        "perhaps we should proceed", current_mode=GameMode.EXPLORATION
    )
    assert result.intent == Intent.UNKNOWN
    assert result.mechanic == Mechanic.CLARIFY
    assert result.is_valid is False
    assert result.confidence == 0.1


def test_auto_with_no_llm_provider_returns_none_provider(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    router = IntentRouter(provider="auto")
    result = router.route(
        "perhaps we should proceed", current_mode=GameMode.EXPLORATION
    )
    assert result.intent == Intent.UNKNOWN
    assert result.provider_used == "none"
