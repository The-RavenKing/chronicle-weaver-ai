"""Tests for deterministic lexical retrieval."""

from chronicle_weaver_ai.retrieval.lexical import Doc, retrieve


def test_retrieve_ranks_obvious_match_first() -> None:
    docs = [
        Doc(doc_id="doc-1", source="lore", text="goblin ambush near tavern"),
        Doc(doc_id="doc-2", source="lore", text="baron owns amulet"),
        Doc(doc_id="doc-3", source="session", text="rolled d20 17"),
    ]

    results = retrieve(query="goblin tavern", docs=docs, k=5)

    assert results
    assert results[0].doc_id == "doc-1"


def test_retrieve_tie_breaks_length_then_id() -> None:
    docs = [
        Doc(doc_id="doc-b", source="lore", text="goblin"),
        Doc(doc_id="doc-a", source="lore", text="goblin"),
        Doc(doc_id="doc-c", source="lore", text="goblin cave"),
    ]

    results = retrieve(query="goblin", docs=docs, k=5)

    assert [doc.doc_id for doc in results] == ["doc-a", "doc-b", "doc-c"]
