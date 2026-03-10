# Chronicle Weaver — Agent Instructions

This repository implements a **deterministic AI-driven tabletop RPG engine**.

Any AI agent modifying this repository must follow the rules below.

Project architecture and development flow are documented in:

- `docs/ARCHITECTURE_OVERVIEW.md` — development roadmap and milestone status
- `docs/ENGINE_PIPELINE.md` — engine pipeline and combat flow
- `docs/PROJECT_GLOSSARY.md` — terminology reference

Agents must read those files before making major changes.

---

## Non-Negotiable Rule

LLMs generate words, not outcomes. The LLM may never:

- roll dice
- change game state
- decide mechanic outcomes
- advance time
- write to persistence directly

---

## Core Principles

### Determinism is mandatory

All gameplay mechanics must be deterministic.

Randomness must ONLY come from the engine's dice / entropy provider.

Never introduce:

- `random.random()`
- `random.randint()`
- nondeterministic timing behavior
- external randomness sources

All dice rolls must use the engine's deterministic dice system.

---

### Narration never affects mechanics

Game mechanics must complete BEFORE narration.

Pipeline:

```
interpret intent
→ match compendium entry
→ validate resources
→ resolve mechanics
→ apply state updates
→ emit events
→ generate narration
```

Narration must never influence mechanical outcomes.

---

### Narration grounding rules

Narration may describe: hits, misses, damage, defeat, spell effects, movement, combat transitions.

Narration must NEVER invent: damage numbers, dice rolls, new entities, additional mechanics, rule outcomes.

Narration must only describe resolved event data.

---

### Combat Resolution Pipeline

No step should be skipped or reordered:

```
Intent Interpretation
→ Compendium Match
→ Resource Validation
→ Action Resolution
→ Hit/Miss Determination
→ Damage / Healing Resolution
→ HP Application
→ Encounter State Update
→ Event Emission
→ Narration
```

---

### Compendium-driven rules

Weapons, spells, features, monsters, and abilities must come from compendium entries.

Avoid hardcoding rule logic tied to specific names.

Compendium entries define: attack bonuses, damage formulas, spell behavior, resource costs, feature effects.

---

### Combatant abstraction

All combat participants must use the `Combatant` model.

Combat systems must not special-case players or monsters. Use shared combatant interfaces instead.

---

### Event-driven state updates

Game state changes should emit structured events (e.g. `attack_resolved`, `damage_applied`, `healing_applied`, `condition_added`, `combatant_defeated`).

---

## Testing Requirements

All changes must keep tests passing.

Run after every modification:

```bash
black .
ruff check .
mypy src
pytest -q
```

Never commit code that fails these checks.

---

## Roadmap Discipline

Development milestones are defined in `docs/ARCHITECTURE_OVERVIEW.md`.

Agents must:

- implement one milestone at a time
- avoid skipping roadmap stages
- avoid large architectural rewrites unless explicitly required

---

## Refactor Restraint

Do not refactor stable systems unless the current milestone explicitly requires it.

When making changes:

- prefer the smallest change that satisfies the milestone
- preserve existing public interfaces where possible
- avoid renaming files, modules, classes, or functions unless necessary
- if a bug can be fixed locally, fix it locally

Before making a broad refactor, ask:

1. Is this required for the current milestone?
2. Will this break tests, fixtures, or CLI workflows?
3. Can this be solved with a smaller patch?

If the answer to 3 is yes, choose the smaller patch.

---

## CLI Stability

The CLI interface is a core development tool.

Commands such as `chronicle-weaver demo`, `chronicle-weaver interpret`, `chronicle-weaver compendium`
should remain stable unless a roadmap milestone explicitly changes them.

---

## Persistence Rules

Game state persistence must remain deterministic and serializable.

State objects must support JSON serialization for: campaigns, encounters, actors, scenes.

---

## Code Style Guidelines

Prefer: small pure functions, deterministic logic, explicit typing, clear data models.

Avoid: deep inheritance hierarchies, hidden state mutation, global mutable state.

Favor composable modules over large classes. Working code with tests is higher priority than cleaner-looking code with larger risk.

---

## Final Project Goals

Chronicle Weaver should ultimately support:

- deterministic combat
- monsters and initiative
- HP, damage, and healing
- conditions and status effects
- reactions and opportunity attacks
- AoE spells and concentration tracking
- XP and levelling
- encounter state management
- campaign persistence
- API access
- UI interface

Agents should prioritize stability, determinism, and composability when implementing new features.
