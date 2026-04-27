# Changelog

All notable changes to the IMS Agent are documented here. Entries are organized by phase completion, with key deliverables and metrics for each.

---

## Tier 3 — Live Teams Interview Demo (2026-04-26)

**Capability:** A named bot participant ("ATLAS Scheduler") joins a live Microsoft Teams meeting and conducts a full CAM status interview. Both sides of the conversation (agent questions and simulated CAM responses) are played as ElevenLabs TTS audio into the call — anyone in the meeting hears both voices in real time.

### Added
- `agent/voice/teams_connector.py` — `TeamsGraphConnector` class: joins Teams meetings via Microsoft Graph Communications API (`POST /communications/calls`), synthesises TTS with ElevenLabs PCM output, wraps in WAV, serves audio via FastAPI, triggers `playPrompt`
- `agent/dashboard/server.py` — `POST /graph/callback` endpoint: handles Graph call-state notifications (establishing → established → terminated), `playPromptOperation` completion events; `GET /graph/audio/{id}` serves single-use WAV clips to Graph
- `agent/demo_interview.py` — Connector priority order: TeamsGraphConnector → TeamsACSConnector → LocalElevenLabsConnector (local speaker fallback)
- `scripts/check_teams_auth.py` — Diagnostic script: verifies MSAL token acquisition, decodes JWT claims, checks `Calls.JoinGroupCall.All` consent, tests `/communications/calls` API access

### Changed
- `agent/voice/interview_agent.py` — Replaced all keyword-based NLU (`_extract_percent`, `_contains_blocker_mention`, `_is_affirmative`) with a single LLM classifier (`_classify_cam_response`) that understands natural language responses; added `_is_material_risk()` threshold (15-point gap) to suppress spurious risk flags
- `agent/voice/cam_simulator.py` — Removed response truncation and strict 10-rule system prompt; replaced with natural conversational prompt that allows realistic engineer-style responses
- `agent/voice/teams_connector.py` — `LocalElevenLabsConnector`: replaced `playsound` (silent on Windows) with `sounddevice` + numpy direct PCM playback via `output_format="pcm_16000"`
- `agent/dashboard/server.py` — Fixed `graph_callback`: handle `resourceData` as list, extract call ID from `/calls/{id}/` path segment via regex (not last segment), match `playPromptOperation` via `"operation" in odata_type.lower()`
- `agent/demo_interview.py` — Fixed Unicode `─` (U+2500) in `_divider()` calls that crashed on Windows cp1252 consoles
- `requirements.txt` — Added `msal>=1.30.0`; replaced `playsound==1.2.2` with `sounddevice>=0.4.6`

### Azure Infrastructure Required
- **Azure AD App Registration** — `TEAMS_BOT_APP_ID`, `TEAMS_BOT_APP_SECRET`, `TEAMS_TENANT_ID`; API permission `Calls.JoinGroupCall.All` (Application, admin-consented)
- **Azure Bot Service** — Registers the app with Teams calling infrastructure; Teams channel enabled with calling webhook pointing to `/graph/callback`
- **ElevenLabs API** — TTS for both agent voice (Rachel) and CAM voice (Bella); `ELEVENLABS_API_KEY`
- **ngrok** — Public HTTPS tunnel to local port 8080 for Graph callbacks

### Demo Command
```
python main.py --demo-interview \
  --meeting-url "https://teams.microsoft.com/meet/..." \
  --cam "Alice Nguyen" \
  --callback-url "https://xxxx.ngrok-free.app"
```

### Known Limitations
- ~8–14 seconds per turn latency (ElevenLabs TTS × 2 + LLM classifier + Graph API round-trips)
- ngrok URL changes each session on free plan — must update Azure Bot Service webhook URL each run
- `TeamsMeetingLocator` removed from `azure-communication-callautomation` SDK 1.5+; ACS path is legacy fallback only

---

## Phase 5 — Production Hardening (2026-04-26)

**Capability:** The agent is containerized, secured with RBAC, observable, and ready for production deployment.

### Added
- `Dockerfile` + `docker-compose.yml` + `docker-compose.prod.yml` — non-root user (`imsagent` uid 1001), health check, named volumes, resource limits, `unless-stopped` restart
- **RBAC** — two-key model: `DASHBOARD_API_KEY` (read), `DASHBOARD_ADMIN_KEY` (admin); backward-compatible single-key fallback; all `/api/*` routes protected
- **Rate limiting** — `QA_RATE_LIMIT_PER_HOUR` per-IP rolling window on `POST /api/ask` (HTTP 429 on excess)
- **`GET /metrics`** — JSON snapshot of 7 in-memory counters (cycles, Q&A queries, durations); requires API key auth
- **`POST /api/admin/purge`** — triggers immediate data purge; requires admin key
- **`LLM_BASE_URL`** — single env var routes all LLM calls to local Ollama-compatible endpoint for ITAR/on-prem deployments
- **Data retention** — `DATA_RETENTION_DAYS` env var; `CycleRunner.purge_old_data()` auto-runs at end of every cycle; deletes cycle status JSONs + IMS snapshots older than window
- **Structured JSON logging** — `LOG_FORMAT=json` outputs `{ts, level, logger, msg}` for log aggregators (Datadog, ELK, CloudWatch)
- **`/health` improvements** — uptime, cycle active status, auth flag, state file presence
- `agent/metrics.py` — thread-safe in-memory counters; `increment()`, `set_value()`, `snapshot()`
- Q&A metrics wiring — `qa_queries_total`, `qa_queries_direct`, `qa_queries_llm` incremented on every query
- `tests/test_phase5.py` — 37 new tests covering all Phase 5 functionality
- `DEPLOYMENT.md`, `OPERATIONS.md`, `SECURITY.md`, `API.md`, `CONFIGURATION.md` — complete production documentation
- `CHANGELOG.md` — this file

### Security
- Dependency audit: 0 runtime CVEs (`pip-audit` 2026-04-26); pip CVE-2026-3219 documented (no fix; no runtime impact)
- SECURITY.md updated with completed RBAC section and `LLM_BASE_URL` on-prem swap path

### Metrics
- Total tests: **242** (all passing)
- Phase 5 tests: **37** (metrics, RBAC, rate limiting, purge, LLM_BASE_URL, endpoints)
- Runtime CVEs: **0**

### Acceptance
- Accepted by John Forbes, 2026-04-26. See [PHASE5-FEEDBACK.md](PHASE5-FEEDBACK.md).

---

## Phase 4.5 — IMS Schedule Tools (2026-04-26)

**Capability:** Direct Q&A against raw IMS schedule data via Anthropic tool_use (function calling).

Previously the Q&A engine could only answer from the synthesized dashboard state. This release adds an agentic tool-use loop so the LLM can query the live IMS XML directly when needed — returning exact float values, dependency chains, task details, and CAM workloads rather than "data not available."

### Added
- `agent/qa/ims_tools.py` — 8 tool handlers: `get_task`, `search_tasks`, `get_critical_path`, `get_tasks_by_cam`, `get_float`, `get_dependencies`, `get_milestones`, `get_behind_tasks`
- `LLMInterface.ask_with_tools()` — agentic loop (up to 5 rounds); all tool calls dispatched and results fed back as `tool_result` messages
- `QAEngine.ask()` upgraded — all LLM-routed questions now use tool_use; direct-answer fast path unchanged
- `tests/test_ims_tools.py` — 41 new tests (tool handlers, dispatcher, schemas, loop behavior, QAEngine integration)

### Metrics
- Total tests: **205** (all passing)
- Tool schemas: **8** (complete Anthropic tool_use JSON schemas)
- Max tool-call rounds: **5** (configurable; prevents infinite loops)

---

## Phase 4 — Q&A Interface (2026-04-26)

**Capability:** PM can ask natural language questions about the schedule at any time via web chat or Slack.

### Added
- `agent/qa/context_builder.py` — intent detection (9 patterns) + targeted context slicing from dashboard state
- `agent/qa/qa_engine.py` — Q&A engine with direct-answer fast path (~2s) and LLM-routed path (~10s)
- `agent/slack_command.py` — Slack `/ims` slash command via Socket Mode (no public URL required)
- Dashboard chat widget — `POST /api/ask` endpoint + full sessionStorage persistence across auto-refresh
- 26 new tests; 20-question PM acceptance test

### Metrics
- Direct queries: **~2.1s** average response time
- LLM-routed queries: **~10.1s** average response time
- Hallucination rate: **0%** (20-question acceptance test, 2026-04-26)
- Accuracy: All SRA probability values exact (PDR 22.5%, CDR 20.9%, SAT 0.8%)

### Acceptance
- Accepted by John Forbes, 2026-04-26. See [PHASE4-FEEDBACK.md](PHASE4-FEEDBACK.md).

---

## Phase 3 — Full Automation Loop (2026-04-26)

**Capability:** Fully autonomous cycle — trigger → interviews → update → analysis → output — runs on a cron schedule without human initiation.

### Added
- `agent/cycle_runner.py` — full cycle orchestration with phase tracking and locking
- `agent/scheduler.py` — APScheduler cron trigger (configurable period, default weekly)
- `agent/validation.py` — input validation (backwards movement, large jumps, missing responses)
- `agent/notifier.py` — Slack webhook and SMTP email notifications
- `agent/voice_briefing.py` — LLM + TTS voice briefing generation
- `agent/dashboard/` — FastAPI dashboard server + live HTML dashboard
- `agent/interview_orchestrator.py` — parallel CAM interview coordination
- `main.py` — `--run`, `--serve`, `--schedule` entry points

### Metrics
- Cycle time: **avg 7m 59s** across 3 acceptance test cycles (target: <10 min ✅)
- CAM response rate: **100%** (simulator)
- Validation holds: 3 → 7 across cycles (expected; threshold comparisons tighten after each update)

### Acceptance
- 3 consecutive automated cycles completed without errors. Accepted by John Forbes, 2026-04-26. See [PHASE3-FEEDBACK.md](PHASE3-FEEDBACK.md).

---

## Phase 2 — Voice Interview Layer (2026-04-25)

**Capability:** Structured voice interview agent that conducts per-CAM conversations, extracts structured data (percent complete, blockers, risks), and feeds it into the Phase 1 analysis pipeline.

### Added
- `agent/voice/interview_agent.py` — conversation state machine (GREETING → TASK → BLOCKER → RISK → RISK_DESC → CONFIRM → CLOSE)
- `agent/voice/cam_simulator.py` — Claude-powered CAM simulator for dev/test
- `agent/voice/stt_engine.py` — STT abstraction (`WhisperSTTEngine`, `MockSTTEngine`)
- `agent/voice/tts_engine.py` — TTS abstraction (`ElevenLabsTTSEngine`, `AzureTTSEngine`, `MockTTSEngine`)
- `agent/voice/teams_connector.py` — Teams/ACS connector stub (full implementation deferred to Phase 5)
- `agent/cam_directory.py` — CAM registry with business hours, retry, and escalation logic

### Notes
- Phase 2 acceptance test used the Claude-powered CAM simulator (5 CAMs, 50 tasks, 100% completion rate)
- Real Teams/ACS voice integration is implemented as a stub; full integration deferred to Phase 5 (TD-011)

### Acceptance
- Accepted by John Forbes, 2026-04-25 (simulator-based). See [PHASE2-FEEDBACK.md](PHASE2-FEEDBACK.md).

---

## Phase 1 — Proof of Concept (2026-04-25)

**Capability:** Agent reads an IMS, simulates CAM input, runs CPM + Monte Carlo SRA, synthesizes intelligence via Claude, and produces a structured Markdown report.

### Added
- `agent/file_handler.py` — MSPDI XML parsing and write-back
- `agent/critical_path.py` — CPM calculation, float analysis, near-critical flagging
- `agent/sra_runner.py` — Monte Carlo SRA (N=1000); per-milestone P50/P80/P95 and on-time probability
- `agent/llm_interface.py` — single entry point for all Anthropic API calls
- `agent/report_generator.py` — structured Markdown report generation
- `data/sample_ims.xml` — ATLAS synthetic program (57 tasks, 5 CAMs, 7 milestones)
- Architecture Decision Records: ADR-001 (MSPDI XML), ADR-002 (Monte Carlo SRA), ADR-003 (Anthropic API)

### Acceptance
- Accepted by John Forbes, 2026-04-25. See [PHASE1-FEEDBACK.md](PHASE1-FEEDBACK.md).
