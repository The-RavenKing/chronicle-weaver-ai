"""Tests for Ollama/OpenAI narrator backend response extraction."""

from __future__ import annotations

from typing import Any

from chronicle_weaver_ai.memory.context_models import ContextBundle
from chronicle_weaver_ai.narration.models import ActionResult, NarrationRequest
from chronicle_weaver_ai.narration.ollama import OllamaNarrator
from chronicle_weaver_ai.narration.openai import OpenAINarrator


def _request() -> NarrationRequest:
    return NarrationRequest(
        context=ContextBundle(
            system_text="You are the GM.", items=[], total_tokens_est=1
        ),
        action=ActionResult(
            intent="attack",
            mechanic="combat_roll",
            dice_roll=11,
            mode_from="exploration",
            mode_to="combat",
        ),
    )


def test_ollama_narrator_extracts_response_field() -> None:
    captured: dict[str, Any] = {}

    def fake_http(
        url: str, payload: dict[str, object], **kwargs: object
    ) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return {"response": "A goblin reels from your strike."}

    narrator = OllamaNarrator(
        http_post_json=fake_http,
        model="llama3",
        timeout_seconds=33,
    )
    response = narrator.narrate(_request())

    assert response.text == "A goblin reels from your strike."
    assert response.provider == "ollama"
    assert captured["url"].endswith("/api/generate")
    assert captured["payload"]["model"] == "llama3"
    assert captured["kwargs"]["timeout_seconds"] == 33


def test_openai_narrator_extracts_chat_content() -> None:
    captured: dict[str, Any] = {}

    def fake_http(
        url: str,
        payload: dict[str, object],
        headers: dict[str, str] | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return {
            "choices": [
                {
                    "message": {
                        "content": "Steel flashes and the cave falls briefly silent."
                    }
                }
            ]
        }

    narrator = OpenAINarrator(
        api_key="test-key",
        http_post_json=fake_http,
        model="gpt-4o-mini",
    )
    response = narrator.narrate(_request())

    assert response.text == "Steel flashes and the cave falls briefly silent."
    assert response.provider == "openai"
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["payload"]["model"] == "gpt-4o-mini"
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_truncates_to_max_sentences() -> None:
    seven_sentences = "One. Two. Three. Four. Five. Six. Seven."

    def fake_http(
        url: str, payload: dict[str, object], **kwargs: object
    ) -> dict[str, object]:
        return {"response": seven_sentences}

    narrator = OllamaNarrator(http_post_json=fake_http, model="llama3")
    response = narrator.narrate(_request())
    assert response.text == "One. Two. Three. Four. Five."
