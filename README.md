# IMS Agent

[![CI](https://github.com/johnfforbes3/ims-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/johnfforbes3/ims-agent/actions/workflows/ci.yml)

An AI agent that autonomously manages Integrated Master Schedule (IMS) updates for defense programs. It conducts structured voice interviews with Cost Account Managers (CAMs), updates the schedule, runs critical path and Monte Carlo SRA analysis, synthesizes schedule intelligence, and delivers output via a live dashboard, Slack, email, and a natural language Q&A interface.

**Current status: Phase 15 complete + PM Portal pill-alignment fix. Full dashboard rebuild from user-supplied design zip. React 18 + Babel Standalone single-page app with terminal/aerospace aesthetic (IBM Plex fonts, sky-blue/lime accent, sticky ticker bar, full SVG Gantt + SRA + line charts). All third-party deps vendored locally (no CDN — ITAR-clean). 3 tabs: IMS Stats & Info, Program Management Portal, Agent Controls. Live data wired from /api/state, /api/evm/history, /api/health/history, /api/diff/latest, /api/changes, /api/baseline-drift, /api/interview-stream (SSE). Core agent (server.py, cycle_runner, interview_orchestrator, LLM interface) UNCHANGED. **771/771 non-legacy tests passing** (0 failed) + 63 Phase 15 tests + 407 legacy tests (Phase 12/12.1/14) skipped by default via `@pytest.mark.legacy`. Soft rollback `IMS_LEGACY_DASHBOARD=1` still works. Rollback tag: `pre-dashboard-zip-rebuild-2026-05-08`. Production cycle `20260507T222726Z`: 5/5 CAMs (Teams chat relay), health=RED.**

---

## Quick Start

### Prerequisites

- Python 3.13
- Anthropic API key (set in `.env`)

### Setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/johnfforbes3/ims-agent.git
cd ims-agent

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY and IMS_FILE_PATH

# 5. Run a single analysis cycle
python main.py --run

# 6. Start the dashboard + Q&A server (http://localhost:9000)
python main.py --serve

# 7. Start the dashboard + recurring scheduler (weekly by default)
python main.py --schedule
```

### Running Tests

```bash
pytest tests/ -v         # all 1010 tests (4 Whisper integration tests skipped)
pytest tests/ -q         # quiet summary only
```

---

## What It Does

Each automated cycle:

1. **Interviews all CAMs** — structured voice conversation per CAM capturing percent complete, blockers, and risk flags
2. **Validates inputs** — flags backwards movement, large jumps, and missing responses before writing
3. **Updates the IMS** — writes validated percent completes and notes back to the XML schedule
4. **Runs analysis** — critical path (CPM) and Monte Carlo SRA (N=1000) on the updated schedule
5. **Synthesizes intelligence** — LLM connects schedule data + CAM context to produce narrative, top risks, and PM actions
6. **Distributes output** — updates live dashboard, posts to Slack, sends email, optionally generates a voice briefing

Between cycles, the PM can ask natural language questions via the dashboard chat widget or Slack `/ims` command. The Q&A engine answers from the synthesized state and can call IMS schedule tools (float, dependencies, task details) directly when needed.

---

## Project Structure

```
ims-agent/
├── agent/
│   ├── file_handler.py         — IMS XML parsing and write-back (+ predecessor_links, float, constraints)
│   ├── llm_interface.py        — All Anthropic SDK calls (single entry point)
│   ├── critical_path.py        — CPM calculation and float analysis
│   ├── sra_runner.py           — Monte Carlo SRA engine (N=1000, beta-PERT)
│   ├── report_generator.py     — Markdown report + IMS diff/drift sections
│   ├── evm_engine.py           — EVM metrics (BAC/BCWP/BCWS/SPI/SV/EAC/BEI) — Phase 9.2
│   ├── dcma_assessment.py      — DCMA 14-Point Assessment Engine — Phase 9.3
│   ├── variance_analyst.py     — LLM-backed CPR Format 5 variance narrative — Phase 9.4
│   ├── executive_briefing.py   — Self-contained HTML executive brief generator — Phase 9.5
│   ├── portfolio.py            — Multi-program portfolio health aggregator — Phase 9.6
│   ├── cam_directory.py        — CAM registry, scheduling, retry logic
│   ├── cycle_runner.py         — Full cycle orchestration
│   ├── cycle_state.py          — Cycle state persistence
│   ├── interview_orchestrator.py — Parallel CAM interview coordination
│   ├── scheduler.py            — APScheduler cron-based cycle trigger
│   ├── validation.py           — Input validation (backwards movement, jumps)
│   ├── notifier.py             — Slack and email output
│   ├── voice_briefing.py       — TTS voice briefing generation
│   ├── slack_command.py        — Slack /ims slash command (Socket Mode)
│   ├── auth.py                 — JWT token issuance + Bearer auth + JTI blocklist (Phase 7.2)
│   ├── siem.py                 — SIEM syslog handler configuration (Phase 7.2)
│   ├── ims_diff.py             — Per-cycle IMS diff, cumulative merge, baseline drift (Phase 6.5/7.4)
│   ├── metrics.py              — Thread-safe in-memory counters + Prometheus text format
│   ├── approval_store.py       — JSON-backed PM approval queue
│   ├── dashboard/
│   │   ├── server.py           — FastAPI server (all HTTP endpoints + JWT auth)
│   │   └── templates/
│   │       └── index.html      — Live dashboard with Q&A chat, CAM pills, diff/drift tabs
│   ├── qa/
│   │   ├── context_builder.py  — Intent detection + context slicing (30s TTL cache)
│   │   ├── qa_engine.py        — Q&A engine (direct + LLM-routed)
│   │   └── ims_tools.py        — Anthropic tool_use handlers for raw IMS queries
│   └── voice/
│       ├── interview_agent.py      — Conversation state machine (12 states)
│       ├── cam_simulator.py        — Claude-powered CAM simulator (dev/test)
│       ├── stt_engine.py           — STT abstraction (Whisper / mock)
│       ├── tts_engine.py           — TTS abstraction (ElevenLabs / Azure / mock)
│       ├── transcript_extractor.py — Post-interview LLM structured data extraction
│       ├── teams_connector.py      — Teams/ACS voice connector (Tier 3)
│       └── teams_chat_connector.py — Teams Chat Bot connector (Tier 4)
├── agent/demo_chat.py          — Teams Chat demo runner (--demo-chat mode)
├── tests/                      — pytest test suite (1010 tests)
├── data/
│   ├── sample_ims.xml          — Synthetic 100-task AI Agent Server Rack IMS
│   ├── ims_master/             — Timestamped .mpp master (source of truth)
│   ├── ims_exports/            — Versioned XML exports + diff JSON/Markdown per cycle
│   ├── dashboard_state.json    — Live dashboard state (updated each cycle; incl. EVM, DCMA, variance)
│   ├── cycle_history.json      — Per-cycle summary history
│   ├── portfolio.json          — Multi-program portfolio registry (Phase 9.6)
│   └── snapshots/              — Pre-write IMS snapshots (rollback source)
├── reports/
│   ├── cycles/                 — Per-cycle status JSON (gitignored)
│   └── briefings/              — Generated executive brief HTML files (Phase 9.5)
├── docs/
│   ├── STATUS.md               — Single source of truth for current system state
│   ├── CMMC_GAP.md             — CMMC Level 2 gap analysis (6 gaps REMEDIATED)
│   ├── IR_PLAN.md              — Incident response plan (P1–P4, IR.2.092)
│   ├── DR_RUNBOOK.md           — Disaster recovery runbook + credential rotation (§9)
│   ├── ONBOARDING.md           — Customer onboarding checklist
│   ├── decisions.md            — Architecture Decision Records (ADR-001–003)
│   └── teams-integration-decision.md — ADR-004–006 (ACS, TTS, STT)
├── .env.example                — All environment variables documented
├── requirements.txt
├── Dockerfile                  — Non-root production container image
├── docker-compose.yml          — Local dev compose
├── docker-compose.prod.yml     — Production compose (named volumes, resource limits)
├── main.py                     — Entry point (--run, --serve, --schedule)
├── IMS-AGENT-PROGRAM-PLAN.md   — Authoritative program plan
├── TECHNICAL-DEBT.md           — Known issues and deferred work
├── CHANGELOG.md                — Version history by phase
├── DEPLOYMENT.md               — Step-by-step production deployment guide
├── OPERATIONS.md               — Monitoring, troubleshooting, backup/restore
├── SECURITY.md                 — Security architecture, JWT auth, CMMC posture
├── API.md                      — All endpoints with auth requirements and schemas
├── CONFIGURATION.md            — All env vars with defaults and descriptions
└── TEST_RESULTS.md             — Test procedure run history
```

---

## Phase Status

| Phase / Tier | Name | Status | Completed |
|---|---|---|---|
| 1 | Proof of Concept | ✅ Complete | 2026-04-25 |
| 2 | Voice Interview Layer | ✅ Complete (simulator) | 2026-04-25 |
| 3 | Full Automation Loop | ✅ Complete | 2026-04-26 |
| 4 | Q&A Interface + IMS Tools | ✅ Complete | 2026-04-26 |
| 5 | Production Hardening | ✅ Complete | 2026-04-26 |
| Tier 3 | Live Teams Voice Demo | ✅ Complete | 2026-04-26 |
| Tier 4 | Teams Chat Bot Interview | ✅ Complete | 2026-04-27 |
| 6.0–6.6 | Core Integrity, Observability, Security, IMS Audit Trail, Pilot Docs | ✅ Complete | 2026-05-03 |
| 7.1 | Technical Debt Sprint | ✅ Complete — 336 tests | 2026-05-03 |
| 7.4 | Platform Enhancements | ✅ Complete — 359 tests | 2026-05-03 |
| 7.2 | Security & Compliance (CMMC Level 2) | ✅ Complete — 375 tests | 2026-05-03 |
| **7.3** | **EAC Date Interview Collection** | ✅ **Complete — 404 tests** (infra items awaiting deployment) | 2026-05-03 |
| 8.3 | Advanced SRA (beta-PERT), bootstrap CLI, Whisper integration tests | ✅ Complete — 424 tests | 2026-05-04 |
| **8.4** | **Latency & reliability sprint** — `claude-haiku-4-5` model fix, validation fix, `force=true` trigger, Listen-In dropdown, CAM simulator markdown fix | ✅ **Complete — 445 tests** | **2026-05-06** |
| **8.5** | **CI & infrastructure** — GitHub Actions CI workflow, Dockerfile Python 3.13 | ✅ **Complete — 445 tests** | **2026-05-06** |
| **9.2** | **EVM Metrics Engine** — BAC/BCWP/BCWS/SPI/SV/EAC/BEI per program and CAM | ✅ **Complete** | **2026-05-06** |
| **9.3** | **DCMA 14-Point Assessment** — auto-scored schedule quality | ✅ **Complete** | **2026-05-06** |
| **9.4** | **Variance Analysis Narratives** — LLM-backed CPR Format 5 | ✅ **Complete** | **2026-05-06** |
| **9.5** | **Executive Briefing Generator** — one-click self-contained HTML brief | ✅ **Complete** | **2026-05-06** |
| **9.6** | **Portfolio View** — multi-program health aggregation — **611 tests** | ✅ **Complete** | **2026-05-06** |
| **10** | **Full System Integration Test Suite** — relay wiring, SSE stream, API smoke, E2E cycle | ✅ **Complete — 721 tests** | **2026-05-07** |
| **11** | **Comprehensive Dashboard UI Test Suite** — 289 element-by-element dashboard tests (18 classes) | ✅ **Complete — 1010 tests** | **2026-05-07** |
| 7.5 | First Customer Pilot Execution | ⏳ Awaiting customer engagement | — |

**Phase 6 note:** 4 Core Integrity bugs fixed; Prometheus metrics + extended `/health`; secrets hardening + CMMC gap analysis; LLM retry backoff + DR runbook; IMS audit trail (`ims_diff.py`, per-cycle diff JSON/Markdown, `GET /api/diff/{cycle_id}`); customer onboarding docs.

**Phase 7.2 note:** JWT auth (`POST /api/auth/token`, HS256, 1-hour expiry), JTI replay blocklist (CMMC IA.3.084), read/admin tier separation, key age alert in `GET /health` (CMMC SC.3.187), SIEM syslog (`agent/siem.py`, CMMC AU.3.045), formal incident response plan (`docs/IR_PLAN.md`), credential rotation procedures (`docs/DR_RUNBOOK.md §9`). 6 HIGH CMMC gaps remediated. 375 tests passing.

**Phase 7.3 note:** New `AWAITING_EAC_DATE` interview state collects CAM-provided projected finish dates for all 1–99% tasks. LLM date extractor (`_classify_eac_date`) resolves absolute dates, relative dates, "on schedule", and uncertain responses. `SRARunner(eac_dates=...)` overrides remaining-duration estimates with CAM EAC dates. Cycle report "Tasks Behind Schedule" table expanded with CAM Forecast and Δ Days columns. 29 new tests in `test_eac_date.py`. Grafana/log-aggregation infra items deferred to deployment platform.

**Phase 7.4 note:** Per-CAM dashboard progress pills, cumulative diff (`GET /api/changes`), baseline drift alert (`GET /api/baseline-drift`), Q&A 30s TTL cache (TD-016), `SIMULATOR_CALL_DELAY_MS` rate limiting (TD-009), cycle report IMS Diff Summary and Baseline Drift Alert sections.

**Phase 8.3 note:** Beta-PERT three-point SRA sampling (`_pert_variate`), `--bootstrap-sessions` CLI for proactive CAM onboarding via Graph API, Whisper STT integration tests (`@pytest.mark.integration`). 424 tests.

**Phase 8.4 note:** `claude-haiku-4-5` model fix eliminated HTTP 404 errors and reduced interview latency from 30-60s to ~5s/turn. Validation backwards-movement rule now distinguishes explained regressions (warning) from unexplained (hard failure). Trigger Cycle button always sends `?force=true` to allow immediate re-runs after failed cycles. Listen-In panel per-interview dropdown filters transcript and audio to a single CAM. Graph CAM Responder poll/delay reduced (2s / 0.5s). CAM simulator markdown fix: `LLMInterface.ask()` now accepts an optional `system` override; `_SIMULATOR_SYSTEM_PROMPT` (the "No Markdown — plain speech only" instruction) is now wired into every `CAMSimulator.respond()` call — eliminating asterisks and other markdown from simulated CAM responses. Production cycle `20260505T121010Z` verified end-to-end.

**Phase 8.5 note:** GitHub Actions CI pipeline (`.github/workflows/ci.yml`) — Windows runner, Python 3.13, Java 21. Runs `pytest tests/ -q -m "not integration"` on every push and PR to main. Requires `ANTHROPIC_API_KEY` GitHub Actions secret. Dockerfile base image corrected from `python:3.11-slim` to `python:3.13-slim` to match the development and production runtime.

**Phase 9.2–9.6 note:** Five executive-grade features added in one sprint. EVM engine uses task `duration_days` as the budget proxy (BAC unit: work-days) to produce schedule-based SPI, SV, EAC, and BEI without cost data. DCMA 14-point assessment parses MSPDI `PredecessorLink`, `ConstraintType`, and `TotalSlack` fields for all 14 checks. Variance narrative is an LLM-generated CPR Format 5 text incorporating EVM, DCMA, CAM interview inputs, and IMS diff. Executive brief is a fully self-contained HTML file (no CDN dependencies) suitable for print-to-PDF distribution. Portfolio view reads a `data/portfolio.json` registry and aggregates health across all registered programs — any RED → RED, all GREEN → GREEN, else YELLOW. All five subsystems are wired into the cycle runner and gracefully degrade on individual module failure. 611 tests passing.

**Phase 10 note:** Full System Integration Test Suite — 110 new integration tests covering Teams relay wiring, SSE stream endpoint, full API smoke suite, and end-to-end cycle integration. 6 bug fixes discovered and resolved during integration testing. 721 tests passing.

**Phase 11 note:** Comprehensive Dashboard UI Test Suite — 289 element-by-element dashboard tests across 18 test classes covering all panels, KPIs, tables, EVM/DCMA/briefing/portfolio UI paths, and JavaScript API paths. Graph CAM Responder lookback window fix (30s→2h) to prevent interview stall on responder restart during active cycle. 1010 tests passing.

**Phase 12 note:** IMS Command Center 3-tab dashboard overhaul — monolithic 1822-line `index.html` split into `base.html` + 3 tab partials (`tabs/metrics.html`, `tabs/pm.html`, `tabs/atlas.html`). All CSS/JS extracted to `agent/dashboard/static/`. Chart.js v4 vendored locally (no CDN, ITAR-friendly). New visual data layer: 4 EVM rolling-24-cycle sparklines (SPI/CPI/BEI/SV), schedule-health trend line with G/Y/R zone bands, milestone-risk and portfolio donuts, DCMA violations and baseline-drift bar charts. Two new endpoints: `GET /api/evm/history?n=24`, `GET /api/health/history?n=24`. Soft-rollback flag `IMS_LEGACY_DASHBOARD=1`. Rollback snapshot at tag `pre-dashboard-overhaul-2026-05-08`.

**Phase 12.1 note:** Overnight polish on top of Phase 12. Resolved TD-042 (interview-test flake → mocked LLM in test, deterministic), TD-046 (CAMSimulator eager LLM construction → lazy in `respond()`), TD-048 (CI Node.js 20 deprecation → `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true`). Added demo mode (`GET /?demo=1` injects 24 cycles of synthetic data so all charts populate without a real run), keyboard shortcuts (Ctrl/Cmd+1/2/3 jumps between tabs; Ctrl/Cmd+L toggles theme), chart PNG export (📥 button on each chart, uses Chart.js `toBase64Image`), print stylesheet (`@media print` cascades all tab panels onto pages for executive PDF export), light/dark theme toggle (`[data-theme="light"]` palette, persisted in `localStorage`). 58 dedicated Phase 12 tests added. **1068/1068 unit tests passing.**

**Phase 14 note:** Modern Polish Pass on top of Phase 12.1 — purely additive visual polish, zero structural change. Glassmorphism on every card via `backdrop-filter: blur(14px) saturate(140%)` + 1px white inset highlight. Animated body gradient (3 radial color washes with a 40s diagonal pan). Conic-gradient progress rings on the HIGH Risk Milestones tile (Metrics) and CAMs Responded tile (ATLAS) — pure CSS, no library. Animated KPI counters (`animateNumber` with `easeOutQuart`, `tabular-nums` to keep digits stable). Skeleton-loader utility classes (`.skeleton`, `.skel-line`, `.skel-block`) and `markSkeleton`/`clearSkeleton` JS helpers. View Transitions API hook on tab swap (`document.startViewTransition()` with named pseudo-elements) — graceful fallback when unsupported or under reduced-motion. Hover micro-interactions: cards lift, chips lift, buttons press, logo rotates, gradient underline grows from center on tab buttons. Aurora strip animation under the header. Breathing animation on the cycle-in-progress card. Chart.js global defaults tuned (900ms easeOutQuart entry, polished tooltips, thicker lines, rounded bars). All animations respect `prefers-reduced-motion: reduce`. 47 dedicated Phase 14 tests. **1115/1115 unit tests passing.** Rollback tag: `pre-modern-polish-2026-05-08`.

**Phase 15 note:** Complete dashboard rebuild from a user-supplied design zip. New design is a **React 18 + Babel Standalone** single-page app with a terminal/aerospace aesthetic (IBM Plex Mono/Sans, sky-blue + lime accent, sticky scrolling ticker bar, full SVG Gantt with critical-path coloring + ghost overlay, Monte-Carlo SRA histogram with cumulative line + percentile markers, 6-month KPI sparklines, RYG orb indicator). All third-party deps **vendored locally** at `/static/vendor/` (React 18.3.1 production, Babel 7.29.0 standalone, IBM Plex Latin subset 11 woff2 files) — zero CDN dependencies, ITAR-clean. 3 tabs: **IMS Stats & Info** (Summary Schedule Gantt, BEI/SFA/HRM tiles, SRA, EVM, DCMA-14), **Program Management Portal** (Executive Briefing CTA, Top Risks, Recommended Actions, Schedule Health History, Variance Narrative), **Agent Controls** (Mode segment, Force/Dry-Run/Kill Switch CTAs, Cycle In Progress phase pipeline, CAM Response Status, Diff Viewer, Change History, Baseline Drift, Live Interview Listen-In SSE). Live data wired from `/api/state` + `/api/evm/history` + `/api/health/history` + `/api/diff/latest` + `/api/changes` + `/api/baseline-drift` + `/api/interview-stream` via a hydration shim (`api.js`) that overrides `window.*` mock globals before React mounts. SSE stream falls back to scripted demo loop when no live interview is active. **Core agent code unchanged** (server.py, cycle_runner, interview_orchestrator, LLM interface, all backend modules untouched — Phase 15 is a pure UI replacement). Phase 12/12.1/14 dashboard tests marked `@pytest.mark.legacy` and skipped by default; run them with `pytest -m legacy` or `IMS_LEGACY_DASHBOARD=1`. 63 new Phase 15 tests covering shell, vendored assets, JSX modules, data + api layer, agent API regression, legacy rollback path. **770/770 non-legacy unit tests passing.** Rollback tag: `pre-dashboard-zip-rebuild-2026-05-08`.

---

## Key Commands

| Command | Description |
|---|---|
| `python main.py --run` | Run one full cycle immediately |
| `python main.py --serve` | Start dashboard + Q&A server on port 9000 |
| `python main.py --schedule` | Start dashboard + recurring scheduler |
| `python main.py --run --serve` | Run one cycle then keep server running |
| `python main.py --demo-chat --cam "Alice Nguyen"` | Teams Chat Bot interview demo (single CAM) |
| `python main.py --demo-interview --meeting-url <url> --callback-url <url>` | Teams voice demo (Tier 3, requires ACS) |

---

## Environment Variables

Copy `.env.example` to `.env` and configure. Minimum required:

```bash
ANTHROPIC_API_KEY=sk-ant-...
IMS_FILE_PATH=data/sample_ims.xml
```

See `.env.example` for the full list with documentation for all 40+ variables covering: Anthropic API, SRA settings, TTS/STT engines, Teams/ACS integration, Slack, email, dashboard, scheduler, and validation thresholds.

---

## Key Design Decisions

See [docs/decisions.md](docs/decisions.md) for full rationale. Summary:

| Component | Decision | Rationale |
|---|---|---|
| IMS format | MSPDI XML | No Java dependency; planner exports from MS Project |
| SRA | Python Monte Carlo (N=1000) | No external tool dependency; fully testable |
| LLM | Anthropic Claude API | Best reasoning quality; single entry point in `llm_interface.py` |
| Voice platform | Azure ACS + Teams (stub) | Standard at defense contractors; Azure provisioned |
| Dashboard | FastAPI + vanilla JS | Minimal footprint; no build step |
| Q&A | Tool-use agentic loop | LLM decides when to query raw IMS vs synthesized state |

**ITAR note:** For production deployment with ITAR/CUI data, set `LLM_BASE_URL` to any Ollama-compatible local endpoint. All LLM calls route through `agent/llm_interface.py` — no code changes required.

---

## Architecture Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — full technical reference (module map, state machine, Teams relay loop, env setup, CAM directory, gotchas)
- [ADR-001: MSPDI XML over binary .mpp](docs/decisions.md#adr-001)
- [ADR-002: Python Monte Carlo SRA](docs/decisions.md#adr-002)
- [ADR-003: Anthropic API for Phase 1–4](docs/decisions.md#adr-003)
- [ADR-004–006: Azure ACS, ElevenLabs TTS, Whisper STT](docs/teams-integration-decision.md)

## Production Documentation

- [DEPLOYMENT.md](DEPLOYMENT.md) — step-by-step deploy guide (Docker Compose)
- [OPERATIONS.md](OPERATIONS.md) — monitoring, alerts, backup/restore, common issues
- [SECURITY.md](SECURITY.md) — RBAC, secrets, ITAR posture, input validation, dependency audit
- [API.md](API.md) — all endpoints with auth requirements and response schemas
- [CONFIGURATION.md](CONFIGURATION.md) — every env var with default, required/optional, description
- [CHANGELOG.md](CHANGELOG.md) — version history by phase
- [TEST_RESULTS.md](TEST_RESULTS.md) — test procedure run history (1010 tests passing)
