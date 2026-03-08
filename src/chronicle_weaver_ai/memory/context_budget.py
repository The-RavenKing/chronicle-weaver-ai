"""Deterministic context budgeting and token estimation."""

from __future__ import annotations

from chronicle_weaver_ai.memory.context_models import ContextItem


def estimate_tokens(text: str) -> int:
    """Deterministic coarse token estimator."""
    return max(1, len(text) // 4)


class ContextBudgetManager:
    """Selects context items deterministically under a token budget."""

    def select(self, items: list[ContextItem], budget_tokens: int) -> list[ContextItem]:
        if budget_tokens <= 0:
            return []

        ordered = sorted(
            items, key=lambda item: (-item.priority, item.tokens_est, item.id)
        )
        selected: list[ContextItem] = []
        used = 0
        for item in ordered:
            item_tokens = max(1, item.tokens_est)
            if used + item_tokens > budget_tokens:
                continue
            selected.append(item)
            used += item_tokens
        return selected
