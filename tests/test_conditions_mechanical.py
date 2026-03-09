"""Tests for Milestone 4 — Conditions with Mechanical Effects.

Covers:
- is_blocked_by_conditions: stunned rejects all actions
- attack_roll_mode: poisoned / prone → disadvantage
- CLI enricher: disadvantage rolls two d20s and takes the lower
- CLI resolver: stunned combatant is rejected before compendium lookup
- tick_condition_durations: expired conditions are removed
- Narration prompt: roll_mode appears in resolved action keys
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chronicle_weaver_ai.compendium import CompendiumStore
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.models import Actor
from chronicle_weaver_ai.rules import (
    add_condition,
    attack_roll_mode,
    is_blocked_by_conditions,
    tick_condition_durations,
)
from chronicle_weaver_ai.rules.combatant import Condition, CombatantSnapshot
from chronicle_weaver_ai.narration.models import ActionResult, NarrationRequest
from chronicle_weaver_ai.narration.narrator import build_user_prompt
from chronicle_weaver_ai.memory.context_models import ContextBundle


# ── Helpers ────────────────────────────────────────────────────────────────────


def _bare_snap(combatant_id: str = "pc.fighter") -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id=combatant_id,
        display_name="Fighter",
        source_type="actor",
        source_id=combatant_id,
        armor_class=16,
        hit_points=28,
    )


def _snap_with(*condition_names: str) -> CombatantSnapshot:
    snap = _bare_snap()
    for name in condition_names:
        cond = Condition(
            condition_name=name,
            source="test",
            duration_type="rounds",
            remaining_rounds=2,
        )
        snap = add_condition(snap, cond)
    return snap


def _store() -> CompendiumStore:
    store = CompendiumStore()
    store.load([Path("compendiums/core_5e")])
    return store


def _fighter(hp: int = 28) -> Actor:
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
        max_hit_points=28,
    )


def _context_bundle() -> ContextBundle:
    return ContextBundle(
        system_text="You are a narrator.", items=[], total_tokens_est=0
    )


# ── is_blocked_by_conditions ──────────────────────────────────────────────────


def test_stunned_is_blocked() -> None:
    """is_blocked_by_conditions must return a reason string for a stunned combatant."""
    snap = _snap_with("stunned")
    result = is_blocked_by_conditions(snap)
    assert result is not None
    assert "stunned" in result.lower()


def test_not_stunned_is_not_blocked() -> None:
    """is_blocked_by_conditions must return None for a combatant with no blocking conditions."""
    snap = _bare_snap()
    assert is_blocked_by_conditions(snap) is None


def test_poisoned_does_not_block() -> None:
    """Poisoned combatant is not blocked — it only imposes disadvantage."""
    snap = _snap_with("poisoned")
    assert is_blocked_by_conditions(snap) is None


def test_prone_does_not_block() -> None:
    """Prone combatant is not blocked — it only imposes disadvantage."""
    snap = _snap_with("prone")
    assert is_blocked_by_conditions(snap) is None


# ── attack_roll_mode ───────────────────────────────────────────────────────────


def test_no_condition_gives_normal_roll_mode() -> None:
    snap = _bare_snap()
    assert attack_roll_mode(snap) == "normal"


def test_poisoned_gives_disadvantage() -> None:
    snap = _snap_with("poisoned")
    assert attack_roll_mode(snap) == "disadvantage"


def test_prone_gives_disadvantage() -> None:
    snap = _snap_with("prone")
    assert attack_roll_mode(snap) == "disadvantage"


def test_stunned_alone_does_not_give_disadvantage() -> None:
    """Stunned blocks action entirely; attack_roll_mode still returns 'normal'
    because the attack will be blocked before the roll matters."""
    snap = _snap_with("stunned")
    assert attack_roll_mode(snap) == "normal"


def test_multiple_disadvantage_conditions_still_disadvantage() -> None:
    """Two disadvantage sources do not stack to anything beyond 'disadvantage'."""
    snap = _snap_with("poisoned", "prone")
    assert attack_roll_mode(snap) == "disadvantage"


# ── Disadvantage enricher integration ─────────────────────────────────────────


def _make_mock_output(d20_value: int) -> Any:
    """Build a minimal EngineOutput stand-in with the given dice roll."""
    from chronicle_weaver_ai.models import DiceRollRecord

    class _FakeOutput:
        dice_roll = DiceRollRecord(
            sides=20,
            entropy=d20_value - 1,
            accepted_entropy=d20_value - 1,
            value=d20_value,
            attempts=1,
            provider="fixed_entropy",
        )

    return _FakeOutput()


def test_normal_roll_uses_single_d20() -> None:
    """Without disadvantage, attack_rolls_d20 should contain exactly one value."""
    from chronicle_weaver_ai.cli import _enrich_weapon_attack_resolution_with_roll

    payload: dict[str, Any] = {
        "action_kind": "attack",
        "attack_bonus_total": 5,
    }
    output = _make_mock_output(d20_value=15)
    provider = FixedEntropyDiceProvider((14,))  # not consumed in normal mode
    attacker = _bare_snap()  # no conditions

    _enrich_weapon_attack_resolution_with_roll(
        payload=payload,
        output=output,
        dice_provider=provider,
        attacker_combatant=attacker,
    )

    assert payload["roll_mode"] == "normal"
    assert payload["attack_rolls_d20"] == [15]
    assert payload["attack_roll_d20"] == 15
    assert payload["attack_total"] == 20


def test_disadvantage_rolls_two_d20s_takes_lower() -> None:
    """Poisoned attacker must roll two d20s and use the lower value."""
    from chronicle_weaver_ai.cli import _enrich_weapon_attack_resolution_with_roll

    # First roll from engine = 15; second roll from provider with entropy=3 → d20=4
    payload: dict[str, Any] = {
        "action_kind": "attack",
        "attack_bonus_total": 5,
    }
    output = _make_mock_output(d20_value=15)
    # entropy=3 → roll_d20(3) = (3 % 20) + 1 = 4
    provider = FixedEntropyDiceProvider((3,))
    attacker = _snap_with("poisoned")

    _enrich_weapon_attack_resolution_with_roll(
        payload=payload,
        output=output,
        dice_provider=provider,
        attacker_combatant=attacker,
    )

    assert payload["roll_mode"] == "disadvantage"
    assert set(payload["attack_rolls_d20"]) == {15, 4}
    assert payload["attack_roll_d20"] == 4  # lower of 15 and 4
    assert payload["attack_total"] == 9  # 4 + 5


def test_prone_disadvantage_takes_lower() -> None:
    """Prone attacker: same disadvantage mechanic as poisoned."""
    from chronicle_weaver_ai.cli import _enrich_weapon_attack_resolution_with_roll

    # First roll = 8; second entropy=18 → d20=(18%20)+1=19; lower is 8
    payload: dict[str, Any] = {
        "action_kind": "attack",
        "attack_bonus_total": 3,
    }
    output = _make_mock_output(d20_value=8)
    provider = FixedEntropyDiceProvider((18,))  # → d20=19
    attacker = _snap_with("prone")

    _enrich_weapon_attack_resolution_with_roll(
        payload=payload,
        output=output,
        dice_provider=provider,
        attacker_combatant=attacker,
    )

    assert payload["roll_mode"] == "disadvantage"
    assert payload["attack_roll_d20"] == 8  # lower of 8 and 19
    assert payload["attack_total"] == 11


def test_disadvantage_deterministic_with_fixed_entropy() -> None:
    """Disadvantage roll is fully deterministic given the same entropy sequence."""
    from chronicle_weaver_ai.cli import _enrich_weapon_attack_resolution_with_roll

    def _run(first_d20: int, second_entropy: int) -> dict[str, Any]:
        payload: dict[str, Any] = {"action_kind": "attack", "attack_bonus_total": 4}
        output = _make_mock_output(d20_value=first_d20)
        provider = FixedEntropyDiceProvider((second_entropy,))
        _enrich_weapon_attack_resolution_with_roll(
            payload=payload,
            output=output,
            dice_provider=provider,
            attacker_combatant=_snap_with("poisoned"),
        )
        return payload

    result_a = _run(first_d20=12, second_entropy=9)
    result_b = _run(first_d20=12, second_entropy=9)
    assert result_a["attack_roll_d20"] == result_b["attack_roll_d20"]
    assert result_a["attack_total"] == result_b["attack_total"]


# ── Stunned rejection via resolver ────────────────────────────────────────────


def test_stunned_combatant_is_rejected_at_resolver() -> None:
    """_resolve_compendium_backed_action must reject actions from a stunned attacker."""
    from chronicle_weaver_ai.cli import _resolve_compendium_backed_action
    from chronicle_weaver_ai.models import IntentResult, Intent, Mechanic

    store = _store()
    actor = _fighter()
    stunned_snap = _snap_with("stunned")
    intent = IntentResult(
        intent=Intent.ATTACK,
        mechanic=Mechanic.COMBAT_ROLL,
        confidence=1.0,
        rationale="test",
        entry_id="w.longsword",
    )

    updated_intent, payload, rejection = _resolve_compendium_backed_action(
        interpreted=intent,
        actor=actor,
        compendium_store=store,
        turn_budget=None,
        attacker_combatant=stunned_snap,
    )

    assert rejection is not None
    assert "stunned" in rejection.lower()
    assert updated_intent.is_valid is False


def test_poisoned_combatant_is_not_rejected_at_resolver() -> None:
    """A poisoned combatant can still attempt an attack (disadvantage applies later)."""
    from chronicle_weaver_ai.cli import _resolve_compendium_backed_action
    from chronicle_weaver_ai.models import IntentResult, Intent, Mechanic

    store = _store()
    actor = _fighter()
    poisoned_snap = _snap_with("poisoned")
    intent = IntentResult(
        intent=Intent.ATTACK,
        mechanic=Mechanic.COMBAT_ROLL,
        confidence=1.0,
        rationale="test",
        entry_id="w.longsword",
    )

    _, _, rejection = _resolve_compendium_backed_action(
        interpreted=intent,
        actor=actor,
        compendium_store=store,
        turn_budget=None,
        attacker_combatant=poisoned_snap,
    )

    assert rejection is None


# ── Condition ticking ─────────────────────────────────────────────────────────


def test_tick_removes_expired_rounds_condition() -> None:
    """tick_condition_durations must remove a condition when remaining_rounds reaches 0."""
    cond = Condition(
        condition_name="poisoned",
        source="test",
        duration_type="rounds",
        remaining_rounds=1,
    )
    snap = add_condition(_bare_snap(), cond)
    assert any(c.condition_name == "poisoned" for c in snap.conditions)

    ticked = tick_condition_durations(snap)
    assert not any(c.condition_name == "poisoned" for c in ticked.conditions)


def test_tick_decrements_multi_round_condition() -> None:
    """tick_condition_durations must decrement remaining_rounds by 1."""
    cond = Condition(
        condition_name="prone",
        source="test",
        duration_type="rounds",
        remaining_rounds=3,
    )
    snap = add_condition(_bare_snap(), cond)
    ticked = tick_condition_durations(snap)

    prone = next(c for c in ticked.conditions if c.condition_name == "prone")
    assert prone.remaining_rounds == 2


def test_tick_removes_until_end_of_turn_condition() -> None:
    """tick_condition_durations must remove 'until_end_of_turn' conditions."""
    cond = Condition(
        condition_name="stunned",
        source="test",
        duration_type="until_end_of_turn",
    )
    snap = add_condition(_bare_snap(), cond)
    ticked = tick_condition_durations(snap)
    assert not any(c.condition_name == "stunned" for c in ticked.conditions)


def test_tick_leaves_persistent_condition() -> None:
    """tick_condition_durations must NOT remove persistent conditions."""
    cond = Condition(
        condition_name="poisoned",
        source="test",
        duration_type="persistent",
    )
    snap = add_condition(_bare_snap(), cond)
    ticked = tick_condition_durations(snap)
    assert any(c.condition_name == "poisoned" for c in ticked.conditions)


def test_attack_roll_mode_resets_after_condition_expires() -> None:
    """After a condition expires, roll mode returns to 'normal'."""
    cond = Condition(
        condition_name="poisoned",
        source="test",
        duration_type="rounds",
        remaining_rounds=1,
    )
    snap = add_condition(_bare_snap(), cond)
    assert attack_roll_mode(snap) == "disadvantage"

    ticked = tick_condition_durations(snap)
    assert attack_roll_mode(ticked) == "normal"


# ── Narration grounding ───────────────────────────────────────────────────────


def test_narration_prompt_includes_roll_mode() -> None:
    """roll_mode must appear in the Resolved Action section of the prompt."""
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=4,
        mode_from="combat",
        mode_to="combat",
        resolved_action={
            "action_kind": "attack",
            "entry_name": "Longsword",
            "roll_mode": "disadvantage",
            "attack_rolls_d20": [15, 4],
            "attack_roll_d20": 4,
            "attack_bonus_total": 5,
            "attack_total": 9,
            "hit_result": False,
        },
    )
    request = NarrationRequest(context=_context_bundle(), action=action)
    prompt = build_user_prompt(request)

    assert "roll_mode: disadvantage" in prompt
    assert "attack_rolls_d20" in prompt


def test_narration_prompt_contains_condition_style_rule() -> None:
    """Style rule 19 (disadvantage/condition grounding) must appear in the prompt."""
    action = ActionResult(
        intent="attack",
        mechanic="combat_roll",
        dice_roll=None,
        mode_from="combat",
        mode_to="combat",
    )
    request = NarrationRequest(context=_context_bundle(), action=action)
    prompt = build_user_prompt(request)
    assert "19." in prompt
    assert "roll_mode=disadvantage" in prompt
