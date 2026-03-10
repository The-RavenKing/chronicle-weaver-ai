"""Tests for Short/Long Rest mechanics.

Covers:
- apply_short_rest: HP gain, hit dice spending, resource restoration
- apply_long_rest: full HP, spell slot restoration, resource restoration, hit dice recovery
- Edge cases: no hit dice, unknown hit die, already full HP
- FeatureEntry.reset_on loaded from compendium
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from chronicle_weaver_ai.compendium.models import FeatureEntry
from chronicle_weaver_ai.compendium.store import CompendiumStore
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.models import Actor
from chronicle_weaver_ai.rules import apply_long_rest, apply_short_rest


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _fighter(
    hp: int = 10,
    max_hp: int = 28,
    hit_die: str = "d10",
    hit_dice_remaining: int = 3,
    spell_slots: dict | None = None,
    spell_slots_max: dict | None = None,
    resources: dict | None = None,
    max_resources: dict | None = None,
) -> Actor:
    return Actor(
        actor_id="hero",
        name="Hero",
        class_name="fighter",
        level=3,
        proficiency_bonus=2,
        abilities={
            "str": 16,
            "dex": 12,
            "con": 14,  # CON mod = +2
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        equipped_weapon_ids=["w.longsword"],
        feature_ids=["f.second_wind"],
        hit_points=hp,
        max_hit_points=max_hp,
        hit_die=hit_die,
        hit_dice_remaining=hit_dice_remaining,
        spell_slots=spell_slots or {},
        spell_slots_max=spell_slots_max or {},
        resources=resources or {"second_wind_uses": 0},
        max_resources=max_resources or {"second_wind_uses": 1},
    )


# ── apply_short_rest ──────────────────────────────────────────────────────────


def test_short_rest_spends_hit_die_and_gains_hp():
    actor = _fighter(hp=10)
    # entropy=9 → 1d10 = 10, + CON mod 2 = 12 HP gained
    provider = FixedEntropyDiceProvider((9,))
    updated, rolls = apply_short_rest(actor, provider, hit_dice_to_spend=1)
    assert len(rolls) == 1
    assert rolls[0] == 12  # 10 + 2 CON
    assert updated.hit_points == 22


def test_short_rest_caps_hp_at_max():
    actor = _fighter(hp=26, max_hp=28)
    # entropy=9 → 1d10=10 + 2 CON = 12, capped at max_hp=28
    provider = FixedEntropyDiceProvider((9,))
    updated, rolls = apply_short_rest(actor, provider, hit_dice_to_spend=1)
    assert updated.hit_points == 28


def test_short_rest_decrements_hit_dice_remaining():
    actor = _fighter(hit_dice_remaining=3)
    provider = FixedEntropyDiceProvider((9,))
    updated, _ = apply_short_rest(actor, provider, hit_dice_to_spend=2)
    assert updated.hit_dice_remaining == 1


def test_short_rest_no_hit_dice_available():
    actor = _fighter(hit_dice_remaining=0)
    provider = FixedEntropyDiceProvider((9,))
    updated, rolls = apply_short_rest(actor, provider)
    assert rolls == []
    assert updated.hit_points == actor.hit_points
    assert updated.hit_dice_remaining == 0


def test_short_rest_cannot_spend_more_than_available():
    actor = _fighter(hit_dice_remaining=1)
    provider = FixedEntropyDiceProvider((9, 9, 9))
    updated, rolls = apply_short_rest(actor, provider, hit_dice_to_spend=3)
    # Only 1 die available — spends 1
    assert len(rolls) == 1
    assert updated.hit_dice_remaining == 0


def test_short_rest_restores_resources_from_max_resources():
    actor = _fighter(
        resources={"second_wind_uses": 0},
        max_resources={"second_wind_uses": 1},
    )
    provider = FixedEntropyDiceProvider((9,))
    updated, _ = apply_short_rest(actor, provider)
    assert updated.resources["second_wind_uses"] == 1


def test_short_rest_fallback_d8_when_hit_die_not_set():
    actor = Actor(
        actor_id="x",
        name="X",
        level=1,
        abilities={"con": 10},
        hit_points=5,
        max_hit_points=15,
        hit_die=None,  # no hit_die set
        hit_dice_remaining=1,
        max_resources={},
        spell_slots_max={},
    )
    # entropy=7 → 1d8=8 + CON mod 0 = 8 HP gained
    provider = FixedEntropyDiceProvider((7,))
    updated, rolls = apply_short_rest(actor, provider)
    assert len(rolls) == 1
    assert updated.hit_points == 13


# ── apply_long_rest ───────────────────────────────────────────────────────────


def test_long_rest_restores_full_hp():
    actor = _fighter(hp=5, max_hp=28)
    updated = apply_long_rest(actor)
    assert updated.hit_points == 28


def test_long_rest_restores_spell_slots():
    actor = _fighter(
        spell_slots={1: 0, 2: 1},
        spell_slots_max={1: 2, 2: 2},
    )
    updated = apply_long_rest(actor)
    assert updated.spell_slots[1] == 2
    assert updated.spell_slots[2] == 2


def test_long_rest_restores_resources():
    actor = _fighter(
        resources={"second_wind_uses": 0, "action_surge_uses": 0},
        max_resources={"second_wind_uses": 1, "action_surge_uses": 1},
    )
    updated = apply_long_rest(actor)
    assert updated.resources["second_wind_uses"] == 1
    assert updated.resources["action_surge_uses"] == 1


def test_long_rest_recovers_hit_dice():
    # Level 3 fighter, 1 die remaining → regain max(3//2, 1) = 1, total 2
    actor = _fighter(hit_dice_remaining=1)
    updated = apply_long_rest(actor)
    assert updated.hit_dice_remaining == 2


def test_long_rest_hit_dice_capped_at_level():
    actor = _fighter(hit_dice_remaining=3)  # already at max (level=3)
    updated = apply_long_rest(actor)
    assert updated.hit_dice_remaining == 3  # regain 1, but min(3+1, 3) = 3


def test_long_rest_no_hp_change_when_max_hp_unknown():
    actor = Actor(
        actor_id="x",
        name="X",
        level=1,
        abilities={"con": 10},
        hit_points=5,
        max_hit_points=None,  # unknown max
        hit_dice_remaining=None,
        max_resources={},
        spell_slots_max={},
    )
    updated = apply_long_rest(actor)
    # max_hit_points is None → hp stays at current value
    assert updated.hit_points == 5


def test_long_rest_leaves_empty_spell_slots_alone():
    actor = _fighter(spell_slots={}, spell_slots_max={})
    updated = apply_long_rest(actor)
    assert updated.spell_slots == {}


# ── FeatureEntry.reset_on from compendium ─────────────────────────────────────


def test_feature_entry_reset_on_loaded_from_json():
    data = {
        "id": "f.test",
        "kind": "feature",
        "name": "Test Feature",
        "description": "Test.",
        "tags": ["test"],
        "feature_type": "surge",
        "action_type": "action",
        "usage_key": "test_uses",
        "effect_summary": "Test effect.",
        "reset_on": "short_rest",
    }
    store = CompendiumStore()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "feature_test.json").write_text(json.dumps(data))
        store.load([root])
    entry = store.get_by_id("f.test")
    assert isinstance(entry, FeatureEntry)
    assert entry.reset_on == "short_rest"


def test_second_wind_reset_on_loads_from_compendiums_dir():
    store = CompendiumStore()
    root = Path("compendiums/core_5e")
    if not root.exists():
        import pytest

        pytest.skip("compendiums/core_5e not found")
    store.load([root])
    entry = store.get_by_id("f.second_wind")
    assert isinstance(entry, FeatureEntry)
    assert entry.reset_on == "short_rest"


def test_action_surge_reset_on_loads_from_compendiums_dir():
    store = CompendiumStore()
    root = Path("compendiums/core_5e")
    if not root.exists():
        import pytest

        pytest.skip("compendiums/core_5e not found")
    store.load([root])
    entry = store.get_by_id("f.action_surge")
    assert isinstance(entry, FeatureEntry)
    assert entry.reset_on == "short_rest"
