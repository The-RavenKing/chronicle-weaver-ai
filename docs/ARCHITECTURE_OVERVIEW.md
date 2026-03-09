# Chronicle Weaver Development Roadmap
This document provides milestone prompts for Claude Code to continue developing the Chronicle Weaver deterministic AI RPG engine.

Claude should execute **one milestone at a time**, ensuring the repository passes all checks before moving to the next.

Required checks after every milestone:

black .
ruff check .
mypy src
pytest -q

Do not attempt multiple milestones simultaneously.

---

# Milestone 1 — Acceptance + Regression Stabilization

Goal:
Stabilize the full vertical slice and ensure end-to-end gameplay works.

Claude instructions:

1. Add end-to-end scenario tests for:

- fighter attacking goblin with longsword
- wizard casting Magic Missile
- fighter using Second Wind twice (second fails)

Each scenario should exercise:

interpret  
compendium lookup  
actor resolution  
turn economy  
combat resolution  
HP change  
narration plumbing  

2. Add encounter save/load round-trip test.

3. Create:

docs/acceptance_checklist.md

Include manual checks for:

- hit/miss resolution
- HP changes
- turn progression
- rejected actions
- narration grounding
- persistence correctness

4. Normalize CLI output formatting.

Resolution blocks should be consistent and deterministic.

After completion print:

- new tests added
- any CLI inconsistencies found

---

# Milestone 2 — Encounter AI (Monster Turns)

Goal:
Allow monsters to act during encounters.

Claude instructions:

1. Implement simple deterministic monster action selection.

Monster behavior v0:

- if melee attack available → attack nearest enemy
- otherwise use first available action

2. Ensure monster actions go through the same resolver pipeline as players.

3. Integrate monster turns with initiative order.

4. Add tests for:

- goblin taking an attack action
- goblin turn progressing correctly
- player → monster → player turn loop

Do not implement advanced AI yet.

---

# Milestone 3 — Healing & Resource Restoration

Goal:
Add deterministic healing and resource restoration.

Claude instructions:

1. Add healing resolution function.

2. Support healing from:

- Second Wind
- healing spells (future support)

3. Update HP application logic to support:

apply_damage()  
apply_healing()

4. Add tests:

- healing cannot exceed max HP
- healing applies correctly
- healing does not affect defeated targets incorrectly

---

# Milestone 4 — Conditions with Mechanical Effects

Goal:
Make conditions affect gameplay.

Claude instructions:

Add mechanical handling for conditions:

prone
poisoned
stunned

Examples:

prone → disadvantage on attacks  
poisoned → disadvantage on attack rolls  
stunned → cannot act  

Add condition evaluation step during action resolution.

Tests:

- stunned combatant cannot act
- prone attack disadvantage applied
- poisoned disadvantage applied

---

# Milestone 5 — Opportunity Attacks & Reactions

Goal:
Implement deterministic reaction system.

Claude instructions:

1. Track reactions per combatant.

2. Implement opportunity attacks when a target leaves melee range.

3. Reaction rules:

- one reaction per round
- resets at start of combatant turn

Tests:

- opportunity attack triggered
- reaction consumed
- second reaction rejected

---

# Milestone 6 — Inventory & Equipment State

Goal:
Allow equipment to influence combat.

Claude instructions:

1. Add equipment state to actor snapshots.

Fields:

equipped_weapons  
equipped_armor  
carried_items  

2. Modify attack resolution to reference equipped weapons.

3. Allow switching weapons via interaction action.

Tests:

- weapon switch works
- attack uses correct weapon stats

---

# Milestone 7 — Scene State & Environmental Context

Goal:
Allow narration and gameplay to reference scene state.

Claude instructions:

Add SceneState model:

scene_id  
description_stub  
combat_active  
present_entities  

Scene state should appear in narration prompt context.

Tests:

- scene state included in prompt
- combat flag toggles correctly

---

# Milestone 8 — Campaign Persistence

Goal:
Persist campaigns, encounters, and actors.

Claude instructions:

Add CampaignState model:

campaign_id  
actors  
lorebook  
scenes  
encounters  

Implement:

save_campaign()  
load_campaign()

Tests:

- campaign save/load round trip
- encounter persistence

---

# Milestone 9 — API Layer

Goal:
Expose engine functionality through a FastAPI API.

Endpoints:

POST /interpret  
POST /resolve-action  
POST /narrate  
GET /compendium  
GET /campaign/{id}

API must call engine code — do not duplicate logic.

Tests:

- interpret endpoint
- resolve endpoint
- compendium endpoint

---

# Milestone 10 — Minimal UI Shell

Goal:
Provide a thin UI to interact with the engine.

UI must allow:

- player input
- narration output
- combatant HP display
- initiative order
- resource tracking

UI should call the API endpoints.

No game logic in the frontend.

---

# Development Rules

Claude must:

• follow AGENTS.md  
• keep deterministic behavior  
• avoid introducing randomness outside entropy provider  
• keep narration grounded in resolved data  
• ensure tests remain green  

If tests fail, fix the implementation before proceeding.

---

# Final Target

After all milestones the engine should support:

✔ deterministic combat  
✔ monsters and initiative  
✔ resource tracking  
✔ HP/damage/healing  
✔ conditions  
✔ reactions  
✔ encounters  
✔ campaign persistence  
✔ API access  
✔ basic UI
