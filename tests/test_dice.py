"""Dice mapping and provider tests."""

from chronicle_weaver_ai.dice import (
    ACCEPTANCE_CEILING,
    FixedEntropyDiceProvider,
    LocalCSPRNGDiceProvider,
    roll_d20,
    roll_d20_record,
)


def test_roll_d20_returns_1_to_20_for_accepted_values() -> None:
    assert roll_d20(0) == 1
    assert roll_d20(19) == 20
    assert roll_d20(20) == 1
    assert roll_d20(39) == 20


def test_roll_d20_rejects_tail_values() -> None:
    assert roll_d20(ACCEPTANCE_CEILING) is None


def test_roll_record_uses_rejection_sampling_and_stays_stable() -> None:
    provider = FixedEntropyDiceProvider((ACCEPTANCE_CEILING, 41))
    record = roll_d20_record(provider)
    assert record.value == 2
    assert record.attempts == 2
    assert record.entropy == ACCEPTANCE_CEILING
    assert record.accepted_entropy == 41


def test_local_provider_returns_u32() -> None:
    provider = LocalCSPRNGDiceProvider()
    value = provider.next_u32()
    assert 0 <= value <= (2**32 - 1)
