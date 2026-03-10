"""Typer CLI for deterministic Chronicle Weaver demo flow."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
import re
from pathlib import Path
from collections.abc import Mapping

import typer

from chronicle_weaver_ai.dice import (
    FixedEntropyDiceProvider,
    LocalCSPRNGDiceProvider,
    SeededDiceProvider,
    roll_damage_formula,
    roll_d20_record,
)
from chronicle_weaver_ai.engine import Engine, reduce_state
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.compendium import (
    FeatureEntry,
    CompendiumLoadError,
    CompendiumStore,
    SpellEntry,
    WeaponEntry,
    resolve_compendium_roots,
)
from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.lore.store import (
    LoreQueueStore,
    LorebookStore,
    build_queue_items_from_scribe,
)
from chronicle_weaver_ai.lore.normalize import (
    canonicalize_entity_record,
    fact_id,
    normalize_name,
    player_entity,
)
from chronicle_weaver_ai.memory.context_builder import ContextBuilder
from chronicle_weaver_ai.memory.context_models import ContextBundle
from chronicle_weaver_ai.models import (
    Actor,
    DiceProvider,
    EngineOutput,
    Event,
    GameMode,
    GameState,
    GmPersona,
    IntentResult,
    JSONValue,
    Mechanic,
    PlayerPersona,
    TurnBudget,
    advance_time,
    clock_display,
)
from chronicle_weaver_ai.narration.models import (
    ActionResult,
    NarrationRequest,
    SceneState,
)
from chronicle_weaver_ai.narration.narrator import (
    Narrator,
    build_prompt_parts,
    get_narrator,
)
from chronicle_weaver_ai.retrieval.lexical import Doc, retrieve
from chronicle_weaver_ai.rules import (
    CombatantSnapshot,
    apply_damage,
    attack_roll_mode,
    combatant_from_actor,
    combatant_from_monster_entry,
    is_blocked_by_conditions,
    resolve_feature_use,
    resolve_spell_cast,
    resolve_weapon_attack,
)
from chronicle_weaver_ai.compendium.models import MonsterEntry
from chronicle_weaver_ai.encounter import (
    EncounterState,
    create_encounter,
    current_combatant,
    end_turn,
    engage,
    is_encounter_over,
    mark_defeated,
    update_combatant,
)
from chronicle_weaver_ai.scribe.scribe import run_lore_scribe
from chronicle_weaver_ai.encounter_events import (
    emit_attack_resolved,
    emit_combatant_defeated,
    emit_encounter_ended,
    emit_encounter_started,
    emit_hp_changed,
    emit_turn_started,
)

app = typer.Typer(add_completion=False, help="Chronicle Weaver deterministic CLI.")

DEFAULT_ENEMY_AC = 13

_compendium_store_cache: CompendiumStore | None = None


@app.callback()
def main() -> None:
    """CLI root callback."""


@app.command()
def demo(
    player_input: str | None = typer.Option(
        None, "--player-input", help="Free text action."
    ),
    compendium_root: list[str] = typer.Option(
        ["compendiums"],
        "--compendium-root",
        help=(
            "Optional compendium root directories for intent matching. "
            "Repeat to include multiple roots."
        ),
    ),
    seed: int | None = typer.Option(
        None, "--seed", help="Seed deterministic provider for repeatable runs."
    ),
    fixed_entropy: int | None = typer.Option(
        None, "--fixed-entropy", help="Single fixed u32 entropy sample for testing."
    ),
    save: str | None = typer.Option(
        None, "--save", help="Append newly generated events to JSONL file."
    ),
    load: str | None = typer.Option(
        None,
        "--load",
        help="Load and replay events from JSONL before processing input.",
    ),
    replay: str | None = typer.Option(
        None,
        "--replay",
        help="Read-only replay from JSONL, print final mode, and exit.",
    ),
    intent_provider: str = typer.Option(
        "auto",
        "--intent-provider",
        help="Intent provider: auto|rules|ollama|openai.",
    ),
    narrator_provider: str = typer.Option(
        "auto",
        "--narrator-provider",
        help="Narrator provider: auto|ollama|openai.",
    ),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        help="Narrator HTTP timeout in seconds (overrides NARRATOR_TIMEOUT_SECONDS).",
    ),
    lore: str | None = typer.Option(
        None,
        "--lore",
        help="Optional lorebook JSON path used when building narration context.",
    ),
    auto_narrate: bool = typer.Option(
        True,
        "--auto-narrate/--no-auto-narrate",
        help="Auto-generate narration each interactive turn.",
    ),
    debug_prompt: bool = typer.Option(
        False,
        "--debug-prompt",
        help="Print exact system/user prompt sent to narrator (stderr).",
    ),
    actor: str | None = typer.Option(
        None,
        "--actor",
        help="Optional actor sheet JSON path used for compendium-backed resolution.",
    ),
    show_resolution: bool = typer.Option(
        False,
        "--show-resolution/--hide-resolution",
        help="Print structured resolved action payload before narration/output.",
    ),
    spawn: str | None = typer.Option(
        None,
        "--spawn",
        help=(
            "Spawn a named monster and run a full deterministic encounter "
            "(e.g. --spawn goblin). Uses --seed / --fixed-entropy for dice."
        ),
    ),
    event_log: str | None = typer.Option(
        None,
        "--event-log",
        help="Append structured encounter events to this JSONL file (--spawn only).",
    ),
    campaign_file: str | None = typer.Option(
        None,
        "--campaign-file",
        help="Campaign JSON to update with clock auto-advance after --spawn encounter.",
    ),
    companion: str | None = typer.Option(
        None,
        "--companion",
        help=(
            "Path to an actor JSON file for a companion who fights alongside the "
            "player in --spawn encounters."
        ),
    ),
) -> None:
    """Run one deterministic vertical-slice turn."""
    if seed is not None and fixed_entropy is not None:
        raise typer.BadParameter("Use either --seed or --fixed-entropy, not both.")
    if replay is not None and player_input is not None:
        raise typer.BadParameter(
            "--replay cannot be combined with --player-input.",
            param_hint="--replay",
        )
    if replay is not None and load is not None:
        raise typer.BadParameter(
            "Use either --load or --replay, not both.",
            param_hint="--replay",
        )
    if replay is not None and save is not None:
        raise typer.BadParameter(
            "--replay is read-only and cannot be combined with --save.",
            param_hint="--replay",
        )
    if timeout is not None and timeout < 1:
        raise typer.BadParameter("--timeout must be >= 1", param_hint="--timeout")

    provider: DiceProvider
    if fixed_entropy is not None:
        provider = FixedEntropyDiceProvider((fixed_entropy,))
    elif seed is not None:
        provider = SeededDiceProvider(seed)
    else:
        provider = LocalCSPRNGDiceProvider()

    event_store = InMemoryEventStore()
    compendium_store = _load_compendium_store_from_roots(
        root=compendium_root,
        fail_on_missing=len(compendium_root) > 0,
        option_name="--compendium-root",
    )
    try:
        intent_router = IntentRouter(
            provider=intent_provider,
            compendium_store=compendium_store,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--intent-provider") from exc
    engine = Engine(
        dice_provider=provider,
        event_store=event_store,
        intent_router=intent_router,
    )
    actor_state = {"actor": _load_demo_actor(actor)}
    state = GameState()

    if spawn is not None:
        if compendium_store is None:
            typer.echo(
                "spawn error: no compendium loaded; use --compendium-root", err=True
            )
            raise typer.Exit(code=1)
        spawn_narrator: Narrator | None = None
        if auto_narrate:
            try:
                spawn_narrator = get_narrator(
                    provider=narrator_provider, timeout_seconds=timeout
                )
            except ValueError:
                pass
        companion_actor: Actor | None = None
        if companion is not None:
            companion_actor = _load_demo_actor(companion)
        _run_spawn_encounter(
            compendium_store=compendium_store,
            spawn=spawn,
            actor=actor_state["actor"],
            dice_provider=provider,
            event_log_path=event_log,
            campaign_file=campaign_file,
            narrator=spawn_narrator,
            narrator_provider=narrator_provider,
            timeout=timeout,
            debug_prompt=debug_prompt,
            companion_actor=companion_actor,
        )
        return

    if replay is not None:
        loaded_events, replayed_state = _load_and_replay(
            event_store, replay, "--replay"
        )
        typer.echo(
            f"Replayed {len(loaded_events)} events. Final mode: {replayed_state.mode.value}"
        )
        return

    if load is not None:
        loaded_events, state = _load_and_replay(event_store, load, "--load")
        typer.echo(
            f"Loaded {len(loaded_events)} events. Current mode: {state.mode.value}"
        )

    if player_input is not None:
        _print_turn(
            engine=engine,
            state=state,
            text=player_input,
            save_path=save,
            actor_state=actor_state,
            compendium_store=compendium_store,
            show_resolution=show_resolution,
        )
        return

    narrator = None
    if auto_narrate:
        try:
            narrator = get_narrator(
                provider=narrator_provider,
                timeout_seconds=timeout,
            )
        except ValueError as exc:
            typer.echo(
                f"demo narration fallback: {exc}",
                err=True,
            )
            auto_narrate = False

    typer.echo("Chronicle Weaver demo. Type 'exit' to quit.")
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        normalized = line.strip()
        if not normalized:
            continue
        if normalized.lower() in {"exit", "quit"}:
            break
        typer.echo()
        state = _run_interactive_turn(
            engine=engine,
            state=state,
            text=normalized,
            lore_path=lore,
            narrator=narrator,
            narrator_provider=narrator_provider,
            timeout=timeout,
            auto_narrate=auto_narrate,
            debug_prompt=debug_prompt,
            add_trailing_blank_line=True,
            save_path=save,
            actor_state=actor_state,
            compendium_store=compendium_store,
            show_resolution=show_resolution,
        )


def _print_turn(
    engine: Engine,
    state: GameState,
    text: str,
    add_trailing_blank_line: bool = False,
    save_path: str | None = None,
    actor_state: dict[str, Actor] | None = None,
    compendium_store: CompendiumStore | None = None,
    show_resolution: bool = False,
) -> GameState:
    actor = actor_state.get("actor") if actor_state is not None else None
    (
        new_state,
        output,
        all_events,
        resolved_payload,
        resolution_rejection_reason,
        updated_actor,
    ) = _process_turn_with_resolution(
        engine=engine,
        state=state,
        text=text,
        actor=actor,
        compendium_store=compendium_store,
    )
    if actor_state is not None and updated_actor is not None:
        actor_state["actor"] = updated_actor
    if save_path is not None:
        _append_events_jsonl(save_path, all_events)

    if show_resolution and resolved_payload is not None:
        typer.echo(f"resolution {json.dumps(resolved_payload, sort_keys=True)}")
    if resolution_rejection_reason is not None:
        typer.echo(f"resolution rejected: {resolution_rejection_reason}")
        if add_trailing_blank_line:
            typer.echo()
        return new_state

    typer.echo(f"intent={output.intent.value} mechanic={output.mechanic.value}")
    if output.dice_roll is not None:
        typer.echo(
            "dice "
            f"value={output.dice_roll.value} "
            f"attempts={output.dice_roll.attempts} "
            f"provider={output.dice_roll.provider}"
        )
    else:
        typer.echo("dice none")
    typer.echo(f"mode {output.previous_mode.value} -> {new_state.mode.value}")
    if new_state.mode == GameMode.COMBAT and new_state.combat is not None:
        fallback_suffix = ""
        if (
            new_state.combat.entropy_source == "local"
            and new_state.combat.entropy_fallback_reason is not None
        ):
            fallback_suffix = (
                f" fallback_reason={new_state.combat.entropy_fallback_reason}"
            )
        typer.echo(
            f"round={new_state.combat.round_number} "
            f"turn={new_state.combat.turn_index} "
            f"remaining_entropy={len(new_state.combat.entropy_pool)} "
            f"entropy_source={new_state.combat.entropy_source or 'unknown'}"
            f"{fallback_suffix}"
        )
    typer.echo(f"narrative {output.narrative}")
    if add_trailing_blank_line:
        typer.echo()
    return new_state


def _append_events_jsonl(path: str, events: tuple[Event, ...]) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False))
            handle.write("\n")


def _run_interactive_turn(
    engine: Engine,
    state: GameState,
    text: str,
    lore_path: str | None,
    narrator: Narrator | None,
    narrator_provider: str,
    timeout: int | None,
    auto_narrate: bool,
    debug_prompt: bool,
    add_trailing_blank_line: bool = False,
    save_path: str | None = None,
    actor_state: dict[str, Actor] | None = None,
    compendium_store: CompendiumStore | None = None,
    show_resolution: bool = False,
    scene: SceneState | None = None,
) -> GameState:
    actor = actor_state.get("actor") if actor_state is not None else None
    (
        new_state,
        output,
        all_events,
        resolved_payload,
        resolution_rejection_reason,
        updated_actor,
    ) = _process_turn_with_resolution(
        engine=engine,
        state=state,
        text=text,
        actor=actor,
        compendium_store=compendium_store,
    )
    if actor_state is not None and updated_actor is not None:
        actor_state["actor"] = updated_actor
    if save_path is not None:
        _append_events_jsonl(save_path, all_events)
    if show_resolution and resolved_payload is not None:
        typer.echo(f"resolution {json.dumps(resolved_payload, sort_keys=True)}")

    if resolution_rejection_reason is not None:
        typer.echo(f"resolution rejected: {resolution_rejection_reason}")
        if add_trailing_blank_line:
            typer.echo()
        return new_state

    if not auto_narrate:
        typer.echo(output.narrative)
        if add_trailing_blank_line:
            typer.echo()
        return new_state

    narration_text = output.narrative
    try:
        query = _latest_intent_target(all_events) or _fallback_context_query(text)
        session_events = engine.event_store.list_events()
        turn_action = _latest_action_result(list(all_events))
        bundle = _build_context_bundle(
            events=session_events,
            state=new_state,
            lore=lore_path,
            budget=800,
            query=query,
            k=5,
            graph_depth=1,
            graph_k=10,
        )
        request = NarrationRequest(
            context=bundle,
            action=ActionResult(
                intent=output.intent.value,
                mechanic=output.mechanic.value,
                dice_roll=(
                    output.dice_roll.value if output.dice_roll is not None else None
                ),
                mode_from=output.previous_mode.value,
                mode_to=output.new_mode.value,
                action_category=turn_action.action_category,
                resolved_action=turn_action.resolved_action,
            ),
            scene=scene,
        )
        if debug_prompt:
            _emit_debug_prompt(request)
        resolved_narrator = narrator
        if resolved_narrator is None:
            resolved_narrator = get_narrator(
                provider=narrator_provider,
                timeout_seconds=timeout,
            )
        response = resolved_narrator.narrate(request)
        narration_text = response.text
    except (OSError, ValueError, RuntimeError) as exc:
        typer.echo(f"demo narration fallback: {exc}", err=True)

    typer.echo(narration_text)
    if add_trailing_blank_line:
        typer.echo()
    return new_state


def _process_turn_with_resolution(
    engine: Engine,
    state: GameState,
    text: str,
    actor: Actor | None,
    compendium_store: CompendiumStore | None,
) -> tuple[
    GameState,
    EngineOutput,
    tuple[Event, ...],
    dict[str, JSONValue] | None,
    str | None,
    Actor | None,
]:
    interpreted = engine.intent_router.route(text=text, current_mode=state.mode)
    intent_for_engine = interpreted
    resolved_payload: dict[str, JSONValue] | None = None
    resolution_rejection_reason: str | None = None

    attacker_combatant: CombatantSnapshot | None = (
        combatant_from_actor(actor) if actor is not None else None
    )
    target_combatant: CombatantSnapshot | None = _resolve_target_combatant(
        target=interpreted.target,
        compendium_store=compendium_store,
    )

    if (
        interpreted.entry_id is not None
        and compendium_store is not None
        and actor is not None
    ):
        (
            intent_for_engine,
            resolved_payload,
            resolution_rejection_reason,
        ) = _resolve_compendium_backed_action(
            interpreted=interpreted,
            actor=actor,
            compendium_store=compendium_store,
            turn_budget=state.combat.turn_budget if state.combat is not None else None,
            attacker_combatant=attacker_combatant,
        )

    new_state, output = engine.process_input(
        state=state,
        text=text,
        intent_result=intent_for_engine,
    )
    if (
        resolved_payload is not None
        and resolution_rejection_reason is None
        and output.mechanic != Mechanic.CLARIFY
    ):
        _enrich_weapon_attack_resolution_with_roll(
            payload=resolved_payload,
            output=output,
            dice_provider=engine.dice_provider,
            target_combatant=target_combatant,
            attacker_combatant=attacker_combatant,
        )
        if actor is not None and compendium_store is not None:
            _enrich_feature_use_with_healing(
                payload=resolved_payload,
                actor=actor,
                dice_provider=engine.dice_provider,
                compendium_store=compendium_store,
            )
    all_events = list(output.events)
    if resolved_payload is not None:
        resolved_event = Event(
            event_type="resolved_action",
            payload=resolved_payload,
            timestamp=_next_timestamp(all_events, fallback=state.logical_time),
        )
        engine.event_store.append(resolved_event)
        all_events.append(resolved_event)

    updated_actor = actor
    if (
        updated_actor is not None
        and resolved_payload is not None
        and resolution_rejection_reason is None
        and output.mechanic != Mechanic.CLARIFY
    ):
        updated_actor = _apply_actor_resource_spend(
            actor=updated_actor,
            resolved_payload=resolved_payload,
        )

    return (
        new_state,
        output,
        tuple(all_events),
        resolved_payload,
        resolution_rejection_reason,
        updated_actor,
    )


def _resolve_compendium_backed_action(
    interpreted: IntentResult,
    actor: Actor,
    compendium_store: CompendiumStore,
    turn_budget: TurnBudget | None,
    attacker_combatant: CombatantSnapshot | None = None,
) -> tuple[IntentResult, dict[str, JSONValue], str | None]:
    # Condition guard: stunned combatants cannot take any action.
    if attacker_combatant is not None:
        block_reason = is_blocked_by_conditions(attacker_combatant)
        if block_reason is not None:
            return (
                _reject_interpreted_action(interpreted, block_reason),
                {
                    "action_kind": interpreted.intent.value,
                    "entry_id": interpreted.entry_id,
                    "reason": block_reason,
                },
                block_reason,
            )

    if interpreted.entry_id is None:
        raise ValueError("entry_id is required for compendium-backed action resolution")

    entry = compendium_store.get_by_id(interpreted.entry_id)
    if entry is None:
        missing_reason = f"compendium entry '{interpreted.entry_id}' was not found"
        return (
            _reject_interpreted_action(interpreted, missing_reason),
            {
                "action_kind": interpreted.intent.value,
                "entry_id": interpreted.entry_id,
                "entry_name": interpreted.entry_name or interpreted.entry_id,
                "action_cost": interpreted.action_cost or "action",
                "reason": missing_reason,
            },
            missing_reason,
        )

    if isinstance(entry, WeaponEntry):
        weapon_resolved = resolve_weapon_attack(
            actor=actor, weapon_entry=entry, turn_budget=turn_budget
        )
        payload: dict[str, JSONValue] = {
            "action_kind": weapon_resolved.action_kind,
            "entry_id": weapon_resolved.entry_id,
            "entry_name": weapon_resolved.entry_name,
            "action_cost": weapon_resolved.action_cost,
            "attack_ability_used": weapon_resolved.attack_ability_used,
            "attack_bonus_total": weapon_resolved.attack_bonus_total,
            "damage_formula": weapon_resolved.damage_formula,
            "action_available": weapon_resolved.action_available,
            "explanation": weapon_resolved.explanation,
        }
        if attacker_combatant is not None:
            payload["attacker_combatant_id"] = attacker_combatant.combatant_id
            payload["attacker_name"] = attacker_combatant.display_name
        weapon_reason: str | None = None
        if not weapon_resolved.action_available:
            weapon_reason = f"turn budget does not allow {weapon_resolved.action_cost}"
        intent = replace(interpreted, action_cost=weapon_resolved.action_cost)
        if weapon_reason is not None:
            return (
                _reject_interpreted_action(intent, weapon_reason),
                payload,
                weapon_reason,
            )
        return intent, payload, None

    if isinstance(entry, SpellEntry):
        spell_resolved = resolve_spell_cast(
            actor=actor, spell_entry=entry, turn_budget=turn_budget
        )
        payload = {
            "action_kind": spell_resolved.action_kind,
            "entry_id": spell_resolved.entry_id,
            "entry_name": spell_resolved.entry_name,
            "action_cost": spell_resolved.action_cost,
            "action_available": spell_resolved.action_available,
            "auto_hit": spell_resolved.auto_hit,
            "attack_type": spell_resolved.attack_type,
            "save_ability": spell_resolved.save_ability,
            "effect_summary": spell_resolved.effect_summary,
            "can_cast": spell_resolved.can_cast,
            "reason": spell_resolved.reason,
            "slot_level_used": spell_resolved.slot_level_used,
        }
        intent = replace(interpreted, action_cost=spell_resolved.action_cost)
        if not spell_resolved.can_cast:
            spell_reason = spell_resolved.reason or "cannot cast spell"
            return (
                _reject_interpreted_action(intent, spell_reason),
                payload,
                spell_reason,
            )
        return intent, payload, None

    if isinstance(entry, FeatureEntry):
        feature_resolved = resolve_feature_use(
            actor=actor,
            feature_entry=entry,
            turn_budget=turn_budget,
        )
        payload = {
            "action_kind": feature_resolved.action_kind,
            "entry_id": feature_resolved.entry_id,
            "entry_name": feature_resolved.entry_name,
            "action_cost": feature_resolved.action_cost,
            "action_available": feature_resolved.action_available,
            "can_use": feature_resolved.can_use,
            "usage_key": feature_resolved.usage_key,
            "remaining_uses": feature_resolved.remaining_uses,
            "effect_summary": feature_resolved.effect_summary,
            "reason": feature_resolved.reason,
        }
        intent = replace(interpreted, action_cost=feature_resolved.action_cost)
        if not feature_resolved.can_use:
            feature_reason = feature_resolved.reason or "feature cannot be used"
            return (
                _reject_interpreted_action(intent, feature_reason),
                payload,
                feature_reason,
            )
        return intent, payload, None

    return (
        interpreted,
        {
            "action_kind": interpreted.intent.value,
            "entry_id": entry.id,
            "entry_name": entry.name,
            "action_cost": interpreted.action_cost or "action",
            "reason": f"no resolver implemented for entry kind '{entry.kind}'",
        },
        None,
    )


def _resolve_target_combatant(
    target: str | None,
    compendium_store: CompendiumStore | None,
) -> CombatantSnapshot | None:
    """Look up a monster entry by target name and return a CombatantSnapshot."""
    if target is None or compendium_store is None:
        return None
    matches = compendium_store.find_by_name(target)
    monster = next((e for e in matches if isinstance(e, MonsterEntry)), None)
    if monster is None:
        return None
    return combatant_from_monster_entry(monster)


def _reject_interpreted_action(interpreted: IntentResult, reason: str) -> IntentResult:
    return replace(
        interpreted,
        mechanic=Mechanic.CLARIFY,
        is_valid=False,
        rationale=f"{interpreted.rationale}; {reason}",
    )


def _apply_actor_resource_spend(
    actor: Actor,
    resolved_payload: Mapping[str, JSONValue],
) -> Actor:
    action_kind = resolved_payload.get("action_kind")
    if action_kind == "cast_spell":
        can_cast = resolved_payload.get("can_cast")
        slot_level_used = resolved_payload.get("slot_level_used")
        if (
            can_cast is True
            and isinstance(slot_level_used, int)
            and slot_level_used > 0
        ):
            slots = dict(actor.spell_slots)
            current = slots.get(slot_level_used, 0)
            slots[slot_level_used] = max(0, current - 1)
            return replace(actor, spell_slots=slots)
        return actor

    if action_kind == "use_feature":
        can_use = resolved_payload.get("can_use")
        usage_key = resolved_payload.get("usage_key")
        updated = actor
        if can_use is True and isinstance(usage_key, str):
            resources = dict(updated.resources)
            current = resources.get(usage_key, 0)
            resources[usage_key] = max(0, current - 1)
            updated = replace(updated, resources=resources)
        healing_total = resolved_payload.get("healing_total")
        if (
            can_use is True
            and isinstance(healing_total, int)
            and updated.hit_points is not None
        ):
            new_hp = updated.hit_points + healing_total
            if updated.max_hit_points is not None:
                new_hp = min(new_hp, updated.max_hit_points)
            updated = replace(updated, hit_points=new_hp)
        return updated

    return actor


def _enrich_weapon_attack_resolution_with_roll(
    payload: dict[str, JSONValue],
    output: EngineOutput,
    dice_provider: DiceProvider,
    target_combatant: CombatantSnapshot | None = None,
    attacker_combatant: CombatantSnapshot | None = None,
) -> None:
    action_kind = payload.get("action_kind")
    if action_kind != "attack":
        return
    if output.dice_roll is None:
        return
    attack_bonus_total = payload.get("attack_bonus_total")
    if not isinstance(attack_bonus_total, int):
        return

    # Determine roll mode from attacker conditions (poisoned or prone → disadvantage).
    roll_mode = (
        attack_roll_mode(attacker_combatant)
        if attacker_combatant is not None
        else "normal"
    )

    first_roll = output.dice_roll.value
    if roll_mode == "disadvantage":
        # Roll a second d20; take the lower of the two.
        second_record = roll_d20_record(dice_provider)
        second_roll = second_record.value
        attack_roll_d20 = min(first_roll, second_roll)
        payload["attack_rolls_d20"] = [first_roll, second_roll]
    else:
        attack_roll_d20 = first_roll
        payload["attack_rolls_d20"] = [first_roll]

    payload["roll_mode"] = roll_mode
    attack_total = attack_roll_d20 + attack_bonus_total

    if target_combatant is not None and target_combatant.armor_class is not None:
        target_armor_class = target_combatant.armor_class
    else:
        target_armor_class = DEFAULT_ENEMY_AC

    hit_result = attack_total >= target_armor_class

    payload["attack_roll_d20"] = attack_roll_d20
    payload["attack_total"] = attack_total
    payload["target_armor_class"] = target_armor_class
    payload["hit_result"] = hit_result

    if target_combatant is not None:
        payload["target_combatant_id"] = target_combatant.combatant_id
        payload["target_name"] = target_combatant.display_name

    if hit_result:
        damage_formula = payload.get("damage_formula")
        if isinstance(damage_formula, str) and damage_formula:
            dmg = roll_damage_formula(damage_formula, dice_provider)
            payload["damage_rolls"] = dmg.damage_rolls
            payload["damage_modifier_total"] = dmg.damage_modifier_total
            payload["damage_total"] = dmg.damage_total

            if target_combatant is not None and isinstance(
                target_combatant.hit_points, int
            ):
                hp_before = target_combatant.hit_points
                updated = apply_damage(target_combatant, dmg.damage_total)
                hp_after = updated.hit_points
                if isinstance(hp_after, int):
                    payload["target_hp_before"] = hp_before
                    payload["target_hp_after"] = hp_after
                    payload["defeated"] = hp_after == 0


def _enrich_feature_use_with_healing(
    payload: dict[str, JSONValue],
    actor: Actor,
    dice_provider: DiceProvider,
    compendium_store: CompendiumStore,
) -> None:
    """Roll and record healing for features that have a healing_formula.

    Mutates *payload* in place with healing fields.  Called only when the feature
    use was accepted (can_use=True) and the entry has healing_formula set.
    """
    if payload.get("action_kind") != "use_feature":
        return
    if payload.get("can_use") is not True:
        return
    entry_id = payload.get("entry_id")
    if not isinstance(entry_id, str):
        return
    entry = compendium_store.get_by_id(entry_id)
    if not isinstance(entry, FeatureEntry):
        return
    if not entry.healing_formula:
        return

    # Build the effective formula, optionally appending actor level
    effective_formula = entry.healing_formula
    if entry.healing_level_bonus and actor.level > 0:
        effective_formula = f"{effective_formula} +{actor.level}"

    dmg = roll_damage_formula(effective_formula, dice_provider)
    healing_total = max(0, dmg.damage_total)

    payload["healing_formula"] = effective_formula
    payload["healing_rolls"] = dmg.damage_rolls
    payload["healing_modifier_total"] = dmg.damage_modifier_total
    payload["healing_total"] = healing_total

    if actor.hit_points is not None:
        hp_before = actor.hit_points
        new_hp = hp_before + healing_total
        if actor.max_hit_points is not None:
            new_hp = min(new_hp, actor.max_hit_points)
        payload["self_hp_before"] = hp_before
        payload["self_hp_after"] = new_hp


def _next_timestamp(events: list[Event], fallback: int) -> int:
    latest = fallback
    for event in events:
        if isinstance(event.timestamp, (int, float)):
            latest = max(latest, int(event.timestamp))
    return latest + 1


def _latest_intent_target(events: tuple[Event, ...]) -> str | None:
    for event in reversed(events):
        if event.event_type != "intent_resolved":
            continue
        target = event.payload.get("target")
        if isinstance(target, str) and target:
            return target
    return None


def _emit_debug_prompt(narration_request: NarrationRequest) -> None:
    system_text, user_prompt = build_prompt_parts(narration_request)
    typer.echo("SYSTEM PROMPT:", err=True)
    typer.echo(system_text, err=True)
    typer.echo("", err=True)
    typer.echo("USER PROMPT:", err=True)
    typer.echo(user_prompt, err=True)


def _fallback_context_query(text: str) -> str | None:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    stop_words = {
        "i",
        "you",
        "we",
        "the",
        "a",
        "an",
        "to",
        "at",
        "in",
        "into",
        "with",
        "on",
        "and",
        "or",
        "please",
        "could",
        "would",
        "should",
        "can",
        "around",
        "away",
        "now",
    }
    for token in reversed(tokens):
        if token in stop_words:
            continue
        if len(token) < 3:
            continue
        return token
    return None


def _load_and_replay(
    event_store: InMemoryEventStore,
    path: str,
    option_name: str,
) -> tuple[list[Event], GameState]:
    try:
        loaded_events = event_store.load_jsonl(path)
    except (OSError, ValueError) as exc:
        typer.echo(f"{option_name} error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    replayed_state = event_store.replay(GameState(), reduce_state)
    return loaded_events, replayed_state


# ── Spawn encounter helpers ────────────────────────────────────────────────────

_SPAWN_ROUNDS_MAX = 20


def _run_spawn_encounter(
    compendium_store: CompendiumStore,
    spawn: str,
    actor: Actor,
    dice_provider: DiceProvider,
    event_log_path: str | None = None,
    campaign_file: str | None = None,
    narrator: "Narrator | None" = None,
    narrator_provider: str = "auto",
    timeout: int | None = None,
    debug_prompt: bool = False,
    companion_actor: "Actor | None" = None,
) -> None:
    """Run a deterministic player-vs-monster encounter to completion and print results.

    If *event_log_path* is given the structured encounter events are appended to
    that JSONL file so they can be consumed by the scribe, replayed for
    narration, or inspected offline.
    If *campaign_file* is given the world clock is advanced by the encounter
    duration and the campaign is saved.
    If *narrator* is given (or *narrator_provider* resolves to one) each turn
    produces LLM narrative prose after the deterministic resolution printout.
    """
    from chronicle_weaver_ai.campaign import (
        CampaignScene,
        set_scene_combat_active,
    )
    from chronicle_weaver_ai.narration.models import EncounterContext

    # Resolve narrator — use passed narrator or try to build one
    _narrator = narrator
    if _narrator is None and narrator_provider != "auto":
        try:
            _narrator = get_narrator(
                provider=narrator_provider, timeout_seconds=timeout
            )
        except ValueError:
            pass

    # Resolve monster entry by name
    matches = compendium_store.find_by_name(spawn)
    monster_entry = next((e for e in matches if isinstance(e, MonsterEntry)), None)
    if monster_entry is None:
        typer.echo(f"spawn error: monster '{spawn}' not found in compendium", err=True)
        raise typer.Exit(code=1)

    player_snap = combatant_from_actor(actor)
    monster_snap = combatant_from_monster_entry(monster_entry)

    all_combatants = [player_snap, monster_snap]
    if companion_actor is not None:
        companion_snap = combatant_from_actor(companion_actor, source_type="companion")
        all_combatants.append(companion_snap)

    encounter = create_encounter("enc.spawn", all_combatants, dice_provider)

    # Collect encounter events for event-log bridge
    collected_events: list[Event] = []
    ts_counter = [0]

    def _ts() -> int:
        ts_counter[0] += 1
        return ts_counter[0]

    collected_events.append(
        emit_encounter_started(
            encounter_id=encounter.encounter_id,
            combatant_names=[s.display_name for s in encounter.combatants.values()],
            initiative_order=list(encounter.turn_order.combatant_ids),
            ts=_ts(),
        )
    )

    # Create scene and toggle combat_active
    party_names = [actor.name] + (
        [companion_actor.name] if companion_actor is not None else []
    )
    combatants_present = party_names + [monster_entry.name]
    scene = CampaignScene(
        scene_id="scene.spawn",
        description_stub=(
            f"A combat arena where {', '.join(party_names)} face {monster_entry.name}."
        ),
        combat_active=False,
        combatants_present=combatants_present,
    )
    scene = set_scene_combat_active(scene, True)

    encounter_title = " & ".join(party_names) + f" vs {monster_entry.name}"
    typer.echo(f"=== Encounter: {encounter_title} ===")
    typer.echo(f"Scene: {scene.description_stub} [combat_active={scene.combat_active}]")
    typer.echo(f"Initiative order: {', '.join(encounter.turn_order.combatant_ids)}")
    typer.echo()

    rounds_elapsed = 0
    for _ in range(_SPAWN_ROUNDS_MAX):
        if is_encounter_over(encounter):
            break

        active_id = current_combatant(encounter.turn_order)
        active = encounter.combatants[active_id]
        rounds_elapsed = encounter.turn_order.current_round

        collected_events.append(
            emit_turn_started(
                encounter_id=encounter.encounter_id,
                round_number=encounter.turn_order.current_round,
                combatant_id=active_id,
                combatant_name=active.display_name,
                ts=_ts(),
            )
        )

        typer.echo(
            f"--- Round {encounter.turn_order.current_round}, "
            f"turn: {active.display_name} ---"
        )

        if active.source_type == "actor":
            encounter = _do_player_ai_turn(
                encounter=encounter,
                actor=actor,
                compendium_store=compendium_store,
                dice_provider=dice_provider,
                events_out=collected_events,
                ts_fn=_ts,
            )
        elif active.source_type == "companion" and companion_actor is not None:
            encounter = _do_companion_ai_turn(
                encounter=encounter,
                companion_actor=companion_actor,
                compendium_store=compendium_store,
                dice_provider=dice_provider,
            )
        else:
            encounter = _do_monster_ai_turn(
                encounter=encounter,
                monster_snap=active,
                monster_entry=monster_entry,
                compendium_store=compendium_store,
                dice_provider=dice_provider,
                events_out=collected_events,
                ts_fn=_ts,
            )

        # Print current HP after the turn
        for cid, snap in encounter.combatants.items():
            status = (
                "defeated" if cid in encounter.defeated_ids else f"HP={snap.hit_points}"
            )
            typer.echo(f"  {snap.display_name}: {status}")

        # Optional LLM narration per turn
        if _narrator is not None:
            enc_ctx = EncounterContext(
                current_round=encounter.turn_order.current_round,
                acting_combatant=active.display_name,
                turn_order=[
                    encounter.combatants[cid].display_name
                    for cid in encounter.turn_order.combatant_ids
                ],
            )
            narration_scene = SceneState(
                scene_id=scene.scene_id,
                description_stub=scene.description_stub,
                combat_active=scene.combat_active,
                combatants_present=list(scene.combatants_present),
            )
            ctx_bundle = ContextBuilder().build(state=GameState())
            action_result = ActionResult(
                intent="attack",
                mechanic="combat_roll",
                dice_roll=None,
                mode_from="combat",
                mode_to="combat",
            )
            narr_req = NarrationRequest(
                context=ctx_bundle,
                action=action_result,
                scene=narration_scene,
                encounter_context=enc_ctx,
            )
            if debug_prompt:
                parts = build_prompt_parts(narr_req)
                typer.echo(
                    f"[DEBUG system]\n{parts[0]}\n[DEBUG user]\n{parts[1]}", err=True
                )
            try:
                narr_resp = _narrator.narrate(narr_req)
                typer.echo(f"\n{narr_resp.text}\n")
            except Exception as exc:  # noqa: BLE001
                typer.echo(f"  [narration error: {exc}]", err=True)
        else:
            typer.echo()

        if is_encounter_over(encounter):
            break

        encounter = end_turn(encounter)

    # End combat — toggle scene
    scene = set_scene_combat_active(scene, False)

    # Outcome
    allied_ids = [
        cid
        for cid, snap in encounter.combatants.items()
        if snap.source_type in ("actor", "companion")
    ]
    monster_ids = [
        cid
        for cid, snap in encounter.combatants.items()
        if snap.source_type == "monster"
    ]
    if all(cid in encounter.defeated_ids for cid in monster_ids):
        outcome = "victory"
        typer.echo(f"Victory! {encounter_title}")
    elif all(cid in encounter.defeated_ids for cid in allied_ids):
        outcome = "defeat"
        typer.echo(f"Defeat! {encounter_title}")
    else:
        outcome = "draw"
        typer.echo(
            f"Encounter ended after {_SPAWN_ROUNDS_MAX} rounds (no decisive outcome)."
        )
    typer.echo(f"Scene: [combat_active={scene.combat_active}]")

    collected_events.append(
        emit_encounter_ended(
            encounter_id=encounter.encounter_id,
            outcome=outcome,
            winner_ids=[
                cid
                for cid in allied_ids + monster_ids
                if cid not in encounter.defeated_ids
            ],
            loser_ids=list(encounter.defeated_ids),
            rounds_elapsed=rounds_elapsed,
            ts=_ts(),
        )
    )

    # Write event log if requested
    if event_log_path:
        import json as _json

        with open(event_log_path, "a", encoding="utf-8") as fh:
            for ev in collected_events:
                fh.write(_json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
        typer.echo(
            f"Event log: {len(collected_events)} events written -> {event_log_path}"
        )

    # Advance world clock if a campaign file is provided
    if campaign_file is not None:
        import dataclasses as _dc

        from chronicle_weaver_ai.campaign import load_campaign, save_campaign
        from chronicle_weaver_ai.models import advance_clock_for_encounter

        camp_path = Path(campaign_file)
        if camp_path.exists():
            campaign = load_campaign(camp_path)
            new_clock = advance_clock_for_encounter(
                campaign.world_clock, rounds_elapsed
            )
            updated_campaign = _dc.replace(campaign, world_clock=new_clock)
            save_campaign(updated_campaign, camp_path)
            typer.echo(f"Clock advanced: {clock_display(new_clock)}")
        else:
            typer.echo(f"Warning: campaign file not found: {campaign_file}", err=True)


def _process_death_save(
    encounter: EncounterState,
    combatant_id: str,
    dice_provider: DiceProvider,
) -> EncounterState:
    """Roll a death save for a dying combatant and update the encounter state."""
    from chronicle_weaver_ai.rules import roll_death_save

    snap = encounter.combatants[combatant_id]
    new_snap, result = roll_death_save(snap, dice_provider)
    encounter = update_combatant(encounter, new_snap)
    typer.echo(
        f"  {snap.display_name} rolls death save: {result.roll} → {result.outcome} "
        f"(successes={result.new_successes}, failures={result.new_failures})"
    )
    if result.outcome == "dead":
        typer.echo(f"  {snap.display_name} has died!")
        encounter = mark_defeated(encounter, combatant_id)
    elif result.outcome == "stable":
        typer.echo(f"  {snap.display_name} has stabilised.")
    return encounter


def _do_player_ai_turn(
    encounter: EncounterState,
    actor: Actor,
    compendium_store: CompendiumStore,
    dice_provider: DiceProvider,
    events_out: list[Event] | None = None,
    ts_fn: object = None,
) -> EncounterState:
    """Execute a simple AI player turn: attack the first living monster with equipped weapon.

    If the player is dying (HP=0) they roll a death saving throw instead.
    """
    from collections.abc import Callable

    from chronicle_weaver_ai.rules import is_dying

    _ts: Callable[[], int] = ts_fn if callable(ts_fn) else (lambda: 0)  # type: ignore[assignment]

    player_snap = encounter.combatants.get(actor.actor_id)
    if player_snap is not None and is_dying(player_snap):
        return _process_death_save(encounter, actor.actor_id, dice_provider)

    weapon_id = actor.equipped_weapon_ids[0] if actor.equipped_weapon_ids else None
    if weapon_id is None:
        typer.echo(f"  {actor.name} has no equipped weapon — skips turn.")
        return encounter

    weapon_entry = compendium_store.get_by_id(weapon_id)
    if not isinstance(weapon_entry, WeaponEntry):
        typer.echo(
            f"  {actor.name}: weapon entry '{weapon_id}' not found — skips turn."
        )
        return encounter

    resolved = resolve_weapon_attack(actor, weapon_entry)

    for attack_num in range(resolved.attack_count):
        # Re-select target each swing (previous target may have been defeated)
        target_id = next(
            (
                cid
                for cid, snap in encounter.combatants.items()
                if snap.source_type == "monster" and cid not in encounter.defeated_ids
            ),
            None,
        )
        if target_id is None:
            break  # no more targets

        target = encounter.combatants[target_id]
        attack_record = roll_d20_record(dice_provider)
        attack_total = attack_record.value + resolved.attack_bonus_total

        attack_label = (
            f" (attack {attack_num + 1}/{resolved.attack_count})"
            if resolved.attack_count > 1
            else ""
        )
        typer.echo(
            f"  {actor.name} attacks {target.display_name} with {weapon_entry.name}"
            f"{attack_label} — "
            f"d20={attack_record.value}+{resolved.attack_bonus_total}={attack_total} "
            f"vs AC {target.armor_class}"
        )

        # Track melee engagement
        encounter = engage(encounter, actor.actor_id, target_id)

        hit = target.armor_class is not None and attack_total >= target.armor_class
        damage_total = 0

        if hit:
            dmg = roll_damage_formula(resolved.damage_formula, dice_provider)
            damage_total = dmg.damage_total
            typer.echo(f"  Hit! Damage: {damage_total}")
            old_hp = target.hit_points
            damaged = apply_damage(target, damage_total)
            encounter = update_combatant(encounter, damaged)
            if events_out is not None:
                events_out.append(
                    emit_hp_changed(
                        encounter.encounter_id,
                        target_id,
                        target.display_name,
                        old_hp,
                        damaged.hit_points,
                        _ts(),
                    )
                )
            if damaged.hit_points == 0:
                typer.echo(f"  {target.display_name} is defeated!")
                encounter = mark_defeated(encounter, target_id)
                if events_out is not None:
                    events_out.append(
                        emit_combatant_defeated(
                            encounter.encounter_id,
                            target_id,
                            target.display_name,
                            _ts(),
                        )
                    )
        else:
            typer.echo("  Miss!")

        if events_out is not None:
            events_out.append(
                emit_attack_resolved(
                    encounter_id=encounter.encounter_id,
                    attacker_id=actor.actor_id,
                    attacker_name=actor.name,
                    target_id=target_id,
                    target_name=target.display_name,
                    attack_roll=attack_record.value,
                    attack_bonus=resolved.attack_bonus_total,
                    attack_total=attack_total,
                    target_ac=target.armor_class,
                    hit=hit,
                    damage_total=damage_total,
                    weapon_name=weapon_entry.name,
                    ts=_ts(),
                )
            )

    return encounter


def _do_monster_ai_turn(
    encounter: EncounterState,
    monster_snap: CombatantSnapshot,
    monster_entry: MonsterEntry,
    compendium_store: CompendiumStore,
    dice_provider: DiceProvider,
    events_out: list[Event] | None = None,
    ts_fn: object = None,
) -> EncounterState:
    """Execute a monster AI turn via the shared monster_turn library."""
    from collections.abc import Callable

    from chronicle_weaver_ai.monster_turn import run_monster_turn

    _ts: Callable[[], int] = ts_fn if callable(ts_fn) else (lambda: 0)  # type: ignore[assignment]

    encounter, result = run_monster_turn(encounter, monster_entry, dice_provider)

    if result.resolved_attack is None:
        typer.echo(f"  {monster_snap.display_name} has no valid action — skips turn.")
        return encounter

    target_display = (
        encounter.combatants[result.target_id].display_name
        if result.target_id is not None
        else "???"
    )

    # Track melee engagement when the monster attacks
    if result.target_id is not None:
        encounter = engage(encounter, monster_snap.combatant_id, result.target_id)

    typer.echo(
        f"  {monster_snap.display_name} attacks {target_display}"
        f" with {result.action_name} — "
        f"d20={result.attack_roll}+{result.resolved_attack.attack_bonus_total}"
        f"={result.attack_total}"
        f" vs AC {result.resolved_attack.target_armor_class}"
    )

    if result.hit:
        typer.echo(f"  Hit! Damage: {result.damage_total}")
        if result.target_defeated:
            typer.echo(f"  {target_display} is defeated!")
            if events_out is not None and result.target_id is not None:
                events_out.append(
                    emit_combatant_defeated(
                        encounter.encounter_id,
                        result.target_id,
                        target_display,
                        _ts(),
                    )
                )
    else:
        typer.echo("  Miss!")

    if events_out is not None and result.target_id is not None:
        ra = result.resolved_attack
        events_out.append(
            emit_attack_resolved(
                encounter_id=encounter.encounter_id,
                attacker_id=monster_snap.combatant_id,
                attacker_name=monster_snap.display_name,
                target_id=result.target_id,
                target_name=target_display,
                attack_roll=result.attack_roll or 0,
                attack_bonus=ra.attack_bonus_total,
                attack_total=result.attack_total or 0,
                target_ac=ra.target_armor_class,
                hit=bool(result.hit),
                damage_total=result.damage_total or 0,
                weapon_name=result.action_name or "",
                ts=_ts(),
            )
        )

    return encounter


def _do_companion_ai_turn(
    encounter: EncounterState,
    companion_actor: Actor,
    compendium_store: CompendiumStore,
    dice_provider: DiceProvider,
) -> EncounterState:
    """Execute a companion AI turn using the companion_turn pipeline."""
    from chronicle_weaver_ai.companion_turn import run_companion_turn
    from chronicle_weaver_ai.rules import is_dying

    companion_snap = encounter.combatants.get(companion_actor.actor_id)
    if companion_snap is not None and is_dying(companion_snap):
        return _process_death_save(encounter, companion_actor.actor_id, dice_provider)

    encounter, result = run_companion_turn(
        encounter, companion_actor, compendium_store, dice_provider
    )

    if result.skipped_reason:
        typer.echo(f"  {result.companion_name} skips turn ({result.skipped_reason}).")
        return encounter

    target_name = (
        encounter.combatants[result.target_id].display_name
        if result.target_id is not None
        else "???"
    )
    typer.echo(
        f"  {result.companion_name} attacks {target_name} with {result.action_name} — "
        f"d20={result.attack_roll}+{result.attack_bonus}={result.attack_total} "
        f"vs AC {result.target_ac}"
    )
    if result.hit:
        typer.echo(f"  Hit! Damage: {result.damage_total}")
        if result.target_defeated:
            typer.echo(f"  {target_name} is defeated!")
    else:
        typer.echo("  Miss!")

    return encounter


def _print_opp_attack_results(results: list) -> None:
    """Print opportunity attack results to the CLI."""
    for oar in results:
        hit_str = (
            f"Hit! Damage: {oar.damage_total}"
            if oar.hit
            else f"Miss (roll {oar.attack_total} vs AC {oar.target_ac})"
        )
        typer.echo(
            f"  [OA] {oar.reactor_name} strikes {oar.mover_name} "
            f"(d20={oar.attack_roll}+{oar.attack_bonus}={oar.attack_total}"
            f" vs AC {oar.target_ac}) — {hit_str}"
        )


@app.command()
def compendium(
    root: list[str] = typer.Option(
        ["compendiums"],
        "--root",
        help="Compendium root directory. Repeat to include multiple roots.",
    ),
    kind: str | None = typer.Option(
        None,
        "--kind",
        help="Filter by entry kind (weapon, spell, item, feature, monster).",
    ),
) -> None:
    """Load and print entries from one or more compendium roots."""
    try:
        resolved_roots = []
        for candidate in root:
            resolved_roots.extend(resolve_compendium_roots(candidate))
        store = CompendiumStore()
        store.load(resolved_roots)
    except CompendiumLoadError as exc:
        typer.echo(f"compendium error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if kind is None:
        entries = store.entries
    else:
        entries = store.list_by_kind(kind)

    for entry in entries:
        typer.echo(
            f"{entry.id}\t{entry.kind}\t{entry.name}\t{entry.source_path or '<unknown>'}"
        )


@app.command()
def interpret(
    text: str = typer.Option(..., "--text", help="Freeform player input to classify."),
    intent_provider: str = typer.Option(
        "auto",
        "--intent-provider",
        help="Intent provider: auto|rules|ollama|openai.",
    ),
    compendium_root: list[str] = typer.Option(
        ["compendiums"],
        "--compendium-root",
        help="Optional compendium root directories for intent matching.",
    ),
) -> None:
    """Resolve intent + target using hybrid rules-first router."""
    compendium_store = _load_compendium_store_from_roots(
        root=compendium_root,
        fail_on_missing=len(compendium_root) > 0,
        option_name="--compendium-root",
    )
    try:
        router = IntentRouter(
            provider=intent_provider,
            compendium_store=compendium_store,
        )
        result = router.route(text=text, current_mode=GameMode.EXPLORATION)
    except ValueError as exc:
        typer.echo(f"interpret error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "intent": result.intent.value,
                "target": result.target,
                "entry_id": result.entry_id,
                "entry_kind": result.entry_kind,
                "entry_name": result.entry_name,
                "confidence": result.confidence,
                "is_valid": result.is_valid,
                "provider_used": result.provider_used,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


@app.command()
def scribe(
    load: str = typer.Option(
        ..., "--load", help="Load session events JSONL and run deterministic scribe."
    ),
    queue: str | None = typer.Option(
        None,
        "--queue",
        help="Optional review_queue.jsonl path to append scribe candidates.",
    ),
    session_name: str | None = typer.Option(
        None,
        "--session-name",
        help="Optional source session label recorded in queue items.",
    ),
) -> None:
    """Run Lore Scribe v0 on a saved event session."""
    event_store = InMemoryEventStore()
    try:
        events = event_store.load_jsonl(load)
    except (OSError, ValueError) as exc:
        typer.echo(f"--load error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    result = run_lore_scribe(events)
    typer.echo(f"Summary: {result.summary.text}")
    typer.echo("Entities:")
    for entity in result.entities[:10]:
        typer.echo(f"- {entity.name} ({entity.kind}) x{entity.count}")
    typer.echo("Facts:")
    for fact in result.facts[:10]:
        typer.echo(f"- [{fact.type}] {fact.text}")
    typer.echo("Relations:")
    for relation in result.relations[:10]:
        typer.echo(
            f"- {relation.subject_name} --{relation.predicate}--> {relation.object_name}"
        )
    if queue is not None:
        source_session = session_name or load
        items = build_queue_items_from_scribe(result, source_session=source_session)
        queued_new, skipped_existing = LoreQueueStore().append_items(queue, items)
        typer.echo(
            f"Queued {queued_new} new items (skipped {skipped_existing} existing) -> {queue}"
        )


@app.command()
def context(
    load: str = typer.Option(
        ..., "--load", help="Load session events JSONL and replay state."
    ),
    lore: str | None = typer.Option(
        None, "--lore", help="Optional lorebook JSON path for approved lore."
    ),
    budget: int = typer.Option(
        800, "--budget", help="Approximate token budget for selected context items."
    ),
    query: str | None = typer.Option(
        None, "--query", help="Optional lexical retrieval query for extra context."
    ),
    k: int = typer.Option(
        5, "--k", help="Top-k retrieved snippets when --query is provided."
    ),
    graph_depth: int = typer.Option(
        1, "--graph-depth", help="Graph expansion depth for query neighbors (0..2)."
    ),
    graph_k: int = typer.Option(
        10, "--graph-k", help="Maximum graph relations to include in graph neighbors."
    ),
    show_raw: bool = typer.Option(
        False, "--show-raw", help="Print raw JSON for the built context bundle."
    ),
) -> None:
    """Build and print deterministic LLM context bundle from session + lore."""
    if budget < 1:
        raise typer.BadParameter("--budget must be >= 1", param_hint="--budget")
    if k < 1:
        raise typer.BadParameter("--k must be >= 1", param_hint="--k")
    if graph_depth < 0 or graph_depth > 2:
        raise typer.BadParameter(
            "--graph-depth must be in range 0..2", param_hint="--graph-depth"
        )
    if graph_k < 1:
        raise typer.BadParameter("--graph-k must be >= 1", param_hint="--graph-k")

    event_store = InMemoryEventStore()
    events, state = _load_and_replay(event_store, load, "--load")
    try:
        bundle = _build_context_bundle(
            events=events,
            state=state,
            lore=lore,
            budget=budget,
            query=query,
            k=k,
            graph_depth=graph_depth,
            graph_k=graph_k,
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"context error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("SYSTEM:")
    typer.echo(bundle.system_text)
    typer.echo()
    typer.echo(
        f"ITEMS (selected {len(bundle.items)}, "
        f"tokens_est={bundle.total_tokens_est} / budget={budget}):"
    )
    for item in bundle.items:
        typer.echo(
            f"- [{_display_context_kind(item.kind)}|priority={item.priority}|"
            f"tokens={item.tokens_est}] {item.text}"
        )

    if show_raw:
        typer.echo()
        typer.echo("RAW:")
        typer.echo(
            json.dumps(
                _context_bundle_to_dict(bundle),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )


@app.command()
def narrate(
    load: str = typer.Option(
        ..., "--load", help="Load session events JSONL and replay state."
    ),
    lore: str | None = typer.Option(
        None, "--lore", help="Optional lorebook JSON path for approved lore."
    ),
    budget: int = typer.Option(
        800, "--budget", help="Approximate token budget for context selection."
    ),
    query: str | None = typer.Option(
        None, "--query", help="Optional retrieval query to focus narration context."
    ),
    provider: str = typer.Option(
        "auto", "--provider", help="Narrator provider: auto|ollama|openai."
    ),
    debug_prompt: bool = typer.Option(
        False,
        "--debug-prompt",
        help="Print exact system/user prompt sent to narrator (stderr).",
    ),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        help="Narrator HTTP timeout in seconds (overrides NARRATOR_TIMEOUT_SECONDS).",
    ),
    k: int = typer.Option(
        5, "--k", help="Top-k retrieved snippets when --query is provided."
    ),
    graph_depth: int = typer.Option(
        1, "--graph-depth", help="Graph expansion depth for query neighbors (0..2)."
    ),
    graph_k: int = typer.Option(
        10, "--graph-k", help="Maximum graph relations to include in graph neighbors."
    ),
) -> None:
    """Generate narration text from deterministic context and last action."""
    if budget < 1:
        raise typer.BadParameter("--budget must be >= 1", param_hint="--budget")
    if k < 1:
        raise typer.BadParameter("--k must be >= 1", param_hint="--k")
    if graph_depth < 0 or graph_depth > 2:
        raise typer.BadParameter(
            "--graph-depth must be in range 0..2", param_hint="--graph-depth"
        )
    if graph_k < 1:
        raise typer.BadParameter("--graph-k must be >= 1", param_hint="--graph-k")
    if timeout is not None and timeout < 1:
        raise typer.BadParameter("--timeout must be >= 1", param_hint="--timeout")

    event_store = InMemoryEventStore()
    events, state = _load_and_replay(event_store, load, "--load")
    try:
        bundle = _build_context_bundle(
            events=events,
            state=state,
            lore=lore,
            budget=budget,
            query=query,
            k=k,
            graph_depth=graph_depth,
            graph_k=graph_k,
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"narrate context error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    action = _latest_action_result(events)
    narration_request = NarrationRequest(context=bundle, action=action)
    if debug_prompt:
        _emit_debug_prompt(narration_request)
    try:
        narrator = get_narrator(provider=provider, timeout_seconds=timeout)
        response = narrator.narrate(narration_request)
    except (ValueError, RuntimeError) as exc:
        typer.echo(f"narrate error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(response.text)


@app.command()
def review(
    queue: str = typer.Option(..., "--queue", help="Review queue JSONL path."),
) -> None:
    """List pending queue items."""
    store = LoreQueueStore()
    try:
        items = store.list_items(queue, status="pending")
    except (OSError, ValueError) as exc:
        typer.echo(f"--queue error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not items:
        typer.echo("No pending items.")
        return
    typer.echo(f"Pending items: {len(items)}")
    for item in items:
        typer.echo(f"- {item.id} [{item.kind}] {_queue_item_preview(item.payload)}")


@app.command()
def approve(
    queue: str = typer.Option(..., "--queue", help="Review queue JSONL path."),
    lore: str = typer.Option(..., "--lore", help="Lorebook JSON path."),
    id: str = typer.Option(..., "--id", help="Queue item id to approve."),
) -> None:
    """Approve one queue item into lorebook and mark queue entry approved."""
    queue_store = LoreQueueStore()
    try:
        all_items = queue_store.list_items(queue, status=None)
    except (OSError, ValueError) as exc:
        typer.echo(f"--queue error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    matched = next((item for item in all_items if item.id == id), None)
    if matched is None:
        typer.echo(f"Queue id not found: {id}", err=True)
        raise typer.Exit(code=1)

    lore_store = LorebookStore()
    if matched.kind == "entity":
        lore_store.add_entity(lore, matched.payload)
    elif matched.kind == "relation":
        lore_store.add_relation(lore, matched.payload)
    else:
        lore_store.add_fact(lore, matched.payload)

    queue_store.mark_approved(queue, id)
    typer.echo(f"Approved {id} -> {lore}")


def _queue_item_preview(payload: Mapping[str, JSONValue]) -> str:
    subject_name = payload.get("subject_name")
    predicate = payload.get("predicate")
    object_name = payload.get("object_name")
    if (
        isinstance(subject_name, str)
        and isinstance(predicate, str)
        and isinstance(object_name, str)
    ):
        return f"{subject_name} --{predicate}--> {object_name}"
    if "name" in payload:
        return str(payload["name"])
    if "text" in payload:
        text_value = payload["text"]
        if isinstance(text_value, str):
            return text_value
        return "<unknown>"
    return "<unknown>"


def _lore_entries_from_lorebook_data(
    entities: list[dict[str, JSONValue]],
    facts: list[dict[str, JSONValue]],
) -> list[tuple[str, str]]:
    entity_entries: list[tuple[str, str]] = []
    for entity in entities:
        canonical = canonicalize_entity_record(entity)
        name = str(canonical["name"])
        kind = str(canonical["kind"])
        canonical_id = str(canonical["entity_id"])
        entity_entries.append(
            (f"entity:{canonical_id}", f"Lore: Entity: {name} ({kind})")
        )

    fact_entries: list[tuple[str, str]] = []
    for fact in facts:
        text = fact.get("text")
        if not isinstance(text, str) or not text:
            continue
        canonical_id = fact_id(text)
        fact_entries.append((f"fact:{canonical_id}", f"Lore: Fact: {text}"))

    return sorted(entity_entries) + sorted(fact_entries)


def _build_context_bundle(
    events: list[Event],
    state: GameState,
    lore: str | None,
    budget: int,
    query: str | None,
    k: int,
    graph_depth: int,
    graph_k: int,
) -> ContextBundle:
    lore_entities: list[dict[str, JSONValue]] = []
    lore_facts: list[dict[str, JSONValue]] = []
    lore_relations: list[dict[str, JSONValue]] = []
    lore_entries: list[tuple[str, str]] = []
    if lore is not None:
        lorebook = LorebookStore().load(lore)
        lore_entities = lorebook.entities
        lore_facts = lorebook.facts
        lore_relations = lorebook.relations
        lore_entries = _lore_entries_from_lorebook_data(lore_entities, lore_facts)

    retrieved_entries: list[tuple[str, str]] = []
    graph_entries: list[tuple[str, str]] = []
    compendium_entry = _latest_compendium_context_item(events)
    if compendium_entry is not None:
        retrieved_entries.append(compendium_entry)
    resolved_action_entry = _latest_resolved_action_context_item(events)
    if resolved_action_entry is not None:
        retrieved_entries.append(resolved_action_entry)

    if query is not None:
        retrieval_docs = _retrieval_docs_from_sources(
            events=events,
            lore_entities=lore_entities,
            lore_facts=lore_facts,
        )
        top_docs = retrieve(query=query, docs=retrieval_docs, k=k)
        retrieved_entries.extend(
            [
                (
                    doc.doc_id,
                    f"Retrieved: {doc.text} (score={doc.score:.3f})",
                )
                for doc in top_docs
            ]
        )
        graph_entries = _graph_neighbor_entries(
            query=query,
            lore_entities=lore_entities,
            lore_relations=lore_relations,
            depth=graph_depth,
            max_neighbors=graph_k,
        )

    return ContextBuilder().build(
        state=state,
        recent_events=events,
        graph_entries=graph_entries,
        retrieved_entries=retrieved_entries,
        lore_entries=lore_entries,
        budget_tokens=budget,
    )


def _latest_compendium_context_item(
    events: list[Event],
) -> tuple[str, str] | None:
    for event in reversed(events):
        if event.event_type != "intent_resolved":
            continue

        entry_id = event.payload.get("entry_id")
        entry_kind = event.payload.get("entry_kind")
        entry_name = event.payload.get("entry_name")
        if (
            not isinstance(entry_id, str)
            or not isinstance(entry_kind, str)
            or not isinstance(entry_name, str)
        ):
            return None

        description = _compendium_description(
            entry_id=entry_id,
            entry_kind=entry_kind,
            entry_name=entry_name,
        )
        return (
            f"compendium:{entry_kind}:{entry_id}",
            f"Compendium: {entry_kind.title()}: {entry_name} — {description}",
        )
    return None


def _latest_resolved_action_context_item(
    events: list[Event],
) -> tuple[str, str] | None:
    for event in reversed(events):
        if event.event_type != "resolved_action":
            continue
        action_kind = event.payload.get("action_kind")
        entry_name = event.payload.get("entry_name")
        if not isinstance(action_kind, str) or not isinstance(entry_name, str):
            return None
        summary = _resolved_action_summary(event.payload)
        return (
            f"resolved_action:{action_kind}:{entry_name.casefold()}",
            f"Resolved action: {summary}",
        )
    return None


def _resolved_action_summary(payload: Mapping[str, JSONValue]) -> str:
    action_kind = payload.get("action_kind")
    entry_name = payload.get("entry_name")
    action_cost = payload.get("action_cost")
    parts: list[str] = []
    if isinstance(action_kind, str):
        parts.append(action_kind)
    if isinstance(entry_name, str):
        parts.append(entry_name)
    if isinstance(action_cost, str):
        parts.append(f"cost={action_cost}")

    attack_bonus_total = payload.get("attack_bonus_total")
    attack_roll_d20 = payload.get("attack_roll_d20")
    attack_total = payload.get("attack_total")
    damage_formula = payload.get("damage_formula")
    auto_hit = payload.get("auto_hit")
    remaining_uses = payload.get("remaining_uses")
    slot_level_used = payload.get("slot_level_used")
    reason = payload.get("reason")
    if isinstance(attack_roll_d20, int):
        parts.append(f"attack_roll={attack_roll_d20}")
    if isinstance(attack_bonus_total, int):
        parts.append(f"attack_bonus={attack_bonus_total:+d}")
    if isinstance(attack_total, int):
        parts.append(f"attack_total={attack_total}")
    if isinstance(damage_formula, str):
        parts.append(f"damage={damage_formula}")
    if auto_hit is True:
        parts.append("auto_hit=true")
    if isinstance(slot_level_used, int) and slot_level_used > 0:
        parts.append(f"slot_level={slot_level_used}")
    if isinstance(remaining_uses, int):
        parts.append(f"remaining_uses={remaining_uses}")
    if isinstance(reason, str) and reason:
        parts.append(f"reason={reason}")
    if not parts:
        return "no details"
    return " | ".join(parts)


def _latest_action_result(events: list[Event]) -> ActionResult:
    intent = "unknown"
    mechanic = "clarify"
    dice_roll: int | None = None
    mode_from: str | None = None
    mode_to: str | None = None
    action_category = "primary_action"
    resolved_action: dict[str, JSONValue] | None = None

    for event in events:
        if event.event_type == "intent_resolved":
            raw_intent = event.payload.get("intent", intent)
            if isinstance(raw_intent, str):
                intent = raw_intent
            elif raw_intent is not None:
                intent = str(raw_intent)
            raw_mechanic = event.payload.get("mechanic", mechanic)
            if isinstance(raw_mechanic, str):
                mechanic = raw_mechanic
            elif raw_mechanic is not None:
                mechanic = str(raw_mechanic)
            action_category = str(event.payload.get("action_category", action_category))
        elif event.event_type == "dice_roll":
            value = event.payload.get("value")
            if isinstance(value, int):
                dice_roll = value
            elif value is not None:
                try:
                    dice_roll = int(str(value))
                except ValueError:
                    pass
        elif event.event_type == "mode_transition":
            mode_from = str(event.payload.get("from_mode", mode_from or "unknown"))
            mode_to = str(event.payload.get("to_mode", mode_to or "unknown"))
        elif event.event_type == "resolved_action":
            resolved_action = dict(event.payload)

    return ActionResult(
        intent=intent,
        mechanic=mechanic,
        dice_roll=dice_roll,
        mode_from=mode_from,
        mode_to=mode_to,
        action_category=action_category,
        resolved_action=resolved_action,
    )


def _compendium_description(
    entry_id: str,
    entry_kind: str,
    entry_name: str,
) -> str:
    store = _load_compendium_store()
    if store is None:
        return entry_name

    entry = store.get_by_id(entry_id)
    if entry is not None and entry.description:
        return entry.description
    matching_by_name = [
        candidate
        for candidate in store.find_by_name(entry_name)
        if candidate.kind == entry_kind
    ]
    if matching_by_name:
        return matching_by_name[0].description
    return entry_name


def _load_demo_actor(path: str | None) -> Actor:
    if path is None:
        return _default_demo_actor()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"--actor error: {exc}", param_hint="--actor") from exc
    try:
        return _parse_actor_payload(raw, source=path)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--actor") from exc


def _default_demo_actor() -> Actor:
    return Actor(
        actor_id="pc.demo",
        name="Demo Hero",
        class_name="fighter",
        species_name="human",
        level=3,
        proficiency_bonus=2,
        abilities={
            "str": 16,
            "dex": 12,
            "con": 14,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        equipped_weapon_ids=["w.longsword"],
        known_spell_ids=["s.magic_missile"],
        feature_ids=["f.second_wind"],
        spell_slots={1: 2},
        spell_slots_max={1: 2},
        resources={"second_wind_uses": 1},
        max_resources={"second_wind_uses": 1},
        armor_class=16,
        hit_points=24,
        max_hit_points=28,
        hit_die="d10",
        hit_dice_remaining=3,
    )


def _parse_actor_payload(raw: object, source: str) -> Actor:
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: actor payload must be a JSON object")

    actor_id = _actor_required_str(raw, "actor_id", source)
    name = _actor_required_str(raw, "name", source)
    class_name = _actor_optional_str(raw.get("class_name"), "class_name", source)
    species_name = _actor_optional_str(raw.get("species_name"), "species_name", source)
    level = _actor_int(raw.get("level", 1), "level", source, minimum=1)
    proficiency_bonus = _actor_int(
        raw.get("proficiency_bonus", 2),
        "proficiency_bonus",
        source,
        minimum=0,
    )
    abilities = _actor_abilities(raw.get("abilities"), source)
    equipped_weapon_ids = _actor_str_list(
        raw.get("equipped_weapon_ids", []), source, "equipped_weapon_ids"
    )
    known_spell_ids = _actor_str_list(
        raw.get("known_spell_ids", []), source, "known_spell_ids"
    )
    feature_ids = _actor_str_list(raw.get("feature_ids", []), source, "feature_ids")
    item_ids = _actor_str_list(raw.get("item_ids", []), source, "item_ids")
    spell_slots = _actor_int_key_mapping(
        raw.get("spell_slots", {}), source, "spell_slots"
    )
    resources = _actor_str_key_mapping(raw.get("resources", {}), source, "resources")
    max_resources = _actor_str_key_mapping(
        raw.get("max_resources", {}), source, "max_resources"
    )
    spell_slots_max = _actor_int_key_mapping(
        raw.get("spell_slots_max", {}), source, "spell_slots_max"
    )
    armor_class = _actor_optional_int(raw.get("armor_class"), source, "armor_class")
    hit_points = _actor_optional_int(raw.get("hit_points"), source, "hit_points")
    max_hit_points = _actor_optional_int(
        raw.get("max_hit_points"), source, "max_hit_points"
    )
    equipped_armor_id = _actor_optional_str(
        raw.get("equipped_armor_id"), "equipped_armor_id", source
    )
    hit_die = _actor_optional_str(raw.get("hit_die"), "hit_die", source)
    hit_dice_remaining = _actor_optional_int(
        raw.get("hit_dice_remaining"), source, "hit_dice_remaining"
    )
    return Actor(
        actor_id=actor_id,
        name=name,
        class_name=class_name,
        species_name=species_name,
        level=level,
        proficiency_bonus=proficiency_bonus,
        abilities=abilities,
        equipped_weapon_ids=equipped_weapon_ids,
        known_spell_ids=known_spell_ids,
        feature_ids=feature_ids,
        item_ids=item_ids,
        spell_slots=spell_slots,
        spell_slots_max=spell_slots_max,
        resources=resources,
        max_resources=max_resources,
        armor_class=armor_class,
        hit_points=hit_points,
        max_hit_points=max_hit_points,
        equipped_armor_id=equipped_armor_id,
        hit_die=hit_die,
        hit_dice_remaining=hit_dice_remaining,
    )


def _actor_abilities(raw: object, source: str) -> dict[str, int]:
    default = {
        "str": 10,
        "dex": 10,
        "con": 10,
        "int": 10,
        "wis": 10,
        "cha": 10,
    }
    if raw is None:
        return default
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: abilities must be an object")
    abilities = dict(default)
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"{source}: abilities keys must be strings")
        normalized = key.strip().lower()
        if normalized not in abilities:
            raise ValueError(f"{source}: unsupported ability '{key}'")
        abilities[normalized] = _actor_int(value, f"abilities.{normalized}", source)
    return abilities


def _actor_required_str(raw: Mapping[object, object], field: str, source: str) -> str:
    value = raw.get(field)
    if isinstance(value, str) and value:
        return value
    raise ValueError(f"{source}: field '{field}' must be a non-empty string")


def _actor_optional_str(value: object, field: str, source: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ValueError(f"{source}: field '{field}' must be a string or null")


def _actor_optional_int(value: object, source: str, field: str) -> int | None:
    if value is None:
        return None
    return _actor_int(value, field, source)


def _actor_int(
    value: object,
    field: str,
    source: str,
    *,
    minimum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{source}: field '{field}' must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{source}: field '{field}' must be >= {minimum}")
    return value


def _actor_str_list(value: object, source: str, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{source}: field '{field}' must be a list of strings")
    return list(value)


def _actor_int_key_mapping(value: object, source: str, field: str) -> dict[int, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{source}: field '{field}' must be an object")
    parsed: dict[int, int] = {}
    for key, raw_value in value.items():
        key_str = str(key)
        try:
            parsed_key = int(key_str)
        except ValueError as exc:
            raise ValueError(
                f"{source}: field '{field}' keys must be integers"
            ) from exc
        parsed[parsed_key] = _actor_int(
            raw_value, f"{field}.{key_str}", source, minimum=0
        )
    return parsed


def _actor_str_key_mapping(value: object, source: str, field: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{source}: field '{field}' must be an object")
    parsed: dict[str, int] = {}
    for key, raw_value in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{source}: field '{field}' keys must be strings")
        parsed[key] = _actor_int(raw_value, f"{field}.{key}", source, minimum=0)
    return parsed


def _load_compendium_store_from_roots(
    root: list[str] | None,
    *,
    fail_on_missing: bool,
    option_name: str,
) -> CompendiumStore | None:
    global _compendium_store_cache
    if not root:
        return None
    try:
        resolved_roots: list[Path] = []
        for candidate in root:
            resolved_roots.extend(resolve_compendium_roots(candidate))
        store = CompendiumStore()
        store.load(resolved_roots)
        _compendium_store_cache = store
        return store
    except (OSError, CompendiumLoadError) as exc:
        if fail_on_missing:
            typer.echo(f"{option_name} error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        return None


def _load_compendium_store() -> CompendiumStore | None:
    global _compendium_store_cache
    if _compendium_store_cache is not None:
        return _compendium_store_cache
    try:
        roots = resolve_compendium_roots("compendiums")
    except CompendiumLoadError:
        return None

    store = CompendiumStore()
    try:
        store.load(roots)
    except CompendiumLoadError:
        return None
    _compendium_store_cache = store
    return _compendium_store_cache


def _retrieval_docs_from_sources(
    events: list[Event],
    lore_entities: list[dict[str, JSONValue]],
    lore_facts: list[dict[str, JSONValue]],
) -> list[Doc]:
    docs_by_id: dict[str, Doc] = {}

    for entity in lore_entities:
        canonical = canonicalize_entity_record(entity)
        canonical_id = str(canonical["entity_id"])
        text = f"Entity: {canonical['name']} ({canonical['kind']})"
        _upsert_doc(
            docs_by_id,
            Doc(doc_id=f"entity:{canonical_id}", source="lore", text=text),
        )

    for lore_fact in lore_facts:
        lore_fact_text = lore_fact.get("text")
        if not isinstance(lore_fact_text, str) or not lore_fact_text:
            continue
        _upsert_doc(
            docs_by_id,
            Doc(
                doc_id=f"fact:{fact_id(lore_fact_text)}",
                source="lore",
                text=f"Fact: {lore_fact_text}",
            ),
        )

    scribe_result = run_lore_scribe(events)
    sorted_session_facts = sorted(
        scribe_result.facts,
        key=lambda fact: (fact.ts, fact.type, fact.text),
    )
    for session_fact in sorted_session_facts:
        _upsert_doc(
            docs_by_id,
            Doc(
                doc_id=f"fact:{fact_id(session_fact.text)}",
                source="session",
                text=f"Session fact: {session_fact.text}",
            ),
        )

    return [docs_by_id[doc_id] for doc_id in sorted(docs_by_id)]


def _upsert_doc(docs_by_id: dict[str, Doc], doc: Doc) -> None:
    current = docs_by_id.get(doc.doc_id)
    if current is None:
        docs_by_id[doc.doc_id] = doc
        return
    if len(doc.text) < len(current.text):
        docs_by_id[doc.doc_id] = doc


def _graph_neighbor_entries(
    query: str,
    lore_entities: list[dict[str, JSONValue]],
    lore_relations: list[dict[str, JSONValue]],
    depth: int = 1,
    max_neighbors: int = 5,
) -> list[tuple[str, str]]:
    if depth <= 0:
        return []
    if not lore_entities or not lore_relations:
        return []

    query_tokens = [token for token in normalize_name(query).split(" ") if token]
    if not query_tokens:
        return []

    entity_ids_by_name: dict[str, str] = {}
    entity_name_by_id: dict[str, str] = {}
    for entity in lore_entities:
        canonical = canonicalize_entity_record(entity)
        entity_id_value = str(canonical["entity_id"])
        canonical_name = str(canonical["name"])
        entity_name_by_id[entity_id_value] = canonical_name
        entity_ids_by_name[canonical_name] = entity_id_value
        aliases_raw = canonical.get("aliases", [])
        if isinstance(aliases_raw, list):
            for alias in aliases_raw:
                if isinstance(alias, str):
                    entity_ids_by_name[alias] = entity_id_value

    matched_entity_ids = {
        entity_ids_by_name[token]
        for token in query_tokens
        if token in entity_ids_by_name
    }
    if not matched_entity_ids:
        return []

    player = player_entity()
    player_id = str(player["entity_id"])
    entity_name_by_id[player_id] = str(player["name"])

    sorted_relations = _sorted_relations(
        lore_relations=lore_relations,
        entity_name_by_id=entity_name_by_id,
    )
    relations_by_entity = _relations_index_by_entity(sorted_relations)
    expanded = _expand_relations(
        start_entity_ids=sorted(matched_entity_ids),
        relations_by_entity=relations_by_entity,
        depth=depth,
    )
    expanded = _sorted_relations(
        lore_relations=expanded,
        entity_name_by_id=entity_name_by_id,
    )

    if not expanded:
        return []

    selected = expanded[:max_neighbors]
    omitted = len(expanded) - len(selected)

    relation_lines = [
        _relation_line(
            relation=relation,
            entity_name_by_id=entity_name_by_id,
        )
        for relation in selected
    ]
    graph_lines = [f"Graph neighbors (depth={depth}):"]
    graph_lines.extend(f"- {line}" for line in relation_lines)
    if omitted > 0:
        graph_lines.append(f"... (+{omitted} more)")
    graph_text = "\n".join(graph_lines)
    matched_id = sorted(matched_entity_ids)[0]
    return [(f"graph_neighbors:{matched_id}", graph_text)]


def _relations_index_by_entity(
    relations: list[dict[str, JSONValue]],
) -> dict[str, list[dict[str, JSONValue]]]:
    by_entity: dict[str, list[dict[str, JSONValue]]] = {}
    for relation in relations:
        subject_id = str(relation.get("subject_entity_id", ""))
        object_id = str(relation.get("object_entity_id", ""))
        if subject_id:
            by_entity.setdefault(subject_id, []).append(relation)
        if object_id and object_id != subject_id:
            by_entity.setdefault(object_id, []).append(relation)
    return by_entity


def _expand_relations(
    start_entity_ids: list[str],
    relations_by_entity: dict[str, list[dict[str, JSONValue]]],
    depth: int,
) -> list[dict[str, JSONValue]]:
    selected_by_id: dict[str, dict[str, JSONValue]] = {}
    visited_entities = set(start_entity_ids)
    frontier = list(start_entity_ids)

    for _ in range(depth):
        if not frontier:
            break
        next_frontier: set[str] = set()
        for entity_id_value in frontier:
            incident = relations_by_entity.get(entity_id_value, [])
            for relation in incident:
                relation_id_value = str(relation.get("relation_id", ""))
                if not relation_id_value:
                    continue
                if relation_id_value not in selected_by_id:
                    selected_by_id[relation_id_value] = relation
                subject_id = str(relation.get("subject_entity_id", ""))
                object_id = str(relation.get("object_entity_id", ""))
                if subject_id and subject_id not in visited_entities:
                    next_frontier.add(subject_id)
                if object_id and object_id not in visited_entities:
                    next_frontier.add(object_id)
        visited_entities.update(next_frontier)
        frontier = sorted(next_frontier)

    return [selected_by_id[item_id] for item_id in sorted(selected_by_id)]


def _sorted_relations(
    lore_relations: list[dict[str, JSONValue]],
    entity_name_by_id: dict[str, str],
) -> list[dict[str, JSONValue]]:
    return sorted(
        lore_relations,
        key=lambda item: (
            str(item.get("predicate", "")),
            entity_name_by_id.get(
                str(item.get("subject_entity_id", "")),
                str(item.get("subject_entity_id", "")),
            ),
            entity_name_by_id.get(
                str(item.get("object_entity_id", "")),
                str(item.get("object_entity_id", "")),
            ),
            str(item.get("relation_id", "")),
        ),
    )


def _relation_line(
    relation: dict[str, JSONValue],
    entity_name_by_id: dict[str, str],
) -> str:
    subject_id = str(relation.get("subject_entity_id", ""))
    object_id = str(relation.get("object_entity_id", ""))
    predicate = str(relation.get("predicate", "related_to"))
    subject_name = entity_name_by_id.get(subject_id, subject_id)
    object_name = entity_name_by_id.get(object_id, object_id)
    return f"{subject_name} --{predicate}--> {object_name}"


def _display_context_kind(kind: str) -> str:
    if kind == "lorebook":
        return "lore"
    return kind


def _context_bundle_to_dict(bundle: ContextBundle) -> dict[str, JSONValue]:
    items: list[dict[str, JSONValue]] = []
    for item in bundle.items:
        raw_item = asdict(item)
        item_dict: dict[str, JSONValue] = {
            "id": str(raw_item["id"]),
            "kind": str(raw_item["kind"]),
            "text": str(raw_item["text"]),
            "priority": int(raw_item["priority"]),
            "tokens_est": int(raw_item["tokens_est"]),
        }
        items.append(item_dict)
    return {
        "system_text": bundle.system_text,
        "items": items,
        "total_tokens_est": bundle.total_tokens_est,
    }


@app.command()
def reject(
    queue: str = typer.Option(..., "--queue", help="Review queue JSONL path."),
    id: str = typer.Option(..., "--id", help="Queue item id to reject."),
) -> None:
    """Reject one pending queue item (marks it rejected; does not add to lorebook)."""
    queue_store = LoreQueueStore()
    try:
        queue_store.mark_rejected(queue, id)
    except (OSError, ValueError) as exc:
        typer.echo(f"reject error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Rejected {id}")


@app.command()
def rest(
    rest_type: str = typer.Option(
        "short",
        "--type",
        help="Rest type: short or long.",
    ),
    actor: str | None = typer.Option(
        None,
        "--actor",
        help="Actor sheet JSON path. Uses default demo hero if omitted.",
    ),
    hit_dice: int = typer.Option(
        1,
        "--hit-dice",
        help="Number of hit dice to spend during a short rest.",
    ),
    seed: int | None = typer.Option(
        None, "--seed", help="Seed deterministic dice provider for repeatable runs."
    ),
    save_actor: str | None = typer.Option(
        None,
        "--save-actor",
        help="Write updated actor sheet JSON to this path after resting.",
    ),
    campaign_file: str | None = typer.Option(
        None,
        "--campaign-file",
        help="Campaign JSON to update with clock auto-advance after the rest.",
    ),
) -> None:
    """Apply a short or long rest to an actor sheet and print the result."""
    from chronicle_weaver_ai.rules import apply_long_rest, apply_short_rest

    if rest_type not in ("short", "long"):
        typer.echo("--type must be 'short' or 'long'", err=True)
        raise typer.Exit(code=1)

    actor_obj = _load_demo_actor(actor)

    if rest_type == "short":
        dice_provider = (
            SeededDiceProvider(seed) if seed is not None else LocalCSPRNGDiceProvider()
        )
        updated_actor, rolls = apply_short_rest(actor_obj, dice_provider, hit_dice)
        hp_gained = (updated_actor.hit_points or 0) - (actor_obj.hit_points or 0)
        typer.echo(f"Short rest: {actor_obj.name}")
        if rolls:
            typer.echo(
                f"  Hit dice spent: {len(rolls)}  Rolls: {rolls}  HP gained: {hp_gained}"
            )
        else:
            typer.echo(
                "  No hit dice available."
                f" (remaining={actor_obj.hit_dice_remaining or 0})"
            )
    else:
        updated_actor = apply_long_rest(actor_obj)
        hp_restored = (updated_actor.hit_points or 0) - (actor_obj.hit_points or 0)
        typer.echo(f"Long rest: {actor_obj.name}")
        typer.echo(
            f"  HP: {actor_obj.hit_points} -> {updated_actor.hit_points} (+{hp_restored})"
        )

    typer.echo(
        f"  HP: {updated_actor.hit_points}/{updated_actor.max_hit_points}"
        f"  Resources: {dict(updated_actor.resources)}"
        f"  Hit dice remaining: {updated_actor.hit_dice_remaining}"
    )

    if save_actor is not None:
        from chronicle_weaver_ai.campaign import actor_to_dict

        Path(save_actor).write_text(
            json.dumps(actor_to_dict(updated_actor), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        typer.echo(f"  Saved actor -> {save_actor}")

    if campaign_file is not None:
        import dataclasses as _dc

        from chronicle_weaver_ai.campaign import load_campaign, save_campaign
        from chronicle_weaver_ai.models import advance_clock_for_rest

        camp_path = Path(campaign_file)
        if camp_path.exists():
            campaign = load_campaign(camp_path)
            new_clock = advance_clock_for_rest(campaign.world_clock, rest_type)
            updated_campaign = _dc.replace(campaign, world_clock=new_clock)
            save_campaign(updated_campaign, camp_path)
            typer.echo(f"  Clock advanced: {clock_display(new_clock)}")
        else:
            typer.echo(f"  Warning: campaign file not found: {campaign_file}", err=True)


@app.command("advance-time")
def advance_time_cmd(
    minutes: int = typer.Option(..., "--minutes", help="Minutes to advance the clock."),
    campaign_file: str = typer.Option(
        ..., "--campaign-file", help="Path to campaign JSON file."
    ),
) -> None:
    """Advance the world clock by a given number of minutes and save the campaign."""
    from chronicle_weaver_ai.campaign import load_campaign, save_campaign

    path = Path(campaign_file)
    if not path.exists():
        typer.echo(f"Campaign file not found: {campaign_file}", err=True)
        raise typer.Exit(code=1)

    campaign = load_campaign(path)
    before = clock_display(campaign.world_clock)
    new_clock = advance_time(campaign.world_clock, minutes)
    import dataclasses as _dc

    updated = _dc.replace(campaign, world_clock=new_clock)
    save_campaign(updated, path)
    after = clock_display(updated.world_clock)
    typer.echo(f"Clock advanced +{minutes}m: {before} -> {after}")


@app.command("set-persona")
def set_persona(
    campaign_file: str = typer.Option(
        ..., "--campaign-file", help="Path to campaign JSON file."
    ),
    gm_style: str = typer.Option(
        "balanced", "--gm-style", help="GM style: balanced/gritty/heroic/comedic."
    ),
    narrative_voice: str = typer.Option(
        "third_person",
        "--narrative-voice",
        help="Narrative voice: third_person/second_person.",
    ),
    detail_level: str = typer.Option(
        "medium", "--detail-level", help="Detail level: sparse/medium/vivid."
    ),
    character_name: str = typer.Option("", "--character-name", help="PC name."),
    class_flavor: str = typer.Option(
        "", "--class-flavor", help="PC class flavor description."
    ),
    pronouns: str = typer.Option(
        "they/them", "--pronouns", help="PC preferred pronouns."
    ),
) -> None:
    """Update GM and player personas on a campaign file."""
    from chronicle_weaver_ai.campaign import load_campaign, save_campaign

    path = Path(campaign_file)
    if not path.exists():
        typer.echo(f"Campaign file not found: {campaign_file}", err=True)
        raise typer.Exit(code=1)

    campaign = load_campaign(path)
    new_gm = GmPersona(
        gm_style=gm_style,
        narrative_voice=narrative_voice,
        detail_level=detail_level,
    )
    new_player = PlayerPersona(
        character_name=character_name,
        class_flavor=class_flavor,
        pronouns=pronouns,
    )
    import dataclasses as _dc

    updated = _dc.replace(campaign, gm_persona=new_gm, player_persona=new_player)
    save_campaign(updated, path)
    typer.echo(
        f"GM persona: style={gm_style} voice={narrative_voice} detail={detail_level}"
    )
    if character_name:
        typer.echo(f"Player persona: {character_name} ({class_flavor}) [{pronouns}]")


@app.command("check-conflicts")
def check_conflicts_cmd(
    queue: str = typer.Argument(..., help="Path to lore queue JSONL file."),
    lorebook: str = typer.Argument(..., help="Path to lorebook JSON file."),
    status: str = typer.Option(
        "pending", "--status", help="Queue status to check (pending/approved/all)."
    ),
) -> None:
    """Check pending lore queue items for conflicts against the lorebook."""
    from chronicle_weaver_ai.lore.store import LorebookStore, detect_conflicts

    lorebook_store = LorebookStore()
    lore = lorebook_store.load(lorebook)

    queue_store = LoreQueueStore()
    status_filter: str | None = None if status == "all" else status
    items = queue_store.list_items(queue, status=status_filter)

    conflicts = detect_conflicts(items, lore)
    if not conflicts:
        typer.echo(f"No conflicts found ({len(items)} items checked).")
        return

    typer.echo(f"{len(conflicts)} conflict(s) found:")
    for c in conflicts:
        typer.echo(f"  [{c.conflict_type}] item={c.item_id}")
        typer.echo(f"    {c.description}")


@app.command("import-foundry")
def import_foundry_cmd(
    input_path: str = typer.Argument(
        ..., help="Path to Foundry VTT .json or .db (NeDB) file."
    ),
    output_dir: str = typer.Option(
        "compendiums/imported",
        "--output-dir",
        help="Directory to write Chronicle Weaver JSON compendium files.",
    ),
) -> None:
    """Import a Foundry VTT compendium pack into Chronicle Weaver JSON format."""
    from chronicle_weaver_ai.compendium.foundry_adapter import load_foundry_pack

    src = Path(input_path)
    if not src.exists():
        typer.echo(f"Error: {src} does not exist.", err=True)
        raise typer.Exit(1)

    entries = load_foundry_pack(src)
    if not entries:
        typer.echo("No supported entries found in the pack.")
        raise typer.Exit(0)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for entry in entries:
        from dataclasses import asdict as _asdict

        data = _asdict(entry)
        fname = f"{entry.kind}_{entry.id.replace('.', '_')}.json"
        out_file = out_dir / fname
        with out_file.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        written += 1

    typer.echo(f"Imported {written} entries from '{src}' → '{out_dir}'")


@app.command("export-foundry")
def export_foundry_cmd(
    compendium_root: str = typer.Option(
        "compendiums",
        "--compendium-root",
        help="Chronicle Weaver compendium root directory to export.",
    ),
    output_path: str = typer.Option(
        "foundry_export/chronicle_core.db",
        "--output",
        help="Output .db (NeDB JSONL) file path.",
    ),
) -> None:
    """Export Chronicle Weaver compendium entries to a Foundry VTT .db pack."""
    from chronicle_weaver_ai.compendium.foundry_adapter import export_to_foundry_pack

    store = CompendiumStore()
    try:
        roots = resolve_compendium_roots(compendium_root)
        store.load(roots)
    except CompendiumLoadError as exc:
        typer.echo(f"Error loading compendium: {exc}", err=True)
        raise typer.Exit(1)

    if not store.entries:
        typer.echo("No compendium entries found.")
        raise typer.Exit(0)

    out_path = Path(output_path)
    written = export_to_foundry_pack(store.entries, out_path)
    typer.echo(f"Exported {written} entries → '{out_path}'")


if __name__ == "__main__":
    app()
