"""Tests for narrator prompt formatting."""

from __future__ import annotations

from chronicle_weaver_ai.memory.context_models import ContextBundle, ContextItem
from chronicle_weaver_ai.narration.models import ActionResult, NarrationRequest
from chronicle_weaver_ai.narration.narrator import (
    NON_OUTCOME_RULE,
    build_system_text,
    build_user_prompt,
)


def _request() -> NarrationRequest:
    bundle = ContextBundle(
        system_text="You are the GM.",
        items=[
            ContextItem(
                id="session.summary",
                kind="session",
                text="Session summary: Player intent: attack.",
                priority=60,
                tokens_est=10,
            )
        ],
        total_tokens_est=20,
    )
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=17,
        mode_from="exploration",
        mode_to="combat",
        resolved_action={
            "action_kind": "attack",
            "entry_name": "Longsword",
            "action_cost": "action",
            "attack_roll_d20": 17,
            "attack_bonus_total": 6,
            "attack_total": 23,
            "damage_formula": "1d8 +3 +1",
            "explanation": "Longsword: STR mod +3, proficiency +2, magic +1.",
        },
    )
    return NarrationRequest(context=bundle, action=action)


def test_system_text_contains_non_outcome_rule() -> None:
    system_text = build_system_text(_request())
    assert NON_OUTCOME_RULE in system_text


def test_user_prompt_contains_action_result_and_context_items() -> None:
    prompt = build_user_prompt(_request())
    assert "Action Result:" in prompt
    assert "Narrative Guidance:" in prompt
    assert "Resolved Action:" in prompt
    assert "intent: attack" in prompt
    assert "mechanic: combat_roll" in prompt
    assert "dice_roll: 17" in prompt
    assert "mode_transition: exploration -> combat" in prompt
    assert "entry_name: Longsword" in prompt
    assert "attack_roll_d20: 17" in prompt
    assert "attack_bonus_total: 6" in prompt
    assert "attack_total: 23" in prompt
    assert "damage_formula: 1d8 +3 +1" in prompt
    assert prompt.index("Resolved Action:") < prompt.index("Context Items:")
    assert "Context Items:" in prompt
    assert "Session summary: Player intent: attack." in prompt


def test_user_prompt_strips_internal_metadata_from_context_items() -> None:
    bundle = ContextBundle(
        system_text="You are the GM.",
        items=[
            ContextItem(
                id="retrieved.goblin",
                kind="retrieved",
                text="Retrieved: Entity: goblin (unknown) (score=2.253)",
                priority=45,
                tokens_est=12,
            )
        ],
        total_tokens_est=25,
    )
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=17,
        mode_from="exploration",
        mode_to="combat",
    )
    prompt = build_user_prompt(NarrationRequest(context=bundle, action=action))
    assert "score=" not in prompt
    assert "priority=" not in prompt
    assert "[retrieved]" not in prompt
    assert "Entity: goblin (unknown)" in prompt


def test_prompt_does_not_include_forbidden_terms() -> None:
    bundle = ContextBundle(
        system_text="You are the GM.",
        items=[
            ContextItem(
                id="raw.internal",
                kind="retrieved",
                text="[graph|priority=50|tokens_est=20] Retrieved: Fact: score=2.253, remaining_entropy=7, entropy_source=local",
                priority=45,
                tokens_est=12,
            )
        ],
        total_tokens_est=25,
    )
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=17,
        mode_from="exploration",
        mode_to="combat",
    )
    prompt = build_user_prompt(NarrationRequest(context=bundle, action=action))
    lowered = prompt.lower()
    assert "score=" not in lowered
    assert "tokens_est=" not in lowered
    assert "priority=" not in lowered
    assert "remaining_entropy" not in lowered
    assert "entropy_source" not in lowered


def test_prompt_contains_grounding_rule_for_setting_details() -> None:
    prompt = build_user_prompt(_request())
    assert "Do not invent setting details" in prompt
    assert "Do not introduce new entities, locations, or items." in prompt


def test_prompt_contains_never_invent_die_result_rule() -> None:
    prompt = build_user_prompt(_request())
    assert "Never invent a die result unless explicitly provided." in prompt
    assert "Never infer a die roll from attack_bonus_total." in prompt


def test_prompt_does_not_confuse_attack_bonus_for_roll() -> None:
    bundle = ContextBundle(system_text="You are the GM.", items=[], total_tokens_est=5)
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=None,
        mode_from="combat",
        mode_to="combat",
        resolved_action={
            "action_kind": "attack",
            "entry_name": "Longsword",
            "action_cost": "action",
            "attack_bonus_total": 6,
            "damage_formula": "1d8 +3 +1",
        },
    )
    prompt = build_user_prompt(NarrationRequest(context=bundle, action=action))
    assert "dice_roll: none" in prompt
    assert "dice_roll: 6" not in prompt
    assert "attack_bonus_total: 6" in prompt


def test_magic_missile_auto_hit_prompt_grounding() -> None:
    bundle = ContextBundle(
        system_text="You are the GM.",
        items=[],
        total_tokens_est=5,
    )
    action = ActionResult(
        intent="cast_spell",
        mechanic="combat_roll",
        dice_roll=None,
        mode_from="exploration",
        mode_to="combat",
        resolved_action={
            "action_kind": "cast_spell",
            "entry_name": "Magic Missile",
            "action_cost": "action",
            "auto_hit": True,
            "effect_summary": "Create three force darts that automatically hit targets.",
        },
    )
    prompt = build_user_prompt(NarrationRequest(context=bundle, action=action))
    assert "auto_hit: true" in prompt
    assert "If auto_hit=true, do not imply a miss or failed connection." in prompt


def test_relation_rendering_converts_graph_syntax_to_plain_text() -> None:
    bundle = ContextBundle(
        system_text="You are the GM.",
        items=[
            ContextItem(
                id="graph.goblins",
                kind="graph",
                text="Graph neighbors (depth=1):\n- player --attacked--> goblin",
                priority=50,
                tokens_est=20,
            )
        ],
        total_tokens_est=20,
    )
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=17,
        mode_from="exploration",
        mode_to="combat",
    )
    prompt = build_user_prompt(NarrationRequest(context=bundle, action=action))
    assert "The player has attacked the goblin." in prompt
    assert "--attacked-->" not in prompt
    assert "- -" not in prompt
