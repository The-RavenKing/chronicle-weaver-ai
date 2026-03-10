"""Character n-gram TF-IDF retrieval.

Provides soft matching that catches morphological variants (plural/singular,
partial names) that pure lexical retrieval misses.

Algorithm
---------
1. Extract character n-grams of sizes *ngram_sizes* from each token.
2. Build an IDF weight table over the corpus.
3. For each document, compute a sparse TF-IDF vector (n-gram → weight).
4. Score queries against documents by cosine similarity of their TF-IDF vectors.

All arithmetic is pure Python — no numpy / scipy required.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from chronicle_weaver_ai.retrieval.tokenize import tokenize


@dataclass(frozen=True)
class DenseDoc:
    """Candidate document for n-gram TF-IDF retrieval (same shape as lexical.Doc)."""

    doc_id: str
    source: str
    text: str


@dataclass(frozen=True)
class DenseRetrievedDoc:
    """Retrieved document with n-gram TF-IDF cosine score."""

    doc_id: str
    source: str
    text: str
    score: float


def _char_ngrams(text: str, sizes: tuple[int, ...] = (3, 4)) -> list[str]:
    """Return all character n-grams of given sizes from *text*."""
    grams: list[str] = []
    for n in sizes:
        for i in range(len(text) - n + 1):
            grams.append(text[i : i + n])
    return grams


def _doc_ngrams(text: str, sizes: tuple[int, ...] = (3, 4)) -> list[str]:
    """Tokenize *text* then extract character n-grams from each token."""
    tokens = tokenize(text, drop_stopwords=True)
    grams: list[str] = []
    for token in tokens:
        grams.extend(_char_ngrams(token, sizes))
    return grams


def _tf(grams: list[str]) -> dict[str, float]:
    """Compute raw term frequency (count / total) for a gram list."""
    if not grams:
        return {}
    counts: dict[str, int] = {}
    for g in grams:
        counts[g] = counts.get(g, 0) + 1
    total = len(grams)
    return {g: count / total for g, count in counts.items()}


def _idf(
    doc_tfs: list[dict[str, float]],
) -> dict[str, float]:
    """Compute IDF weights over a corpus of TF dicts."""
    n = len(doc_tfs)
    df: dict[str, int] = {}
    for tf_vec in doc_tfs:
        for gram in tf_vec:
            df[gram] = df.get(gram, 0) + 1
    return {gram: math.log((n + 1) / (freq + 1)) + 1.0 for gram, freq in df.items()}


def _tfidf(tf_vec: dict[str, float], idf_weights: dict[str, float]) -> dict[str, float]:
    """Multiply TF by IDF to produce a TF-IDF vector."""
    return {gram: tf * idf_weights.get(gram, 1.0) for gram, tf in tf_vec.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors (dicts)."""
    if not a or not b:
        return 0.0
    dot = sum(a.get(g, 0.0) * b.get(g, 0.0) for g in b)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve_dense(
    query: str,
    docs: list[DenseDoc],
    k: int = 5,
    ngram_sizes: tuple[int, ...] = (3, 4),
) -> list[DenseRetrievedDoc]:
    """Return top-k documents ranked by n-gram TF-IDF cosine similarity.

    Handles morphological variants and partial name matches better than
    the lexical retriever.  Complements rather than replaces lexical retrieval.
    """
    if k <= 0 or not docs:
        return []

    query_grams = _doc_ngrams(query, ngram_sizes)
    if not query_grams:
        return []

    doc_gram_lists = [_doc_ngrams(doc.text, ngram_sizes) for doc in docs]
    doc_tfs = [_tf(grams) for grams in doc_gram_lists]
    idf_weights = _idf(doc_tfs)

    query_tf = _tf(query_grams)
    query_vec = _tfidf(query_tf, idf_weights)

    scored: list[DenseRetrievedDoc] = []
    for doc, doc_tf in zip(docs, doc_tfs):
        doc_vec = _tfidf(doc_tf, idf_weights)
        score = _cosine(query_vec, doc_vec)
        if score > 0.0:
            scored.append(
                DenseRetrievedDoc(
                    doc_id=doc.doc_id,
                    source=doc.source,
                    text=doc.text,
                    score=score,
                )
            )

    scored.sort(key=lambda r: (-r.score, len(r.text), r.doc_id))
    return scored[:k]
