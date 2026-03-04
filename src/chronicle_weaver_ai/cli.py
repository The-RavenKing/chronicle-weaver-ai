"""Typer CLI for deterministic Chronicle Weaver demo flow."""

from __future__ import annotations

import typer

from chronicle_weaver_ai.dice import (
    FixedEntropyDiceProvider,
    LocalCSPRNGDiceProvider,
    SeededDiceProvider,
)
from chronicle_weaver_ai.engine import Engine
from chronicle_weaver_ai.models import DiceProvider, GameState

app = typer.Typer(add_completion=False, help="Chronicle Weaver deterministic CLI.")


@app.callback()
def main() -> None:
    """CLI root callback."""


@app.command()
def demo(
    player_input: str | None = typer.Option(
        None, "--player-input", help="Free text action."
    ),
    seed: int | None = typer.Option(
        None, "--seed", help="Seed deterministic provider for repeatable runs."
    ),
    fixed_entropy: int | None = typer.Option(
        None, "--fixed-entropy", help="Single fixed u32 entropy sample for testing."
    ),
) -> None:
    """Run one deterministic vertical-slice turn."""
    if seed is not None and fixed_entropy is not None:
        raise typer.BadParameter("Use either --seed or --fixed-entropy, not both.")

    provider: DiceProvider
    if fixed_entropy is not None:
        provider = FixedEntropyDiceProvider((fixed_entropy,))
    elif seed is not None:
        provider = SeededDiceProvider(seed)
    else:
        provider = LocalCSPRNGDiceProvider()

    engine = Engine(dice_provider=provider)
    state = GameState()

    if player_input is not None:
        _print_turn(engine=engine, state=state, text=player_input)
        return

    typer.echo("Chronicle Weaver demo. Type 'exit' to quit.")
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        normalized = line.strip()
        if not normalized:
            continue
        if normalized.lower() in {"exit", "quit"}:
            break
        state = _print_turn(engine=engine, state=state, text=normalized)


def _print_turn(engine: Engine, state: GameState, text: str) -> GameState:
    new_state, output = engine.process_input(state=state, text=text)
    typer.echo(f"intent={output.intent.value} mechanic={output.mechanic.value}")
    if output.dice_roll is not None:
        typer.echo(
            "dice "
            f"value={output.dice_roll.value} "
            f"attempts={output.dice_roll.attempts} "
            f"provider={output.dice_roll.provider}"
        )
    else:
        typer.echo("dice none")
    typer.echo(f"mode {output.previous_mode.value} -> {new_state.mode.value}")
    typer.echo(f"narrative {output.narrative}")
    return new_state


if __name__ == "__main__":
    app()
