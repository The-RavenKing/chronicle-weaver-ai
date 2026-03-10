"""Hybrid retrieval — blends lexical IDF-overlap with n-gram TF-IDF cosine.

Usage
-----
from chronicle_weaver_ai.retrieval.hybrid import HybridDoc, retrieve_hybrid

docs = [HybridDoc(doc_id="d1", source="lore", text="The Goblin King rules...")]
results = retrieve_hybrid("goblin king", docs, k=3)

Design
------
Scores are normalised to [0, 1] per method then combined:

    final_score = lexical_weight * norm_lexical + dense_weight * norm_dense

Both weights default to 0.5 so neither method dominates.  The lexical
component catches exact token matches; the dense component catches partial
names, plurals, and morphological variants.
"""

from __future__ import annotations

from dataclasses import dataclass

from chronicle_weaver_ai.retrieval.dense import DenseDoc, retrieve_dense
from chronicle_weaver_ai.retrieval.lexical import Doc, retrieve


@dataclass(frozen=True)
class HybridDoc:
    """Candidate document for hybrid retrieval."""

    doc_id: str
    source: str
    text: str


@dataclass(frozen=True)
class HybridRetrievedDoc:
    """Retrieved document with blended lexical + dense score."""

    doc_id: str
    source: str
    text: str
    score: float
    lexical_score: float
    dense_score: float


def retrieve_hybrid(
    query: str,
    docs: list[HybridDoc],
    k: int = 5,
    lexical_weight: float = 0.5,
    dense_weight: float = 0.5,
) -> list[HybridRetrievedDoc]:
    """Return top-k documents ranked by a weighted blend of lexical and dense scores.

    Parameters
    ----------
    query          — free-text query string.
    docs           — candidate document pool.
    k              — number of results to return.
    lexical_weight — weight applied to normalised lexical score (default 0.5).
    dense_weight   — weight applied to normalised n-gram dense score (default 0.5).
    """
    if k <= 0 or not docs:
        return []

    lexical_docs = [Doc(doc_id=d.doc_id, source=d.source, text=d.text) for d in docs]
    dense_docs = [DenseDoc(doc_id=d.doc_id, source=d.source, text=d.text) for d in docs]

    # Retrieve with a large k so we can blend all candidates
    fetch_k = len(docs)
    lexical_results = retrieve(query, lexical_docs, k=fetch_k)
    dense_results = retrieve_dense(query, dense_docs, k=fetch_k)

    # Build score maps (doc_id → raw score)
    lexical_map: dict[str, float] = {r.doc_id: r.score for r in lexical_results}
    dense_map: dict[str, float] = {r.doc_id: r.score for r in dense_results}

    # Normalise each to [0, 1]
    def _normalise(scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}
        max_score = max(scores.values())
        if max_score == 0.0:
            return {k: 0.0 for k in scores}
        return {k: v / max_score for k, v in scores.items()}

    norm_lexical = _normalise(lexical_map)
    norm_dense = _normalise(dense_map)

    # Union of all doc_ids that scored in either method
    all_ids = set(norm_lexical) | set(norm_dense)

    # Build a lookup from doc_id to original HybridDoc
    doc_lookup: dict[str, HybridDoc] = {d.doc_id: d for d in docs}

    scored: list[HybridRetrievedDoc] = []
    for doc_id in all_ids:
        lex_score = norm_lexical.get(doc_id, 0.0)
        den_score = norm_dense.get(doc_id, 0.0)
        combined = lexical_weight * lex_score + dense_weight * den_score
        if combined == 0.0:
            continue
        doc = doc_lookup[doc_id]
        scored.append(
            HybridRetrievedDoc(
                doc_id=doc_id,
                source=doc.source,
                text=doc.text,
                score=combined,
                lexical_score=lex_score,
                dense_score=den_score,
            )
        )

    scored.sort(key=lambda r: (-r.score, len(r.text), r.doc_id))
    return scored[:k]
