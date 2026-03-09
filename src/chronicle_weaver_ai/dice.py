"""Deterministic dice mapping and providers."""

from __future__ import annotations

import random
import re
import secrets
from dataclasses import dataclass

from chronicle_weaver_ai.models import DiceProvider, DiceRollRecord

U32_MAX = 2**32 - 1
ACCEPTANCE_CEILING = (2**32 // 20) * 20


def roll_d20(entropy: int) -> int | None:
    """
    Map one u32 entropy sample to d20 with rejection sampling.

    Returns `None` when the sample falls in the rejected tail to avoid modulo bias.
    """
    if entropy < 0 or entropy > U32_MAX:
        raise ValueError("entropy must be within [0, 2**32 - 1]")
    if entropy >= ACCEPTANCE_CEILING:
        return None
    return (entropy % 20) + 1


class LocalCSPRNGDiceProvider:
    """Local CSPRNG provider using Python's secrets module."""

    source = "local_csprng"

    def next_u32(self) -> int:
        return secrets.randbits(32)


class SeededDiceProvider:
    """Deterministic provider for tests and repeatable demos."""

    source = "seeded_deterministic"

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def next_u32(self) -> int:
        return self._rng.getrandbits(32)


class FixedEntropyDiceProvider:
    """Deterministic provider cycling through fixed entropy values."""

    source = "fixed_entropy"

    def __init__(self, values: tuple[int, ...]) -> None:
        if not values:
            raise ValueError("FixedEntropyDiceProvider requires at least one value")
        for value in values:
            if value < 0 or value > U32_MAX:
                raise ValueError("fixed entropy values must be within u32 range")
        self._values = values
        self._index = 0

    def next_u32(self) -> int:
        value = self._values[self._index % len(self._values)]
        self._index += 1
        return value


def roll_d20_record(provider: DiceProvider) -> DiceRollRecord:
    """Roll a d20 using provider entropy and record deterministic metadata."""
    attempts = 0
    first_entropy: int | None = None
    while True:
        entropy = provider.next_u32()
        attempts += 1
        if first_entropy is None:
            first_entropy = entropy
        result = roll_d20(entropy)
        if result is None:
            continue
        record = DiceRollRecord(
            sides=20,
            entropy=first_entropy,
            accepted_entropy=entropy,
            value=result,
            attempts=attempts,
            provider=provider.source,
        )
        return record


@dataclass(frozen=True)
class DamageRollResult:
    """Result of rolling a damage formula deterministically."""

    damage_rolls: list[int]
    damage_modifier_total: int
    damage_total: int


def roll_dn(sides: int, entropy: int) -> int | None:
    """Map one u32 entropy sample to dn with rejection sampling."""
    if sides < 2:
        raise ValueError("sides must be >= 2")
    if entropy < 0 or entropy > U32_MAX:
        raise ValueError("entropy must be within [0, 2**32 - 1]")
    acceptance_ceiling = (2**32 // sides) * sides
    if entropy >= acceptance_ceiling:
        return None
    return (entropy % sides) + 1


def roll_dn_record(provider: DiceProvider, sides: int) -> DiceRollRecord:
    """Roll a dn using provider entropy and record deterministic metadata."""
    attempts = 0
    first_entropy: int | None = None
    while True:
        entropy = provider.next_u32()
        attempts += 1
        if first_entropy is None:
            first_entropy = entropy
        result = roll_dn(sides, entropy)
        if result is None:
            continue
        return DiceRollRecord(
            sides=sides,
            entropy=first_entropy,
            accepted_entropy=entropy,
            value=result,
            attempts=attempts,
            provider=provider.source,
        )


_DICE_SPEC_RE = re.compile(r"(\d+)d(\d+)", re.IGNORECASE)
_MODIFIER_RE = re.compile(r"[+-]\s*\d+")


def roll_damage_formula(formula: str, provider: DiceProvider) -> DamageRollResult:
    """Parse and roll a damage formula like '1d8 +3 +1' deterministically."""
    damage_rolls: list[int] = []
    modifier_total: int = 0

    for match in _DICE_SPEC_RE.finditer(formula):
        count = int(match.group(1))
        sides = int(match.group(2))
        for _ in range(count):
            record = roll_dn_record(provider, sides)
            damage_rolls.append(record.value)

    remaining = _DICE_SPEC_RE.sub("", formula)
    for mod_str in _MODIFIER_RE.findall(remaining):
        modifier_total += int(mod_str.replace(" ", ""))

    damage_total = sum(damage_rolls) + modifier_total
    return DamageRollResult(
        damage_rolls=damage_rolls,
        damage_modifier_total=modifier_total,
        damage_total=damage_total,
    )


def roll_d20_record_from_entropy(entropy: int, provider: str) -> DiceRollRecord:
    """Build a deterministic d20 record from a preselected entropy value."""
    result = roll_d20(entropy)
    if result is None:
        raise ValueError("prefetched entropy must map directly to d20")
    return DiceRollRecord(
        sides=20,
        entropy=entropy,
        accepted_entropy=entropy,
        value=result,
        attempts=1,
        provider=provider,
    )
