"""Tests for deterministic context budgeting."""

from chronicle_weaver_ai.memory.context_budget import ContextBudgetManager
from chronicle_weaver_ai.memory.context_models import ContextItem


def test_budget_selection_order_and_trimming_is_deterministic() -> None:
    items = [
        ContextItem(id="b", kind="x", text="x", priority=100, tokens_est=5),
        ContextItem(id="a", kind="x", text="x", priority=100, tokens_est=2),
        ContextItem(id="c", kind="x", text="x", priority=60, tokens_est=1),
        ContextItem(id="d", kind="x", text="x", priority=60, tokens_est=2),
    ]
    selected = ContextBudgetManager().select(items, budget_tokens=3)
    assert [item.id for item in selected] == ["a", "c"]


def test_budget_tie_breaks_on_id_lexical() -> None:
    items = [
        ContextItem(id="item-b", kind="x", text="x", priority=50, tokens_est=1),
        ContextItem(id="item-a", kind="x", text="x", priority=50, tokens_est=1),
    ]
    selected = ContextBudgetManager().select(items, budget_tokens=2)
    assert [item.id for item in selected] == ["item-a", "item-b"]
