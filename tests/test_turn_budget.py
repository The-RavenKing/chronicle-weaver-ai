"""Turn budget unit tests for deterministic action economy v0."""

from dataclasses import replace

from chronicle_weaver_ai.models import (
    can_spend_action,
    can_use_object_interaction,
    mark_spoken,
    new_turn_budget,
    spend_action,
    spend_object_interaction,
)


def test_attack_consumes_action() -> None:
    budget = new_turn_budget()
    assert can_spend_action(budget)

    updated, used = spend_action(budget)
    assert used is True
    assert updated.action is False
    assert can_spend_action(updated) is False


def test_disengage_consumes_action() -> None:
    budget = new_turn_budget()

    updated, used = spend_action(budget)
    assert used is True
    assert updated.action is False


def test_speech_does_not_consume_action() -> None:
    budget = new_turn_budget()

    updated, spoken = mark_spoken(budget)
    assert spoken is True
    assert updated.speech is False
    assert updated.action is True


def test_one_object_interaction_is_free() -> None:
    budget = new_turn_budget()
    assert can_use_object_interaction(budget)

    after_first, first_used = spend_object_interaction(budget)
    assert first_used is True
    assert after_first.object_interaction is False

    after_second, second_used = spend_object_interaction(after_first)
    assert second_used is False
    assert after_second.object_interaction is False


def test_new_turn_resets_spendable_fields() -> None:
    replace(
        new_turn_budget(),
        action=False,
        object_interaction=False,
        speech=False,
        movement_remaining=12,
    )

    fresh = new_turn_budget()
    assert fresh.action is True
    assert fresh.object_interaction is True
    assert fresh.speech is True
    assert fresh.movement_remaining == 30
