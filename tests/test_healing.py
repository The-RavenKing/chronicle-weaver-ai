"""Tests for Milestone 3 — Healing & Resource Restoration.

Covers:
- apply_healing() core semantics (cap, floor, None passthrough)
- Second Wind feature end-to-end: resource depletion, HP change, payload fields
- Narration prompt grounding for healing outcomes
- Interaction with max_hit_points on Actor and CombatantSnapshot
"""

from __future__ import annotations

import dataclasses


from pathlib import Path

from chronicle_weaver_ai.compendium import CompendiumStore
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.models import Actor
from chronicle_weaver_ai.rules import apply_healing
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot
from chronicle_weaver_ai.narration.models import ActionResult, NarrationRequest
from chronicle_weaver_ai.narration.narrator import build_user_prompt
from chronicle_weaver_ai.memory.context_models import ContextBundle


# ── Helpers ────────────────────────────────────────────────────────────────────


def _snap(hp: int, max_hp: int | None = None) -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id="pc.fighter",
        display_name="Fighter",
        source_type="actor",
        source_id="pc.fighter",
        armor_class=16,
        hit_points=hp,
        max_hit_points=max_hp,
    )


def _store() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


def _fighter(hp: int = 20, max_hp: int = 28) -> Actor:
    return Actor(
        actor_id="pc.fighter",
        name="Fighter",
        class_name="fighter",
        level=3,
        proficiency_bonus=2,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 10, "cha": 10},
        equipped_weapon_ids=["w.longsword"],
        feature_ids=["f.second_wind"],
        resources={"second_wind_uses": 1},
        armor_class=16,
        hit_points=hp,
        max_hit_points=max_hp,
    )


def _context_bundle() -> ContextBundle:
    return ContextBundle(
        system_text="You are a narrator.", items=[], total_tokens_est=0
    )


# ── apply_healing — core semantics ─────────────────────────────────────────────


def test_apply_healing_increases_hp() -> None:
    """apply_healing must add healing_amount to hit_points."""
    snap = _snap(hp=10, max_hp=28)
    result = apply_healing(snap, 8)
    assert result.hit_points == 18


def test_apply_healing_caps_at_max_hit_points() -> None:
    """apply_healing must not exceed max_hit_points."""
    snap = _snap(hp=25, max_hp=28)
    result = apply_healing(snap, 10)
    assert result.hit_points == 28


def test_apply_healing_exact_full_heal() -> None:
    """apply_healing fills exactly to max when healing matches the deficit."""
    snap = _snap(hp=18, max_hp=28)
    result = apply_healing(snap, 10)
    assert result.hit_points == 28


def test_apply_healing_zero_amount_is_noop() -> None:
    """apply_healing with zero amount leaves HP unchanged."""
    snap = _snap(hp=10, max_hp=28)
    result = apply_healing(snap, 0)
    assert result.hit_points == 10


def test_apply_healing_negative_amount_is_noop() -> None:
    """apply_healing with negative amount is treated as zero — no HP reduction."""
    snap = _snap(hp=10, max_hp=28)
    result = apply_healing(snap, -5)
    assert result.hit_points == 10


def test_apply_healing_no_max_hp_allows_overheal() -> None:
    """When max_hit_points is None, healing is uncapped."""
    snap = _snap(hp=10, max_hp=None)
    result = apply_healing(snap, 100)
    assert result.hit_points == 110


def test_apply_healing_none_hp_returns_unchanged() -> None:
    """apply_healing must return the snapshot unchanged when hit_points is None."""
    snap = CombatantSnapshot(
        combatant_id="x",
        display_name="X",
        source_type="monster",
        source_id="x",
        armor_class=None,
        hit_points=None,
        max_hit_points=None,
    )
    result = apply_healing(snap, 5)
    assert result.hit_points is None


def test_apply_healing_at_full_hp_is_noop() -> None:
    """Healing a fully-healed combatant must leave HP at max."""
    snap = _snap(hp=28, max_hp=28)
    result = apply_healing(snap, 5)
    assert result.hit_points == 28


def test_apply_healing_does_not_affect_other_fields() -> None:
    """apply_healing must only modify hit_points; all other fields unchanged."""
    snap = _snap(hp=10, max_hp=28)
    result = apply_healing(snap, 5)
    assert result.combatant_id == snap.combatant_id
    assert result.armor_class == snap.armor_class
    assert result.max_hit_points == snap.max_hit_points


# ── Second Wind feature entry ──────────────────────────────────────────────────


def test_second_wind_feature_has_healing_formula() -> None:
    """Second Wind compendium entry must have healing_formula set."""
    from chronicle_weaver_ai.compendium.models import FeatureEntry

    store = _store()
    entry = store.get_by_id("f.second_wind")
    assert isinstance(entry, FeatureEntry)
    assert entry.healing_formula == "1d10"
    assert entry.healing_level_bonus is True


# ── Second Wind end-to-end via CLI enricher ────────────────────────────────────


def test_second_wind_enriches_payload_with_healing_fields() -> None:
    """_enrich_feature_use_with_healing must add healing fields to payload."""
    from chronicle_weaver_ai.cli import _enrich_feature_use_with_healing

    store = _store()
    actor = _fighter(hp=20, max_hp=28)
    # entropy=4 → d10=(4%10)+1=5; level bonus=3 → healing_total=8
    provider = FixedEntropyDiceProvider((4,))
    payload: dict = {
        "action_kind": "use_feature",
        "entry_id": "f.second_wind",
        "can_use": True,
    }
    _enrich_feature_use_with_healing(payload, actor, provider, store)

    assert "healing_total" in payload
    assert isinstance(payload["healing_total"], int)
    assert payload["healing_total"] >= 1  # at minimum 1d10(1) + 3 = 4
    assert "healing_rolls" in payload
    assert "healing_modifier_total" in payload
    assert payload["self_hp_before"] == 20
    assert payload["self_hp_after"] == min(28, 20 + payload["healing_total"])


def test_second_wind_enricher_skips_when_can_use_false() -> None:
    """Enricher must not add healing fields if can_use is False."""
    from chronicle_weaver_ai.cli import _enrich_feature_use_with_healing

    store = _store()
    actor = _fighter()
    provider = FixedEntropyDiceProvider((4,))
    payload: dict = {
        "action_kind": "use_feature",
        "entry_id": "f.second_wind",
        "can_use": False,
    }
    _enrich_feature_use_with_healing(payload, actor, provider, store)
    assert "healing_total" not in payload


def test_second_wind_enricher_skips_non_healing_features() -> None:
    """Enricher must not add healing fields for features without healing_formula."""
    from chronicle_weaver_ai.cli import _enrich_feature_use_with_healing

    store = _store()
    actor = _fighter()
    provider = FixedEntropyDiceProvider((4,))
    # Weapon entry used as wrong kind — should be a no-op
    payload: dict = {
        "action_kind": "use_feature",
        "entry_id": "w.longsword",
        "can_use": True,
    }
    _enrich_feature_use_with_healing(payload, actor, provider, store)
    assert "healing_total" not in payload


def test_second_wind_healing_capped_at_max_hp() -> None:
    """Enricher self_hp_after must not exceed actor.max_hit_points."""
    from chronicle_weaver_ai.cli import _enrich_feature_use_with_healing

    store = _store()
    # Fighter at near-full HP; even a small heal should cap at max
    actor = _fighter(hp=27, max_hp=28)
    provider = FixedEntropyDiceProvider((9,))  # d10=10 → total=10+3=13 → capped at 28
    payload: dict = {
        "action_kind": "use_feature",
        "entry_id": "f.second_wind",
        "can_use": True,
    }
    _enrich_feature_use_with_healing(payload, actor, provider, store)
    assert payload["self_hp_after"] == 28


def test_second_wind_resource_consumed_and_hp_applied() -> None:
    """_apply_actor_resource_spend must decrement second_wind_uses and apply HP."""
    from chronicle_weaver_ai.cli import _apply_actor_resource_spend

    actor = _fighter(hp=20, max_hp=28)
    payload = {
        "action_kind": "use_feature",
        "can_use": True,
        "usage_key": "second_wind_uses",
        "healing_total": 8,
    }
    updated = _apply_actor_resource_spend(actor, payload)

    assert updated.resources["second_wind_uses"] == 0
    assert updated.hit_points == 28  # 20 + 8 = 28, at max


def test_second_wind_resource_hp_caps_at_max() -> None:
    """HP after resource spend must cap at max_hit_points."""
    from chronicle_weaver_ai.cli import _apply_actor_resource_spend

    actor = _fighter(hp=25, max_hp=28)
    payload = {
        "action_kind": "use_feature",
        "can_use": True,
        "usage_key": "second_wind_uses",
        "healing_total": 10,
    }
    updated = _apply_actor_resource_spend(actor, payload)
    assert updated.hit_points == 28  # 25 + 10 would be 35; capped at 28


def test_second_wind_depleted_cannot_be_used_again() -> None:
    """After second_wind_uses reaches 0, resolve_feature_use must reject the action."""
    from chronicle_weaver_ai.rules import resolve_feature_use
    from chronicle_weaver_ai.compendium.models import FeatureEntry

    store = _store()
    entry = store.get_by_id("f.second_wind")
    assert isinstance(entry, FeatureEntry)

    actor_depleted = _fighter()
    actor_depleted = dataclasses.replace(
        actor_depleted, resources={"second_wind_uses": 0}
    )
    resolved = resolve_feature_use(actor_depleted, entry)

    assert resolved.can_use is False
    assert resolved.reason is not None
    assert "depleted" in resolved.reason.lower()


# ── Narration grounding for healing ───────────────────────────────────────────


def test_narration_prompt_contains_healing_outcome_section() -> None:
    """build_user_prompt must include Healing Outcome section when healing_total present."""
    action = ActionResult(
        intent="use_feature",
        mechanic="narrate_only",
        dice_roll=None,
        mode_from="combat",
        mode_to="combat",
        resolved_action={
            "action_kind": "use_feature",
            "entry_name": "Second Wind",
            "can_use": True,
            "healing_total": 8,
            "self_hp_before": 20,
            "self_hp_after": 28,
        },
    )
    request = NarrationRequest(context=_context_bundle(), action=action)
    prompt = build_user_prompt(request)

    assert "Healing Outcome:" in prompt
    assert "healing_total: 8" in prompt
    assert "self_hp_before: 20" in prompt
    assert "self_hp_after: 28" in prompt


def test_narration_prompt_no_healing_section_when_absent() -> None:
    """build_user_prompt must not include Healing Outcome when no healing fields present."""
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=15,
        mode_from="combat",
        mode_to="combat",
        resolved_action={
            "action_kind": "attack",
            "entry_name": "Longsword",
            "hit_result": True,
            "damage_total": 9,
        },
    )
    request = NarrationRequest(context=_context_bundle(), action=action)
    prompt = build_user_prompt(request)

    assert "Healing Outcome:" not in prompt


def test_narration_prompt_contains_healing_style_rule() -> None:
    """Style rule 11d must be present in the prompt."""
    action = ActionResult(
        intent="use_feature",
        mechanic="narrate_only",
        dice_roll=None,
        mode_from="combat",
        mode_to="combat",
    )
    request = NarrationRequest(context=_context_bundle(), action=action)
    prompt = build_user_prompt(request)
    assert "healing_total" in prompt and "11d" in prompt


def test_narration_resolved_action_includes_healing_fields() -> None:
    """Healing fields must appear in the Resolved Action section of the prompt."""
    action = ActionResult(
        intent="use_feature",
        mechanic="narrate_only",
        dice_roll=None,
        mode_from="combat",
        mode_to="combat",
        resolved_action={
            "action_kind": "use_feature",
            "entry_name": "Second Wind",
            "healing_formula": "1d10 +3",
            "healing_rolls": [7],
            "healing_modifier_total": 3,
            "healing_total": 10,
        },
    )
    request = NarrationRequest(context=_context_bundle(), action=action)
    prompt = build_user_prompt(request)

    assert "healing_formula: 1d10 +3" in prompt
    assert "healing_total: 10" in prompt
