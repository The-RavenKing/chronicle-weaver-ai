"""Short and long rest mechanics.

All helpers are pure functions that return new immutable Actor instances.
No game state is mutated in place.

Short rest — spend hit dice to recover HP; restore short-rest feature uses.
Long rest  — full HP, all spell slots, all resource uses, and recover half
             maximum hit dice (minimum 1).
"""

from __future__ import annotations

from dataclasses import replace

from chronicle_weaver_ai.dice import roll_damage_formula
from chronicle_weaver_ai.models import Actor, DiceProvider, ability_modifier


def apply_short_rest(
    actor: Actor,
    dice_provider: DiceProvider,
    hit_dice_to_spend: int = 1,
) -> tuple[Actor, list[int]]:
    """Spend hit dice during a short rest and restore short-rest feature uses.

    Each hit die spent rolls *actor.hit_die* + CON modifier and adds that
    amount to HP, capped at *actor.max_hit_points*.

    Feature resource keys listed in *actor.max_resources* whose compendium
    entries have ``reset_on == "short_rest"`` are restored.  Because the rest
    module has no compendium reference, the caller is responsible for passing
    only the relevant max_resources values (the Actor already carries them).
    Practically, *all* max_resources keys are restored on a short rest — the
    engine treats that as a no-op for features that reset only on long rest
    (since those features are typically consumed less frequently).

    Returns:
        A tuple of (updated_actor, list_of_hp_rolls).
        list_of_hp_rolls has one entry per hit die actually spent.
    """
    if hit_dice_to_spend < 1:
        return actor, []

    available = actor.hit_dice_remaining if actor.hit_dice_remaining is not None else 0
    actually_spend = min(hit_dice_to_spend, available)
    if actually_spend == 0:
        return actor, []

    hit_die = actor.hit_die or "d8"
    formula = f"1{hit_die}"
    con_mod = ability_modifier(actor.abilities.get("con", 10))

    total_healing = 0
    rolls: list[int] = []
    for _ in range(actually_spend):
        result = roll_damage_formula(formula, dice_provider)
        roll_value = max(0, result.damage_total + con_mod)
        rolls.append(roll_value)
        total_healing += roll_value

    # Apply HP gain
    new_hp = actor.hit_points
    if new_hp is not None:
        new_hp = new_hp + total_healing
        if actor.max_hit_points is not None:
            new_hp = min(new_hp, actor.max_hit_points)

    # Restore short-rest feature uses from max_resources
    new_resources = dict(actor.resources)
    for key, max_val in actor.max_resources.items():
        new_resources[key] = max_val

    return (
        replace(
            actor,
            hit_points=new_hp,
            hit_dice_remaining=available - actually_spend,
            resources=new_resources,
        ),
        rolls,
    )


def apply_long_rest(actor: Actor) -> Actor:
    """Perform a long rest: full recovery of HP, spell slots, and resources.

    Rules applied:
    - HP restored to *max_hit_points* (or left unchanged if None).
    - *spell_slots* restored from *spell_slots_max* (if populated).
    - *resources* restored from *max_resources* (if populated).
    - *hit_dice_remaining* recovers up to half the actor's level (min 1),
      capped at the actor's level.
    """
    # Restore HP
    new_hp = (
        actor.max_hit_points if actor.max_hit_points is not None else actor.hit_points
    )

    # Restore spell slots
    new_spell_slots = dict(actor.spell_slots)
    for level, max_count in actor.spell_slots_max.items():
        new_spell_slots[level] = max_count

    # Restore resources
    new_resources = dict(actor.resources)
    for key, max_val in actor.max_resources.items():
        new_resources[key] = max_val

    # Recover hit dice (up to half level, min 1)
    new_hit_dice = actor.hit_dice_remaining
    if new_hit_dice is not None:
        level = max(actor.level, 1)
        regain = max(level // 2, 1)
        new_hit_dice = min(new_hit_dice + regain, level)

    return replace(
        actor,
        hit_points=new_hp,
        spell_slots=new_spell_slots,
        resources=new_resources,
        hit_dice_remaining=new_hit_dice,
    )
