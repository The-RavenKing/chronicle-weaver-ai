"""Tests for dense n-gram and hybrid retrieval.

Covers:
- retrieve_dense: basic matching, n-gram soft matching (plurals/variants)
- retrieve_dense: k limit, empty corpus, zero query
- retrieve_hybrid: blends both scorers, returns top-k
- retrieve_hybrid: lexical-only query still works
- retrieve_hybrid: dense-only improvement for morphological variants
- Normalisation: scores in [0, 1] range
"""

from __future__ import annotations

from chronicle_weaver_ai.retrieval.dense import DenseDoc, retrieve_dense
from chronicle_weaver_ai.retrieval.hybrid import HybridDoc, retrieve_hybrid


# ── retrieve_dense unit tests ─────────────────────────────────────────────────


def test_dense_returns_matching_doc():
    docs = [
        DenseDoc("d1", "lore", "The Goblin King rules the cave."),
        DenseDoc("d2", "lore", "A dragon sleeps in the mountain."),
    ]
    results = retrieve_dense("goblin", docs, k=1)
    assert len(results) == 1
    assert results[0].doc_id == "d1"


def test_dense_soft_match_plural():
    """N-gram retrieval should soft-match 'goblins' against 'goblin'."""
    docs = [
        DenseDoc("d1", "lore", "Goblin raiding party attacked."),
        DenseDoc("d2", "lore", "The wizard cast a fireball."),
    ]
    results = retrieve_dense("goblins", docs, k=2)
    # d1 should score higher than d2
    assert results[0].doc_id == "d1"


def test_dense_empty_corpus_returns_empty():
    assert retrieve_dense("query", [], k=5) == []


def test_dense_k_zero_returns_empty():
    docs = [DenseDoc("d1", "lore", "Some text.")]
    assert retrieve_dense("query", docs, k=0) == []


def test_dense_no_matching_grams_returns_empty():
    docs = [DenseDoc("d1", "lore", "xyz")]
    # 3-char grams of "xyz" and "abc" have no overlap
    results = retrieve_dense("abc", docs, k=5)
    assert results == []


def test_dense_respects_k_limit():
    docs = [DenseDoc(f"d{i}", "lore", f"goblin entry {i}") for i in range(10)]
    results = retrieve_dense("goblin", docs, k=3)
    assert len(results) <= 3


def test_dense_scores_positive():
    docs = [DenseDoc("d1", "lore", "The Goblin King is feared.")]
    results = retrieve_dense("goblin king", docs, k=1)
    assert results[0].score > 0.0


# ── retrieve_hybrid unit tests ────────────────────────────────────────────────


def test_hybrid_returns_results():
    docs = [
        HybridDoc("d1", "lore", "The Goblin King commands an army."),
        HybridDoc("d2", "lore", "A fireball scorches the dungeon."),
    ]
    results = retrieve_hybrid("goblin", docs, k=2)
    assert len(results) >= 1
    assert results[0].doc_id == "d1"


def test_hybrid_score_in_range():
    docs = [HybridDoc("d1", "lore", "The Goblin King.")]
    results = retrieve_hybrid("goblin", docs, k=1)
    assert 0.0 < results[0].score <= 1.0


def test_hybrid_exposes_component_scores():
    docs = [HybridDoc("d1", "lore", "Goblin raiding party.")]
    results = retrieve_hybrid("goblin", docs, k=1)
    r = results[0]
    assert r.lexical_score >= 0.0
    assert r.dense_score >= 0.0


def test_hybrid_empty_corpus():
    assert retrieve_hybrid("query", [], k=5) == []


def test_hybrid_k_zero():
    docs = [HybridDoc("d1", "lore", "Goblin.")]
    assert retrieve_hybrid("goblin", docs, k=0) == []


def test_hybrid_respects_k_limit():
    docs = [HybridDoc(f"d{i}", "lore", f"goblin fighter {i}") for i in range(10)]
    results = retrieve_hybrid("goblin", docs, k=4)
    assert len(results) <= 4


def test_hybrid_lexical_only_weight():
    """lexical_weight=1.0, dense_weight=0.0 should produce purely lexical ranking."""
    docs = [
        HybridDoc("d1", "lore", "goblin attack"),
        HybridDoc("d2", "lore", "dragon fire"),
    ]
    results = retrieve_hybrid("goblin", docs, k=2, lexical_weight=1.0, dense_weight=0.0)
    assert results[0].doc_id == "d1"


def test_hybrid_dense_only_weight():
    """dense_weight=1.0, lexical_weight=0.0 should use only n-gram scores."""
    docs = [
        HybridDoc("d1", "lore", "goblin horde marches"),
        HybridDoc("d2", "lore", "castle walls crumble"),
    ]
    results = retrieve_hybrid(
        "goblins", docs, k=2, lexical_weight=0.0, dense_weight=1.0
    )
    # d1 should still win via n-gram soft match
    assert results[0].doc_id == "d1"


def test_hybrid_improves_on_plural_variant():
    """Hybrid should retrieve the correct doc even when query uses plural form."""
    docs = [
        HybridDoc("d1", "lore", "The orc chieftain leads."),
        HybridDoc("d2", "lore", "A peaceful meadow."),
    ]
    # Lexical retrieval of "orcs" (plural) gets zero token overlap with "orc"
    from chronicle_weaver_ai.retrieval.lexical import Doc, retrieve

    lex_results = retrieve("orcs", [Doc(d.doc_id, d.source, d.text) for d in docs], k=2)
    lex_ids = [r.doc_id for r in lex_results]

    hybrid_results = retrieve_hybrid("orcs", docs, k=2)
    hybrid_ids = [r.doc_id for r in hybrid_results]

    # Hybrid must find d1; lexical may miss it
    assert "d1" in hybrid_ids
    # If lexical also found it, hybrid should rank it at least as well
    if "d1" in lex_ids:
        assert hybrid_ids[0] == "d1"
