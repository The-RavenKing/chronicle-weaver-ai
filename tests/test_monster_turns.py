"""Tests for Monster Turns / Encounter AI v0 (Milestone 2).

Covers:
  - select_monster_action: policy and edge cases
  - run_monster_turn: hit, miss, defeat, no-target
  - initiative ordering: player → goblin → player turn loop
  - defeated monster skipped in end_turn
  - encounter termination after all monsters defeated
  - narration prompt built from MonsterTurnResult payload
"""

from __future__ import annotations

from pathlib import Path


from chronicle_weaver_ai.compendium import CompendiumStore, MonsterEntry
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.encounter import (
    create_encounter,
    current_combatant,
    end_turn,
    get_combatant,
    is_encounter_over,
    mark_defeated,
)
from chronicle_weaver_ai.memory.context_models import ContextBundle
from chronicle_weaver_ai.monster_turn import (
    run_monster_turn,
    select_monster_action,
)
from chronicle_weaver_ai.narration.models import ActionResult, NarrationRequest
from chronicle_weaver_ai.narration.narrator import build_user_prompt
from chronicle_weaver_ai.rules.combatant import (
    CombatantSnapshot,
    combatant_from_monster_entry,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _store() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


def _goblin_entry(store: CompendiumStore) -> MonsterEntry:
    entry = store.get_by_id("m.goblin")
    assert isinstance(entry, MonsterEntry)
    return entry


def _fighter_snap(hp: int = 28, ac: int = 16) -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id="pc.fighter",
        display_name="Sample Fighter",
        source_type="actor",
        source_id="pc.fighter",
        armor_class=ac,
        hit_points=hp,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 10, "cha": 10},
    )


def _goblin_snap(store: CompendiumStore) -> CombatantSnapshot:
    return combatant_from_monster_entry(_goblin_entry(store))


def _encounter_goblin_first(
    store: CompendiumStore, fighter_hp: int = 28, fighter_ac: int = 16
) -> object:
    """Create an encounter where the goblin acts first in initiative.

    entropy=0  → fighter d20=1 (low)
    entropy=19 → goblin  d20=20 (high → goes first)
    """
    fighter = _fighter_snap(hp=fighter_hp, ac=fighter_ac)
    goblin = _goblin_snap(store)
    provider = FixedEntropyDiceProvider((0, 19))
    return create_encounter("enc.test", [fighter, goblin], provider)


def _encounter_fighter_first(
    store: CompendiumStore, fighter_hp: int = 28, fighter_ac: int = 16
) -> object:
    """Create an encounter where the fighter acts first in initiative.

    entropy=19 → fighter d20=20 (high → goes first)
    entropy=5  → goblin  d20=6  (low)
    """
    fighter = _fighter_snap(hp=fighter_hp, ac=fighter_ac)
    goblin = _goblin_snap(store)
    provider = FixedEntropyDiceProvider((19, 5))
    return create_encounter("enc.test", [fighter, goblin], provider)


def _bundle() -> ContextBundle:
    return ContextBundle(system_text="You are the GM.", items=[], total_tokens_est=0)


# ── select_monster_action ─────────────────────────────────────────────────────


def test_select_monster_action_returns_first_action() -> None:
    """select_monster_action must resolve the monster's first action."""
    store = _store()
    goblin_entry = _goblin_entry(store)
    goblin_snap = _goblin_snap(store)
    fighter = _fighter_snap()

    resolved = select_monster_action(goblin_entry, goblin_snap, fighter)

    assert resolved is not None
    assert resolved.action_kind == "monster_attack"
    assert resolved.action_name == "Scimitar"  # first listed action in compendium
    assert resolved.attack_bonus_total == 4
    assert resolved.damage_formula == "1d6 +2"
    assert resolved.target_armor_class == 16


def test_select_monster_action_no_target_returns_none() -> None:
    """select_monster_action returns None when target is None."""
    store = _store()
    goblin_entry = _goblin_entry(store)
    goblin_snap = _goblin_snap(store)

    result = select_monster_action(goblin_entry, goblin_snap, target=None)

    assert result is None


def test_select_monster_action_no_actions_returns_none() -> None:
    """select_monster_action returns None when monster has no actions."""
    store = _store()
    goblin_entry = _goblin_entry(store)
    # Create a stripped-down entry with empty actions list
    import dataclasses

    empty_entry = dataclasses.replace(goblin_entry, actions=[])
    goblin_snap = _goblin_snap(store)
    fighter = _fighter_snap()

    result = select_monster_action(empty_entry, goblin_snap, fighter)

    assert result is None


# ── run_monster_turn: hit scenario ────────────────────────────────────────────


def test_run_monster_turn_on_hit_updates_target_hp() -> None:
    """Monster attack that hits must apply damage and update encounter HP.

    Goblin (attack_bonus=4) vs Fighter (AC=16):
      initiative entropy: 0→fighter d20=1, 19→goblin d20=20 (goblin first)
      attack entropy:    11 → d20=12, attack_total=12+4=16 ≥ 16 → hit
      damage entropy:     5 → d6=(5%6)+1=6, damage_total=6+2=8
    """
    store = _store()
    goblin_entry = _goblin_entry(store)

    # Initiative: goblin first (entropy=0 → fighter d20=1, entropy=19 → goblin d20=20)
    # Then attack: entropy=11 → d20=12 (hit), entropy=5 → d6=6 (damage=8)
    provider = FixedEntropyDiceProvider((0, 19, 11, 5))
    fighter = _fighter_snap(hp=28, ac=16)
    goblin = _goblin_snap(store)
    encounter = create_encounter("enc.test", [fighter, goblin], provider)

    # Goblin should be current combatant
    assert current_combatant(encounter.turn_order) == "m.goblin"

    updated_enc, result = run_monster_turn(encounter, goblin_entry, provider)

    # Attack was made
    assert result.combatant_id == "m.goblin"
    assert result.action_name == "Scimitar"
    assert result.target_id == "pc.fighter"
    assert result.attack_roll == 12
    assert result.attack_total == 16
    assert result.hit is True

    # Damage applied
    assert result.damage_total == 8
    assert result.damage_rolls == [6]
    assert result.target_hp_before == 28
    assert result.target_hp_after == 20
    assert result.target_defeated is False

    # HP reflected in updated encounter
    fighter_after = get_combatant(updated_enc, "pc.fighter")
    assert fighter_after.hit_points == 20
    assert "pc.fighter" not in updated_enc.defeated_ids


def test_run_monster_turn_on_miss_leaves_hp_unchanged() -> None:
    """Monster attack that misses must not change target HP.

    attack entropy: 0 → d20=1, attack_total=1+4=5 < 16 → miss
    """
    store = _store()
    goblin_entry = _goblin_entry(store)

    # Initiative: goblin first; then attack entropy=0 → d20=1 (miss)
    provider = FixedEntropyDiceProvider((0, 19, 0))
    fighter = _fighter_snap(hp=28, ac=16)
    goblin = _goblin_snap(store)
    encounter = create_encounter("enc.test", [fighter, goblin], provider)

    assert current_combatant(encounter.turn_order) == "m.goblin"

    updated_enc, result = run_monster_turn(encounter, goblin_entry, provider)

    assert result.hit is False
    assert result.damage_total is None
    assert result.damage_rolls == []
    assert result.target_hp_before == 28
    assert result.target_hp_after == 28
    assert result.target_defeated is False

    fighter_after = get_combatant(updated_enc, "pc.fighter")
    assert fighter_after.hit_points == 28  # unchanged


def test_run_monster_turn_actor_enters_dying_state_at_zero_hp() -> None:
    """Monster hit that reduces actor to 0 HP puts actor in dying state (not immediately defeated).

    Actors have death saves — they are only defeated after 3 failed saves, not at 0 HP.
    Monsters are immediately defeated when reduced to 0 HP.

    Fighter HP=5, goblin damage=8 on a hit → fighter HP=0 → dying (not yet in defeated_ids).

    attack entropy: 11 → d20=12, attack_total=16 ≥ 16 → hit
    damage entropy:  5 → d6=6, damage_total=8 > 5 → HP=0 → dying
    """
    store = _store()
    goblin_entry = _goblin_entry(store)

    provider = FixedEntropyDiceProvider((0, 19, 11, 5))
    fighter = _fighter_snap(hp=5, ac=16)
    goblin = _goblin_snap(store)
    encounter = create_encounter("enc.test", [fighter, goblin], provider)

    assert current_combatant(encounter.turn_order) == "m.goblin"

    updated_enc, result = run_monster_turn(encounter, goblin_entry, provider)

    assert result.hit is True
    assert result.target_hp_after == 0
    # Actor enters dying state — not immediately defeated
    assert result.target_defeated is False
    assert "pc.fighter" not in updated_enc.defeated_ids
    # HP is 0 in the combatant record
    fighter_after = get_combatant(updated_enc, "pc.fighter")
    assert fighter_after.hit_points == 0


def test_run_monster_turn_no_actor_target_skips_cleanly() -> None:
    """run_monster_turn skips cleanly when all actors are already defeated."""
    store = _store()
    goblin_entry = _goblin_entry(store)

    # Only a monster-vs-monster encounter — no actor targets
    goblin1 = _goblin_snap(store)
    import dataclasses

    goblin2 = dataclasses.replace(
        goblin1,
        combatant_id="m.goblin2",
        display_name="Goblin 2",
        source_id="m.goblin2",
    )
    provider_init = FixedEntropyDiceProvider((10, 5))
    enc = create_encounter("enc.test", [goblin1, goblin2], provider_init)

    provider_turn = FixedEntropyDiceProvider((1,))  # no dice should be consumed
    updated_enc, result = run_monster_turn(enc, goblin_entry, provider_turn)

    assert result.target_id is None
    assert result.resolved_attack is None
    assert result.hit is None
    assert result.target_defeated is False
    # Encounter unchanged
    assert updated_enc.defeated_ids == enc.defeated_ids


# ── Initiative / turn progression ─────────────────────────────────────────────


def test_initiative_player_goblin_player_turn_loop() -> None:
    """Full turn loop: fighter → goblin → fighter (round 2) with correct state."""
    store = _store()
    # Fighter initiative: entropy=19 → d20=20 (goes first)
    # Goblin initiative:  entropy=5  → d20=6  (goes second)
    fighter = _fighter_snap()
    goblin = _goblin_snap(store)
    provider = FixedEntropyDiceProvider((19, 5))
    encounter = create_encounter("enc.test", [fighter, goblin], provider)

    # Round 1, turn 0: fighter's turn
    assert current_combatant(encounter.turn_order) == "pc.fighter"
    assert encounter.turn_order.current_round == 1

    # End fighter's turn → goblin's turn
    encounter = end_turn(encounter)
    assert current_combatant(encounter.turn_order) == "m.goblin"
    assert encounter.turn_order.current_round == 1

    # End goblin's turn → back to fighter (round 2)
    encounter = end_turn(encounter)
    assert current_combatant(encounter.turn_order) == "pc.fighter"
    assert encounter.turn_order.current_round == 2


def test_defeated_monster_is_skipped_by_end_turn() -> None:
    """end_turn must skip a monster that is in defeated_ids."""
    # Three combatants: fighter, goblin1, goblin2 (alphabetical tie-break with equal d20)
    # Use equal initiative entropy so alphabetical tie-break applies
    fighter = CombatantSnapshot(
        combatant_id="a.fighter",  # "a." prefix → first alphabetically
        display_name="Fighter",
        source_type="actor",
        source_id="a.fighter",
        armor_class=16,
        hit_points=28,
        abilities={"dex": 10},
    )
    goblin1 = CombatantSnapshot(
        combatant_id="m.goblin1",
        display_name="Goblin 1",
        source_type="monster",
        source_id="m.goblin1",
        armor_class=13,
        hit_points=7,
        abilities={"dex": 10},
    )
    goblin2 = CombatantSnapshot(
        combatant_id="m.goblin2",
        display_name="Goblin 2",
        source_type="monster",
        source_id="m.goblin2",
        armor_class=13,
        hit_points=7,
        abilities={"dex": 10},
    )
    # Equal entropy → equal d20 → alphabetical: a.fighter < m.goblin1 < m.goblin2
    provider = FixedEntropyDiceProvider((5, 5, 5))
    encounter = create_encounter("enc.test", [fighter, goblin1, goblin2], provider)

    order = encounter.turn_order.combatant_ids
    assert order[0] == "a.fighter"
    assert order[1] == "m.goblin1"
    assert order[2] == "m.goblin2"

    # Defeat goblin1 (index 1)
    encounter = mark_defeated(encounter, "m.goblin1")

    # From fighter's turn, end_turn should skip goblin1 and land on goblin2
    encounter = end_turn(encounter)
    assert current_combatant(encounter.turn_order) == "m.goblin2"


def test_encounter_ends_when_all_monsters_defeated() -> None:
    """is_encounter_over returns True after the only monster is defeated."""
    store = _store()
    encounter = _encounter_goblin_first(store)

    assert is_encounter_over(encounter) is False  # both sides alive

    encounter = mark_defeated(encounter, "m.goblin")

    assert is_encounter_over(encounter) is True


def test_encounter_ends_when_all_actors_defeated() -> None:
    """is_encounter_over returns True after the only actor is defeated."""
    store = _store()
    encounter = _encounter_goblin_first(store)

    encounter = mark_defeated(encounter, "pc.fighter")

    assert is_encounter_over(encounter) is True


# ── Narration prompt for monster turn ─────────────────────────────────────────


def test_narration_prompt_contains_monster_attack_outcome() -> None:
    """Narration prompt built from a monster attack payload must include hit and damage."""
    resolved_payload = {
        "action_kind": "monster_attack",
        "action_name": "Scimitar",
        "attacker_name": "Goblin",
        "attack_roll_d20": 12,
        "attack_bonus_total": 4,
        "attack_total": 16,
        "hit_result": True,
        "damage_formula": "1d6 +2",
        "damage_rolls": [6],
        "damage_modifier_total": 2,
        "damage_total": 8,
        "target_hp_before": 28,
        "target_hp_after": 20,
        "defeated": False,
    }
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=12,
        mode_from="combat",
        mode_to="combat",
        resolved_action=resolved_payload,
    )
    prompt = build_user_prompt(NarrationRequest(context=_bundle(), action=action))

    assert "hit_result: true" in prompt
    assert "damage_total: 8" in prompt
    assert "target_hp_before: 28" in prompt
    assert "target_hp_after: 20" in prompt
    assert "Target Outcome:" in prompt


def test_narration_prompt_for_monster_miss_has_no_damage_fields() -> None:
    """Narration prompt for a miss must not contain damage_total or HP change fields."""
    resolved_payload = {
        "action_kind": "monster_attack",
        "action_name": "Scimitar",
        "attack_roll_d20": 1,
        "attack_bonus_total": 4,
        "attack_total": 5,
        "hit_result": False,
    }
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=1,
        mode_from="combat",
        mode_to="combat",
        resolved_action=resolved_payload,
    )
    prompt = build_user_prompt(NarrationRequest(context=_bundle(), action=action))

    assert "hit_result: false" in prompt
    assert "damage_total" not in prompt
    assert "target_hp_before" not in prompt


# ── Full monster-turn pipeline integration ───────────────────────────────────


def test_full_pipeline_goblin_hits_then_round_advances() -> None:
    """Integrated pipeline: goblin attacks on its turn, then round advances to fighter."""
    store = _store()
    goblin_entry = _goblin_entry(store)

    # Initiative: goblin first (entropy 0→fighter d20=1, 19→goblin d20=20)
    # attack hit: entropy 11 → d20=12, total=16 ≥ 16, hit
    # damage: entropy 5 → d6=6, damage=8
    provider = FixedEntropyDiceProvider((0, 19, 11, 5))
    fighter = _fighter_snap(hp=28, ac=16)
    goblin = _goblin_snap(store)
    encounter = create_encounter("enc.test", [fighter, goblin], provider)

    assert current_combatant(encounter.turn_order) == "m.goblin"

    # Goblin takes its turn
    encounter, result = run_monster_turn(encounter, goblin_entry, provider)
    assert result.hit is True
    assert result.damage_total == 8

    # Fighter HP updated in encounter
    fighter_after = get_combatant(encounter, "pc.fighter")
    assert fighter_after.hit_points == 20

    # Encounter not over (fighter still alive)
    assert is_encounter_over(encounter) is False

    # Advance to fighter's turn (round still 1)
    encounter = end_turn(encounter)
    assert current_combatant(encounter.turn_order) == "pc.fighter"
    assert encounter.turn_order.current_round == 1
