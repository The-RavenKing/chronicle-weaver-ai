"""Deterministic lexical retrieval with IDF-weighted token overlap."""

from __future__ import annotations

import math
from dataclasses import dataclass

from chronicle_weaver_ai.retrieval.tokenize import tokenize


@dataclass(frozen=True)
class Doc:
    """Candidate document for lexical retrieval."""

    doc_id: str
    source: str
    text: str


@dataclass(frozen=True)
class RetrievedDoc:
    """Retrieved document with deterministic lexical score."""

    doc_id: str
    source: str
    text: str
    score: float


def retrieve(query: str, docs: list[Doc], k: int = 5) -> list[RetrievedDoc]:
    """Retrieve top-k docs by deterministic IDF-weighted lexical overlap."""
    if k <= 0:
        return []
    if not docs:
        return []

    query_tokens = set(tokenize(query))
    if not query_tokens:
        return []

    doc_token_sets = {doc.doc_id: set(tokenize(doc.text)) for doc in docs}
    doc_frequency: dict[str, int] = {}
    for token_set in doc_token_sets.values():
        for token in token_set:
            doc_frequency[token] = doc_frequency.get(token, 0) + 1

    total_docs = len(docs)
    scored: list[RetrievedDoc] = []
    for doc in docs:
        token_set = doc_token_sets[doc.doc_id]
        intersection = query_tokens.intersection(token_set)
        if not intersection:
            continue
        score = 0.0
        for token in intersection:
            df = doc_frequency[token]
            score += math.log((total_docs + 1) / (df + 1)) + 1.0
        scored.append(
            RetrievedDoc(
                doc_id=doc.doc_id,
                source=doc.source,
                text=doc.text,
                score=score,
            )
        )

    scored.sort(key=lambda item: (-item.score, len(item.text), item.doc_id))
    return scored[:k]
