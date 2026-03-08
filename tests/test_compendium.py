"""Compendium loader and model behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chronicle_weaver_ai.cli import app
from chronicle_weaver_ai.compendium import CompendiumLoadError
from chronicle_weaver_ai.compendium.models import SpellEntry, WeaponEntry
from chronicle_weaver_ai.compendium.store import CompendiumStore


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _build_root_with_examples(tmp_root: Path) -> None:
    _write_json(
        tmp_root / "core_5e" / "combat" / "longsword.json",
        {
            "id": "w.longsword",
            "name": "Longsword",
            "kind": "weapon",
            "description": "A versatile steel sword.",
            "tags": ["martial", "versatile"],
            "damage": "1d8",
            "damage_type": "slashing",
            "properties": ["versatile", "heavy"],
        },
    )
    _write_json(
        tmp_root / "campaign" / "spells" / "fireball.json",
        {
            "id": "s.fireball",
            "name": "Fireball",
            "kind": "spell",
            "description": "A bright streak explodes in flame.",
            "tags": ["evocation", "area"],
            "level": 3,
            "school": "evocation",
            "casting_time": "action",
            "range": "150 feet",
            "components": ["V", "S", "M"],
            "duration": "instantaneous",
        },
    )
    _write_json(
        tmp_root / "homebrew" / "items" / "torch.json",
        {
            "id": "i.torch",
            "name": "Torch",
            "kind": "item",
            "description": "A simple light source.",
            "tags": ["common"],
            "item_type": "adventuring gear",
        },
    )


def test_loading_valid_weapon_json(tmp_path: Path) -> None:
    _build_root_with_examples(tmp_path)
    store = CompendiumStore()
    store.load([tmp_path / "core_5e"])

    entry = store.get_by_id("w.longsword")
    assert isinstance(entry, WeaponEntry)
    assert entry.id == "w.longsword"
    assert entry.name == "Longsword"
    assert entry.kind == "weapon"
    assert entry.damage == "1d8"
    assert entry.damage_type == "slashing"
    assert entry.properties == ["versatile", "heavy"]


def test_loading_valid_spell_json(tmp_path: Path) -> None:
    _build_root_with_examples(tmp_path)
    store = CompendiumStore()
    store.load([tmp_path / "campaign"])

    entry = store.get_by_id("s.fireball")
    assert isinstance(entry, SpellEntry)
    assert entry.level == 3
    assert entry.school == "evocation"
    assert entry.range == "150 feet"
    assert entry.components == ["V", "S", "M"]
    assert entry.duration == "instantaneous"


def test_invalid_entry_missing_required_fields(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "core_5e" / "invalid.json",
        {
            "id": "w.bad",
            "name": "Bad Blade",
            "kind": "weapon",
            # missing description and tags
            "damage": "1d6",
            "damage_type": "slashing",
        },
    )

    store = CompendiumStore()
    with pytest.raises(
        CompendiumLoadError, match="missing required field 'description'"
    ):
        store.load([tmp_path / "core_5e"])


def test_override_core_overridden_by_homebrew(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "core_5e" / "spear.json",
        {
            "id": "w.spear",
            "name": "Spear",
            "kind": "weapon",
            "description": "A basic spear from rulebook.",
            "tags": ["martial"],
            "damage": "1d6",
        },
    )
    _write_json(
        tmp_path / "homebrew" / "spear_override.json",
        {
            "id": "w.spear",
            "name": "Sunforged Spear",
            "kind": "weapon",
            "description": "A homebrew spear with a unique blade.",
            "tags": ["homebrew"],
            "damage": "1d8",
        },
    )

    store = CompendiumStore()
    store.load([tmp_path / "core_5e", tmp_path / "campaign", tmp_path / "homebrew"])

    entry = store.get_by_id("w.spear")
    assert entry is not None
    assert entry.name == "Sunforged Spear"
    assert entry.damage == "1d8"
    assert entry.source_path == str(tmp_path / "homebrew" / "spear_override.json")


def test_lookup_by_id_name_and_kind(tmp_path: Path) -> None:
    _build_root_with_examples(tmp_path)
    store = CompendiumStore()
    store.load([tmp_path / "core_5e", tmp_path / "campaign", tmp_path / "homebrew"])

    by_id = store.get_by_id("s.fireball")
    assert by_id is not None
    assert by_id.name == "Fireball"

    by_name = store.find_by_name("fireball")
    assert len(by_name) == 1
    assert by_name[0].id == "s.fireball"

    by_name_casefold = store.find_by_name("FIREBALL")
    assert len(by_name_casefold) == 1
    assert by_name_casefold[0].id == "s.fireball"

    spells = store.list_by_kind("spell")
    assert len(spells) == 1
    assert spells[0].id == "s.fireball"


def test_compendium_cli_lists_spell_kind(tmp_path: Path) -> None:
    _build_root_with_examples(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app, ["compendium", "--root", str(tmp_path), "--kind", "spell"]
    )

    assert result.exit_code == 0
    assert "s.fireball" in result.stdout
    assert "spell\tFireball" in result.stdout
    assert "\tspell\t" in result.stdout
