"""Deterministic initiative rolling, encounter turn order, and encounter state."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from chronicle_weaver_ai.dice import roll_d20_record
from chronicle_weaver_ai.models import (
    DiceProvider,
    TurnBudget,
    ability_modifier,
    new_turn_budget,
)
from chronicle_weaver_ai.rules.combatant import CombatantSnapshot


@dataclass(frozen=True)
class InitiativeRoll:
    """Recorded initiative result for one combatant."""

    combatant_id: str
    d20_value: int
    dex_modifier: int
    total: int


@dataclass(frozen=True)
class EncounterTurnOrder:
    """Immutable snapshot of initiative order and current turn state.

    combatant_ids is sorted high-initiative-first (the canonical play order).
    current_turn_index is an index into combatant_ids.
    current_round is 1-based.
    current_turn_budget tracks action economy for the active combatant's turn.
    """

    encounter_id: str
    combatant_ids: list[str]
    current_turn_index: int
    current_round: int
    initiative_rolls: dict[str, InitiativeRoll]
    current_turn_budget: TurnBudget = field(default_factory=new_turn_budget)


def roll_initiative(
    combatant_id: str,
    dex_score: int,
    provider: DiceProvider,
) -> InitiativeRoll:
    """Roll d20 + DEX modifier for one combatant."""
    record = roll_d20_record(provider)
    dex_mod = ability_modifier(dex_score)
    return InitiativeRoll(
        combatant_id=combatant_id,
        d20_value=record.value,
        dex_modifier=dex_mod,
        total=record.value + dex_mod,
    )


def start_encounter(
    encounter_id: str,
    combatants: list[CombatantSnapshot],
    provider: DiceProvider,
) -> EncounterTurnOrder:
    """Roll initiative for all combatants and return sorted turn order.

    Sorting priority (all deterministic):
      1. initiative total descending
      2. DEX modifier descending
      3. combatant_id ascending (alphabetical tie-break)
    """
    rolls: dict[str, InitiativeRoll] = {}
    for combatant in combatants:
        dex_score = combatant.abilities.get("dex", 10)
        rolls[combatant.combatant_id] = roll_initiative(
            combatant.combatant_id, dex_score, provider
        )

    ordered_ids = sorted(
        rolls.keys(),
        key=lambda cid: (-rolls[cid].total, -rolls[cid].dex_modifier, cid),
    )

    return EncounterTurnOrder(
        encounter_id=encounter_id,
        combatant_ids=ordered_ids,
        current_turn_index=0,
        current_round=1,
        initiative_rolls=rolls,
        current_turn_budget=new_turn_budget(),
    )


def current_combatant(order: EncounterTurnOrder) -> str:
    """Return the combatant_id whose turn it currently is."""
    return order.combatant_ids[order.current_turn_index]


def advance_turn(order: EncounterTurnOrder) -> EncounterTurnOrder:
    """Advance to the next combatant's turn, resetting the turn budget.

    When the last combatant in the round finishes, current_turn_index wraps to 0
    and current_round increments by 1.
    """
    next_index = order.current_turn_index + 1
    if next_index >= len(order.combatant_ids):
        next_index = 0
        next_round = order.current_round + 1
    else:
        next_round = order.current_round

    return dataclasses.replace(
        order,
        current_turn_index=next_index,
        current_round=next_round,
        current_turn_budget=new_turn_budget(),
    )


# ── Encounter state ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EncounterState:
    """Full live state of an encounter: combatants, initiative order, and status.

    combatants maps combatant_id → CombatantSnapshot (current HP / stats).
    turn_order owns the initiative list, current_turn_index, current_round, and
    the active combatant's turn budget.
    defeated_ids tracks combatants eliminated this encounter (hp reached 0).
    active is False once the encounter has ended.
    """

    encounter_id: str
    combatants: dict[str, CombatantSnapshot]
    turn_order: EncounterTurnOrder
    active: bool = True
    defeated_ids: frozenset[str] = field(default_factory=frozenset)


def create_encounter(
    encounter_id: str,
    combatants: list[CombatantSnapshot],
    provider: DiceProvider,
) -> EncounterState:
    """Build a fresh EncounterState by rolling initiative for all combatants."""
    turn_order = start_encounter(encounter_id, combatants, provider)
    return EncounterState(
        encounter_id=encounter_id,
        combatants={c.combatant_id: c for c in combatants},
        turn_order=turn_order,
        active=True,
        defeated_ids=frozenset(),
    )


def get_combatant(encounter: EncounterState, combatant_id: str) -> CombatantSnapshot:
    """Return the current snapshot for combatant_id; raise KeyError if absent."""
    try:
        return encounter.combatants[combatant_id]
    except KeyError:
        raise KeyError(
            f"combatant '{combatant_id}' not found in encounter '{encounter.encounter_id}'"
        )


def update_combatant(
    encounter: EncounterState, snapshot: CombatantSnapshot
) -> EncounterState:
    """Return a new EncounterState with snapshot replacing the existing entry."""
    new_combatants = dict(encounter.combatants)
    new_combatants[snapshot.combatant_id] = snapshot
    return dataclasses.replace(encounter, combatants=new_combatants)


def mark_defeated(encounter: EncounterState, combatant_id: str) -> EncounterState:
    """Return a new EncounterState with combatant_id added to defeated_ids."""
    return dataclasses.replace(
        encounter,
        defeated_ids=encounter.defeated_ids | {combatant_id},
    )


def remove_from_order(encounter: EncounterState, combatant_id: str) -> EncounterState:
    """Return encounter with combatant_id removed from the initiative order.

    Adjusts current_turn_index to maintain the same relative position:
      - If the removed combatant is before current_turn_index, decrement index.
      - If the removed combatant IS the current one, clamp index to new list end.
      - If the removed combatant is after, leave index unchanged.
    """
    order = encounter.turn_order
    if combatant_id not in order.combatant_ids:
        return encounter

    removed_index = order.combatant_ids.index(combatant_id)
    new_ids = [cid for cid in order.combatant_ids if cid != combatant_id]

    if not new_ids:
        new_turn_index = 0
    elif removed_index < order.current_turn_index:
        new_turn_index = order.current_turn_index - 1
    elif removed_index == order.current_turn_index:
        new_turn_index = min(order.current_turn_index, len(new_ids) - 1)
    else:
        new_turn_index = order.current_turn_index

    new_order = dataclasses.replace(
        order, combatant_ids=new_ids, current_turn_index=new_turn_index
    )
    return dataclasses.replace(encounter, turn_order=new_order)


def end_turn(encounter: EncounterState) -> EncounterState:
    """End the current combatant's turn and advance to the next non-defeated combatant.

    Skips any combatants in defeated_ids.  When the search wraps past the last
    combatant in the list, current_round increments by 1 and the turn budget resets.
    Returns the encounter unchanged if every combatant is defeated.
    """
    order = encounter.turn_order
    n = len(order.combatant_ids)
    if n == 0:
        return encounter

    for offset in range(1, n + 1):
        raw_index = order.current_turn_index + offset
        candidate_index = raw_index % n
        candidate_id = order.combatant_ids[candidate_index]
        if candidate_id not in encounter.defeated_ids:
            wrapped = raw_index >= n
            next_round = order.current_round + (1 if wrapped else 0)
            new_order = dataclasses.replace(
                order,
                current_turn_index=candidate_index,
                current_round=next_round,
                current_turn_budget=new_turn_budget(),
            )
            return dataclasses.replace(encounter, turn_order=new_order)

    # All combatants are defeated — return unchanged.
    return encounter


def is_encounter_over(encounter: EncounterState) -> bool:
    """Return True if all combatants on one side (actors or monsters) are defeated.

    Encounter ends the moment the last member of either side reaches 0 HP.
    Returns False if either side has at least one non-defeated combatant.
    """
    actor_ids = [
        cid for cid, snap in encounter.combatants.items() if snap.source_type == "actor"
    ]
    monster_ids = [
        cid
        for cid, snap in encounter.combatants.items()
        if snap.source_type == "monster"
    ]

    if actor_ids and all(cid in encounter.defeated_ids for cid in actor_ids):
        return True
    if monster_ids and all(cid in encounter.defeated_ids for cid in monster_ids):
        return True
    return False
