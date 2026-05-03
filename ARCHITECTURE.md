# IMS Agent — Architecture Reference

This document is the authoritative technical reference for AI agents and developers working on this codebase. Read this before making any changes. It covers the full system architecture, every module's responsibility, the interview state machine, critical deployment patterns, and common gotchas.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository Map](#2-repository-map)
3. [Full Cycle Data Flow](#3-full-cycle-data-flow)
4. [Interview State Machine](#4-interview-state-machine)
5. [Teams Chat Architecture](#5-teams-chat-architecture)
6. [Critical: `--schedule` vs `--trigger`](#6-critical----schedule-vs---trigger)
7. [Environment Configuration](#7-environment-configuration)
8. [CAM Directory Setup](#8-cam-directory-setup)
9. [Test Suite](#9-test-suite)
10. [Key Design Patterns](#10-key-design-patterns)
11. [Common AI Agent Gotchas](#11-common-ai-agent-gotchas)

---

## 1. System Overview

The IMS Agent autonomously manages Integrated Master Schedule (IMS) updates for defense programs. Each week (configurable), it:

1. **Interviews all CAMs** via Microsoft Teams Chat — structured conversation capturing percent complete, blockers, and schedule risk flags
2. **Validates inputs** — catches backwards movement, large jumps, and missing responses
3. **Updates the IMS** — writes validated data back to the MSPDI XML schedule file
4. **Runs analysis** — critical path (CPM) and Monte Carlo SRA (N=1000)
5. **Synthesizes intelligence** — LLM connects schedule data with CAM context to produce narrative, top risks, and PM actions
6. **Distributes output** — live dashboard, Slack, email, optional voice briefing

Between cycles, a PM can ask natural language questions via the dashboard chat widget or Slack `/ims` command.

### High-Level Component Map

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py (entry point)                   │
│   --run | --serve | --schedule | --demo-chat | --cam-responder  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
  agent/scheduler.py  agent/dashboard/  agent/cycle_runner.py
  (APScheduler cron)  server.py          (orchestrates one cycle)
                      (FastAPI)
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
    interview_        file_handler  sra_runner +
    orchestrator      .py           critical_path
    .py               (IMS XML      .py
    (parallel CAM     parse/write)  (analysis)
     interviews)
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
interview_  cam_       llm_
agent.py    simulator  interface.py
(state      .py        (all LLM calls)
 machine)   (test only)
```

---

## 2. Repository Map

### Root Files

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point. Parses args, dispatches to the correct runtime mode. |
| `requirements.txt` | All Python dependencies. |
| `.env.example` | Template for all 40+ environment variables with descriptions. |
| `Dockerfile` | Non-root production container (`imsagent` uid 1001, `python:3.11-slim`). |
| `docker-compose.yml` | Local dev compose (bind-mount volumes). |
| `docker-compose.prod.yml` | Production compose (named volumes, resource limits, `unless-stopped`). |
| `START.bat` | One-click Windows startup: activates venv, seeds master, launches `--schedule`. |
| `IMS-AGENT-PROGRAM-PLAN.md` | Authoritative program plan. Phase gates, roadmap, open questions. |
| `ARCHITECTURE.md` | This file. |
| `CHANGELOG.md` | Version history by phase. Update on every significant change. |
| `TECHNICAL-DEBT.md` | Known issues register. Add an entry whenever you cut a corner. |
| `STARTUP.md` | Operational runbook for humans and AI agents bringing the system up. |
| `DEPLOYMENT.md` | Step-by-step production deployment guide (Docker Compose). |
| `OPERATIONS.md` | Monitoring, troubleshooting, backup/restore, common issues. |
| `SECURITY.md` | RBAC, secrets management, ITAR posture, input validation. |
| `API.md` | All endpoints with request/response examples and response times. |
| `CONFIGURATION.md` | Every env var with default, required/optional, description. |
| `TEST_RESULTS.md` | Most recent test procedure run results. |

### `agent/` — Core Package

| File | Responsibility |
|------|---------------|
| `llm_interface.py` | **Single entry point for ALL Anthropic API calls.** Never call the SDK directly from other modules. Provides: `synthesize()`, `classify_cam_response()`, `ask()`, `ask_with_tools()`. Routes to local Ollama if `LLM_BASE_URL` is set. |
| `file_handler.py` | IMS XML parsing (`parse()`) and write-back (`apply_updates()`). Reads/writes MSPDI XML format. Atomic in-place write via `os.replace(tmp, target)`. Caches parsed tree; call `parse()` again after write to refresh. |
| `critical_path.py` | CPM calculation. Returns `critical_path` (ordered task ID list), `total_float` (per-task dict), `project_float_days` (scalar), `near_critical` (task IDs with float < 5 days). |
| `sra_runner.py` | Monte Carlo SRA engine. N=1000 simulations (configurable). Per-milestone: P50/P80/P95 dates and `prob_on_baseline`. |
| `cycle_runner.py` | Orchestrates one full cycle: lock → interview → validate → write → analyze → synthesize → report → distribute → purge. Owns the cycle lock to prevent concurrent runs. |
| `cycle_state.py` | Cycle state persistence. Reads/writes `reports/cycles/{cycle_id}_status.json`. |
| `scheduler.py` | APScheduler cron wrapper. Fires `CycleRunner.run()` on the configured schedule. |
| `validation.py` | Input validation rules: no backwards movement, no >50% jump, no missing tasks. Returns hold list for human review. |
| `interview_orchestrator.py` | Coordinates parallel CAM interviews. Spawns one `InterviewAgent` per CAM; waits for all to complete or time out. Passes `all_tasks` to every agent for milestone lookup. |
| `cam_directory.py` | CAM registry. Loads from `data/cam_directory.json`. Business hours check (`can_call_now()`), retry logic (`should_retry()`), escalation (`should_escalate()`), call history tracking. |
| `cam_identity.py` | Loads `data/cam_identity_map.json`. Maps CAM names to M365 email addresses, Teams user IDs, and responder configuration. |
| `cam_input.py` | Structures raw interview results into the standard CAM input dict format consumed by `CycleRunner`. |
| `schedule_health.py` | Deterministic RED/YELLOW/GREEN scoring from SRA `prob_on_baseline` thresholds and CPM float. Called by `CycleRunner`; result injected into LLM prompt as a given (LLM does not decide health). |
| `approval_store.py` | JSON-backed approval queue at `data/pending_approvals/`. Saves cycles held by validation; `mark_approved()` / `mark_rejected()` for PM workflow. |
| `report_generator.py` | Markdown report generation. Output to `reports/{date}_ims_report.md`. |
| `notifier.py` | Slack webhook and SMTP email notifications. Config read at module import time (TD-014). |
| `voice_briefing.py` | LLM + TTS 1–2 minute voice briefing generation (optional). |
| `slack_command.py` | Slack `/ims` slash command via Socket Mode. No public URL required. |
| `ngrok_updater.py` | On `--demo-chat` startup, reads ngrok local API and PATCHes Azure Bot Service endpoint via ARM REST. |
| `mpp_converter.py` | MS Project COM automation: `mpp_to_xml()` and `xml_to_mpp()`. Falls back gracefully if COM is unavailable (C2R AppV isolation — see TD-025). |
| `metrics.py` | Thread-safe in-memory counters. `increment()`, `set_value()`, `snapshot()`. Exposed via `GET /metrics`. |

### `agent/dashboard/`

| File | Responsibility |
|------|---------------|
| `server.py` | FastAPI server. All HTTP endpoints. Hosts the dashboard HTML, Q&A API, Bot Framework webhook, internal relay endpoint, metrics, health check, and admin routes. |
| `templates/index.html` | Single-page dashboard. Vanilla JS — no build step. Auto-refreshes via AJAX polling (every 5s during active cycle, 60s idle). |

### `agent/qa/`

| File | Responsibility |
|------|---------------|
| `qa_engine.py` | Q&A engine. Direct-answer fast path for common queries (~2s). LLM-routed path using `ask_with_tools()` for raw IMS queries (~10s). |
| `context_builder.py` | Intent detection (9 patterns). Slices relevant context from `dashboard_state.json` and `cycle_history.json` for LLM grounding. |
| `ims_tools.py` | 8 Anthropic tool_use handlers: `get_task`, `search_tasks`, `get_critical_path`, `get_tasks_by_cam`, `get_float`, `get_dependencies`, `get_milestones`, `get_behind_tasks`. All query the live IMS XML directly. |

### `agent/voice/`

| File | Responsibility |
|------|---------------|
| `interview_agent.py` | **Conversation state machine.** 11 states. Handles all NLU via LLM classifier. Tracks per-milestone risk history to avoid repetitive questions. See [Section 4](#4-interview-state-machine). |
| `cam_simulator.py` | Claude-powered CAM simulator for dev/test. **Not part of production.** Feeds realistic responses into `InterviewAgent.process()`. |
| `teams_chat_connector.py` | `ChatInterviewManager` singleton + `ChatInterviewSession`. Manages active Teams chat interviews. `_bf_send()` sends messages via Bot Framework REST. See [Section 5](#5-teams-chat-architecture). |
| `teams_connector.py` | `TeamsACSConnector` — Azure ACS voice connector stub. Raises `NotImplementedError` (pending ACS credentials, TD-011). `TeamsGraphConnector` — joins Teams meetings via Graph Communications API for voice demo (Tier 3). |
| `stt_engine.py` | STT abstraction. `WhisperSTTEngine` (local Whisper model), `MockSTTEngine` (returns pre-set strings for testing). |
| `tts_engine.py` | TTS abstraction. `ElevenLabsTTSEngine`, `AzureTTSEngine`, `MockTTSEngine`. Factory: `build_tts_engine()`. |
| `transcript_extractor.py` | Post-interview LLM structured data extraction from raw transcript. Returns typed dict with percent_complete, blocker, risk_flag, risk_description per task. |

### `data/` — Runtime Data (not source-controlled except sample_ims.xml)

| Path | Purpose | Gitignored? |
|------|---------|-------------|
| `sample_ims.xml` | Synthetic 100-task ATLAS program IMS (source of truth for tests). | No — committed |
| `ims_master/` | One timestamped `.mpp` file — the authoritative schedule. Updated each cycle. | No — committed as empty dir |
| `cam_directory.json` | CAM registry (names, emails, business hours, retry config). | No — committed |
| `cam_identity_map.json` | M365 email → Teams user ID mapping for each CAM. | No — committed |
| `dashboard_state.json` | Live dashboard state. Regenerated every cycle. | **Yes** — runtime |
| `cycle_history.json` | Rolling 52-cycle summary history. | **Yes** — runtime |
| `cam_sessions.json` | Teams chat conversation IDs per CAM. Sensitive. | **Yes** — runtime |
| `cam_tokens/` | MSAL token caches per CAM account. Sensitive. | **Yes** — gitignored |
| `snapshots/` | Timestamped IMS XML before each update (rollback source). | **Yes** — runtime |
| `ims_exports/` | Post-cycle IMS exports. `latest_ims.xml` always current. | **Yes** — runtime |
| `pending_approvals/` | Cycles held for PM approval. | **Yes** — runtime |
| `interview_kicks/` | Legacy kick-file mechanism (superseded by relay endpoint). | **Yes** — runtime |
| `ims.db` | SQLite database (reserved for future use). | **Yes** — runtime |

---

## 3. Full Cycle Data Flow

```
Trigger (cron schedule or POST /api/trigger)
    │
    ▼
CycleRunner._acquire_lock()          — prevents concurrent cycles
    │
    ▼
IMSFileHandler.parse(ims_path)       — parse current IMS XML into task dicts
    │
    ▼
InterviewOrchestrator.run(all_tasks) — fan out, interview all CAMs in parallel
    │   Per CAM:
    │     InterviewAgent(cam_name, cam_tasks, all_tasks=all_tasks)
    │     agent.start()               — sends greeting to Teams
    │     [CAM replies via Teams → Graph responder → POST /internal/cam_message]
    │     agent.process(text)         — advance state machine
    │     [repeat until agent.state == COMPLETE]
    │     results = agent.results     — list[TaskResult]
    │
    ▼
CycleRunner._build_cam_inputs()      — flatten TaskResult lists into input dicts
    │
    ▼
validate(cam_inputs, parsed_tasks)   — check backwards movement, large jumps
    │   Holds → save to approval_store, alert PM, skip IMS write
    │   Clean → proceed
    │
    ▼
IMSFileHandler.apply_updates(inputs) — atomic in-place XML write (os.replace)
    │
    ▼
calculate_critical_path(tasks)       — CPM, float, near-critical tasks
    │
    ▼
run_sra(tasks, n=1000)               — Monte Carlo per-milestone P50/P80/P95
    │
    ▼
compute_health(sra, cp, tasks)       — deterministic RED/YELLOW/GREEN
    │
    ▼
LLMInterface.synthesize(...)         — narrative, top risks, PM actions
    │                                  (health injected as given, not LLM-decided)
    │
    ▼
ReportGenerator.generate(...)        — Markdown report → reports/{date}_ims_report.md
    │
    ▼
_update_dashboard_state(...)         — write dashboard_state.json (atomic)
_update_cycle_history(...)           — append to cycle_history.json (atomic)
    │
    ▼
send_slack(...) + send_email(...)    — distribute output
    │
    ▼
_export_ims_snapshot(cycle_id)       — copy XML to data/ims_exports/{id}_ims.xml
    │                                  + data/ims_exports/latest_ims.xml
    │
    ▼
CycleRunner.purge_old_data()         — delete data outside DATA_RETENTION_DAYS window
    │
    ▼
CycleRunner._release_lock()
```

---

## 4. Interview State Machine

`agent/voice/interview_agent.py` — class `InterviewAgent`

### States (enum `InterviewState`)

| State | Description |
|-------|-------------|
| `GREETING` | Initial state. `start()` sends the opening greeting and transitions to `TASK_INTRO`. |
| `TASK_INTRO` | Introduces the current task to the CAM. Transitions to `AWAITING_PCT`. |
| `AWAITING_PCT` | Waiting for percent complete. LLM classifier extracts a number 0–100. |
| `AWAITING_BLOCKER` | Asked when task is behind expected progress. Waiting for free-text blocker description. |
| `AWAITING_RISK_FLAG` | Asked when task has a blocker. "Could this put [milestone] at risk?" Yes/No. |
| `AWAITING_RISK_DESC` | Asked when risk flag is YES. Waiting for risk description. |
| `CONFIRM` | Summary read-back. CAM confirms or corrects. CONFIRM keyword pre-check fires before LLM classifier. |
| `CLOSING` | Final closing message. Transitions to `COMPLETE`. |
| `COMPLETE` | Terminal state. `results` property returns `list[TaskResult]`. |
| `NO_RESPONSE` | Terminal state. CAM was unreachable or hit max retries. |
| `ABORTED` | Terminal state. Reached 60-turn safety limit. |

### Key Instance Variables

```python
_cam_name: str                         # CAM's display name
_tasks: list[dict]                     # This CAM's non-milestone tasks
_milestones: list[dict]                # All milestone tasks (from all_tasks)
_task_index: int                       # Current task pointer
_state: InterviewState                 # Current FSM state
_results: list[TaskResult]             # Completed task results
_transcript: list[ConversationTurn]    # Full conversation log

# Per-task working state (reset by _reset_task_state() on each task advance)
_current_pct: int | None
_current_blocker: str
_current_risk_flag: bool
_current_risk_desc: str

# Milestone risk tracking (persist across tasks for the full interview)
_flagged_milestones: dict[str, bool]   # milestone_name → True/False (risk answer)
_milestone_no_count: dict[str, int]    # milestone_name → count of NO answers
                                       # After ≥2 NOs, skip risk question for that milestone
```

### State Transitions (happy path)

```
start()
  └─► GREETING
        └─► TASK_INTRO           (_handle_greeting processes CAM's ready signal)
              └─► AWAITING_PCT   (_introduce_current_task fires automatically)
                    ├─► [on-track] CONFIRM     (skip BLOCKER+RISK)
                    └─► [behind]  AWAITING_BLOCKER
                                    └─► AWAITING_RISK_FLAG
                                          ├─► [YES] AWAITING_RISK_DESC
                                          │           └─► CONFIRM
                                          └─► [NO]  CONFIRM
                                                      └─► [next task] TASK_INTRO
                                                      └─► [all done]  CLOSING
                                                                        └─► COMPLETE
```

### Risk Question Suppression Logic

Two mechanisms prevent the "you've asked me this 6 times" problem when many tasks share the same milestone:

1. **`_flagged_milestones` (True path)**: If a CAM already answered YES for a milestone, subsequent tasks with blockers skip the risk question and inherit `risk_flag=False` (not True — the milestone is already flagged; don't auto-flag every subsequent task).

2. **`_milestone_no_count` threshold**: If the CAM has answered NO ≥ 2 times for the same milestone, stop asking entirely. Subsequent tasks auto-set `risk_flag=False`.

### CONFIRM Keyword Pre-check

`_handle_confirm()` runs a keyword scan **before** the LLM classifier. If the CAM response contains correction language ("actually", "that's wrong", "no,", "not quite", etc.), it routes directly to `_extract_and_apply_correction()` without an LLM call. This eliminates the CONFIRM→NO→re-ask infinite loop that was TD-004.

### Nearest Milestone Selection

`_nearest_milestone_name()` returns the milestone whose finish date is **at or after the current task's own finish date**. This prevents the logically wrong question "Could this put Milestone X at risk?" when the task is scheduled to complete after that milestone has already passed.

---

## 5. Teams Chat Architecture

### Components

```
Teams (CAM's client)
    │  CAM types a reply
    ▼
Azure Bot Service
    │  forwards Activity to messaging endpoint
    ▼
POST /bot/messages  (server.py)
    │  routes to ChatInterviewManager
    ▼
ChatInterviewManager (singleton in server process)
    │  looks up ChatInterviewSession by Teams user ID
    ▼
ChatInterviewSession.process(text)
    │  calls InterviewAgent.process(text)
    ▼
InterviewAgent (state machine advances)
    │  returns next agent turn text
    ▼
_bf_send(service_url, conversation_id, text)
    │  Bot Framework REST API (proactive send)
    ▼
Azure Bot Service → Teams (CAM sees agent's reply)
```

### Graph CAM Responder (for automated testing)

When running with simulated CAM accounts (M365 trial tenant), a separate process polls Teams for new messages:

```
graph_cam_responder.py
    │  polls Graph API for unread messages per CAM account
    │  generates reply via cam_simulator.py (LLM)
    │  posts reply via Graph API (as the CAM)
    ▼
POST /internal/cam_message  (server.py)
    │  looks up ChatInterviewSession by email
    ▼
[same relay path as above]
```

### ChatInterviewManager

`ChatInterviewManager` is a **process-level singleton** in `agent/voice/teams_chat_connector.py`. It maps Teams user IDs and email addresses to active `ChatInterviewSession` objects.

**Critical**: This singleton only exists in the process that created it. See [Section 6](#6-critical----schedule-vs---trigger) for why this matters.

### Session Lifecycle

1. `CycleRunner._run_teams_chat_interviews()` creates a `ChatInterviewSession` per CAM via `ChatInterviewManager.register_by_email()`
2. The cycle runner calls `_bf_send()` to deliver the opening greeting to each CAM
3. CAM replies flow in via `/bot/messages` or `/internal/cam_message`
4. `session.process(text)` advances the `InterviewAgent` state machine
5. When `agent.state == COMPLETE`, `remove_session_by_email()` cleans up
6. `cycle_runner.py` collects `session.results` from all completed sessions

---

## 6. Critical: `--schedule` vs `--trigger`

**This is the most important architectural constraint in the system.** Getting it wrong causes interviews to silently fail.

### The Problem: Process Isolation

`ChatInterviewManager` is a **singleton in the process that created it**. When the system runs Teams chat interviews:

- The `--serve` / `--schedule` server process holds all active `ChatInterviewSession` objects
- Incoming CAM replies (via `/bot/messages` or `/internal/cam_message`) must reach the **same process** to advance the correct session

If you run:
```bash
# WRONG for Teams chat mode
python main.py --serve        # process A — has ChatInterviewManager
python main.py --trigger      # process B — creates its OWN ChatInterviewManager
```

The `--trigger` process creates sessions in its own singleton. When the server in process A receives CAM replies, it looks up sessions in **its own empty** `ChatInterviewManager` and returns `{"status": "no_session"}`. All replies are silently dropped. Interviews never advance past the greeting.

### The Correct Pattern

```bash
# CORRECT for Teams chat mode
python main.py --schedule     # single process — scheduler + server + ChatInterviewManager

# To fire a cycle immediately without waiting for the cron:
curl -X POST http://localhost:9000/api/trigger
```

Or for a one-time manual run with Teams chat, start the server and trigger via HTTP:
```bash
python main.py --serve        # process A — server with ChatInterviewManager
curl -X POST http://localhost:9000/api/trigger   # fires cycle in process A
```

### Mode Reference

| Command | Server | Scheduler | ChatInterviewManager | Use case |
|---------|--------|-----------|---------------------|---------|
| `--run` | No | No | N/A | Single cycle, simulator mode only |
| `--serve` | Yes | No | Yes | Dashboard + manual trigger via API |
| `--schedule` | Yes | Yes | Yes | **Production** — cron fires every Monday 06:00 |
| `--trigger` | No | No | Isolated | **Do not use for Teams chat mode** |
| `--demo-chat` | Yes | No | Yes | Teams chat demo (single CAM) |

---

## 7. Environment Configuration

Copy `.env.example` to `.env`. Minimum required for local dev:

```bash
ANTHROPIC_API_KEY=sk-ant-...
IMS_FILE_PATH=data/sample_ims.xml
```

### Complete Variable Reference

#### Core LLM
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ANTHROPIC_API_KEY` | — | **Yes** | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | No | Model name |
| `LLM_BASE_URL` | — | No | Override to local Ollama endpoint for ITAR/on-prem. All LLM calls route here if set. No code changes needed. |

#### File Paths
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `IMS_FILE_PATH` | `data/sample_ims.xml` | No | Path to active IMS file |
| `REPORTS_DIR` | `reports` | No | Output directory for cycle reports |
| `LOGS_DIR` | `logs` | No | Log file directory |

#### Interview / Transport
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `CALL_TRANSPORT` | `simulated` | No | `simulated` (CAM simulator) or `teams_chat` (live Teams) |
| `INTERVIEW_RESPONSE_TIMEOUT_SEC` | `120` | No | Seconds to wait for CAM reply before retry |
| `INTERVIEW_MAX_RETRIES` | `2` | No | Max retries before marking CAM as no_response |
| `INTERVIEW_MAX_CONCURRENT` | `5` | No | Max simultaneous CAM interviews |
| `INTERVIEW_COMPLETION_THRESHOLD` | `0.8` | No | Fraction of CAMs required before proceeding |
| `CAM_DIRECTORY_PATH` | `data/cam_directory.json` | No | Path to CAM registry |

#### Teams / Azure
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `TEAMS_BOT_APP_ID` | — | Teams chat | Azure App Registration client ID |
| `TEAMS_BOT_APP_SECRET` | — | Teams chat | App Registration secret |
| `TEAMS_TENANT_ID` | — | Teams chat | M365 tenant ID |
| `ACS_CONNECTION_STRING` | — | ACS voice | Azure Communication Services connection string |

#### ElevenLabs TTS
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ELEVENLABS_API_KEY` | — | Voice demo | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | — | Voice demo | Voice ID for agent voice |
| `ELEVENLABS_MODEL` | `eleven_turbo_v2` | No | ElevenLabs model |

#### Dashboard / API
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DASHBOARD_PORT` | `9000` | No | Port for FastAPI server |
| `DASHBOARD_API_KEY` | — | No | Read-route auth key (`X-API-Key` header). Unset = no auth. |
| `DASHBOARD_ADMIN_KEY` | — | No | Admin-route auth key (`X-Admin-Key` header). Gates `/api/trigger` and `/api/admin/purge`. |

#### Scheduler
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `SCHEDULE_CRON` | `0 6 * * 1` | No | Cron expression (default: Monday 06:00) |
| `SCHEDULE_TIMEZONE` | `America/New_York` | No | IANA timezone for cron |

#### SRA (Monte Carlo)
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `SRA_ITERATIONS` | `1000` | No | Monte Carlo iteration count |
| `SRA_DURATION_UNCERTAINTY` | `0.10` | No | ±fraction of remaining duration as default uncertainty |
| `SRA_HIGH_RISK_THRESHOLD` | `0.50` | No | `prob_on_baseline` below this → HIGH risk |
| `SRA_MEDIUM_RISK_THRESHOLD` | `0.75` | No | `prob_on_baseline` below this → MEDIUM risk |

#### Validation
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `VALIDATION_MAX_JUMP_PCT` | `50` | No | Max allowed single-cycle percent increase |
| `VALIDATION_ALLOW_BACKWARDS` | `false` | No | Set `true` to allow percent decreases (testing only) |

#### Slack / Email
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `SLACK_WEBHOOK_URL` | — | No | Incoming webhook for cycle summary posts |
| `SLACK_BOT_TOKEN` | — | Slash command | `xoxb-...` bot token for Socket Mode |
| `SLACK_APP_TOKEN` | — | Slash command | `xapp-...` app token for Socket Mode |
| `EMAIL_SMTP_HOST` | — | No | SMTP server hostname |
| `EMAIL_SMTP_PORT` | `587` | No | SMTP port |
| `EMAIL_SMTP_USER` | — | No | SMTP username |
| `EMAIL_SMTP_PASS` | — | No | SMTP password |
| `EMAIL_FROM` | — | No | Sender address |
| `EMAIL_TO` | — | No | Comma-separated recipient list |

#### Data / Logging
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATA_RETENTION_DAYS` | `90` | No | Auto-purge cycle data older than this |
| `LOG_LEVEL` | `INFO` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | `text` | No | `json` for Datadog/ELK/CloudWatch log aggregators |

#### ngrok / Azure Management (optional)
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `AZURE_SUBSCRIPTION_ID` | — | ngrok auto-update | For `ngrok_updater.py` to PATCH Bot Service endpoint |
| `AZURE_RESOURCE_GROUP` | — | ngrok auto-update | Resource group containing the Bot Service |
| `AZURE_BOT_NAME` | — | ngrok auto-update | Bot Service resource name |

---

## 8. CAM Directory Setup

CAMs are configured across three JSON files in `data/`. These files are committed to source control (they are config, not runtime state).

### `data/cam_directory.json`

Registry of CAM names, contact info, business hours, and retry configuration.

```json
{
  "cams": [
    {
      "name": "Alice Nguyen",
      "email": "alice@intelligenceexpanse.onmicrosoft.com",
      "timezone": "America/New_York",
      "business_hours_start": 8,
      "business_hours_end": 17,
      "max_retries": 2,
      "retry_delay_hours": 1
    }
  ]
}
```

### `data/cam_identity_map.json`

Maps CAM display names to M365 email addresses and Teams responder configuration. Used by `cam_identity.py` and `graph_cam_responder.py`.

```json
{
  "Alice Nguyen": {
    "email": "alice@intelligenceexpanse.onmicrosoft.com",
    "auto_respond": true,
    "responder_type": "graph"
  }
}
```

`auto_respond: true` means the Graph CAM responder will auto-reply on behalf of this CAM (dev/test only). Set to `false` for real humans.

### `data/cam_sessions.json` (gitignored — runtime)

Stores real Teams conversation IDs, service URLs, and user IDs per CAM. Built automatically when a CAM first messages the bot. **This file is gitignored** because it contains live Teams session data. It is rebuilt automatically on first contact.

```json
{
  "alice@intelligenceexpanse.onmicrosoft.com": {
    "user_id": "29:abc...",
    "service_url": "https://smba.trafficmanager.net/amer/",
    "conversation_id": "19:def..."
  }
}
```

### Adding a New CAM

1. Add an entry to `data/cam_directory.json` with name, email, timezone, hours, retry config
2. Add an entry to `data/cam_identity_map.json` with name → email mapping
3. Assign tasks to the CAM's name in the IMS XML (`<Resource Name="Alice Nguyen"/>` pattern)
4. For Teams chat mode:
   - Create an M365 account for the CAM (real or simulator)
   - If using the Graph responder (simulator): run `python main.py --cam-responder --cam "New CAM"` and complete device-code auth once
   - Bootstrap first-contact: have the CAM send any message to the ATLAS bot in Teams, or use `--demo-chat --cam "New CAM"` to initiate proactively
   - Verify `data/cam_sessions.json` now has an entry for the CAM's email

---

## 9. Test Suite

### Running Tests

```bash
pytest tests/ -v              # all tests, verbose
pytest tests/ -q              # quiet summary only
pytest tests/ -k "interview"  # filter by keyword
pytest tests/ --tb=short      # short tracebacks on failure
```

**Current count:** 255 tests (all passing as of 2026-05-03)

### Test File Map

| File | What it covers |
|------|---------------|
| `test_interview_agent.py` | InterviewAgent state machine — all state transitions, edge cases, milestone risk suppression, CONFIRM keyword pre-check |
| `test_cam_directory.py` | CAM registry, business hours, retry/escalation logic |
| `test_cam_input.py` | CAM input structuring and validation |
| `test_critical_path.py` | CPM calculation, float, near-critical flagging |
| `test_cycle_runner.py` | Full cycle orchestration, lock, validation hold paths |
| `test_file_handler.py` | IMS XML parsing and write-back |
| `test_ims_tools.py` | Q&A tool handlers, dispatcher, agentic loop |
| `test_qa_engine.py` | Q&A engine — direct path and LLM-routed path |
| `test_report_generator.py` | Markdown report structure |
| `test_scheduler.py` | APScheduler cron configuration |
| `test_sra_runner.py` | Monte Carlo SRA correctness |
| `test_stt_engine.py` | STT engine abstraction (mock path) |
| `test_tts_engine.py` | TTS engine abstraction (mock path) |
| `test_validation.py` | Validation rules — backwards, large jump, missing |
| `test_phase5.py` | RBAC, rate limiting, metrics, purge, health endpoint |

### Test Fixtures (`tests/conftest.py`)

- `autouse` fixture patches `agent.mpp_converter.find_latest_master` → `None` for all tests. This prevents the MS Project COM automation from firing during unit tests (which would crash the test process on Windows). Tests that specifically need the MPP workflow opt out explicitly with `@pytest.mark.no_mpp_patch`.

- `test_cycle_runner.py` has an `isolated_data_dirs` autouse fixture that redirects `_REPORTS_DIR` and `_DATA_DIR` to `tmp_path` for every test, preventing I/O side-effects.

### Integration Tests

Some tests that require real credentials (Azure, Slack, ElevenLabs) are marked `@pytest.mark.integration` and skipped in CI. Run them manually when the relevant credentials are available.

---

## 10. Key Design Patterns

### Single LLM Entry Point

All Anthropic API calls go through `agent/llm_interface.py`. No other module calls the Anthropic SDK directly. This means:
- ITAR swap: set `LLM_BASE_URL` to a local Ollama endpoint → all LLM calls route there, zero code changes
- Cost tracking: one place to add token counting
- Testing: mock `llm_interface` to test all LLM-dependent code without API calls

### Atomic File Writes

All JSON state file writes use `os.replace(tmp, target)` — write to a temp file then atomically rename. This prevents corrupted state files if the process is killed mid-write (TD-013). Pattern used in:
- `IMSFileHandler.apply_updates()`
- `CycleRunner._update_dashboard_state()`
- `CycleRunner._update_cycle_history()`

### Deterministic Health Scoring

`schedule_health.compute_health()` produces RED/YELLOW/GREEN from numeric SRA thresholds and CPM float. The result is injected into the LLM synthesis prompt as a given — the LLM is never asked to decide the health label. This eliminates run-to-run variance in health scoring (resolved TD-001).

### ChatInterviewManager Singleton

`ChatInterviewManager` in `teams_chat_connector.py` is a module-level singleton. It maps Teams user IDs and email addresses to active `ChatInterviewSession` objects. Only one exists per process. Sessions created in one process are not visible to another. See [Section 6](#6-critical----schedule-vs---trigger).

### Cycle Lock

`CycleRunner._acquire_lock()` writes a lock file at startup and checks for it before starting. If the lock exists (from a crashed prior cycle), a restart clears it. This prevents duplicate cycles from running simultaneously.

---

## 11. Common AI Agent Gotchas

### 1. Never use `--trigger` for Teams chat mode

See [Section 6](#6-critical----schedule-vs---trigger). Use `--schedule` + `POST /api/trigger` instead.

### 2. `cam_sessions.json` is gitignored — it's rebuilt at runtime

If the file is missing, Teams chat interviews will fail silently. It is populated automatically when CAMs first message the bot. For a fresh checkout, it must be bootstrapped before `CALL_TRANSPORT=teams_chat` works.

### 3. Always pass `all_tasks` to `InterviewAgent`

```python
# WRONG — milestones will always be empty; risk questions use fallback "the next milestone"
agent = InterviewAgent(cam_name, cam_tasks)

# CORRECT
agent = InterviewAgent(cam_name, cam_tasks, all_tasks=all_tasks)
```

`InterviewOrchestrator` handles this correctly. If writing code that instantiates `InterviewAgent` directly, always pass `all_tasks`.

### 4. `IMS_FILE_PATH` is the working file, not the master

The system reads from and writes back to `IMS_FILE_PATH` (default: `data/sample_ims.xml`). The `data/ims_master/` folder holds the `.mpp` binary (Microsoft Project format) as a separate artifact. After each cycle, the XML is also exported to `data/ims_exports/latest_ims.xml`.

### 5. `parse()` caches the XML tree

`IMSFileHandler` caches the parsed XML tree after the first `parse()` call. After `apply_updates()` writes changes, call `parse()` again to refresh the cache before any downstream code reads the updated data.

### 6. COM automation requires MS Project installed (Windows only)

`mpp_converter.py` uses MS Project COM automation to convert between `.mpp` (binary) and `.xml` (MSPDI). If MS Project is not installed, or the Click-to-Run AppV isolation blocks COM, all MPP operations fall back gracefully — the agent continues with XML only. The `--init-mpp` command requires COM. See TD-025 for the fix if COM is blocked.

### 7. Test count in documentation

The test count appears in several doc files. When adding new tests, update:
- `README.md` (Quick Start → Running Tests section)
- `STARTUP.md` (Step 4)
- `CHANGELOG.md` (new entry)
- `IMS-AGENT-PROGRAM-PLAN.md` (Phase 5.7 acceptance note)

### 8. `_flagged_milestones` True → risk=False (not True)

When a CAM has already answered YES for a milestone, subsequent tasks with blockers sharing the same milestone skip the risk question and inherit `risk_flag=False`. This is intentional — the milestone is already flagged once; no need to flag every task. Setting it to `True` would cause excessive CONFIRM corrections (this was a bug fixed in commit `0e68d50`).

### 9. The CONFIRM state handles corrections, not rejections

If a CAM says "No" in CONFIRM, `_handle_confirm` checks for correction language first (keyword pre-check). If correction language is found, it routes to `_extract_and_apply_correction`. If the CAM says a flat "No" with no correction content, `_confirm_retry_count` caps re-asks at 2 before closing the interview. The loop is bounded; it cannot hang indefinitely.

### 10. Notifier config is read at import time

`agent/notifier.py` reads Slack and email config from `os.getenv` at module import time (TD-014). Changing `.env` while the server is running has no effect until restart. This is expected behavior — credential rotation requires a restart.

---

*Last updated: 2026-05-03*  
*Maintainer: John Forbes*
