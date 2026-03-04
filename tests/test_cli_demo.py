"""CLI smoke tests."""

from typer.testing import CliRunner

from chronicle_weaver_ai.cli import app


def test_cli_demo_smoke() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["demo", "--player-input", "attack goblin", "--fixed-entropy", "42"],
    )
    assert result.exit_code == 0
    assert "intent=attack mechanic=combat_roll" in result.stdout
    assert "mode exploration -> combat" in result.stdout
