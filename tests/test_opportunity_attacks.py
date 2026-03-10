"""Tests for M5 — Opportunity Attacks & Reactions.

Covers:
- Reaction tracking helpers (has_reaction_available, spend_combatant_reaction)
- Reaction restoration on end_turn
- resolve_opportunity_attack for actor and monster reactors
- trigger_opportunity_attacks: engagement, reaction checks, damage application
- Defeated mover detection
"""

from __future__ import annotations


from chronicle_weaver_ai.compendium.models import MonsterAction, MonsterEntry
from chronicle_weaver_ai.compendium.store import CompendiumStore
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.encounter import (
    create_encounter,
    end_turn,
    engage,
    has_reaction_available,
    spend_combatant_reaction,
)
from chronicle_weaver_ai.models import Actor
from chronicle_weaver_ai.rules import (
    OppAttackResult,
    combatant_from_actor,
    combatant_from_monster_entry,
    resolve_opportunity_attack,
    trigger_opportunity_attacks,
)
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _weapon_entry_json() -> dict:
    return {
        "id": "w.longsword",
        "kind": "weapon",
        "name": "Longsword",
        "description": "A versatile blade.",
        "tags": ["weapon", "melee"],
        "damage": "1d8",
        "damage_type": "slashing",
        "attack_ability": "str",
    }


def _monster_entry_json() -> dict:
    return {
        "id": "m.goblin",
        "kind": "monster",
        "name": "Goblin",
        "description": "A small creature.",
        "tags": ["monster"],
        "size": "small",
        "creature_type": "humanoid",
        "armor_class": 13,
        "hit_points": 7,
        "speed": 30,
        "abilities": {"str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8},
        "actions": [
            {
                "name": "Scimitar",
                "attack_bonus": 4,
                "damage_formula": "1d6+2",
                "target_count": 1,
                "damage_type": "slashing",
            }
        ],
        "challenge_rating": "0.25",
    }


def _store() -> CompendiumStore:
    import json
    import tempfile
    from pathlib import Path

    store = CompendiumStore()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "weapon_longsword.json").write_text(
            json.dumps(_weapon_entry_json()), encoding="utf-8"
        )
        (root / "monster_goblin.json").write_text(
            json.dumps(_monster_entry_json()), encoding="utf-8"
        )
        store.load([root])
    return store


def _actor_snap() -> CombatantSnapshot:
    actor = Actor(
        actor_id="hero",
        name="Hero",
        proficiency_bonus=2,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 10, "cha": 10},
        equipped_weapon_ids=["w.longsword"],
        armor_class=16,
        hit_points=20,
        max_hit_points=28,
    )
    return combatant_from_actor(actor)


def _monster_snap() -> CombatantSnapshot:

    entry = MonsterEntry(
        id="m.goblin",
        name="Goblin",
        kind="monster",
        description="A small creature.",
        tags=["monster"],
        size="small",
        creature_type="humanoid",
        armor_class=13,
        hit_points=7,
        speed=30,
        abilities={"str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8},
        actions=[
            MonsterAction(
                name="Scimitar",
                attack_bonus=4,
                damage_formula="1d6+2",
                target_count=1,
                damage_type="slashing",
            )
        ],
        challenge_rating="0.25",
    )
    return combatant_from_monster_entry(entry)


def _two_combatant_encounter():
    actor = _actor_snap()
    monster = _monster_snap()
    provider = FixedEntropyDiceProvider((10, 10, 10, 10, 10))
    return create_encounter("enc.test", [actor, monster], provider)


# ── Reaction tracking ─────────────────────────────────────────────────────────


def test_has_reaction_available_initially_true():
    enc = _two_combatant_encounter()
    assert has_reaction_available(enc, "hero") is True
    assert has_reaction_available(enc, "m.goblin") is True


def test_spend_combatant_reaction_marks_spent():
    enc = _two_combatant_encounter()
    enc = spend_combatant_reaction(enc, "hero")
    assert has_reaction_available(enc, "hero") is False


def test_spend_combatant_reaction_is_idempotent():
    enc = _two_combatant_encounter()
    enc = spend_combatant_reaction(enc, "hero")
    enc2 = spend_combatant_reaction(enc, "hero")
    assert enc2.reactions_spent == enc.reactions_spent


def test_spend_combatant_reaction_does_not_affect_other_combatants():
    enc = _two_combatant_encounter()
    enc = spend_combatant_reaction(enc, "hero")
    assert has_reaction_available(enc, "m.goblin") is True


def test_end_turn_restores_reaction_for_next_combatant():
    enc = _two_combatant_encounter()
    # Spend both reactions
    enc = spend_combatant_reaction(enc, "hero")
    enc = spend_combatant_reaction(enc, "m.goblin")
    assert has_reaction_available(enc, "hero") is False
    assert has_reaction_available(enc, "m.goblin") is False

    # Advance to next combatant — their reaction is restored
    enc = end_turn(enc)
    next_id = enc.turn_order.combatant_ids[enc.turn_order.current_turn_index]
    assert has_reaction_available(enc, next_id) is True
    # The other combatant's reaction is still spent
    prev_ids = [cid for cid in enc.turn_order.combatant_ids if cid != next_id]
    for prev_id in prev_ids:
        assert has_reaction_available(enc, prev_id) is False


# ── resolve_opportunity_attack ────────────────────────────────────────────────


def test_resolve_opp_attack_actor_reactor_hit():
    store = _store()
    actor = _actor_snap()
    monster = _monster_snap()
    # entropy=19 → d20=20 (guaranteed hit), then 5 → damage
    provider = FixedEntropyDiceProvider((19, 5))
    result = resolve_opportunity_attack(actor, monster, store, provider)
    assert isinstance(result, OppAttackResult)
    assert result.reactor_id == "hero"
    assert result.mover_id == "m.goblin"
    assert result.hit is True
    assert result.attack_roll == 20
    # attack_bonus = prof(2) + STR_mod(3) = 5
    assert result.attack_bonus == 5
    assert result.attack_total == 25
    assert result.damage_total > 0
    assert result.updated_mover.hit_points is not None
    assert result.updated_mover.hit_points < 7


def test_resolve_opp_attack_actor_reactor_miss():
    store = _store()
    actor = _actor_snap()
    monster = _monster_snap()
    # entropy=0 → d20=1 (guaranteed miss vs AC 13)
    provider = FixedEntropyDiceProvider((0, 0))
    result = resolve_opportunity_attack(actor, monster, store, provider)
    assert result.hit is False
    assert result.damage_total == 0
    assert result.updated_mover.hit_points == 7  # unchanged


def test_resolve_opp_attack_monster_reactor_hit():
    store = _store()
    monster = _monster_snap()
    actor = _actor_snap()
    # entropy=19 → d20=20 (guaranteed hit), then 5 → damage
    provider = FixedEntropyDiceProvider((19, 5))
    result = resolve_opportunity_attack(monster, actor, store, provider)
    assert result.reactor_id == "m.goblin"
    assert result.mover_id == "hero"
    assert result.hit is True
    assert result.attack_bonus == 4  # goblin Scimitar attack_bonus
    assert result.damage_total > 0


def test_resolve_opp_attack_monster_reactor_miss():
    store = _store()
    monster = _monster_snap()
    actor = _actor_snap()
    # entropy=0 → d20=1, +4 = 5 < AC 16 → miss
    provider = FixedEntropyDiceProvider((0, 0))
    result = resolve_opportunity_attack(monster, actor, store, provider)
    assert result.hit is False
    assert result.damage_total == 0


def test_resolve_opp_attack_no_weapon_in_refs_uses_unarmed_fallback():
    """Actor with no weapon compendium refs falls back to 1d4 unarmed strike."""
    store = _store()
    bare_actor = Actor(
        actor_id="bare",
        name="Bare",
        proficiency_bonus=2,
        abilities={"str": 10, "dex": 10},
        armor_class=10,
        hit_points=10,
    )
    bare_snap = combatant_from_actor(bare_actor)
    monster = _monster_snap()
    provider = FixedEntropyDiceProvider((19, 3))
    result = resolve_opportunity_attack(bare_snap, monster, store, provider)
    assert result.damage_formula == "1d4"
    assert result.hit is True


# ── trigger_opportunity_attacks ───────────────────────────────────────────────


def test_trigger_opp_attacks_no_engagement_returns_empty():
    store = _store()
    enc = _two_combatant_encounter()
    provider = FixedEntropyDiceProvider((19, 5))
    enc2, results = trigger_opportunity_attacks(enc, "hero", store, provider)
    assert results == []
    assert enc2.combatants["m.goblin"].hit_points == 7  # unchanged


def test_trigger_opp_attacks_fires_when_engaged():
    store = _store()
    enc = _two_combatant_encounter()
    enc = engage(enc, "hero", "m.goblin")
    # entropy: d20=20 for monster OA, then damage
    provider = FixedEntropyDiceProvider((19, 5, 5))
    enc2, results = trigger_opportunity_attacks(enc, "hero", store, provider)
    # Monster gets OA against hero (hero is the mover)
    assert len(results) == 1
    assert results[0].reactor_id == "m.goblin"
    assert results[0].mover_id == "hero"


def test_trigger_opp_attacks_reaction_consumed_after_firing():
    store = _store()
    enc = _two_combatant_encounter()
    enc = engage(enc, "hero", "m.goblin")
    provider = FixedEntropyDiceProvider((19, 5))
    enc2, results = trigger_opportunity_attacks(enc, "hero", store, provider)
    assert len(results) == 1
    assert has_reaction_available(enc2, "m.goblin") is False


def test_trigger_opp_attacks_no_reaction_available_skips():
    store = _store()
    enc = _two_combatant_encounter()
    enc = engage(enc, "hero", "m.goblin")
    enc = spend_combatant_reaction(enc, "m.goblin")
    provider = FixedEntropyDiceProvider((19, 5))
    enc2, results = trigger_opportunity_attacks(enc, "hero", store, provider)
    assert results == []


def test_trigger_opp_attacks_hit_applies_damage_to_mover():
    store = _store()
    enc = _two_combatant_encounter()
    enc = engage(enc, "hero", "m.goblin")
    # Goblin OA on hero: d20=20, damage=5
    provider = FixedEntropyDiceProvider((19, 5, 5))
    enc2, results = trigger_opportunity_attacks(enc, "hero", store, provider)
    assert len(results) == 1
    if results[0].hit:
        assert enc2.combatants["hero"].hit_points < enc.combatants["hero"].hit_points


def test_trigger_opp_attacks_miss_does_not_change_mover_hp():
    store = _store()
    enc = _two_combatant_encounter()
    enc = engage(enc, "hero", "m.goblin")
    # d20=1 → miss
    provider = FixedEntropyDiceProvider((0, 0))
    enc2, results = trigger_opportunity_attacks(enc, "hero", store, provider)
    assert len(results) == 1
    assert results[0].hit is False
    assert enc2.combatants["hero"].hit_points == enc.combatants["hero"].hit_points


def test_trigger_opp_attacks_defeated_mover_when_hp_reaches_zero():
    """OA that kills the mover should mark them as defeated."""
    store = _store()
    # Give goblin only 1 HP so any hit kills it
    from dataclasses import replace

    enc = _two_combatant_encounter()
    low_hp_goblin = replace(enc.combatants["m.goblin"], hit_points=1)
    from chronicle_weaver_ai.encounter import update_combatant

    enc = update_combatant(enc, low_hp_goblin)
    enc = engage(enc, "m.goblin", "hero")  # monster is the mover
    # Hero gets OA against goblin: d20=19 → 20+5=25 vs AC 13 → hit
    provider = FixedEntropyDiceProvider((19, 3))
    enc2, results = trigger_opportunity_attacks(enc, "m.goblin", store, provider)
    if results and results[0].hit:
        assert "m.goblin" in enc2.defeated_ids


def test_trigger_opp_attacks_multiple_engaged_enemies():
    """When mover is engaged with two enemies, both may take OA."""
    store = _store()

    actor2 = Actor(
        actor_id="ally",
        name="Ally",
        proficiency_bonus=2,
        abilities={"str": 14, "dex": 10},
        equipped_weapon_ids=["w.longsword"],
        armor_class=14,
        hit_points=20,
        max_hit_points=20,
    )
    ally_snap = combatant_from_actor(actor2)
    monster = _monster_snap()
    hero = _actor_snap()

    provider = FixedEntropyDiceProvider((10, 10, 10, 10, 10))
    from chronicle_weaver_ai.encounter import create_encounter as ce

    enc = ce("enc.multi", [hero, ally_snap, monster], provider)
    # Monster engaged with both hero and ally
    enc = engage(enc, "m.goblin", "hero")
    enc = engage(enc, "m.goblin", "ally")

    # Enough entropy for two OA rolls + damage rolls
    provider2 = FixedEntropyDiceProvider((19, 5, 19, 5, 5, 5))
    enc2, results = trigger_opportunity_attacks(enc, "m.goblin", store, provider2)
    # hero and ally both get OA (both engaged with goblin, goblin is the mover)
    assert len(results) == 2
    reactors = {r.reactor_id for r in results}
    assert "hero" in reactors
    assert "ally" in reactors


def test_trigger_opp_attacks_defeated_reactor_is_skipped():
    store = _store()
    enc = _two_combatant_encounter()
    enc = engage(enc, "hero", "m.goblin")
    from chronicle_weaver_ai.encounter import mark_defeated

    enc = mark_defeated(enc, "m.goblin")
    provider = FixedEntropyDiceProvider((19, 5))
    enc2, results = trigger_opportunity_attacks(enc, "hero", store, provider)
    assert results == []
