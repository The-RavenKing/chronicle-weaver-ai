# Chronicle Weaver – Engine Pipeline

This document describes the authoritative runtime pipeline for Chronicle Weaver.

It exists to help human developers and AI coding agents understand:

- how player input becomes game state
- where deterministic mechanics happen
- where narration is allowed
- how compendium, actors, combatants, encounters, and persistence fit together

This file should be read together with:

- `AGENTS.md`
- `docs/ARCHITECTURE_OVERVIEW.md`
- `docs/CLAUDE_ROADMAP.md`

---

# Core Rule

**Narration is never authoritative.**  
Only the deterministic engine decides mechanics and state.

The pipeline is always:

Player Input  
→ Intent Interpretation  
→ Compendium Match  
→ Actor / Combatant Resolution  
→ Resource Validation  
→ Turn Economy Validation  
→ Action Resolution  
→ Hit / Miss / Damage / Healing  
→ Encounter State Update  
→ Event Emission  
→ Context Construction  
→ Narration  

---

# High-Level Flow

## 1. Player Input

The user provides freeform text such as:

- "I swing my longsword at the goblin"
- "I cast magic missile at the goblin"
- "I use second wind"
- "I shout to Mira to get back"

This input is not mechanically authoritative. It is interpreted into structured intent first.

---

## 2. Intent Interpretation

The interpreter converts freeform text into structured data.

Typical output includes:

- intent
- target
- confidence
- provider_used
- optional compendium reference fields:
  - entry_id
  - entry_kind
  - entry_name

Examples:

- attack
- cast_spell
- use_feature
- use_item
- talk
- search
- disengage

Rules-first interpretation is preferred. LLM fallback may assist interpretation, but only for classification and extraction, never for mechanics.

---

## 3. Compendium Match

If the input references a weapon, spell, item, feature, or monster, the system attempts to match it against compendium entries.

Examples:

- "longsword" or "long sword" → `w.longsword`
- "magic missile" → `s.magic_missile`
- "second wind" → `f.second_wind`

The compendium is the source of truth for structured gameplay content.

Compendium entries may include:

- weapons
- spells
- items
- features
- monsters

These entries define mechanics data, not narration.

---

## 4. Actor Resolution

If the acting entity is a player character or named actor, the system loads actor data.

Actor data may include:

- ability scores
- proficiency bonus
- equipped weapons
- known spells
- feature IDs
- item IDs
- HP
- AC
- spell slots
- resource pools

Actors do not directly resolve actions; they provide the data needed by the resolver.

---

## 5. Combatant Resolution

Actors and monsters are converted into a common combat-facing structure.

Combat uses a shared combatant abstraction so the engine does not special-case:

- player characters
- monsters
- NPC allies
- summons

A combatant snapshot typically includes:

- combatant_id
- display_name
- source_type
- source_id
- armor_class
- hit_points
- abilities
- resources
- proficiency_bonus
- compendium_refs
- metadata

All combat resolution should work through combatants.

---

## 6. Resource Validation

Before an action resolves, the system checks whether it is legal.

Examples:

- is the spell known?
- is there an available spell slot?
- does the feature have remaining uses?
- is the required weapon equipped?
- does the actor have the required item?

If validation fails, the action is rejected deterministically.

Rejected actions should not produce success narration.

---

## 7. Turn Economy Validation

Combat actions must fit into turn economy.

The turn budget may include:

- action
- bonus action
- reaction
- movement
- object interaction
- speech

Examples:

- weapon attack → usually consumes action
- second wind → bonus action
- opportunity attack → reaction
- brief speech → speech slot
- draw or manipulate object → object interaction

Validation occurs before mechanics resolve.

---

## 8. Action Resolution

The resolver transforms an interpreted action plus actor/combatant/compendium data into structured mechanical output.

Examples:

### Weapon attack resolution
May produce:

- action_kind = attack
- entry_id / entry_name
- attack_ability_used
- attack_bonus_total
- attack_roll_d20
- attack_total
- target_armor_class
- hit_result
- damage_formula
- damage_rolls
- damage_modifier_total
- damage_total

### Spell resolution
May produce:

- action_kind = cast_spell
- entry_id / entry_name
- action_cost
- spell slot used
- auto_hit
- attack_type
- save_ability
- effect_summary
- can_cast

### Feature resolution
May produce:

- action_kind = use_feature
- entry_id / entry_name
- action_cost
- usage_key
- remaining_uses
- effect_summary
- can_use

The resolver is authoritative for mechanics.

---

## 9. Hit / Miss / Damage / Healing

For attacks and damaging effects, the engine resolves outcome in order.

Typical sequence:

1. roll attack if needed
2. compare against target AC if applicable
3. determine hit / miss / unknown
4. if hit and damage applies:
   - roll damage deterministically
   - compute damage total
5. apply healing if appropriate

At this stage, mechanical result exists even if narration has not yet happened.

Narration must follow these results, never invent them.

---

## 10. HP Application

If damage or healing is resolved, the target combatant is updated.

Examples:

- hit_points before
- hit_points after
- defeated true/false

Rules such as resistances, vulnerabilities, temporary HP, death saving throws, and advanced healing may be added later, but HP updates must remain deterministic and event-driven.

---

## 11. Encounter State Update

The encounter state is the authoritative combat container.

It may include:

- encounter_id
- combatants
- initiative order
- current turn index
- current round
- active flag

After each action, encounter state updates may include:

- HP changes
- resource changes
- action economy consumption
- condition changes
- turn advancement
- defeat state

The encounter should be serializable and replayable.

---

## 12. Event Emission

Every meaningful state change should produce structured events.

Examples:

- intent_resolved
- action_resolved
- attack_resolved
- damage_applied
- healing_applied
- condition_added
- combatant_defeated
- mode_transition
- turn_advanced

Events are important because they support:

- narration grounding
- persistence
- replay
- debugging
- lore extraction
- graph memory

The event stream is one of the core truths of the engine.

---

## 13. Persistence

State should remain JSON-serializable.

Persistence may include:

- campaigns
- encounters
- actors
- scenes
- lorebooks
- event logs

Persistence exists to support:

- save/load
- campaign continuity
- audits
- replay
- future API/UI usage

---

## 14. Context Construction

Before narration, the engine builds a context bundle.

Context may include:

- current mode
- encounter status
- combat round / turn
- current combatants
- resolved action summary
- target outcome
- scene state
- compendium excerpts
- lorebook facts
- graph neighbor facts
- session summary

Context should be:

- deterministic
- budgeted
- grounded
- stripped of unnecessary internal metadata before being sent to the narrator

---

## 15. Narration

Narration is the final step.

The narrator receives:

- system prompt
- action result
- resolved action details
- context bundle

Narration may:

- describe what happened
- describe what the player perceives
- describe momentum and tension
- mention hit, miss, damage, defeat, or effect only if already resolved

Narration must never:

- invent mechanics
- invent rolls
- invent damage numbers
- invent entities
- invent setting facts not present in context
- change state

The narrator is descriptive only.

---

# Visual Pipeline

## Core engine pipeline

Player Input  
→ Intent Interpretation  
→ Compendium Match  
→ Actor Load  
→ Combatant Conversion  
→ Resource Validation  
→ Turn Economy Validation  
→ Resolver  
→ Hit/Miss  
→ Damage/Healing  
→ HP Update  
→ Encounter State Update  
→ Event Emission  
→ Context Builder  
→ Narrator  

---

## Responsibility boundaries

### Deterministic / authoritative
These systems define truth:

- interpreter output structure
- compendium entries
- actor data
- combatant snapshots
- turn economy
- action resolver
- hit/miss logic
- damage/healing logic
- HP changes
- encounter state
- events
- persistence

### Non-authoritative / descriptive
These systems only describe truth:

- narration prompt builder
- narrator model
- UI text display

---

# Shared Data Models

The exact field list may change over time, but these conceptual models are central:

## Actor
Represents a player character or other authored sheet.

## CombatantSnapshot
Represents a runtime combat participant.

## CompendiumEntry
Base type for rules content.

Subtypes include:

- WeaponEntry
- SpellEntry
- ItemEntry
- FeatureEntry
- MonsterEntry

## EncounterState
Represents active combat and turn order.

## Event
Represents a structured state change.

## ContextBundle
Represents grounded narration context.

---

# Design Rules

## Rule 1 — Smallest authoritative unit wins
If structured resolved action data exists, it outranks narration assumptions.

## Rule 2 — Resolver outranks context
Narration must describe the resolved result, not infer a different one from broad context.

## Rule 3 — Context informs description, not mechanics
Context may help the narrator sound coherent, but cannot override resolved mechanical truth.

## Rule 4 — Events make the system debuggable
Every meaningful change should be visible in structured event form.

## Rule 5 — Additive changes are preferred
When extending the engine, prefer adding new resolvers, event fields, or adapter layers instead of rewriting stable working systems.

---

# Current Development Direction

The intended order of growth is:

1. deterministic engine core
2. compendium-backed action resolution
3. combatant abstraction
4. damage / HP / healing
5. monsters and initiative
6. encounter state
7. conditions / reactions
8. campaign persistence
9. API
10. UI

Do not skip directly to UI or broad AI behavior changes without respecting the engine pipeline.

---

# Final Reminder

Chronicle Weaver is not a freeform storytelling bot.

It is a deterministic RPG engine with an AI narration layer.

The engine decides what happens.  
The narrator describes what happened.
