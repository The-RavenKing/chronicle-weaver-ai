"""Demo flow integration tests for actor/resolver wiring."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chronicle_weaver_ai.cli import _load_demo_actor, _run_interactive_turn, app
from chronicle_weaver_ai.compendium import CompendiumStore
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.engine import Engine
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.models import (
    CombatState,
    EngineConfig,
    GameMode,
    GameState,
    TurnBudget,
)
from chronicle_weaver_ai.narration.models import NarrationResponse

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "actors"
FIGHTER_FIXTURE = FIXTURES_DIR / "fighter.json"
WIZARD_FIXTURE = FIXTURES_DIR / "wizard.json"


def _compendium_store() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


def _combat_state() -> GameState:
    return GameState(
        mode=GameMode.COMBAT,
        combat=CombatState(
            round_number=1,
            turn_index=0,
            initiative_order=["player", "enemy"],
            entropy_pool=[42],
            entropy_source="local",
            turn_budget=TurnBudget(),
        ),
    )


def _engine_with_store(store: CompendiumStore) -> Engine:
    return Engine(
        event_store=InMemoryEventStore(),
        dice_provider=FixedEntropyDiceProvider((42,)),
        intent_router=IntentRouter(provider="rules", compendium_store=store),
        config=EngineConfig(use_drand=False, combat_entropy_pool_size=1),
    )


def test_demo_longsword_attack_emits_resolution_and_spends_action() -> None:
    store = _compendium_store()
    engine = _engine_with_store(store)
    actor_state = {"actor": _load_demo_actor(str(FIGHTER_FIXTURE))}

    _run_interactive_turn(
        engine=engine,
        state=_combat_state(),
        text="I swing my longsword at the goblin",
        lore_path=None,
        narrator=None,
        narrator_provider="auto",
        timeout=None,
        auto_narrate=False,
        debug_prompt=False,
        actor_state=actor_state,
        compendium_store=store,
    )

    events = engine.event_store.list_events()
    resolved_action = next(
        event for event in events if event.event_type == "resolved_action"
    )
    assert resolved_action.payload["action_kind"] == "attack"
    assert resolved_action.payload["entry_id"] == "w.longsword"
    assert resolved_action.payload["attack_roll_d20"] == 3
    assert resolved_action.payload["attack_bonus_total"] == 6
    assert resolved_action.payload["attack_total"] == 9
    assert (
        resolved_action.payload["attack_total"]
        == resolved_action.payload["attack_roll_d20"]
        + resolved_action.payload["attack_bonus_total"]
    )
    assert resolved_action.payload["damage_formula"] == "1d8 +3 +1"

    mode_transition = next(
        event for event in reversed(events) if event.event_type == "mode_transition"
    )
    budget = mode_transition.payload.get("combat_turn_budget")
    assert isinstance(budget, dict)
    assert budget.get("action") is False


def test_demo_second_wind_spends_bonus_action_not_action() -> None:
    store = _compendium_store()
    engine = _engine_with_store(store)
    actor_state = {"actor": _load_demo_actor(str(FIGHTER_FIXTURE))}

    state = _run_interactive_turn(
        engine=engine,
        state=_combat_state(),
        text="I use second wind",
        lore_path=None,
        narrator=None,
        narrator_provider="auto",
        timeout=None,
        auto_narrate=False,
        debug_prompt=False,
        actor_state=actor_state,
        compendium_store=store,
    )

    events = engine.event_store.list_events()
    resolved_action = next(
        event for event in events if event.event_type == "resolved_action"
    )
    assert resolved_action.payload["action_kind"] == "use_feature"
    assert resolved_action.payload["action_cost"] == "bonus_action"
    assert resolved_action.payload["can_use"] is True
    assert resolved_action.payload["remaining_uses"] == 1

    mode_transition = next(
        event for event in reversed(events) if event.event_type == "mode_transition"
    )
    budget = mode_transition.payload.get("combat_turn_budget")
    assert isinstance(budget, dict)
    assert budget.get("bonus_action") is False
    assert budget.get("action") is True
    assert state.combat is not None
    assert state.combat.turn_budget.bonus_action is False
    assert state.combat.turn_budget.action is True
    assert actor_state["actor"].resources["second_wind_uses"] == 0


def test_demo_magic_missile_consumes_action_and_slot() -> None:
    store = _compendium_store()
    engine = _engine_with_store(store)
    actor_state = {"actor": _load_demo_actor(str(WIZARD_FIXTURE))}

    _run_interactive_turn(
        engine=engine,
        state=_combat_state(),
        text="I cast magic missile at the goblin",
        lore_path=None,
        narrator=None,
        narrator_provider="auto",
        timeout=None,
        auto_narrate=False,
        debug_prompt=False,
        actor_state=actor_state,
        compendium_store=store,
    )

    events = engine.event_store.list_events()
    resolved_action = next(
        event for event in events if event.event_type == "resolved_action"
    )
    assert resolved_action.payload["action_kind"] == "cast_spell"
    assert resolved_action.payload["action_cost"] == "action"
    assert resolved_action.payload["auto_hit"] is True
    assert resolved_action.payload["can_cast"] is True
    assert resolved_action.payload["slot_level_used"] == 1

    mode_transition = next(
        event for event in reversed(events) if event.event_type == "mode_transition"
    )
    budget = mode_transition.payload.get("combat_turn_budget")
    assert isinstance(budget, dict)
    assert budget.get("action") is False
    assert actor_state["actor"].spell_slots[1] == 0


def test_demo_second_wind_twice_fails_deterministically(monkeypatch) -> None:
    printed: list[str] = []

    def fake_echo(message=None, **kwargs):  # type: ignore[no-untyped-def]
        if not kwargs.get("err"):
            printed.append("" if message is None else str(message))

    monkeypatch.setattr("chronicle_weaver_ai.cli.typer.echo", fake_echo)

    store = _compendium_store()
    engine = _engine_with_store(store)
    actor_state = {"actor": _load_demo_actor(str(FIGHTER_FIXTURE))}
    state = _combat_state()

    state = _run_interactive_turn(
        engine=engine,
        state=state,
        text="I use second wind",
        lore_path=None,
        narrator=None,
        narrator_provider="auto",
        timeout=None,
        auto_narrate=False,
        debug_prompt=False,
        actor_state=actor_state,
        compendium_store=store,
    )
    state = _run_interactive_turn(
        engine=engine,
        state=state,
        text="I use second wind",
        lore_path=None,
        narrator=None,
        narrator_provider="auto",
        timeout=None,
        auto_narrate=False,
        debug_prompt=False,
        actor_state=actor_state,
        compendium_store=store,
    )

    assert any(
        "resolution rejected: resource 'second_wind_uses' is depleted" in line
        for line in printed
    )
    resolved_actions = [
        event
        for event in engine.event_store.list_events()
        if event.event_type == "resolved_action"
    ]
    assert len(resolved_actions) == 2
    assert resolved_actions[1].payload["can_use"] is False
    assert (
        resolved_actions[1].payload["reason"]
        == "resource 'second_wind_uses' is depleted"
    )
    assert actor_state["actor"].resources["second_wind_uses"] == 0


def test_demo_show_resolution_with_actor_option() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "demo",
            "--player-input",
            "I use second wind",
            "--intent-provider",
            "rules",
            "--compendium-root",
            "compendiums",
            "--actor",
            str(FIGHTER_FIXTURE),
            "--show-resolution",
            "--fixed-entropy",
            "42",
        ],
    )
    assert result.exit_code == 0
    assert "resolution {" in result.stdout
    assert '"action_kind": "use_feature"' in result.stdout


def test_rejected_resolution_skips_narrator_invocation() -> None:
    class _CountingNarrator:
        provider = "fake"

        def __init__(self) -> None:
            self.calls = 0

        def narrate(self, request):  # type: ignore[no-untyped-def]
            self.calls += 1
            return NarrationResponse(
                text="Narrator called.",
                provider="fake",
                model="fake-model",
            )

    store = _compendium_store()
    engine = _engine_with_store(store)
    actor_state = {"actor": _load_demo_actor(str(FIGHTER_FIXTURE))}
    narrator = _CountingNarrator()
    state = _combat_state()

    state = _run_interactive_turn(
        engine=engine,
        state=state,
        text="I use second wind",
        lore_path=None,
        narrator=narrator,
        narrator_provider="auto",
        timeout=None,
        auto_narrate=True,
        debug_prompt=False,
        actor_state=actor_state,
        compendium_store=store,
    )
    _run_interactive_turn(
        engine=engine,
        state=state,
        text="I use second wind",
        lore_path=None,
        narrator=narrator,
        narrator_provider="auto",
        timeout=None,
        auto_narrate=True,
        debug_prompt=False,
        actor_state=actor_state,
        compendium_store=store,
    )

    assert narrator.calls == 1


def test_context_includes_resolved_action_summary(tmp_path) -> None:
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"
    events = [
        {
            "type": "intent_resolved",
            "payload": {
                "intent": "attack",
                "mechanic": "combat_roll",
                "entry_id": "w.longsword",
                "entry_kind": "weapon",
                "entry_name": "Longsword",
                "action_category": "primary_action",
                "is_valid": True,
            },
            "ts": 1,
        },
        {
            "type": "resolved_action",
            "payload": {
                "action_kind": "attack",
                "entry_id": "w.longsword",
                "entry_name": "Longsword",
                "action_cost": "action",
                "attack_bonus_total": 6,
                "damage_formula": "1d8 +3 +1",
            },
            "ts": 2,
        },
    ]
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event))
            handle.write("\n")

    result = runner.invoke(
        app, ["context", "--load", str(session_path), "--budget", "700"]
    )
    assert result.exit_code == 0
    assert "Resolved action: attack | Longsword | cost=action" in result.stdout
