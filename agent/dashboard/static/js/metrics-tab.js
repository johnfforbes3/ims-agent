/**
 * @file metrics-tab.js
 * @description IMS Command Center — Tab 1 (IMS Metrics & Indicators).
 *
 * Owns the loaders + Chart.js renderers for the IMS Metrics tab:
 *
 *   - {@link loadEvm}                — Earned Value Metrics (current cycle)
 *     plus the 4 rolling 24-cycle sparklines (SPI/CPI/BEI/SV) backed by
 *     `/api/evm/history`.
 *   - {@link loadDcma}               — DCMA 14-Point Assessment scorecard +
 *     violations bar chart.
 *   - {@link _renderMilestoneDonut}  — Milestone risk distribution donut
 *     (HIGH/MEDIUM/LOW) sourced from server-injected `window.__IMS.milestones`.
 *
 * All chart instances are tracked in module-local maps (`_evmCharts`, etc.)
 * so subsequent refreshes destroy + re-create cleanly, preventing memory
 * leaks when the user clicks "Refresh" or switches tabs.
 *
 * Charts auto-render via the `tab:activated` event dispatched by
 * dashboard-core.js when the user navigates to the metrics tab.
 *
 * @module metrics-tab
 * @requires Chart (vendored at /static/vendor/chart.umd.min.js)
 * @requires escapeHtml _authHeaders _attachExportButtons (from dashboard-core)
 */

let _evmCharts = {};   // chart-id -> Chart instance (so we can destroy/refresh)
let _dcmaChart = null;
let _milestoneDonut = null;

/* ── Common chart options (dark theme tuned for our palette) ─────────────── */
const _chartFontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", sans-serif';
const _gridColor = '#21262d';
const _tickColor = '#7d8590';
const _axisColor = '#484f58';

function _sparklineOptions(yMin, yMax, healthBands) {
  const opts = {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#161b22', titleColor: '#e6edf3', bodyColor: '#c9d1d9',
        borderColor: '#30363d', borderWidth: 1, padding: 8,
        titleFont: { family: _chartFontFamily, size: 11 },
        bodyFont:  { family: _chartFontFamily, size: 11 },
      },
    },
    scales: {
      x: {
        grid: { display: false }, border: { display: false },
        ticks: { color: _tickColor, font: { family: _chartFontFamily, size: 9 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 },
      },
      y: {
        min: yMin, max: yMax,
        grid: { color: _gridColor, drawBorder: false },
        border: { display: false },
        ticks: { color: _tickColor, font: { family: _chartFontFamily, size: 10 } },
      },
    },
    elements: {
      line:  { borderWidth: 2, tension: 0.25 },
      point: { radius: 0, hoverRadius: 4 },
    },
  };
  if (healthBands) {
    // Add background plugin annotation later if needed
  }
  return opts;
}

/* ── EVM (current cycle KPIs + 24-pt rolling sparklines) ─────────────────── */
async function loadEvm() {
  const status  = document.getElementById('evm-status');
  const cardsEl = document.getElementById('evm-program-cards');
  const tableEl = document.getElementById('evm-cam-table');
  const badge   = document.getElementById('evm-health-badge');
  if (status) status.textContent = 'Loading…';
  try {
    const r = await fetch('/api/evm', { headers: _authHeaders() });
    if (!r.ok) { if (status) status.textContent = 'No EVM data yet.'; return; }
    const data = await r.json();
    const prog = data.program || {};

    // Health badge
    const health = prog.health || 'UNKNOWN';
    if (badge) { badge.textContent = health; badge.style.display = ''; badge.className = 'panel-badge health-' + health.toLowerCase(); }

    // KPI cards — current values
    const kpis = [
      ['SPI', prog.spi != null ? prog.spi.toFixed(3) : 'N/A', prog.spi < 0.85 ? 'red' : prog.spi < 0.95 ? 'yellow' : 'green'],
      ['SV', prog.sv != null ? prog.sv.toFixed(1) + 'd' : 'N/A', prog.sv < 0 ? 'red' : 'green'],
      ['Completion', prog.completion_pct != null ? prog.completion_pct.toFixed(1) + '%' : 'N/A', 'neutral'],
      ['BEI', prog.bei != null ? prog.bei.toFixed(3) : 'N/A', prog.bei < 0.85 ? 'red' : prog.bei < 0.95 ? 'yellow' : 'green'],
      ['BAC', prog.bac != null ? prog.bac.toFixed(1) + 'd' : 'N/A', 'neutral'],
      ['EAC', prog.eac != null ? prog.eac.toFixed(1) + 'd' : 'N/A', 'neutral'],
      ['VAC', prog.vac != null ? prog.vac.toFixed(1) + 'd' : 'N/A', prog.vac < 0 ? 'red' : 'green'],
      ['BCWP', prog.bcwp != null ? prog.bcwp.toFixed(1) + 'd' : 'N/A', 'neutral'],
    ];
    if (cardsEl) cardsEl.innerHTML = kpis.map(([lbl, val, col]) =>
      `<div style="background:#161b22;border:1px solid #21262d;border-radius:6px;padding:10px;text-align:center;">
        <div style="font-size:20px;font-weight:800;color:${col==='red'?'#f85149':col==='yellow'?'#d29922':col==='green'?'#3fb950':'#58a6ff'}">${escapeHtml(val)}</div>
        <div style="font-size:10px;color:#7d8590;text-transform:uppercase;letter-spacing:0.5px;margin-top:2px">${escapeHtml(lbl)}</div>
      </div>`).join('');

    // CAM breakdown table
    const byCam = data.by_cam || {};
    const camRows = Object.entries(byCam).sort((a,b) => (a[1].spi||99) - (b[1].spi||99));
    if (tableEl && camRows.length) {
      tableEl.innerHTML = '<table style="width:100%;border-collapse:collapse;font-size:12px;">' +
        '<tr style="background:#21262d;">' +
        '<th style="padding:6px 8px;text-align:left;">CAM</th>' +
        '<th>BAC (d)</th><th>BCWP</th><th>BCWS</th><th>SPI</th><th>SV (d)</th><th>% Done</th><th>Health</th></tr>' +
        camRows.map(([cam, d]) => {
          const hcol = d.health==='RED'?'#f85149':d.health==='YELLOW'?'#d29922':'#3fb950';
          return `<tr style="border-bottom:1px solid #21262d;">
            <td style="padding:5px 8px;"><strong>${escapeHtml(cam)}</strong></td>
            <td style="padding:5px 8px;text-align:right;">${(d.bac||0).toFixed(1)}</td>
            <td style="padding:5px 8px;text-align:right;">${(d.bcwp||0).toFixed(1)}</td>
            <td style="padding:5px 8px;text-align:right;">${(d.bcws||0).toFixed(1)}</td>
            <td style="padding:5px 8px;text-align:right;color:${hcol}">${d.spi!=null?d.spi.toFixed(3):'N/A'}</td>
            <td style="padding:5px 8px;text-align:right;">${(d.sv||0).toFixed(1)}</td>
            <td style="padding:5px 8px;text-align:right;">${(d.completion_pct||0).toFixed(1)}%</td>
            <td style="padding:5px 8px;color:${hcol};font-weight:700;">${escapeHtml(d.health||'')}</td>
          </tr>`;
        }).join('') + '</table>';
    }
    if (status) status.textContent = `Updated ${new Date().toLocaleTimeString()}`;

    // Render rolling 24-pt sparklines
    await _renderEvmSparklines();
  } catch(e) {
    if (status) status.textContent = 'Error loading EVM data.';
  }
}

async function _renderEvmSparklines() {
  const container = document.getElementById('evm-sparklines');
  if (!container) return;
  try {
    const r = await fetch('/api/evm/history?n=24', { headers: _authHeaders() });
    if (!r.ok) return;
    const data = await r.json();
    const history = data.history || [];
    if (!history.length) {
      container.innerHTML = '<p class="empty">No EVM history yet — needs 2+ completed cycles.</p>';
      return;
    }

    const labels = history.map(h => (h.timestamp || '').slice(5, 16).replace('T', ' '));
    const metrics = [
      { id: 'spark-spi',  label: 'SPI Trend',  field: 'spi',  color: '#58a6ff', yMin: 0.5, yMax: 1.2 },
      { id: 'spark-cpi',  label: 'CPI Trend',  field: 'cpi',  color: '#3fb950', yMin: 0.5, yMax: 1.2 },
      { id: 'spark-bei',  label: 'BEI Trend',  field: 'bei',  color: '#d29922', yMin: 0.5, yMax: 1.2 },
      { id: 'spark-sv',   label: 'SV (days)',  field: 'sv',   color: '#f85149', yMin: null, yMax: null },
    ];

    // Build the layout once (idempotent)
    if (!container.querySelector('canvas')) {
      container.innerHTML = metrics.map(m => `
        <div class="spark-tile">
          <div class="spark-label">${escapeHtml(m.label)}</div>
          <div class="spark-value accent" id="${m.id}-value">—</div>
          <div style="height:60px;position:relative"><canvas id="${m.id}"></canvas></div>
        </div>`).join('');
    }

    metrics.forEach(m => {
      const values = history.map(h => h[m.field]);
      const valEl = document.getElementById(m.id + '-value');
      const last = values[values.length - 1];
      if (valEl) valEl.textContent = last != null ? (m.field === 'sv' ? last.toFixed(1) + 'd' : last.toFixed(3)) : 'N/A';

      const ctx = document.getElementById(m.id);
      if (!ctx) return;
      if (_evmCharts[m.id]) _evmCharts[m.id].destroy();
      _evmCharts[m.id] = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            data: values,
            borderColor: m.color,
            backgroundColor: m.color + '22',
            fill: true,
          }],
        },
        options: _sparklineOptions(m.yMin, m.yMax),
      });
    });
  } catch(_) { /* swallow */ }
}

/* ── DCMA 14-Point with stacked-bar pass/fail viz ─────────────────────────── */
async function loadDcma() {
  const status = document.getElementById('dcma-status');
  const scoreEl = document.getElementById('dcma-scorecard');
  const tableEl = document.getElementById('dcma-checks-table');
  const badge = document.getElementById('dcma-score-badge');
  if (status) status.textContent = 'Loading…';
  try {
    const r = await fetch('/api/dcma', { headers: _authHeaders() });
    if (!r.ok) { if (status) status.textContent = 'No DCMA data yet.'; return; }
    const data = await r.json();
    const score = data.score || 0;
    const total = data.total_checks || 14;
    const health = data.health || 'UNKNOWN';
    const hcol = health==='RED'?'#f85149':health==='YELLOW'?'#d29922':'#3fb950';

    if (badge) { badge.textContent = `${score}/${total}`; badge.style.display = ''; }

    if (scoreEl) scoreEl.innerHTML = `<div style="display:flex;align-items:center;gap:16px;padding:10px;background:#161b22;border-radius:6px;border:1px solid #21262d;">
      <div style="font-size:36px;font-weight:900;color:${hcol}">${score}/${total}</div>
      <div><strong style="color:${hcol}">${escapeHtml(health)}</strong><br>
      <span style="font-size:11px;color:#7d8590">${escapeHtml(data.summary||'')}</span></div>
    </div>`;

    const checks = data.checks || [];

    // Render bar chart of violations per check
    const canvas = document.getElementById('dcma-bar-chart');
    if (canvas && checks.length) {
      if (_dcmaChart) _dcmaChart.destroy();
      _dcmaChart = new Chart(canvas, {
        type: 'bar',
        data: {
          labels: checks.map(c => `#${c.check_id}`),
          datasets: [{
            label: 'Violations',
            data: checks.map(c => c.violations),
            backgroundColor: checks.map(c => c.passed ? '#3fb950' : '#f85149'),
            borderWidth: 0,
            borderRadius: 3,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: '#161b22', titleColor: '#e6edf3', bodyColor: '#c9d1d9',
              borderColor: '#30363d', borderWidth: 1,
              callbacks: {
                title: (items) => {
                  const i = items[0].dataIndex;
                  return checks[i].name;
                },
                label: (item) => `${item.parsed.y} violation(s)`,
              },
            },
          },
          scales: {
            x: { grid: { display: false }, border: { display: false }, ticks: { color: _tickColor, font: { family: _chartFontFamily, size: 10 } } },
            y: { beginAtZero: true, grid: { color: _gridColor }, border: { display: false }, ticks: { color: _tickColor, font: { family: _chartFontFamily, size: 10 }, precision: 0 } },
          },
        },
      });
    }

    if (tableEl && checks.length) {
      tableEl.innerHTML = '<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:8px;">' +
        '<tr style="background:#21262d;"><th style="padding:6px 8px;text-align:left;">#</th>' +
        '<th style="padding:6px 8px;text-align:left;">Check</th>' +
        '<th>Status</th><th>Violations</th><th style="text-align:left;">Note</th></tr>' +
        checks.map(c => {
          const scol = c.passed ? '#3fb950' : '#f85149';
          return `<tr style="border-bottom:1px solid #21262d;">
            <td style="padding:5px 8px;color:#7d8590;">${c.check_id}</td>
            <td style="padding:5px 8px;">${escapeHtml(c.name)}</td>
            <td style="padding:5px 8px;text-align:center;font-weight:700;color:${scol}">${c.passed?'PASS':'FAIL'}</td>
            <td style="padding:5px 8px;text-align:center;">${c.violations}</td>
            <td style="padding:5px 8px;color:#7d8590;font-size:11px">${escapeHtml(c.note||'')}</td>
          </tr>`;
        }).join('') + '</table>';
    }
    if (status) status.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch(e) {
    if (status) status.textContent = 'Error loading DCMA data.';
  }
}

/* ── Milestone Risk Distribution Donut ────────────────────────────────────── */
function _renderMilestoneDonut() {
  const canvas = document.getElementById('milestone-donut');
  if (!canvas || !window.__IMS) return;
  const milestones = window.__IMS.milestones || [];
  if (!milestones.length) return;

  const counts = { HIGH: 0, MEDIUM: 0, LOW: 0 };
  milestones.forEach(m => {
    const r = (m.risk_level || '').toUpperCase();
    if (counts.hasOwnProperty(r)) counts[r]++;
  });

  if (_milestoneDonut) _milestoneDonut.destroy();
  _milestoneDonut = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels: ['HIGH', 'MEDIUM', 'LOW'],
      datasets: [{
        data: [counts.HIGH, counts.MEDIUM, counts.LOW],
        backgroundColor: ['#f85149', '#d29922', '#3fb950'],
        borderColor: '#0d1117',
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: '65%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: _tickColor, font: { family: _chartFontFamily, size: 11 }, boxWidth: 10, padding: 8 },
        },
        tooltip: {
          backgroundColor: '#161b22', titleColor: '#e6edf3', bodyColor: '#c9d1d9',
          borderColor: '#30363d', borderWidth: 1,
        },
      },
    },
  });
}

/* ── Initialize on tab activation (lazy chart render) ─────────────────────── */
document.addEventListener('tab:activated', e => {
  if (e.detail.tab === 'metrics') {
    if (typeof Chart !== 'undefined') {
      Promise.all([loadEvm(), loadDcma()])
        .then(() => { _renderMilestoneDonut(); _attachExportButtons(); });
    }
  }
});
