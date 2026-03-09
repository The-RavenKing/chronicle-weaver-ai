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

from chronicle_weaver_ai.campaign import campaign_to_dict, load_campaign
from chronicle_weaver_ai.compendium import (
    CompendiumStore,
    FeatureEntry,
    SpellEntry,
    WeaponEntry,
    resolve_compendium_roots,
)
from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.memory.context_models import ContextBundle
from chronicle_weaver_ai.models import Actor, GameMode, JSONValue
from chronicle_weaver_ai.narration.models import ActionResult, NarrationRequest
from chronicle_weaver_ai.narration.narrator import build_user_prompt
from chronicle_weaver_ai.rules import (
    resolve_feature_use,
    resolve_spell_cast,
    resolve_weapon_attack,
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

    app.state.compendium = store
    app.state.intent_router = IntentRouter(provider="rules", compendium_store=store)
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
