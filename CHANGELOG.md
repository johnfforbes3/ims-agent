# Changelog

All notable changes to the IMS Agent are documented here. Entries are organized by phase completion, with key deliverables and metrics for each.

---

## Phase 5 Sprint 4 — Test Procedure Execution & Bug Fixes (2026-04-29)

**Summary:** Full end-to-end execution of the Phase 5 / Sprint 3 test procedure (12 sections, 242 unit tests). Ten bugs found; all ten resolved in this sprint. Three were fixed during test execution; seven more fixed immediately after. No regressions; 242/242 tests pass.

### Fixed

- **BUG-001 / TD-026** — Unit tests caused Windows fatal COM crash (`0x80010108`): `test_cycle_runner.py::test_lock_released_after_failure` called real COM automation via `find_latest_master`. Fixed by creating `tests/conftest.py` with an autouse fixture patching `find_latest_master` to return `None` for all unit tests.
- **BUG-002 / TD-027** — MS Project Planning Wizard modal dialog blocked all COM operations after opening `.mpp` files with scheduling conflicts. Fixed by setting `msp.DisplayAlerts = False` immediately after obtaining the COM instance in all four functions in `agent/mpp_converter.py` (`is_com_available`, `_get_com_instance`, `_com_mpp_to_xml`, `_com_xml_to_mpp`). `DisplayAlerts` is restored in every `finally` block.
- **BUG-003 / TD-028** — `import sys` inside the `elif args.cam_responder:` block in `main()` made `sys` a local variable for the entire function, causing `UnboundLocalError: cannot access local variable 'sys'` in five unrelated branches (`--ims-file`, `--demo-interview`, etc.). Fixed by removing the inner import — the module-level `import sys` was already sufficient.
- **BUG-004 / TD-029** — `VALIDATION_ALLOW_BACKWARDS` env var was read once at module import time (`_ALLOW_BACKWARDS` module constant). Changing `os.environ` at runtime had no effect. Fixed by replacing the constant with a `_allow_backwards()` function that calls `os.getenv` at each call site. Enables runtime reconfiguration and proper monkeypatching in tests.
- **BUG-005 / TD-030** — `calculate_critical_path()` returned no `project_float_days` key (missing from result dict; returned `None` via `.get()`). Fixed by computing the scalar as `min(total_float[tid] for tid in critical_path)` and adding `project_float_days` to the return dict and `_empty_result()`.
- **BUG-006 / TD-031** — Unit tests wrote real `*_status.json` files to `reports/cycles/` on disk on every test run. Fixed by adding an `isolated_data_dirs` autouse fixture in `tests/test_cycle_runner.py` that monkeypatches `_REPORTS_DIR` and `_DATA_DIR` to `tmp_path` for every test.
- **BUG-007 / TD-032** — COM `mpp_to_xml` / `xml_to_mpp` failed silently: `FileSaveAs` returned without error but no output file was written. Fixed by adding post-call verification in both `_com_mpp_to_xml` and `_com_xml_to_mpp`: if the output file is missing or zero-size after the save call, a `RuntimeError` is raised with a diagnostic message. Also increased `_LAUNCH_WAIT_SEC` from 8 → 12 s to give Click-to-Run MS Project more startup time.
- **BUG-008** — Test procedure step 7.5 used `/tmp/ims_test.mpp` (Linux path, invalid on Windows). Updated to use `tempfile.gettempdir()`.
- **BUG-009** — Test procedure step 5.2 expected `<meta http-equiv="refresh">` (not present). Dashboard uses JavaScript countdown. Updated step to verify JS-based auto-refresh.
- **BUG-010** — Test procedure step 3.4 referenced `TTSEngine()` directly (abstract class, raises `TypeError`). Updated to use the `build_tts_engine()` factory function.

### Test Results (Phase 5 / Sprint 3 Test Procedure)

| Metric | Value |
|--------|-------|
| Unit tests | 242 / 242 PASS |
| Required procedure steps | PASS (all non-optional) |
| Procedure steps FAIL | 0 |
| Procedure steps SKIP | 27 (Teams/ACS/Slack/TTS — no credentials) |
| Bugs found | 10 |
| Bugs fixed | 10 (all) |
| Overall verdict | CONDITIONAL PASS |

See `TEST_RESULTS.md` for the full section-by-section results.

### Changed
- `agent/validation.py` — `_ALLOW_BACKWARDS` constant → `_allow_backwards()` function
- `agent/critical_path.py` — Added `project_float_days` scalar key to result dict and `_empty_result()`
- `agent/mpp_converter.py` — Output-file verification in `_com_mpp_to_xml` and `_com_xml_to_mpp`; `_LAUNCH_WAIT_SEC` 8 → 12
- `main.py` — Removed inner `import sys` from `elif args.cam_responder:` block
- `tests/conftest.py` — NEW: autouse fixture patching `find_latest_master` to `None`
- `tests/test_cycle_runner.py` — NEW: `isolated_data_dirs` autouse fixture for I/O isolation
- `TEST_PROCEDURE.txt` — Steps 3.4, 5.2, 7.5 corrected

---

## Phase 5 Sprint 3 — Teams Chat Relay Loop, IMS Export, & Bug Fixes (2026-04-28)

**Capability:** The IMS Agent now conducts fully automated Teams Chat status interviews end-to-end without any manual intervention. The Trigger Cycle button sends opening questions to all CAMs via Bot Framework REST, the Graph CAM responder relays each reply to the dashboard server, and the server advances the interview and sends the next question — all in real time. On completion, the updated IMS is exported to a versioned folder (`data/ims_exports/`) that can be opened directly in Microsoft Project.

### Added
- `agent/cycle_runner.py` — `_export_ims_snapshot(cycle_id, ims_path)`: copies the updated IMS XML to `data/ims_exports/{cycle_id}_ims.xml` (versioned) and `data/ims_exports/latest_ims.xml` (always-current) after every successful cycle write; also runs on `apply_approved()`. Folder path surfaced as `ims_exports_dir` and `latest_ims_path` in dashboard state JSON.
- `agent/dashboard/server.py` — `POST /internal/cam_message`: relay endpoint that receives Graph CAM responder replies, looks up the active `ChatInterviewSession` by email, advances the interview via `session.process()`, and sends the next question to Teams via `_bf_send()`. Closes the session on completion.
- `agent/voice/teams_chat_connector.py` — `_bf_send(service_url, conversation_id, text)`: proactive Bot Framework REST send (no reply-to-id). `get_session_by_email()` / `remove_session_by_email()` / `register_by_email()` added to `ChatInterviewManager` for relay lookup by email.
- `data/cam_sessions.json` — seeded with real Teams chat IDs (conversation_id) for all 4 CAM accounts, extracted from responder logs.
- Dashboard header — IMS exports folder path displayed next to Trigger Cycle button.

### Changed
- `agent/cycle_runner.py` — Teams chat mode now sends opening greeting via `_bf_send()` (replaces kick-file mechanism); `directory.record_attempt()` called after each session completes/times out so CAM Response Status on the dashboard reflects actual outcome.
- `agent/graph_cam_responder.py` — Removed kick-file check from `_tick()`; added `_relay_to_server()` call after each Graph API reply to drive the interview forward.
- `agent/cycle_runner.py` — Fixed "9 out of 5 CAMs responded" display bug: fallback CAM count now uses `len(set(inp.get("cam_name") for inp in fallback_inputs))` instead of `sim_report.get("responded", 0)`.

### Fixed
- **CAM Response Status showing "No Response"**: `directory.record_attempt()` was never called in `teams_chat` mode. All 4 CAMs now show `responded=True, outcome=completed` after a successful cycle (verified cycle 20260428T095857Z).
- **`_notify_approval_required` crash**: Passed a plain string to `send_slack()` which expects a dict. Wrapped notification text in a minimal summary dict (resolves TD-022).

### Verified End-to-End (cycle 20260428T095857Z)
- Alice Nguyen: `teams_session_complete inputs=9`, `relay_interview_complete`
- Bob Martinez: `teams_session_complete inputs=10`, `relay_interview_complete`
- Carol Smith: `teams_session_complete inputs=9`, `relay_interview_complete`
- David Lee: `teams_session_complete inputs=8`, `relay_interview_complete`
- Eva Johnson: fallback simulator (not yet bootstrapped for Teams chat)

### Technical Debt Resolved
- TD-019 (proactive bot initiation) — fully resolved; relay loop verified end-to-end
- TD-022 (send_slack type error in approval notification) — resolved

---

## Phase 5 Sprint 2 — Schedule Authority, Approval Gates & Proactive Bot (2026-04-27)

**Capability:** The IMS is now the authoritative, persistent schedule. Each cycle reads what the prior cycle wrote (atomic in-place write), health scoring is deterministic, risky writes are gated behind a PM approval workflow, the Teams bot can initiate conversations proactively once a CAM has made first contact, and ngrok URL updates are automated on startup.

### Added
- `agent/schedule_health.py` — `compute_health(sra_results, cp_result, tasks)`: deterministic RED/YELLOW/GREEN scoring from SRA `prob_on_baseline` thresholds and CPM float. Eliminates LLM flip-flopping across identical data. Resolves TD-001.
- `agent/approval_store.py` — `save_pending()`, `load_pending()`, `list_all()`, `mark_approved()`, `mark_rejected()`: JSON-backed approval queue at `data/pending_approvals/<cycle_id>.json`
- `agent/ngrok_updater.py` — `auto_update_from_ngrok()`: reads ngrok local API, PATCHes Azure Bot Service endpoint via ARM REST on `--demo-chat` startup. Partially resolves TD-020.
- `agent/dashboard/server.py` — `GET /api/approvals`, `POST /api/approvals/{cycle_id}/approve`, `POST /api/approvals/{cycle_id}/reject` endpoints for PM approval workflow

### Changed
- `agent/file_handler.py` — `apply_updates()` now writes in-place atomically (`os.replace(tmp, target)`) instead of creating a `*_updated` sibling. Resets internal tree cache after write so next `parse()` re-reads fresh. Cycle N+1 now reads the IMS as Cycle N left it.
- `agent/cycle_runner.py` — Deterministic health via `compute_health()`; approval gate: validation holds save to `approval_store` and skip IMS write; `apply_approved(cycle_id, approver)` classmethod re-runs CPM+SRA+synthesis+report after PM approves; all dashboard/history writes atomic via temp+replace; `mode="teams_chat"` path wired (TD-019 partial)
- `agent/llm_interface.py` — `synthesize()` accepts `schedule_health`/`health_rationale` params; pre-computed health is injected into prompt as a given rather than asking the LLM to decide it
- `agent/voice/teams_chat_connector.py` — `proactive_create_conversation()`, `load_cam_sessions()`, `save_cam_session()` added; serviceUrl+userId persisted from reactive contact for future proactive initiation (TD-019 partial)
- `agent/dashboard/server.py` — `POST /bot/messages` now calls `save_cam_session()` on first CAM contact
- `main.py` — `--demo-chat` calls `auto_update_from_ngrok()` on startup

### Fixed
- **Approval race condition** — `POST /api/approvals/{cycle_id}/approve` was calling `mark_approved()` before spawning the background thread that called `apply_approved()`. Since `apply_approved()` required `status=="pending"`, it always found `"approved"` and errored. Fix: removed pre-emptive `mark_approved()` from the endpoint; `apply_approved()` now owns that call atomically.

### Known Issues (tracked)
- Dashboard countdown displays 60s but page reloads every 5s during active cycles due to `pollStatus()` conflict — tracked as TD-021
- Proactive Teams bot requires prior reactive contact to bootstrap `cam_sessions.json` — tracked as TD-019

---

## Tier 4 — Teams Chat Bot Interview (2026-04-27)

**Capability:** The ATLAS Scheduler bot conducts fully automated CAM status interviews via Teams direct chat messages — no audio, no TTS, no Azure ACS required. The bot sends structured questions, processes natural-language replies through the LLM interview agent, captures percent-complete and blockers, and runs IMS impact analysis on completion. Latency is ~2 s/turn (vs ~10–14 s for the voice path).

### Added
- `agent/voice/teams_chat_connector.py` — `ChatInterviewManager` singleton (maps Teams user IDs to active sessions), `ChatInterviewSession` (wraps `InterviewAgent` for one interview), `_bf_reply()` (posts text reply via Bot Framework REST), `_bf_typing()` (sends typing indicator)
- `agent/demo_chat.py` — `run_chat_demo()`: loads IMS, registers wildcard `ChatInterviewSession`, waits for the first Teams user to message the bot, streams interview to completion, prints extracted CAM data and IMS impact analysis
- `agent/dashboard/server.py` — `POST /bot/messages` endpoint: receives Bot Framework Activity objects from Teams, routes to `ChatInterviewManager`, sends replies via `_bf_reply()`
- `main.py` — `--demo-chat --cam "<name>"` mode: starts FastAPI server on background thread, registers CAM session, prints deep-link URL to open the chat

### Changed
- `agent/voice/teams_chat_connector.py` — MSAL token authority changed from `login.microsoftonline.com/botframework.com` to `login.microsoftonline.com/<tenant-id>` (fix: App Registration lives in org tenant, not BF directory)
- `agent/demo_chat.py` — `_print_cp_diff()`: `calculate_critical_path()` returns a list of string task IDs, not dicts; fixed set construction (was calling `.get("task_id")` on strings)
- All source files — Dashboard port default changed from `8080` to `9000` (`DASHBOARD_PORT` env var)

### Teams App Publishing Flow (completed)
1. **App Registration** — AAD app `9afa38ea-6efc-45b5-9f70-248aa32ff9a4` in `intelligenceexpanse.onmicrosoft.com`
2. **Azure Bot Service** — messaging endpoint set to `https://<ngrok-url>/bot/messages`; Teams channel enabled
3. **App Manifest** — `manifest.json` + `color.png` + `outline.png` zipped; fixed: removed invalid `packageName` field, aligned `id` with `botId`
4. **Developer Portal** — package imported at `dev.teams.microsoft.com`, published to org catalog
5. **Teams Admin Center** — custom app submission approved at `admin.teams.microsoft.com`
6. **Teams installation** — bot installed via `https://teams.microsoft.com/l/app/<id>` deep link

### Demo Command
```
python main.py --demo-chat --cam "Alice Nguyen"
# Then open the printed deep link and send any message to start
```

### End-to-End Test Result
- CAM: Alice Nguyen, 8 tasks
- Bot correctly probed blockers, flagged ICD (60%) and RTM (40%) as schedule risks
- IMS impact analysis: 10,000 Monte Carlo iterations; MS-02 PDR on-time probability = 36%

### Known Limitations
- Bot is **reactive only** — waits for the CAM to send the first message. Proactive initiation (bot opens the conversation) requires a stored `serviceUrl` + `conversationId` per CAM and a `CreateConversation` API call (tracked as TD-019)
- Trigger Cycle button uses `CAMSimulator`, not Teams Chat — wiring requires registering all CAM sessions and replacing the simulator loop with `session.done` event waits (see TD-019)
- ngrok URL changes each session on the free plan; must update Azure Bot Service messaging endpoint each run (tracked as TD-020)

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
