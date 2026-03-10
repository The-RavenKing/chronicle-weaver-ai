"""Tests for companion NPC autonomous turns."""

from __future__ import annotations

import dataclasses


from chronicle_weaver_ai.companion_turn import CompanionTurnResult, run_companion_turn
from chronicle_weaver_ai.compendium import CompendiumStore, resolve_compendium_roots
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.encounter import (
    EncounterState,
    create_encounter,
    mark_defeated,
)
from chronicle_weaver_ai.models import Actor
from chronicle_weaver_ai.rules.combatant import (
    CombatantSnapshot,
    combatant_from_actor,
    combatant_from_monster_entry,
)

_COMPENDIUM_ROOT = "compendiums"


def _store() -> CompendiumStore:
    store = CompendiumStore()
    try:
        roots = resolve_compendium_roots(_COMPENDIUM_ROOT)
        store.load(roots)
    except Exception:
        pass
    return store


def _companion_actor() -> Actor:
    return Actor(
        actor_id="comp.elara",
        name="Elara",
        level=3,
        proficiency_bonus=2,
        abilities={"str": 14, "dex": 12, "con": 12, "int": 10, "wis": 12, "cha": 10},
        equipped_weapon_ids=["w.longsword"],
        armor_class=16,
        hit_points=20,
        max_hit_points=20,
    )


def _player_actor() -> Actor:
    return Actor(
        actor_id="pc.fighter",
        name="Fighter",
        level=3,
        proficiency_bonus=2,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 10, "cha": 10},
        equipped_weapon_ids=["w.longsword"],
        armor_class=16,
        hit_points=28,
        max_hit_points=28,
    )


def _goblin_snap(store: CompendiumStore) -> CombatantSnapshot:
    from chronicle_weaver_ai.compendium.models import MonsterEntry

    entry = next(
        (e for e in store.entries if isinstance(e, MonsterEntry) and "goblin" in e.id),
        None,
    )
    assert entry is not None, "goblin entry missing from compendium"
    return combatant_from_monster_entry(entry)


def _make_encounter(store: CompendiumStore) -> tuple[EncounterState, Actor, Actor]:
    companion = _companion_actor()
    player = _player_actor()
    goblin = _goblin_snap(store)
    player_snap = combatant_from_actor(player)
    companion_snap = combatant_from_actor(companion, source_type="companion")
    # Deterministic initiative: entropy 0 → goblin goes last (low DEX roll)
    provider = FixedEntropyDiceProvider((19, 0, 10))
    encounter = create_encounter(
        "enc.test", [player_snap, companion_snap, goblin], provider
    )
    return encounter, player, companion


# ── Basic turn execution ──────────────────────────────────────────────────────


def test_companion_attacks_monster() -> None:
    store = _store()
    encounter, player, companion = _make_encounter(store)

    # Force companion to be active
    order = dataclasses.replace(
        encounter.turn_order,
        current_turn_index=encounter.turn_order.combatant_ids.index("comp.elara"),
    )
    encounter = dataclasses.replace(encounter, turn_order=order)

    provider = FixedEntropyDiceProvider((15, 3))  # d20=16, dmg=4
    updated_enc, result = run_companion_turn(encounter, companion, store, provider)

    assert result.skipped_reason is None
    assert result.target_id is not None
    assert result.attack_roll == 16


def test_companion_hit_damages_goblin() -> None:
    store = _store()
    encounter, player, companion = _make_encounter(store)

    order = dataclasses.replace(
        encounter.turn_order,
        current_turn_index=encounter.turn_order.combatant_ids.index("comp.elara"),
    )
    encounter = dataclasses.replace(encounter, turn_order=order)

    # Goblin AC=13; roll=15+attack_bonus(+4)=19 → hit; damage: d8+2 (longsword versatile)
    provider = FixedEntropyDiceProvider((14, 4))  # d20=15 hit, d8=5 → dmg=7
    updated_enc, result = run_companion_turn(encounter, companion, store, provider)

    if result.hit:
        goblin_id = result.target_id
        assert goblin_id is not None
        goblin_after = updated_enc.combatants[goblin_id]
        assert goblin_after.hit_points is not None
        # Goblin HP=7; took some damage
        assert goblin_after.hit_points < 7


def test_companion_skips_when_no_monsters() -> None:
    store = _store()
    encounter, player, companion = _make_encounter(store)

    # Defeat all monsters
    goblin_id = next(
        cid
        for cid, snap in encounter.combatants.items()
        if snap.source_type == "monster"
    )
    encounter = mark_defeated(encounter, goblin_id)

    order = dataclasses.replace(
        encounter.turn_order,
        current_turn_index=encounter.turn_order.combatant_ids.index("comp.elara"),
    )
    encounter = dataclasses.replace(encounter, turn_order=order)

    provider = FixedEntropyDiceProvider((15, 3))
    _, result = run_companion_turn(encounter, companion, store, provider)

    assert result.skipped_reason == "no living monsters"


def test_companion_skips_when_no_weapon() -> None:
    store = _store()
    companion = dataclasses.replace(_companion_actor(), equipped_weapon_ids=[])
    goblin = _goblin_snap(store)
    companion_snap = combatant_from_actor(companion, source_type="companion")
    provider = FixedEntropyDiceProvider((10, 10))
    encounter = create_encounter("enc.test", [companion_snap, goblin], provider)

    order = dataclasses.replace(
        encounter.turn_order,
        current_turn_index=encounter.turn_order.combatant_ids.index("comp.elara"),
    )
    encounter = dataclasses.replace(encounter, turn_order=order)

    _, result = run_companion_turn(encounter, companion, store, provider)
    assert result.skipped_reason == "no equipped weapon"


def test_companion_result_is_immutable() -> None:
    store = _store()
    encounter, player, companion = _make_encounter(store)

    order = dataclasses.replace(
        encounter.turn_order,
        current_turn_index=encounter.turn_order.combatant_ids.index("comp.elara"),
    )
    encounter = dataclasses.replace(encounter, turn_order=order)
    provider = FixedEntropyDiceProvider((15, 3))
    _, result = run_companion_turn(encounter, companion, store, provider)

    assert isinstance(result, CompanionTurnResult)
