# Observer-Mode Testing Companion

**Purpose:** quick-reference for hands-on user testing of the IMS Command Center (Phase 15 ATLAS console) with the user driving and Claude observing/instrumenting.

**Status:** active companion as of 2026-05-08 · React-based dashboard at `http://localhost:9000/`

---

## 0. Pre-flight

```powershell
# Confirm server is running
netstat -ano | Select-String ":9000\s.*LISTENING"

# If not, start it:
cd "C:\Users\forbe\OneDrive\Documents\AI Projects\04 - IMS AGENT\ims-agent"
python main.py --serve
# Logs stream to logs/scheduler.log
```

Open `http://localhost:9000/` in Chrome.  Hard-refresh (`Ctrl+Shift+R`) the first time after any code change so the Babel-compiled JSX cache is cleared.

---

## 1. What to look at (visual inventory)

### Header bar (cross-tab, always visible)
| Element | Expected behavior |
|---|---|
| **A** logo (gradient square) | Static — clicking does nothing currently |
| **ATLAS · IMS AGENT** brand | Static text |
| **01 / 02 / 03** numbered tabs | Click to switch; underline + opacity changes on hover; F1 / F2 / F3 keyboard shortcuts |
| **● LIVE** indicator | Pulsing green dot · static "LIVE" text |
| **Wall clock** | Updates every 1 s |
| **OP · M.OYELOWO** | Static operator label |
| **Theme toggle** (sun ☀ / moon 🌙) | Click or `⌘L` toggles light ↔ dark; choice persists to `localStorage` |

### Ticker bar (cross-tab, just below header)
Scrolling KPI strip with 13 items (BEI · SFA · SPI · CPI · BCWP · EAC · VAC · P50 · P80 · DCMA-HF · CAMs · CYCLE · MODE).  Each shows value + small delta arrow.  Loop is seamless.

### Hero (per tab)
Top of each tab: large typographic title + 3-4 action buttons + 4 hero KPI tiles.  Tab-specific:

| Tab | Hero buttons |
|---|---|
| **01 IMS Stats** | ▶ JUMP TO SCHEDULE · ⇣ EXPORT CYCLE C-19 · ⌘ CHANGE BASELINE *(all currently UI-only)* |
| **02 PM Portal** | ⌗ GENERATE EXECUTIVE BRIEFING · ⇣ EXPORT CPR FMT-5 *(UI-only)* |
| **03 Agent Controls** | ▶ FORCE CYCLE *(**LIVE** — fires `POST /api/trigger?force=true`)* · ⏵ DRY-RUN · ■ KILL SWITCH *(both stubs)* |

---

## 2. Tab 1 — IMS Stats & Info

### What's wired to live data
| Tile | Source |
|---|---|
| Hero KPIs (BEI / SFA / HIGH-RISK MILESTONES / P80 FINISH) | `/api/state` EVM + milestone count |
| BEI · SFA · HRM sparkline tiles | `/api/evm/history` (last 24 cycles) |
| EVM KPIs panel (SPI/SV/% Complete/BEI/BAC/EAC/VAC/BCWP) | `/api/state.evm.program` |
| Per-CAM WBS breakdown table | `/api/state.evm.by_cam` |
| DCMA 14-point cells | `/api/state.dcma.checks` |

### What's still mock (no backend endpoint yet)
| Tile | Why |
|---|---|
| **Summary Schedule Gantt** (10 phase rows + 7 milestones) | Needs `GET /api/schedule/summary` endpoint to expose phase boundaries |
| **SRA Monte-Carlo Histogram** (10,000 sims, P10–P90 markers, cumulative line) | Needs `GET /api/sra` endpoint to expose histogram bins + percentiles |

### What to verify
- All 10 phase rows render with critical-path coloring (red) vs non-critical (blue)
- "GHOST OVERLAY" checkbox toggle reveals dashed prior-cycle bars
- "Current · v2026.10" / "Prior · v2026.09" segmented toggle swaps the shown schedule
- Hover any task bar → tooltip with `id · name · start · end · cp · complete %`
- BEI tile shows **RED** value (real BEI from production cycle is ~0.82 < 0.85 threshold)
- DCMA cells color-graded: green PASS · yellow WARN · red FAIL

---

## 3. Tab 2 — Program Management Portal

### What's wired
| Tile | Source |
|---|---|
| Top Risks (3 enumerated cards w/ impact + probability) | `/api/state.top_risks` (LLM-synthesized prose, parsed into 3 items) |
| Recommended Actions (4 enumerated cards w/ priority pill) | `/api/state.recommended_actions` (LLM prose) |
| Schedule Health History line chart | `/api/health/history?n=24` |
| Variance Narrative (CPR Format 5) | `/api/state.variance.narrative` |

### What's static / UI-demo
| Element | Why |
|---|---|
| **Generate Briefing** modal | Simulates streaming completion (1.4 s timeout) then shows a hardcoded sample briefing. Real `/api/briefing` exists — wiring to the modal is a future task. |
| **SCHEDULE AUTO** button | Shows an alert(). |
| **REGENERATE / EDIT / APPROVE FOR REPORT** buttons (variance footer) | UI only. |

### What to verify
- All 3 Top Risks pills (CRITICAL · HIGH · MODERATE) right-aligned at top of each item — **this was the fix you just spotted**
- All 4 Recommended Actions pills (NOW · THIS WEEK · WITHIN 2 CYCLES · RECURRING) right-aligned similarly
- Schedule Health History line shows real downward trend (RED zone, current value ~35)
- Generate Briefing modal opens, shows "▸ ATLAS · drafting briefing…" pipeline animation, then renders the briefing
- Variance Narrative body is full prose (not "No variance narrative yet.")

---

## 4. Tab 3 — ATLAS Agent Controls

### What's wired (LIVE — caution)
| Element | Action |
|---|---|
| **▶ FORCE CYCLE** (hero or agent-bar) | `POST /api/trigger?force=true` — fires a real cycle |
| **CAMS RESPONDED** KPI | `/api/state.completion_report` + `/api/state.cam_response_status` |
| **CAM Response Status table** | `/api/state.cam_response_status` (5 real CAMs) |
| **What Changed Diff Viewer** | `/api/diff/latest` (real PROC-01..PROC-09 task changes) |
| **Change History Cumulative Diff** | `/api/changes` (real cycle range) |
| **Baseline Drift Report** | `/api/baseline-drift` |
| **Live Interview Listen-In** | `EventSource('/api/interview-stream')` + backfill from `/api/interview-recent` |

### What's stub / UI-only
| Element | Status |
|---|---|
| ⏵ **DRY-RUN** button | Opens a confirm modal that does nothing on confirm — no backend endpoint. |
| ■ **KILL SWITCH** button | Same — confirm-and-noop. |
| **Mode** segment (Autonomous / Supervised / Paused) | Pure UI state — no backend yet. |
| **STEP / HOLD / RESUME** controls in Cycle In Progress | UI-only phase-stepper. |
| **PAUSE STREAM / EXPORT TRANSCRIPT / END SESSION** buttons (Listen-In footer) | UI-only. |

### What to verify
- Real CAM names in the CAM Response Status table: Alice Nguyen, Bob Martinez, Carol Smith, Eva Johnson, David Lee
- Diff cycle dropdown changes selection but always shows the same data (it's a UI-only filter for now)
- Live Interview Listen-In: should show either real SSE turns (if a cycle is running) or fall back to the scripted demo loop after 8 s
- Clicking **FORCE CYCLE** in the hero shows inline `▶ TRIGGERING…` then `✓ TRIGGERED` (no full-page reload)

---

## 5. Known gaps / not-yet-wired

These are the items where the UI is built but the backend isn't reachable yet. **Don't file as bugs — they're documented Phase 16 candidates.**

1. **SRA histogram** (Tab 1) — needs `GET /api/sra`
2. **Summary Schedule Gantt** (Tab 1) — needs `GET /api/schedule/summary`
3. **DRY-RUN** + **KILL SWITCH** endpoints (Tab 3) — need `POST /api/admin/dry-run` + `POST /api/admin/kill-switch`
4. **Executive Briefing modal** (Tab 2) is a UI demo — real `/api/briefing` exists but the modal doesn't fetch it yet
5. **Mode segment** (Tab 3) doesn't persist or affect agent behavior
6. **Hero export buttons** (Tab 1 — EXPORT CYCLE C-19, CHANGE BASELINE) — UI only
7. **Briefing footer buttons** (Tab 2 — SCHEDULE AUTO, EXPORT CPR FMT-5) — UI only
8. **Diff cycle dropdown** (Tab 3) doesn't refetch on change

---

## 6. How to flag an issue during testing

When you spot something, just describe it.  The detail that helps me debug fastest:

1. **Tab and tile name** (e.g. "Tab 2, Top Risks panel")
2. **Symptom** (visual misalignment, wrong data, button does nothing, etc.)
3. **Screenshot** if visual — annotated is great but not required
4. **Reproduction steps** if interactive (e.g. "click X, then Y")

I'll triage into one of three buckets:
- **Bug** — should be fixed before any further work
- **Cosmetic polish** — fix it now if quick, defer if it's a rabbit hole
- **Phase 16 work** — backend not wired yet, document it for the next phase

---

## 7. Quick console snippets

Open Chrome DevTools (`F12`) → Console:

```js
// Dump the hydrated live state
window.__IMS_LIVE.state.cycle_id
window.__IMS_LIVE.state.evm.program

// Force a tab switch from console
location.hash = '#agent'   // or #stats, #portal

// Toggle theme manually
document.documentElement.setAttribute('data-theme', 'light')

// Check current CAMs (live or mock)
window.CAMS

// Replay the demo interview script (Listen-In)
// Reload the page; if no real interview is active, the 8-second SSE watchdog
// kicks in and the scripted INTERVIEW_SCRIPT starts cycling.
```

---

## 8. Test harness for me (Claude)

To rerun the suite without disturbing the live server:

```bash
# Default (771 passed, 407 legacy skipped)
python -m pytest tests/ -q -m "not integration"

# Phase 15 suite only (fastest)
python -m pytest tests/test_phase15_dashboard_rebuild.py -q

# Legacy regression suite (against IMS_LEGACY_DASHBOARD=1 — soft-rollback path)
IMS_LEGACY_DASHBOARD=1 python -m pytest tests/test_phase14_modern_polish.py -q

# Single test by name pattern
python -m pytest tests/ -k "test_react_shell" -v
```

---

## 9. Rollback if something goes badly wrong

```bash
# Soft (no redeploy) — env flag falls back to original Phase 12 dashboard
$env:IMS_LEGACY_DASHBOARD = "1"
# then restart the server: Stop-Process -Name python; python main.py --serve

# Branch — switch the whole repo state to the pre-Phase-15 snapshot
git checkout pre-dashboard-zip-rebuild-2026-05-08

# Hard revert (creates a clean revert commit on master)
git revert 864cca2 ce5ab69   # PM-Portal fix + Phase 15 in one go
git push origin master
```

---

**Maintainer:** Claude · **Last updated:** 2026-05-08 · **Status:** active companion
