# Chronicle Weaver – Project Glossary

This glossary defines the canonical terms used throughout the Chronicle Weaver engine.

It exists to ensure that developers and AI coding agents consistently use the same vocabulary when working on the project.

Related documentation:

- docs/ARCHITECTURE_OVERVIEW.md
- docs/ENGINE_PIPELINE.md
- docs/CLAUDE_ROADMAP.md
- AGENTS.md

---

# Core Concepts

## Engine

The **engine** is the deterministic system responsible for resolving all gameplay mechanics.

The engine is authoritative for:

- combat resolution
- dice rolls
- damage
- healing
- resource consumption
- turn order
- encounter state
- event generation

The engine does not generate narrative text.

---

## Narrator

The **narrator** is the AI model responsible for describing events in natural language.

The narrator:

- receives structured context
- receives resolved action data
- generates prose describing what occurred

The narrator must never modify game mechanics.

Narration is descriptive only.

---

## Deterministic System

Chronicle Weaver is designed as a **deterministic engine**.

This means:

- the same inputs produce the same outputs
- randomness comes only from controlled dice sources
- external randomness sources are not allowed

Examples of prohibited sources:

- random.random()
- system time based randomness
- LLM-generated dice results

---

# Gameplay Structures

## Actor

An **actor** represents a character sheet.

Actors may represent:

- player characters
- important NPCs
- custom creatures

Actors contain:

- ability scores
- proficiency bonus
- equipment
- known spells
- class features
- resource pools
- maximum hit points

Actors are the authored source data used to construct combat participants.

---

## Combatant

A **combatant** is the runtime representation of a participant in combat.

Combatants may originate from:

- actors
- monsters
- NPC templates
- summoned creatures

Combatants contain only the data needed for combat resolution.

Typical fields include:

- combatant_id
- display_name
- armor_class
- hit_points
- abilities
- resources
- proficiency_bonus
- metadata

The combat engine operates on combatants, not actors.

---

## Encounter

An **encounter** represents an active combat scene.

Encounter state may include:

- encounter_id
- list of combatants
- initiative order
- current round
- current turn
- encounter status

Encounters control turn order and action progression.

---

## Turn Economy

The **turn economy** represents the action limits available during a combat turn.

Typical categories include:

- action
- bonus action
- reaction
- movement
- object interaction
- speech

Actions consume these resources.

The engine validates action availability before resolution.

---

# Rules Content

## Compendium

The **compendium** is the structured rule database used by the engine.

Compendium entries define:

- weapons
- spells
- items
- features
- monsters

Compendium entries provide structured mechanical data.

They do not contain narrative descriptions.

---

## Compendium Entry

A **compendium entry** represents a single rules element.

Examples:

- weapon_longsword
- spell_magic_missile
- feature_second_wind
- monster_goblin

Entries include fields describing mechanics such as:

- attack bonus modifiers
- damage formulas
- spell behavior
- resource usage
- action costs

---

## Resolver

A **resolver** is the deterministic logic responsible for turning an interpreted action into a mechanical result.

Examples:

- weapon attack resolver
- spell casting resolver
- feature usage resolver

Resolvers produce structured outputs such as:

- attack totals
- hit or miss results
- damage values
- resource consumption

---

# Game Mechanics

## Attack Roll

An **attack roll** is a deterministic dice roll used to determine whether an attack hits a target.

Typical formula:

d20 + ability modifier + proficiency + bonuses

If the result equals or exceeds the target's armor class, the attack hits.

---

## Damage Roll

A **damage roll** determines how much damage is applied after a successful hit.

Damage formulas may look like:

- 1d8 + 3
- 2d6 + 4
- 3d4 + 3

Damage is resolved deterministically using the engine's dice system.

---

## Hit Points (HP)

**Hit Points** represent a combatant's current health.

Damage reduces hit points.

Healing increases hit points.

If hit points reach zero, the combatant may be defeated or enter a special state depending on future rules.

---

# Data and Memory

## Event

An **event** represents a structured record of a gameplay change.

Examples include:

- intent_resolved
- action_resolved
- attack_resolved
- damage_applied
- healing_applied
- combatant_defeated

Events provide an auditable history of game activity.

---

## Event Log

The **event log** is the chronological record of all emitted events during gameplay.

Event logs enable:

- debugging
- replay
- campaign persistence
- narrative grounding

---

## Context Bundle

A **context bundle** is the structured information sent to the narrator to generate narration.

It may include:

- resolved action results
- encounter status
- involved entities
- recent events
- relevant lore

The context bundle is deterministic.

---

## Lorebook

The **lorebook** stores long-term world knowledge discovered during gameplay.

Examples include:

- characters
- locations
- relationships
- discovered facts

The lorebook may grow during campaigns as events are processed.

---

## Graph Memory

**Graph memory** represents relationships between entities.

Examples:

- player attacked goblin
- goblin belongs to tribe
- NPC knows another NPC

Graph memory enables structured world knowledge.

---

# AI Integration

## Interpreter

The **interpreter** converts freeform player input into structured intent.

Example input:

"I swing my longsword at the goblin"

Example interpreted output:

intent = attack  
target = goblin  
entry_id = w.longsword

The interpreter does not resolve mechanics.

---

## Narration Context

Narration context is the filtered subset of game state used for AI narration.

It is intentionally limited to avoid exposing internal system metadata.

---

# Design Philosophy

Chronicle Weaver follows these core principles:

- deterministic mechanics
- event-driven state
- compendium-driven rules
- separation of mechanics and narration
- reproducible gameplay

The engine decides what happens.

The narrator describes what happened.

