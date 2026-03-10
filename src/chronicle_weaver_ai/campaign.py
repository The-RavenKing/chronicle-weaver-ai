"""Campaign persistence — save/load campaign state to/from JSON.

CampaignState is the top-level durable model for a running campaign.
It embeds actors, scenes, session-log references, and any active encounter.

All serialisation helpers are pure functions so callers can build, mutate,
and persist state independently of the CLI.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chronicle_weaver_ai.encounter import (
    EncounterState,
    EncounterTurnOrder,
    InitiativeRoll,
)
from chronicle_weaver_ai.models import (
    Actor,
    CompanionPersona,
    GmPersona,
    PlayerPersona,
    TurnBudget,
    WorldClock,
)
from chronicle_weaver_ai.rules.combatant import Condition, CombatantSnapshot


# ── Domain models ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CampaignScene:
    """Minimal persistent scene reference.

    description_stub is a brief GM-written flavour line — never LLM-generated.
    combatants_present holds display names of entities known to be in the scene.
    environment_tags are short descriptors for the scene (e.g. "dim_light", "rain",
    "stone_floor") that the narrator may reference for atmosphere.
    """

    scene_id: str
    description_stub: str
    combat_active: bool = False
    combatants_present: list[str] = field(default_factory=list)
    environment_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CampaignState:
    """Top-level persistent campaign state.

    actors          — player-character Actor sheets keyed by actor_id.
    lorebook_refs   — file paths or IDs of external lorebook JSONL files.
    scenes          — scene references keyed by scene_id.
    session_log_refs— file paths of JSONL session event logs.
    active_encounter_id — encounter_id of the currently running encounter, or None.
    encounter_states    — embedded EncounterState snapshots keyed by encounter_id.
    """

    campaign_id: str
    campaign_name: str
    actors: dict[str, Actor]
    lorebook_refs: list[str]
    scenes: dict[str, CampaignScene]
    session_log_refs: list[str]
    active_encounter_id: str | None = None
    encounter_states: dict[str, EncounterState] = field(default_factory=dict)
    world_clock: WorldClock = field(default_factory=WorldClock)
    gm_persona: GmPersona = field(default_factory=GmPersona)
    player_persona: PlayerPersona = field(default_factory=PlayerPersona)
    companions: list[CompanionPersona] = field(default_factory=list)


# ── Scene lifecycle helpers ──────────────────────────────────────────────────


def scene_from_campaign(scene: CampaignScene) -> Any:
    """Convert a CampaignScene to a narration SceneState."""
    from chronicle_weaver_ai.narration.models import SceneState

    return SceneState(
        scene_id=scene.scene_id,
        description_stub=scene.description_stub,
        combat_active=scene.combat_active,
        combatants_present=list(scene.combatants_present),
        environment_tags=list(scene.environment_tags),
    )


def set_scene_combat_active(scene: CampaignScene, active: bool) -> CampaignScene:
    """Return a new scene with combat_active toggled."""
    return dataclasses.replace(scene, combat_active=active)


def update_scene_combatants(
    scene: CampaignScene, combatant_names: list[str]
) -> CampaignScene:
    """Return a new scene with combatants_present updated."""
    return dataclasses.replace(scene, combatants_present=combatant_names)


# ── Actor serialisation ───────────────────────────────────────────────────────


def actor_to_dict(actor: Actor) -> dict[str, Any]:
    """Serialise an Actor to a JSON-compatible dict.

    spell_slots int keys are stored as strings because JSON only allows
    string object keys; actor_from_dict reverses this.
    """
    return {
        "actor_id": actor.actor_id,
        "name": actor.name,
        "class_name": actor.class_name,
        "species_name": actor.species_name,
        "level": actor.level,
        "proficiency_bonus": actor.proficiency_bonus,
        "abilities": dict(actor.abilities),
        "equipped_weapon_ids": list(actor.equipped_weapon_ids),
        "known_spell_ids": list(actor.known_spell_ids),
        "feature_ids": list(actor.feature_ids),
        "item_ids": list(actor.item_ids),
        "spell_slots": {str(k): v for k, v in actor.spell_slots.items()},
        "resources": dict(actor.resources),
        "armor_class": actor.armor_class,
        "hit_points": actor.hit_points,
        "max_hit_points": actor.max_hit_points,
        "equipped_armor_id": actor.equipped_armor_id,
        "hit_die": actor.hit_die,
        "hit_dice_remaining": actor.hit_dice_remaining,
        "max_resources": dict(actor.max_resources),
        "spell_slots_max": {str(k): v for k, v in actor.spell_slots_max.items()},
    }


def actor_from_dict(d: dict[str, Any]) -> Actor:
    """Reconstruct an Actor from a serialised dict."""
    raw_slots: dict[str, Any] = d.get("spell_slots") or {}
    spell_slots: dict[int, int] = {int(k): int(v) for k, v in raw_slots.items()}
    return Actor(
        actor_id=d["actor_id"],
        name=d["name"],
        class_name=d.get("class_name"),
        species_name=d.get("species_name"),
        level=int(d.get("level", 1)),
        proficiency_bonus=int(d.get("proficiency_bonus", 2)),
        abilities=dict(d.get("abilities") or {}),
        equipped_weapon_ids=list(d.get("equipped_weapon_ids") or []),
        known_spell_ids=list(d.get("known_spell_ids") or []),
        feature_ids=list(d.get("feature_ids") or []),
        item_ids=list(d.get("item_ids") or []),
        spell_slots=spell_slots,
        resources=dict(d.get("resources") or {}),
        armor_class=d.get("armor_class"),
        hit_points=d.get("hit_points"),
        max_hit_points=d.get("max_hit_points"),
        equipped_armor_id=d.get("equipped_armor_id"),
        hit_die=d.get("hit_die"),
        hit_dice_remaining=d.get("hit_dice_remaining"),
        max_resources=dict(d.get("max_resources") or {}),
        spell_slots_max={
            int(k): int(v) for k, v in (d.get("spell_slots_max") or {}).items()
        },
    )


# ── CombatantSnapshot serialisation ──────────────────────────────────────────


def _condition_to_dict(c: Condition) -> dict[str, Any]:
    return {
        "condition_name": c.condition_name,
        "source": c.source,
        "duration_type": c.duration_type,
        "remaining_rounds": c.remaining_rounds,
    }


def _condition_from_dict(d: dict[str, Any]) -> Condition:
    return Condition(
        condition_name=d["condition_name"],
        source=d["source"],
        duration_type=d["duration_type"],  # type: ignore[arg-type]
        remaining_rounds=d.get("remaining_rounds"),
    )


def combatant_snapshot_to_dict(snap: CombatantSnapshot) -> dict[str, Any]:
    """Serialise a CombatantSnapshot to a JSON-compatible dict."""
    return {
        "combatant_id": snap.combatant_id,
        "display_name": snap.display_name,
        "source_type": snap.source_type,
        "source_id": snap.source_id,
        "armor_class": snap.armor_class,
        "hit_points": snap.hit_points,
        "max_hit_points": snap.max_hit_points,
        "equipped_armor_id": snap.equipped_armor_id,
        "abilities": dict(snap.abilities),
        "resources": dict(snap.resources),
        "proficiency_bonus": snap.proficiency_bonus,
        "compendium_refs": list(snap.compendium_refs),
        # metadata values are str in practice; cast for JSON safety
        "metadata": {
            k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
            for k, v in snap.metadata.items()
        },
        "conditions": [_condition_to_dict(c) for c in snap.conditions],
    }


def combatant_snapshot_from_dict(d: dict[str, Any]) -> CombatantSnapshot:
    """Reconstruct a CombatantSnapshot from a serialised dict."""
    return CombatantSnapshot(
        combatant_id=d["combatant_id"],
        display_name=d["display_name"],
        source_type=d["source_type"],
        source_id=d["source_id"],
        armor_class=d.get("armor_class"),
        hit_points=d.get("hit_points"),
        max_hit_points=d.get("max_hit_points"),
        equipped_armor_id=d.get("equipped_armor_id"),
        abilities=dict(d.get("abilities") or {}),
        resources=dict(d.get("resources") or {}),
        proficiency_bonus=d.get("proficiency_bonus"),
        compendium_refs=list(d.get("compendium_refs") or []),
        metadata=dict(d.get("metadata") or {}),
        conditions=tuple(_condition_from_dict(c) for c in (d.get("conditions") or [])),
    )


# ── EncounterState serialisation ──────────────────────────────────────────────


def encounter_state_to_dict(state: EncounterState) -> dict[str, Any]:
    """Serialise an EncounterState to a JSON-compatible dict."""
    order = state.turn_order
    return {
        "encounter_id": state.encounter_id,
        "active": state.active,
        "defeated_ids": sorted(state.defeated_ids),
        "combatants": {
            cid: combatant_snapshot_to_dict(snap)
            for cid, snap in state.combatants.items()
        },
        "turn_order": {
            "encounter_id": order.encounter_id,
            "combatant_ids": list(order.combatant_ids),
            "current_turn_index": order.current_turn_index,
            "current_round": order.current_round,
            "initiative_rolls": {
                cid: dataclasses.asdict(roll)
                for cid, roll in order.initiative_rolls.items()
            },
            "current_turn_budget": dataclasses.asdict(order.current_turn_budget),
        },
        # engaged_pairs: each frozenset of two IDs is stored as a sorted 2-element list
        "engaged_pairs": [
            sorted(pair)
            for pair in sorted(state.engaged_pairs, key=lambda p: sorted(p))
        ],
        "reactions_spent": sorted(state.reactions_spent),
    }


def encounter_state_from_dict(d: dict[str, Any]) -> EncounterState:
    """Reconstruct an EncounterState from a serialised dict."""
    tod: dict[str, Any] = d["turn_order"]
    initiative_rolls: dict[str, InitiativeRoll] = {
        cid: InitiativeRoll(**roll_d) for cid, roll_d in tod["initiative_rolls"].items()
    }
    turn_order = EncounterTurnOrder(
        encounter_id=tod["encounter_id"],
        combatant_ids=list(tod["combatant_ids"]),
        current_turn_index=int(tod["current_turn_index"]),
        current_round=int(tod["current_round"]),
        initiative_rolls=initiative_rolls,
        current_turn_budget=TurnBudget(**tod["current_turn_budget"]),
    )
    combatants: dict[str, CombatantSnapshot] = {
        cid: combatant_snapshot_from_dict(snap_d)
        for cid, snap_d in d["combatants"].items()
    }
    raw_pairs = d.get("engaged_pairs") or []
    engaged_pairs: frozenset[frozenset[str]] = frozenset(
        frozenset(pair) for pair in raw_pairs
    )
    reactions_spent: frozenset[str] = frozenset(d.get("reactions_spent") or [])
    return EncounterState(
        encounter_id=d["encounter_id"],
        combatants=combatants,
        turn_order=turn_order,
        active=bool(d.get("active", True)),
        defeated_ids=frozenset(d.get("defeated_ids") or []),
        engaged_pairs=engaged_pairs,
        reactions_spent=reactions_spent,
    )


# ── WorldClock / Persona serialisation ───────────────────────────────────────


def _clock_to_dict(clock: WorldClock) -> dict[str, Any]:
    return {"day": clock.day, "hour": clock.hour, "minute": clock.minute}


def _clock_from_dict(d: dict[str, Any]) -> WorldClock:
    return WorldClock(
        day=int(d.get("day", 1)),
        hour=int(d.get("hour", 8)),
        minute=int(d.get("minute", 0)),
    )


def _gm_persona_to_dict(p: GmPersona) -> dict[str, Any]:
    return {
        "gm_style": p.gm_style,
        "narrative_voice": p.narrative_voice,
        "detail_level": p.detail_level,
    }


def _gm_persona_from_dict(d: dict[str, Any]) -> GmPersona:
    return GmPersona(
        gm_style=str(d.get("gm_style", "balanced")),
        narrative_voice=str(d.get("narrative_voice", "third_person")),
        detail_level=str(d.get("detail_level", "medium")),
    )


def _player_persona_to_dict(p: PlayerPersona) -> dict[str, Any]:
    return {
        "character_name": p.character_name,
        "class_flavor": p.class_flavor,
        "pronouns": p.pronouns,
    }


def _player_persona_from_dict(d: dict[str, Any]) -> PlayerPersona:
    return PlayerPersona(
        character_name=str(d.get("character_name", "")),
        class_flavor=str(d.get("class_flavor", "")),
        pronouns=str(d.get("pronouns", "they/them")),
    )


def _companion_to_dict(c: CompanionPersona) -> dict[str, Any]:
    return {
        "companion_id": c.companion_id,
        "character_name": c.character_name,
        "class_flavor": c.class_flavor,
        "pronouns": c.pronouns,
        "role": c.role,
    }


def _companion_from_dict(d: dict[str, Any]) -> CompanionPersona:
    return CompanionPersona(
        companion_id=str(d.get("companion_id", "")),
        character_name=str(d.get("character_name", "")),
        class_flavor=str(d.get("class_flavor", "")),
        pronouns=str(d.get("pronouns", "they/them")),
        role=str(d.get("role", "party_member")),
    )


# ── CampaignScene serialisation ───────────────────────────────────────────────


def _scene_to_dict(scene: CampaignScene) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "description_stub": scene.description_stub,
        "combat_active": scene.combat_active,
        "combatants_present": list(scene.combatants_present),
        "environment_tags": list(scene.environment_tags),
    }


def _scene_from_dict(d: dict[str, Any]) -> CampaignScene:
    return CampaignScene(
        scene_id=d["scene_id"],
        description_stub=d.get("description_stub", ""),
        combat_active=bool(d.get("combat_active", False)),
        combatants_present=list(d.get("combatants_present") or []),
        environment_tags=list(d.get("environment_tags") or []),
    )


# ── CampaignState serialisation ───────────────────────────────────────────────


def campaign_to_dict(campaign: CampaignState) -> dict[str, Any]:
    """Serialise a CampaignState to a JSON-compatible dict."""
    return {
        "campaign_id": campaign.campaign_id,
        "campaign_name": campaign.campaign_name,
        "actors": {
            actor_id: actor_to_dict(actor)
            for actor_id, actor in campaign.actors.items()
        },
        "lorebook_refs": list(campaign.lorebook_refs),
        "scenes": {
            scene_id: _scene_to_dict(scene)
            for scene_id, scene in campaign.scenes.items()
        },
        "session_log_refs": list(campaign.session_log_refs),
        "active_encounter_id": campaign.active_encounter_id,
        "encounter_states": {
            enc_id: encounter_state_to_dict(enc)
            for enc_id, enc in campaign.encounter_states.items()
        },
        "world_clock": _clock_to_dict(campaign.world_clock),
        "gm_persona": _gm_persona_to_dict(campaign.gm_persona),
        "player_persona": _player_persona_to_dict(campaign.player_persona),
        "companions": [_companion_to_dict(c) for c in campaign.companions],
    }


def campaign_from_dict(d: dict[str, Any]) -> CampaignState:
    """Reconstruct a CampaignState from a serialised dict."""
    actors: dict[str, Actor] = {
        actor_id: actor_from_dict(actor_d)
        for actor_id, actor_d in (d.get("actors") or {}).items()
    }
    scenes: dict[str, CampaignScene] = {
        scene_id: _scene_from_dict(scene_d)
        for scene_id, scene_d in (d.get("scenes") or {}).items()
    }
    encounter_states: dict[str, EncounterState] = {
        enc_id: encounter_state_from_dict(enc_d)
        for enc_id, enc_d in (d.get("encounter_states") or {}).items()
    }
    raw_clock = d.get("world_clock") or {}
    raw_gm = d.get("gm_persona") or {}
    raw_player = d.get("player_persona") or {}
    companions = [
        _companion_from_dict(c)
        for c in (d.get("companions") or [])
        if isinstance(c, dict)
    ]
    return CampaignState(
        campaign_id=d["campaign_id"],
        campaign_name=d["campaign_name"],
        actors=actors,
        lorebook_refs=list(d.get("lorebook_refs") or []),
        scenes=scenes,
        session_log_refs=list(d.get("session_log_refs") or []),
        active_encounter_id=d.get("active_encounter_id"),
        encounter_states=encounter_states,
        world_clock=(
            _clock_from_dict(raw_clock) if isinstance(raw_clock, dict) else WorldClock()
        ),
        gm_persona=(
            _gm_persona_from_dict(raw_gm) if isinstance(raw_gm, dict) else GmPersona()
        ),
        player_persona=(
            _player_persona_from_dict(raw_player)
            if isinstance(raw_player, dict)
            else PlayerPersona()
        ),
        companions=companions,
    )


# ── File I/O ──────────────────────────────────────────────────────────────────


def save_campaign(campaign: CampaignState, path: Path) -> None:
    """Write campaign state to a JSON file at *path* (creates or overwrites)."""
    path.write_text(
        json.dumps(campaign_to_dict(campaign), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_campaign(path: Path) -> CampaignState:
    """Load and reconstruct a CampaignState from a JSON file at *path*."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Campaign file {path} must contain a JSON object")
    return campaign_from_dict(raw)
