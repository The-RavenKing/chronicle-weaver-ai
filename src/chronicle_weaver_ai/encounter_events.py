"""Structured event emission for encounter turns.

This module bridges the deterministic encounter execution path (encounter.py,
monster_turn.py, cli.py spawn loop) with the engine's Event type so that
encounter outcomes can be stored in an event log, fed to the scribe, and
replayed for narration.

Design
------
- All events use the standard ``Event`` dataclass so they are compatible
  with ``InMemoryEventStore``, the scribe, and ``snapshot.py``.
- Callers pass an ``events_out`` list; helpers append to it.
- No engine state mutation happens here — this is pure event construction.

Event types emitted
-------------------
encounter_started    — encounter_id, combatant names, initiative order
turn_started         — encounter_id, round, combatant_id, combatant_name
attack_resolved      — encounter_id, attacker/target ids+names, roll, hit, damage
hp_changed           — encounter_id, combatant_id, old_hp, new_hp
combatant_defeated   — encounter_id, combatant_id, combatant_name
encounter_ended      — encounter_id, outcome (victory/defeat/draw), winner_ids
"""

from __future__ import annotations

from chronicle_weaver_ai.models import Event, JSONValue


def emit_encounter_started(
    encounter_id: str,
    combatant_names: list[str],
    initiative_order: list[str],
    ts: int = 0,
) -> Event:
    return Event(
        event_type="encounter_started",
        payload={
            "encounter_id": encounter_id,
            "combatant_names": combatant_names,
            "initiative_order": initiative_order,
        },
        timestamp=ts,
    )


def emit_turn_started(
    encounter_id: str,
    round_number: int,
    combatant_id: str,
    combatant_name: str,
    ts: int = 0,
) -> Event:
    return Event(
        event_type="turn_started",
        payload={
            "encounter_id": encounter_id,
            "round": round_number,
            "combatant_id": combatant_id,
            "combatant_name": combatant_name,
        },
        timestamp=ts,
    )


def emit_attack_resolved(
    encounter_id: str,
    attacker_id: str,
    attacker_name: str,
    target_id: str,
    target_name: str,
    attack_roll: int,
    attack_bonus: int,
    attack_total: int,
    target_ac: int | None,
    hit: bool,
    damage_total: int,
    weapon_name: str = "",
    ts: int = 0,
) -> Event:
    payload: dict[str, JSONValue] = {
        "encounter_id": encounter_id,
        "attacker_id": attacker_id,
        "attacker_name": attacker_name,
        "target_id": target_id,
        "target_name": target_name,
        "attack_roll": attack_roll,
        "attack_bonus": attack_bonus,
        "attack_total": attack_total,
        "target_ac": target_ac,
        "hit": hit,
        "damage_total": damage_total,
    }
    if weapon_name:
        payload["weapon_name"] = weapon_name
    return Event(event_type="attack_resolved", payload=payload, timestamp=ts)


def emit_hp_changed(
    encounter_id: str,
    combatant_id: str,
    combatant_name: str,
    old_hp: int | None,
    new_hp: int | None,
    ts: int = 0,
) -> Event:
    return Event(
        event_type="hp_changed",
        payload={
            "encounter_id": encounter_id,
            "combatant_id": combatant_id,
            "combatant_name": combatant_name,
            "old_hp": old_hp,
            "new_hp": new_hp,
        },
        timestamp=ts,
    )


def emit_combatant_defeated(
    encounter_id: str,
    combatant_id: str,
    combatant_name: str,
    ts: int = 0,
) -> Event:
    return Event(
        event_type="combatant_defeated",
        payload={
            "encounter_id": encounter_id,
            "combatant_id": combatant_id,
            "combatant_name": combatant_name,
        },
        timestamp=ts,
    )


def emit_encounter_ended(
    encounter_id: str,
    outcome: str,
    winner_ids: list[str],
    loser_ids: list[str],
    rounds_elapsed: int,
    ts: int = 0,
) -> Event:
    """outcome: 'victory' | 'defeat' | 'draw'."""
    return Event(
        event_type="encounter_ended",
        payload={
            "encounter_id": encounter_id,
            "outcome": outcome,
            "winner_ids": winner_ids,
            "loser_ids": loser_ids,
            "rounds_elapsed": rounds_elapsed,
        },
        timestamp=ts,
    )
