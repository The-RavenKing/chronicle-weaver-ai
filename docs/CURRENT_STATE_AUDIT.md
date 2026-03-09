# Chronicle Weaver — Current State Audit

**Date:** 2026-03-09
**Auditor:** Claude Sonnet 4.6
**Branch:** main (commit b567809)
**Test count:** 255 passing

---

## A. Implemented Systems

### Deterministic Dice / Entropy
`dice.py`, `drand_stub.py`
Full implementation: `FixedEntropyDiceProvider` (tests), `SeededDiceProvider` (demos), `LocalCSPRNGDiceProvider` (production), `DrandHTTPClient` (verifiable randomness with local fallback). Entropy pools, beacon logging, and `roll_d20_record` / `roll_damage_formula` helpers all present.

### Intent Parsing
`intent_router.py`
`HybridIntentRouter` — rules-first keyword matching with OpenAI/Ollama LLM fallback. Covers ATTACK, CAST_SPELL, USE_FEATURE, DISENGAGE, TALK, SEARCH, INTERACT, and UNKNOWN. Full test suite in `test_intent_router.py`.

### Compendium Loading
`compendium/store.py`, `compendium/models.py`
`CompendiumStore` loads weapons, spells, features, and monsters from JSON files. Four sample entries ship: `w.longsword`, `spell_magic_missile`, `feature_second_wind`, `m.goblin`. Monster entries include AC, HP, abilities, and action lists with damage formulae.

### Actor Loading
`models.py` (`Actor` dataclass)
Full actor sheet: ability scores, proficiency bonus, class/species, level, spell slots, hit points, max hit points, equipped items, known spells/features.

### Combat Resolution
`rules/resolver.py`, `rules/combatant.py`
`resolve_weapon_attack`, `resolve_spell_cast`, `resolve_feature_use`, `resolve_monster_action` all present. Same pipeline for player and monster actions. Attack bonus calculation, damage formula construction, action-economy validation, and `apply_damage` (floors at 0) all working.

### Narration Integration
`narration/narrator.py`, `narration/models.py`, `narration/openai.py`, `narration/ollama.py`
`Narrator` protocol with OpenAI and Ollama adapters. `build_user_prompt` and `build_system_text` produce deterministic, grounded prompts enforcing the "LLM generates words, not outcomes" rule. Scene, encounter context, conditions, and action result all fed into prompt. Style rules 1–18 present.

### Encounter State & Turn Management
`encounter.py`
`EncounterState`, `EncounterTurnOrder`, `create_encounter` (with initiative rolling), `end_turn` (defeat-skipping, round increment), `remove_from_order` (index adjustment), `mark_defeated`, `update_combatant`, `is_encounter_over`. Full test coverage.

### Monster Turns / Encounter AI v0
`monster_turn.py`
`MonsterTurnResult`, `select_monster_action` (v0: first listed action), `run_monster_turn` (full pipeline: identify monster → target selection → resolve → roll d20 → damage on hit → mark defeated). CLI `demo --spawn goblin` runs a complete deterministic encounter.

### Campaign Persistence
`campaign.py`
`CampaignState` model with actors, scenes, lorebook refs, and active encounter. `save_campaign` / `load_campaign` with JSON round-trip. Handles `frozenset` (as sorted list), `int` spell-slot keys, and nested encounter state. Full round-trip tests in `test_campaign_persistence.py`.

### FastAPI Layer
`api.py`
Endpoints: `POST /interpret`, `POST /resolve-action` (weapon/spell/feature), `POST /narrate`, `GET /compendium`, `GET /campaign/{id}`. Thin wrappers delegating to library functions. Path traversal guard on campaign endpoint. `httpx` test client in `test_api.py`.

### Minimal UI Shell
`ui/index.html`, `ui/app.js`
Static HTML/JS frontend. Served by FastAPI. Calls API endpoints for player input, narration, HP display, initiative order, and resource tracking.

### State Machine FSM
`state_machine.py`
Three modes: EXPLORATION → COMBAT → CONTESTED. Transition rules implemented. Tests in `test_state_machine.py`.

### Event Store
`event_store.py`
`InMemoryEventStore` — append-only event log. Used by `Engine` for event sourcing.

### Turn Budget / Action Economy
`models.py` (`TurnBudget`, `can_spend_action`, `spend_action`, etc.)
Tracks action, bonus action, reaction, movement, object interaction, speech per turn. Validated in resolver before action resolution.

### Lore / Context System
`lore/store.py` (`LoreQueueStore`), `memory/context_builder.py`, `memory/context_budget.py`
Append-only JSONL lore queue with approve/reject. `ContextBuilder` assembles context bundles with token budget. Lexical retrieval in `retrieval/lexical.py`.

### Scribe
`scribe/scribe.py`
Deterministic NLP extraction from event list. Produces entity candidates, fact candidates, relation candidates, and session summaries.

### Conditions Model
`rules/conditions.py`, `rules/combatant.py` (`Condition`, `CombatantSnapshot.conditions`)
`Condition` dataclass: `condition_name`, `duration_type` (`rounds`/`permanent`), `remaining_rounds`. Model, serialisation, and combatant integration present. Tests in `test_conditions.py`.

---

## B. Partially Implemented Systems

### Healing
`rules/combatant.py` has `apply_damage` (floors at 0, no negative HP) but **no `apply_healing` function**. `feature_second_wind.json` is in the compendium and `resolve_feature_use` can resolve Second Wind, but no function applies the healing roll result to actor HP. The feature works for resource-depletion tracking; HP restoration is not wired.

### Conditions with Mechanical Effects
The `Condition` model exists and survives persistence round-trips, but conditions are **not evaluated during action resolution**. Prone (disadvantage on attacks), poisoned (disadvantage), and stunned (cannot act) have no effect on dice rolls or resolver output. Milestone 4 is not done.

### Engine Orchestration vs. CLI Encounter Mode
`engine.py` is a standalone orchestrator used by the interactive `demo` loop (intent → compendium match → mechanics → events → narration). The `--spawn` encounter path in `cli.py` bypasses `engine.py` entirely, calling `encounter.py`, `monster_turn.py`, and `rules/resolver.py` directly. The two execution paths are not unified.

### Inventory / Equipment
`Actor` has an `equipment` field, but there is no equip/unequip mechanic, no `equipped_weapons` / `equipped_armor` structure, and attack resolution does not cross-reference what is currently equipped. Milestone 6 is not done.

### Scene State
`CampaignScene` exists in `campaign.py` and the narration prompt accepts `SceneState`. The `combat_active` flag is defined but never toggled by encounter lifecycle events. Scene is not mechanically linked to combat start/end.

### Scribe Approval UX
`LoreQueueStore` supports `approve` / `reject` status updates but there is no CLI command, API endpoint, or interactive workflow for a human to review the queue. The extraction pipeline runs but the results have no consumption path.

---

## C. Missing Systems

| System | Notes |
|--------|-------|
| **`apply_healing()`** | Milestone 3 — no healing function; Second Wind HP restore is unimplemented |
| **Conditions with mechanical effects** | Milestone 4 — model exists but resolver ignores conditions |
| **Opportunity attacks & reactions** | Milestone 5 — reaction tracking exists in `TurnBudget` but no trigger logic |
| **Inventory / equipment mechanics** | Milestone 6 — no equip/unequip, no resolver cross-reference to equipped gear |
| **Scene state mechanical toggle** | Milestone 7 — `CampaignScene` exists but `combat_active` is not toggled by engine |
| **Persona system** | Stubs only in `context_builder.py`; no player/GM/companion personas |
| **Vector RAG** | Only lexical retrieval implemented in `retrieval/lexical.py` |
| **World clock** | No time advancement mechanism |
| **State snapshot rollback** | Event log exists but no `restore_from_snapshot` |
| **Scribe conflict detection** | No duplicate/contradiction detection in lore queue |
| **Companion autonomous behaviour** | Deferred to Phase 2 per design |

---

## D. Documentation Drift

### README.md — Severely outdated
Current text: *"Phase-1 repository skeleton for a deterministic AI RPG engine."*

Reality: The project has a full FastAPI layer, campaign persistence, encounter management, monster AI, narration adapters (OpenAI + Ollama), 255 tests, a UI shell, and 8 of 10 roadmap milestones implemented. The CLI demo also supports `--spawn goblin` and `--compendium-root`.

**Fix needed:** Update description, add `--spawn` demo, add API server instructions.

### pyproject.toml — Stale description
`description = "Chronicle Weaver deterministic AI RPG engine skeleton."` — "skeleton" no longer applies.

### docs/ARCHITECTURE_OVERVIEW.md — Misnaming
This file contains the **development roadmap** (milestone 1–10 prompts for Claude), not an architecture overview. The actual architecture documentation is in `docs/ENGINE_PIPELINE.md` and `docs/PROJECT_GLOSSARY.md`. The filename is misleading.

The file also does not reflect completion status — milestones 1, 2, 8, 9, 10 are implemented but the file gives no indication.

### docs/ — No CLAUDE_ROADMAP.md
Memory notes referenced `docs/CLAUDE_ROADMAP.md` but it does not exist. The roadmap lives at `docs/ARCHITECTURE_OVERVIEW.md`.

### MEMORY.md — Stale test count
Project memory records "117 tests, all passing" — actual count is 255.

---

## E. Test Coverage Assessment

### Well Covered
- Combat resolution pipeline: weapon attacks, spell casts, feature use, monster actions, damage formulae, hit/miss logic
- Encounter lifecycle: initiative rolling, turn order, `end_turn`, `remove_from_order`, `is_encounter_over`, defeat pipeline
- Monster turns: hit/miss/defeat, initiative loop, no-target skip, narration prompt content
- Campaign persistence: full JSON round-trip, spell-slot int keys, `frozenset` serialisation, conditions tuple
- API endpoints: all five endpoint types including error cases and path traversal
- Narration: prompt building, style rules, scene/encounter context, hit/miss grounding
- Intent routing: keyword rules, LLM fallback, each intent type
- Turn budget: action economy validation, depletion, reset on `end_turn`
- Compendium: loading, lookup, monster entries, action lists
- Conditions model: construction, round decrement, serialisation
- HP application: `apply_damage`, overkill floors at 0

### Likely Gaps / Weak Coverage
- **Healing:** No `apply_healing` tests exist because the function does not exist
- **Conditions affecting combat rolls:** No test exercises prone/poisoned/stunned changing an attack roll
- **Opportunity attacks:** No tests for reaction triggers
- **Engine ↔ encounter integration:** `engine.py` and the `--spawn` encounter loop are tested separately; no test exercises them together (e.g., player attacks via engine, then monster responds via encounter loop)
- **Scribe approval workflow:** Queue append/status tested; no test for a full extract → review → approve → lorebook cycle
- **UI:** `test_ui.py` exists (53 lines) but likely only sanity-checks static file serving

---

## F. Recommended Next Milestone

### Milestone 3 — Healing & Resource Restoration

**Justification:**

1. **Closes the most obvious functional gap.** `apply_damage` exists and is fully tested; `apply_healing` is its logical counterpart. Second Wind is already in the compendium and its resolver path is already wired — only the HP-change step is missing.

2. **It is tightly scoped.** Add `apply_healing(combatant, amount) → CombatantSnapshot` to `rules/combatant.py`, wire it into the feature-use path in both `engine.py` and `cli.py`, add ~10 tests. No new subsystems required.

3. **Enables narrative correctness.** Right now a player can use Second Wind (resource depletes) but HP never changes — a testable lie. Fixing it makes the narration grounding claims true.

4. **Unblocks Milestone 4.** Conditions like *Poisoned* are most useful to test when healing is already working (e.g., remove poison → restore HP interaction).

5. **Roadmap sequence.** Milestones 1 and 2 are done; Milestone 3 is next in order.
