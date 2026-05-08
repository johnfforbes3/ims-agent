/**
 * @file atlas-tab.js
 * @description IMS Command Center — Tab 3 (ATLAS Agent Control).
 *
 * Operational views for the agent operator:
 *
 *   - {@link loadDiff}               — "What Changed" single-cycle diff viewer
 *     (`/api/diff/{cycle}`).
 *   - {@link loadChanges}            — Cumulative diff across a cycle range
 *     (`/api/changes?from_cycle=…&to_cycle=…`) with CSV export link.
 *   - {@link loadBaselineDrift}      — Baseline drift table + horizontal bar
 *     chart of the top-10 most-slipped tasks (`/api/baseline-drift`).
 *   - {@link autoInitPanels}         — On DOM ready, pre-loads the most recent
 *     diff, the cumulative-diff table, and the baseline-drift table so each
 *     panel has data before the user opens it.
 *   - **Live Interview Listen-In** — SSE stream from `/api/interview-stream`
 *     plus a serialised audio playback queue.  Architecture:
 *       1. Fetch /api/interview-recent for transcript-only backfill (no
 *          audio prefetch — avoids browser freeze from 30 concurrent fetches).
 *       2. EventSource from `current_seq` for live turns (audio prefetch +
 *          natural conversational pause between turns).
 *
 * @module atlas-tab
 * @requires Chart escapeHtml _authHeaders _attachExportButtons
 */

let _baselineDriftChart = null;

/* ── Diff helper: render a table of change rows ──────────────────────────── */
function _renderDiffTable(changes) {
  if (!changes.length)
    return '<p class="empty">No field changes recorded for this cycle.</p>';
  return '<table><thead><tr>'
    + '<th>Task</th><th>CAM</th><th>Field</th><th>Old</th><th>New</th>'
    + '</tr></thead><tbody>'
    + changes.map(c =>
        `<tr><td style="color:#e6edf3;font-weight:500">${escapeHtml(c.task_name||c.task_id)}</td>`
      + `<td style="color:#7d8590">${escapeHtml(c.cam_name||'—')}</td>`
      + `<td>${escapeHtml(c.field)}</td>`
      + `<td style="color:#484f58">${escapeHtml(String(c.old_value??'—'))}</td>`
      + `<td style="color:#3fb950;font-weight:600">${escapeHtml(String(c.new_value??'—'))}</td></tr>`
      ).join('')
    + '</tbody></table>';
}

/* ── What Changed — single-cycle diff ────────────────────────────────────── */
async function loadDiff() {
  const cycleId   = document.getElementById('diff-cycle-input').value.trim();
  const status    = document.getElementById('diff-status');
  const container = document.getElementById('diff-table-container');
  const badge     = document.getElementById('diff-count-badge');
  if (!cycleId) { status.textContent = 'Enter a cycle ID.'; return; }
  status.textContent = 'Loading…';
  try {
    const data = await fetch(`/api/diff/${encodeURIComponent(cycleId)}`).then(r => r.json());
    if (data.error) {
      status.textContent = data.error;
      container.innerHTML = `<p class="empty">${escapeHtml(data.error)}</p>`;
      badge.style.display = 'none';
      return;
    }
    const changes = Array.isArray(data) ? data : (data.changes || []);
    status.textContent = `${changes.length} change(s) — cycle ${cycleId}`;
    badge.textContent  = changes.length;
    badge.style.display = changes.length ? '' : 'none';
    container.innerHTML = _renderDiffTable(changes);
  } catch (e) { status.textContent = 'Error: ' + e; }
}

/* ── Change History — cumulative diff across cycle range ─────────────────── */
async function loadChanges() {
  const from = document.getElementById('ch-from').value.trim();
  const to   = document.getElementById('ch-to').value.trim();
  const status    = document.getElementById('ch-status');
  const container = document.getElementById('ch-table-container');
  const csvLink   = document.getElementById('ch-csv-link');
  const badge     = document.getElementById('ch-count-badge');
  status.textContent = 'Loading…';
  let url = '/api/changes';
  const params = new URLSearchParams();
  if (from) params.set('from_cycle', from);
  if (to)   params.set('to_cycle', to);
  if ([...params].length) url += '?' + params;
  try {
    const data = await fetch(url).then(r => r.json());
    if (data.error) {
      status.textContent = data.error;
      container.innerHTML = `<p class="empty">${escapeHtml(data.error)}</p>`;
      badge.style.display = 'none';
      return;
    }
    const changes = data.changes || [];
    status.textContent = `${data.total_changes} net change(s) · ${data.from_cycle} → ${data.to_cycle}`;
    badge.textContent  = data.total_changes;
    badge.style.display = data.total_changes ? '' : 'none';
    csvLink.href = url + (url.includes('?') ? '&' : '?') + 'format=csv';
    csvLink.style.display = '';
    if (!changes.length) {
      container.innerHTML = '<p class="empty">No changes in range.</p>';
      return;
    }
    container.innerHTML = '<table><thead><tr>'
      + '<th>Task</th><th>CAM</th><th>Field</th><th>Old</th><th>New</th><th>Hops</th><th>Cycles</th>'
      + '</tr></thead><tbody>'
      + changes.map(c =>
          `<tr><td style="color:#e6edf3;font-weight:500">${escapeHtml(c.task_name||c.task_id)}</td>`
        + `<td style="color:#7d8590">${escapeHtml(c.cam_name||'—')}</td>`
        + `<td>${escapeHtml(c.field)}</td>`
        + `<td style="color:#484f58">${escapeHtml(String(c.old_value??'—'))}</td>`
        + `<td style="color:#3fb950;font-weight:600">${escapeHtml(String(c.new_value??'—'))}</td>`
        + `<td style="color:#7d8590">${c.hop_count}</td>`
        + `<td style="font-size:11px;color:#484f58">${escapeHtml((c.contributing_cycle_ids||[]).join(', '))}</td></tr>`
        ).join('')
      + '</tbody></table>';
  } catch (e) { status.textContent = 'Error: ' + e; }
}

/* ── Baseline Drift Report (table + horizontal bar chart of top slips) ───── */
async function loadBaselineDrift() {
  const status    = document.getElementById('bd-status');
  const container = document.getElementById('bd-table-container');
  const badge     = document.getElementById('bd-count-badge');
  status.textContent = 'Loading…';
  try {
    const data = await fetch('/api/baseline-drift').then(r => r.json());
    if (data.error) {
      const msg = data.error.includes('No baseline')
        ? 'No baseline snapshot yet — established after the first approved IMS write cycle.'
        : data.error;
      status.textContent = msg;
      container.innerHTML = `<p class="empty">${escapeHtml(msg)}</p>`;
      badge.style.display = 'none';
      return;
    }
    const drift    = data.task_drift || [];
    const baseline = data.baseline_cycle_id || '?';
    status.textContent = `Baseline: ${baseline} · ${drift.length} task(s) drifted`;
    badge.textContent  = drift.length;
    badge.style.display = drift.length ? '' : 'none';
    if (!drift.length) {
      container.innerHTML = '<p class="empty">No drift from baseline — all tasks within tolerance.</p>';
      return;
    }
    container.innerHTML = '<table><thead><tr>'
      + '<th>Task</th><th>CAM</th><th>Baseline Finish</th><th>Current Finish</th>'
      + '<th>Slip (days)</th><th>Δ%</th>'
      + '</tr></thead><tbody>'
      + drift.map(t => {
          const slip = t.finish_slip_days;
          const slipCol = slip >= 30 ? '#f85149' : slip >= 14 ? '#d29922' : '#c9d1d9';
          const pctCol  = (t.pct_delta||0) < 0 ? '#f85149' : '#3fb950';
          return `<tr>`
            + `<td style="color:#e6edf3;font-weight:500">${escapeHtml(t.name||t.task_id)}${t.is_milestone?' ⛳':''}</td>`
            + `<td style="color:#7d8590">${escapeHtml(t.cam||'—')}</td>`
            + `<td style="color:#484f58">${escapeHtml(t.baseline_finish||'—')}</td>`
            + `<td>${escapeHtml(t.current_finish||'—')}</td>`
            + `<td style="color:${slipCol};font-weight:700">${slip!=null?'+'+slip:'—'}</td>`
            + `<td style="color:${pctCol}">${(t.pct_delta||0)>0?'+':''}${t.pct_delta||0}%</td></tr>`;
        }).join('')
      + '</tbody></table>';

    // Top-10 slip horizontal bar chart
    const canvas = document.getElementById('baseline-drift-chart');
    if (canvas && drift.length) {
      const top10 = [...drift].sort((a, b) => (b.finish_slip_days || 0) - (a.finish_slip_days || 0)).slice(0, 10);
      if (_baselineDriftChart) _baselineDriftChart.destroy();
      _baselineDriftChart = new Chart(canvas, {
        type: 'bar',
        data: {
          labels: top10.map(t => (t.name || t.task_id || '').slice(0, 28)),
          datasets: [{
            label: 'Slip (days)',
            data: top10.map(t => t.finish_slip_days || 0),
            backgroundColor: top10.map(t => {
              const s = t.finish_slip_days || 0;
              return s >= 30 ? '#f85149' : s >= 14 ? '#d29922' : '#58a6ff';
            }),
            borderWidth: 0, borderRadius: 3,
          }],
        },
        options: {
          indexAxis: 'y',
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: '#161b22', titleColor: '#e6edf3', bodyColor: '#c9d1d9',
              borderColor: '#30363d', borderWidth: 1,
              callbacks: { label: ctx => `+${ctx.parsed.x} days` },
            },
          },
          scales: {
            x: { beginAtZero: true, grid: { color: '#21262d' }, border: { display: false }, ticks: { color: '#7d8590', font: { size: 10 } } },
            y: { grid: { display: false }, border: { display: false }, ticks: { color: '#7d8590', font: { size: 10 } } },
          },
        },
      });
    }
  } catch (e) { status.textContent = 'Error: ' + e; }
}

/* ── Auto-init the bottom panels ─────────────────────────────────────────── */
async function autoInitPanels() {
  // 1. Most-recent diff via /api/diff/latest
  try {
    const data = await fetch('/api/diff/latest').then(r => r.json());
    if (!data.error && data.cycle_id) {
      document.getElementById('diff-cycle-input').value = data.cycle_id;
      const changes = data.changes || [];
      const status  = document.getElementById('diff-status');
      const badge   = document.getElementById('diff-count-badge');
      status.textContent = `${changes.length} change(s) — cycle ${data.cycle_id}`;
      badge.textContent  = changes.length;
      badge.style.display = changes.length ? '' : 'none';
      document.getElementById('diff-table-container').innerHTML = _renderDiffTable(changes);
      if (changes.length) document.getElementById('what-changed-panel').open = true;
    }
  } catch (_) {}

  try {
    await loadChanges();
    const chBadge = document.getElementById('ch-count-badge');
    if (chBadge && chBadge.textContent && parseInt(chBadge.textContent) > 0)
      document.getElementById('change-history-panel').open = true;
  } catch (_) {}

  try {
    await loadBaselineDrift();
    const bdBadge = document.getElementById('bd-count-badge');
    if (bdBadge && bdBadge.style.display !== 'none')
      document.getElementById('baseline-drift-panel').open = true;
  } catch (_) {}
}

/* ============================================================================
 * Live Interview Listen-In (SSE + audio queue)
 * ============================================================================ */

let _listenEvt    = null;
let _listenSeq    = 0;
let _currentAudio = null;
let _audioPlaying = false;
let _audioQueue   = [];
let _seenEventIds = new Set();
let _knownCams    = new Map();
const _audioPending = new Map();

function _selectedCam() {
  return document.getElementById('listenin-cam-select')?.value || 'all';
}

function listenInFilterChange() {
  const sel = _selectedCam();
  document.querySelectorAll('#listenin-transcript .listenin-turn').forEach(el => {
    const email = el.dataset.camEmail || '';
    el.style.display = (sel === 'all' || email === sel) ? '' : 'none';
  });
  if (sel !== 'all' && _currentAudio) {
    const playing = document.querySelector('#listenin-transcript .listenin-turn.playing');
    if (playing && playing.dataset.camEmail !== sel) {
      _currentAudio.pause();
    }
  }
}

function _prefetch(event_id) {
  if (_audioPending.has(event_id)) return _audioPending.get(event_id);
  const p = (async () => {
    for (let i = 0; i < 30; i++) {
      try {
        const r = await fetch(`/api/interview-audio/${encodeURIComponent(event_id)}`);
        if (r.ok) return r.blob();
      } catch (_) {}
      if (i < 29) await new Promise(res => setTimeout(res, 300));
    }
    return null;
  })();
  _audioPending.set(event_id, p);
  return p;
}

function _showSpeaking(name, speaker) {
  const row = document.getElementById('listenin-speaking-row');
  if (!row) return;
  document.getElementById('speaking-name').textContent = name;
  row.classList.toggle('cam-speaking', speaker === 'cam');
  row.classList.add('visible');
}
function _hideSpeaking() {
  const row = document.getElementById('listenin-speaking-row');
  if (row) row.classList.remove('visible');
}

async function _drainAudioQueue() {
  if (_audioPlaying || !_audioQueue.length) return;
  _audioPlaying = true;

  while (_audioQueue.length) {
    const { event_id, cam_name, speaker, cam_email } = _audioQueue.shift();
    const sel = _selectedCam();
    if (sel !== 'all' && cam_email && cam_email !== sel) {
      _audioPending.delete(event_id);
      continue;
    }
    const displayName = speaker === 'bot' ? 'ATLAS' : cam_name;

    _showSpeaking(displayName, speaker);
    const turnEl = document.querySelector(`[data-event-id="${event_id}"]`);
    if (turnEl) turnEl.classList.add('playing');

    const blob = await (_audioPending.get(event_id) || _prefetch(event_id));
    _audioPending.delete(event_id);

    if (blob) {
      const vol = parseFloat(document.getElementById('listenin-volume')?.value ?? 0.85);
      await new Promise(resolve => {
        const url   = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.volume = Math.max(0, Math.min(1, vol));
        _currentAudio = audio;
        audio.onended = () => { URL.revokeObjectURL(url); _currentAudio = null; resolve(); };
        audio.onerror = () => { URL.revokeObjectURL(url); resolve(); };
        audio.play().catch(() => resolve());
      });
    }

    if (turnEl) turnEl.classList.remove('playing');
    await new Promise(r => setTimeout(r, 380));
  }

  _hideSpeaking();
  _audioPlaying = false;
}

function _appendTurn(ev, { live = true } = {}) {
  if (_seenEventIds.has(ev.event_id)) return;
  _seenEventIds.add(ev.event_id);

  const camEmail = (ev.cam_email || '').toLowerCase();
  const camName  = ev.cam_name || ev.cam_email || '';

  if (camEmail && !_knownCams.has(camEmail)) {
    _knownCams.set(camEmail, camName);
    const sel = document.getElementById('listenin-cam-select');
    if (sel) {
      const opt = document.createElement('option');
      opt.value       = camEmail;
      opt.textContent = camName;
      sel.appendChild(opt);
    }
  }

  const selectedCam = _selectedCam();
  const visible = selectedCam === 'all' || !camEmail || camEmail === selectedCam;

  const box = document.getElementById('listenin-transcript');
  const empty = document.getElementById('listenin-empty');
  if (empty) empty.remove();

  const isBot = ev.speaker === 'bot';
  const label = isBot ? 'ATLAS' : escapeHtml(camName);
  const ts    = new Date(ev.timestamp * 1000)
                  .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  const turn = document.createElement('div');
  turn.className = `listenin-turn ${ev.speaker}${live ? '' : ' historical'}`;
  turn.dataset.eventId  = ev.event_id;
  turn.dataset.camEmail = camEmail;
  if (!visible) turn.style.display = 'none';
  turn.innerHTML = `
    <div class="listenin-bubble">${escapeHtml(ev.text)}</div>
    <div class="listenin-meta">${label} · ${ts}${live ? '' : ' <span class="hist-badge">history</span>'}</div>`;
  box.appendChild(turn);
  if (visible) box.scrollTop = box.scrollHeight;

  if (live) {
    _prefetch(ev.event_id);
    if (document.getElementById('listenin-autoplay').checked) {
      _audioQueue.push({ event_id: ev.event_id, cam_name: camName, speaker: ev.speaker, cam_email: camEmail });
      _drainAudioQueue();
    }
  }
}

async function listenInConnect() {
  if (_listenEvt) { _listenEvt.close(); _listenEvt = null; }

  document.getElementById('listenin-connect-btn').style.display    = 'none';
  document.getElementById('listenin-disconnect-btn').style.display = '';
  _setListenStatus('Loading history…');

  let startSeq = _listenSeq;
  try {
    const resp = await fetch('/api/interview-recent?n=30');
    if (resp.ok) {
      const { seq, events } = await resp.json();
      if (_listenSeq === 0 && events.length) {
        events.forEach(ev => _appendTurn(ev, { live: false }));
      }
      startSeq = Math.max(startSeq, seq);
      _listenSeq = startSeq;
    }
  } catch (_) {}

  _setListenStatus('Connecting…');
  const url = `/api/interview-stream?since=${_listenSeq}`;
  _listenEvt = new EventSource(url);

  _listenEvt.onopen = () => {
    _setListenStatus('🟢 Connected — listening live');
    document.getElementById('listenin-panel').open = true;
  };

  _listenEvt.onmessage = e => {
    try {
      const ev = JSON.parse(e.data);
      _listenSeq = Math.max(_listenSeq, (ev.seq || 0) + 1);
      _appendTurn(ev, { live: true });
    } catch (_) {}
  };

  _listenEvt.onerror = () => { _setListenStatus('⚠️ Reconnecting…'); };
}

function listenInDisconnect() {
  if (_listenEvt) { _listenEvt.close(); _listenEvt = null; }
  document.getElementById('listenin-connect-btn').style.display    = '';
  document.getElementById('listenin-disconnect-btn').style.display = 'none';
  if (_currentAudio) { _currentAudio.pause(); _currentAudio = null; }
  _hideSpeaking();
  _setListenStatus('Disconnected');
}

function listenInClear() {
  document.getElementById('listenin-transcript').innerHTML =
    `<div class="listenin-empty" id="listenin-empty">Transcript cleared — waiting for next turn…</div>`;
  _audioQueue = [];
  _audioPending.clear();
  _seenEventIds.clear();
  _knownCams.clear();
  const sel = document.getElementById('listenin-cam-select');
  if (sel) {
    while (sel.options.length > 1) sel.remove(1);
    sel.value = 'all';
  }
}

function _setListenStatus(msg) {
  const el = document.getElementById('listenin-status');
  if (el) el.textContent = msg;
}

function _refreshListeninSessions() {
  fetch('/api/interview-sessions')
    .then(r => r.json())
    .then(sessions => {
      const c = document.getElementById('listenin-sessions');
      const b = document.getElementById('listenin-session-badge');
      if (!c || !b) return;
      if (!sessions.length) {
        c.innerHTML = `<span class="listenin-session-pill idle">
          <span class="live-dot"></span>No active interviews</span>`;
        b.style.display = 'none';
        return;
      }
      b.textContent   = sessions.length;
      b.style.display = '';
      c.innerHTML = sessions.map(s =>
        `<span class="listenin-session-pill">
          <span class="live-dot"></span>${escapeHtml(s.cam_name || s.cam_email)}
        </span>`
      ).join('');
    })
    .catch(() => {});
}

/* ── DOM ready: panel auto-init + session polling + auto-connect on open ── */
document.addEventListener('DOMContentLoaded', () => {
  autoInitPanels();
  _refreshListeninSessions();
  setInterval(_refreshListeninSessions, 5000);

  const panel = document.getElementById('listenin-panel');
  if (panel) {
    panel.addEventListener('toggle', e => {
      if (e.target.open && !_listenEvt) listenInConnect();
    });
  }
});

/* Re-trigger panel init when ATLAS tab is activated */
document.addEventListener('tab:activated', e => {
  if (e.detail.tab === 'atlas') {
    if (typeof Chart !== 'undefined') {
      loadBaselineDrift().then(() => _attachExportButtons());
    }
  }
});
