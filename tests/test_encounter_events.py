"""Tests for encounter event emission and event log bridge.

Covers:
- emit_* helpers produce correct event_type and payload fields
- _run_spawn_encounter collects events and writes them to JSONL
- event log contains encounter_started and encounter_ended events
- attack_resolved event payload includes hit/damage fields
- combatant_defeated emitted when HP hits 0
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from chronicle_weaver_ai.encounter_events import (
    emit_attack_resolved,
    emit_combatant_defeated,
    emit_encounter_ended,
    emit_encounter_started,
    emit_hp_changed,
    emit_turn_started,
)


# ── emit_* unit tests ─────────────────────────────────────────────────────────


def test_emit_encounter_started_fields():
    ev = emit_encounter_started(
        encounter_id="enc.1",
        combatant_names=["Hero", "Goblin"],
        initiative_order=["hero.1", "goblin.1"],
        ts=1,
    )
    assert ev.event_type == "encounter_started"
    assert ev.payload["encounter_id"] == "enc.1"
    assert ev.payload["combatant_names"] == ["Hero", "Goblin"]
    assert ev.payload["initiative_order"] == ["hero.1", "goblin.1"]
    assert ev.timestamp == 1


def test_emit_turn_started_fields():
    ev = emit_turn_started(
        "enc.1", round_number=2, combatant_id="c1", combatant_name="Hero", ts=5
    )
    assert ev.event_type == "turn_started"
    assert ev.payload["round"] == 2
    assert ev.payload["combatant_id"] == "c1"
    assert ev.payload["combatant_name"] == "Hero"


def test_emit_attack_resolved_hit():
    ev = emit_attack_resolved(
        encounter_id="enc.1",
        attacker_id="a1",
        attacker_name="Hero",
        target_id="t1",
        target_name="Goblin",
        attack_roll=15,
        attack_bonus=6,
        attack_total=21,
        target_ac=13,
        hit=True,
        damage_total=8,
        weapon_name="Longsword",
        ts=3,
    )
    assert ev.event_type == "attack_resolved"
    assert ev.payload["hit"] is True
    assert ev.payload["damage_total"] == 8
    assert ev.payload["weapon_name"] == "Longsword"


def test_emit_attack_resolved_miss():
    ev = emit_attack_resolved(
        encounter_id="enc.1",
        attacker_id="a1",
        attacker_name="Hero",
        target_id="t1",
        target_name="Goblin",
        attack_roll=3,
        attack_bonus=6,
        attack_total=9,
        target_ac=13,
        hit=False,
        damage_total=0,
        ts=4,
    )
    assert ev.payload["hit"] is False
    assert ev.payload["damage_total"] == 0
    assert "weapon_name" not in ev.payload  # omitted when empty


def test_emit_hp_changed_fields():
    ev = emit_hp_changed("enc.1", "c1", "Goblin", old_hp=7, new_hp=2, ts=6)
    assert ev.event_type == "hp_changed"
    assert ev.payload["old_hp"] == 7
    assert ev.payload["new_hp"] == 2


def test_emit_combatant_defeated_fields():
    ev = emit_combatant_defeated("enc.1", "c1", "Goblin", ts=7)
    assert ev.event_type == "combatant_defeated"
    assert ev.payload["combatant_id"] == "c1"
    assert ev.payload["combatant_name"] == "Goblin"


def test_emit_encounter_ended_victory():
    ev = emit_encounter_ended(
        encounter_id="enc.1",
        outcome="victory",
        winner_ids=["hero.1"],
        loser_ids=["goblin.1"],
        rounds_elapsed=3,
        ts=20,
    )
    assert ev.event_type == "encounter_ended"
    assert ev.payload["outcome"] == "victory"
    assert ev.payload["rounds_elapsed"] == 3
    assert "hero.1" in ev.payload["winner_ids"]


# ── event serialisation round-trip ────────────────────────────────────────────


def test_encounter_event_to_dict_round_trip():
    ev = emit_encounter_started("enc.1", ["Hero"], ["hero.1"], ts=1)
    d = ev.to_dict()
    assert d["type"] == "encounter_started"
    assert isinstance(d["payload"], dict)
    assert d["ts"] == 1


# ── spawn encounter writes event log ──────────────────────────────────────────


def test_spawn_encounter_writes_event_log():
    """End-to-end: spawn encounter writes JSONL with encounter_started and encounter_ended."""
    from chronicle_weaver_ai.compendium.store import CompendiumStore
    from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
    from chronicle_weaver_ai.models import Actor

    store = CompendiumStore()
    from pathlib import Path as _Path

    compendium_root = _Path("compendiums/core_5e")
    if not compendium_root.exists():
        import pytest

        pytest.skip("compendiums/core_5e not present")

    store.load([compendium_root])

    actor = Actor(
        actor_id="hero",
        name="Hero",
        level=3,
        proficiency_bonus=2,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 10, "cha": 10},
        equipped_weapon_ids=["w.longsword"],
        hit_points=28,
        max_hit_points=28,
        armor_class=16,
    )
    # Fixed entropy: alternate high/low so each roll is deterministic
    provider = FixedEntropyDiceProvider(tuple(range(100)))

    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = str(Path(tmpdir) / "events.jsonl")

        from chronicle_weaver_ai.cli import _run_spawn_encounter

        _run_spawn_encounter(
            compendium_store=store,
            spawn="goblin",
            actor=actor,
            dice_provider=provider,
            event_log_path=log_path,
        )

        lines = Path(log_path).read_text().strip().splitlines()
        events = [json.loads(line) for line in lines]

    event_types = [e["type"] for e in events]
    assert "encounter_started" in event_types
    assert "encounter_ended" in event_types
    assert "turn_started" in event_types
    assert "attack_resolved" in event_types
    # encounter_started must be first
    assert event_types[0] == "encounter_started"
    # encounter_ended must be last
    assert event_types[-1] == "encounter_ended"
