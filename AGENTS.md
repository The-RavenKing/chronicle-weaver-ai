# AI RPG Engine – Agent Rules (AGENTS.md)

## Non-negotiable rule
LLMs generate words, not outcomes. The LLM may never:
- roll dice
- change game state
- decide mechanics outcomes
- advance time
- write to persistence directly

## Architecture
- Deterministic backend owns: state machine, mechanics, dice, time, persistence, validation.
- LLM layer: intent classification (structured JSON) + narrative text only.

## Workflow
- Always do: PLAN → IMPLEMENT → TEST → SUMMARY.
- Never create files not listed in the approved file manifest.
- Keep changes small and runnable.

## Tech choices (bootstrap)
- Python 3.12
- CLI: Typer
- Tests: pytest
- Lint: ruff
- Format: black
- Types: mypy (light)
- Persistence: in-memory EventStore interface first
- drand: client stub only for now; local CSPRNG is initial implementation