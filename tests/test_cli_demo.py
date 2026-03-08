"""CLI smoke tests."""

import json

from typer.testing import CliRunner

from chronicle_weaver_ai.cli import _run_interactive_turn, app
from chronicle_weaver_ai.dice import FixedEntropyDiceProvider
from chronicle_weaver_ai.engine import Engine
from chronicle_weaver_ai.event_store import InMemoryEventStore
from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.lore.normalize import entity_id, relation_id
from chronicle_weaver_ai.models import EngineConfig, Event, GameMode, GameState
from chronicle_weaver_ai.narration.models import NarrationResponse


def test_cli_demo_smoke(monkeypatch) -> None:
    monkeypatch.setattr(
        "chronicle_weaver_ai.engine.DrandHTTPClient.latest",
        lambda self: (_ for _ in ()).throw(RuntimeError("network disabled in tests")),
    )
    monkeypatch.setattr(
        "chronicle_weaver_ai.engine.DrandHTTPClient.by_round",
        lambda self, round_number: (_ for _ in ()).throw(
            RuntimeError("network disabled in tests")
        ),
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["demo", "--player-input", "attack goblin", "--fixed-entropy", "42"],
    )
    assert result.exit_code == 0
    assert "intent=attack mechanic=combat_roll" in result.stdout
    assert "mode exploration -> combat" in result.stdout


def test_cli_interpret_rules_output() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "interpret",
            "--text",
            "attack goblin",
            "--intent-provider",
            "rules",
        ],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["intent"] == "attack"
    assert parsed["target"] == "goblin"
    assert parsed["provider_used"] == "rules"


def test_cli_interpret_uses_default_compendium() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "interpret",
            "--text",
            "I cast magic missile at the goblin",
            "--intent-provider",
            "rules",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["intent"] == "cast_spell"
    assert payload["target"] == "goblin"
    assert payload["entry_id"] == "s.magic_missile"
    assert payload["entry_kind"] == "spell"
    assert payload["entry_name"] == "Magic Missile"


def test_run_interactive_turn_calls_interpret_engine_and_narrator(monkeypatch) -> None:
    calls = {"interpret": 0, "engine": 0, "narrator": 0}
    printed: list[str] = []

    router = IntentRouter(provider="rules")
    original_route = router.route

    def counted_route(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["interpret"] += 1
        return original_route(*args, **kwargs)

    monkeypatch.setattr(router, "route", counted_route)

    engine = Engine(
        intent_router=router,
        event_store=InMemoryEventStore(),
        dice_provider=FixedEntropyDiceProvider((42,)),
        config=EngineConfig(use_drand=False),
    )
    original_process = engine.process_input

    def counted_process(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["engine"] += 1
        return original_process(*args, **kwargs)

    monkeypatch.setattr(engine, "process_input", counted_process)

    class _FakeNarrator:
        provider = "fake"

        def narrate(self, request):  # type: ignore[no-untyped-def]
            calls["narrator"] += 1
            assert request.action.intent == "attack"
            return NarrationResponse(
                text="You surge toward the goblin and steel flashes.",
                provider="fake",
                model="fake-model",
            )

    def fake_echo(message=None, **kwargs):  # type: ignore[no-untyped-def]
        if not kwargs.get("err"):
            printed.append("" if message is None else str(message))

    monkeypatch.setattr("chronicle_weaver_ai.cli.typer.echo", fake_echo)

    state = _run_interactive_turn(
        engine=engine,
        state=GameState(),
        text="I lunge at the goblin",
        lore_path=None,
        narrator=_FakeNarrator(),
        narrator_provider="auto",
        timeout=None,
        auto_narrate=True,
        debug_prompt=False,
    )

    assert state.mode == GameMode.COMBAT
    assert calls == {"interpret": 1, "engine": 1, "narrator": 1}
    assert any("You surge toward the goblin" in line for line in printed)


def test_cli_demo_load_save_smoke(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "chronicle_weaver_ai.engine.DrandHTTPClient.latest",
        lambda self: (_ for _ in ()).throw(RuntimeError("network disabled in tests")),
    )
    monkeypatch.setattr(
        "chronicle_weaver_ai.engine.DrandHTTPClient.by_round",
        lambda self, round_number: (_ for _ in ()).throw(
            RuntimeError("network disabled in tests")
        ),
    )
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"

    first = runner.invoke(
        app,
        [
            "demo",
            "--player-input",
            "attack goblin",
            "--fixed-entropy",
            "42",
            "--save",
            str(session_path),
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "demo",
            "--player-input",
            "flee",
            "--load",
            str(session_path),
            "--save",
            str(session_path),
        ],
    )
    assert second.exit_code == 0
    assert "Loaded 5 events. Current mode: combat" in second.stdout
    assert "mode combat -> exploration" in second.stdout


def test_cli_context_loads_session_and_lore(tmp_path) -> None:
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"
    lore_path = tmp_path / "lorebook.json"

    events = [
        Event(
            event_type="mode_transition",
            payload={"from_mode": "exploration", "to_mode": "combat"},
            timestamp=1,
        ),
        Event(
            event_type="entropy_prefetched",
            payload={
                "round": 1,
                "initiative_order": ["player", "enemy"],
                "source": "local",
                "values": [42, 43],
            },
            timestamp=2,
        ),
    ]
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict()))
            handle.write("\n")

    with open(lore_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "entities": [{"name": "Goblin", "kind": "npc"}],
                "facts": [{"type": "world", "text": "The tavern is neutral ground."}],
            },
            handle,
        )

    result = runner.invoke(
        app,
        [
            "context",
            "--load",
            str(session_path),
            "--lore",
            str(lore_path),
            "--budget",
            "600",
        ],
    )

    assert result.exit_code == 0
    assert "SYSTEM:" in result.stdout
    assert "Current mode: combat." in result.stdout
    assert "Lore: Entity: goblin (npc)" in result.stdout
    assert "Lore: Fact: The tavern is neutral ground." in result.stdout


def test_cli_context_with_query_prints_retrieved_items(tmp_path) -> None:
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"
    lore_path = tmp_path / "lorebook.json"

    events = [
        Event(
            event_type="player_input",
            payload={"text": "attack goblin near tavern"},
            timestamp=1,
        ),
        Event(
            event_type="intent_resolved",
            payload={"intent": "attack"},
            timestamp=2,
        ),
    ]
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict()))
            handle.write("\n")

    with open(lore_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "entities": [{"name": "Goblin", "kind": "npc"}],
                "facts": [{"type": "world", "text": "Tavern is contested ground."}],
            },
            handle,
        )

    result = runner.invoke(
        app,
        [
            "context",
            "--load",
            str(session_path),
            "--lore",
            str(lore_path),
            "--query",
            "goblin tavern",
            "--k",
            "5",
            "--budget",
            "600",
        ],
    )

    assert result.exit_code == 0
    assert "Retrieved:" in result.stdout


def test_cli_context_query_dedupes_canonical_goblin_entity(tmp_path) -> None:
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"
    lore_path = tmp_path / "lorebook.json"

    events = [
        Event(
            event_type="player_input", payload={"text": "attack goblins"}, timestamp=1
        ),
        Event(
            event_type="intent_resolved",
            payload={"intent": "attack"},
            timestamp=2,
        ),
    ]
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict()))
            handle.write("\n")

    with open(lore_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "entities": [{"name": "Goblin", "kind": "npc"}],
                "facts": [],
            },
            handle,
        )

    result = runner.invoke(
        app,
        [
            "context",
            "--load",
            str(session_path),
            "--lore",
            str(lore_path),
            "--query",
            "goblin",
            "--k",
            "5",
            "--budget",
            "600",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.count("Entity: goblin (npc)") == 1


def test_cli_context_query_includes_graph_neighbors(tmp_path) -> None:
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"
    lore_path = tmp_path / "lorebook.json"

    events = [
        Event(
            event_type="player_input", payload={"text": "attack goblin"}, timestamp=1
        ),
        Event(
            event_type="intent_resolved",
            payload={"intent": "attack"},
            timestamp=2,
        ),
    ]
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict()))
            handle.write("\n")

    player_id = entity_id("player", "pc")
    goblin_id = entity_id("goblin", "npc")
    rel_id = relation_id(player_id, "attacked", goblin_id)
    with open(lore_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "entities": [
                    {
                        "entity_id": player_id,
                        "name": "player",
                        "kind": "pc",
                        "aliases": [],
                        "count": 1,
                    },
                    {
                        "entity_id": goblin_id,
                        "name": "goblin",
                        "kind": "npc",
                        "aliases": [],
                        "count": 1,
                    },
                ],
                "facts": [],
                "relations": [
                    {
                        "relation_id": rel_id,
                        "subject_entity_id": player_id,
                        "predicate": "attacked",
                        "object_entity_id": goblin_id,
                        "evidence": {"event_type": "intent_resolved", "event_ts": 2},
                        "ts_first_seen": 2,
                        "ts_last_seen": 2,
                    }
                ],
            },
            handle,
        )

    result = runner.invoke(
        app,
        [
            "context",
            "--load",
            str(session_path),
            "--lore",
            str(lore_path),
            "--query",
            "goblin",
            "--budget",
            "600",
        ],
    )

    assert result.exit_code == 0
    assert "Graph neighbors (depth=1):" in result.stdout
    assert "- player --attacked--> goblin" in result.stdout


def test_cli_context_graph_neighbors_order_is_deterministic(tmp_path) -> None:
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"
    lore_path = tmp_path / "lorebook.json"

    events = [
        Event(
            event_type="player_input", payload={"text": "inspect goblin"}, timestamp=1
        ),
    ]
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict()))
            handle.write("\n")

    player_id = entity_id("player", "pc")
    goblin_id = entity_id("goblin", "npc")
    amulet_id = entity_id("amulet", "item")
    rel_attack = relation_id(player_id, "attacked", goblin_id)
    rel_owns = relation_id(goblin_id, "owns", amulet_id)

    with open(lore_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "entities": [
                    {
                        "entity_id": player_id,
                        "name": "player",
                        "kind": "pc",
                        "aliases": [],
                        "count": 1,
                    },
                    {
                        "entity_id": goblin_id,
                        "name": "goblin",
                        "kind": "npc",
                        "aliases": [],
                        "count": 1,
                    },
                    {
                        "entity_id": amulet_id,
                        "name": "amulet",
                        "kind": "item",
                        "aliases": [],
                        "count": 1,
                    },
                ],
                "facts": [],
                "relations": [
                    {
                        "relation_id": rel_owns,
                        "subject_entity_id": goblin_id,
                        "predicate": "owns",
                        "object_entity_id": amulet_id,
                        "evidence": {"event_type": "intent_resolved", "event_ts": 2},
                        "ts_first_seen": 2,
                        "ts_last_seen": 2,
                    },
                    {
                        "relation_id": rel_attack,
                        "subject_entity_id": player_id,
                        "predicate": "attacked",
                        "object_entity_id": goblin_id,
                        "evidence": {"event_type": "intent_resolved", "event_ts": 1},
                        "ts_first_seen": 1,
                        "ts_last_seen": 1,
                    },
                ],
            },
            handle,
        )

    result = runner.invoke(
        app,
        [
            "context",
            "--load",
            str(session_path),
            "--lore",
            str(lore_path),
            "--query",
            "goblin",
            "--budget",
            "600",
        ],
    )

    assert result.exit_code == 0
    assert "Graph neighbors (depth=1):" in result.stdout
    assert "- player --attacked--> goblin" in result.stdout
    assert "- goblin --owns--> amulet" in result.stdout


def test_cli_context_graph_depth_0_1_2(tmp_path) -> None:
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"
    lore_path = tmp_path / "lorebook.json"

    with open(session_path, "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                Event(
                    event_type="player_input",
                    payload={"text": "inspect goblin"},
                    timestamp=1,
                ).to_dict()
            )
        )
        handle.write("\n")

    player_id = entity_id("player", "pc")
    goblin_id = entity_id("goblin", "npc")
    tavern_id = entity_id("tavern", "location")
    rel_attack = relation_id(player_id, "attacked", goblin_id)
    rel_located = relation_id(player_id, "located_in", tavern_id)
    with open(lore_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "entities": [
                    {
                        "entity_id": player_id,
                        "name": "player",
                        "kind": "pc",
                        "aliases": [],
                        "count": 1,
                    },
                    {
                        "entity_id": goblin_id,
                        "name": "goblin",
                        "kind": "npc",
                        "aliases": [],
                        "count": 1,
                    },
                    {
                        "entity_id": tavern_id,
                        "name": "tavern",
                        "kind": "location",
                        "aliases": [],
                        "count": 1,
                    },
                ],
                "facts": [],
                "relations": [
                    {
                        "relation_id": rel_attack,
                        "subject_entity_id": player_id,
                        "predicate": "attacked",
                        "object_entity_id": goblin_id,
                        "evidence": {"event_type": "intent_resolved", "event_ts": 1},
                        "ts_first_seen": 1,
                        "ts_last_seen": 1,
                    },
                    {
                        "relation_id": rel_located,
                        "subject_entity_id": player_id,
                        "predicate": "located_in",
                        "object_entity_id": tavern_id,
                        "evidence": {"event_type": "mode_transition", "event_ts": 2},
                        "ts_first_seen": 2,
                        "ts_last_seen": 2,
                    },
                ],
            },
            handle,
        )

    depth0 = runner.invoke(
        app,
        [
            "context",
            "--load",
            str(session_path),
            "--lore",
            str(lore_path),
            "--query",
            "goblin",
            "--graph-depth",
            "0",
        ],
    )
    assert depth0.exit_code == 0
    assert "Graph neighbors:" not in depth0.stdout

    depth1 = runner.invoke(
        app,
        [
            "context",
            "--load",
            str(session_path),
            "--lore",
            str(lore_path),
            "--query",
            "goblin",
            "--graph-depth",
            "1",
        ],
    )
    assert depth1.exit_code == 0
    assert "Graph neighbors (depth=1):" in depth1.stdout
    assert "- player --attacked--> goblin" in depth1.stdout
    assert "located_in" not in depth1.stdout

    depth2 = runner.invoke(
        app,
        [
            "context",
            "--load",
            str(session_path),
            "--lore",
            str(lore_path),
            "--query",
            "goblin",
            "--graph-depth",
            "2",
        ],
    )
    assert depth2.exit_code == 0
    assert "Graph neighbors (depth=2):" in depth2.stdout
    assert "- player --attacked--> goblin" in depth2.stdout
    assert "- player --located_in--> tavern" in depth2.stdout


def test_cli_context_graph_k_cap_appends_more_line(tmp_path) -> None:
    runner = CliRunner()
    session_path = tmp_path / "session.jsonl"
    lore_path = tmp_path / "lorebook.json"

    with open(session_path, "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                Event(
                    event_type="player_input",
                    payload={"text": "inspect goblin"},
                    timestamp=1,
                ).to_dict()
            )
        )
        handle.write("\n")

    player_id = entity_id("player", "pc")
    goblin_id = entity_id("goblin", "npc")
    tavern_id = entity_id("tavern", "location")
    amulet_id = entity_id("amulet", "item")
    relations = [
        {
            "relation_id": relation_id(player_id, "attacked", goblin_id),
            "subject_entity_id": player_id,
            "predicate": "attacked",
            "object_entity_id": goblin_id,
            "evidence": {"event_type": "intent_resolved", "event_ts": 1},
            "ts_first_seen": 1,
            "ts_last_seen": 1,
        },
        {
            "relation_id": relation_id(player_id, "located_in", tavern_id),
            "subject_entity_id": player_id,
            "predicate": "located_in",
            "object_entity_id": tavern_id,
            "evidence": {"event_type": "mode_transition", "event_ts": 2},
            "ts_first_seen": 2,
            "ts_last_seen": 2,
        },
        {
            "relation_id": relation_id(goblin_id, "owns", amulet_id),
            "subject_entity_id": goblin_id,
            "predicate": "owns",
            "object_entity_id": amulet_id,
            "evidence": {"event_type": "intent_resolved", "event_ts": 3},
            "ts_first_seen": 3,
            "ts_last_seen": 3,
        },
    ]
    with open(lore_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "entities": [
                    {
                        "entity_id": player_id,
                        "name": "player",
                        "kind": "pc",
                        "aliases": [],
                        "count": 1,
                    },
                    {
                        "entity_id": goblin_id,
                        "name": "goblin",
                        "kind": "npc",
                        "aliases": [],
                        "count": 1,
                    },
                    {
                        "entity_id": tavern_id,
                        "name": "tavern",
                        "kind": "location",
                        "aliases": [],
                        "count": 1,
                    },
                    {
                        "entity_id": amulet_id,
                        "name": "amulet",
                        "kind": "item",
                        "aliases": [],
                        "count": 1,
                    },
                ],
                "facts": [],
                "relations": relations,
            },
            handle,
        )

    result = runner.invoke(
        app,
        [
            "context",
            "--load",
            str(session_path),
            "--lore",
            str(lore_path),
            "--query",
            "goblin",
            "--graph-depth",
            "2",
            "--graph-k",
            "1",
            "--budget",
            "600",
        ],
    )

    assert result.exit_code == 0
    assert "Graph neighbors (depth=2):" in result.stdout
    assert result.stdout.count("\n- ") >= 1
    assert "... (+2 more)" in result.stdout
