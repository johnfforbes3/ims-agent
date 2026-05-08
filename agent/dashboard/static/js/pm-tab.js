/**
 * @file pm-tab.js
 * @description IMS Command Center — Tab 2 (PM Dashboard).
 *
 * Decision-support views for the program manager:
 *
 *   - {@link loadHealthHistoryChart} — 24-cycle Schedule Health trend line
 *     with **green/yellow/red zone backgrounds** painted by the custom
 *     `_healthZonesPlugin`.  Y-axis is a numeric health score; ticks are
 *     formatted back to "RED"/"YELLOW"/"GREEN".  Source: `/api/health/history`.
 *   - {@link loadVariance}           — Schedule Variance Narrative (CPR Format 5).
 *   - {@link openBriefing}           — Opens the Executive Briefing HTML in a
 *     new tab via `/api/briefing`.
 *   - {@link loadPortfolio}          — Portfolio tile grid + health-distribution
 *     donut chart sourced from `/api/portfolio`.
 *
 * Charts auto-render on `tab:activated` (event dispatched by dashboard-core).
 *
 * @module pm-tab
 * @requires Chart escapeHtml _authHeaders _attachExportButtons
 */

let _healthTrendChart = null;
let _portfolioDonut = null;

/* Map a health label to a numeric score for the trend Y-axis. */
const _healthScore = { GREEN: 90, YELLOW: 60, RED: 25, UNKNOWN: 50 };

/* Custom plugin: paint G/Y/R zone backgrounds across the chart area. */
const _healthZonesPlugin = {
  id: 'healthZones',
  beforeDraw(chart) {
    const { ctx, chartArea: { left, right, top, bottom }, scales: { y } } = chart;
    if (!y) return;
    const zones = [
      { from: 75, to: 100, color: 'rgba(63,185,80,0.10)'  },  // GREEN
      { from: 40, to: 75,  color: 'rgba(210,153,34,0.10)' },  // YELLOW
      { from: 0,  to: 40,  color: 'rgba(248,81,73,0.10)'  },  // RED
    ];
    ctx.save();
    zones.forEach(z => {
      const yTop = y.getPixelForValue(z.to);
      const yBot = y.getPixelForValue(z.from);
      ctx.fillStyle = z.color;
      ctx.fillRect(left, Math.min(yTop, yBot), right - left, Math.abs(yBot - yTop));
    });
    ctx.restore();
  },
};

/* ── Schedule Health History trend chart ─────────────────────────────────── */
async function loadHealthHistoryChart() {
  const status = document.getElementById('health-history-status');
  const canvas = document.getElementById('health-history-chart');
  if (!canvas) return;
  if (status) status.textContent = 'Loading…';
  try {
    const r = await fetch('/api/health/history?n=24', { headers: _authHeaders() });
    if (!r.ok) {
      if (status) status.textContent = 'No history yet — needs 1+ completed cycles.';
      return;
    }
    const data = await r.json();
    const history = data.history || [];
    if (!history.length) {
      if (status) status.textContent = 'No cycle history yet.';
      return;
    }

    const labels = history.map(h => (h.timestamp || '').slice(0, 10));
    const scores = history.map(h => _healthScore[h.schedule_health || 'UNKNOWN']);
    const pointColors = history.map(h => {
      const s = h.schedule_health;
      return s === 'GREEN' ? '#3fb950' : s === 'YELLOW' ? '#d29922' : s === 'RED' ? '#f85149' : '#7d8590';
    });

    if (_healthTrendChart) _healthTrendChart.destroy();
    _healthTrendChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Schedule Health',
          data: scores,
          borderColor: '#58a6ff',
          backgroundColor: 'rgba(88,166,255,0.05)',
          pointBackgroundColor: pointColors,
          pointBorderColor: pointColors,
          pointRadius: 5,
          pointHoverRadius: 7,
          borderWidth: 2,
          tension: 0.2,
          fill: true,
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
              label: (ctx) => {
                const h = history[ctx.dataIndex];
                return `${h.schedule_health || 'UNKNOWN'} · ${h.cams_responded || 0}/${h.cams_total || 0} CAMs`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: '#21262d' }, border: { display: false },
            ticks: { color: '#7d8590', font: { size: 10 }, maxRotation: 45, autoSkip: true, maxTicksLimit: 12 },
          },
          y: {
            min: 0, max: 100,
            grid: { color: '#21262d' }, border: { display: false },
            ticks: {
              color: '#7d8590', font: { size: 10 },
              callback: (v) => v >= 75 ? 'GREEN' : v >= 40 ? 'YELLOW' : 'RED',
              stepSize: 25,
            },
          },
        },
      },
      plugins: [_healthZonesPlugin],
    });

    if (status) status.textContent = `${history.length} cycles · Updated ${new Date().toLocaleTimeString()}`;
  } catch(e) {
    if (status) status.textContent = 'Error loading health history.';
  }
}

/* ── Schedule Variance Narrative (CPR Format 5) ──────────────────────────── */
async function loadVariance() {
  const status = document.getElementById('variance-status');
  const textEl = document.getElementById('variance-text');
  if (status) status.textContent = 'Loading…';
  try {
    const r = await fetch('/api/variance', { headers: _authHeaders() });
    if (!r.ok) { if (status) status.textContent = 'No variance narrative yet.'; return; }
    const data = await r.json();
    if (textEl) textEl.textContent = data.narrative || 'No narrative available.';
    if (status) status.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch(e) {
    if (status) status.textContent = 'Error loading variance narrative.';
  }
}

/* ── Executive Briefing (one-click HTML) ─────────────────────────────────── */
function openBriefing() {
  window.open('/api/briefing', '_blank');
}

/* ── Portfolio View (tiles + health distribution donut) ──────────────────── */
async function loadPortfolio() {
  const status = document.getElementById('portfolio-status');
  const tilesEl = document.getElementById('portfolio-tiles');
  const badge = document.getElementById('portfolio-at-risk-badge');
  if (status) status.textContent = 'Loading…';
  try {
    const r = await fetch('/api/portfolio', { headers: _authHeaders() });
    if (!r.ok) { if (status) status.textContent = 'Error loading portfolio.'; return; }
    const data = await r.json();
    const programs = data.programs || [];
    const atRisk = data.programs_at_risk || 0;

    if (badge && atRisk > 0) { badge.textContent = atRisk + ' at risk'; badge.style.display = ''; }

    if (tilesEl) tilesEl.innerHTML = programs.map(p => {
      const health = p.health || 'UNKNOWN';
      const hcol = health==='RED'?'#f85149':health==='YELLOW'?'#d29922':health==='GREEN'?'#3fb950':'#7d8590';
      const hbg = health==='RED'?'#2a0a0a':health==='YELLOW'?'#1f1a08':health==='GREEN'?'#0a1f0a':'#161b22';
      return `<div style="background:${hbg};border:2px solid ${hcol};border-radius:8px;padding:14px;position:relative;">
        <div style="font-weight:700;font-size:14px;margin-bottom:4px;">${escapeHtml(p.name)}</div>
        <div style="font-size:24px;font-weight:900;color:${hcol};margin-bottom:8px;">${escapeHtml(health)}</div>
        <div style="font-size:11px;color:#7d8590;display:grid;grid-template-columns:1fr 1fr;gap:2px;">
          <span>SPI: <strong style="color:#e6edf3">${p.spi!=null?p.spi.toFixed(3):'N/A'}</strong></span>
          <span>Completion: <strong style="color:#e6edf3">${p.completion_pct!=null?p.completion_pct.toFixed(1)+'%':'N/A'}</strong></span>
          <span>DCMA: <strong style="color:#e6edf3">${escapeHtml(p.dcma_score||'N/A')}</strong></span>
          <span>CAMs: <strong style="color:#e6edf3">${escapeHtml(p.cam_response_rate||'N/A')}</strong></span>
          <span>High-Risk MS: <strong style="color:${p.milestones_high_risk>0?'#f85149':'#e6edf3'}">${p.milestones_high_risk||0}</strong></span>
          <span>BEI: <strong style="color:#e6edf3">${p.bei!=null?p.bei.toFixed(3):'N/A'}</strong></span>
        </div>
        ${p.top_risk_preview ? '<div style="margin-top:8px;font-size:11px;color:#7d8590;border-top:1px solid #21262d;padding-top:6px;">' + escapeHtml(p.top_risk_preview) + '</div>' : ''}
        ${p.is_stale ? '<div style="position:absolute;top:8px;right:8px;font-size:10px;background:#3d2a00;color:#d29922;padding:2px 5px;border-radius:3px;">STALE</div>' : ''}
      </div>`;
    }).join('');

    // Render distribution donut
    const canvas = document.getElementById('portfolio-donut');
    if (canvas && programs.length) {
      const counts = { GREEN: 0, YELLOW: 0, RED: 0, UNKNOWN: 0 };
      programs.forEach(p => {
        const h = (p.health || 'UNKNOWN').toUpperCase();
        if (counts.hasOwnProperty(h)) counts[h]++;
        else counts.UNKNOWN++;
      });
      if (_portfolioDonut) _portfolioDonut.destroy();
      _portfolioDonut = new Chart(canvas, {
        type: 'doughnut',
        data: {
          labels: ['GREEN', 'YELLOW', 'RED', 'UNKNOWN'],
          datasets: [{
            data: [counts.GREEN, counts.YELLOW, counts.RED, counts.UNKNOWN],
            backgroundColor: ['#3fb950', '#d29922', '#f85149', '#7d8590'],
            borderColor: '#0d1117', borderWidth: 2,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          cutout: '60%',
          plugins: {
            legend: { position: 'bottom', labels: { color: '#7d8590', font: { size: 10 }, boxWidth: 10, padding: 6 } },
            tooltip: { backgroundColor: '#161b22', titleColor: '#e6edf3', bodyColor: '#c9d1d9', borderColor: '#30363d', borderWidth: 1 },
          },
        },
      });
    }

    if (status) status.textContent = `${programs.length} programs · Updated ${new Date().toLocaleTimeString()}`;
  } catch(e) {
    if (status) status.textContent = 'Error loading portfolio data.';
  }
}

/* ── Initialize on tab activation ────────────────────────────────────────── */
document.addEventListener('tab:activated', e => {
  if (e.detail.tab === 'pm') {
    if (typeof Chart !== 'undefined') {
      Promise.all([loadHealthHistoryChart(), loadVariance(), loadPortfolio()])
        .then(() => _attachExportButtons());
    }
  }
});
