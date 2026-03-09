"""Tests for rules-aware narrator prompt sections (Milestone: Rules-aware Narrator v0)."""

from __future__ import annotations

from chronicle_weaver_ai.memory.context_models import ContextBundle
from chronicle_weaver_ai.narration.models import (
    ActionResult,
    EncounterContext,
    NarrationRequest,
    SceneState,
)
from chronicle_weaver_ai.narration.narrator import build_user_prompt


# ── Helpers ───────────────────────────────────────────────────────────────────


def _bundle() -> ContextBundle:
    return ContextBundle(system_text="You are the GM.", items=[], total_tokens_est=5)


def _hit_action(defeated: bool = False, target_hp_after: int = 2) -> ActionResult:
    return ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=17,
        mode_from="combat",
        mode_to="combat",
        resolved_action={
            "action_kind": "attack",
            "entry_name": "Longsword",
            "action_cost": "action",
            "attacker_name": "Sample Fighter",
            "target_name": "Goblin",
            "attack_roll_d20": 17,
            "attack_bonus_total": 6,
            "attack_total": 23,
            "target_armor_class": 13,
            "hit_result": True,
            "damage_formula": "1d8 +3 +1",
            "damage_rolls": [5],
            "damage_modifier_total": 4,
            "damage_total": 9,
            "target_hp_before": 7,
            "target_hp_after": target_hp_after,
            "defeated": defeated,
        },
    )


def _miss_action() -> ActionResult:
    return ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=3,
        mode_from="combat",
        mode_to="combat",
        resolved_action={
            "action_kind": "attack",
            "entry_name": "Longsword",
            "action_cost": "action",
            "attacker_name": "Sample Fighter",
            "target_name": "Goblin",
            "attack_roll_d20": 3,
            "attack_bonus_total": 6,
            "attack_total": 9,
            "target_armor_class": 13,
            "hit_result": False,
        },
    )


def _encounter_ctx(
    attacker_conds: list[str] | None = None,
    target_conds: list[str] | None = None,
) -> EncounterContext:
    return EncounterContext(
        current_round=2,
        acting_combatant="Sample Fighter",
        turn_order=["Sample Fighter", "Goblin", "Sample Wizard"],
        attacker_conditions=attacker_conds or [],
        target_conditions=target_conds or [],
    )


def _scene() -> SceneState:
    return SceneState(
        scene_id="room.dungeon_corridor",
        description_stub="A narrow stone corridor lit by a single torch.",
        combat_active=True,
        combatants_present=["Sample Fighter", "Goblin"],
    )


# ── Target Outcome section ────────────────────────────────────────────────────


def test_prompt_includes_target_outcome_section_on_hit() -> None:
    """A hit with damage and HP fields must produce a Target Outcome: section."""
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_hit_action())
    )

    assert "Target Outcome:" in prompt
    assert "hit_result: true" in prompt
    assert "damage_total: 9" in prompt
    assert "target_hp_before: 7" in prompt
    assert "target_hp_after: 2" in prompt
    assert "defeated: false" in prompt


def test_target_outcome_section_precedes_context_items() -> None:
    """Target Outcome: must appear between Resolved Action: and Context Items:."""
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_hit_action())
    )

    assert prompt.index("Target Outcome:") > prompt.index("Resolved Action:")
    assert prompt.index("Target Outcome:") < prompt.index("Context Items:")


def test_prompt_includes_defeat_state_when_applicable() -> None:
    """defeated=true must appear in Target Outcome: when the target is defeated."""
    prompt = build_user_prompt(
        NarrationRequest(
            context=_bundle(),
            action=_hit_action(defeated=True, target_hp_after=0),
        )
    )

    assert "Target Outcome:" in prompt
    assert "defeated: true" in prompt
    assert "target_hp_after: 0" in prompt


def test_prompt_includes_target_outcome_on_miss_with_no_damage_fields() -> None:
    """A miss shows hit_result: false in Target Outcome but no damage/HP fields."""
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_miss_action())
    )

    assert "Target Outcome:" in prompt
    assert "hit_result: false" in prompt
    # No damage or HP fields when miss
    assert "damage_total:" not in prompt
    assert "target_hp_before:" not in prompt
    assert "target_hp_after:" not in prompt
    assert "defeated:" not in prompt


def test_prompt_omits_target_outcome_when_no_resolved_action() -> None:
    """Without a resolved_action payload there must be no Target Outcome: section."""
    action = ActionResult(
        intent="talk",
        mechanic="narrate_only",
        dice_roll=None,
        mode_from="exploration",
        mode_to="exploration",
    )
    prompt = build_user_prompt(NarrationRequest(context=_bundle(), action=action))
    assert "Target Outcome:" not in prompt


# ── Scene section ─────────────────────────────────────────────────────────────


def test_prompt_includes_scene_section_when_provided() -> None:
    """A SceneState must produce a Scene: section with its fields."""
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_hit_action(), scene=_scene())
    )

    assert "Scene:" in prompt
    assert "scene_id: room.dungeon_corridor" in prompt
    assert "combat_active: true" in prompt
    assert "Sample Fighter" in prompt
    assert "Goblin" in prompt


def test_prompt_omits_scene_section_when_not_provided() -> None:
    """Without a SceneState there must be no Scene: section."""
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_hit_action())
    )
    assert "Scene:" not in prompt


# ── Encounter Context section ─────────────────────────────────────────────────


def test_prompt_includes_encounter_context_when_provided() -> None:
    """An EncounterContext must produce an Encounter Context: section."""
    prompt = build_user_prompt(
        NarrationRequest(
            context=_bundle(),
            action=_hit_action(),
            encounter_context=_encounter_ctx(),
        )
    )

    assert "Encounter Context:" in prompt
    assert "round: 2" in prompt
    assert "acting_combatant: Sample Fighter" in prompt
    assert "Sample Fighter → Goblin → Sample Wizard" in prompt


def test_prompt_omits_encounter_context_when_not_provided() -> None:
    """Without an EncounterContext there must be no Encounter Context: section."""
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_hit_action())
    )
    assert "Encounter Context:" not in prompt


# ── Conditions section ────────────────────────────────────────────────────────


def test_prompt_includes_active_conditions_when_present() -> None:
    """Active conditions on attacker/target must appear in the Conditions: section."""
    prompt = build_user_prompt(
        NarrationRequest(
            context=_bundle(),
            action=_hit_action(),
            encounter_context=_encounter_ctx(
                attacker_conds=["prone (2 rounds remaining)"],
                target_conds=["poisoned (persistent)", "stunned (until end of turn)"],
            ),
        )
    )

    assert "Conditions:" in prompt
    assert "attacker: prone (2 rounds remaining)" in prompt
    assert "target: poisoned (persistent), stunned (until end of turn)" in prompt


def test_prompt_shows_none_when_conditions_are_empty() -> None:
    """When EncounterContext has no conditions, Conditions: section shows (none)."""
    prompt = build_user_prompt(
        NarrationRequest(
            context=_bundle(),
            action=_hit_action(),
            encounter_context=_encounter_ctx(),
        )
    )

    assert "Conditions:" in prompt
    assert "attacker: (none)" in prompt
    assert "target: (none)" in prompt


def test_prompt_omits_conditions_when_no_encounter_context() -> None:
    """Without an EncounterContext there must be no Conditions: section."""
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_hit_action())
    )
    assert "Conditions:" not in prompt


# ── Grounding rules ───────────────────────────────────────────────────────────


def test_prompt_contains_encounter_context_grounding_rule() -> None:
    """Style rule 16 for Encounter Context must always be present."""
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_hit_action())
    )
    assert "Encounter Context shows the current round" in prompt


def test_prompt_contains_conditions_grounding_rule() -> None:
    """Style rule 17 for conditions must always be present."""
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_hit_action())
    )
    assert "do not invent conditions not listed there" in prompt


def test_prompt_contains_no_reinforcements_rule() -> None:
    """Style rule 18 forbidding invented terrain/enemies must always be present."""
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_hit_action())
    )
    assert "Never invent enemy reinforcements" in prompt
