'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
// All rules logic lives in the backend.  The frontend only holds display state.
const state = {
  mode: 'exploration',    // current GameMode string
  actor: null,            // ActorBody dict mirroring the Pydantic model
  encounter: null,        // { combatants:[{id,name,hp,maxHp,ac}], currentIndex, round }
  actionUsed: false,      // reset each turn advance
  bonusUsed: false,
  reactionUsed: false,
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

// ── HTML escape ───────────────────────────────────────────────────────────────
function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ── Log helpers ───────────────────────────────────────────────────────────────
function log(html) {
  const el = $('narration-log');
  el.insertAdjacentHTML('beforeend', html);
  el.scrollTop = el.scrollHeight;
}

// ── Fetch wrapper ─────────────────────────────────────────────────────────────
async function apiFetch(path, method, body) {
  const opts = { method: method || 'GET', headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (_) {}
    throw new Error(`HTTP ${resp.status}: ${detail}`);
  }
  return resp.json();
}

// ── KV row helper ─────────────────────────────────────────────────────────────
function kv(key, val) {
  return `<div class="kv"><span class="k">${esc(key)}</span><span class="v">${esc(String(val))}</span></div>`;
}

// ── Render: actor sheet ───────────────────────────────────────────────────────
function renderActor() {
  const panel = $('actor-panel');
  const a = state.actor;
  if (!a) { panel.innerHTML = '<span class="dim">No actor — click Load Demo</span>'; return; }

  const hp = a.hit_points != null ? `${a.hit_points}/${a.hit_points}` : '?';
  const slots = Object.entries(a.spell_slots || {})
    .map(([lvl, n]) => `L${lvl}×${n}`).join(' ') || '—';

  const resourceRows = Object.entries(a.resources || {}).length
    ? Object.entries(a.resources).map(([k, v]) => kv(k.replace(/_/g, ' '), v)).join('')
    : '<div class="kv"><span class="k">—</span></div>';

  const actionCls  = state.actionUsed  ? 'token used' : 'token';
  const bonusCls   = state.bonusUsed   ? 'token used' : 'token';
  const reactionCls = state.reactionUsed ? 'token used' : 'token';

  panel.innerHTML = `
    ${kv('name', a.name)}
    ${kv('level', a.level)}
    ${kv('hp', hp)}
    ${kv('ac', a.armor_class ?? '?')}
    ${kv('prof bonus', '+' + a.proficiency_bonus)}
    ${kv('spell slots', slots)}
    <div class="sub-title">Resources</div>
    ${resourceRows}
    <div class="sub-title">Action Economy</div>
    <div class="economy-row">
      <span class="${actionCls}">Action</span>
      <span class="${bonusCls}">Bonus</span>
      <span class="${reactionCls}">Reaction</span>
    </div>`;
}

// ── Render: encounter order ───────────────────────────────────────────────────
function renderEncounter() {
  const panel = $('encounter-panel');
  const enc = state.encounter;
  if (!enc) { panel.innerHTML = '<span class="dim">No encounter</span>'; return; }

  const rows = enc.combatants.map((c, i) => {
    const active = i === enc.currentIndex;
    return `<div class="turn-entry${active ? ' active' : ''}">` +
      `${active ? '▶ ' : '  '}${esc(c.name)} &nbsp;HP ${c.hp}/${c.maxHp} AC ${c.ac}` +
      `</div>`;
  }).join('');

  panel.innerHTML = kv('round', enc.round) + rows;
}

// ── Render: last resolution ───────────────────────────────────────────────────
function renderResolution(res) {
  const panel = $('resolution-panel');
  if (!res) { panel.innerHTML = '<span class="dim">None</span>'; return; }

  const rows = Object.entries(res)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => kv(k, typeof v === 'object' ? JSON.stringify(v) : v))
    .join('');
  panel.innerHTML = rows;
}

// ── Mode badge ────────────────────────────────────────────────────────────────
function setMode(m) {
  state.mode = m;
  const badge = $('mode-badge');
  badge.textContent = m;
  badge.className = m === 'combat' ? 'combat' : '';
}

// ── Advance encounter turn ────────────────────────────────────────────────────
function advanceTurn() {
  if (!state.encounter) return;
  state.encounter.currentIndex =
    (state.encounter.currentIndex + 1) % state.encounter.combatants.length;
  if (state.encounter.currentIndex === 0) state.encounter.round++;
  // reset action economy for new turn
  state.actionUsed = false;
  state.bonusUsed = false;
  state.reactionUsed = false;
  renderEncounter();
}

// ── Demo state loader ─────────────────────────────────────────────────────────
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
    resources: { second_wind_uses: 1 },
    armor_class: 16,
    hit_points: 28,
  };
  state.encounter = {
    combatants: [
      { id: 'pc.fighter.demo', name: 'Aldric', hp: 28, maxHp: 28, ac: 16 },
      { id: 'm.goblin',         name: 'Goblin', hp: 7,  maxHp: 7,  ac: 13 },
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
  log('<div class="intent-line">Demo loaded — Aldric vs Goblin, combat round 1.</div>' +
      '<div class="intent-line">Try: "I attack the goblin with my longsword"</div>');
}

// ── Main action flow ──────────────────────────────────────────────────────────
async function submitAction() {
  const inputEl = $('player-input');
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';

  log(`<div class="player-cmd">&gt; ${esc(text)}</div>`);

  // ── 1. Interpret ────────────────────────────────────────────
  let intent;
  try {
    intent = await apiFetch('/interpret', 'POST', { text, mode: state.mode });
  } catch (e) {
    log(`<div class="err-line">Interpret error: ${esc(e.message)}</div>`);
    return;
  }

  const entryTag = intent.entry_name ? ` · entry=<strong>${esc(intent.entry_name)}</strong>` : '';
  log(`<div class="intent-line">` +
    `intent=<strong>${esc(intent.intent)}</strong>` +
    ` mechanic=<strong>${esc(intent.mechanic)}</strong>` +
    ` conf=${Number(intent.confidence).toFixed(2)}${entryTag}` +
    `</div>`);

  // ── 2. Resolve action (if compendium entry known + actor loaded) ──
  let resolved = null;
  const resolvableKinds = new Set(['weapon', 'spell', 'feature']);
  if (intent.entry_id && resolvableKinds.has(intent.entry_kind) && state.actor) {
    try {
      resolved = await apiFetch('/resolve-action', 'POST', {
        action_type: intent.entry_kind,
        entry_id: intent.entry_id,
        actor: state.actor,
      });
      renderResolution(resolved);
      // Mark action as used if action cost is 'action'
      if (resolved.action_cost === 'action') state.actionUsed = true;
      if (resolved.action_cost === 'bonus_action') state.bonusUsed = true;
      renderActor();
    } catch (e) {
      log(`<div class="warn-line">Resolve: ${esc(e.message)}</div>`);
    }
  }

  // ── 3. Narrate ──────────────────────────────────────────────
  const modeFrom = state.mode;
  // Only the backend decides mode transitions; we mirror the intent signal.
  if (intent.intent === 'enter_combat') setMode('combat');
  else if (['disengage', 'flee', 'end_combat'].includes(intent.intent)) setMode('exploration');

  try {
    const narrated = await apiFetch('/narrate', 'POST', {
      intent: intent.intent,
      mechanic: intent.mechanic,
      mode_from: modeFrom,
      mode_to: state.mode,
      system_text: 'You are the GM.',
      resolved_action: resolved,
    });
    log(`<div class="narration-block">` +
        `<div class="narration-label">Narration Prompt →</div>` +
        `${esc(narrated.prompt)}` +
        `</div>`);
  } catch (e) {
    log(`<div class="err-line">Narrate error: ${esc(e.message)}</div>`);
  }

  // ── 4. Advance encounter turn ───────────────────────────────
  advanceTurn();
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  $('submit-btn').addEventListener('click', submitAction);
  $('demo-btn').addEventListener('click', loadDemo);
  $('player-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submitAction();
  });
  renderActor();
  renderEncounter();
  renderResolution(null);
});
