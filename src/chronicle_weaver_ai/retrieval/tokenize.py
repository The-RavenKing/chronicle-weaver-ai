"""Deterministic lexical tokenization utilities."""

from __future__ import annotations

import re

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
_STOPWORDS = {"the", "a", "an", "to", "and", "of", "in", "on", "at", "is", "are"}


def tokenize(text: str, drop_stopwords: bool = True) -> list[str]:
    """Lowercase deterministic tokenizer split on non-alphanumeric."""
    lowered = text.lower()
    tokens = [token for token in _TOKEN_SPLIT.split(lowered) if token]
    if not drop_stopwords:
        return tokens
    return [token for token in tokens if token not in _STOPWORDS]
