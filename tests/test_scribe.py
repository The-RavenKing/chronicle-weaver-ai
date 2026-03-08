"""Tests for deterministic Lore Scribe extraction."""

from chronicle_weaver_ai.lore.normalize import entity_id
from chronicle_weaver_ai.models import Event
from chronicle_weaver_ai.scribe.scribe import run_lore_scribe


def _sample_events() -> list[Event]:
    return [
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
        Event(event_type="dice_roll", payload={"value": 13}, timestamp=4),
        Event(
            event_type="entropy_prefetched",
            payload={"source": "local", "values": [42, 43]},
            timestamp=5,
        ),
    ]


def test_scribe_determinism_same_input_same_output() -> None:
    events = _sample_events()
    first = run_lore_scribe(events)
    second = run_lore_scribe(events)
    assert first == second


def test_scribe_basic_extraction_from_events() -> None:
    result = run_lore_scribe(_sample_events())
    assert "Player intent: attack" in result.summary.text
    assert "Mode changed exploration -> combat" in result.summary.text
    assert any(entity.name.lower() == "goblin" for entity in result.entities)
    assert any(fact.text == "Rolled d20=13" for fact in result.facts)
    target_relation = next(
        relation for relation in result.relations if relation.predicate == "attacked"
    )
    assert target_relation.object_name == "goblin"
    assert target_relation.object_entity_id == entity_id("goblin", "unknown")
