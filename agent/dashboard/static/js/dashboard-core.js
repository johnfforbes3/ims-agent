/* ============================================================================
 * IMS Command Center — Core JS
 * ============================================================================
 * Shared utilities: polling, manual trigger, escapeHtml, _authHeaders,
 * tab navigation (hash routing), Q&A chat widget with sessionStorage
 * persistence.  Loaded on every page; tab-specific JS modules layer on top.
 * ============================================================================ */

/* ── HTML escape helper (used by every renderer) ─────────────────────────── */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>');
}

/* ── Auth headers (placeholder — server injects api_key into window.__IMS) ── */
function _authHeaders() {
  const key = (window.__IMS && window.__IMS.api_key) || '';
  return key ? { 'X-API-Key': key } : {};
}

/* ── Polling & countdown ─────────────────────────────────────────────────── */
const countdownEl = document.getElementById('countdown');
let _pollMs     = 60000;
let _nextPollAt = Date.now() + _pollMs;
let _wasActive  = false;
let _polling    = false;

const _statusHtml = {
  complete:  '<span class="dot dot-ok"></span>Responded',
  no_answer: '<span class="dot dot-miss"></span>No Response',
  pending:   '<span class="dot dot-pend"></span>Interviewing…',
};

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

/* ── Manual cycle trigger ────────────────────────────────────────────────── */
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

/* ── Tab Navigation (hash routing: #/metrics, #/pm, #/atlas) ─────────────── */
const TAB_ORDER = ['metrics', 'pm', 'atlas'];
const DEFAULT_TAB = 'metrics';

function _activateTab(tabId) {
  if (!TAB_ORDER.includes(tabId)) tabId = DEFAULT_TAB;
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-panel').forEach(panel => {
    panel.classList.toggle('active', panel.dataset.tab === tabId);
  });
  // Notify tab modules so they can lazy-init charts on first show
  document.dispatchEvent(new CustomEvent('tab:activated', { detail: { tab: tabId } }));
}

function switchTab(tabId) {
  window.location.hash = '#/' + tabId;
}

function _tabFromHash() {
  const m = (window.location.hash || '').match(/^#\/(\w+)$/);
  return m ? m[1] : DEFAULT_TAB;
}

window.addEventListener('hashchange', () => _activateTab(_tabFromHash()));

/* ── Q&A Chat with sessionStorage persistence ────────────────────────────── */
const CHAT_KEY = 'ims_chat_history';

function _loadHistory() {
  try { return JSON.parse(sessionStorage.getItem(CHAT_KEY) || '[]'); }
  catch { return []; }
}
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
  catch { /* quota */ }
}
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
function clearChat() {
  sessionStorage.removeItem(CHAT_KEY);
  const msgs = document.getElementById('chat-messages');
  if (!msgs) return;
  msgs.innerHTML = `<div class="chat-msg assistant">
    <div class="chat-bubble">Ask me anything about the schedule — critical path, milestone risk, CAM status, blockers, or recommended actions.</div>
  </div>`;
}

function askQuestion(q) {
  const inp = document.getElementById('chat-input');
  if (inp) inp.value = q;
  sendChat();
}

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

/* ── DOM ready: activate tab from hash, restore chat history ─────────────── */
document.addEventListener('DOMContentLoaded', () => {
  _activateTab(_tabFromHash());
  _restoreHistory();
});
