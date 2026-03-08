"""Tests for deterministic context bundle construction."""

from chronicle_weaver_ai.memory.context_builder import ContextBuilder
from chronicle_weaver_ai.models import CombatState, Event, GameMode, GameState


def test_context_builder_includes_always_on_and_session_items() -> None:
    state = GameState(
        mode=GameMode.COMBAT,
        combat=CombatState(
            round_number=2,
            turn_index=1,
            initiative_order=["player", "enemy"],
            entropy_pool=[1, 2, 3],
            entropy_source="local",
        ),
    )
    events = [
        Event(event_type="intent_resolved", payload={}, timestamp=1),
        Event(event_type="mode_transition", payload={}, timestamp=2),
    ]
    builder = ContextBuilder()
    bundle = builder.build(
        state=state,
        recent_events=events,
        lore_entries=["The moon gate opens at dawn."],
        budget_tokens=500,
    )

    ids = {item.id for item in bundle.items}
    assert "always.mode" in ids
    assert "always.combat" in ids
    assert "session.recent" in ids
    assert "session.summary" in ids
    assert bundle.system_text.startswith("You are the GM.")


def test_context_builder_respects_budget_and_prefers_high_priority() -> None:
    state = GameState(mode=GameMode.EXPLORATION)
    events = [Event(event_type=f"e{i}", payload={}, timestamp=i) for i in range(4)]
    lore = ["lore one", "lore two", "lore three"]
    builder = ContextBuilder()
    bundle = builder.build(
        state=state,
        recent_events=events,
        lore_entries=lore,
        budget_tokens=20,
    )
    assert bundle.items
    assert bundle.items[0].id == "always.mode"
    assert sum(item.tokens_est for item in bundle.items) <= 20
    priorities = [item.priority for item in bundle.items]
    assert priorities == sorted(priorities, reverse=True)


def test_context_builder_uses_lore_scribe_summary_for_session() -> None:
    state = GameState(mode=GameMode.EXPLORATION)
    events = [
        Event(
            event_type="player_input", payload={"text": "attack goblin"}, timestamp=1
        ),
        Event(
            event_type="intent_resolved",
            payload={"intent": "attack"},
            timestamp=2,
        ),
        Event(
            event_type="mode_transition",
            payload={"from_mode": "exploration", "to_mode": "combat"},
            timestamp=3,
        ),
    ]

    bundle = ContextBuilder().build(
        state=state, recent_events=events, budget_tokens=500
    )
    summary_item = next(item for item in bundle.items if item.id == "session.summary")
    assert summary_item.text.startswith("Session summary:")
    assert "Player intent: attack" in summary_item.text


def test_context_builder_dedupes_same_entity_across_layers() -> None:
    state = GameState(mode=GameMode.EXPLORATION)
    bundle = ContextBuilder().build(
        state=state,
        recent_events=[],
        retrieved_entries=[
            ("entity:abc123", "Retrieved: Entity: goblin (npc) (score=2.000)")
        ],
        lore_entries=[
            ("entity:abc123", "Lore: Entity: goblin (npc)"),
        ],
        budget_tokens=500,
    )

    goblin_items = [item for item in bundle.items if item.id == "entity:abc123"]
    assert len(goblin_items) == 1
    assert goblin_items[0].kind == "retrieved"
