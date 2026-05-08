/**
 * @file dashboard-core.js
 * @description IMS Command Center — Core JavaScript module.
 *
 * Loaded on every page; tab-specific modules (metrics-tab.js, pm-tab.js,
 * atlas-tab.js) layer on top.  This file owns:
 *
 *   - HTML escape helper (used by every renderer)
 *   - Authenticated fetch headers (`_authHeaders`)
 *   - Status / state polling with adaptive cadence (60 s idle, 5 s active cycle)
 *   - Cycle progress card live update from /api/state
 *   - Manual cycle trigger button handler (`triggerCycle`)
 *   - Tab navigation: hash routing (#/metrics, #/pm, #/atlas) + keyboard
 *     shortcuts (Ctrl/Cmd+1/2/3) — Phase 12 / TIER 2F
 *   - Q&A chat widget with sessionStorage persistence (Phase 4)
 *   - Chart export to PNG (`exportChart`) — Phase 12 / TIER 2G
 *   - Light/dark theme toggle with localStorage persistence — Phase 12 / TIER 3
 *
 * @module dashboard-core
 * @see /static/js/metrics-tab.js
 * @see /static/js/pm-tab.js
 * @see /static/js/atlas-tab.js
 */

/* ========================================================================
 * HTML escape helper
 * ======================================================================== */

/**
 * Escape a string for safe HTML insertion.
 * Newlines become `<br>` so multi-line text renders naturally.
 * @param {*} str Anything stringable.
 * @returns {string} HTML-escaped output.
 */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>');
}

/* ========================================================================
 * Auth headers
 * ======================================================================== */

/**
 * Return Authorization headers if an API key is present in window.__IMS.
 * Server injects the key into the page; tab modules pass these into fetch().
 * @returns {Object} Header dict (empty when no key set).
 */
function _authHeaders() {
  const key = (window.__IMS && window.__IMS.api_key) || '';
  return key ? { 'X-API-Key': key } : {};
}

/* ========================================================================
 * Polling & countdown
 * ======================================================================== */

const countdownEl = document.getElementById('countdown');
let _pollMs     = 60000;            // 60 s when idle
let _nextPollAt = Date.now() + _pollMs;
let _wasActive  = false;
let _polling    = false;

/** Map a CAM live-status enum to a status-cell HTML fragment. */
const _statusHtml = {
  complete:  '<span class="dot dot-ok"></span>Responded',
  no_answer: '<span class="dot dot-miss"></span>No Response',
  pending:   '<span class="dot dot-pend"></span>Interviewing…',
};

/**
 * Update the Cycle In Progress card from a freshly-fetched state object.
 * Hides the card entirely when no cycle is in flight.
 * @param {Object} state Full /api/state response.
 */
function _updateCycleCard(state) {
  const cur   = state.current_cycle || {};
  const phase = (cur.phase || '').toLowerCase();
  const card  = document.getElementById('cycle-progress-card');
  if (!card) return;

  if (phase && phase !== 'complete' && phase !== 'failed') {
    document.getElementById('cp-phase').textContent = phase.toUpperCase();
    document.getElementById('cp-cycle').textContent = cur.cycle_id || '—';
    document.getElementById('cp-cams').textContent  =
      (cur.cams_responded || 0) + '/' + (cur.cams_total || 0);
    card.style.display = '';

    const camLive = cur.cam_status_live;
    if (camLive && typeof camLive === 'object') {
      const table = document.getElementById('cam-status-table');
      if (table && table.tBodies[0]) {
        for (const row of table.tBodies[0].rows) {
          const camName = row.dataset.cam || '';
          if (!camName) continue;
          const liveStatus = camLive[camName];
          if (!liveStatus) continue;
          const cell = row.querySelector('.cam-status-cell');
          if (cell) cell.innerHTML = _statusHtml[liveStatus] || cell.innerHTML;
        }
      }
      const pills = Object.entries(camLive).map(([name, st]) => {
        const icon = st === 'complete' ? '✓' : st === 'no_answer' ? '✗' : '⏳';
        const col  = st === 'complete' ? '#3fb950' : st === 'no_answer' ? '#f85149' : '#d29922';
        return `<span style="border:1px solid ${col};color:${col};border-radius:20px;`
             + `padding:2px 11px;margin:2px;display:inline-block;font-size:12px">${icon} ${name}</span>`;
      }).join(' ');
      const prog = document.getElementById('cp-cam-progress');
      if (prog) prog.innerHTML = pills;
    }
  } else {
    card.style.display = 'none';
  }
}

/**
 * Single poll round — checks /api/status; if a cycle is active, fetches
 * /api/state and updates the live progress card.  When a cycle completes
 * (was active, now isn't), do a full reload so the page re-renders all
 * server-side templated regions.
 */
async function _poll() {
  if (_polling) return;
  _polling = true;
  try {
    const status = await fetch('/api/status').then(r => r.json());
    const active = !!status.cycle_active;
    if (_wasActive && !active) { window.location.reload(); return; }
    _wasActive = active;
    _pollMs    = active ? 5000 : 60000;
    if (active) {
      const state = await fetch('/api/state').then(r => r.json());
      _updateCycleCard(state);
    }
  } catch (_) { _pollMs = 10000; }
  finally     { _polling = false; }
  _nextPollAt = Date.now() + _pollMs;
}

setInterval(() => {
  const rem = Math.max(0, Math.ceil((_nextPollAt - Date.now()) / 1000));
  if (countdownEl) countdownEl.textContent = rem;
  if (!_polling && Date.now() >= _nextPollAt) _poll();
}, 1000);
_poll();

/* ========================================================================
 * Manual cycle trigger
 * ======================================================================== */

/**
 * Click handler for the prominent "▶ Trigger Cycle" button in the header.
 * POSTs /api/trigger?force=true and reloads after the response lands.
 */
function triggerCycle() {
  const btn = document.getElementById('trigger-btn');
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = '⏳ Starting…';
  fetch('/api/trigger?force=true', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      btn.textContent = data.status === 'triggered' ? '✓ Cycle Started' : '✗ Error';
      setTimeout(() => window.location.reload(), 2000);
    })
    .catch(() => { btn.textContent = '✗ Error — check logs'; btn.disabled = false; });
}

/* ========================================================================
 * Tab Navigation — hash routing + keyboard shortcuts (Phase 12 / TIER 2F)
 * ======================================================================== */

const TAB_ORDER = ['metrics', 'pm', 'atlas'];
const DEFAULT_TAB = 'metrics';

/**
 * Show only the requested tab; emit `tab:activated` so tab modules can
 * lazy-init charts on first show.
 * @param {string} tabId One of TAB_ORDER (metrics | pm | atlas).
 */
function _activateTab(tabId) {
  if (!TAB_ORDER.includes(tabId)) tabId = DEFAULT_TAB;
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-panel').forEach(panel => {
    panel.classList.toggle('active', panel.dataset.tab === tabId);
  });
  document.dispatchEvent(new CustomEvent('tab:activated', { detail: { tab: tabId } }));
}

/**
 * Public tab switcher — updates the URL hash; the hashchange listener
 * actually swaps panels.  Use this from button onclick or keyboard handler.
 * @param {string} tabId One of TAB_ORDER.
 */
function switchTab(tabId) {
  window.location.hash = '#/' + tabId;
}

/** @returns {string} Current tab from URL hash, or DEFAULT_TAB. */
function _tabFromHash() {
  const m = (window.location.hash || '').match(/^#\/(\w+)$/);
  return m ? m[1] : DEFAULT_TAB;
}

window.addEventListener('hashchange', () => _activateTab(_tabFromHash()));

/**
 * Global keyboard shortcuts:
 *   Ctrl/Cmd + 1  → IMS Metrics & Indicators tab
 *   Ctrl/Cmd + 2  → PM Dashboard tab
 *   Ctrl/Cmd + 3  → ATLAS Agent Control tab
 *   Ctrl/Cmd + L  → Toggle light/dark theme
 */
document.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  // Ignore if user is typing in an input/textarea
  const tag = (e.target && e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
  if (e.key === '1') { e.preventDefault(); switchTab('metrics'); }
  else if (e.key === '2') { e.preventDefault(); switchTab('pm'); }
  else if (e.key === '3') { e.preventDefault(); switchTab('atlas'); }
  else if (e.key === 'l' || e.key === 'L') { e.preventDefault(); toggleTheme(); }
});

/* ========================================================================
 * Light/Dark theme toggle (Phase 12 / TIER 3, redesigned in Phase 13)
 * ======================================================================== */

const THEME_KEY = 'ims_theme';

/**
 * Apply a theme by setting `data-theme` on the <html> element.  Light is the
 * Phase 13 default; dark is the alternate (preserves the original palette).
 * Also syncs the segmented light/dark control in the sidebar footer.
 * @param {'dark' | 'light'} theme
 */
function _applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btnLight = document.getElementById('theme-light');
  const btnDark  = document.getElementById('theme-dark');
  if (btnLight) btnLight.classList.toggle('active', theme === 'light');
  if (btnDark)  btnDark.classList.toggle('active',  theme === 'dark');
  // Legacy single-button toggle kept hidden for Phase 12 test compatibility.
  const single = document.getElementById('theme-toggle');
  if (single) single.textContent = theme === 'light' ? '🌙' : '☀';
}

/**
 * Set the theme to a specific value and persist to localStorage.
 * Wired to the segmented sun/moon buttons in the sidebar footer.
 * @param {'dark' | 'light'} theme
 */
function setTheme(theme) {
  _applyTheme(theme);
  try { localStorage.setItem(THEME_KEY, theme); } catch (_) {}
}

/**
 * Cycle the theme light ↔ dark.  Persists to localStorage.
 * Also bound to Ctrl/Cmd+L.
 */
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  setTheme(current === 'dark' ? 'light' : 'dark');
}

/** Restore persisted theme on page load (Phase 13 default = 'light'). */
function _restoreTheme() {
  let saved = 'light';
  try { saved = localStorage.getItem(THEME_KEY) || 'light'; } catch (_) {}
  _applyTheme(saved);
}

/* ========================================================================
 * Chart export to PNG (Phase 12 / TIER 2G)
 * ======================================================================== */

/**
 * Download a Chart.js chart as a PNG file.  Bound to the small ⬇ button
 * each tab module places on the chart container.
 *
 * @param {string} canvasId DOM id of the <canvas> element rendering the chart.
 * @param {string} [filename] Suggested download filename (without extension).
 */
function exportChart(canvasId, filename) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  let dataUrl;
  // Prefer Chart.js's helper which respects retina + background — falls back
  // to canvas.toDataURL when Chart isn't yet attached.
  if (window.Chart && typeof Chart.getChart === 'function') {
    const c = Chart.getChart(canvas);
    if (c && typeof c.toBase64Image === 'function') {
      dataUrl = c.toBase64Image('image/png', 1.0);
    }
  }
  if (!dataUrl) dataUrl = canvas.toDataURL('image/png');
  const a = document.createElement('a');
  a.href = dataUrl;
  a.download = (filename || canvasId) + '.png';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/**
 * Idempotently inject a tiny 📥 export button into every chart container.
 * Tab modules call `_attachExportButtons()` after Chart.js mounts so each
 * chart picks up an export action.  Re-running the function is safe.
 */
function _attachExportButtons() {
  document.querySelectorAll('.chart-container canvas[id]').forEach(canvas => {
    const container = canvas.closest('.chart-container');
    if (!container || container.querySelector('.chart-export-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'chart-export-btn';
    btn.title = 'Download chart as PNG';
    btn.textContent = '📥';
    btn.onclick = () => exportChart(canvas.id, canvas.id);
    container.appendChild(btn);
  });
}

/* ========================================================================
 * Q&A Chat widget with sessionStorage persistence (Phase 4)
 * ======================================================================== */

const CHAT_KEY = 'ims_chat_history';

/** @returns {Array<Object>} Persisted chat history (or []). */
function _loadHistory() {
  try { return JSON.parse(sessionStorage.getItem(CHAT_KEY) || '[]'); }
  catch { return []; }
}

/** Persist current rendered chat to sessionStorage so it survives reloads. */
function _saveHistory() {
  const msgs = document.getElementById('chat-messages');
  if (!msgs) return;
  const entries = [];
  for (const el of msgs.children) {
    const role = el.dataset.role;
    if (!role) continue;
    const bubble = el.querySelector('.chat-bubble');
    if (!bubble || bubble.classList.contains('thinking')) continue;
    const source = el.querySelector('.chat-source');
    entries.push({ role, html: bubble.innerHTML, source: source ? source.textContent : '' });
  }
  try { sessionStorage.setItem(CHAT_KEY, JSON.stringify(entries)); }
  catch { /* storage quota exceeded */ }
}

/** Re-hydrate the chat widget from sessionStorage on initial load. */
function _restoreHistory() {
  const history = _loadHistory();
  if (!history.length) return;
  const msgs = document.getElementById('chat-messages');
  if (!msgs) return;
  msgs.innerHTML = '';
  for (const { role, html, source } of history) {
    const el = document.createElement('div');
    el.className = `chat-msg ${role}`;
    el.dataset.role = role;
    el.innerHTML = `<div class="chat-bubble">${html}</div>`
      + (source ? `<div class="chat-source">${escapeHtml(source)}</div>` : '');
    msgs.appendChild(el);
  }
  msgs.scrollTop = msgs.scrollHeight;
}

/** Reset the chat to its empty greeting. */
function clearChat() {
  sessionStorage.removeItem(CHAT_KEY);
  const msgs = document.getElementById('chat-messages');
  if (!msgs) return;
  msgs.innerHTML = `<div class="chat-msg assistant">
    <div class="chat-bubble">Ask me anything about the schedule — critical path, milestone risk, CAM status, blockers, or recommended actions.</div>
  </div>`;
}

/**
 * Convenience for the suggestion chips — paste the chip text into the input
 * and immediately submit.
 * @param {string} q Question text.
 */
function askQuestion(q) {
  const inp = document.getElementById('chat-input');
  if (inp) inp.value = q;
  sendChat();
}

/** Submit the current chat input to /api/ask and render the response. */
function sendChat() {
  const input    = document.getElementById('chat-input');
  const btn      = document.getElementById('chat-send-btn');
  if (!input || !btn) return;
  const question = input.value.trim();
  if (!question) return;

  const messages = document.getElementById('chat-messages');
  const userMsg  = document.createElement('div');
  userMsg.className   = 'chat-msg user';
  userMsg.dataset.role = 'user';
  userMsg.innerHTML   = `<div class="chat-bubble">${escapeHtml(question)}</div>`;
  messages.appendChild(userMsg);

  const thinkingMsg = document.createElement('div');
  thinkingMsg.className = 'chat-msg assistant';
  thinkingMsg.innerHTML = `<div class="chat-bubble thinking">Thinking…</div>`;
  messages.appendChild(thinkingMsg);
  messages.scrollTop = messages.scrollHeight;

  input.value  = '';
  input.disabled = true;
  btn.disabled   = true;

  fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
    .then(r => r.json())
    .then(data => {
      thinkingMsg.dataset.role = 'assistant';
      thinkingMsg.innerHTML = `
        <div class="chat-bubble">${escapeHtml(data.answer || data.detail || 'No answer returned.')}</div>
        ${data.source_cycle ? `<div class="chat-source">Source: cycle ${data.source_cycle}</div>` : ''}
      `;
      _saveHistory();
    })
    .catch(err => {
      thinkingMsg.innerHTML = `<div class="chat-bubble" style="color:#f85149">Error: ${escapeHtml(String(err))}</div>`;
    })
    .finally(() => {
      input.disabled = false;
      btn.disabled   = false;
      input.focus();
      messages.scrollTop = messages.scrollHeight;
    });
}

/* ========================================================================
 * DOM-ready bootstrap
 * ======================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  _restoreTheme();
  _activateTab(_tabFromHash());
  _restoreHistory();
});
