"""Context scaffolding models for deterministic memory assembly."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextItem:
    """One candidate memory item for LLM context construction."""

    id: str
    kind: str
    text: str
    priority: int
    tokens_est: int


@dataclass(frozen=True)
class ContextBundle:
    """Final context payload selected under a token budget."""

    system_text: str
    items: list[ContextItem]
    total_tokens_est: int
