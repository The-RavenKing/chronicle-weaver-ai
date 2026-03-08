"""Tests for narrator provider selection."""

from __future__ import annotations

import pytest

from chronicle_weaver_ai.narration.narrator import (
    DEFAULT_NARRATOR_TIMEOUT_SECONDS,
    get_narrator,
    resolve_timeout_seconds,
)


def _fake_http(*args, **kwargs):  # type: ignore[no-untyped-def]
    return {"response": "ok"}


def test_get_narrator_auto_prefers_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    narrator = get_narrator(provider="auto", http_post_json=_fake_http)
    assert narrator.provider == "openai"


def test_get_narrator_auto_uses_ollama_without_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    narrator = get_narrator(provider="auto", http_post_json=_fake_http)
    assert narrator.provider == "ollama"


def test_get_narrator_auto_errors_when_no_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    with pytest.raises(ValueError, match="No narrator provider available"):
        get_narrator(provider="auto", http_post_json=_fake_http)


def test_resolve_timeout_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NARRATOR_TIMEOUT_SECONDS", raising=False)
    assert resolve_timeout_seconds() == DEFAULT_NARRATOR_TIMEOUT_SECONDS


def test_timeout_env_used_when_cli_override_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARRATOR_TIMEOUT_SECONDS", "45")
    narrator = get_narrator(provider="ollama", http_post_json=_fake_http)
    assert narrator.timeout_seconds == 45


def test_timeout_cli_override_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NARRATOR_TIMEOUT_SECONDS", "45")
    narrator = get_narrator(
        provider="ollama",
        http_post_json=_fake_http,
        timeout_seconds=7,
    )
    assert narrator.timeout_seconds == 7
