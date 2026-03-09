"""Tests for HP application (Milestone: HP Application v0)."""

from __future__ import annotations

from pathlib import Path

from chronicle_weaver_ai.cli import _load_demo_actor, _run_interactive_turn
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
from chronicle_weaver_ai.rules import CombatantSnapshot, apply_damage

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


def _goblin_snap(hp: int = 7) -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id="m.goblin",
        display_name="Goblin",
        source_type="monster",
        source_id="m.goblin",
        armor_class=13,
        hit_points=hp,
    )


# ── apply_damage unit tests ───────────────────────────────────────────────────


def test_damage_reduces_hp() -> None:
    """apply_damage must subtract damage_total from hit_points."""
    snap = _goblin_snap(hp=7)
    result = apply_damage(snap, 4)
    assert result.hit_points == 3
    assert result.combatant_id == snap.combatant_id  # other fields unchanged


def test_hp_floors_at_zero() -> None:
    """apply_damage must not reduce hit_points below zero."""
    snap = _goblin_snap(hp=3)
    result = apply_damage(snap, 10)
    assert result.hit_points == 0


def test_apply_damage_unchanged_when_hp_is_none() -> None:
    """apply_damage must return the snapshot unchanged when hit_points is None."""
    snap = CombatantSnapshot(
        combatant_id="m.unknown",
        display_name="Unknown",
        source_type="monster",
        source_id="m.unknown",
        armor_class=None,
        hit_points=None,
    )
    result = apply_damage(snap, 5)
    assert result is snap


# ── Integration tests: resolved payload ──────────────────────────────────────


def test_defeated_true_when_hp_reaches_zero() -> None:
    """A hit that deals >= HP must set defeated=true and target_hp_after=0."""
    store = _compendium_store()
    # entropy_pool=[6] → d20=7, attack_total=13 == goblin AC 13 → HIT
    # dice_provider entropy=7 → d8=7%8+1=8, damage=8+4=12 > goblin HP 7 → DEFEATED
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
    resolved = next(e for e in events if e.event_type == "resolved_action")
    assert resolved.payload["hit_result"] is True
    assert resolved.payload["target_hp_before"] == 7
    assert resolved.payload["target_hp_after"] == 0
    assert resolved.payload["defeated"] is True


def test_hit_that_does_not_defeat_includes_hp_fields() -> None:
    """A hit that leaves HP > 0 must set defeated=false with correct before/after."""
    store = _compendium_store()
    # entropy_pool=[6] → HIT; dice_provider=1 → d8=1%8+1=2, damage=2+4=6 < 7
    engine = _engine_with_store(store, dice_entropy=(1,))
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
    resolved = next(e for e in events if e.event_type == "resolved_action")
    assert resolved.payload["hit_result"] is True
    assert resolved.payload["target_hp_before"] == 7
    assert resolved.payload["target_hp_after"] == 1  # 7 - 6 = 1
    assert resolved.payload["defeated"] is False


def test_miss_does_not_include_hp_fields() -> None:
    """A miss must not produce target_hp_before, target_hp_after, or defeated."""
    store = _compendium_store()
    # entropy_pool=[42] → d20=3, attack_total=9 < 13 → MISS
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
    resolved = next(e for e in events if e.event_type == "resolved_action")
    assert resolved.payload["hit_result"] is False
    assert "target_hp_before" not in resolved.payload
    assert "target_hp_after" not in resolved.payload
    assert "defeated" not in resolved.payload
