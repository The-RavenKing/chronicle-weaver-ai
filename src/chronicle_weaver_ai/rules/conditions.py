"""Condition helpers: add, remove, tick durations, render, and mechanic queries."""

from __future__ import annotations

import dataclasses
from typing import Literal

from chronicle_weaver_ai.rules.combatant import Condition, CombatantSnapshot

RollMode = Literal["normal", "disadvantage"]

# Conditions that prevent the combatant from taking any action/bonus/reaction.
_BLOCKING_CONDITIONS: frozenset[str] = frozenset({"stunned"})

# Conditions that impose disadvantage on the combatant's own attack rolls.
_DISADVANTAGE_CONDITIONS: frozenset[str] = frozenset({"poisoned", "prone"})


def add_condition(
    snapshot: CombatantSnapshot, condition: Condition
) -> CombatantSnapshot:
    """Return a new snapshot with condition added.

    If a condition with the same condition_name is already present it is replaced,
    so a combatant cannot carry duplicates of the same named condition.
    """
    pruned = tuple(
        c for c in snapshot.conditions if c.condition_name != condition.condition_name
    )
    return dataclasses.replace(snapshot, conditions=pruned + (condition,))


def remove_condition(
    snapshot: CombatantSnapshot, condition_name: str
) -> CombatantSnapshot:
    """Return a new snapshot with all conditions matching condition_name removed."""
    remaining = tuple(
        c for c in snapshot.conditions if c.condition_name != condition_name
    )
    return dataclasses.replace(snapshot, conditions=remaining)


def tick_condition_durations(snapshot: CombatantSnapshot) -> CombatantSnapshot:
    """Advance one tick for all conditions on the snapshot.

    Rules per duration_type:
      "until_end_of_turn" — expired; removed.
      "rounds"            — remaining_rounds decremented by 1; removed when it reaches 0.
      "instant"           — already resolved; left unchanged.
      "persistent"        — never expires by ticking; left unchanged.
    """
    updated: list[Condition] = []
    for condition in snapshot.conditions:
        if condition.duration_type == "until_end_of_turn":
            continue  # expired — drop it
        if condition.duration_type == "rounds":
            remaining = (condition.remaining_rounds or 0) - 1
            if remaining <= 0:
                continue  # expired — drop it
            updated.append(dataclasses.replace(condition, remaining_rounds=remaining))
        else:
            # "instant" and "persistent" are not modified by ticking
            updated.append(condition)
    return dataclasses.replace(snapshot, conditions=tuple(updated))


def is_blocked_by_conditions(snapshot: CombatantSnapshot) -> str | None:
    """Return a rejection reason string if any condition blocks all actions, else None.

    A combatant is blocked when it carries a condition in _BLOCKING_CONDITIONS
    (currently only 'stunned').  The returned string is suitable for display as
    a resolution rejection reason.
    """
    for condition in snapshot.conditions:
        if condition.condition_name in _BLOCKING_CONDITIONS:
            return f"combatant is {condition.condition_name} and cannot act"
    return None


def attack_roll_mode(snapshot: CombatantSnapshot) -> RollMode:
    """Return the roll mode that applies to this combatant's own attack rolls.

    Returns 'disadvantage' if the combatant has any condition in
    _DISADVANTAGE_CONDITIONS (poisoned or prone), otherwise 'normal'.
    Only one roll mode is returned; if multiple disadvantage sources are
    present the result is still 'disadvantage' (no stacking).
    """
    active_names = {c.condition_name for c in snapshot.conditions}
    if active_names & _DISADVANTAGE_CONDITIONS:
        return "disadvantage"
    return "normal"


def render_condition(condition: Condition) -> str:
    """Return a human-readable string for one condition suitable for narrator prompts.

    Examples:
      "prone (2 rounds remaining)"
      "poisoned (persistent)"
      "stunned (until end of turn)"
      "blinded (instant)"
    """
    name = condition.condition_name
    if condition.duration_type == "persistent":
        return f"{name} (persistent)"
    if condition.duration_type == "until_end_of_turn":
        return f"{name} (until end of turn)"
    if condition.duration_type == "rounds" and condition.remaining_rounds is not None:
        r = condition.remaining_rounds
        return f"{name} ({r} round{'s' if r != 1 else ''} remaining)"
    return name
