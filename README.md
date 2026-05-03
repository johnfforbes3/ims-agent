# IMS Agent

An AI agent that autonomously manages Integrated Master Schedule (IMS) updates for defense programs. It conducts structured voice interviews with Cost Account Managers (CAMs), updates the schedule, runs critical path and Monte Carlo SRA analysis, synthesizes schedule intelligence, and delivers output via a live dashboard, Slack, email, and a natural language Q&A interface.

**Current status: Phase 7.2 COMPLETE — JWT auth, SIEM syslog, IR plan, CMMC gap remediation. 375 tests passing.**

---

## Quick Start

### Prerequisites

- Python 3.11+
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
pytest tests/ -v         # all 375 tests
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
│   ├── file_handler.py         — IMS XML parsing and write-back
│   ├── llm_interface.py        — All Anthropic SDK calls (single entry point)
│   ├── critical_path.py        — CPM calculation and float analysis
│   ├── sra_runner.py           — Monte Carlo SRA engine (N=1000)
│   ├── report_generator.py     — Markdown report + IMS diff/drift sections
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
│       ├── interview_agent.py      — Conversation state machine (11 states)
│       ├── cam_simulator.py        — Claude-powered CAM simulator (dev/test)
│       ├── stt_engine.py           — STT abstraction (Whisper / mock)
│       ├── tts_engine.py           — TTS abstraction (ElevenLabs / Azure / mock)
│       ├── transcript_extractor.py — Post-interview LLM structured data extraction
│       ├── teams_connector.py      — Teams/ACS voice connector (Tier 3)
│       └── teams_chat_connector.py — Teams Chat Bot connector (Tier 4)
├── agent/demo_chat.py          — Teams Chat demo runner (--demo-chat mode)
├── tests/                      — pytest test suite (375 tests)
├── data/
│   ├── sample_ims.xml          — Synthetic 100-task AI Agent Server Rack IMS
│   ├── ims_master/             — Timestamped .mpp master (source of truth)
│   ├── ims_exports/            — Versioned XML exports + diff JSON/Markdown per cycle
│   ├── dashboard_state.json    — Live dashboard state (updated each cycle)
│   ├── cycle_history.json      — Per-cycle summary history
│   └── snapshots/              — Pre-write IMS snapshots (rollback source)
├── reports/
│   └── cycles/                 — Per-cycle status JSON (gitignored)
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
| **7.2** | **Security & Compliance (CMMC Level 2)** | ✅ **Complete — 375 tests** | 2026-05-03 |
| 7.3 | Infrastructure & Observability (Grafana, log aggregation) | ⏳ Awaiting deployment platform | — |
| 7.5 | First Customer Pilot Execution | ⏳ Awaiting customer engagement | — |

**Phase 6 note:** 4 Core Integrity bugs fixed; Prometheus metrics + extended `/health`; secrets hardening + CMMC gap analysis; LLM retry backoff + DR runbook; IMS audit trail (`ims_diff.py`, per-cycle diff JSON/Markdown, `GET /api/diff/{cycle_id}`); customer onboarding docs.

**Phase 7.2 note:** JWT auth (`POST /api/auth/token`, HS256, 1-hour expiry), JTI replay blocklist (CMMC IA.3.084), read/admin tier separation, key age alert in `GET /health` (CMMC SC.3.187), SIEM syslog (`agent/siem.py`, CMMC AU.3.045), formal incident response plan (`docs/IR_PLAN.md`), credential rotation procedures (`docs/DR_RUNBOOK.md §9`). 6 HIGH CMMC gaps remediated. 375 tests passing.

**Phase 7.4 note:** Per-CAM dashboard progress pills, cumulative diff (`GET /api/changes`), baseline drift alert (`GET /api/baseline-drift`), Q&A 30s TTL cache (TD-016), `SIMULATOR_CALL_DELAY_MS` rate limiting (TD-009), cycle report IMS Diff Summary and Baseline Drift Alert sections.

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
- [TEST-PROCEDURE.md](TEST-PROCEDURE.md) — 228-case test procedure with run history
