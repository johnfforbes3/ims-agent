// ATLAS IMS Console — real-data hydration layer
// ----------------------------------------------------------------------------
// Phase 15.4 — Before React mounts, this module fetches live state from the
// existing /api/* endpoints and overrides the mock data in data.js.  Each
// fetch is independent and falls back silently to the mock value when the
// server returns 404 / 500 / empty, so the demo experience stays intact when
// no production cycle has run.
//
// Loads as a regular <script> AFTER data.js + components/charts/tabs but
// BEFORE app.jsx, because app.jsx's ReactDOM.createRoot() reads the window.*
// globals on first render.  We block app.jsx mount with a Promise so the
// initial paint already has live numbers — no flash of mock data.
// ----------------------------------------------------------------------------

(function () {
  const authHeaders = () => {
    const k = (window.__IMS && window.__IMS.api_key) || "";
    return k ? { "X-API-Key": k } : {};
  };

  async function safeJson(path) {
    try {
      const r = await fetch(path, { headers: authHeaders() });
      if (!r.ok) return null;
      return await r.json();
    } catch (_) { return null; }
  }

  function classifyHealth(h) {
    if (h === "RED") return "bad";
    if (h === "YELLOW") return "warn";
    if (h === "GREEN") return "ok";
    return "warn";
  }

  // ────────────────────────────────────────────────────────────────────────
  // Hydrate the window.* globals consumed by the React components.  Each
  // section only runs if the upstream endpoint returned usable data.
  // ────────────────────────────────────────────────────────────────────────

  async function hydrate() {
    // Phase 16 — additional real-data endpoints: HRM history, SRA milestones,
    // and parsed IMS schedule summary.  Each is independently fetched and
    // overrides the corresponding mock global only when it returns data.
    const [state, evmHist, healthHist, hrmHist, sra, schedSummary, sessions] = await Promise.all([
      safeJson("/api/state"),
      safeJson("/api/evm/history?n=24"),
      safeJson("/api/health/history?n=24"),
      safeJson("/api/hrm/history?n=24"),
      safeJson("/api/sra"),
      safeJson("/api/schedule/summary"),
      safeJson("/api/interview-sessions"),
    ]);

    // Stash raw payloads for any debug/inspection later
    window.__IMS_LIVE = { state, evmHist, healthHist };

    // -- Top-level header / ticker numbers ---------------------------------
    if (state) {
      const evm = state.evm && state.evm.program ? state.evm.program : null;
      if (evm) {
        // Override the latest entry in the rolling KPI histories so the
        // hero block + sparklines reflect the CURRENT cycle even before
        // the history endpoint returns a full series.
        if (typeof evm.bei === "number" && Array.isArray(window.BEI_HIST)) {
          window.BEI_HIST = window.BEI_HIST.slice(0, -1).concat(evm.bei);
        }
        if (typeof evm.spi === "number" && Array.isArray(window.SFA_HIST)) {
          window.SFA_HIST = window.SFA_HIST.slice(0, -1).concat(evm.spi);
        }
      }
      // High-risk milestone count
      const ms = state.milestones || [];
      const hrm = ms.filter(m => (m.risk_level || "").toUpperCase() === "HIGH").length;
      if (Array.isArray(window.HRM_HIST) && ms.length > 0) {
        window.HRM_HIST = window.HRM_HIST.slice(0, -1).concat(hrm);
      }
    }

    // -- 6-month BEI/SPI/HRM histories from /api/evm/history ----------------
    // Phase 16 — extracts the program-level snapshot now persisted per cycle.
    if (evmHist && Array.isArray(evmHist.history) && evmHist.history.length >= 2) {
      const series = evmHist.history;
      const bei = series.map(h => h.bei).filter(v => typeof v === "number");
      const spi = series.map(h => h.spi).filter(v => typeof v === "number");
      if (bei.length >= 2) window.BEI_HIST = bei;
      if (spi.length >= 2) window.SFA_HIST = spi;
    }
    // Phase 16 — HRM history from dedicated endpoint
    if (hrmHist && Array.isArray(hrmHist.history) && hrmHist.history.length >= 2) {
      const hrm = hrmHist.history
        .map(h => h.high_risk_milestones)
        .filter(v => typeof v === "number");
      if (hrm.length >= 2) window.HRM_HIST = hrm;
    }

    // Phase 16 — SRA endpoint: real Monte-Carlo milestone outputs
    if (sra && Array.isArray(sra.milestones) && sra.milestones.length > 0) {
      window.__IMS_SRA_REAL = sra;
      // We don't have a full date-by-date histogram from the cycle yet, but
      // we can synthesise the bar chart from milestone P50/P80/P95 anchors
      // when present so the chart shows real anchor points instead of mock.
      // (Full histogram requires a Monte-Carlo run endpoint, future work.)
    }

    // Phase 16 — Schedule summary endpoint: real parsed IMS rows + milestones
    if (schedSummary && Array.isArray(schedSummary.rows) && schedSummary.rows.length > 0) {
      const programStart = schedSummary.program_start
        ? new Date(schedSummary.program_start) : window.PROGRAM_START;
      const programEnd   = schedSummary.program_end
        ? new Date(schedSummary.program_end) : window.PROGRAM_END;
      if (programStart) window.PROGRAM_START = programStart;
      if (programEnd)   window.PROGRAM_END   = programEnd;
      window.SCHED_CURRENT = {
        label:      schedSummary.label || "current",
        generated:  schedSummary.generated || "",
        rows:       schedSummary.rows,
        milestones: schedSummary.milestones || [],
      };
      // Prior version is unavailable from a single export — clone & mark stale
      // so the ghost overlay degrades gracefully instead of showing mock data.
      window.SCHED_PRIOR = {
        ...window.SCHED_CURRENT,
        label: "prior (unavailable)",
      };
    }

    // Phase 16 — Active interview sessions → real per-CAM live progress
    if (sessions && Array.isArray(sessions) && sessions.length > 0) {
      const progressByCam = {};
      sessions.forEach(s => {
        // session shape: { cam_name, status, turns_completed, turns_expected, ... }
        const turns = s.turns_completed || 0;
        const expected = s.turns_expected || s.turns_target || 8;
        const pct = s.status === "completed" ? 100
                  : s.status === "escalated" ? 100
                  : Math.min(95, Math.round((turns / Math.max(1, expected)) * 100));
        if (s.cam_name) progressByCam[s.cam_name] = pct;
      });
      window.__IMS_CAM_PROGRESS = progressByCam;
    }

    // -- Schedule-health history (PM Portal line chart) --------------------
    if (healthHist && Array.isArray(healthHist.history) && healthHist.history.length >= 2) {
      const scoreFor = h => h === "GREEN" ? 90 : h === "YELLOW" ? 65 : h === "RED" ? 35 : 50;
      window.HEALTH_HISTORY = healthHist.history.map(h => scoreFor(h.schedule_health));
    }

    // -- EVM KPI tiles (Tab 1, section 04) ---------------------------------
    if (state && state.evm && state.evm.program) {
      const p = state.evm.program;
      const tone = v => v == null ? "neutral" : v < 0.85 ? "bad" : v < 0.95 ? "warn" : "ok";
      const newKpis = [
        { key: "SPI",         val: p.spi  != null ? p.spi  : 0, fmt: "ratio", tone: tone(p.spi),  note: "Schedule Perf. Index" },
        { key: "SV",          val: p.sv   != null ? p.sv * 1000 : 0, fmt: "kusd", tone: p.sv < 0 ? "bad" : "ok", note: "Schedule Variance" },
        { key: "% Complete",  val: p.completion_pct != null ? p.completion_pct / 100 : 0, fmt: "pct", tone: "ok", note: "Weighted physical" },
        { key: "BEI",         val: p.bei  != null ? p.bei  : 0, fmt: "ratio", tone: tone(p.bei),  note: "Baseline Exec. Index" },
        { key: "BAC",         val: p.bac  != null ? p.bac  : 0, fmt: "kusd",  tone: "neutral",     note: "Budget At Completion" },
        { key: "EAC",         val: p.eac  != null ? p.eac  : 0, fmt: "kusd",  tone: "warn",        note: "Estimate At Completion" },
        { key: "VAC",         val: p.vac  != null ? p.vac  : 0, fmt: "kusd",  tone: p.vac < 0 ? "bad" : "ok", note: "Variance At Completion" },
        { key: "BCWP",        val: p.bcwp != null ? p.bcwp : 0, fmt: "kusd",  tone: "neutral",     note: "Earned Value" },
      ];
      // Only override if at least SPI is set; otherwise keep the rich mock
      if (typeof p.spi === "number") window.EVM_KPIS = newKpis;
    }

    // -- Per-CAM breakdown (EVM + Agent Controls tables) -------------------
    if (state && state.evm && state.evm.by_cam && Object.keys(state.evm.by_cam).length > 0) {
      const camStatus = state.cam_response_status || {};
      const liveCams = Object.entries(state.evm.by_cam).map(([cam, d], i) => {
        const respInfo = camStatus[cam] || {};
        const status = d.health === "RED" ? "bad" : d.health === "YELLOW" ? "warn" : "ok";
        return {
          cam:       cam,
          lead:      cam, // CAM name doubles as lead in current state shape
          wbs:       d.wbs || ("1." + (i + 1) + " " + cam),
          bac:       d.bac  || 0,
          bcwp:      d.bcwp || 0,
          bcws:      d.bcws || 0,
          acwp:      d.acwp || d.bcwp || 0,
          spi:       d.spi  != null ? d.spi  : 0,
          cpi:       d.cpi  != null ? d.cpi  : 0,
          status:    status,
          responded: !!respInfo.responded,
          attempts:  respInfo.attempts || 1,
          outcome:   respInfo.responded ? "BASELINE" : (respInfo.attempts > 1 ? "ESCALATE" : "PENDING"),
          drift:     0,
          health:    d.health === "RED" ? "red" : d.health === "YELLOW" ? "yellow" : "green",
        };
      });
      if (liveCams.length > 0) window.CAMS = liveCams;
    }

    // -- DCMA 14-Point -----------------------------------------------------
    if (state && state.dcma && Array.isArray(state.dcma.checks) && state.dcma.checks.length > 0) {
      window.DCMA14 = state.dcma.checks.map(c => ({
        id:     c.check_id,
        name:   c.name,
        val:    c.violations + (c.violations === 1 ? " issue" : " issues"),
        target: c.note || "",
        pass:   c.passed ? "pass" : (c.violations <= 2 ? "warn" : "fail"),
      }));
    }

    // -- Top risks + recommended actions (PM Portal) -----------------------
    if (state && typeof state.top_risks === "string" && state.top_risks.trim().length > 0) {
      const lines = state.top_risks.split("\n").filter(s => s.trim().length > 0).slice(0, 3);
      if (lines.length > 0) {
        window.TOP_RISKS_PROSE = lines.map((line, i) => {
          const m = line.match(/^[\d\.\)\-\s]*(.+)$/);
          const text = m ? m[1].trim() : line.trim();
          return {
            id:          "R" + (i + 1),
            title:       text.length > 60 ? text.substring(0, 60) + "…" : text,
            body:        text,
            impact:      i === 0 ? "Critical" : i === 1 ? "High" : "Moderate",
            probability: 0.78 - i * 0.10,
          };
        });
      }
    }
    if (state && typeof state.recommended_actions === "string" && state.recommended_actions.trim().length > 0) {
      const lines = state.recommended_actions.split("\n").filter(s => s.trim().length > 0).slice(0, 4);
      if (lines.length > 0) {
        const priorities = ["Now", "This week", "Within 2 cycles", "Recurring"];
        window.PM_ACTIONS_PROSE = lines.map((line, i) => {
          const m = line.match(/^[\d\.\)\-•\s]*(.+)$/);
          const text = m ? m[1].trim() : line.trim();
          return {
            id:       "A" + (i + 1),
            title:    text.length > 60 ? text.substring(0, 60) + "…" : text,
            body:     text,
            priority: priorities[i] || "Within 2 cycles",
          };
        });
      }
    }

    // -- Diff viewer + change history + drift (Agent Controls tab) ---------
    const [diff, changes, drift] = await Promise.all([
      safeJson("/api/diff/latest"),
      safeJson("/api/changes"),
      safeJson("/api/baseline-drift"),
    ]);

    if (diff && Array.isArray(diff.changes) && diff.changes.length > 0) {
      window.DIFF_ROWS = diff.changes.slice(0, 12).map(c => ({
        task:  c.task_name || c.task_id,
        cam:   c.cam_name  || "—",
        field: c.field,
        oldv:  String(c.old_value == null ? "—" : c.old_value),
        newv:  String(c.new_value == null ? "—" : c.new_value),
        delta: c.delta || "",
      }));
    }

    if (changes && Array.isArray(changes.changes) && changes.changes.length > 0) {
      window.CUM_DIFF = changes.changes.slice(0, 10).map(c => ({
        task:        c.task_name || c.task_id,
        cam:         c.cam_name  || "—",
        finishDrift: c.finish_drift_days || 0,
        hops:        c.hop_count || 1,
        cycles:      (c.contributing_cycle_ids || []).slice(0, 2).join(" → ") || "—",
      }));
    }

    if (drift && Array.isArray(drift.task_drift) && drift.task_drift.length > 0) {
      window.DRIFT_ROWS = drift.task_drift.slice(0, 12).map(t => ({
        task:     t.name || t.task_id,
        cam:      t.cam  || "—",
        baseFin:  t.baseline_finish || "—",
        curFin:   t.current_finish  || "—",
        slip:     t.finish_slip_days || 0,
        pctDelta: t.pct_delta || 0,
      }));
    }

    // -- Cycle phase / metadata --------------------------------------------
    if (state && state.current_cycle && state.current_cycle.phase) {
      const phaseMap = {
        boot: 0, dispatch: 1, interview: 2, diff: 3,
        validate: 4, publish: 5, complete: 5, failed: 5,
      };
      window.__IMS_LIVE_PHASE = phaseMap[state.current_cycle.phase.toLowerCase()] ?? 2;
    }
    window.__IMS_CYCLE_ID = (state && state.cycle_id) || "C-2026-19";
  }

  // Expose so app.jsx can await before render
  window.__IMS_HYDRATE = hydrate();
})();
