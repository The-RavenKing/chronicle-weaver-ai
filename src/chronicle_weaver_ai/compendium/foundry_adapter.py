"""Foundry VTT compendium bidirectional adapter.

Import:  Foundry VTT .json / .db (NeDB JSONL) → Chronicle Weaver compendium entries.
Export:  Chronicle Weaver compendium entries → Foundry VTT .db (NeDB JSONL).

Foundry document types handled
-------------------------------
- Actor  (type="npc")    → MonsterEntry
- Item   (type="weapon") → WeaponEntry
- Item   (type="spell")  → SpellEntry
- Item   (type="feat")   → FeatureEntry
- Item   (type="armor" | "equipment") → ArmorEntry (armour / shield detection)

Foundry VTT system namespace: ``system`` (dnd5e game system assumed).

Usage
-----
from chronicle_weaver_ai.compendium.foundry_adapter import (
    load_foundry_pack,
    export_to_foundry_pack,
)

entries = load_foundry_pack(Path("packs/weapons.db"))
export_to_foundry_pack(entries, Path("out/chronicle_core.db"))
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from chronicle_weaver_ai.compendium.models import (
    ArmorEntry,
    CompendiumEntry,
    FeatureEntry,
    MonsterAction,
    MonsterEntry,
    SpellEntry,
    WeaponEntry,
)

# ---------------------------------------------------------------------------
# Public import helpers
# ---------------------------------------------------------------------------


def load_foundry_pack(path: Path) -> list[CompendiumEntry]:
    """Load a Foundry VTT pack (.json or .db) and return typed compendium entries.

    .db files are NeDB JSONL — one JSON object per line.
    .json files may be a single document or a list.
    """
    suffix = path.suffix.lower()
    raw_docs: list[dict[str, Any]] = []

    if suffix == ".db":
        raw_docs = _read_nedb(path)
    else:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        raw_docs = data if isinstance(data, list) else [data]

    entries: list[CompendiumEntry] = []
    for doc in raw_docs:
        entry = foundry_doc_to_entry(doc)
        if entry is not None:
            entries.append(entry)
    return entries


def foundry_doc_to_entry(doc: dict[str, Any]) -> CompendiumEntry | None:
    """Convert a single Foundry document dict to a Chronicle Weaver compendium entry.

    Returns None if the document type is unrecognised or lacks required data.
    """
    doc_type = str(doc.get("type", "")).lower()
    if doc_type == "npc":
        return _actor_to_monster(doc)
    if doc_type == "weapon":
        return _item_to_weapon(doc)
    if doc_type == "spell":
        return _item_to_spell(doc)
    if doc_type in {"feat", "feature"}:
        return _item_to_feature(doc)
    if doc_type in {"armor", "armour", "equipment", "loot"}:
        return _item_to_armor(doc)
    return None


# ---------------------------------------------------------------------------
# Public export helpers
# ---------------------------------------------------------------------------


def export_to_foundry_pack(
    entries: list[CompendiumEntry],
    output_path: Path,
) -> int:
    """Write Chronicle Weaver entries to a Foundry VTT .db (NeDB JSONL) file.

    Returns the number of entries written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output_path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            doc = entry_to_foundry(entry)
            if doc:
                fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
                written += 1
    return written


def entry_to_foundry(entry: CompendiumEntry) -> dict[str, Any] | None:
    """Convert a Chronicle Weaver compendium entry to a Foundry VTT document dict."""
    if isinstance(entry, MonsterEntry):
        return _monster_to_foundry(entry)
    if isinstance(entry, WeaponEntry):
        return _weapon_to_foundry(entry)
    if isinstance(entry, SpellEntry):
        return _spell_to_foundry(entry)
    if isinstance(entry, FeatureEntry):
        return _feature_to_foundry(entry)
    if isinstance(entry, ArmorEntry):
        return _armor_to_foundry(entry)
    return None


# ---------------------------------------------------------------------------
# Import: Foundry → Chronicle Weaver
# ---------------------------------------------------------------------------


def _actor_to_monster(doc: dict[str, Any]) -> MonsterEntry | None:
    name = doc.get("name", "")
    if not name:
        return None
    system = doc.get("system", doc.get("data", {}))
    attrs = system.get("attributes", {})
    abilities_raw = system.get("abilities", {})

    # HP
    hp_block = attrs.get("hp", {})
    hit_points = int(hp_block.get("value", hp_block.get("max", 8)))
    # AC
    ac_block = attrs.get("ac", {})
    armor_class = int(ac_block.get("value", ac_block.get("flat", 10)))
    # Speed
    movement = attrs.get("movement", {})
    speed_walk = int(movement.get("walk", movement.get("value", 30)))

    # Abilities
    abilities: dict[str, int] = {}
    for ab_key, ab_data in abilities_raw.items():
        short = ab_key[:3].lower()
        val = ab_data.get("value", 10) if isinstance(ab_data, dict) else int(ab_data)
        abilities[short] = int(val)

    # CR
    details = system.get("details", {})
    cr_raw = details.get("cr", None)
    challenge_rating = str(cr_raw) if cr_raw is not None else None

    # Size / type
    size_raw = details.get("type", {})
    if isinstance(size_raw, dict):
        creature_type = str(size_raw.get("value", ""))
    else:
        creature_type = str(size_raw)
    size_label = str(details.get("type", {}).get("swarm", "")) or _foundry_size(
        system.get("traits", {}).get("size", "")
    )

    # Actions from items
    actions: list[MonsterAction] = []
    for item in doc.get("items", []):
        action = _item_to_monster_action(item)
        if action is not None:
            actions.append(action)

    entry_id = _stable_id("m", name)
    description = str(doc.get("prototypeToken", {}).get("name", name))
    biog = system.get("details", {}).get("biography", {})
    if isinstance(biog, dict):
        desc_html = biog.get("value", "")
        description = _strip_html(desc_html) or name

    return MonsterEntry(
        id=entry_id,
        name=name,
        kind="monster",
        description=description,
        size=size_label,
        creature_type=creature_type,
        armor_class=armor_class,
        hit_points=hit_points,
        speed=speed_walk,
        abilities=abilities,
        actions=actions,
        challenge_rating=challenge_rating,
        tags=["imported", "foundry"],
    )


def _item_to_weapon(doc: dict[str, Any]) -> WeaponEntry | None:
    name = doc.get("name", "")
    if not name:
        return None
    system = doc.get("system", doc.get("data", {}))
    damage_block = system.get("damage", {})
    base_parts = damage_block.get("parts", [])
    damage_formula = ""
    damage_type = ""
    if (
        base_parts
        and isinstance(base_parts[0], (list, tuple))
        and len(base_parts[0]) >= 2
    ):
        damage_formula = str(base_parts[0][0])
        damage_type = str(base_parts[0][1])
    ability_mods = system.get("ability", "str")
    magic_bonus_raw = system.get("attackBonus", 0)
    try:
        magic_bonus = int(magic_bonus_raw) if magic_bonus_raw else 0
    except (ValueError, TypeError):
        magic_bonus = 0
    properties = [k for k, v in system.get("properties", {}).items() if v]

    entry_id = _stable_id("w", name)
    description_html = system.get("description", {}).get("value", "")
    description = _strip_html(description_html) or name

    return WeaponEntry(
        id=entry_id,
        name=name,
        kind="weapon",
        description=description,
        damage=damage_formula,
        damage_type=damage_type,
        properties=properties,
        attack_ability=ability_mods[:3].lower() if ability_mods else "str",
        magic_bonus=magic_bonus or None,
        tags=["imported", "foundry"],
    )


def _item_to_spell(doc: dict[str, Any]) -> SpellEntry | None:
    name = doc.get("name", "")
    if not name:
        return None
    system = doc.get("system", doc.get("data", {}))
    level = int(system.get("level", 0))
    school_block = system.get("school", "")
    school = str(school_block)
    casting_time = str(system.get("activation", {}).get("cost", 1))
    activation_type = str(system.get("activation", {}).get("type", "action"))
    action_type = _foundry_activation_to_action_type(activation_type)
    duration_block = system.get("duration", {})
    duration = (
        f"{duration_block.get('value','')} {duration_block.get('units','')}".strip()
    )
    range_block = system.get("range", {})
    spell_range = f"{range_block.get('value','')} {range_block.get('units','')}".strip()
    components_block = system.get("components", {})
    components: list[str] = []
    if components_block.get("vocal"):
        components.append("V")
    if components_block.get("somatic"):
        components.append("S")
    if components_block.get("material"):
        components.append("M")
    # Attack vs save
    attack_type_raw = str(system.get("actionType", ""))
    save_ability = None
    attack_type = None
    auto_hit = False
    if attack_type_raw in {"rsak", "msak"}:
        attack_type = "spell_attack"
    elif attack_type_raw == "save":
        save_block = system.get("save", {})
        save_ability = str(save_block.get("ability", "con"))
    elif attack_type_raw in {"heal", "abil", "util"}:
        auto_hit = True
    damage_block = system.get("damage", {})
    parts = damage_block.get("parts", [])
    effect_parts: list[str] = []
    if parts:
        for part in parts:
            if isinstance(part, (list, tuple)) and len(part) >= 1:
                effect_parts.append(str(part[0]))
    effect_summary = "; ".join(effect_parts) or system.get("description", {}).get(
        "value", ""
    )
    effect_summary = _strip_html(str(effect_summary))[:200]

    entry_id = _stable_id("s", name)
    description_html = system.get("description", {}).get("value", "")
    description = _strip_html(description_html) or name

    return SpellEntry(
        id=entry_id,
        name=name,
        kind="spell",
        description=description,
        level=level,
        school=school,
        casting_time=casting_time,
        range=spell_range,
        components=components,
        duration=duration,
        action_type=action_type,
        attack_type=attack_type,
        save_ability=save_ability,
        auto_hit=auto_hit,
        effect_summary=effect_summary,
        tags=["imported", "foundry"],
    )


def _item_to_feature(doc: dict[str, Any]) -> FeatureEntry | None:
    name = doc.get("name", "")
    if not name:
        return None
    system = doc.get("system", doc.get("data", {}))
    activation_type = str(system.get("activation", {}).get("type", "passive"))
    action_type = _foundry_activation_to_action_type(activation_type)
    uses_block = system.get("uses", {})
    max_uses = uses_block.get("max", None)
    usage_key = _stable_id("res", name) if max_uses else None
    description_html = system.get("description", {}).get("value", "")
    description = _strip_html(description_html) or name
    effect_summary = description[:200]

    entry_id = _stable_id("f", name)

    return FeatureEntry(
        id=entry_id,
        name=name,
        kind="feature",
        description=description,
        action_type=action_type,
        usage_key=usage_key,
        effect_summary=effect_summary,
        tags=["imported", "foundry"],
    )


def _item_to_armor(doc: dict[str, Any]) -> ArmorEntry | None:
    name = doc.get("name", "")
    if not name:
        return None
    system = doc.get("system", doc.get("data", {}))
    armor_block = system.get("armor", system.get("armour", {}))
    armor_type_raw = str(armor_block.get("type", "light"))
    ac_base = int(armor_block.get("value", armor_block.get("base", 10)))
    max_dex_raw = armor_block.get("dex", None)
    max_dex = int(max_dex_raw) if max_dex_raw is not None else None
    str_req_raw = system.get("strength", None)
    str_req = int(str_req_raw) if str_req_raw else None
    armor_type = _foundry_armor_type(armor_type_raw)
    description_html = system.get("description", {}).get("value", "")
    description = _strip_html(description_html) or name
    entry_id = _stable_id("a", name)

    return ArmorEntry(
        id=entry_id,
        name=name,
        kind="armor",
        description=description,
        armor_class_base=ac_base,
        max_dex_bonus=max_dex,
        strength_requirement=str_req,
        armor_type=armor_type,
        tags=["imported", "foundry"],
    )


def _item_to_monster_action(item: dict[str, Any]) -> MonsterAction | None:
    if str(item.get("type", "")).lower() != "weapon":
        return None
    name = item.get("name", "")
    if not name:
        return None
    system = item.get("system", item.get("data", {}))
    attack_bonus_raw = system.get("attackBonus", 0)
    try:
        attack_bonus = int(attack_bonus_raw) if attack_bonus_raw else 0
    except (ValueError, TypeError):
        attack_bonus = 0
    damage_block = system.get("damage", {})
    parts = damage_block.get("parts", [])
    damage_formula = ""
    damage_type = ""
    if parts and isinstance(parts[0], (list, tuple)) and len(parts[0]) >= 1:
        damage_formula = str(parts[0][0])
        damage_type = str(parts[0][1]) if len(parts[0]) > 1 else ""
    if not damage_formula:
        return None
    return MonsterAction(
        name=name,
        attack_bonus=attack_bonus,
        damage_formula=damage_formula,
        damage_type=damage_type,
    )


# ---------------------------------------------------------------------------
# Export: Chronicle Weaver → Foundry
# ---------------------------------------------------------------------------


def _monster_to_foundry(entry: MonsterEntry) -> dict[str, Any]:
    foundry_id = _foundry_id(entry.id)
    abilities_block: dict[str, Any] = {}
    for ab in ("str", "dex", "con", "int", "wis", "cha"):
        val = entry.abilities.get(ab, 10)
        mod = (val - 10) // 2
        abilities_block[ab] = {"value": val, "mod": mod, "prof": 0, "save": mod}
    items: list[dict[str, Any]] = []
    for action in entry.actions:
        items.append(_monster_action_to_foundry_item(action))
    return {
        "_id": foundry_id,
        "name": entry.name,
        "type": "npc",
        "img": "icons/svg/mystery-man.svg",
        "system": {
            "abilities": abilities_block,
            "attributes": {
                "hp": {"value": entry.hit_points or 0, "max": entry.hit_points or 0},
                "ac": {
                    "value": entry.armor_class or 10,
                    "flat": entry.armor_class or 10,
                },
                "movement": {"walk": entry.speed},
            },
            "details": {
                "biography": {"value": f"<p>{entry.description}</p>"},
                "cr": (
                    float(entry.challenge_rating)
                    if entry.challenge_rating is not None
                    and _is_numeric(entry.challenge_rating)
                    else 0
                ),
                "type": {"value": entry.creature_type, "custom": ""},
            },
            "traits": {
                "size": _chronicle_size_to_foundry(entry.size),
            },
        },
        "items": items,
        "flags": {"chronicle-weaver": {"original_id": entry.id}},
    }


def _weapon_to_foundry(entry: WeaponEntry) -> dict[str, Any]:
    damage_parts = [[entry.damage or "1d4", entry.damage_type or "slashing"]]
    return {
        "_id": _foundry_id(entry.id),
        "name": entry.name,
        "type": "weapon",
        "img": "icons/svg/sword.svg",
        "system": {
            "description": {"value": f"<p>{entry.description}</p>"},
            "damage": {"parts": damage_parts},
            "ability": entry.attack_ability or "str",
            "attackBonus": entry.magic_bonus or 0,
            "properties": {p: True for p in (entry.properties or [])},
            "actionType": "mwak",
        },
        "flags": {"chronicle-weaver": {"original_id": entry.id}},
    }


def _spell_to_foundry(entry: SpellEntry) -> dict[str, Any]:
    action_type_foundry = (
        "rsak" if entry.attack_type else ("save" if entry.save_ability else "util")
    )
    save_block: dict[str, Any] = {}
    if entry.save_ability:
        save_block = {"ability": entry.save_ability, "dc": None, "scaling": "spell"}
    damage_parts = [[entry.effect_summary, ""]] if entry.effect_summary else []
    components = {
        "vocal": "V" in (entry.components or []),
        "somatic": "S" in (entry.components or []),
        "material": "M" in (entry.components or []),
    }
    return {
        "_id": _foundry_id(entry.id),
        "name": entry.name,
        "type": "spell",
        "img": "icons/svg/magic.svg",
        "system": {
            "description": {"value": f"<p>{entry.description}</p>"},
            "level": entry.level,
            "school": entry.school,
            "activation": {
                "type": _action_type_to_foundry(entry.action_type),
                "cost": 1,
            },
            "duration": {"value": "", "units": ""},
            "range": {"value": None, "units": "ft"},
            "components": components,
            "save": save_block,
            "damage": {"parts": damage_parts},
            "actionType": action_type_foundry,
        },
        "flags": {"chronicle-weaver": {"original_id": entry.id}},
    }


def _feature_to_foundry(entry: FeatureEntry) -> dict[str, Any]:
    return {
        "_id": _foundry_id(entry.id),
        "name": entry.name,
        "type": "feat",
        "img": "icons/svg/book.svg",
        "system": {
            "description": {"value": f"<p>{entry.description}</p>"},
            "activation": {
                "type": _action_type_to_foundry(entry.action_type),
                "cost": 1,
            },
            "uses": {
                "value": None,
                "max": None,
                "per": None,
            },
        },
        "flags": {"chronicle-weaver": {"original_id": entry.id}},
    }


def _armor_to_foundry(entry: ArmorEntry) -> dict[str, Any]:
    armor_type = _chronicle_armor_type_to_foundry(entry.armor_type)
    return {
        "_id": _foundry_id(entry.id),
        "name": entry.name,
        "type": "armor",
        "img": "icons/svg/shield.svg",
        "system": {
            "description": {"value": f"<p>{entry.description}</p>"},
            "armor": {
                "type": armor_type,
                "value": entry.armor_class_base,
                "dex": entry.max_dex_bonus,
            },
            "strength": entry.strength_requirement,
        },
        "flags": {"chronicle-weaver": {"original_id": entry.id}},
    }


def _monster_action_to_foundry_item(action: MonsterAction) -> dict[str, Any]:
    return {
        "_id": _foundry_id(action.name),
        "name": action.name,
        "type": "weapon",
        "system": {
            "damage": {"parts": [[action.damage_formula, action.damage_type]]},
            "attackBonus": action.attack_bonus,
            "actionType": "mwak",
            "equipped": True,
        },
    }


# ---------------------------------------------------------------------------
# NeDB helpers
# ---------------------------------------------------------------------------


def _read_nedb(path: Path) -> list[dict[str, Any]]:
    """Read a NeDB .db file (JSONL) and return valid document dicts."""
    docs: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                doc = json.loads(line)
                if isinstance(doc, dict):
                    docs.append(doc)
            except json.JSONDecodeError:
                pass
    return docs


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _stable_id(prefix: str, name: str) -> str:
    """Generate a stable, slug-like Chronicle Weaver ID from a Foundry entry name."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"{prefix}.{slug}"


def _foundry_id(text: str) -> str:
    """Generate a 16-char alphanumeric Foundry-compatible _id from any string."""
    h = hashlib.md5(
        text.encode()
    ).hexdigest()  # nosec — not for security, only ID generation
    # Foundry uses 16-char alphanumeric IDs
    return h[:16]


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).strip()


def _foundry_size(raw: str) -> str:
    mapping = {
        "tiny": "Tiny",
        "sm": "Small",
        "med": "Medium",
        "lg": "Large",
        "huge": "Huge",
        "grg": "Gargantuan",
    }
    return mapping.get(raw.lower(), raw.capitalize())


def _chronicle_size_to_foundry(size: str) -> str:
    mapping = {
        "tiny": "tiny",
        "small": "sm",
        "medium": "med",
        "large": "lg",
        "huge": "huge",
        "gargantuan": "grg",
    }
    return mapping.get(size.lower(), "med")


def _foundry_armor_type(raw: str) -> str:
    mapping = {
        "light": "light",
        "medium": "medium",
        "heavy": "heavy",
        "shield": "natural",
    }
    return mapping.get(raw.lower(), "light")


def _chronicle_armor_type_to_foundry(armor_type: str) -> str:
    mapping = {
        "light": "light",
        "medium": "medium",
        "heavy": "heavy",
        "natural": "natural",
    }
    return mapping.get(armor_type.lower(), "light")


def _foundry_activation_to_action_type(activation_type: str) -> str:
    mapping = {
        "action": "action",
        "bonus": "bonus_action",
        "reaction": "reaction",
        "none": "passive",
        "passive": "passive",
        "special": "action",
    }
    return mapping.get(activation_type.lower(), "action")


def _action_type_to_foundry(action_type: str) -> str:
    mapping = {
        "action": "action",
        "bonus_action": "bonus",
        "reaction": "reaction",
        "passive": "none",
        "none": "none",
    }
    return mapping.get(action_type.lower(), "action")


def _is_numeric(value: str | None) -> bool:
    if value is None:
        return False
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


__all__ = [
    "load_foundry_pack",
    "foundry_doc_to_entry",
    "export_to_foundry_pack",
    "entry_to_foundry",
]
