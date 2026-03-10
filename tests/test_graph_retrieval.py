"""Tests for GraphRAG-lite graph retrieval."""

from __future__ import annotations


from chronicle_weaver_ai.lore.models import Lorebook
from chronicle_weaver_ai.retrieval.graph_retrieval import (
    GraphRetriever,
    build_lore_docs,
)


def _lorebook() -> Lorebook:
    entities = [
        {
            "entity_id": "e1",
            "name": "Goblin King",
            "kind": "npc",
            "description": "Rules the cave",
        },
        {
            "entity_id": "e2",
            "name": "Dark Cave",
            "kind": "location",
            "description": "Underground hideout",
        },
        {
            "entity_id": "e3",
            "name": "Iron Sword",
            "kind": "item",
            "description": "Sharp blade",
        },
        {
            "entity_id": "e4",
            "name": "Aldric",
            "kind": "npc",
            "description": "Hero knight",
        },
    ]
    facts = [
        {"content": "The Goblin King lives in the Dark Cave.", "entity_ids": "e1,e2"},
        {"content": "Aldric carries the Iron Sword.", "entity_ids": "e3,e4"},
    ]
    relations = [
        {
            "relation_id": "r1",
            "subject_entity_id": "e1",
            "predicate": "inhabits",
            "object_entity_id": "e2",
        },
        {
            "relation_id": "r2",
            "subject_entity_id": "e4",
            "predicate": "carries",
            "object_entity_id": "e3",
        },
    ]
    return Lorebook(entities=entities, facts=facts, relations=relations)


def test_graph_retriever_returns_seed_entity() -> None:
    retriever = GraphRetriever(_lorebook())
    results = retriever.retrieve("Goblin King", k=3)
    assert len(results) > 0
    ids = [r.item_id for r in results]
    assert "e1" in ids


def test_graph_retriever_expands_neighbours() -> None:
    retriever = GraphRetriever(_lorebook())
    results = retriever.retrieve("Goblin King", k=10, max_hops=1)
    ids = [r.item_id for r in results]
    # e2 (Dark Cave) is 1 hop from e1 via "inhabits"
    assert "e2" in ids


def test_graph_retriever_seed_ranks_first() -> None:
    retriever = GraphRetriever(_lorebook())
    results = retriever.retrieve("Goblin King", k=5)
    assert results[0].hop == 0  # seed match first


def test_graph_retriever_respects_k() -> None:
    retriever = GraphRetriever(_lorebook())
    results = retriever.retrieve("Goblin King", k=2)
    assert len(results) <= 2


def test_graph_retriever_includes_facts() -> None:
    retriever = GraphRetriever(_lorebook())
    results = retriever.retrieve("Goblin King", k=10, max_hops=1)
    item_types = {r.item_type for r in results}
    assert "fact" in item_types


def test_graph_retriever_empty_lorebook() -> None:
    retriever = GraphRetriever(Lorebook(entities=[], facts=[], relations=[]))
    results = retriever.retrieve("anything", k=5)
    assert results == []


def test_graph_retriever_no_relations() -> None:
    lorebook = Lorebook(
        entities=[
            {
                "entity_id": "e1",
                "name": "Goblin",
                "kind": "npc",
                "description": "A goblin",
            }
        ],
        facts=[],
        relations=[],
    )
    retriever = GraphRetriever(lorebook)
    results = retriever.retrieve("goblin", k=3)
    assert len(results) >= 1


def test_build_lore_docs_creates_docs() -> None:
    docs = build_lore_docs(_lorebook())
    assert len(docs) == 4
    doc_ids = {d.doc_id for d in docs}
    assert "e1" in doc_ids
    assert "e4" in doc_ids


def test_graph_retriever_hop_0_score_highest() -> None:
    retriever = GraphRetriever(_lorebook())
    results = retriever.retrieve("Goblin King", k=10, max_hops=2)
    if len(results) >= 2:
        hop0 = [r for r in results if r.hop == 0]
        hop1 = [r for r in results if r.hop == 1]
        if hop0 and hop1:
            assert hop0[0].score >= hop1[0].score
