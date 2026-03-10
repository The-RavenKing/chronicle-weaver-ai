"""Tests for Foundry VTT bidirectional adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


from chronicle_weaver_ai.compendium.foundry_adapter import (
    entry_to_foundry,
    export_to_foundry_pack,
    foundry_doc_to_entry,
    load_foundry_pack,
)
from chronicle_weaver_ai.compendium.models import (
    ArmorEntry,
    FeatureEntry,
    MonsterEntry,
    SpellEntry,
    WeaponEntry,
)


# ---------------------------------------------------------------------------
# Sample Foundry documents
# ---------------------------------------------------------------------------


def _foundry_npc() -> dict:
    return {
        "name": "Test Goblin",
        "type": "npc",
        "system": {
            "abilities": {
                "str": {"value": 8},
                "dex": {"value": 14},
                "con": {"value": 10},
                "int": {"value": 10},
                "wis": {"value": 8},
                "cha": {"value": 8},
            },
            "attributes": {
                "hp": {"value": 7, "max": 7},
                "ac": {"value": 13},
                "movement": {"walk": 30},
            },
            "details": {
                "biography": {"value": "<p>A small goblin creature.</p>"},
                "cr": 0.25,
                "type": {"value": "humanoid"},
            },
            "traits": {"size": "sm"},
        },
        "items": [
            {
                "name": "Scimitar",
                "type": "weapon",
                "system": {
                    "damage": {"parts": [["1d6+2", "slashing"]]},
                    "attackBonus": 4,
                },
            }
        ],
    }


def _foundry_weapon() -> dict:
    return {
        "name": "Test Longsword",
        "type": "weapon",
        "system": {
            "description": {"value": "<p>A fine longsword.</p>"},
            "damage": {"parts": [["1d8", "slashing"]]},
            "ability": "str",
            "attackBonus": 0,
            "properties": {"versatile": True, "martial": True},
        },
    }


def _foundry_spell() -> dict:
    return {
        "name": "Test Fireball",
        "type": "spell",
        "system": {
            "description": {"value": "<p>A burst of flame.</p>"},
            "level": 3,
            "school": "evocation",
            "activation": {"type": "action", "cost": 1},
            "duration": {"value": "Instantaneous", "units": ""},
            "range": {"value": 150, "units": "ft"},
            "components": {"vocal": True, "somatic": True, "material": True},
            "save": {"ability": "dex", "dc": None},
            "damage": {"parts": [["8d6", "fire"]]},
            "actionType": "save",
        },
    }


def _foundry_feat() -> dict:
    return {
        "name": "Test Extra Attack",
        "type": "feat",
        "system": {
            "description": {"value": "<p>Attack twice.</p>"},
            "activation": {"type": "action", "cost": 1},
            "uses": {"value": None, "max": None, "per": None},
        },
    }


def _foundry_armor() -> dict:
    return {
        "name": "Test Chain Mail",
        "type": "armor",
        "system": {
            "description": {"value": "<p>Heavy armor.</p>"},
            "armor": {"type": "heavy", "value": 16, "dex": None},
            "strength": 13,
        },
    }


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


def test_import_npc_returns_monster_entry() -> None:
    entry = foundry_doc_to_entry(_foundry_npc())
    assert isinstance(entry, MonsterEntry)
    assert entry.name == "Test Goblin"
    assert entry.hit_points == 7
    assert entry.armor_class == 13
    assert entry.abilities["dex"] == 14


def test_import_npc_includes_actions() -> None:
    entry = foundry_doc_to_entry(_foundry_npc())
    assert isinstance(entry, MonsterEntry)
    assert len(entry.actions) == 1
    assert entry.actions[0].name == "Scimitar"
    assert entry.actions[0].attack_bonus == 4


def test_import_weapon_returns_weapon_entry() -> None:
    entry = foundry_doc_to_entry(_foundry_weapon())
    assert isinstance(entry, WeaponEntry)
    assert entry.name == "Test Longsword"
    assert entry.damage == "1d8"
    assert entry.damage_type == "slashing"
    assert entry.attack_ability == "str"


def test_import_spell_returns_spell_entry() -> None:
    entry = foundry_doc_to_entry(_foundry_spell())
    assert isinstance(entry, SpellEntry)
    assert entry.name == "Test Fireball"
    assert entry.level == 3
    assert entry.save_ability == "dex"
    assert "V" in entry.components


def test_import_feat_returns_feature_entry() -> None:
    entry = foundry_doc_to_entry(_foundry_feat())
    assert isinstance(entry, FeatureEntry)
    assert entry.name == "Test Extra Attack"
    assert entry.action_type == "action"


def test_import_armor_returns_armor_entry() -> None:
    entry = foundry_doc_to_entry(_foundry_armor())
    assert isinstance(entry, ArmorEntry)
    assert entry.name == "Test Chain Mail"
    assert entry.armor_class_base == 16
    assert entry.armor_type == "heavy"
    assert entry.strength_requirement == 13


def test_import_unknown_type_returns_none() -> None:
    result = foundry_doc_to_entry({"name": "Unknown", "type": "vehicle"})
    assert result is None


def test_import_empty_name_returns_none() -> None:
    result = foundry_doc_to_entry({"name": "", "type": "npc"})
    assert result is None


def test_load_foundry_pack_json_file() -> None:
    docs = [_foundry_npc(), _foundry_weapon(), _foundry_spell()]
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as fh:
        json.dump(docs, fh)
        path = Path(fh.name)
    entries = load_foundry_pack(path)
    assert len(entries) == 3
    assert isinstance(entries[0], MonsterEntry)


def test_load_foundry_pack_nedb_file() -> None:
    docs = [_foundry_npc(), _foundry_weapon()]
    with tempfile.NamedTemporaryFile(suffix=".db", mode="w", delete=False) as fh:
        for doc in docs:
            fh.write(json.dumps(doc) + "\n")
        path = Path(fh.name)
    entries = load_foundry_pack(path)
    assert len(entries) == 2


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


def test_export_monster_to_foundry() -> None:
    from chronicle_weaver_ai.compendium.models import MonsterAction

    entry = MonsterEntry(
        id="m.test_goblin",
        name="Test Goblin",
        kind="monster",
        description="A goblin",
        armor_class=13,
        hit_points=7,
        speed=30,
        abilities={"str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8},
        actions=[
            MonsterAction(name="Scimitar", attack_bonus=4, damage_formula="1d6+2")
        ],
        challenge_rating="0.25",
    )
    doc = entry_to_foundry(entry)
    assert doc is not None
    assert doc["type"] == "npc"
    assert doc["name"] == "Test Goblin"
    assert doc["system"]["attributes"]["hp"]["value"] == 7
    assert doc["system"]["attributes"]["ac"]["value"] == 13


def test_export_weapon_to_foundry() -> None:
    entry = WeaponEntry(
        id="w.test_sword",
        name="Test Sword",
        kind="weapon",
        description="A sword",
        damage="1d8",
        damage_type="slashing",
        attack_ability="str",
    )
    doc = entry_to_foundry(entry)
    assert doc is not None
    assert doc["type"] == "weapon"
    assert doc["system"]["damage"]["parts"][0][0] == "1d8"


def test_export_spell_to_foundry() -> None:
    entry = SpellEntry(
        id="s.test_spell",
        name="Test Spell",
        kind="spell",
        description="A spell",
        level=3,
        school="evocation",
        save_ability="dex",
        components=["V", "S", "M"],
        effect_summary="8d6 fire",
    )
    doc = entry_to_foundry(entry)
    assert doc is not None
    assert doc["type"] == "spell"
    assert doc["system"]["level"] == 3
    assert doc["system"]["components"]["vocal"] is True


def test_export_to_foundry_pack_writes_nedb() -> None:
    from chronicle_weaver_ai.compendium.models import MonsterAction

    entries = [
        MonsterEntry(
            id="m.tg",
            name="Test Goblin",
            kind="monster",
            description="Goblin",
            armor_class=13,
            hit_points=7,
            abilities={"str": 8},
            actions=[MonsterAction(name="Bite", attack_bonus=2, damage_formula="1d4")],
        ),
        WeaponEntry(
            id="w.ts",
            name="Test Sword",
            kind="weapon",
            description="Sword",
            damage="1d8",
        ),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "test.db"
        written = export_to_foundry_pack(entries, out_path)
        assert written == 2
        assert out_path.exists()
        lines = out_path.read_text().strip().splitlines()
        assert len(lines) == 2
        doc = json.loads(lines[0])
        assert doc["type"] == "npc"


def test_roundtrip_npc() -> None:
    """Import a Foundry NPC then re-export it and verify the structure."""
    entry = foundry_doc_to_entry(_foundry_npc())
    assert isinstance(entry, MonsterEntry)
    doc = entry_to_foundry(entry)
    assert doc is not None
    assert doc["type"] == "npc"
    assert doc["name"] == "Test Goblin"
    # Re-import from exported doc
    reimported = foundry_doc_to_entry(doc)
    assert isinstance(reimported, MonsterEntry)
    assert reimported.name == "Test Goblin"
