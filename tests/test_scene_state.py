"""Tests for Milestone 7 — Scene State & Environmental Context.

Covers:
- CampaignScene: environment_tags field, lifecycle helpers
- SceneState: environment_tags in narration model
- scene_from_campaign: CampaignScene → SceneState conversion
- set_scene_combat_active: toggle combat_active
- update_scene_combatants: replace combatants_present
- Narrator prompt: environment_tags rendered in Scene section
- Narrator style rule 14 update: references environment_tags
- Campaign persistence: environment_tags round-trip
"""

from __future__ import annotations

from pathlib import Path

from chronicle_weaver_ai.campaign import (
    CampaignScene,
    CampaignState,
    campaign_from_dict,
    campaign_to_dict,
    save_campaign,
    load_campaign,
    scene_from_campaign,
    set_scene_combat_active,
    update_scene_combatants,
)
from chronicle_weaver_ai.memory.context_models import ContextBundle
from chronicle_weaver_ai.narration.models import (
    ActionResult,
    NarrationRequest,
    SceneState,
)
from chronicle_weaver_ai.narration.narrator import build_user_prompt


# ── Helpers ──────────────────────────────────────────────────────────────────


def _scene(
    combat_active: bool = True,
    tags: list[str] | None = None,
) -> CampaignScene:
    return CampaignScene(
        scene_id="scene.dungeon_hall",
        description_stub="A torch-lit stone hall with crumbling pillars.",
        combat_active=combat_active,
        combatants_present=["Fighter", "Goblin"],
        environment_tags=tags or ["dim_light", "stone_floor", "damp"],
    )


def _bundle() -> ContextBundle:
    return ContextBundle(system_text="You are the GM.", items=[], total_tokens_est=5)


def _action() -> ActionResult:
    return ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=14,
        mode_from="combat",
        mode_to="combat",
        resolved_action={
            "action_kind": "attack",
            "entry_name": "Longsword",
            "attack_roll_d20": 14,
            "attack_bonus_total": 6,
            "attack_total": 20,
            "target_armor_class": 13,
            "hit_result": True,
        },
    )


# ── CampaignScene model ─────────────────────────────────────────────────────


def test_campaign_scene_has_environment_tags() -> None:
    """CampaignScene must accept and store environment_tags."""
    scene = _scene()
    assert scene.environment_tags == ["dim_light", "stone_floor", "damp"]


def test_campaign_scene_default_environment_tags_is_empty() -> None:
    """CampaignScene.environment_tags defaults to empty list."""
    scene = CampaignScene(scene_id="s.bare", description_stub="Empty room.")
    assert scene.environment_tags == []


# ── SceneState model ─────────────────────────────────────────────────────────


def test_scene_state_has_environment_tags() -> None:
    """SceneState must accept and store environment_tags."""
    ss = SceneState(
        scene_id="s.test",
        description_stub="A room.",
        combat_active=False,
        environment_tags=["rain", "mud"],
    )
    assert ss.environment_tags == ["rain", "mud"]


def test_scene_state_default_environment_tags_is_empty() -> None:
    """SceneState.environment_tags defaults to empty list."""
    ss = SceneState(scene_id="s.bare", description_stub="A room.", combat_active=False)
    assert ss.environment_tags == []


# ── scene_from_campaign ──────────────────────────────────────────────────────


def test_scene_from_campaign_copies_all_fields() -> None:
    """scene_from_campaign must produce a SceneState with identical fields."""
    cs = _scene()
    ss = scene_from_campaign(cs)
    assert isinstance(ss, SceneState)
    assert ss.scene_id == cs.scene_id
    assert ss.description_stub == cs.description_stub
    assert ss.combat_active == cs.combat_active
    assert ss.combatants_present == cs.combatants_present
    assert ss.environment_tags == cs.environment_tags


def test_scene_from_campaign_with_empty_tags() -> None:
    """scene_from_campaign handles empty environment_tags correctly."""
    cs = CampaignScene(scene_id="s.bare", description_stub="Quiet.")
    ss = scene_from_campaign(cs)
    assert ss.environment_tags == []


# ── set_scene_combat_active ──────────────────────────────────────────────────


def test_set_scene_combat_active_true() -> None:
    scene = CampaignScene(scene_id="s.1", description_stub="Room.")
    updated = set_scene_combat_active(scene, True)
    assert updated.combat_active is True
    assert updated.scene_id == scene.scene_id  # other fields unchanged


def test_set_scene_combat_active_false() -> None:
    scene = _scene(combat_active=True)
    updated = set_scene_combat_active(scene, False)
    assert updated.combat_active is False


def test_set_scene_combat_active_preserves_environment_tags() -> None:
    scene = _scene(tags=["rain"])
    updated = set_scene_combat_active(scene, False)
    assert updated.environment_tags == ["rain"]


# ── update_scene_combatants ──────────────────────────────────────────────────


def test_update_scene_combatants_replaces_list() -> None:
    scene = _scene()
    updated = update_scene_combatants(scene, ["Wizard", "Dragon"])
    assert updated.combatants_present == ["Wizard", "Dragon"]
    assert updated.scene_id == scene.scene_id


def test_update_scene_combatants_to_empty() -> None:
    scene = _scene()
    updated = update_scene_combatants(scene, [])
    assert updated.combatants_present == []


# ── Narrator prompt: environment_tags ────────────────────────────────────────


def test_narrator_prompt_includes_environment_tags() -> None:
    """Environment tags must appear in the Scene section of the narrator prompt."""
    ss = SceneState(
        scene_id="room.cave",
        description_stub="A damp cave.",
        combat_active=True,
        combatants_present=["Fighter"],
        environment_tags=["dim_light", "stalactites"],
    )
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_action(), scene=ss)
    )
    assert "environment: dim_light, stalactites" in prompt


def test_narrator_prompt_omits_environment_when_empty() -> None:
    """When environment_tags is empty, no environment line should appear."""
    ss = SceneState(
        scene_id="room.bare",
        description_stub="An empty room.",
        combat_active=False,
    )
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_action(), scene=ss)
    )
    assert "environment:" not in prompt


def test_narrator_prompt_scene_section_order() -> None:
    """Scene section must appear between Resolved Action and Context Items."""
    ss = SceneState(
        scene_id="room.test",
        description_stub="Test.",
        combat_active=True,
        environment_tags=["test_tag"],
    )
    prompt = build_user_prompt(
        NarrationRequest(context=_bundle(), action=_action(), scene=ss)
    )
    assert prompt.index("Scene:") > prompt.index("Resolved Action:")
    assert prompt.index("Scene:") < prompt.index("Context Items:")


def test_narrator_style_rule_14_references_environment_tags() -> None:
    """Style rule 14 must mention environment_tags as a valid source."""
    prompt = build_user_prompt(NarrationRequest(context=_bundle(), action=_action()))
    assert "environment_tags" in prompt


# ── Campaign persistence: environment_tags round-trip ────────────────────────


def test_scene_environment_tags_survive_dict_round_trip() -> None:
    """environment_tags must survive campaign_to_dict → campaign_from_dict."""
    state = CampaignState(
        campaign_id="c.test",
        campaign_name="Test",
        actors={},
        lorebook_refs=[],
        scenes={
            "s.cave": CampaignScene(
                scene_id="s.cave",
                description_stub="A damp cave.",
                environment_tags=["dim_light", "wet_stone"],
            )
        },
        session_log_refs=[],
    )
    d = campaign_to_dict(state)
    restored = campaign_from_dict(d)
    assert restored.scenes["s.cave"].environment_tags == ["dim_light", "wet_stone"]


def test_scene_environment_tags_survive_file_round_trip(tmp_path: Path) -> None:
    """environment_tags must survive save_campaign → load_campaign to disk."""
    state = CampaignState(
        campaign_id="c.test2",
        campaign_name="Test 2",
        actors={},
        lorebook_refs=[],
        scenes={
            "s.hall": CampaignScene(
                scene_id="s.hall",
                description_stub="A great hall.",
                combat_active=True,
                combatants_present=["Fighter"],
                environment_tags=["torchlight", "stone_pillars", "echo"],
            )
        },
        session_log_refs=[],
    )
    path = tmp_path / "campaign.json"
    save_campaign(state, path)
    loaded = load_campaign(path)
    scene = loaded.scenes["s.hall"]
    assert scene.environment_tags == ["torchlight", "stone_pillars", "echo"]
    assert scene.combat_active is True
    assert scene.combatants_present == ["Fighter"]


def test_scene_without_tags_loads_as_empty_list() -> None:
    """Loading a scene dict without environment_tags must produce empty list."""
    state = campaign_from_dict(
        {
            "campaign_id": "c.old",
            "campaign_name": "Old",
            "actors": {},
            "lorebook_refs": [],
            "scenes": {
                "s.old": {
                    "scene_id": "s.old",
                    "description_stub": "An old room.",
                }
            },
            "session_log_refs": [],
        }
    )
    assert state.scenes["s.old"].environment_tags == []
