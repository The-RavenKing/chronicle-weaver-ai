"""Tests for campaign persistence (Milestone: Campaign Persistence Upgrade v0)."""

from __future__ import annotations

from pathlib import Path

from chronicle_weaver_ai.campaign import (
    CampaignScene,
    CampaignState,
    actor_from_dict,
    actor_to_dict,
    campaign_from_dict,
    campaign_to_dict,
    combatant_snapshot_from_dict,
    combatant_snapshot_to_dict,
    encounter_state_from_dict,
    encounter_state_to_dict,
    load_campaign,
    save_campaign,
)
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.encounter import (
    EncounterState,
    create_encounter,
    get_combatant,
    mark_defeated,
)
from chronicle_weaver_ai.models import Actor
from chronicle_weaver_ai.rules import add_condition
from chronicle_weaver_ai.rules.combatant import Condition, CombatantSnapshot


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _fighter() -> Actor:
    return Actor(
        actor_id="pc.fighter.sample",
        name="Sample Fighter",
        class_name="fighter",
        species_name="human",
        level=3,
        proficiency_bonus=2,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 10, "cha": 10},
        equipped_weapon_ids=["w.longsword"],
        known_spell_ids=[],
        feature_ids=["f.second_wind"],
        item_ids=[],
        spell_slots={1: 0},
        resources={"second_wind_uses": 1},
        armor_class=16,
        hit_points=28,
    )


def _wizard() -> Actor:
    return Actor(
        actor_id="pc.wizard.sample",
        name="Sample Wizard",
        class_name="wizard",
        species_name="human",
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


def _goblin_snap(hp: int = 7) -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id="m.goblin",
        display_name="Goblin",
        source_type="monster",
        source_id="m.goblin",
        armor_class=13,
        hit_points=hp,
        abilities={"str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8},
        metadata={"creature_type": "humanoid", "size": "small"},
    )


def _fighter_snap() -> CombatantSnapshot:
    return CombatantSnapshot(
        combatant_id="pc.fighter.sample",
        display_name="Sample Fighter",
        source_type="actor",
        source_id="pc.fighter.sample",
        armor_class=16,
        hit_points=28,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 10, "cha": 10},
        proficiency_bonus=2,
    )


def _bare_campaign() -> CampaignState:
    return CampaignState(
        campaign_id="camp.test",
        campaign_name="Test Campaign",
        actors={
            "pc.fighter.sample": _fighter(),
            "pc.wizard.sample": _wizard(),
        },
        lorebook_refs=["lorebooks/core.jsonl"],
        scenes={
            "scene.dungeon_entry": CampaignScene(
                scene_id="scene.dungeon_entry",
                description_stub="A narrow corridor with mossy stone walls.",
                combat_active=False,
                combatants_present=["Sample Fighter", "Sample Wizard"],
            )
        },
        session_log_refs=["logs/session_001.jsonl"],
        active_encounter_id=None,
    )


def _encounter() -> EncounterState:
    combatants = [_goblin_snap(), _fighter_snap()]
    provider = FixedEntropyDiceProvider((10, 5))
    return create_encounter("enc.test", combatants, provider)


# ── Actor round-trip ──────────────────────────────────────────────────────────


def test_actor_serialisation_roundtrip() -> None:
    """actor_to_dict → actor_from_dict must produce an identical Actor."""
    fighter = _fighter()
    d = actor_to_dict(fighter)
    restored = actor_from_dict(d)

    assert restored.actor_id == fighter.actor_id
    assert restored.name == fighter.name
    assert restored.class_name == fighter.class_name
    assert restored.level == fighter.level
    assert restored.proficiency_bonus == fighter.proficiency_bonus
    assert restored.abilities == fighter.abilities
    assert restored.equipped_weapon_ids == fighter.equipped_weapon_ids
    assert restored.spell_slots == fighter.spell_slots
    assert restored.resources == fighter.resources
    assert restored.armor_class == fighter.armor_class
    assert restored.hit_points == fighter.hit_points


def test_actor_spell_slots_int_keys_survive_roundtrip() -> None:
    """spell_slots with int keys must round-trip faithfully through JSON."""
    wizard = _wizard()
    d = actor_to_dict(wizard)
    # Keys must be strings in the serialised form (JSON constraint)
    assert all(isinstance(k, str) for k in d["spell_slots"])
    restored = actor_from_dict(d)
    assert restored.spell_slots == {1: 1}


# ── CombatantSnapshot round-trip ──────────────────────────────────────────────


def test_combatant_snapshot_roundtrip_with_conditions() -> None:
    """combatant_snapshot_to_dict → from_dict must preserve conditions and metadata."""
    snap = _goblin_snap()
    snap = add_condition(
        snap,
        Condition("prone", "attack.trip", "rounds", remaining_rounds=2),
    )
    snap = add_condition(
        snap,
        Condition("poisoned", "spell.cloud", "persistent", remaining_rounds=None),
    )

    d = combatant_snapshot_to_dict(snap)
    restored = combatant_snapshot_from_dict(d)

    assert restored.combatant_id == snap.combatant_id
    assert restored.hit_points == snap.hit_points
    assert restored.armor_class == snap.armor_class
    assert restored.abilities == snap.abilities
    assert restored.metadata["creature_type"] == "humanoid"
    assert len(restored.conditions) == 2
    prone = next(c for c in restored.conditions if c.condition_name == "prone")
    assert prone.duration_type == "rounds"
    assert prone.remaining_rounds == 2
    poisoned = next(c for c in restored.conditions if c.condition_name == "poisoned")
    assert poisoned.duration_type == "persistent"


# ── EncounterState round-trip ─────────────────────────────────────────────────


def test_encounter_state_serialisation_roundtrip() -> None:
    """encounter_state_to_dict → from_dict must produce equivalent EncounterState."""
    enc = _encounter()
    enc = mark_defeated(enc, "m.goblin")

    d = encounter_state_to_dict(enc)
    restored = encounter_state_from_dict(d)

    assert restored.encounter_id == enc.encounter_id
    assert restored.active == enc.active
    assert restored.defeated_ids == enc.defeated_ids
    assert set(restored.combatants.keys()) == set(enc.combatants.keys())

    # Combatant HP preserved
    assert get_combatant(restored, "m.goblin").hit_points == 7
    assert get_combatant(restored, "pc.fighter.sample").hit_points == 28

    # Turn order preserved
    assert restored.turn_order.current_round == enc.turn_order.current_round
    assert restored.turn_order.current_turn_index == enc.turn_order.current_turn_index
    assert restored.turn_order.combatant_ids == enc.turn_order.combatant_ids

    # Initiative rolls preserved
    for cid, roll in enc.turn_order.initiative_rolls.items():
        r = restored.turn_order.initiative_rolls[cid]
        assert r.d20_value == roll.d20_value
        assert r.dex_modifier == roll.dex_modifier
        assert r.total == roll.total


def test_encounter_state_defeated_ids_roundtrip() -> None:
    """defeated_ids frozenset must survive serialisation as a sorted list."""
    enc = _encounter()
    enc = mark_defeated(enc, "m.goblin")

    d = encounter_state_to_dict(enc)
    assert isinstance(d["defeated_ids"], list)
    assert "m.goblin" in d["defeated_ids"]

    restored = encounter_state_from_dict(d)
    assert isinstance(restored.defeated_ids, frozenset)
    assert "m.goblin" in restored.defeated_ids


# ── CampaignState round-trip (dict only) ──────────────────────────────────────


def test_campaign_dict_roundtrip() -> None:
    """campaign_to_dict → campaign_from_dict must produce an equivalent CampaignState."""
    campaign = _bare_campaign()
    d = campaign_to_dict(campaign)
    restored = campaign_from_dict(d)

    assert restored.campaign_id == campaign.campaign_id
    assert restored.campaign_name == campaign.campaign_name
    assert set(restored.actors.keys()) == set(campaign.actors.keys())
    assert restored.lorebook_refs == campaign.lorebook_refs
    assert restored.session_log_refs == campaign.session_log_refs
    assert restored.active_encounter_id is None
    assert "scene.dungeon_entry" in restored.scenes
    scene = restored.scenes["scene.dungeon_entry"]
    assert scene.description_stub == "A narrow corridor with mossy stone walls."
    assert scene.combat_active is False


# ── CampaignState file I/O ────────────────────────────────────────────────────


def test_campaign_save_load_roundtrip(tmp_path: Path) -> None:
    """save_campaign + load_campaign must produce a campaign equal to the original."""
    campaign = _bare_campaign()
    out = tmp_path / "campaign.json"

    save_campaign(campaign, out)
    assert out.exists()

    restored = load_campaign(out)
    assert restored.campaign_id == campaign.campaign_id
    assert restored.campaign_name == campaign.campaign_name

    fighter = restored.actors["pc.fighter.sample"]
    assert fighter.hit_points == 28
    assert fighter.armor_class == 16
    assert fighter.spell_slots == {1: 0}

    wizard = restored.actors["pc.wizard.sample"]
    assert wizard.known_spell_ids == ["s.magic_missile"]
    assert wizard.spell_slots == {1: 1}


def test_campaign_with_active_encounter_roundtrip(tmp_path: Path) -> None:
    """A campaign carrying an embedded EncounterState must round-trip faithfully."""
    enc = _encounter()
    campaign = CampaignState(
        campaign_id="camp.enc_test",
        campaign_name="Encounter Campaign",
        actors={"pc.fighter.sample": _fighter()},
        lorebook_refs=[],
        scenes={},
        session_log_refs=[],
        active_encounter_id=enc.encounter_id,
        encounter_states={enc.encounter_id: enc},
    )

    out = tmp_path / "campaign_enc.json"
    save_campaign(campaign, out)
    restored = load_campaign(out)

    assert restored.active_encounter_id == enc.encounter_id
    assert enc.encounter_id in restored.encounter_states

    r_enc = restored.encounter_states[enc.encounter_id]
    assert r_enc.encounter_id == enc.encounter_id
    assert set(r_enc.combatants.keys()) == {"m.goblin", "pc.fighter.sample"}
    assert r_enc.turn_order.combatant_ids == enc.turn_order.combatant_ids


def test_campaign_json_is_readable(tmp_path: Path) -> None:
    """Saved campaign JSON must be valid JSON with expected top-level keys."""
    campaign = _bare_campaign()
    out = tmp_path / "campaign.json"
    save_campaign(campaign, out)

    import json

    raw = json.loads(out.read_text())
    assert raw["campaign_id"] == "camp.test"
    assert "actors" in raw
    assert "scenes" in raw
    assert "lorebook_refs" in raw
    assert "session_log_refs" in raw
    assert raw["active_encounter_id"] is None
