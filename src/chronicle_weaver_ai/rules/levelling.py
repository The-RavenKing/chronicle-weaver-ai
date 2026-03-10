"""XP awards and level-up logic (D&D 5e milestone-adjacent model).

XP thresholds are the standard D&D 5e total cumulative XP requirements.
Proficiency bonus follows the standard 5e table.
HP gain on level-up uses: average hit-die roll + CON modifier (per D&D 5e recommended).

Usage
-----
from chronicle_weaver_ai.rules.levelling import apply_xp_award, xp_for_level

actor, levelled_up = apply_xp_award(actor, xp_gained=100)
"""

from __future__ import annotations

from dataclasses import replace

from chronicle_weaver_ai.models import Actor, ability_modifier

# D&D 5e cumulative XP thresholds (level N requires this total XP to reach it)
_XP_THRESHOLDS: dict[int, int] = {
    1: 0,
    2: 300,
    3: 900,
    4: 2700,
    5: 6500,
    6: 14000,
    7: 23000,
    8: 34000,
    9: 48000,
    10: 64000,
    11: 85000,
    12: 100000,
    13: 120000,
    14: 140000,
    15: 165000,
    16: 195000,
    17: 225000,
    18: 265000,
    19: 305000,
    20: 355000,
}

# D&D 5e standard proficiency bonus by level
_PROFICIENCY_BY_LEVEL: dict[int, int] = {
    1: 2,
    2: 2,
    3: 2,
    4: 2,
    5: 3,
    6: 3,
    7: 3,
    8: 3,
    9: 4,
    10: 4,
    11: 4,
    12: 4,
    13: 5,
    14: 5,
    15: 5,
    16: 5,
    17: 6,
    18: 6,
    19: 6,
    20: 6,
}

# Average hit-die roll by die type (d6=4, d8=5, d10=6, d12=7)
_HIT_DIE_AVERAGE: dict[str, int] = {
    "d4": 3,
    "d6": 4,
    "d8": 5,
    "d10": 6,
    "d12": 7,
}

# Standard CR → XP reward lookup (D&D 5e Monster Manual)
CR_XP_TABLE: dict[str, int] = {
    "0": 10,
    "1/8": 25,
    "1/4": 50,
    "1/2": 100,
    "1": 200,
    "2": 450,
    "3": 700,
    "4": 1100,
    "5": 1800,
    "6": 2300,
    "7": 2900,
    "8": 3900,
    "9": 5000,
    "10": 5900,
    "11": 7200,
    "12": 8400,
    "13": 10000,
    "14": 11500,
    "15": 13000,
    "16": 15000,
    "17": 18000,
    "18": 20000,
    "19": 22000,
    "20": 25000,
}


def xp_for_level(level: int) -> int:
    """Return the cumulative XP required to reach *level*."""
    return _XP_THRESHOLDS.get(max(1, min(level, 20)), 355000)


def level_for_xp(xp: int) -> int:
    """Return the character level corresponding to *xp* total XP earned."""
    current = 1
    for lvl in range(1, 21):
        if xp >= _XP_THRESHOLDS.get(lvl, 0):
            current = lvl
        else:
            break
    return current


def xp_reward_for_cr(cr: str | None) -> int:
    """Return the XP reward for a monster with the given challenge rating string."""
    if cr is None:
        return 0
    # Handle decimal CR representations like "0.25" → "1/4"
    cr_norm = cr.strip()
    if cr_norm in CR_XP_TABLE:
        return CR_XP_TABLE[cr_norm]
    try:
        val = float(cr_norm)
        if val <= 0:
            return CR_XP_TABLE["0"]
        if val < 0.2:
            return CR_XP_TABLE["1/8"]
        if val < 0.4:
            return CR_XP_TABLE["1/4"]
        if val < 0.9:
            return CR_XP_TABLE["1/2"]
        return CR_XP_TABLE.get(str(int(round(val))), 0)
    except (ValueError, TypeError):
        return 0


def apply_xp_award(actor: Actor, xp_gained: int) -> tuple[Actor, bool]:
    """Award *xp_gained* XP to *actor* and apply level-up if the threshold is crossed.

    Returns
    -------
    (updated_actor, levelled_up)
        levelled_up is True when the actor gained one or more levels.
    """
    if xp_gained <= 0:
        return actor, False

    new_xp = actor.xp + xp_gained
    old_level = actor.level
    new_level = level_for_xp(new_xp)

    if new_level <= old_level:
        return replace(actor, xp=new_xp), False

    # Apply level-up changes
    updated = _apply_level_up(
        actor, old_level=old_level, new_level=new_level, new_xp=new_xp
    )
    return updated, True


def _apply_level_up(actor: Actor, old_level: int, new_level: int, new_xp: int) -> Actor:
    """Apply all mechanical changes from levelling up old_level → new_level."""
    levels_gained = new_level - old_level
    new_proficiency = _PROFICIENCY_BY_LEVEL.get(new_level, 2)

    # HP gain: average hit die + CON mod per level gained
    con_mod = ability_modifier(actor.abilities.get("con", 10))
    hit_die = actor.hit_die or "d8"
    avg_hp_per_level = _HIT_DIE_AVERAGE.get(hit_die, 5)
    hp_gain = max(1, avg_hp_per_level + con_mod) * levels_gained

    new_max_hp = (actor.max_hit_points or 0) + hp_gain
    new_hp = (actor.hit_points or 0) + hp_gain  # current HP increases too

    # Hit dice: gain one die per level
    new_hit_dice = (actor.hit_dice_remaining or old_level) + levels_gained

    return replace(
        actor,
        level=new_level,
        xp=new_xp,
        proficiency_bonus=new_proficiency,
        max_hit_points=new_max_hp,
        hit_points=new_hp,
        hit_dice_remaining=new_hit_dice,
    )


__all__ = [
    "apply_xp_award",
    "xp_for_level",
    "level_for_xp",
    "xp_reward_for_cr",
    "CR_XP_TABLE",
]
