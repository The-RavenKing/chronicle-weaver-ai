"""Memory context bundle builder for always-on, session, and lore layers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeAlias

from chronicle_weaver_ai.memory.context_budget import (
    ContextBudgetManager,
    estimate_tokens,
)
from chronicle_weaver_ai.memory.context_models import ContextBundle, ContextItem
from chronicle_weaver_ai.models import (
    CompanionPersona,
    Event,
    GameState,
    GmPersona,
    PlayerPersona,
    WorldClock,
    clock_display,
)
from chronicle_weaver_ai.scribe.scribe import run_lore_scribe

SYSTEM_HEADER = "You are the GM. LLM generates words, not outcomes."
PRIORITY_ALWAYS_ON = 100
PRIORITY_SESSION = 60
PRIORITY_GRAPH = 50
PRIORITY_RETRIEVED = 45
PRIORITY_LORE = 30
ContextEntry: TypeAlias = str | tuple[str, str]


class ContextBuilder:
    """Builds a deterministic LLM context bundle from memory stubs."""

    def __init__(self, budget_manager: ContextBudgetManager | None = None) -> None:
        self._budget_manager = budget_manager or ContextBudgetManager()

    def build(
        self,
        state: GameState,
        recent_events: Sequence[Event] | None = None,
        graph_entries: Sequence[ContextEntry] | None = None,
        retrieved_entries: Sequence[ContextEntry] | None = None,
        lore_entries: Sequence[ContextEntry] | None = None,
        budget_tokens: int = 256,
        recent_limit: int = 6,
        world_clock: WorldClock | None = None,
        gm_persona: GmPersona | None = None,
        player_persona: PlayerPersona | None = None,
        companions: list[CompanionPersona] | None = None,
    ) -> ContextBundle:
        items: list[ContextItem] = []

        persona_text = _persona_text(gm_persona, player_persona, companions)
        clock_text = (
            f"World clock: {clock_display(world_clock)}."
            if world_clock is not None
            else "World clock: Day 1, 08:00 (morning)."
        )

        items.extend(
            [
                _item(
                    "always.persona",
                    "always_on",
                    persona_text,
                    PRIORITY_ALWAYS_ON,
                ),
                _item(
                    "always.clock",
                    "always_on",
                    clock_text,
                    PRIORITY_ALWAYS_ON,
                ),
                _item(
                    "always.party_location",
                    "always_on",
                    "Party/location: stub (party at current scene).",
                    PRIORITY_ALWAYS_ON,
                ),
                _item(
                    "always.mode",
                    "always_on",
                    f"Current mode: {state.mode.value}.",
                    PRIORITY_ALWAYS_ON,
                ),
            ]
        )

        if state.combat is not None:
            items.append(
                _item(
                    "always.combat",
                    "always_on",
                    (
                        "Combat status: "
                        f"round={state.combat.round_number}, "
                        f"turn={state.combat.turn_index}, "
                        f"remaining_entropy={len(state.combat.entropy_pool)}."
                    ),
                    PRIORITY_ALWAYS_ON,
                )
            )

        recent_text = _recent_events_text(
            recent_events=recent_events, limit=recent_limit
        )
        summary_text = _session_summary_text(recent_events=recent_events)
        items.extend(
            [
                _item(
                    "session.recent",
                    "session",
                    recent_text,
                    PRIORITY_SESSION,
                ),
                _item(
                    "session.summary",
                    "session",
                    summary_text,
                    PRIORITY_SESSION,
                ),
            ]
        )

        if retrieved_entries:
            for index, retrieved in enumerate(retrieved_entries):
                item_id, text = _entry_id_text(
                    entry=retrieved,
                    default_id=f"retrieved.{index:03d}",
                )
                items.append(
                    _item(
                        id=item_id,
                        kind="retrieved",
                        text=text,
                        priority=PRIORITY_RETRIEVED,
                    )
                )

        if graph_entries:
            for index, graph in enumerate(graph_entries):
                item_id, text = _entry_id_text(
                    entry=graph,
                    default_id=f"graph.{index:03d}",
                )
                items.append(
                    _item(
                        id=item_id,
                        kind="graph",
                        text=text,
                        priority=PRIORITY_GRAPH,
                    )
                )

        if lore_entries:
            for index, lore in enumerate(lore_entries):
                item_id, text = _entry_id_text(
                    entry=lore,
                    default_id=f"lore.{index:03d}",
                )
                items.append(
                    _item(
                        id=item_id,
                        kind="lorebook",
                        text=text,
                        priority=PRIORITY_LORE,
                    )
                )

        items = _dedupe_items(items)
        selected = self._budget_manager.select(items=items, budget_tokens=budget_tokens)
        total = estimate_tokens(SYSTEM_HEADER) + sum(
            item.tokens_est for item in selected
        )
        return ContextBundle(
            system_text=SYSTEM_HEADER, items=selected, total_tokens_est=total
        )


def _item(id: str, kind: str, text: str, priority: int) -> ContextItem:
    return ContextItem(
        id=id,
        kind=kind,
        text=text,
        priority=priority,
        tokens_est=estimate_tokens(text),
    )


def _recent_events_text(recent_events: Sequence[Event] | None, limit: int) -> str:
    if not recent_events:
        return "Recent: none."
    types = [event.event_type for event in recent_events[-limit:]]
    return f"Recent: {', '.join(types)}."


def _session_summary_text(recent_events: Sequence[Event] | None) -> str:
    if not recent_events:
        return "Session summary: no notable facts."
    scribe_result = run_lore_scribe(list(recent_events))
    return f"Session summary: {scribe_result.summary.text}"


def _entry_id_text(entry: ContextEntry, default_id: str) -> tuple[str, str]:
    if isinstance(entry, tuple):
        return entry
    return default_id, entry


def _dedupe_items(items: Sequence[ContextItem]) -> list[ContextItem]:
    winners: dict[str, ContextItem] = {}
    for item in items:
        current = winners.get(item.id)
        if current is None or _is_preferred(item, current):
            winners[item.id] = item
    return list(winners.values())


def _persona_text(
    gm: GmPersona | None,
    player: PlayerPersona | None,
    companions: list[CompanionPersona] | None = None,
) -> str:
    """Build a compact persona context string from GM, player, and companion personas."""
    gm = gm or GmPersona()
    parts = [
        f"GM style: {gm.gm_style}",
        f"voice: {gm.narrative_voice}",
        f"detail: {gm.detail_level}",
    ]
    if player and player.character_name:
        parts.append(f"PC: {player.character_name}")
        if player.class_flavor:
            parts.append(f"({player.class_flavor})")
        parts.append(f"pronouns: {player.pronouns}")
    if companions:
        companion_strs = [
            f"{c.character_name} [{c.role}]" for c in companions if c.character_name
        ]
        if companion_strs:
            parts.append("companions: " + ", ".join(companion_strs))
    return "Persona: " + ", ".join(parts) + "."


def _is_preferred(candidate: ContextItem, current: ContextItem) -> bool:
    if candidate.priority != current.priority:
        return candidate.priority > current.priority
    if len(candidate.text) != len(current.text):
        return len(candidate.text) < len(current.text)
    if candidate.text != current.text:
        return candidate.text < current.text
    return candidate.kind < current.kind
