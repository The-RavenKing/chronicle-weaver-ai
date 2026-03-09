# Chronicle Weaver — Manual Acceptance Checklist

Use this checklist when performing a manual QA pass against a running backend.
Run `uvicorn chronicle_weaver_ai.api:app --reload` then follow each check.

---

## 1. Hit / Miss

| # | Step | Expected |
|---|------|----------|
| 1 | POST `/interpret` with `"I attack the goblin"` in `combat` mode | `intent=attack`, `entry_id=w.longsword` (if actor has longsword) |
| 2 | POST `/resolve-action` weapon for fighter with longsword | `attack_bonus_total=6`, `action_available=true` |
| 3 | Verify `hit_result=true` when `attack_total ≥ target_armor_class` | Field present in resolved payload after engine enrichment |
| 4 | Verify `hit_result=false` on miss | No `damage_total`, `target_hp_before/after`, or `defeated` fields in payload |
| 5 | POST `/narrate` with `hit_result=true` in `resolved_action` | Prompt section "Target Outcome:" present, contains `hit_result: true` |
| 6 | POST `/narrate` with `hit_result=false` in `resolved_action` | Prompt contains `hit_result: false`; no `damage_total` line in prompt |

---

## 2. Damage

| # | Step | Expected |
|---|------|----------|
| 1 | Resolved weapon attack on a hit | `damage_formula` present (e.g. `"1d8 +3 +1"`) |
| 2 | After engine rolls damage | `damage_rolls`, `damage_modifier_total`, `damage_total` all present |
| 3 | `damage_total` = sum of `damage_rolls` + `damage_modifier_total` | Integer arithmetic, deterministic |
| 4 | Narration prompt on hit includes `damage_total` in Target Outcome | No invented or altered numbers |

---

## 3. HP Changes

| # | Step | Expected |
|---|------|----------|
| 1 | Resolved hit with known target HP | `target_hp_before` and `target_hp_after` both present |
| 2 | `target_hp_after = max(0, target_hp_before - damage_total)` | HP floors at zero, never goes negative |
| 3 | `defeated=true` when `target_hp_after == 0` | Field present only when HP reaches 0 |
| 4 | `defeated=false` when target survives | Field present but false; target continues in encounter |
| 5 | Narration prompt on `defeated=true` | Prompt style rule 11b: narrative may describe target falling |
| 6 | Narration prompt on `target_hp_after=0` | Prompt style rule 11c: no mention of target continuing to fight |

---

## 4. Turn Progression

| # | Step | Expected |
|---|------|----------|
| 1 | Fresh combat turn: `TurnBudget` | `action=true`, `bonus_action=true`, `reaction=true` |
| 2 | After weapon attack (action cost) | `action=false` in persisted budget |
| 3 | After Second Wind (bonus_action cost) | `bonus_action=false`, `action` unchanged |
| 4 | Attempt weapon attack with `action=false` | `action_available=false` in resolved payload; `resolution rejected:` in CLI output |
| 5 | `advance_turn()` resets TurnBudget | Next combatant starts with full budget |
| 6 | `current_round` increments after last combatant acts | `EncounterTurnOrder.current_round` + 1 |

---

## 5. Narration Grounding

| # | Step | Expected |
|---|------|----------|
| 1 | POST `/narrate` returns `prompt` field | Non-empty string; includes style rules 1–18 |
| 2 | Style rule 5 present | "Do not invent outcomes; Action Result and Resolved Action are authoritative." |
| 3 | Style rule 7 present | "Never invent a die result unless explicitly provided." |
| 4 | Style rule 16 present | "Encounter Context shows the current round" |
| 5 | Scene section appears when `scene` provided | "Scene:" header and `scene_id`, `description`, `combat_active` all present |
| 6 | Encounter Context section appears when `encounter_context` provided | "round:", "acting_combatant:", "turn_order:" lines present |
| 7 | Conditions section shows "(none)" when empty | Both attacker and target show "(none)" |
| 8 | No retrieval metadata leaks to prompt | Strings "score=", "priority=", "tokens=", "retrieved" absent from context items |

---

## 6. Rejected Actions / Resources

| # | Step | Expected |
|---|------|----------|
| 1 | POST `/resolve-action` for depleted feature | `can_use=false`, `reason="resource '<key>' is depleted"` |
| 2 | POST `/resolve-action` for spell with no slots | `can_cast=false`, `reason="no spell slot available"` |
| 3 | POST `/resolve-action` for unknown entry | HTTP 404 |
| 4 | POST `/resolve-action` wrong kind (weapon ID → spell endpoint) | HTTP 422 with clear detail |
| 5 | CLI: rejected action (`--player-input`) | `resolution rejected: <reason>` printed and CLI stops; no `intent=`, `dice`, `mode` noise after |
| 6 | CLI: rejected action (interactive loop) | `resolution rejected: <reason>` printed and turn ends; no narrative block follows |
| 7 | CLI: no duplicate rejection messages | Exactly one `resolution rejected:` line per rejected action across both paths |
| 8 | CLI: successful resolution output | `intent=X mechanic=Y`, `dice value=N ...`, `mode A -> B`, `narrative <text>` in order |

---

## 7. Encounter Management

| # | Step | Expected |
|---|------|----------|
| 1 | `demo --spawn goblin --seed 42` | Prints initiative order, round headers, attack rolls, HP status, final outcome |
| 2 | Encounter header | `=== Encounter: <actor> vs <monster> ===` and `Initiative order: ...` |
| 3 | Monster defeat | `<monster> is defeated!` printed; final line says `Victory!` |
| 4 | `is_encounter_over()` after last monster defeated | Returns `True` immediately |
| 5 | `end_turn()` skips defeated combatants | Next active combatant gets turn; defeated entries skipped |
| 6 | `remove_from_order()` adjusts `current_turn_index` | Index decrements if removed entry was before current |
| 7 | Round counter increments | `current_round` increases when last alive combatant wraps |
| 8 | Unknown monster `--spawn dragon_lord` | Exit code ≠ 0, error message on stderr |

---

## 8. Persistence

| # | Step | Expected |
|---|------|----------|
| 1 | `save_campaign` writes valid JSON | File exists; top-level keys: `campaign_id`, `actors`, `scenes`, `encounter_states` |
| 2 | `load_campaign` round-trip for bare campaign | All actors, scenes, lorebook_refs, session_log_refs preserved |
| 3 | `load_campaign` with active encounter | `active_encounter_id` set; encounter combatants present with correct HP |
| 4 | `spell_slots` int keys survive JSON round-trip | Loaded `spell_slots` has `int` keys, not `str` keys |
| 5 | `defeated_ids` frozenset survives round-trip | Serialised as sorted list; loaded as `frozenset` |
| 6 | `conditions` tuple survives round-trip | Each condition's `condition_name`, `duration_type`, `remaining_rounds` preserved |
| 7 | GET `/campaign/{id}` returns 200 for saved campaign | JSON body matches `campaign_to_dict()` output |
| 8 | GET `/campaign/../etc/passwd` returns 400 | Path traversal blocked |
