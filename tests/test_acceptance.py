"""Acceptance + regression scenario tests — full vertical slice.

Each scenario exercises the complete pipeline without a real LLM:
  interpret → compendium lookup → actor resolution → turn economy
  → action resolution → encounter/combatant updates → narration plumbing

These tests complement the unit tests in test_rules_resolver.py,
test_encounter_state.py, and test_demo_resolution_flow.py by wiring all
layers together in realistic gameplay scenarios.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from chronicle_weaver_ai.campaign import (
    CampaignScene,
    CampaignState,
    load_campaign,
    save_campaign,
)
from chronicle_weaver_ai.compendium import (
    CompendiumStore,
    FeatureEntry,
    SpellEntry,
    WeaponEntry,
)
from chronicle_weaver_ai.dice import (
    FixedEntropyDiceProvider,
    roll_d20_record,
    roll_damage_formula,
)
from chronicle_weaver_ai.encounter import (
    create_encounter,
    get_combatant,
    mark_defeated,
    update_combatant,
)
from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.memory.context_models import ContextBundle
from chronicle_weaver_ai.models import Actor, GameMode, TurnBudget
from chronicle_weaver_ai.narration.models import (
    ActionResult,
    EncounterContext,
    NarrationRequest,
)
from chronicle_weaver_ai.narration.narrator import build_user_prompt
from chronicle_weaver_ai.rules import (
    apply_damage,
    combatant_from_actor,
    combatant_from_monster_entry,
    resolve_feature_use,
    resolve_spell_cast,
    resolve_weapon_attack,
)
from chronicle_weaver_ai.compendium.models import MonsterEntry


# ── Shared fixtures ────────────────────────────────────────────────────────────


def _store() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


def _router(store: CompendiumStore) -> IntentRouter:
    return IntentRouter(provider="rules", compendium_store=store)


def _fighter() -> Actor:
    return Actor(
        actor_id="pc.fighter.acceptance",
        name="Sample Fighter",
        class_name="fighter",
        level=3,
        proficiency_bonus=2,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 10, "cha": 10},
        equipped_weapon_ids=["w.longsword"],
        known_spell_ids=[],
        feature_ids=["f.second_wind"],
        item_ids=[],
        spell_slots={},
        resources={"second_wind_uses": 1},
        armor_class=16,
        hit_points=28,
    )


def _wizard() -> Actor:
    return Actor(
        actor_id="pc.wizard.acceptance",
        name="Sample Wizard",
        class_name="wizard",
        level=3,
        proficiency_bonus=2,
        abilities={"str": 8, "dex": 14, "con": 12, "int": 16, "wis": 12, "cha": 10},
        equipped_weapon_ids=[],
        known_spell_ids=["s.magic_missile"],
        feature_ids=[],
        item_ids=[],
        spell_slots={1: 1},
        resources={},
        armor_class=12,
        hit_points=18,
    )


def _goblin_snap(store: CompendiumStore) -> object:
    entry = store.get_by_id("m.goblin")
    assert isinstance(entry, MonsterEntry)
    return combatant_from_monster_entry(entry)


def _bundle() -> ContextBundle:
    return ContextBundle(system_text="You are the GM.", items=[], total_tokens_est=0)


# ── Scenario 1: Fighter longsword attack against goblin ───────────────────────


def test_scenario_fighter_longsword_attack_hit_defeats_goblin() -> None:
    """Full pipeline: interpret → compendium → resolve → roll → encounter update → narrate."""
    store = _store()
    router = _router(store)
    fighter = _fighter()
    goblin = _goblin_snap(store)

    # ── Interpret ────────────────────────────────────────────────────────────
    intent = router.route(
        text="I attack the goblin with my longsword",
        current_mode=GameMode.COMBAT,
    )
    assert intent.intent.value == "attack"
    assert intent.entry_id == "w.longsword"
    assert intent.entry_kind == "weapon"

    # ── Compendium lookup ─────────────────────────────────────────────────────
    entry = store.get_by_id(intent.entry_id)  # type: ignore[arg-type]
    assert isinstance(entry, WeaponEntry)
    assert entry.id == "w.longsword"

    # ── Actor resolution (no turn budget constraint) ───────────────────────────
    resolved = resolve_weapon_attack(actor=fighter, weapon_entry=entry)
    assert resolved.action_kind == "attack"
    assert resolved.attack_bonus_total == 6  # STR mod +3, prof +2, magic +1
    assert resolved.damage_formula == "1d8 +3 +1"
    assert resolved.action_cost == "action"
    assert resolved.action_available is True  # no budget provided → default True

    # ── Turn economy: with a fresh TurnBudget ─────────────────────────────────
    fresh_budget = TurnBudget()
    resolved_with_budget = resolve_weapon_attack(
        actor=fighter, weapon_entry=entry, turn_budget=fresh_budget
    )
    assert resolved_with_budget.action_available is True

    # Exhaust the action and verify rejection
    spent_budget = replace(fresh_budget, action=False)
    resolved_spent = resolve_weapon_attack(
        actor=fighter, weapon_entry=entry, turn_budget=spent_budget
    )
    assert resolved_spent.action_available is False

    # ── Action resolution: roll attack and damage ─────────────────────────────
    # entropy=19 → d20=20 (guaranteed hit vs goblin AC 13 with +6 bonus)
    # entropy=4  → d8=5   → damage total = 5+3+1 = 9 (defeats goblin HP=7)
    dice = FixedEntropyDiceProvider((19, 4))
    d20_record = roll_d20_record(dice)
    assert d20_record.value == 20

    attack_total = d20_record.value + resolved.attack_bonus_total
    assert attack_total == 26

    assert isinstance(goblin.armor_class, int)  # type: ignore[union-attr]
    hit_result = attack_total >= goblin.armor_class  # type: ignore[union-attr]
    assert hit_result is True

    dmg = roll_damage_formula(resolved.damage_formula, dice)
    assert dmg.damage_total == 9  # d8=5, +3 STR, +1 magic

    # ── Encounter / combatant updates ─────────────────────────────────────────
    fighter_snap = combatant_from_actor(fighter)
    encounter = create_encounter(
        "enc.acceptance.1",
        [fighter_snap, goblin],  # type: ignore[list-item]
        FixedEntropyDiceProvider((10, 5)),
    )

    damaged_goblin = apply_damage(goblin, dmg.damage_total)  # type: ignore[arg-type]
    assert damaged_goblin.hit_points == 0  # 7 − 9 = 0

    encounter = update_combatant(encounter, damaged_goblin)
    encounter = mark_defeated(encounter, goblin.combatant_id)  # type: ignore[union-attr]
    assert goblin.combatant_id in encounter.defeated_ids  # type: ignore[union-attr]
    assert get_combatant(encounter, goblin.combatant_id).hit_points == 0  # type: ignore[union-attr]

    # ── Narration plumbing ────────────────────────────────────────────────────
    resolved_action_payload = {
        "action_kind": "attack",
        "entry_name": "Longsword",
        "action_cost": "action",
        "attack_roll_d20": d20_record.value,
        "attack_bonus_total": resolved.attack_bonus_total,
        "attack_total": attack_total,
        "target_armor_class": goblin.armor_class,  # type: ignore[union-attr]
        "hit_result": True,
        "damage_formula": resolved.damage_formula,
        "damage_rolls": dmg.damage_rolls,
        "damage_modifier_total": dmg.damage_modifier_total,
        "damage_total": dmg.damage_total,
        "target_hp_before": 7,
        "target_hp_after": 0,
        "defeated": True,
    }
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=d20_record.value,
        mode_from="combat",
        mode_to="combat",
        resolved_action=resolved_action_payload,
    )
    enc_ctx = EncounterContext(
        current_round=1,
        acting_combatant="Sample Fighter",
        turn_order=["Sample Fighter", "Goblin"],
    )
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=action, encounter_context=enc_ctx)
    )

    assert "Target Outcome:" in prompt
    assert "hit_result: true" in prompt
    assert "damage_total: 9" in prompt
    assert "target_hp_after: 0" in prompt
    assert "defeated: true" in prompt
    assert "Encounter Context:" in prompt


# ── Scenario 2: Wizard casts Magic Missile against goblin ────────────────────


def test_scenario_wizard_magic_missile_auto_hit() -> None:
    """Full pipeline: interpret → compendium → resolve → slot spend → narrate."""
    store = _store()
    router = _router(store)
    wizard = _wizard()
    goblin = _goblin_snap(store)

    # ── Interpret ────────────────────────────────────────────────────────────
    intent = router.route(
        text="I cast magic missile at the goblin",
        current_mode=GameMode.COMBAT,
    )
    assert intent.intent.value == "cast_spell"
    assert intent.entry_id == "s.magic_missile"
    assert intent.entry_kind == "spell"
    assert intent.target == "goblin"

    # ── Compendium lookup ─────────────────────────────────────────────────────
    entry = store.get_by_id(intent.entry_id)  # type: ignore[arg-type]
    assert isinstance(entry, SpellEntry)
    assert entry.auto_hit is True

    # ── Actor resolution ──────────────────────────────────────────────────────
    resolved = resolve_spell_cast(actor=wizard, spell_entry=entry)
    assert resolved.action_kind == "cast_spell"
    assert resolved.can_cast is True
    assert resolved.auto_hit is True
    assert resolved.slot_level_used == 1
    assert resolved.reason is None
    assert resolved.action_cost == "action"

    # ── Turn economy ──────────────────────────────────────────────────────────
    fresh_budget = TurnBudget()
    resolved_with_budget = resolve_spell_cast(
        actor=wizard, spell_entry=entry, turn_budget=fresh_budget
    )
    assert resolved_with_budget.action_available is True

    # Depleted slot → cannot cast
    wizard_no_slots = replace(wizard, spell_slots={1: 0})
    resolved_no_slots = resolve_spell_cast(actor=wizard_no_slots, spell_entry=entry)
    assert resolved_no_slots.can_cast is False
    assert resolved_no_slots.reason == "no spell slot available"

    # ── Spell slot resource spend ─────────────────────────────────────────────
    spent_wizard = replace(wizard, spell_slots={1: max(0, wizard.spell_slots[1] - 1)})
    assert spent_wizard.spell_slots[1] == 0

    # Second cast attempt fails ────────────────────────────────────────────────
    resolved_second = resolve_spell_cast(actor=spent_wizard, spell_entry=entry)
    assert resolved_second.can_cast is False
    assert resolved_second.reason == "no spell slot available"

    # ── Encounter setup (no dice roll for auto_hit spell) ─────────────────────
    wizard_snap = combatant_from_actor(wizard)
    encounter = create_encounter(
        "enc.acceptance.2",
        [wizard_snap, goblin],  # type: ignore[list-item]
        FixedEntropyDiceProvider((10, 5)),
    )
    assert "pc.wizard.acceptance" in encounter.combatants
    assert goblin.combatant_id in encounter.combatants  # type: ignore[union-attr]

    # ── Narration plumbing ────────────────────────────────────────────────────
    resolved_action_payload = {
        "action_kind": "cast_spell",
        "entry_name": "Magic Missile",
        "action_cost": "action",
        "auto_hit": True,
        "can_cast": True,
        "slot_level_used": 1,
        "effect_summary": resolved.effect_summary,
    }
    action = ActionResult(
        intent="cast_spell",
        mechanic="combat_roll",
        dice_roll=None,
        mode_from="combat",
        mode_to="combat",
        resolved_action=resolved_action_payload,
    )
    prompt = build_user_prompt(NarrationRequest(context=_bundle(), action=action))

    assert "cast_spell" in prompt
    assert "auto_hit: true" in prompt
    assert "If auto_hit=true, do not imply a miss" in prompt


# ── Scenario 3: Fighter Second Wind — success then depleted failure ────────────


def test_scenario_second_wind_success_then_depleted_rejection() -> None:
    """Full pipeline: feature resolve → resource spend → second attempt rejected."""
    store = _store()
    router = _router(store)
    fighter = _fighter()

    # ── Interpret (first use) ─────────────────────────────────────────────────
    intent = router.route(text="I use second wind", current_mode=GameMode.COMBAT)
    assert intent.intent.value == "use_feature"
    assert intent.entry_id == "f.second_wind"
    assert intent.entry_kind == "feature"

    # ── Compendium lookup ─────────────────────────────────────────────────────
    entry = store.get_by_id(intent.entry_id)  # type: ignore[arg-type]
    assert isinstance(entry, FeatureEntry)
    assert entry.usage_key == "second_wind_uses"
    assert entry.action_type == "bonus_action"

    # ── Actor resolution (first use) ──────────────────────────────────────────
    resolved_first = resolve_feature_use(actor=fighter, feature_entry=entry)
    assert resolved_first.can_use is True
    assert resolved_first.remaining_uses == 1
    assert resolved_first.action_cost == "bonus_action"
    assert resolved_first.reason is None

    # ── Turn economy ──────────────────────────────────────────────────────────
    # Bonus action must be available; action is untouched
    fresh_budget = TurnBudget()
    resolved_with_budget = resolve_feature_use(
        actor=fighter, feature_entry=entry, turn_budget=fresh_budget
    )
    assert resolved_with_budget.action_available is True  # bonus_action check
    assert resolved_with_budget.can_use is True

    # ── Resource spend ────────────────────────────────────────────────────────
    usage_key = resolved_first.usage_key
    assert usage_key == "second_wind_uses"
    new_resources = dict(fighter.resources)
    new_resources[usage_key] = max(0, new_resources[usage_key] - 1)
    spent_fighter = replace(fighter, resources=new_resources)
    assert spent_fighter.resources["second_wind_uses"] == 0

    # ── Second use: interpret ─────────────────────────────────────────────────
    intent2 = router.route(text="I use second wind", current_mode=GameMode.COMBAT)
    assert intent2.entry_id == "f.second_wind"

    # ── Action resolution (second use — must fail) ────────────────────────────
    resolved_second = resolve_feature_use(actor=spent_fighter, feature_entry=entry)
    assert resolved_second.can_use is False
    assert resolved_second.remaining_uses == 0
    assert resolved_second.reason == "resource 'second_wind_uses' is depleted"

    # ── Narration plumbing: rejection payload in prompt ───────────────────────
    rejection_payload = {
        "action_kind": "use_feature",
        "entry_name": "Second Wind",
        "action_cost": "bonus_action",
        "can_use": False,
        "reason": resolved_second.reason,
    }
    action = ActionResult(
        intent="use_feature",
        mechanic="clarify",
        dice_roll=None,
        mode_from="combat",
        mode_to="combat",
        resolved_action=rejection_payload,
    )
    prompt = build_user_prompt(NarrationRequest(context=_bundle(), action=action))

    assert "use_feature" in prompt
    assert "Second Wind" in prompt
    # Style rule 12: resolution includes rejection reason → do not narrate success
    assert "If resolution includes a rejection reason, do not narrate success" in prompt


# ── Scenario 4: Save/load round-trip with active encounter ────────────────────


def test_scenario_save_load_active_encounter_with_damaged_combatant(
    tmp_path: Path,
) -> None:
    """Scenario round-trip: encounter with partial damage survives save/load."""
    store = _store()
    fighter = _fighter()

    goblin_entry = store.get_by_id("m.goblin")
    assert isinstance(goblin_entry, MonsterEntry)
    goblin = combatant_from_monster_entry(goblin_entry)
    fighter_snap = combatant_from_actor(fighter)

    # ── Create encounter and apply 5 damage to goblin ─────────────────────────
    encounter = create_encounter(
        "enc.acceptance.persist",
        [fighter_snap, goblin],
        FixedEntropyDiceProvider((10, 5)),
    )
    damaged_goblin = apply_damage(goblin, 5)
    assert damaged_goblin.hit_points == 2  # 7 − 5 = 2
    encounter = update_combatant(encounter, damaged_goblin)

    # Verify pre-save state
    assert get_combatant(encounter, goblin.combatant_id).hit_points == 2
    assert encounter.active is True

    # ── Embed in CampaignState and save ───────────────────────────────────────
    campaign = CampaignState(
        campaign_id="camp.acceptance.persist",
        campaign_name="Acceptance Persistence Test",
        actors={"pc.fighter.acceptance": fighter},
        lorebook_refs=[],
        scenes={
            "scene.test": CampaignScene(
                scene_id="scene.test",
                description_stub="A stone-floored chamber.",
                combat_active=True,
                combatants_present=["Sample Fighter", "Goblin"],
            )
        },
        session_log_refs=[],
        active_encounter_id=encounter.encounter_id,
        encounter_states={encounter.encounter_id: encounter},
    )
    out = tmp_path / "acceptance_campaign.json"
    save_campaign(campaign, out)
    assert out.exists()

    # ── Load and verify ───────────────────────────────────────────────────────
    restored = load_campaign(out)

    assert restored.campaign_id == "camp.acceptance.persist"
    assert restored.active_encounter_id == encounter.encounter_id
    assert encounter.encounter_id in restored.encounter_states

    r_enc = restored.encounter_states[encounter.encounter_id]
    assert r_enc.active is True
    assert r_enc.encounter_id == encounter.encounter_id

    # Combatant HP survives round-trip
    r_goblin = get_combatant(r_enc, goblin.combatant_id)
    assert r_goblin.hit_points == 2  # damaged value preserved

    r_fighter = get_combatant(r_enc, fighter_snap.combatant_id)
    assert r_fighter.hit_points == 28

    # Turn order survives round-trip
    assert r_enc.turn_order.combatant_ids == encounter.turn_order.combatant_ids
    assert r_enc.turn_order.current_round == encounter.turn_order.current_round

    # Actor sheet survives round-trip
    r_actor = restored.actors["pc.fighter.acceptance"]
    assert r_actor.resources["second_wind_uses"] == 1
    assert r_actor.armor_class == 16

    # Scene survives round-trip
    assert "scene.test" in restored.scenes
    assert restored.scenes["scene.test"].combat_active is True
