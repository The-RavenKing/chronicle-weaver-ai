"""Compendium-backed intent recognition and context payload wiring."""

from pathlib import Path

import json

from typer.testing import CliRunner

import chronicle_weaver_ai.cli as cli
from chronicle_weaver_ai.compendium import CompendiumStore
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.engine import Engine
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.models import Event, GameMode, GameState, Intent

from chronicle_weaver_ai.cli import app


def _store_from_core_files() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def test_interpreter_recognizes_long_sword_alias() -> None:
    router = IntentRouter(provider="rules", compendium_store=_store_from_core_files())
    result = router.route(
        "I swing my long sword at the goblin", current_mode=GameMode.EXPLORATION
    )
    assert result.intent == Intent.ATTACK
    assert result.entry_id == "w.longsword"
    assert result.entry_kind == "weapon"
    assert result.entry_name == "Longsword"
    assert result.target == "goblin"


def test_interpreter_recognizes_compendium_weapon_attack() -> None:
    router = IntentRouter(provider="rules", compendium_store=_store_from_core_files())
    result = router.route(
        "I swing my longsword at the goblin", current_mode=GameMode.EXPLORATION
    )
    assert result.intent == Intent.ATTACK
    assert result.entry_id == "w.longsword"
    assert result.entry_kind == "weapon"
    assert result.entry_name == "Longsword"
    assert result.target == "goblin"


def test_interpreter_recognizes_weapon_attack_with_default_store() -> None:
    router = IntentRouter(provider="rules")
    result = router.route(
        "I swing my longsword at the goblin", current_mode=GameMode.EXPLORATION
    )
    assert result.intent == Intent.ATTACK
    assert result.entry_id == "w.longsword"
    assert result.entry_kind == "weapon"
    assert result.entry_name == "Longsword"
    assert result.target == "goblin"


def test_alias_lookup_order_is_deterministic(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "core_5e" / "alpha_blade.json",
        {
            "id": "w.alpha",
            "name": "Alpha Blade",
            "kind": "weapon",
            "description": "First deterministic alias candidate.",
            "tags": ["test"],
            "aliases": ["battle blade"],
            "damage": "1d6",
        },
    )
    _write_json(
        tmp_path / "core_5e" / "beta_blade.json",
        {
            "id": "w.beta",
            "name": "Beta Blade",
            "kind": "weapon",
            "description": "Second deterministic alias candidate.",
            "tags": ["test"],
            "aliases": ["battle blade"],
            "damage": "1d6",
        },
    )
    store = CompendiumStore()
    store.load([tmp_path / "core_5e"])
    router = IntentRouter(provider="rules", compendium_store=store)

    result = router.route(
        "I swing my battle blade at the goblin", current_mode=GameMode.EXPLORATION
    )
    assert result.intent == Intent.ATTACK
    assert result.entry_id == "w.alpha"
    assert result.entry_name == "Alpha Blade"


def test_interpreter_recognizes_compendium_spell_cast() -> None:
    router = IntentRouter(provider="rules", compendium_store=_store_from_core_files())
    result = router.route(
        "I cast magic missile at the goblin", current_mode=GameMode.EXPLORATION
    )
    assert result.intent == Intent.CAST_SPELL
    assert result.entry_id == "s.magic_missile"
    assert result.entry_kind == "spell"
    assert result.entry_name == "Magic Missile"
    assert result.target == "goblin"


def test_interpreter_recognizes_spell_cast_with_default_store() -> None:
    router = IntentRouter(provider="rules")
    result = router.route(
        "I cast magic missile at the goblin", current_mode=GameMode.EXPLORATION
    )
    assert result.intent == Intent.CAST_SPELL
    assert result.entry_id == "s.magic_missile"
    assert result.entry_kind == "spell"
    assert result.entry_name == "Magic Missile"
    assert result.target == "goblin"


def test_interpreter_recognizes_compendium_feature() -> None:
    router = IntentRouter(provider="rules", compendium_store=_store_from_core_files())
    result = router.route("I use second wind", current_mode=GameMode.EXPLORATION)
    assert result.intent == Intent.USE_FEATURE
    assert result.entry_id == "f.second_wind"
    assert result.entry_kind == "feature"
    assert result.entry_name == "Second Wind"
    assert result.target is None


def test_interpreter_recognizes_feature_with_default_store() -> None:
    router = IntentRouter(provider="rules")
    result = router.route("I use second wind", current_mode=GameMode.EXPLORATION)
    assert result.intent == Intent.USE_FEATURE
    assert result.entry_id == "f.second_wind"
    assert result.entry_kind == "feature"
    assert result.entry_name == "Second Wind"
    assert result.target is None


def test_engine_includes_compendium_entry_refs_in_intent_event_payload() -> None:
    engine = Engine(
        event_store=InMemoryEventStore(),
        dice_provider=FixedEntropyDiceProvider((42,)),
        intent_router=IntentRouter(
            provider="rules",
            compendium_store=_store_from_core_files(),
        ),
    )
    _, output = engine.process_input(state=GameState(), text="I use second wind")
    intent_event = next(
        event for event in output.events if event.event_type == "intent_resolved"
    )
    assert intent_event.payload["entry_id"] == "f.second_wind"
    assert intent_event.payload["entry_kind"] == "feature"
    assert intent_event.payload["entry_name"] == "Second Wind"


def test_context_includes_last_compendium_reference(tmp_path) -> None:
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"
    events = [
        Event(
            event_type="player_input",
            payload={"text": "I swing my longsword"},
            timestamp=1,
        ),
        Event(
            event_type="intent_resolved",
            payload={
                "intent": "attack",
                "entry_id": "w.longsword",
                "entry_kind": "weapon",
                "entry_name": "Longsword",
                "mechanic": "combat_roll",
                "action_category": "primary_action",
                "is_valid": True,
                "provider_used": "rules",
                "confidence": 0.95,
            },
            timestamp=2,
        ),
    ]
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict()))
            handle.write("\n")

    cli._compendium_store_cache = None
    result = runner.invoke(
        app, ["context", "--load", str(session_path), "--budget", "500"]
    )
    assert result.exit_code == 0
    assert "Compendium: Weapon: Longsword" in result.stdout
    assert "A versatile one-handed sword with a strong cutting edge." in result.stdout
