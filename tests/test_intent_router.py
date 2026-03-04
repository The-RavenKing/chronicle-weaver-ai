"""Intent routing tests."""

from chronicle_weaver_ai.intent_router import IntentRouter
from chronicle_weaver_ai.models import GameMode, Intent, Mechanic


def test_keyword_attack_routes_to_combat_roll() -> None:
    router = IntentRouter()
    result = router.route("attack goblin", current_mode=GameMode.EXPLORATION)
    assert result.intent == Intent.ATTACK
    assert result.mechanic == Mechanic.COMBAT_ROLL


def test_keyword_search_routes_to_narrate_only() -> None:
    router = IntentRouter()
    result = router.route("inspect room", current_mode=GameMode.EXPLORATION)
    assert result.intent == Intent.SEARCH
    assert result.mechanic == Mechanic.NARRATE_ONLY


def test_flee_routes_to_disengage() -> None:
    router = IntentRouter()
    result = router.route("flee now", current_mode=GameMode.COMBAT)
    assert result.intent == Intent.DISENGAGE
    assert result.mechanic == Mechanic.DISENGAGE


def test_end_combat_routes_to_disengage() -> None:
    router = IntentRouter()
    result = router.route("end combat", current_mode=GameMode.COMBAT)
    assert result.intent == Intent.DISENGAGE
    assert result.mechanic == Mechanic.DISENGAGE


def test_unknown_routes_to_clarify() -> None:
    router = IntentRouter()
    result = router.route("???", current_mode=GameMode.EXPLORATION)
    assert result.intent == Intent.UNKNOWN
    assert result.mechanic == Mechanic.CLARIFY
