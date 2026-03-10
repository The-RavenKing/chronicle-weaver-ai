"""Minimal FastAPI application exposing the Chronicle Weaver engine over HTTP.

All endpoints are thin: they validate input, delegate to existing library
functions, and return structured JSON.  No rules logic lives here.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from chronicle_weaver_ai.campaign import (
    CampaignScene,
    CampaignState,
    campaign_to_dict,
    load_campaign,
    save_campaign,
)
from chronicle_weaver_ai.compendium import (
    CompendiumStore,
    FeatureEntry,
    MonsterEntry,
    SpellEntry,
    WeaponEntry,
    resolve_compendium_roots,
)
from chronicle_weaver_ai.dice import LocalCSPRNGDiceProvider
from chronicle_weaver_ai.encounter import (
    EncounterState,
    create_encounter,
    current_combatant,
    end_turn,
    is_encounter_over,
    mark_defeated,
    update_combatant,
)
from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.memory.context_models import ContextBundle
from chronicle_weaver_ai.models import (
    Actor,
    GameMode,
    JSONValue,
    advance_time,
    clock_display,
)
from chronicle_weaver_ai.monster_turn import MonsterTurnResult, run_monster_turn
from chronicle_weaver_ai.narration.models import ActionResult, NarrationRequest
from chronicle_weaver_ai.narration.narrator import build_user_prompt
from chronicle_weaver_ai.rules import (
    consume_spell_slot,
    resolve_feature_use,
    resolve_spell_cast,
    resolve_weapon_attack,
    roll_death_save,
)
from chronicle_weaver_ai.rules.combatant import (
    CombatantSnapshot,
    combatant_from_monster_entry,
)
from chronicle_weaver_ai.rules.resolver import (
    ResolvedFeatureUse,
    ResolvedSpellCast,
    ResolvedWeaponAttack,
)

_COMPENDIUM_ROOT = Path("compendiums")
_CAMPAIGN_DIR = Path("campaigns")
_UI_DIR = Path("ui")


# ── App lifespan ──────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load shared state once at startup; tear down cleanly on shutdown."""
    store = CompendiumStore()
    try:
        if _COMPENDIUM_ROOT.exists():
            roots = resolve_compendium_roots(_COMPENDIUM_ROOT)
            store.load(roots)
    except Exception:
        pass  # empty store is valid — endpoints return 404 on missing entries

    # Seed in-memory scene store from any campaigns found on disk.
    scene_store: dict[str, CampaignScene] = {}
    if _CAMPAIGN_DIR.exists():
        for campaign_file in _CAMPAIGN_DIR.glob("*.json"):
            try:
                campaign = load_campaign(campaign_file)
                for scene_id, scene in campaign.scenes.items():
                    scene_store[scene_id] = scene
            except Exception:
                pass  # malformed campaign files are silently skipped

    app.state.compendium = store
    app.state.intent_router = IntentRouter(provider="rules", compendium_store=store)
    app.state.scenes = scene_store
    app.state.encounters = {}  # dict[str, EncounterState]
    yield


app = FastAPI(
    title="Chronicle Weaver API",
    version="0.1.0",
    description="Deterministic RPG engine HTTP interface.",
    lifespan=lifespan,
)

# Serve the UI shell from /static when the ui/ directory exists.
if _UI_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_UI_DIR)), name="static")


# ── UI shell entry point ───────────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
def root() -> Any:
    """Serve the single-page UI shell, or a JSON status when ui/ is absent."""
    ui_html = _UI_DIR / "index.html"
    if ui_html.exists():
        return FileResponse(str(ui_html))
    return {"status": "Chronicle Weaver API", "docs": "/docs"}


# ── FastAPI dependencies ──────────────────────────────────────────────────────


def _get_compendium(request: Request) -> CompendiumStore:
    return request.app.state.compendium  # type: ignore[no-any-return]


def _get_intent_router(request: Request) -> IntentRouter:
    return request.app.state.intent_router  # type: ignore[no-any-return]


def _get_scenes(request: Request) -> dict[str, CampaignScene]:
    return request.app.state.scenes  # type: ignore[no-any-return]


# ── Pydantic request models ───────────────────────────────────────────────────


class InterpretRequest(BaseModel):
    """Player text and current game mode for intent classification."""

    text: str
    mode: str = "exploration"


class ActorBody(BaseModel):
    """Minimal actor sheet for rules resolution requests."""

    actor_id: str
    name: str
    level: int = 1
    proficiency_bonus: int = 2
    abilities: dict[str, int] = Field(default_factory=dict)
    equipped_weapon_ids: list[str] = Field(default_factory=list)
    known_spell_ids: list[str] = Field(default_factory=list)
    feature_ids: list[str] = Field(default_factory=list)
    item_ids: list[str] = Field(default_factory=list)
    # JSON requires string keys; reconstructed as int on use
    spell_slots: dict[str, int] = Field(default_factory=dict)
    resources: dict[str, int] = Field(default_factory=dict)
    armor_class: int | None = None
    hit_points: int | None = None


class ResolveActionRequest(BaseModel):
    """Resolve deterministic action math for a compendium entry + actor."""

    action_type: str  # "weapon" | "spell" | "feature"
    entry_id: str
    actor: ActorBody | None = None


class NarrateRequest(BaseModel):
    """Build a grounded narration prompt from action context."""

    intent: str
    mechanic: str = "narrate_only"
    mode_from: str = "exploration"
    mode_to: str = "exploration"
    resolved_action: dict[str, Any] | None = None
    system_text: str = "You are the GM."


class PatchSceneRequest(BaseModel):
    """Partial update for a scene stored in memory."""

    description_stub: str | None = None
    combat_active: bool | None = None
    combatants_present: list[str] | None = None
    environment_tags: list[str] | None = None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _actor_body_to_actor(body: ActorBody) -> Actor:
    return Actor(
        actor_id=body.actor_id,
        name=body.name,
        level=body.level,
        proficiency_bonus=body.proficiency_bonus,
        abilities=dict(body.abilities),
        equipped_weapon_ids=list(body.equipped_weapon_ids),
        known_spell_ids=list(body.known_spell_ids),
        feature_ids=list(body.feature_ids),
        item_ids=list(body.item_ids),
        spell_slots={int(k): v for k, v in body.spell_slots.items()},
        resources=dict(body.resources),
        armor_class=body.armor_class,
        hit_points=body.hit_points,
    )


def _entry_to_dict(entry: Any) -> dict[str, Any]:
    """Convert any CompendiumEntry subclass to a JSON-safe dict."""
    return dataclasses.asdict(entry)


# ── POST /interpret ───────────────────────────────────────────────────────────


@app.post("/interpret")
def interpret(
    body: InterpretRequest,
    router: IntentRouter = Depends(_get_intent_router),
) -> dict[str, Any]:
    """Route player text to an intent using deterministic rules-first routing."""
    try:
        mode = GameMode(body.mode)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown mode: {body.mode!r}")

    result = router.route(text=body.text, current_mode=mode)
    return {
        "intent": result.intent.value,
        "mechanic": result.mechanic.value,
        "confidence": result.confidence,
        "rationale": result.rationale,
        "target": result.target,
        "entry_id": result.entry_id,
        "entry_kind": result.entry_kind,
        "entry_name": result.entry_name,
        "provider_used": result.provider_used,
        "is_valid": result.is_valid,
        "action_category": result.action_category.value,
    }


# ── POST /resolve-action ──────────────────────────────────────────────────────


@app.post("/resolve-action")
def resolve_action(
    body: ResolveActionRequest,
    store: CompendiumStore = Depends(_get_compendium),
) -> dict[str, Any]:
    """Resolve deterministic action math for a compendium entry and actor sheet."""
    entry = store.get_by_id(body.entry_id)
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"Entry not found: {body.entry_id!r}"
        )

    actor = _actor_body_to_actor(body.actor) if body.actor is not None else None

    if body.action_type == "weapon":
        if not isinstance(entry, WeaponEntry):
            raise HTTPException(
                status_code=422, detail=f"{body.entry_id!r} is not a weapon entry"
            )
        if actor is None:
            raise HTTPException(
                status_code=422, detail="weapon resolution requires an actor body"
            )
        rw: ResolvedWeaponAttack = resolve_weapon_attack(actor, entry)
        return {
            "action_kind": rw.action_kind,
            "entry_id": rw.entry_id,
            "entry_name": rw.entry_name,
            "attack_ability_used": rw.attack_ability_used,
            "attack_bonus_total": rw.attack_bonus_total,
            "damage_formula": rw.damage_formula,
            "action_cost": rw.action_cost,
            "action_available": rw.action_available,
            "explanation": rw.explanation,
        }

    if body.action_type == "spell":
        if not isinstance(entry, SpellEntry):
            raise HTTPException(
                status_code=422, detail=f"{body.entry_id!r} is not a spell entry"
            )
        if actor is None:
            raise HTTPException(
                status_code=422, detail="spell resolution requires an actor body"
            )
        rs: ResolvedSpellCast = resolve_spell_cast(actor, entry)
        return {
            "action_kind": rs.action_kind,
            "entry_id": rs.entry_id,
            "entry_name": rs.entry_name,
            "action_cost": rs.action_cost,
            "action_available": rs.action_available,
            "auto_hit": rs.auto_hit,
            "attack_type": rs.attack_type,
            "save_ability": rs.save_ability,
            "effect_summary": rs.effect_summary,
            "can_cast": rs.can_cast,
            "reason": rs.reason,
            "slot_level_used": rs.slot_level_used,
        }

    if body.action_type == "feature":
        if not isinstance(entry, FeatureEntry):
            raise HTTPException(
                status_code=422, detail=f"{body.entry_id!r} is not a feature entry"
            )
        if actor is None:
            raise HTTPException(
                status_code=422, detail="feature resolution requires an actor body"
            )
        rf: ResolvedFeatureUse = resolve_feature_use(actor, entry)
        return {
            "action_kind": rf.action_kind,
            "entry_id": rf.entry_id,
            "entry_name": rf.entry_name,
            "action_cost": rf.action_cost,
            "action_available": rf.action_available,
            "can_use": rf.can_use,
            "usage_key": rf.usage_key,
            "remaining_uses": rf.remaining_uses,
            "effect_summary": rf.effect_summary,
            "reason": rf.reason,
        }

    raise HTTPException(
        status_code=422,
        detail=f"Unknown action_type {body.action_type!r}. Expected: weapon | spell | feature",
    )


# ── POST /narrate ─────────────────────────────────────────────────────────────


@app.post("/narrate")
def narrate(body: NarrateRequest) -> dict[str, Any]:
    """Build and return a grounded narration prompt (does not call an LLM)."""
    bundle = ContextBundle(
        system_text=body.system_text,
        items=[],
        total_tokens_est=0,
    )
    resolved: dict[str, JSONValue] | None = None
    if body.resolved_action is not None:
        resolved = {k: v for k, v in body.resolved_action.items()}  # type: ignore[assignment]

    action = ActionResult(
        intent=body.intent,
        mechanic=body.mechanic,
        dice_roll=None,
        mode_from=body.mode_from,
        mode_to=body.mode_to,
        resolved_action=resolved,
    )
    narration_request = NarrationRequest(context=bundle, action=action)
    prompt = build_user_prompt(narration_request)
    return {"prompt": prompt, "system_text": body.system_text}


# ── GET /compendium ───────────────────────────────────────────────────────────


@app.get("/compendium")
def compendium_list(
    store: CompendiumStore = Depends(_get_compendium),
    kind: str | None = Query(default=None, description="Filter by entry kind"),
    name: str | None = Query(
        default=None, description="Filter by name (case-insensitive)"
    ),
    entry_id: str | None = Query(
        default=None, alias="id", description="Look up by exact id"
    ),
) -> dict[str, Any]:
    """List, filter, or look up compendium entries."""
    if entry_id is not None:
        entry = store.get_by_id(entry_id)
        if entry is None:
            raise HTTPException(
                status_code=404, detail=f"Entry not found: {entry_id!r}"
            )
        return {"entries": [_entry_to_dict(entry)], "count": 1}

    if name is not None:
        entries = store.find_by_name(name)
        return {"entries": [_entry_to_dict(e) for e in entries], "count": len(entries)}

    if kind is not None:
        entries = store.list_by_kind(kind)
        return {"entries": [_entry_to_dict(e) for e in entries], "count": len(entries)}

    all_entries = store.entries
    return {
        "entries": [_entry_to_dict(e) for e in all_entries],
        "count": len(all_entries),
    }


# ── GET /scene/{scene_id} ────────────────────────────────────────────────────


@app.get("/scene/{scene_id}")
def get_scene(
    scene_id: str,
    scenes: dict[str, CampaignScene] = Depends(_get_scenes),
) -> dict[str, Any]:
    """Return a scene from the in-memory scene store."""
    scene = scenes.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene not found: {scene_id!r}")
    return {
        "scene_id": scene.scene_id,
        "description_stub": scene.description_stub,
        "combat_active": scene.combat_active,
        "combatants_present": list(scene.combatants_present),
        "environment_tags": list(scene.environment_tags),
    }


# ── PATCH /scene/{scene_id} ───────────────────────────────────────────────────


@app.patch("/scene/{scene_id}")
def patch_scene(
    scene_id: str,
    body: PatchSceneRequest,
    scenes: dict[str, CampaignScene] = Depends(_get_scenes),
) -> dict[str, Any]:
    """Partially update a scene in the in-memory store.

    Fields omitted from the request body are left unchanged.
    If the scene does not exist it is created with the provided fields.
    """
    existing = scenes.get(scene_id) or CampaignScene(
        scene_id=scene_id,
        description_stub=body.description_stub or "",
    )
    import dataclasses

    updated = dataclasses.replace(
        existing,
        description_stub=(
            body.description_stub
            if body.description_stub is not None
            else existing.description_stub
        ),
        combat_active=(
            body.combat_active
            if body.combat_active is not None
            else existing.combat_active
        ),
        combatants_present=(
            body.combatants_present
            if body.combatants_present is not None
            else existing.combatants_present
        ),
        environment_tags=(
            body.environment_tags
            if body.environment_tags is not None
            else existing.environment_tags
        ),
    )
    scenes[scene_id] = updated
    return {
        "scene_id": updated.scene_id,
        "description_stub": updated.description_stub,
        "combat_active": updated.combat_active,
        "combatants_present": list(updated.combatants_present),
        "environment_tags": list(updated.environment_tags),
    }


# ── GET /campaign/{campaign_id} ───────────────────────────────────────────────


@app.get("/campaign/{campaign_id}")
def get_campaign(campaign_id: str) -> dict[str, Any]:
    """Load and return a persisted campaign by id.

    Looks for a JSON file at campaigns/{campaign_id}.json relative to the
    server working directory.
    """
    # Prevent path traversal: accept only a plain filename component.
    safe_id = Path(campaign_id).name
    if (
        not safe_id
        or safe_id != campaign_id
        or "/" in campaign_id
        or "\\" in campaign_id
    ):
        raise HTTPException(status_code=400, detail="Invalid campaign id")

    campaign_path = _CAMPAIGN_DIR / f"{safe_id}.json"
    if not campaign_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Campaign not found: {campaign_id!r}"
        )

    try:
        campaign = load_campaign(campaign_path)
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load campaign: {exc}"
        ) from exc

    return campaign_to_dict(campaign)


# ── PATCH /campaign/{campaign_id}/clock ───────────────────────────────────────


class AdvanceClockRequest(BaseModel):
    """Advance the in-world clock by a given number of minutes."""

    minutes: int = Field(..., ge=1, description="Minutes to advance the clock (≥1).")


def _load_campaign_or_404(campaign_id: str) -> tuple[CampaignState, Path]:
    """Load a campaign file or raise HTTP 404/400.  Returns (campaign, path)."""
    safe_id = Path(campaign_id).name
    if (
        not safe_id
        or safe_id != campaign_id
        or "/" in campaign_id
        or "\\" in campaign_id
    ):
        raise HTTPException(status_code=400, detail="Invalid campaign id")
    campaign_path = _CAMPAIGN_DIR / f"{safe_id}.json"
    if not campaign_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Campaign not found: {campaign_id!r}"
        )
    try:
        return load_campaign(campaign_path), campaign_path
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load campaign: {exc}"
        ) from exc


@app.patch("/campaign/{campaign_id}/clock")
def patch_campaign_clock(campaign_id: str, body: AdvanceClockRequest) -> dict[str, Any]:
    """Advance the world clock on a persisted campaign and save it."""
    campaign, path = _load_campaign_or_404(campaign_id)
    new_clock = advance_time(campaign.world_clock, body.minutes)
    updated = dataclasses.replace(campaign, world_clock=new_clock)
    save_campaign(updated, path)
    return {
        "campaign_id": campaign_id,
        "clock": clock_display(new_clock),
        "day": new_clock.day,
        "hour": new_clock.hour,
        "minute": new_clock.minute,
    }


# ── PATCH /campaign/{campaign_id}/persona ─────────────────────────────────────


class PatchPersonaRequest(BaseModel):
    """Partial update for GM and/or player persona on a campaign."""

    gm_style: str | None = None
    narrative_voice: str | None = None
    detail_level: str | None = None
    character_name: str | None = None
    class_flavor: str | None = None
    pronouns: str | None = None


@app.patch("/campaign/{campaign_id}/persona")
def patch_campaign_persona(
    campaign_id: str, body: PatchPersonaRequest
) -> dict[str, Any]:
    """Update GM and/or player persona fields on a persisted campaign."""
    campaign, path = _load_campaign_or_404(campaign_id)
    gm = campaign.gm_persona
    player = campaign.player_persona
    new_gm = dataclasses.replace(
        gm,
        gm_style=body.gm_style if body.gm_style is not None else gm.gm_style,
        narrative_voice=(
            body.narrative_voice
            if body.narrative_voice is not None
            else gm.narrative_voice
        ),
        detail_level=(
            body.detail_level if body.detail_level is not None else gm.detail_level
        ),
    )
    new_player = dataclasses.replace(
        player,
        character_name=(
            body.character_name
            if body.character_name is not None
            else player.character_name
        ),
        class_flavor=(
            body.class_flavor if body.class_flavor is not None else player.class_flavor
        ),
        pronouns=body.pronouns if body.pronouns is not None else player.pronouns,
    )
    updated = dataclasses.replace(
        campaign, gm_persona=new_gm, player_persona=new_player
    )
    save_campaign(updated, path)
    return {
        "campaign_id": campaign_id,
        "gm_persona": dataclasses.asdict(new_gm),
        "player_persona": dataclasses.asdict(new_player),
    }


# ── POST /lore/check-conflicts ────────────────────────────────────────────────


class CheckConflictsRequest(BaseModel):
    """Lore items and lorebook path to check for conflicts."""

    queue_path: str = Field(..., description="Path to the lore queue JSONL file.")
    lorebook_path: str = Field(..., description="Path to the lorebook JSONL file.")
    status: str = Field(
        "pending", description="Filter queue by status (pending/approved/all)."
    )


@app.post("/lore/check-conflicts")
def lore_check_conflicts(body: CheckConflictsRequest) -> dict[str, Any]:
    """Check a lore queue file against a lorebook for conflicts."""
    from chronicle_weaver_ai.lore.store import LoreQueueStore, LorebookStore

    queue_path = Path(body.queue_path)
    lorebook_path = Path(body.lorebook_path)
    if not queue_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Queue file not found: {body.queue_path!r}"
        )
    if not lorebook_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Lorebook file not found: {body.lorebook_path!r}"
        )

    lorebook_store = LorebookStore()
    lorebook = lorebook_store.load(str(lorebook_path))
    queue_store = LoreQueueStore()
    reports = queue_store.check_conflicts(str(queue_path), lorebook, status=body.status)
    return {
        "conflict_count": len(reports),
        "conflicts": [dataclasses.asdict(r) for r in reports],
    }


# ── Encounter session store dependency ────────────────────────────────────────


def _get_encounters(request: Request) -> dict[str, EncounterState]:
    return request.app.state.encounters  # type: ignore[no-any-return]


# ── Serialisation ─────────────────────────────────────────────────────────────


def _snap_to_dict(snap: CombatantSnapshot) -> dict[str, Any]:
    return {
        "combatant_id": snap.combatant_id,
        "display_name": snap.display_name,
        "source_type": snap.source_type,
        "source_id": snap.source_id,
        "armor_class": snap.armor_class,
        "hit_points": snap.hit_points,
        "max_hit_points": snap.max_hit_points,
        "abilities": snap.abilities,
        "conditions": [
            {
                "condition_name": c.condition_name,
                "source": c.source,
                "duration_type": c.duration_type,
                "remaining_rounds": c.remaining_rounds,
            }
            for c in snap.conditions
        ],
        "death_save_successes": snap.death_save_successes,
        "death_save_failures": snap.death_save_failures,
        "concentration_spell_id": snap.concentration_spell_id,
    }


def _encounter_to_dict(enc: EncounterState) -> dict[str, Any]:
    order = enc.turn_order
    current_id = (
        order.combatant_ids[order.current_turn_index] if order.combatant_ids else None
    )
    return {
        "encounter_id": enc.encounter_id,
        "active": enc.active,
        "round": order.current_round,
        "current_combatant_id": current_id,
        "turn_order": order.combatant_ids,
        "defeated_ids": sorted(enc.defeated_ids),
        "is_over": is_encounter_over(enc),
        "turn_budget": {
            "action": order.current_turn_budget.action,
            "bonus_action": order.current_turn_budget.bonus_action,
            "reaction": order.current_turn_budget.reaction,
        },
        "combatants": {
            cid: _snap_to_dict(snap) for cid, snap in enc.combatants.items()
        },
    }


def _monster_turn_to_dict(result: MonsterTurnResult) -> dict[str, Any]:
    resolved = None
    if result.resolved_attack is not None:
        resolved = {
            "action_name": result.resolved_attack.action_name,
            "attack_bonus_total": result.resolved_attack.attack_bonus_total,
            "damage_formula": result.resolved_attack.damage_formula,
        }
    return {
        "combatant_id": result.combatant_id,
        "action_name": result.action_name,
        "target_id": result.target_id,
        "resolved_attack": resolved,
        "attack_roll": result.attack_roll,
        "attack_total": result.attack_total,
        "hit": result.hit,
        "damage_total": result.damage_total,
        "damage_rolls": result.damage_rolls,
        "target_hp_before": result.target_hp_before,
        "target_hp_after": result.target_hp_after,
        "target_defeated": result.target_defeated,
        "target_dying": result.target_dying,
        "xp_awarded": result.xp_awarded,
    }


# ── POST /encounter ────────────────────────────────────────────────────────────


class CombatantSpec(BaseModel):
    """Specification for one combatant joining an encounter."""

    combatant_id: str
    source_type: str = "monster"  # "actor" | "monster" | "companion"
    # For monsters: either source_id refers to a compendium monster entry
    source_id: str
    display_name: str | None = None
    # Override stats (optional — if omitted, loaded from compendium)
    armor_class: int | None = None
    hit_points: int | None = None
    max_hit_points: int | None = None
    abilities: dict[str, int] | None = None


class CreateEncounterRequest(BaseModel):
    """Create a fresh encounter with the given combatants."""

    encounter_id: str
    combatants: list[CombatantSpec]
    seed: int | None = None  # If provided, used to seed a deterministic dice provider


@app.post("/encounter", status_code=201)
def create_encounter_endpoint(
    body: CreateEncounterRequest,
    store: CompendiumStore = Depends(_get_compendium),
    encounters: dict[str, EncounterState] = Depends(_get_encounters),
) -> dict[str, Any]:
    """Create a new encounter, roll initiative, and store it in session.

    Combatants can be monsters (looked up from compendium), actors (passed as
    stat overrides), or companions.  Returns the full initial encounter state.
    """
    if body.encounter_id in encounters:
        raise HTTPException(
            status_code=409, detail=f"Encounter {body.encounter_id!r} already exists"
        )

    dice = LocalCSPRNGDiceProvider()

    snapshots: list[CombatantSnapshot] = []
    for spec in body.combatants:
        if spec.source_type == "monster":
            entry = store.get_by_id(spec.source_id)
            if entry is None:
                raise HTTPException(
                    status_code=404, detail=f"Monster not found: {spec.source_id!r}"
                )
            if not isinstance(entry, MonsterEntry):
                raise HTTPException(
                    status_code=422, detail=f"{spec.source_id!r} is not a monster entry"
                )
            snap = combatant_from_monster_entry(entry)
            # Allow overrides
            if spec.combatant_id != snap.combatant_id or any(
                v is not None
                for v in [spec.armor_class, spec.hit_points, spec.display_name]
            ):
                import dataclasses as _dc

                snap = _dc.replace(
                    snap,
                    combatant_id=spec.combatant_id,
                    display_name=spec.display_name or snap.display_name,
                    armor_class=(
                        spec.armor_class
                        if spec.armor_class is not None
                        else snap.armor_class
                    ),
                    hit_points=(
                        spec.hit_points
                        if spec.hit_points is not None
                        else snap.hit_points
                    ),
                    max_hit_points=(
                        spec.max_hit_points
                        if spec.max_hit_points is not None
                        else snap.max_hit_points
                    ),
                )
        else:
            # Actor / companion — stat overrides are mandatory
            if spec.hit_points is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"hit_points required for {spec.source_type} combatant {spec.combatant_id!r}",
                )
            snap = CombatantSnapshot(
                combatant_id=spec.combatant_id,
                display_name=spec.display_name or spec.combatant_id,
                source_type=spec.source_type,
                source_id=spec.source_id,
                armor_class=spec.armor_class,
                hit_points=spec.hit_points,
                max_hit_points=spec.max_hit_points or spec.hit_points,
                abilities=spec.abilities or {},
            )
        snapshots.append(snap)

    encounter = create_encounter(body.encounter_id, snapshots, dice)
    encounters[body.encounter_id] = encounter
    return _encounter_to_dict(encounter)


# ── GET /encounter/{encounter_id} ─────────────────────────────────────────────


@app.get("/encounter/{encounter_id}")
def get_encounter(
    encounter_id: str,
    encounters: dict[str, EncounterState] = Depends(_get_encounters),
) -> dict[str, Any]:
    """Return the current state of an encounter."""
    enc = encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(
            status_code=404, detail=f"Encounter not found: {encounter_id!r}"
        )
    return _encounter_to_dict(enc)


# ── POST /encounter/{encounter_id}/player-action ──────────────────────────────


class PlayerActionRequest(BaseModel):
    """Submit a player action in the current encounter."""

    action_type: str  # "weapon" | "spell" | "feature"
    entry_id: str
    target_id: str | None = None
    actor: ActorBody | None = None


@app.post("/encounter/{encounter_id}/player-action")
def encounter_player_action(
    encounter_id: str,
    body: PlayerActionRequest,
    store: CompendiumStore = Depends(_get_compendium),
    encounters: dict[str, EncounterState] = Depends(_get_encounters),
) -> dict[str, Any]:
    """Resolve a player action in the current encounter turn.

    - Weapon: resolves attack math, rolls dice, applies damage. Supports Extra Attack.
    - Spell: checks slots, consumes one slot on success; returns updated actor if provided.
    - Feature: resolves feature availability.
    - Target: if target_id is provided and the action deals damage, HP is updated in the encounter state.
    """
    enc = encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(
            status_code=404, detail=f"Encounter not found: {encounter_id!r}"
        )
    if is_encounter_over(enc):
        raise HTTPException(status_code=409, detail="Encounter is already over")

    entry = store.get_by_id(body.entry_id)
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"Entry not found: {body.entry_id!r}"
        )

    actor = _actor_body_to_actor(body.actor) if body.actor else None
    dice = LocalCSPRNGDiceProvider()

    attacks: list[dict[str, Any]] = []
    updated_actor_slots: dict[str, int] | None = None
    result_payload: dict[str, Any] = {
        "encounter_id": encounter_id,
        "action_type": body.action_type,
        "entry_id": body.entry_id,
    }

    # ── Weapon ────────────────────────────────────────────────────────────────
    if body.action_type == "weapon":
        if not isinstance(entry, WeaponEntry):
            raise HTTPException(
                status_code=422, detail=f"{body.entry_id!r} is not a weapon"
            )
        if actor is None:
            raise HTTPException(
                status_code=422, detail="actor required for weapon action"
            )

        from chronicle_weaver_ai.dice import (
            roll_d20_record,
            roll_damage_formula as _roll_dmg,
        )

        rw: ResolvedWeaponAttack = resolve_weapon_attack(actor, entry)
        if not rw.action_available:
            raise HTTPException(
                status_code=409, detail="Action budget already spent this turn"
            )

        target_snap = enc.combatants.get(body.target_id) if body.target_id else None
        current_enc = enc

        for _ in range(rw.attack_count):  # Extra Attack support
            attack_record = roll_d20_record(dice)
            attack_total = attack_record.value + rw.attack_bonus_total
            hit = (
                target_snap is not None
                and target_snap.armor_class is not None
                and attack_total >= target_snap.armor_class
            )

            dmg_result = None
            if hit and target_snap is not None and body.target_id is not None:
                dmg_result = _roll_dmg(rw.damage_formula, dice)
                from chronicle_weaver_ai.rules.combatant import (
                    apply_damage as _apply_dmg,
                )

                damaged = _apply_dmg(target_snap, dmg_result.damage_total)
                current_enc = update_combatant(current_enc, damaged)
                if isinstance(damaged.hit_points, int) and damaged.hit_points == 0:
                    if target_snap.source_type == "monster":
                        current_enc = mark_defeated(current_enc, body.target_id)
                target_snap = current_enc.combatants.get(body.target_id)

            attacks.append(
                {
                    "attack_roll": attack_record.value,
                    "attack_bonus": rw.attack_bonus_total,
                    "attack_total": attack_total,
                    "target_ac": target_snap.armor_class if target_snap else None,
                    "hit": hit,
                    "damage_total": dmg_result.damage_total if dmg_result else None,
                    "damage_rolls": list(dmg_result.damage_rolls) if dmg_result else [],
                    "target_hp_after": target_snap.hit_points if target_snap else None,
                    "target_defeated": (
                        body.target_id in current_enc.defeated_ids
                        if body.target_id
                        else False
                    ),
                }
            )

        encounters[encounter_id] = current_enc
        result_payload.update(
            {
                "action_kind": "attack",
                "entry_name": rw.entry_name,
                "damage_formula": rw.damage_formula,
                "attack_count": rw.attack_count,
                "attacks": attacks,
                "encounter": _encounter_to_dict(current_enc),
            }
        )

    # ── Spell ─────────────────────────────────────────────────────────────────
    elif body.action_type == "spell":
        if not isinstance(entry, SpellEntry):
            raise HTTPException(
                status_code=422, detail=f"{body.entry_id!r} is not a spell"
            )
        if actor is None:
            raise HTTPException(
                status_code=422, detail="actor required for spell action"
            )

        rs: ResolvedSpellCast = resolve_spell_cast(actor, entry)
        if rs.can_cast and rs.slot_level_used is not None:
            actor = consume_spell_slot(actor, rs.slot_level_used)
            updated_actor_slots = {str(k): v for k, v in actor.spell_slots.items()}

        result_payload.update(
            {
                "action_kind": "cast_spell",
                "entry_name": rs.entry_name,
                "action_cost": rs.action_cost,
                "action_available": rs.action_available,
                "can_cast": rs.can_cast,
                "auto_hit": rs.auto_hit,
                "attack_type": rs.attack_type,
                "save_ability": rs.save_ability,
                "effect_summary": rs.effect_summary,
                "slot_level_used": rs.slot_level_used,
                "reason": rs.reason,
                "updated_spell_slots": updated_actor_slots,
                "encounter": _encounter_to_dict(enc),
            }
        )

    # ── Feature ───────────────────────────────────────────────────────────────
    elif body.action_type == "feature":
        if not isinstance(entry, FeatureEntry):
            raise HTTPException(
                status_code=422, detail=f"{body.entry_id!r} is not a feature"
            )
        if actor is None:
            raise HTTPException(
                status_code=422, detail="actor required for feature action"
            )

        rf: ResolvedFeatureUse = resolve_feature_use(actor, entry)
        result_payload.update(
            {
                "action_kind": "use_feature",
                "entry_name": rf.entry_name,
                "action_cost": rf.action_cost,
                "action_available": rf.action_available,
                "can_use": rf.can_use,
                "usage_key": rf.usage_key,
                "remaining_uses": rf.remaining_uses,
                "effect_summary": rf.effect_summary,
                "reason": rf.reason,
                "encounter": _encounter_to_dict(enc),
            }
        )

    else:
        raise HTTPException(
            status_code=422, detail=f"Unknown action_type {body.action_type!r}"
        )

    return result_payload


# ── POST /encounter/{encounter_id}/monster-turn ───────────────────────────────


@app.post("/encounter/{encounter_id}/monster-turn")
def encounter_monster_turn(
    encounter_id: str,
    encounters: dict[str, EncounterState] = Depends(_get_encounters),
    store: CompendiumStore = Depends(_get_compendium),
) -> dict[str, Any]:
    """Run the current monster's turn deterministically.

    Looks up the active combatant's monster entry from the compendium,
    executes the turn, updates the encounter state.
    """
    enc = encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(
            status_code=404, detail=f"Encounter not found: {encounter_id!r}"
        )
    if is_encounter_over(enc):
        raise HTTPException(status_code=409, detail="Encounter is already over")

    active_id = current_combatant(enc.turn_order)
    active_snap = enc.combatants.get(active_id)
    if active_snap is None or active_snap.source_type != "monster":
        raise HTTPException(
            status_code=409,
            detail=f"Current combatant {active_id!r} is not a monster (type={active_snap.source_type if active_snap else 'unknown'}). Use /player-action or /death-save instead.",
        )

    monster_entry = store.get_by_id(active_snap.source_id)
    if monster_entry is None or not isinstance(monster_entry, MonsterEntry):
        raise HTTPException(
            status_code=404,
            detail=f"Monster compendium entry not found for {active_snap.source_id!r}",
        )

    dice = LocalCSPRNGDiceProvider()
    new_enc, turn_result = run_monster_turn(enc, monster_entry, dice)
    encounters[encounter_id] = new_enc

    return {
        "encounter_id": encounter_id,
        "turn": _monster_turn_to_dict(turn_result),
        "encounter": _encounter_to_dict(new_enc),
    }


# ── POST /encounter/{encounter_id}/end-turn ───────────────────────────────────


@app.post("/encounter/{encounter_id}/end-turn")
def encounter_end_turn(
    encounter_id: str,
    encounters: dict[str, EncounterState] = Depends(_get_encounters),
) -> dict[str, Any]:
    """Advance the encounter to the next combatant's turn."""
    enc = encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(
            status_code=404, detail=f"Encounter not found: {encounter_id!r}"
        )
    if is_encounter_over(enc):
        raise HTTPException(status_code=409, detail="Encounter is already over")

    new_enc = end_turn(enc)
    encounters[encounter_id] = new_enc

    order = new_enc.turn_order
    next_id = (
        order.combatant_ids[order.current_turn_index] if order.combatant_ids else None
    )
    next_snap = new_enc.combatants.get(next_id) if next_id else None

    return {
        "encounter_id": encounter_id,
        "current_round": order.current_round,
        "current_combatant_id": next_id,
        "current_source_type": next_snap.source_type if next_snap else None,
        "is_over": is_encounter_over(new_enc),
        "encounter": _encounter_to_dict(new_enc),
    }


# ── POST /encounter/{encounter_id}/death-save ─────────────────────────────────


class DeathSaveRequest(BaseModel):
    """Roll a death saving throw for a dying combatant."""

    combatant_id: str


@app.post("/encounter/{encounter_id}/death-save")
def encounter_death_save(
    encounter_id: str,
    body: DeathSaveRequest,
    encounters: dict[str, EncounterState] = Depends(_get_encounters),
) -> dict[str, Any]:
    """Roll a death saving throw for a dying actor or companion.

    - 3 successes → stable (no longer dying)
    - 3 failures → dead (marked as defeated)
    Returns the roll result and updated encounter state.
    """
    enc = encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(
            status_code=404, detail=f"Encounter not found: {encounter_id!r}"
        )

    snap = enc.combatants.get(body.combatant_id)
    if snap is None:
        raise HTTPException(
            status_code=404, detail=f"Combatant not found: {body.combatant_id!r}"
        )
    if snap.hit_points != 0 or snap.source_type not in ("actor", "companion"):
        raise HTTPException(
            status_code=409,
            detail=f"{body.combatant_id!r} is not dying (hp={snap.hit_points}, type={snap.source_type})",
        )
    if body.combatant_id in enc.defeated_ids:
        raise HTTPException(
            status_code=409, detail=f"{body.combatant_id!r} is already defeated"
        )

    dice = LocalCSPRNGDiceProvider()
    new_snap, save_result = roll_death_save(snap, dice)
    enc = update_combatant(enc, new_snap)

    # 3 failures → mark as defeated
    if save_result.outcome == "dead":
        enc = mark_defeated(enc, body.combatant_id)

    encounters[encounter_id] = enc

    return {
        "encounter_id": encounter_id,
        "combatant_id": body.combatant_id,
        "roll": save_result.roll,
        "outcome": save_result.outcome,
        "successes_added": save_result.successes_added,
        "failures_added": save_result.failures_added,
        "total_successes": save_result.new_successes,
        "total_failures": save_result.new_failures,
        "now_defeated": save_result.outcome == "dead",
        "encounter": _encounter_to_dict(enc),
    }
