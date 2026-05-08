# Phase 12 — IMS Command Center Dashboard Overhaul

**Date:** 2026-05-08
**Branch:** master
**Pre-overhaul snapshot:** tag `pre-dashboard-overhaul-2026-05-08`, branch `backup/pre-dashboard-overhaul`
**Final commit:** `b1301f6`

---

## 1. Scope

Replace the monolithic 1822-line `agent/dashboard/templates/index.html`
single-page dashboard with a 3-tab IMS Command Center:

| Tab | Purpose |
|---|---|
| **IMS Metrics & Indicators** | Schedule health, KPIs, milestone risk, EVM, DCMA |
| **PM Dashboard** | Decision-support: top risks, actions, health trend, briefing, variance, portfolio |
| **ATLAS Agent Control** | Operations: trigger cycle, CAM status, diff viewer, baseline drift, listen-in |

Add a visual data layer (Chart.js v4 vendored) for trend lines, sparklines, donuts, and bar charts.

---

## 2. Phase-by-phase outcome

| Phase | Title | Status | Output |
|---|---|---|---|
| 0 | Rollback safety net | ✅ | Git tag + branch pushed to remote |
| 1 | Inventory existing dashboard | ✅ | 81 element IDs, 18 JS functions, 23 API endpoints catalogued |
| 2 | Phased build plan | ✅ | Tile placement map confirmed; 3 items (Validation Alerts, Cycle Progress, Countdown) placed |
| 3 | Scaffold 3-tab IA | ✅ | `base.html` + 3 partials, hash routing, static asset mount |
| 4 | IMS Metrics tab | ✅ | 10 tiles wired; EVM gets 24-cycle rolling sparklines |
| 5 | PM Dashboard tab | ✅ | 6 tiles; Schedule Health trend chart with G/Y/R zones |
| 6 | ATLAS Agent Control tab | ✅ | 7 tiles; Baseline Drift gets top-10 slip bar chart |
| 7 | Visual data layer | ✅ | Chart.js v4 (201 KB) vendored, 9 charts wired |
| 8 | Parity audit | ✅ | **81/81 element IDs + 18/18 JS functions** present |
| 9 | End-to-end testing | ✅ | **1009/1010 unit tests passing** (1 pre-existing flake — TD-042) |
| 10 | Documentation | ✅ | This report + 5 doc updates + commit message |

---

## 3. Files changed

```
13 files changed, 2577 insertions(+), 15 deletions(-)
```

### New files (10)
- `agent/dashboard/templates/base.html` — shell + tab nav + 3 partial includes
- `agent/dashboard/templates/tabs/metrics.html` — IMS Metrics tab partial
- `agent/dashboard/templates/tabs/pm.html` — PM Dashboard tab partial
- `agent/dashboard/templates/tabs/atlas.html` — ATLAS Control tab partial
- `agent/dashboard/static/css/dashboard.css` — extracted styles + new tab/chart styles
- `agent/dashboard/static/js/dashboard-core.js` — polling, trigger, hash routing, chat
- `agent/dashboard/static/js/metrics-tab.js` — EVM, DCMA, milestone-risk donut
- `agent/dashboard/static/js/pm-tab.js` — health trend chart, portfolio donut, variance, briefing
- `agent/dashboard/static/js/atlas-tab.js` — diff, change history, drift, listen-in
- `agent/dashboard/static/vendor/chart.umd.min.js` — Chart.js v4.4.6 (vendored, 201 KB)

### Modified files (3)
- `agent/dashboard/server.py` — `/api/evm/history`, `/api/health/history`, static mount, base.html render, `IMS_LEGACY_DASHBOARD` rollback flag
- `tests/test_integration_dashboard_ui.py` — `dash_html` fixture concatenates HTML + linked static assets; 3 content-label tests updated for renamed text
- `tests/test_integration_api_smoke.py` — `_html_plus_js` helper for path-reference tests

### Untouched (intentionally preserved for rollback)
- `agent/dashboard/templates/index.html` — original monolithic template kept as fallback (set `IMS_LEGACY_DASHBOARD=1` to render it)

---

## 4. Visual data representations added

| Tab | Chart | Type | Data source |
|---|---|---|---|
| Metrics | Milestone Risk Distribution | Donut | `state.milestones[].risk_level` |
| Metrics | SPI Trend (24 cycles) | Line / sparkline | `/api/evm/history?n=24` |
| Metrics | CPI Trend (24 cycles) | Line / sparkline | `/api/evm/history?n=24` |
| Metrics | BEI Trend (24 cycles) | Line / sparkline | `/api/evm/history?n=24` |
| Metrics | SV (days) Trend (24 cycles) | Line / sparkline | `/api/evm/history?n=24` |
| Metrics | DCMA Violations by Check | Bar | `/api/dcma` (per-check `violations`) |
| PM | Schedule Health History | Line w/ G/Y/R zone bands | `/api/health/history?n=24` |
| PM | Portfolio Health Distribution | Donut | `/api/portfolio` (program healths) |
| ATLAS | Top 10 Baseline Drift | Horizontal bar | `/api/baseline-drift` (slip days) |

**Total: 9 charts.**  All rendered via Chart.js v4, vendored locally for offline / ITAR compatibility.

---

## 5. Tile placement map (parity from old → new)

| Old element | Old location | New tab | New location |
|---|---|---|---|
| `header` | top of page | header (cross-tab) | unchanged |
| `health-banner` | row 1 | **IMS Metrics** | top of tab |
| `alert-panel` (Validation Alerts) | row 2 | **IMS Metrics** | row 2 |
| KPI: CAMs Responded | row 3 col 1 | **ATLAS** | row 1 col 1 (moved) |
| KPI: HIGH Risk Milestones | row 3 col 2 | **IMS Metrics** | row 3 col 1 |
| KPI: Tasks Behind w/ Blocker | row 3 col 3 | **IMS Metrics** | row 3 col 2 |
| KPI: Critical Path Tasks | row 3 col 4 | **IMS Metrics** | row 3 col 3 |
| Milestone Risk Summary | row 4 | **IMS Metrics** | row 4 + new donut |
| CAM Response Status (`#cam-status-table`) | row 4 | **ATLAS** | row 3 |
| Top Risks | row 5 | **PM Dashboard** | row 1 col 1 |
| Tasks Behind Schedule | row 5 | **IMS Metrics** | row 4 col 2 |
| Critical Path Task IDs | row 6 | **IMS Metrics** | row 5 |
| Recommended Actions for PM | row 7 (conditional) | **PM Dashboard** | row 1 col 2 |
| Schedule Health History | row 8 | **PM Dashboard** | row 2 (now trend chart) |
| Q&A Chat (`#chat-messages`) | row 9 | **IMS Metrics** | row 6 |
| Cycle In Progress (`#cycle-progress-card`) | row 10 (conditional) | **ATLAS** | row 2 |
| What Changed (`#what-changed-panel`) | row 11 | **ATLAS** | row 4 |
| Change History (`#change-history-panel`) | row 12 | **ATLAS** | row 5 |
| Baseline Drift (`#baseline-drift-panel`) | row 13 | **ATLAS** | row 6 + new bar chart |
| Generate Executive Briefing | row 14 | **PM Dashboard** | row 3 (prominent) |
| EVM (`#evm-panel`) | row 15 | **IMS Metrics** | row 7 + 4 sparklines |
| DCMA (`#dcma-panel`) | row 16 | **IMS Metrics** | row 8 + bar chart |
| Variance (`#variance-panel`) | row 17 | **PM Dashboard** | row 4 |
| Portfolio (`#portfolio-panel`) | row 18 | **PM Dashboard** | row 5 + donut |
| Listen-In (`#listenin-panel`) | row 19 | **ATLAS** | row 7 |

Every old element ID is preserved verbatim — old tests keep passing without rewriting their `assert "id-foo" in html` assertions (they now scan the concatenated HTML+JS+CSS via the upgraded fixture).

---

## 6. New API endpoints

```
GET /api/evm/history?n=24
  → { history: [{timestamp, cycle_id, spi, cpi, bei, sv, completion_pct}, ...], n: N }

GET /api/health/history?n=24
  → { history: [{timestamp, cycle_id, schedule_health, cams_responded, cams_total}, ...], n: N }
```

Both walk `data/cycle_history.json`, are auth-gated by `_require_api_key`, and hard-cap `n` at 100.

---

## 7. Test results

### Phase 9 verification (full unit suite, `pytest tests/ -m "not integration"`)

```
1009 passed, 1 failed, 42 deselected, 832 warnings in 350.86s (5:50)
```

The single failure is **`tests/test_interview_agent.py::TestConversationalContext::test_flat_denial_retry_limit_still_works`** — this is the **pre-existing test-order flake documented as TD-042**.  Verified passing in isolation (`pytest tests/test_interview_agent.py::TestConversationalContext::test_flat_denial_retry_limit_still_works`).  Not caused by Phase 12 changes.

### Dashboard suite specifically

```
tests/test_integration_dashboard_ui.py     305 passed
tests/test_phase92_endpoints.py            16 passed
```

After updating the `dash_html` fixture and 3 content-label tests, **0 dashboard tests fail**.

### Parity check (programmatic, not pytest)

```
Element IDs:    81/81 present
JS functions:   18/18 present
Static assets:  6/6 served (200 OK):
  /static/css/dashboard.css           (20.4 KB)
  /static/js/dashboard-core.js        (9.4 KB)
  /static/js/metrics-tab.js           (13.9 KB)
  /static/js/pm-tab.js                (9.8 KB)
  /static/js/atlas-tab.js             (18.9 KB)
  /static/vendor/chart.umd.min.js     (201.1 KB)
```

---

## 8. Rollback plan

Three escalating options if anything looks wrong tomorrow:

1. **Soft rollback (no redeploy):** set `IMS_LEGACY_DASHBOARD=1` in `.env` and reload the dashboard process — the `/` route renders the original `index.html` instead of `base.html`.

2. **Branch rollback (git):** `git checkout backup/pre-dashboard-overhaul` to switch to the pre-overhaul snapshot. Master remains unchanged.

3. **Hard rollback (master):** `git revert b1301f6` to revert the commit on master, or `git reset --hard pre-dashboard-overhaul-2026-05-08` (destructive — destroys subsequent commits).

---

## 9. Known issues / follow-ups

- **TD-042** (pre-existing, documented in TECHNICAL-DEBT.md): `test_flat_denial_retry_limit_still_works` flake. Not Phase 12.
- **No live LLM data on `/api/evm/history` until ≥2 cycles have completed** — this is by design; the empty-state message in the sparkline tile says "No EVM history yet — needs 2+ completed cycles."
- **Tab-activation lazy chart init** — charts re-render on every tab switch. For very large histories this could be optimised by caching, but at n=24 it's <50 ms total.
- **`agent/dashboard/templates/index.html` not deleted** — kept for `IMS_LEGACY_DASHBOARD` rollback. Plan to remove after a 2-week soak.

---

## 10. Verification steps for the morning audit

1. Visit `/` → should see the **IMS Command Center** title and 3 tab buttons in a row.
2. Click each tab → URL hash updates to `#/metrics`, `#/pm`, `#/atlas`; only one panel visible at a time.
3. **IMS Metrics tab:**
   - Health banner colored RED/YELLOW/GREEN per current state.
   - 3 KPI cards (no CAMs Responded — that moved to ATLAS).
   - Milestone Risk Summary table + risk-distribution donut side by side.
   - EVM panel auto-loads; the four "Rolling 24-Cycle Trends" sparklines below the KPI cards.
   - DCMA panel auto-loads; horizontal bar chart of violations by check.
   - Q&A chat works — type a question, hit Ask, get a response.
4. **PM Dashboard tab:**
   - Top Risks + Recommended Actions side by side.
   - Schedule Health History trend chart shows R/Y/G zone backgrounds.
   - Generate Executive Briefing button is prominent and large.
   - Variance Narrative auto-loads.
   - Portfolio panel shows tiles + distribution donut.
5. **ATLAS Agent Control tab:**
   - CAMs Responded KPI is here.
   - Trigger Cycle button (from header) still works.
   - What Changed Diff, Change History, Baseline Drift all auto-init.
   - Baseline Drift shows horizontal bar chart of top 10 slips.
   - Live Interview Listen-In panel auto-connects on expand.

---

**Build session duration:** ~2 hours (start-to-commit).
**Lines added (net):** 2,562.
**Risk level:** Medium — comprehensive test coverage but visual layout changes. Soft-rollback flag available.

---

# Phase 12.1 — Overnight Polish (2026-05-08)

Continuation of Phase 12 the same evening, while the auditor's review was pending in the morning.  Focus: close out remaining open TDs, add comprehensive Phase 12 test coverage, and ship audit-ready quality-of-life features.

## 11. Tier 1 outcomes (TD resolution + Phase 12 tests)

| TD | Title | Resolution |
|---|---|---|
| **TD-042** | `test_flat_denial_retry_limit_still_works` flake | Mocked `_classify_cam_response` and `_classify_eac_date` directly via `monkeypatch.setattr` inside the test.  Runtime dropped 20s → 0.2s.  Test is now deterministic in any suite ordering. |
| **TD-046** | CAMSimulator eager `LLMInterface` construction | Moved `LLMInterface(model=_SIM_MODEL)` from `__init__` to `respond()`.  `__init__` sets `self._llm = None`; lazy-built on first call.  Matches pattern used everywhere else (qa_engine, cycle_runner, variance_analyst, interview_agent). |
| **TD-048** | CI Node.js 20 deprecation | Added `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"` to job-level `env` in `.github/workflows/ci.yml`.  Forces all v4/v5 actions to run on Node.js 24 immediately.  Annotation-clean CI. |

**Net result:** Zero open low/medium TDs.

## 12. New Phase 12 test class (Tier 1D)

`tests/test_phase12_dashboard_overhaul.py` — 58 tests across 11 classes:

| Class | Coverage |
|---|---|
| `TestTabNavigation` | 12 tests: 3 buttons, 3 panels, default-active state, hash-routing fn refs, role attrs |
| `TestStaticAssets` | 8 tests: all 6 asset paths return 200, Chart.js v4 banner, no CDN refs |
| `TestEvmHistoryEndpoint` | 5 tests: 200 status, response shape, n=24 default, n cap at 100, n minimum |
| `TestHealthHistoryEndpoint` | 3 tests: 200 status, response shape, n cap |
| `TestChartCanvasPresence` | 7 tests: every `<canvas id="…">` declared in tab partials |
| `TestDemoMode` | 4 tests: 200 status, IMS Command Center title, milestone names render, no state-file write |
| `TestThemeToggle` | 3 tests: button present, `data-theme` on `<html>`, `[data-theme="light"]` selectors in CSS |
| `TestPrintStylesheet` | 3 tests: `@media print` exists, hides `.tab-nav`, references `.tab-panel` |
| `TestChartPngExport` | 2 tests: `exportChart` defined, uses `toBase64Image` |
| `TestKeyboardShortcuts` | 2 tests: keydown listener, digit-key + ctrl/meta refs |
| `TestCodeQuality` | 8 tests: all 4 JS modules have header comment + at least one function decl |
| `TestLegacyRollback` | 1 test: `IMS_LEGACY_DASHBOARD=1` falls back to monolithic `index.html` |

**Total:** 58/58 passing in 4.83s.

## 13. Tier 1E — Demo mode (`/?demo=1`)

Read-only synthetic data path so the dashboard renders fully populated even when no production cycle has run.

- `_demo_state()` — single-cycle state with 5 CAMs, 4 milestones (HIGH/MEDIUM/LOW/LOW), 2 blocked tasks, full EVM/DCMA/variance, recommended actions.
- `_demo_history()` — 24 cycles of synthetic history with seeded RNG (`random.seed(42)`).  Health trends RED → YELLOW → GREEN as project recovers.  SPI/CPI/BEI sweep 0.78 → 0.96 with realistic noise.
- Read-only — never persists to disk.  Verified by test that asserts `state.json` byte-equality before / after a demo render.

**For the auditor:** open `http://<host>/?demo=1` to see every chart populated in 0 ms.

## 14. Tier 2 outcomes (UX polish)

### F. Keyboard shortcuts
- **Ctrl/Cmd + 1** → IMS Metrics & Indicators tab
- **Ctrl/Cmd + 2** → PM Dashboard tab
- **Ctrl/Cmd + 3** → ATLAS Agent Control tab
- **Ctrl/Cmd + L** → Toggle light/dark theme
- Ignored when typing in inputs/textareas/selects (event-target tag check).

### G. Chart PNG export
- Floating 📥 button auto-injected into every `.chart-container` after Chart.js mounts.
- Uses `Chart.getChart(canvas).toBase64Image('image/png', 1.0)` for retina-correct export, with `canvas.toDataURL()` fallback when Chart.js isn't yet attached.
- Container `:hover` reveals the button (40% → 100% opacity).
- Idempotent — `_attachExportButtons()` skips containers that already have a button.

### H. Print stylesheet (`@media print`)
- Hides `.tab-nav`, header buttons (`#trigger-btn`, `#theme-toggle`, `.chart-export-btn`), chat input, listen-in panel.
- Cascades all 3 tab panels onto pages with `page-break-before: always` (first tab gets `auto`).
- Forces light theme regardless of user setting (`background: #ffffff`, `color: #1f2328`).
- Auto-opens collapsed `<details>` panels so cumulative diff / drift / EVM tables print fully.
- `-webkit-print-color-adjust: exact` ensures chart colors render in PDF.

### I. JSDoc + module-level comments
All 4 JS modules now lead with a `/** @file ... @description ... @module ... @requires ... */` banner.  Function-level JSDoc on every public function (`escapeHtml`, `triggerCycle`, `switchTab`, `toggleTheme`, `exportChart`, `loadEvm`, `loadDcma`, `loadHealthHistoryChart`, `loadVariance`, `loadPortfolio`, `loadDiff`, `loadChanges`, `loadBaselineDrift`, listen-in functions, etc.).

## 15. Tier 3 — Light/dark theme toggle

- Header button (☀/🌙) plus Ctrl/Cmd+L shortcut.
- `[data-theme="light"]` palette in `dashboard.css` flips backgrounds (#0d1117 → #f6f8fa, #161b22 → #ffffff), text (#e6edf3 → #1f2328), and borders (#21262d → #d0d7de).  Accent / health colors unchanged.
- Persists to `localStorage["ims_theme"]`; restored on every page load via `_restoreTheme()` in DOMContentLoaded.
- Print stylesheet always uses light palette.

## 16. Final test results

```
Full unit suite:    1068 / 1068 passing in 345.64s   (was 1009/1010 with TD-042 flake)
Phase 12 suite:       58 /   58 passing in   4.83s   (NEW)
Dashboard suite:     305 /  305 passing                (unchanged from Phase 12)
Integration smoke:   144 /  144 passing                (unchanged)
```

Test count increased by **+58** (Phase 12 class).  The previously flaky `test_flat_denial_retry_limit_still_works` is now deterministic and runs in 0.18s (vs 20s prior with live API calls).

## 17. Updated rollback plan

Phase 12.1 changes layer cleanly on top of Phase 12 — the rollback story is identical:

1. **Soft (no redeploy):** `IMS_LEGACY_DASHBOARD=1` → renders original `index.html`.
2. **Branch:** `git checkout backup/pre-dashboard-overhaul`.
3. **Hard:** `git revert <Phase 12.1 commit>` then `git revert b1301f6` to peel off both phases.

Rollback tag and branch from Phase 12 are still pushed to remote.

---

**Phase 12.1 build session duration:** ~1.5 hours (TD resolution + tests + Tier 2/3 features + docs).
**Lines added (net):** ~1,200 (estimate: 58 new tests + 200 lines of CSS for light/print + 250 lines of JS for shortcuts/export/theme + 250 lines demo data + 150 lines of JSDoc).
**Risk level:** Low — purely additive, every change covered by tests, soft rollback unchanged.
