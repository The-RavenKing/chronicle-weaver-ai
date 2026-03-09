# AI RPG Engine – Agent Rules (AGENTS.md)

## Non-negotiable rule
LLMs generate words, not outcomes. The LLM may never:
- roll dice
- change game state
- decide mechanics outcomes
- advance time
- write to persistence directly

## Architecture
- Deterministic backend owns: state machine, mechanics, dice, time, persistence, validation.
- LLM layer: intent classification (structured JSON) + narrative text only.

## Workflow
- Always do: PLAN → IMPLEMENT → TEST → SUMMARY.
- Never create files not listed in the approved file manifest.
- Keep changes small and runnable.

## Tech choices (bootstrap)
- Python 3.12
- CLI: Typer
- Tests: pytest
- Lint: ruff
- Format: black
- Types: mypy (light)
- Persistence: in-memory EventStore interface first
- drand: client stub only for now; local CSPRNG is initial implementatio# Chronicle Weaver – Agent Instructions

This repository implements a **deterministic AI-driven RPG engine**.

All agents modifying this repository must follow the rules below.

---

# Core Principles

1. **Determinism is critical**

All game mechanics must be deterministic.

Randomness must only come from the project's entropy provider or dice system.

Do not introduce new randomness sources.

---

2. **Separation of responsibilities**

The architecture is layered:

Interpretation layer  
→ Action resolution layer  
→ State update layer  
→ Narration layer  

Narration must never influence game mechanics.

---

3. **Narration is descriptive only**

Narration may describe:

- hits
- misses
- damage
- defeat
- movement
- spell effects

Narration must never invent:

- damage numbers
- dice rolls
- mechanics
- new entities

Narration must only describe resolved events.

---

4. **Combat Resolution Pipeline**

Combat must follow this order:

Interpret player intent  
→ Match compendium entry  
→ Validate resources and turn economy  
→ Resolve attack/spell/feature  
→ Apply hit/miss logic  
→ Roll damage if applicable  
→ Apply HP changes  
→ Emit events  
→ Generate narration

No step may be skipped.

---

5. **Compendium Driven Mechanics**

Weapons, spells, and features must come from compendium entries.

Do not hardcode mechanics.

All actions should reference compendium entries where possible.

---

6. **Testing Rules**

Every change must keep tests passing.

Required checks after modifications:
# Chronicle Weaver – Agent Instructions

This repository implements a deterministic AI-driven tabletop RPG engine.

Any AI agent (Claude Code, Codex, etc.) modifying this repository must follow the rules below.

Project architecture and development flow are documented in:

docs/ARCHITECTURE_OVERVIEW.md  
docs/CLAUDE_ROADMAP.md

Agents must read those files before making major changes.

---

# Core Principles

## Determinism is mandatory

All gameplay mechanics must be deterministic.

Randomness must ONLY come from the engine's dice/entropy provider.

Never introduce:

- random.random()
- random.randint()
- nondeterministic timing behavior
- external randomness sources

All dice rolls must use the engine's deterministic dice system.

---

## Narration never affects mechanics

Game mechanics must complete BEFORE narration.

Pipeline:

interpret intent  
→ match compendium entry  
→ validate resources  
→ resolve mechanics  
→ apply state updates  
→ emit events  
→ generate narration  

Narration must never influence mechanical outcomes.

---

## Narration grounding rules

Narration may describe:

- hits
- misses
- damage
- defeat
- spell effects
- movement
- combat transitions

Narration must NEVER invent:

- damage numbers
- dice rolls
- new entities
- additional mechanics
- rule outcomes

Narration must only describe resolved event data.

---

## Combat Resolution Pipeline

Combat must follow this order:

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

No step should be skipped or reordered.

---

## Compendium-driven rules

Weapons, spells, features, monsters, and abilities should come from compendium entries.

Avoid hardcoding rule logic tied to specific names.

Instead use:

compendium entry  
→ resolver logic  
→ outcome  

Compendium entries define:

- attack bonuses
- damage formulas
- spell behavior
- resource costs
- feature effects

---

## Combatant abstraction

All combat participants must use the Combatant model.

Combatants may represent:

- player characters
- monsters
- NPC allies
- summoned creatures

Combat systems must not special-case players or monsters.

Use shared combatant interfaces instead.

---

## Event-driven state updates

Game state changes should emit structured events.

Examples include:

- attack_resolved
- damage_applied
- healing_applied
- condition_added
- condition_removed
- combatant_defeated

Events enable:

- narration grounding
- persistence
- debugging
- replay

---

## Testing requirements

All changes must keep tests passing.

Agents must run the following after modifications:

black .  
ruff check .  
mypy src  
pytest -q  

Never commit code that fails these checks.

---

## Roadmap discipline

Development milestones are defined in:

docs/CLAUDE_ROADMAP.md

Agents must:

- implement one milestone at a time
- avoid skipping roadmap stages
- avoid large architectural rewrites unless explicitly required

---

## Architecture reference

Before modifying engine systems, agents must read:

docs/ARCHITECTURE_OVERVIEW.md

This file explains:

- engine pipeline
- combat resolution flow
- compendium architecture
- narration design
- encounter state structure

---

## Backwards compatibility

Do not break:

- CLI commands
- example fixtures
- deterministic test behavior

If refactoring requires interface changes, update tests accordingly.

---

## Code style guidelines

Prefer:

- small pure functions
- deterministic logic
- explicit typing
- clear data models

Avoid:

- deep inheritance hierarchies
- hidden state mutation
- global mutable state

Favor composable modules over large classes.

---

## CLI stability

The CLI interface is a core development tool.

Commands such as:

chronicle_weaver_ai.cli demo  
chronicle_weaver_ai.cli interpret  
chronicle_weaver_ai.cli compendium  

should remain stable unless a roadmap milestone explicitly changes them.

---

## Persistence rules

Game state persistence must remain deterministic and serializable.

State objects should support JSON serialization for:

- campaigns
- encounters
- actors
- scenes

---

# Final Project Goals

Chronicle Weaver should ultimately support:

- deterministic combat
- monsters and initiative
- HP, damage, and healing
- conditions and status effects
- reactions and opportunity attacks
- encounter state management
- campaign persistence
- API access
- UI interface

Agents should prioritize stability, determinism, and composability when implementing new features.

## Refactor restraint

Do not refactor stable systems unless the current milestone explicitly requires it.

When making changes:

- prefer the smallest change that satisfies the milestone
- preserve existing public interfaces where possible
- avoid renaming files, modules, classes, or functions unless necessary
- avoid rewriting working subsystems just for style consistency
- do not replace one architecture with another unless required by the roadmap
- if a bug can be fixed locally, fix it locally instead of restructuring surrounding code

Before making a broad refactor, ask:

1. Is this required for the current milestone?
2. Will this break tests, fixtures, or CLI workflows?
3. Can this be solved with a smaller patch?

If the answer to 3 is yes, choose the smaller patch.

When touching multiple subsystems, prefer:

- additive changes
- adapters
- wrapper functions
- compatibility layers

over destructive rewrites.

Working code with tests is higher priority than cleaner-looking code with larger risk.
# Chronicle Weaver – Agent Instructions

This repository implements a deterministic AI-driven tabletop RPG engine.

Any AI agent (Claude Code, Codex, etc.) modifying this repository must follow the rules below.

Project architecture and development flow are documented in:

docs/ARCHITECTURE_OVERVIEW.md  
docs/CLAUDE_ROADMAP.md  

Agents must read those files before making major changes.

---

# Core Principles

## Determinism is mandatory

All gameplay mechanics must be deterministic.

Randomness must ONLY come from the engine's dice / entropy provider.

Never introduce:

- random.random()
- random.randint()
- nondeterministic timing behavior
- external randomness sources

All dice rolls must use the engine's deterministic dice system.

---

## Narration never affects mechanics

Game mechanics must complete BEFORE narration.

Pipeline:

interpret intent  
→ match compendium entry  
→ validate resources  
→ resolve mechanics  
→ apply state updates  
→ emit events  
→ generate narration  

Narration must never influence mechanical outcomes.

---

## Narration grounding rules

Narration may describe:

- hits
- misses
- damage
- defeat
- spell effects
- movement
- combat transitions

Narration must NEVER invent:

- damage numbers
- dice rolls
- new entities
- additional mechanics
- rule outcomes

Narration must only describe resolved event data.

---

## Combat Resolution Pipeline

Combat must follow this order:

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

No step should be skipped or reordered.

---

## Compendium-driven rules

Weapons, spells, features, monsters, and abilities should come from compendium entries.

Avoid hardcoding rule logic tied to specific names.

Instead use:

compendium entry  
→ resolver logic  
→ outcome  

Compendium entries define:

- attack bonuses
- damage formulas
- spell behavior
- resource costs
- feature effects

---

## Combatant abstraction

All combat participants must use the Combatant model.

Combatants may represent:

- player characters
- monsters
- NPC allies
- summoned creatures

Combat systems must not special-case players or monsters.

Use shared combatant interfaces instead.

---

## Event-driven state updates

Game state changes should emit structured events.

Examples include:

- attack_resolved
- damage_applied
- healing_applied
- condition_added
- condition_removed
- combatant_defeated

Events enable:

- narration grounding
- persistence
- debugging
- replay

---

## Testing requirements

All changes must keep tests passing.

Agents must run the following after modifications:

black .  
ruff check .  
mypy src  
pytest -q  

Never commit code that fails these checks.

---

## Roadmap discipline

Development milestones are defined in:

docs/CLAUDE_ROADMAP.md

Agents must:

- implement one milestone at a time
- avoid skipping roadmap stages
- avoid large architectural rewrites unless explicitly required

---

## Architecture reference

Before modifying engine systems, agents must read:

docs/ARCHITECTURE_OVERVIEW.md

This file explains:

- engine pipeline
- combat resolution flow
- compendium architecture
- narration design
- encounter state structure

---

## Backwards compatibility

Do not break:

- CLI commands
- example fixtures
- deterministic test behavior

If refactoring requires interface changes, update tests accordingly.

---

## Code style guidelines

Prefer:

- small pure functions
- deterministic logic
- explicit typing
- clear data models

Avoid:

- deep inheritance hierarchies
- hidden state mutation
- global mutable state

Favor composable modules over large classes.

---

## Refactor restraint

Do not refactor stable systems unless the current milestone explicitly requires it.

When making changes:

- prefer the smallest change that satisfies the milestone
- preserve existing public interfaces where possible
- avoid renaming files, modules, classes, or functions unless necessary
- avoid rewriting working subsystems just for style consistency
- do not replace one architecture with another unless required by the roadmap
- if a bug can be fixed locally, fix it locally instead of restructuring surrounding code

Before making a broad refactor, ask:

1. Is this required for the current milestone?
2. Will this break tests, fixtures, or CLI workflows?
3. Can this be solved with a smaller patch?

If the answer to question 3 is yes, choose the smaller patch.

When touching multiple subsystems, prefer:

- additive changes
- adapters
- wrapper functions
- compatibility layers

over destructive rewrites.

Working code with tests is higher priority than cleaner-looking code with larger risk.

---

## CLI stability

The CLI interface is a core development tool.

Commands such as:

chronicle_weaver_ai.cli demo  
chronicle_weaver_ai.cli interpret  
chronicle_weaver_ai.cli compendium  

should remain stable unless a roadmap milestone explicitly changes them.

---

## Persistence rules

Game state persistence must remain deterministic and serializable.

State objects should support JSON serialization for:

- campaigns
- encounters
- actors
- scenes

---

# Final Project Goals

Chronicle Weaver should ultimately support:

- deterministic combat
- monsters and initiative
- HP, damage, and healing
- conditions and status effects
- reactions and opportunity attacks
- encounter state management
- campaign persistence
- API access
- UI interface

Agents should prioritize stability, determinism, and composability when implementing new features.
