'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  mode: 'exploration',
  actor: null,            // ActorBody dict
  encounter: null,        // { combatants:[{id,name,hp,maxHp,ac,sourceType}], currentIndex, round }
  actionUsed: false,
  bonusUsed: false,
  reactionUsed: false,
  busy: false,
};

// ── DOM ────────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

// ── Escape HTML ────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Ability modifier ───────────────────────────────────────────────────────
const abilityMod = (score) => Math.floor((score - 10) / 2);
const fmtMod = (m) => (m >= 0 ? `+${m}` : String(m));

// ── HP colouring ───────────────────────────────────────────────────────────
function hpClass(hp, maxHp) {
  if (!maxHp) return '';
  const pct = hp / maxHp;
  if (pct <= 0.25) return 'crit';
  if (pct <= 0.5) return 'low';
  return '';
}

// ── Log helpers ────────────────────────────────────────────────────────────
function log(html) {
  const el = $('narration-log');
  // remove empty state on first entry
  const empty = $('empty-state');
  if (empty) empty.remove();
  el.insertAdjacentHTML('beforeend', `<div class="log-entry">${html}</div>`);
  el.scrollTop = el.scrollHeight;
}

let _thinkingEl = null;
function showThinking(text = 'Resolving action…') {
  removeThinking();
  const el = $('narration-log');
  if ($('empty-state')) $('empty-state').remove();
  _thinkingEl = document.createElement('div');
  _thinkingEl.className = 'log-entry';
  _thinkingEl.innerHTML = `<span class="thinking"><span class="spinner"></span>${esc(text)}</span>`;
  el.appendChild(_thinkingEl);
  el.scrollTop = el.scrollHeight;
}
function removeThinking() {
  if (_thinkingEl) { _thinkingEl.remove(); _thinkingEl = null; }
}

// ── Fetch wrapper ──────────────────────────────────────────────────────────
async function apiFetch(path, method, body) {
  const opts = { method: method || 'GET', headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (_) { }
    throw new Error(`HTTP ${resp.status}: ${detail}`);
  }
  return resp.json();
}

// ── Render: actor sheet ────────────────────────────────────────────────────
function renderActor() {
  const panel = $('actor-panel');
  const a = state.actor;
  if (!a) { panel.innerHTML = '<span class="dim">No actor loaded</span>'; return; }

  const hp = a.hit_points ?? '?';
  const maxHp = a.hit_points ?? 0;
  const hpPct = maxHp > 0 ? Math.max(0, Math.min(100, (hp / maxHp) * 100)) : 100;
  const hpCls = hpClass(hp, maxHp);

  const slots = Object.entries(a.spell_slots || {}).map(([l, n]) => `L${l}×${n}`).join(' ') || '—';

  const abilities = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
  const abilityHtml = abilities.map(ab => {
    const score = a.abilities?.[ab] ?? 10;
    const mod = abilityMod(score);
    return `<div class="ability-box">
      <div class="abl">${ab}</div>
      <div class="abl-val">${score}</div>
      <div class="abl-mod">${fmtMod(mod)}</div>
    </div>`;
  }).join('');

  const resourceHtml = Object.entries(a.resources || {}).map(([key, maxVal]) => {
    const label = key.replace(/_/g, ' ');
    const pips = Array.from({ length: Math.max(0, maxVal) }, (_, i) =>
      `<span class="pip${state.bonusUsed && i >= (maxVal - 1) ? ' empty' : ''}"></span>`
    ).join('');
    return `<div class="resource-row">
      <span class="r-name">${esc(label)}</span>
      <span class="r-pips">${pips}</span>
    </div>`;
  }).join('') || '<span class="dim" style="font-size:0.7rem">None</span>';

  const econAction = state.actionUsed ? 'used' : '';
  const econBonus = state.bonusUsed ? 'used' : '';
  const econReaction = state.reactionUsed ? 'used' : '';

  panel.innerHTML = `
    <div class="stat-grid">
      <div class="stat-box"><div class="label">Level</div><div class="value">${esc(a.level)}</div></div>
      <div class="stat-box"><div class="label">Prof</div><div class="value">+${esc(a.proficiency_bonus)}</div></div>
      <div class="stat-box"><div class="label">AC</div><div class="value">${esc(a.armor_class ?? '?')}</div></div>
      <div class="stat-box"><div class="label">Slots</div><div class="value" style="font-size:0.65rem;line-height:1.3">${esc(slots)}</div></div>
    </div>
    <div class="hp-bar-wrap">
      <div class="hp-label"><span>HP</span><span style="font-family:var(--font-mono)">${hp}/${maxHp}</span></div>
      <div class="hp-bar"><div class="hp-fill ${hpCls}" style="width:${hpPct}%"></div></div>
    </div>
    <div class="sub-title">Abilities</div>
    <div class="ability-grid">${abilityHtml}</div>
    <div class="sub-title">Resources</div>
    ${resourceHtml}
    <div class="sub-title">Action Economy</div>
    <div class="economy-row">
      <span class="token ${econAction}">Action</span>
      <span class="token ${econBonus}">Bonus</span>
      <span class="token ${econReaction}">Reaction</span>
    </div>`;
}

// ── Render: encounter order ────────────────────────────────────────────────
function renderEncounter() {
  const panel = $('encounter-panel');
  const enc = state.encounter;
  if (!enc) { panel.innerHTML = '<span class="dim">No encounter active</span>'; return; }

  const roundBadge = `<div class="round-badge">Round ${enc.round}</div>`;

  const rows = enc.combatants.map((c, i) => {
    const active = i === enc.currentIndex;
    const defeated = c.hp <= 0;
    const cls = [active ? 'active' : '', defeated ? 'defeated' : ''].filter(Boolean).join(' ');
    const arrow = active ? '▶' : '&nbsp;';
    const hpPct = c.maxHp > 0 ? Math.max(0, Math.min(100, (c.hp / c.maxHp) * 100)) : 100;
    const hpCls = hpClass(c.hp, c.maxHp);
    const typeIcon = c.sourceType === 'monster' ? '👹' : '🧙';
    return `<div class="combatant-row ${cls}">
      <span class="turn-arrow">${arrow}</span>
      <span style="font-size:0.75rem">${typeIcon}</span>
      <span class="c-name">${esc(c.name)}</span>
      <span class="c-hp ${hpCls}">${c.hp}/${c.maxHp}</span>
    </div>`;
  }).join('');

  panel.innerHTML = roundBadge + rows;
}

// ── Render: resolution panel ───────────────────────────────────────────────
function renderResolution(res) {
  const panel = $('resolution-panel');
  if (!res) { panel.innerHTML = '<span class="dim">None yet</span>'; return; }

  // Fields to omit (too verbose)
  const skip = new Set(['explanation', 'reason', 'effect_summary']);
  const hitKeys = new Set(['action_available', 'auto_hit', 'can_cast', 'can_use']);

  const rows = Object.entries(res)
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== undefined)
    .map(([k, v]) => {
      let displayVal = typeof v === 'object' ? JSON.stringify(v) : String(v);
      let cls = '';
      if (hitKeys.has(k)) cls = v ? 'hit' : 'miss';
      if (k === 'attack_bonus_total') displayVal = `+${displayVal}`;
      return `<div class="res-item">
        <span class="res-key">${esc(k.replace(/_/g, ' '))}</span>
        <span class="res-val ${cls}">${esc(displayVal)}</span>
      </div>`;
    }).join('');

  // Show long narrative fields below
  const narrative = ['explanation', 'reason', 'effect_summary'].map(k => {
    if (!res[k]) return '';
    return `<div style="margin-top:8px;font-size:0.68rem;color:var(--text-muted);line-height:1.5;font-style:italic">${esc(res[k])}</div>`;
  }).join('');

  panel.innerHTML = rows + narrative || '<span class="dim">No data</span>';
}

// ── Mode badge ─────────────────────────────────────────────────────────────
function setMode(m) {
  state.mode = m;
  const badge = $('mode-badge');
  badge.textContent = m;
  badge.className = m === 'combat' ? 'combat' : '';
}

// ── Advance encounter turn ─────────────────────────────────────────────────
function advanceTurn() {
  if (!state.encounter) return;
  const enc = state.encounter;
  let next = enc.currentIndex;
  // skip defeated combatants
  for (let i = 0; i < enc.combatants.length; i++) {
    next = (next + 1) % enc.combatants.length;
    if (enc.combatants[next].hp > 0) break;
  }
  if (next <= enc.currentIndex && next !== enc.currentIndex) enc.round++;
  else if (next === 0 && enc.currentIndex === enc.combatants.length - 1) enc.round++;
  enc.currentIndex = next;
  state.actionUsed = false;
  state.bonusUsed = false;
  state.reactionUsed = false;
  renderEncounter();
  renderActor();
}

// ── Demo loader ────────────────────────────────────────────────────────────
function loadDemo() {
  state.actor = {
    actor_id: 'pc.fighter.demo',
    name: 'Aldric the Fighter',
    level: 3,
    proficiency_bonus: 2,
    abilities: { str: 16, dex: 12, con: 14, int: 8, wis: 10, cha: 10 },
    equipped_weapon_ids: ['w.longsword'],
    known_spell_ids: [],
    feature_ids: ['f.second_wind'],
    item_ids: [],
    spell_slots: {},
    resources: { second_wind: 1 },
    armor_class: 16,
    hit_points: 28,
  };
  state.encounter = {
    combatants: [
      { id: 'pc.fighter.demo', name: 'Aldric', hp: 28, maxHp: 28, ac: 16, sourceType: 'actor' },
      { id: 'm.goblin', name: 'Goblin', hp: 7, maxHp: 7, ac: 13, sourceType: 'monster' },
    ],
    currentIndex: 0,
    round: 1,
  };
  state.actionUsed = false;
  state.bonusUsed = false;
  state.reactionUsed = false;
  setMode('combat');
  renderActor();
  renderEncounter();
  renderResolution(null);
  log(`<div class="divider"></div>
    <div class="player-cmd" style="padding-top:4px">Demo scenario loaded</div>
    <div class="intent-chips">
      <span class="chip intent-chip">Aldric the Fighter vs Goblin</span>
      <span class="chip mech-chip">Standard combat · Round 1</span>
    </div>
    <div class="narration-block">The encounter begins. Aldric stands ready, longsword drawn, facing a sneering goblin across a dusty tavern floor. Initiative has been rolled — it is your turn.\n\nTry: "I attack the goblin with my longsword"</div>`);
}


// ── Prose generator ────────────────────────────────────────────────────────
// Produces readable narration from structured game data without an LLM.
function buildProse(intent, resolved, appState) {
  const actorName = appState.actor?.name || 'You';
  const enc = appState.encounter;
  const target = enc
    ? enc.combatants.find((c, i) => i !== enc.currentIndex && c.hp > 0)
    : null;
  const targetName = target?.name || 'the enemy';

  if (!resolved) {
    // Unresolved intents — fallback by intent type
    const fallbacks = {
      attack: `${actorName} moves into position, weapon ready.`,
      cast_spell: `${actorName} draws upon arcane reserves, words of power forming on their lips.`,
      talk: `${actorName} speaks, voice steady despite the tension in the air.`,
      search: `${actorName} scans the area carefully, eyes sweeping every shadow.`,
      interact: `${actorName} reaches out to examine the object before them.`,
      disengage: `${actorName} steps back deliberately, creating distance without opening themselves to reprisal.`,
      flee: `${actorName} turns and runs, every instinct screaming to put ground between themselves and danger.`,
    };
    return fallbacks[intent.intent] || `${actorName} acts with purpose.`;
  }

  const kind = resolved.action_kind || intent.entry_kind;
  const entryName = resolved.entry_name || intent.entry_name || 'the weapon';
  const available = resolved.action_available ?? resolved.can_cast ?? resolved.can_use ?? true;

  if (!available) {
    const reason = resolved.reason || resolved.effect_summary || 'the action is not available';
    return `${actorName} attempts to act, but cannot — ${reason}.`;
  }

  if (kind === 'attack') {
    const bonus = resolved.attack_bonus_total || 0;
    const formula = resolved.damage_formula || '1d8';
    const ability = resolved.attack_ability_used || 'STR';
    const templates = [
      `${actorName} lunges forward, ${entryName} arcing through the air toward ${targetName}. The strike drives home — ${formula} damage, ${ability.toUpperCase()} granting a +${bonus} to hit.`,
      `Steel meets air as ${actorName} swings their ${entryName} at ${targetName}. The attack connects with a satisfying crack, rolling ${formula} damage (attack bonus: +${bonus}).`,
      `With a battle-cry, ${actorName} levels a blow at ${targetName} with the ${entryName}. The hit lands — +${bonus} to hit, ${formula} damage rolled.`,
    ];
    return templates[Math.floor(Date.now() / 1000) % templates.length];
  }

  if (kind === 'spell') {
    const spellName = entryName;
    const autoHit = resolved.auto_hit;
    const effect = resolved.effect_summary || 'arcane energy erupts';
    const hitLine = autoHit ? 'It strikes true without need for a roll.' : 'The spell arcs toward its mark.';
    return `${actorName} raises a hand and speaks the incantation for ${spellName}. ${effect.charAt(0).toUpperCase() + effect.slice(1)}. ${hitLine}`;
  }

  if (kind === 'feature') {
    const remaining = resolved.remaining_uses ?? 0;
    const effect = resolved.effect_summary || 'a surge of power';
    return `${actorName} calls upon ${entryName} — ${effect}. (${remaining} use${remaining !== 1 ? 's' : ''} remaining.)`;
  }

  return `${actorName} acts decisively.`;
}

// ── Main action flow ───────────────────────────────────────────────────────
async function submitAction() {

  if (state.busy) return;
  const inputEl = $('player-input');
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  state.busy = true;
  inputEl.disabled = true;
  $('submit-btn').disabled = true;

  log(`<div class="player-cmd">${esc(text)}</div>`);
  showThinking('Interpreting intent…');

  // ── 1. Interpret ──────────────────────────────────────────────────
  let intent;
  try {
    intent = await apiFetch('/interpret', 'POST', { text, mode: state.mode });
  } catch (e) {
    removeThinking();
    log(`<div class="err-block">⚠ Interpret error: ${esc(e.message)}</div>`);
    finish(); return;
  }
  removeThinking();

  const entryChip = intent.entry_name
    ? `<span class="chip" style="color:var(--text-body)">${esc(intent.entry_name)}</span>`
    : '';
  const confChip = intent.provider_used
    ? `<span class="chip">${esc(intent.provider_used)} · conf ${Number(intent.confidence).toFixed(2)}</span>`
    : '';
  log(`<div class="intent-chips">
    <span class="chip intent-chip">${esc(intent.intent)}</span>
    <span class="chip mech-chip">${esc(intent.mechanic)}</span>
    ${entryChip}${confChip}
  </div>`);

  // ── 2. Resolve action ─────────────────────────────────────────────
  let resolved = null;
  const resolvableKinds = new Set(['weapon', 'spell', 'feature']);
  if (intent.entry_id && resolvableKinds.has(intent.entry_kind) && state.actor) {
    showThinking('Rolling dice…');
    try {
      resolved = await apiFetch('/resolve-action', 'POST', {
        action_type: intent.entry_kind,
        entry_id: intent.entry_id,
        actor: state.actor,
      });
      removeThinking();
      renderResolution(resolved);
      if (resolved.action_cost === 'action') state.actionUsed = true;
      if (resolved.action_cost === 'bonus_action') state.bonusUsed = true;
      renderActor();
    } catch (e) {
      removeThinking();
      log(`<div class="warn-block">⚡ Resolve: ${esc(e.message)}</div>`);
    }
  }

  // ── 3. Narrate — build prose from resolved data ───────────────────
  const modeFrom = state.mode;
  if (intent.intent === 'enter_combat') setMode('combat');
  else if (['disengage', 'flee', 'end_combat'].includes(intent.intent)) setMode('exploration');

  removeThinking();

  // Build an evocative client-side narration from resolved action data.
  // The /narrate endpoint just builds a prompt for an LLM; we synthesise
  // prose directly here so the UI is usable without an LLM configured.
  const prose = buildProse(intent, resolved, state);

  // Dice result chips
  let resultHtml = '';
  if (resolved) {
    const available = resolved.action_available ?? resolved.can_cast ?? resolved.can_use;
    const formula = resolved.damage_formula || '';
    const bonus = resolved.attack_bonus_total != null ? `+${resolved.attack_bonus_total}` : '';
    if (formula || bonus) {
      resultHtml = `<div class="intent-chips" style="margin-bottom:4px">
        <span class="chip" style="color:var(--${available ? 'green' : 'red'})">${available ? '✓ Action available' : '✗ Blocked'}</span>
        ${formula ? `<span class="chip mech-chip">dmg ${esc(formula)}</span>` : ''}
        ${bonus ? `<span class="chip">${esc(bonus)} to hit</span>` : ''}
      </div>`;
    }
  }

  log(`${resultHtml}<div class="narration-block">${esc(prose)}</div>`);

  // ── 4. Simulate HP change for demo encounters ─────────────────────
  if (resolved && state.encounter && intent.entry_kind === 'weapon') {
    // Simple demo: if attack is available, apply estimated damage to current target
    const enc = state.encounter;
    const targetIdx = enc.combatants.findIndex((c, i) =>
      i !== enc.currentIndex && c.hp > 0
    );
    if (targetIdx >= 0 && resolved.action_available) {
      const formula = resolved.damage_formula || '1d8';
      const match = formula.match(/^(\d+)d(\d+)(?:[+-](\d+))?/);
      if (match) {
        const [, num, sides, bonus] = match;
        // use a fixed mid-roll for display purposes
        const dmg = Math.max(1, Math.round(
          (parseInt(num) * (parseInt(sides) + 1) / 2) + (parseInt(bonus || 0))
        ));
        const target = enc.combatants[targetIdx];
        target.hp = Math.max(0, target.hp - dmg);
        renderEncounter();
      }
    }
  }

  // ── 5. Advance turn ────────────────────────────────────────────────
  advanceTurn();

  finish();
}

function finish() {
  state.busy = false;
  const inputEl = $('player-input');
  inputEl.disabled = false;
  $('submit-btn').disabled = false;
  inputEl.focus();
}

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  $('submit-btn').addEventListener('click', submitAction);
  $('demo-btn').addEventListener('click', loadDemo);
  $('player-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) submitAction();
  });
  renderActor();
  renderEncounter();
  renderResolution(null);
});
