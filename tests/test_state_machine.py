"""State machine transition tests."""

from chronicle_weaver_ai.models import GameMode, Intent, IntentResult, Mechanic
from chronicle_weaver_ai.state_machine import transition


def test_attack_in_exploration_enters_combat() -> None:
    intent_result = IntentResult(
        intent=Intent.ATTACK,
        mechanic=Mechanic.COMBAT_ROLL,
        confidence=0.95,
        rationale="keyword",
    )
    assert transition(GameMode.EXPLORATION, intent_result) == GameMode.COMBAT


def test_disengage_in_combat_returns_exploration() -> None:
    intent_result = IntentResult(
        intent=Intent.DISENGAGE,
        mechanic=Mechanic.NARRATE_ONLY,
        confidence=0.9,
        rationale="keyword",
    )
    assert transition(GameMode.COMBAT, intent_result) == GameMode.EXPLORATION


def test_ambiguous_result_enters_contested() -> None:
    ambiguous = IntentResult(
        intent=Intent.UNKNOWN,
        mechanic=Mechanic.CLARIFY,
        confidence=0.2,
        rationale="fallback",
        is_valid=False,
    )
    assert transition(GameMode.EXPLORATION, ambiguous) == GameMode.CONTESTED
