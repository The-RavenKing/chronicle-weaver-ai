"""Condition helpers: add, remove, tick durations, and render on CombatantSnapshot."""

from __future__ import annotations

import dataclasses

from chronicle_weaver_ai.rules.combatant import Condition, CombatantSnapshot


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
