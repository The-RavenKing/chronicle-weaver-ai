"""Tests for deterministic weapon damage resolution (Milestone: Damage Resolution v0)."""

from __future__ import annotations

from pathlib import Path

from chronicle_weaver_ai.cli import _load_demo_actor, _run_interactive_turn
from chronicle_weaver_ai.compendium import CompendiumStore
from chronicle_weaver_ai.dice import (
    SeededDiceProvider,
    FixedEntropyDiceProvider,
    roll_damage_formula,
)
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

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "actors"
FIGHTER_FIXTURE = FIXTURES_DIR / "fighter.json"


def _compendium_store() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


def _combat_state(entropy_pool: list[int]) -> GameState:
    return GameState(
        mode=GameMode.COMBAT,
        combat=CombatState(
            round_number=1,
            turn_index=0,
            initiative_order=["player", "enemy"],
            entropy_pool=entropy_pool,
            entropy_source="local",
            turn_budget=TurnBudget(),
        ),
    )


def _engine_with_store(
    store: CompendiumStore,
    dice_entropy: tuple[int, ...] = (7,),
) -> Engine:
    return Engine(
        event_store=InMemoryEventStore(),
        dice_provider=FixedEntropyDiceProvider(dice_entropy),
        intent_router=IntentRouter(provider="rules", compendium_store=store),
        config=EngineConfig(use_drand=False, combat_entropy_pool_size=1),
    )


def test_weapon_hit_generates_damage_roll() -> None:
    """A hit (attack_total >= AC) must produce damage_rolls, damage_modifier_total, damage_total."""
    store = _compendium_store()
    # entropy=6 → d20=7, attack_total=7+6=13 == DEFAULT_ENEMY_AC=13 → HIT
    # engine dice_provider entropy=7 → d8 = 7%8+1 = 8
    engine = _engine_with_store(store, dice_entropy=(7,))
    actor_state = {"actor": _load_demo_actor(str(FIGHTER_FIXTURE))}

    _run_interactive_turn(
        engine=engine,
        state=_combat_state(entropy_pool=[6]),
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
    assert resolved_action.payload["hit_result"] is True
    assert resolved_action.payload["target_armor_class"] == 13
    assert "damage_rolls" in resolved_action.payload
    assert "damage_modifier_total" in resolved_action.payload
    assert "damage_total" in resolved_action.payload


def test_weapon_miss_generates_no_damage() -> None:
    """A miss (attack_total < AC) must not produce damage fields."""
    store = _compendium_store()
    # entropy=42 → d20=3, attack_total=3+6=9 < DEFAULT_ENEMY_AC=13 → MISS
    engine = _engine_with_store(store, dice_entropy=(7,))
    actor_state = {"actor": _load_demo_actor(str(FIGHTER_FIXTURE))}

    _run_interactive_turn(
        engine=engine,
        state=_combat_state(entropy_pool=[42]),
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
    assert resolved_action.payload["hit_result"] is False
    assert "damage_rolls" not in resolved_action.payload
    assert "damage_modifier_total" not in resolved_action.payload
    assert "damage_total" not in resolved_action.payload


def test_damage_total_calculated_correctly() -> None:
    """damage_total must equal sum(damage_rolls) + damage_modifier_total."""
    provider = SeededDiceProvider(seed=42)
    result = roll_damage_formula("1d8 +3 +1", provider)

    assert result.damage_modifier_total == 4  # +3 +1
    assert (
        result.damage_total == sum(result.damage_rolls) + result.damage_modifier_total
    )
    assert len(result.damage_rolls) == 1
    assert 1 <= result.damage_rolls[0] <= 8


def test_damage_roll_is_deterministic() -> None:
    """Identical seeds must produce identical damage roll results."""
    result_a = roll_damage_formula("1d8 +3 +1", SeededDiceProvider(seed=99))
    result_b = roll_damage_formula("1d8 +3 +1", SeededDiceProvider(seed=99))

    assert result_a.damage_rolls == result_b.damage_rolls
    assert result_a.damage_modifier_total == result_b.damage_modifier_total
    assert result_a.damage_total == result_b.damage_total
