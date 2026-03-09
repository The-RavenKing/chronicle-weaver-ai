"""Tests for the CombatantSnapshot abstraction (Milestone: Combatant Model v0)."""

from __future__ import annotations

from pathlib import Path

from chronicle_weaver_ai.cli import _load_demo_actor, _run_interactive_turn
from chronicle_weaver_ai.compendium import CompendiumStore, MonsterEntry
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.engine import Engine
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.models import (
    Actor,
    CombatState,
    EngineConfig,
    GameMode,
    GameState,
    TurnBudget,
)
from chronicle_weaver_ai.rules import (
    CombatantSnapshot,
    combatant_from_actor,
    combatant_from_monster_entry,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "actors"
FIGHTER_FIXTURE = FIXTURES_DIR / "fighter.json"


def _compendium_store() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


def _goblin_entry(store: CompendiumStore) -> MonsterEntry:
    entry = store.get_by_id("m.goblin")
    assert isinstance(entry, MonsterEntry)
    return entry


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


# ── combatant_from_actor ──────────────────────────────────────────────────────


def test_combatant_from_actor_returns_expected_snapshot_fields() -> None:
    """combatant_from_actor must map all relevant Actor fields to the snapshot."""
    actor = Actor(
        actor_id="pc.fighter.test",
        name="Test Fighter",
        armor_class=16,
        hit_points=28,
        proficiency_bonus=3,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 10, "cha": 10},
        resources={"second_wind_uses": 1},
        equipped_weapon_ids=["w.longsword"],
        feature_ids=["f.second_wind"],
    )
    snap = combatant_from_actor(actor)

    assert isinstance(snap, CombatantSnapshot)
    assert snap.combatant_id == "pc.fighter.test"
    assert snap.display_name == "Test Fighter"
    assert snap.source_type == "actor"
    assert snap.source_id == "pc.fighter.test"
    assert snap.armor_class == 16
    assert snap.hit_points == 28
    assert snap.proficiency_bonus == 3
    assert snap.abilities["str"] == 16
    assert snap.resources["second_wind_uses"] == 1
    assert "w.longsword" in snap.compendium_refs
    assert "f.second_wind" in snap.compendium_refs


# ── combatant_from_monster_entry ─────────────────────────────────────────────


def test_combatant_from_monster_entry_returns_expected_snapshot_fields() -> None:
    """combatant_from_monster_entry must map MonsterEntry fields to the snapshot."""
    store = _compendium_store()
    goblin = _goblin_entry(store)
    snap = combatant_from_monster_entry(goblin)

    assert isinstance(snap, CombatantSnapshot)
    assert snap.combatant_id == "m.goblin"
    assert snap.display_name == "Goblin"
    assert snap.source_type == "monster"
    assert snap.source_id == "m.goblin"
    assert snap.armor_class == 13
    assert snap.hit_points == 7
    assert snap.proficiency_bonus is None
    assert snap.abilities == {
        "str": 8,
        "dex": 14,
        "con": 10,
        "int": 10,
        "wis": 8,
        "cha": 8,
    }
    assert snap.resources == {}
    assert "m.goblin" in snap.compendium_refs
    assert snap.metadata.get("creature_type") == "humanoid"
    assert snap.metadata.get("size") == "small"


# ── Attack resolution wired to combatants ────────────────────────────────────


def test_weapon_attack_resolution_uses_target_combatant_armor_class() -> None:
    """target_armor_class in the resolved payload must come from the target combatant."""
    store = _compendium_store()
    # entropy_pool=[6] → d20=7, attack_total=7+6=13 == goblin AC=13 → HIT
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
    assert resolved.payload["action_kind"] == "attack"
    assert resolved.payload["target_armor_class"] == 13  # from m.goblin, not a constant
    assert resolved.payload["hit_result"] is True


def test_resolved_payload_includes_attacker_and_target_combatant_ids_and_names() -> (
    None
):
    """Resolved weapon attack payload must carry both combatant IDs and display names."""
    store = _compendium_store()
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
    assert resolved.payload["attacker_combatant_id"] == "pc.fighter.sample"
    assert resolved.payload["attacker_name"] == "Sample Fighter"
    assert resolved.payload["target_combatant_id"] == "m.goblin"
    assert resolved.payload["target_name"] == "Goblin"
