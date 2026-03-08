"""CLI narrate command smoke test with mocked narrator."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from chronicle_weaver_ai.cli import app, narrate as narrate_command
from chronicle_weaver_ai.narration.models import NarrationResponse
from chronicle_weaver_ai.models import Event


class _FakeNarrator:
    provider = "fake"

    def narrate(self, request):  # type: ignore[no-untyped-def]
        assert request.action.intent == "attack"
        return NarrationResponse(
            text="You press forward as the goblin staggers.",
            provider="fake",
            model="fake-model",
        )


def test_cli_narrate_smoke(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"
    captured: dict[str, object] = {}

    events = [
        Event(
            event_type="player_input", payload={"text": "attack goblin"}, timestamp=1
        ),
        Event(
            event_type="intent_resolved",
            payload={"intent": "attack", "mechanic": "combat_roll"},
            timestamp=2,
        ),
        Event(
            event_type="mode_transition",
            payload={"from_mode": "exploration", "to_mode": "combat"},
            timestamp=3,
        ),
        Event(event_type="dice_roll", payload={"value": 15}, timestamp=4),
    ]
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict()))
            handle.write("\n")

    def _fake_get_narrator(
        provider: str, timeout_seconds: int | None = None
    ) -> _FakeNarrator:
        captured["provider"] = provider
        captured["timeout_seconds"] = timeout_seconds
        return _FakeNarrator()

    monkeypatch.setattr("chronicle_weaver_ai.cli.get_narrator", _fake_get_narrator)

    result = runner.invoke(
        app,
        [
            "narrate",
            "--load",
            str(session_path),
            "--provider",
            "auto",
            "--timeout",
            "9",
        ],
    )

    assert result.exit_code == 0
    assert "You press forward as the goblin staggers." in result.stdout
    assert captured["provider"] == "auto"
    assert captured["timeout_seconds"] == 9


def test_cli_narrate_debug_prompt_emits_to_stderr(monkeypatch, tmp_path) -> None:
    session_path = tmp_path / "session.jsonl"
    stderr_lines: list[str] = []

    events = [
        Event(
            event_type="player_input", payload={"text": "attack goblin"}, timestamp=1
        ),
        Event(
            event_type="intent_resolved",
            payload={"intent": "attack", "mechanic": "combat_roll"},
            timestamp=2,
        ),
        Event(
            event_type="mode_transition",
            payload={"from_mode": "exploration", "to_mode": "combat"},
            timestamp=3,
        ),
    ]
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict()))
            handle.write("\n")

    monkeypatch.setattr(
        "chronicle_weaver_ai.cli.get_narrator",
        lambda provider, timeout_seconds=None: _FakeNarrator(),
    )

    def fake_echo(message=None, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("err"):
            stderr_lines.append("" if message is None else str(message))

    monkeypatch.setattr("chronicle_weaver_ai.cli.typer.echo", fake_echo)

    narrate_command(
        load=str(session_path),
        lore=None,
        budget=800,
        query=None,
        provider="auto",
        debug_prompt=True,
        timeout=None,
        k=5,
        graph_depth=1,
        graph_k=10,
    )

    joined = "\n".join(stderr_lines)
    assert "SYSTEM PROMPT:" in joined
    assert "USER PROMPT:" in joined
    assert "Action Result:" in joined
