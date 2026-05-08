# IMS Agent — Technical Debt Register

Track known shortcuts, workarounds, and deferred improvements by phase.
Each entry: what it is, why it was deferred, and a suggested fix.

---

## Phase 1

### TD-001 — Schedule health threshold is manual / LLM-generated — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.1 sprint  
**File:** `agent/schedule_health.py` (new), `agent/cycle_runner.py`  
**Description:** `compute_health()` in `agent/schedule_health.py` implements deterministic RED/YELLOW/GREEN thresholds driven by env-var constants (`HEALTH_RED_MILESTONE_PROB`, `HEALTH_YELLOW_MILESTONE_PROB`, `HEALTH_RED_FLOAT_DAYS`, `HEALTH_YELLOW_FLOAT_DAYS`). The computed label is passed into the LLM prompt as a given; the LLM no longer decides the label. `CycleRunner` calls `compute_health()` and writes the result to `dashboard_state.json`. Unit tests cover all three threshold transitions.

---

### TD-002 — `can_call_now()` uses local machine time, not CAM's timezone — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.1 sprint  
**File:** `agent/cam_directory.py` — `can_call_now()`  
**Description:** `can_call_now()` now uses `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError` (stdlib, Python 3.9+) to convert the current UTC time into the CAM's IANA timezone before comparing hours. Falls back to UTC with a warning log if the timezone string is unrecognised. No extra dependency required. Covered by `TestTimezoneAwareness` (3 tests: out-of-hours at 06:00 UTC, in-hours at 18:00 UTC, invalid timezone fallback).

---

### TD-003 — CAM call history is in-memory only (not persisted between runs) — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.1 sprint  
**File:** `agent/cam_directory.py` — `save_to_file()`, `load_from_file()`  
**Description:** `save_to_file()` now writes `{"cams": [...], "call_history": {...}}` instead of a bare JSON array. `load_from_file()` detects both the legacy list format (backward compatible) and the new dict format, restoring `_call_history` as proper `CallRecord` objects. `should_retry()` and `should_escalate()` now honour history that survived a process restart. Covered by `TestCallHistoryPersistence` (4 tests: roundtrip, should_retry=False after reload, should_escalate=True after reload, legacy format loads cleanly).

---

## Phase 2

### TD-004 — `CONFIRM` state handler loops indefinitely on negative responses — **RESOLVED**
**Resolved:** Phase 3 sprint 1 — 2026-04-25  
**File:** `agent/voice/interview_agent.py` — `_handle_confirm`  
**Severity:** High  
**Description:** When the confirmation summary is read back and the CAM says "No, that's wrong" or any response containing `_is_negative()` match, the handler re-asks "can you tell me which task needs correcting?" The CAM's correction response also typically contains "no" ("No, SE-04 is 100%, not 4%"), which re-triggers the same handler — resulting in an infinite correction loop until the 60-turn safety limit is hit.  
**Observed in demo:** Alice Nguyen generated 20 increasingly exasperated "No." responses escalating from "the agent is broken" through drafting written notices to the Chief Engineer's office, then sending auto-replies.  
**Why deferred:** Safety limit (60 turns) prevents actual hang; task data is captured before CONFIRM, so results are not lost. FB-2-004 acknowledged.  
**Suggested fix:**
1. Track a `_confirm_retry_count` — after 2 failed correction cycles, close the interview anyway and log a warning.
2. In `_handle_confirm`, distinguish "flat denial" (`_is_negative` with no numeric content) from "correction provided" (`_extract_percent` or task ID found in response). Only re-ask if a specific correction is detected.
3. Cap re-asks at 2 before calling `_close_interview()`.

---

### TD-005 — `_extract_percent` only returns first numeric match — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.1 sprint (already implemented in prior session)  
**File:** `agent/voice/interview_agent.py` — `_extract_percent()`  
**Description:** `_extract_percent()` now uses a three-priority extraction system: (1) explicit `\d+%` matches, (2) numbers following context words ("is", "at", "about", "around", "approximately", "currently"), (3) numbers that skip task-ID-like tokens (digits directly after `SE-`, `HW-`, `SW-`, etc.). The "SE-04 is 100%, not 4%" case is now handled correctly by priority-1 extraction finding the explicit `%` token. Covered by existing unit tests in `tests/test_interview_agent.py`.

---

### TD-006 — CAM simulator re-explains same blocker for every task that shares it — **RESOLVED**
**Resolved:** Phase 5 sprint 2 — 2026-04-27  
**File:** `agent/voice/cam_simulator.py` — `_build_context`  
**Description:** `_build_context()` now passes the full conversation history (was last 6 turns / 3 exchanges) so all prior blocker explanations remain visible to Claude throughout the interview. An explicit instruction is appended: "if you have already explained a blocker or root cause earlier in this conversation, do not re-explain it in full — reference it briefly and move on." Together these eliminate the repeated full-blocker re-explanation when multiple tasks share the same root cause.

---

### TD-007 — Report blocker text is untruncated in table — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.1 sprint  
**File:** `agent/report_generator.py` — `_truncate_blocker()`, `_build_report()`  
**Description:** `_truncate_blocker(text, max_len=120)` helper cuts at the first natural sentence boundary (`. `, `! `, `? `) within `max_len`, or hard-truncates at 120 chars, appending `*` to signal truncation. The full blocker text is collected in a `blocker_details` list and rendered in a "## Blocker Details" appendix section at the end of the report. Covered by `TestTruncateBlockerHelper` (5 unit tests) and `TestBlockerTruncationIntegration` (3 integration tests).

---

### TD-008 — `_nearest_milestone_name()` always returns a generic string — **RESOLVED**
**Resolved:** Phase 5 sprint 2 — 2026-04-27  
**File:** `agent/interview_orchestrator.py`, `agent/voice/interview_agent.py`  
**Description:** `_nearest_milestone_name()` was already implemented correctly in `InterviewAgent` (filters `self._milestones` by `finish >= now`, returns shortened milestone name). The gap was that `InterviewOrchestrator._interview_one()` constructed `InterviewAgent(cam_name, cam_tasks)` without passing `all_tasks`, so `self._milestones` was always empty and the fallback "the next milestone" was always returned. Fixed by storing `tasks` as `self._all_tasks` at the start of `InterviewOrchestrator.run()` and passing `all_tasks=self._all_tasks` to every `InterviewAgent` constructor call.

---

### TD-009 — No rate limiting on CAM simulator API calls — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.4 sprint  
**File:** `agent/voice/cam_simulator.py` — `respond()`, `_call_delay_s()`  
**Description:** Added `_call_delay_s()` helper that reads `SIMULATOR_CALL_DELAY_MS` env var at call time (hot-reload, default 200 ms). `CAMSimulator.respond()` calls `_call_delay_s()` and applies `time.sleep(delay)` before each Anthropic API call when the delay is > 0. Setting `SIMULATOR_CALL_DELAY_MS=0` disables throttling entirely. Covered by `TestSimulatorRateLimit` (3 tests: sleep called with configured delay, zero delay skips sleep, hot-reload reads env at call time).

---

### TD-010 — WhisperSTTEngine never tested with real audio — **RESOLVED**
**Resolved:** 2026-05-04 — Phase 8.3 / TD-010 sprint  
**File:** `tests/test_stt_engine.py` — `TestWhisperIntegration` (4 tests)  
**Description:** Added `TestWhisperIntegration` class marked `@pytest.mark.integration`. Tests skip automatically when `openai-whisper` is not installed. A synthetic 440 Hz WAV file is generated in-process using Python's `wave` + `struct` modules (no external fixture file needed). Tests validate: package is importable, `WhisperSTTEngine("tiny")` instantiates correctly, `transcribe_file()` returns a properly-typed `TranscriptionResult`, and `transcribe_file()` raises `FileNotFoundError` for a non-existent path. The `integration` mark is registered in `tests/conftest.py` via `pytest_configure`. Run with: `pytest tests/test_stt_engine.py -m integration` (requires `pip install openai-whisper` and `ffmpeg` on PATH).

---

### TD-011 — TeamsACSConnector is a stub with no test coverage
**File:** `agent/voice/teams_connector.py:125`  
**Severity:** Low (known stub)  
**Description:** `TeamsACSConnector` raises `NotImplementedError` in `__init__`. It has zero test coverage because it cannot be instantiated without Azure credentials.  
**Why deferred:** ADR-004: Azure ACS pending subscription. Intentional stub.  
**Suggested fix:** When Azure ACS credentials are available: implement the full connector, add integration tests against the ACS sandbox environment. In the interim, mock the `CallAutomationClient` in unit tests to at least validate the connector's call flow logic.

---

### TD-012 — IMS-AGENT-PROGRAM-PLAN.md lives outside the repo — **RESOLVED**
**Resolved:** Phase 3 — 2026-04-26  
**File:** `IMS-AGENT-PROGRAM-PLAN.md`  
**Severity:** Low  
**Description:** The authoritative program plan is now at `ims-agent/IMS-AGENT-PROGRAM-PLAN.md` — inside the repo root. It is version-controlled alongside the code. The Phase 3 acceptance test updates and Phase 4 gate are committed from this location.

---

## Phase 3

### TD-013 — Dashboard state file write is not atomic — **RESOLVED**
**Resolved:** 2026-05-03 — §4.2a fix  
**File:** `agent/cycle_runner.py` — `_update_dashboard_state`  
**Severity:** Medium  
**Description:** `state_path.write_text(...)` wrote JSON directly to the target file; a mid-write kill left the file truncated or invalid.  
**Fix:** §4.2a replaced the `write_text()` call with a write-to-temp + `os.replace(tmp, state_path)` pattern, adding an exponential-backoff retry loop (0.1s → 0.2s → raise) for Windows `PermissionError [WinError 5]` from OneDrive sync locks. `os.replace` is atomic on POSIX and on Windows when src/dst are on the same volume. Verified by `TestDashboardStateRetry` (4 tests).

---

### TD-014 — Notifier env vars loaded at module import time — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.1 sprint  
**File:** `agent/notifier.py` — `_get_notifier_config()`  
**Description:** Removed the 8 module-level `_SLACK_WEBHOOK`, `_EMAIL_HOST`, etc. globals. Added `_get_notifier_config()` helper that calls `load_dotenv(override=True)` and reads all credentials via `os.getenv` at call time. `send_slack()` and `send_email()` both call `cfg = _get_notifier_config()` at the top of their bodies. Credential rotations in `.env` now take effect on the next send without a process restart. Covered by `TestNotifierHotReload` (4 tests in `tests/test_notifier.py`).

---

### TD-015 — Validation holds not surfaced on the live dashboard — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.1 sprint  
**File:** `agent/cycle_runner.py` — `_update_dashboard_state`, `agent/dashboard/templates/index.html`  
**Description:** `_update_dashboard_state` already wrote `validation_holds` to state (confirmed in prior session). Added a collapsible `<details>` "Validation Alerts" panel to `index.html` using Jinja2: when `state.validation_holds` is non-empty, a yellow-bordered card appears (open by default) listing each hold as a table row with task ID, CAM, rule badge, and detail text. Panel is completely absent from the DOM when the list is empty.

---

## Phase 4

### TD-016 — Q&A context builder loads full state on every query; no caching — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.4 sprint  
**File:** `agent/qa/context_builder.py` — `load_state()`, `load_history()`  
**Description:** Added module-level cache globals (`_STATE_CACHE`, `_STATE_CACHE_AT`, `_STATE_CACHE_MTIME`, `_HISTORY_CACHE`, etc.) with a `_CACHE_TTL_S = 30.0` second TTL. Both `load_state()` and `load_history()` check mtime equality against the cached value first — if the file was updated (different `st_mtime`), the cache is immediately invalidated regardless of TTL. A freshly completed cycle is always visible within one poll. Covered by `TestContextBuilderCache` (3 tests: second call within TTL returns cache, cache invalidated on mtime change, missing file returns {}).

---

### TD-017 — No authentication on /api/ask or dashboard — **RESOLVED**
**Resolved:** Phase 5 — 2026-04-26  
**File:** `agent/dashboard/server.py`  
**Description:** All `/api/*` routes now require `X-API-Key` (read) or `X-Admin-Key` (admin). Two-key RBAC model implemented: `DASHBOARD_API_KEY` grants access to read routes; `DASHBOARD_ADMIN_KEY` gates `POST /api/trigger` and `POST /api/admin/purge`. Per-IP rate limiting added to `POST /api/ask` via `QA_RATE_LIMIT_PER_HOUR`. Dashboard HTML at `/` still unprotected by API key (browsers don't send custom headers on page loads) — production deployments should put it behind a reverse proxy with TLS and auth (TD tracked in SECURITY.md §Dashboard HTML).

---

### TD-018 — Slack slash command sends "Thinking…" then overwrites it, creating a jarring UX — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.1 sprint  
**File:** `agent/slack_command.py` — `_handle_ims_command`  
**Description:** Both the success path (`respond(blocks=blocks, ..., replace_original=True)`) and the error path (`respond(text=f":warning: ...", replace_original=True)`) now use `replace_original=True`. slack-bolt's `respond()` uses the `response_url` from the slash command payload to replace the "Thinking…" placeholder in-place, eliminating the double-message. No additional Slack API calls required.

---

## Tier 4 — Teams Chat Bot

### TD-019 — Chat bot is reactive only; cannot initiate conversations proactively — **RESOLVED**
**Resolved:** Phase 5 sprint 3 — 2026-04-28. Full end-to-end relay loop verified with all 4 live CAM accounts.  
**File:** `agent/voice/teams_chat_connector.py`, `agent/cycle_runner.py`, `agent/dashboard/server.py`, `agent/graph_cam_responder.py`  
**Description:** Cycle runner now sends the opening interview question directly via Bot Framework REST (`_bf_send()`), bypassing the broken Graph-API→BF-webhook path. The Graph CAM responder polls Teams, posts replies via Graph API, then relays each response to `POST /internal/cam_message` on the local dashboard server. The server advances the interview session via `ChatInterviewSession.process()` and sends the next question back to Teams via `_bf_send()`. Full relay loop: BF REST → Teams → Graph poll → relay → BF REST. Verified end-to-end with Alice Nguyen, Bob Martinez, Carol Smith, David Lee — all 4 `teams_session_complete` with 8–10 task inputs each; `relay_interview_complete` logged for all 4 emails.

---

### TD-020 — ngrok URL must be manually updated in Azure Bot Service on each restart — **PARTIALLY RESOLVED**
**Partially resolved:** Phase 5 sprint 2 — 2026-04-27. Auto-update implemented; requires Azure management env vars.  
**File:** `agent/ngrok_updater.py`, `.env`  
**Severity:** Medium  
**Description:** The free ngrok plan generates a new URL on every `ngrok http 9000` invocation. The Azure Bot Service messaging endpoint must be manually updated each time. This is acceptable for demos but breaks unattended production runs.  
**Progress:** `agent/ngrok_updater.py` reads the ngrok local API (`http://127.0.0.1:4040/api/tunnels`) and PATCHes the Azure Bot Service endpoint via ARM REST API on `--demo-chat` startup. Requires `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_BOT_NAME` in `.env`. Falls back to printing manual instructions if those vars are absent.  
**Remaining work:** Either set Azure management env vars for fully automated update, or upgrade to ngrok paid plan (`NGROK_SUBDOMAIN`) / deploy with fixed FQDN to eliminate ngrok entirely.

---

## Phase 5 / Sprint 2

### TD-021 — Dashboard countdown resets to 5 during active cycle instead of counting down — **RESOLVED**
**Resolved:** 2026-05-03 — Phase 7.1 sprint (already implemented in prior session)  
**File:** `agent/dashboard/templates/index.html` — `pollStatus()`, countdown JS  
**Description:** The dashboard now uses a single AJAX polling loop: `_pollMs` is set to 5000ms when a cycle is active, 60000ms when idle. `_nextPollAt` tracks the next fire time and the countdown badge is updated from `_nextPollAt - Date.now()`. `_updateCycleCard()` patches the "Cycle In Progress" card DOM in-place without a full reload. A full reload is triggered only when `cycle_active` transitions from `true` to `false` so the final health/report data loads cleanly.

---

## Atlas Scheduler — Conversation Quality (2026-05-03)

### TD-033 — `_nearest_milestone_name()` ignored task finish date — **RESOLVED**
**Resolved:** 2026-05-03 — commit `52878be`  
**File:** `agent/voice/interview_agent.py` — `_nearest_milestone_name()`  
**Description:** The method returned the globally-nearest upcoming milestone by date, ignoring the current task's own finish date. This caused the logically wrong question "Could this put Milestone X at risk?" when the task was scheduled to complete *after* Milestone X had already passed. Observed for documentation tasks finishing in June being asked about a June 3 milestone.  
**Fix:** Changed lower bound from `datetime.now()` to `max(datetime.now(), task_finish)`. Milestone selection now returns the nearest milestone at or after the task's own finish date.

---

### TD-034 — `_flagged_milestones[True]` auto-inherit set risk=True for all subsequent tasks — **RESOLVED**
**Resolved:** 2026-05-03 — commit `0e68d50`  
**File:** `agent/voice/interview_agent.py` — `_handle_pct` (2 locations) and `_handle_blocker`  
**Description:** When a CAM confirmed YES for a milestone risk, all subsequent tasks with blockers sharing the same milestone auto-set `risk_flag=True` without asking. This caused excessive CONFIRM corrections (5 corrections for Carol in a single cycle) because most subsequent tasks were NOT milestone risks — only the first one was.  
**Fix:** Changed all 3 locations from `self._current_risk_flag = True` to `self._current_risk_flag = False`. The milestone is already flagged once; subsequent tasks should default to False and not be asked again (handled by `_milestone_no_count` threshold).

---

### TD-035 — No suppression for repeated milestone risk question — **RESOLVED**
**Resolved:** 2026-05-03 — commit `8b05a34`  
**File:** `agent/voice/interview_agent.py` — `_handle_blocker`, `_handle_pct`, `__init__`  
**Description:** When many tasks share the same milestone, the agent asked "Could this put [milestone] at risk?" for every task, even after the CAM had already answered NO multiple times. Observed: CAMs responding "you've asked me this four times now."  
**Fix:** Added `_milestone_no_count: dict[str, int]` instance variable. After ≥2 NO answers for the same milestone in a session, subsequent tasks with blockers skip the risk question and auto-set `risk_flag=False`.

---

### TD-036 — CONFIRM state looped on correction language in CAM response — **RESOLVED**
**Resolved:** 2026-05-03 — commit `8b05a34`  
**File:** `agent/voice/interview_agent.py` — `_handle_confirm`  
**Description:** When a CAM said "No, that's wrong" in CONFIRM, the LLM classifier classified it as a negative, re-asked for correction, and the CAM's correction response (often starting with "No,") re-triggered the same path — creating a correction loop. This was the root cause underlying TD-004, which was only partially resolved previously.  
**Fix:** Added a keyword pre-check in `_handle_confirm` that fires *before* the LLM classifier. Detects correction language ("actually", "that's wrong", "no,", "not quite", etc.) and routes directly to `_extract_and_apply_correction()`, bypassing the negative-response handler. Reduced CONFIRM corrections from 12 per cycle to 3 (75% reduction).

---

## Phase 5 / Sprint 3

### TD-022 — `_notify_approval_required` passed plain string to `send_slack` — **RESOLVED**
**Resolved:** Phase 5 sprint 3 — 2026-04-28.  
**File:** `agent/cycle_runner.py` — `_notify_approval_required`  
**Description:** The method built a plain Slack-formatted string `msg` and called `send_slack(msg)`, but `send_slack` expects a dict with keys `health`, `top_risks`, `cams_responded`, `cams_total`. Caused `AttributeError: 'str' object has no attribute 'get'` when validation holds triggered the approval-required notification path. Fixed by wrapping the message in a minimal summary dict.

---

### TD-025 — MS Project COM automation blocked by Click-to-Run AppV isolation
**File:** `agent/mpp_converter.py`
**Severity:** Medium
**Description:** M365 Click-to-Run (C2R) installations virtualise Office executables inside an AppV container. `win32com.client.Dispatch("MSProject.Application")` raises `CO_E_SERVER_EXEC_FAILURE (0x80080005)` because the COM activation goes through the C2R bootstrap layer, which doesn't allow COM calls from external processes. `GetActiveObject` also fails because the running WINPROJ.EXE process doesn't register itself in the Windows ROT when launched outside the C2R container. `/regserver` does not fix it. The agent falls back gracefully to XML-only mode; `.mpp` files are not written until this is resolved.
**Why deferred:** Requires a one-time user action to fix.
**Fix options (either one resolves it):**
1. **Quick Repair (5 min):** Settings → Apps → Microsoft 365 → ⋯ → Modify → Quick Repair. Rewrites the C2R COM activation infrastructure.
2. **MPXJ backend (no MS Project COM needed):** Install OpenJDK 21 (https://adoptium.net/) then `pip install mpxj`. Update `mpp_converter.py` to add an MPXJ code path alongside the COM path.

---

### TD-024 — Eva Johnson has no Teams chat session; shows "not_contacted" on dashboard
**File:** `data/cam_sessions.json`, `data/cam_identity_map.json`  
**Severity:** Low  
**Status:** RESOLVED — 2026-05-07. Eva's Teams session is confirmed working. She responded in production cycle `20260507T222726Z`. All 5 CAMs (Alice, Bob, Carol, David, Eva) are active with working sessions.

---

### TD-023 — Bootstrap first-contact required before Teams chat mode works for new CAMs — **RESOLVED**
**Resolved:** 2026-05-04 — Phase 8.3 / TD-023 sprint  
**File:** `agent/bootstrap_sessions.py` (new), `main.py` (`--bootstrap-sessions` flag), `tests/test_bootstrap_sessions.py` (17 tests)  
**Description:** Added `python main.py --bootstrap-sessions` CLI flag. The command reads `cam_identity_map.json` and `cam_sessions.json`, identifies CAMs with no established session, and either: (a) sends a proactive bootstrap email via Microsoft Graph API `POST /users/{sender}/sendMail` when `BOOTSTRAP_SENDER_EMAIL`, `TEAMS_BOT_APP_ID`, `TEAMS_BOT_APP_SECRET`, and `TEAMS_TENANT_ID` are all configured (requires `Mail.Send` app permission), or (b) prints step-by-step manual instructions. `--wait` flag polls `cam_sessions.json` every 30s until all sessions appear or `BOOTSTRAP_WAIT_TIMEOUT_SEC` elapses. `--cam <name>` filters to a single CAM. Gracefully skips if `msal`/`requests` are not installed.

---

## Phase 8.4 — Latency & Reliability Sprint (2026-05-05)

### TD-037 — Validation backwards-movement rule raised false failures when blocker was documented — **RESOLVED**
**Resolved:** 2026-05-05 — Phase 8.4 sprint  
**File:** `agent/validation.py` — `ScheduleValidator.validate()`  
**Severity:** Medium  
**Description:** The backwards-movement validation rule in `ScheduleValidator.validate()` always emitted a hard failure (`ValidationFailure` added to `failures` list) whenever `new_pct < prev_pct`, regardless of whether the CAM had provided an explanation in the `blocker` or `risk_description` fields. This caused 4 false-positive holds per cycle — all 4 tasks had documented blockers that fully explained the regression, but all 4 required manual PM approval before the IMS write could proceed.  
**Fix:** Added explanation check immediately after detecting a backwards move: `explanation = (inp.get("blocker") or "").strip() or (inp.get("risk_description") or "").strip()`. When a non-empty explanation is found, the issue is downgraded to a `warnings` entry (detail includes the blocker text truncated to 120 chars) — the IMS write proceeds, the PM is informed via the Validation Alert panel but is not blocked. Only genuinely unexplained decreases remain hard failures. No new tests added (the existing `TestBackwardsMovement` suite was updated to cover both the explained-warning and unexplained-failure paths).

---

### TD-038 — `SIMULATOR_MODEL` / `CLASSIFIER_MODEL` env vars pointed at unavailable model ID — **RESOLVED**
**Resolved:** 2026-05-05 — Phase 8.4 sprint; code-level default also fixed 2026-05-06  
**File:** `.env`, `agent/voice/cam_simulator.py`, `agent/voice/interview_agent.py`  
**Severity:** High (production outage — all CAM responses failed)  
**Description:** Both `SIMULATOR_MODEL` and `CLASSIFIER_MODEL` in `.env` were set to `claude-3-5-haiku-20241022`. The Anthropic API for this account tier returns HTTP 404 for date-stamped model IDs in the 3.x series. Every CAM simulator call and every NLU classification call failed with `Error code: 404 — model: claude-3-5-haiku-20241022`, causing the responder to fall into retry/error loops (30-60s per turn) before ultimately generating no interview data.  
**Fix:** Changed both env vars to `claude-haiku-4-5` (the correct 4.x naming convention). Additionally, the code-level fallback default in `cam_simulator.py` (`_SIM_MODEL = os.getenv("SIMULATOR_MODEL", "claude-3-5-haiku-20241022")`) was also updated to `claude-haiku-4-5` so the default is consistent even without `.env` override. Production latency dropped from 30-60s/turn to ~5s/turn after the fix. `CONFIGURATION.md` updated with a note about the naming convention requirement.

---

### TD-039 — Dead `_SIMULATOR_SYSTEM_PROMPT` variable caused markdown asterisks in CAM responses — **RESOLVED**
**Resolved:** 2026-05-06  
**File:** `agent/voice/cam_simulator.py`, `agent/llm_interface.py`  
**Severity:** Medium (CAM interview responses contained markdown formatting; asterisks appeared in live Teams conversations)  
**Description:** `cam_simulator.py` defined `_SIMULATOR_SYSTEM_PROMPT` containing the correct "No Markdown — plain speech only. No bold, no bullets, no headers." instruction, but this variable was never passed to the API. `CAMSimulator.respond()` called `self._llm.ask(full_prompt, context="")` without a `system` override; `LLMInterface.ask()` hardcoded `system=_SYSTEM_PROMPT` (the PM-analyst prompt), completely ignoring the simulator's plain-speech prompt. Result: simulated CAM responses contained `**bold**` and other markdown that appeared verbatim in live Teams messages.  
**Fix:** Added optional `system: str | None = None` parameter to `LLMInterface.ask()`. When provided, it replaces the default PM-analyst system prompt (`system=system or _SYSTEM_PROMPT`). `CAMSimulator.respond()` now passes `system=_SIMULATOR_SYSTEM_PROMPT` explicitly. Verified: CAM responses are plain speech with no markdown formatting.

---

## Phase 8.5 — CI & Infrastructure (2026-05-06)

### TD-040 — No CI pipeline; regressions not automatically blocked — **RESOLVED**
**Resolved:** 2026-05-06 — Phase 8.5 sprint  
**File:** `.github/workflows/ci.yml` (new)  
**Severity:** High (structural gap — any commit could introduce a regression with no automated catch)  
**Description:** The project had 445 unit tests and a `conftest.py` that registered the `integration` mark with a comment "Skipped in CI" — but no CI existed to skip them in. A broken commit could go undetected until a manual test run.  
**Fix:** Created `.github/workflows/ci.yml`. Windows runner (`windows-latest`) matching the production environment. Python 3.13, Java 21 (for MPXJ/jpype1). Installs full `requirements.txt`. Runs `pytest tests/ -q -m "not integration" --tb=short` on every push and PR to main/master. Requires `ANTHROPIC_API_KEY` GitHub secret (LLM-backed unit tests make real API calls for NLU classification and Q&A). Sets `SIMULATOR_CALL_DELAY_MS=0` to skip inter-call throttle in CI.

---

### TD-041 — `Dockerfile` base image Python version mismatch — **RESOLVED**
**Resolved:** 2026-05-06 — Phase 8.5 sprint  
**File:** `Dockerfile`  
**Severity:** Medium (containerized deploy would use Python 3.11 while codebase targets 3.13)  
**Description:** `Dockerfile` used `FROM python:3.11-slim` while all development, testing, and production operation runs on Python 3.13.3. The mismatch risked incompatibilities with 3.12+ syntax (f-string expression nesting, `zoneinfo`, `tomllib`, type union syntax) and could produce hard-to-diagnose failures only visible in containerized deployment.  
**Fix:** Changed base image to `FROM python:3.13-slim`. One-line change; no other Dockerfile modifications required.

---

## Phase 5 / Sprint 4 — Test & Bug Fix Sprint

### TD-026 — Unit tests caused Windows fatal COM crash — **RESOLVED**
**Resolved:** Phase 5 sprint 4 — 2026-04-29  
**File:** `tests/conftest.py` (new file)  
**Description:** `test_cycle_runner.py::test_lock_released_after_failure` called `CycleRunner.run()` with a nonexistent IMS path. `_run_inner()` called `find_latest_master()` which found a real `.mpp` file in `data/ims_master/`, triggering MS Project COM automation. The COM call caused a fatal Windows exception (`0x80010108: RPC_E_DISCONNECTED`) that crashed the entire pytest process with no test result captured.  
**Fix:** Created `tests/conftest.py` with an `autouse=True` fixture patching `agent.mpp_converter.find_latest_master` to return `None` for all unit tests. Tests needing the real MPP workflow opt out explicitly.

---

### TD-027 — MS Project Planning Wizard modal dialog blocked all COM operations — **RESOLVED**
**Resolved:** Phase 5 sprint 4 — 2026-04-29  
**File:** `agent/mpp_converter.py`  
**Description:** Task 21 in `data/sample_ims.xml` is linked to a non-movable predecessor. When MS Project opened the file via COM, it displayed a "Planning Wizard" modal dialog asking whether to honour the dependency. This blocked all COM calls with RPC errors (`0x800706be`), making `mpp_to_xml` and `xml_to_mpp` hang indefinitely and eventually raise. Any test or cycle run that triggered COM would stall.  
**Fix:** Added `msp.DisplayAlerts = False` immediately after obtaining the COM instance in all four functions: `is_com_available()`, `_get_com_instance()`, `_com_mpp_to_xml()`, `_com_xml_to_mpp()`. `DisplayAlerts` is restored to `True` in every `finally` block.

---

### TD-028 — `import sys` inside `main()` caused `UnboundLocalError` in five CLI branches — **RESOLVED**
**Resolved:** Phase 5 sprint 4 — 2026-04-29  
**File:** `main.py`  
**Description:** An `import sys` statement existed inside the `elif args.cam_responder:` branch of `main()`. Python scoping rules make any `import` inside a function body create a local binding for the **entire function**, regardless of the branch taken. Any branch that called `sys.exit(1)` before execution reached the `cam_responder` block raised `UnboundLocalError: cannot access local variable 'sys' before assignment`. Affected: `--ims-file <nonexistent>`, `--demo-interview` (missing `--meeting-url`), `--demo-interview --meeting-url <url>` (missing `--callback-url`).  
**Fix:** Removed the inner `import sys`. The module-level `import sys` at the top of the file is sufficient for all branches.

---

### TD-029 — `VALIDATION_ALLOW_BACKWARDS` read at module import time — **RESOLVED**
**Resolved:** Phase 5 sprint 4 — 2026-04-29  
**File:** `agent/validation.py`  
**Description:** `_ALLOW_BACKWARDS = os.getenv("VALIDATION_ALLOW_BACKWARDS", "false").lower() == "true"` was a module-level constant, evaluated once at import. Setting `os.environ["VALIDATION_ALLOW_BACKWARDS"] = "true"` at Python runtime after module import had no effect. Test harnesses and integration tests that tried to flip the flag via `monkeypatch.setenv` or `os.environ` got incorrect results.  
**Fix:** Replaced the module constant with a `_allow_backwards()` function that calls `os.getenv` at each invocation. The single call site in `validate()` was updated accordingly.

---

### TD-030 — `calculate_critical_path()` returned no `project_float_days` scalar — **RESOLVED**
**Resolved:** Phase 5 sprint 4 — 2026-04-29  
**File:** `agent/critical_path.py`  
**Description:** The return dict of `calculate_critical_path()` had no `project_float_days` key, even though `total_float` (a per-task dict) was populated. Callers using `cp.get("project_float_days")` received `None`. The test procedure (step 2.4) documented this key as expected, creating a false FAIL for testers.  
**Fix:** After computing `critical_path` and `total_float`, the minimum float across all CP tasks is computed and stored as `project_float_days` (a `float`). The key is also added to `_empty_result()`.

---

### TD-031 — Unit tests wrote real status files to `reports/cycles/` on every run — **RESOLVED**
**Resolved:** Phase 5 sprint 4 — 2026-04-29  
**File:** `tests/test_cycle_runner.py`  
**Description:** `CycleRunner` writes `*_status.json` files to `_REPORTS_DIR/cycles/` (resolved from the `REPORTS_DIR` env var). Unit tests that called `CycleRunner.run()` without patching `_REPORTS_DIR` created real files in the project's `reports/cycles/` directory. These accumulated across test runs and could interfere with test assertions in other tests (e.g., step 4.4 checking "latest" cycle status).  
**Fix:** Added an `isolated_data_dirs` autouse fixture in `tests/test_cycle_runner.py` that uses `monkeypatch` to redirect both `_REPORTS_DIR` and `_DATA_DIR` to a `tmp_path`-scoped temporary directory for every test.

---

### TD-032 — COM `mpp_to_xml` / `xml_to_mpp` failed silently — **RESOLVED**
**Resolved:** Phase 5 sprint 4 — 2026-04-29  
**File:** `agent/mpp_converter.py`  
**Description:** After the `is_com_available()` probe called `msp.Quit()`, subsequent COM calls had to re-launch MS Project. The 8-second `_LAUNCH_WAIT_SEC` was sometimes insufficient for the Click-to-Run bootstrap, causing `FileSaveAs` to return a success code without writing the file. The caller received no error but the output path was empty.  
**Fix:**  
1. Added post-call output-file verification in both `_com_mpp_to_xml` and `_com_xml_to_mpp`: if the file is missing or zero-size after `FileSaveAs`, a `RuntimeError` is raised with a diagnostic message.  
2. Increased `_LAUNCH_WAIT_SEC` from 8 → 12 seconds to give Click-to-Run more time to initialise.

---

## Phase 9 — EVM / DCMA / Briefing / Portfolio Sprint (2026-05-06)

### TD-042 — `test_flat_denial_retry_limit_still_works` is flaky in full-suite runs
**File:** `tests/test_interview_agent.py` — `TestFlatDenialRetryLimit`  
**Severity:** Low (test reliability; feature is correct)  
**Description:** This test passes reliably when run in isolation (`pytest tests/test_interview_agent.py -k flat_denial`) but sporadically fails when run in the full 611-test suite. Root cause is LLM mock state leaking between tests: another test that monkeypatches `agent.voice.interview_agent.LLMInterface` does not fully restore the original before this test runs, causing the `_classify_response` call to return a real API response instead of the patched one.  
**Why deferred:** The feature is correct; the test passes in isolation. Full-suite failures have zero impact on production correctness.  
**Suggested fix:** Add `autouse=True` fixture in `test_interview_agent.py` that wraps each test in a `monkeypatch` scope for `LLMInterface`, ensuring a clean mock state regardless of test order. Alternatively, use `pytest-randomly` with a fixed seed to identify the ordering that triggers the failure.

---

### TD-043 — Module-level `os.getenv()` constants break `monkeypatch.setenv()` isolation
**File:** `agent/executive_briefing.py`, `agent/portfolio.py`, `agent/variance_analyst.py`, `agent/dashboard/server.py` (partially resolved)  
**Severity:** Medium (test isolation; can cause subtle false-passes/failures in new tests)  
**Description:** Several modules read environment variables into module-level constants at import time (e.g., `_REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")`). When tests use `monkeypatch.setenv()` after import, the constant is already set. Three instances were fixed in Phase 9: `_save_briefing()` reads `REPORTS_DIR` at call time; `_portfolio_file()` helper reads `PORTFOLIO_FILE` at call time; `LLMInterface` import moved to module level in `variance_analyst.py`. The `server.py` `load_dotenv(override=True)` at module level also overrides test monkeypatching — tests must explicitly set `srv._STATE_FILE` after `importlib.reload()`.  
**Why deferred:** The three most impactful instances were resolved in Phase 9. Remaining cases are lower-risk or already handled by explicit post-reload overrides in test fixtures.  
**Suggested fix:** Audit all modules for `_CONST = os.getenv(...)` patterns. Replace with `_get_const()` helper functions or move all env reads into constructor/call bodies. Long-term: use a dependency injection pattern for config values so tests can supply them directly without env var manipulation.

---

## Phase 11 — Dashboard UI Test Suite (2026-05-07)

### TD-044 — Graph CAM Responder lookback window too short to catch messages from mid-cycle restart
**Resolved:** 2026-05-07  
**File:** `agent/graph_cam_responder.py` — `__init__`, `_last_check` initialization  
**Severity:** High (responder restart during active cycle caused complete interview stall)  
**Description:** `_last_check` was initialized to `datetime.now(timezone.utc) - timedelta(seconds=30)`. This 30-second lookback was designed to catch greetings sent immediately before the responder started. However, if the responder process was offline when a cycle started (e.g., manual restart, process crash, first-time startup), all greeting messages sent more than 30 seconds earlier were filtered as "too old." The responder would poll indefinitely without finding messages to reply to, stalling the interview phase until the cycle timeout.  
**Fix:** Changed lookback from 30 seconds to 2 hours (`timedelta(hours=2)`). A 2-hour window reliably catches any current-cycle greeting while not reaching back to the previous day's completed interviews (last cycle was 2+ days prior in testing). The seen-message-ID deduplication set prevents double-replies on subsequent polls.

---

### TD-045 — EAC date classifier (and other JSON classifiers) fail on LLM responses with trailing text — **RESOLVED**
**Resolved:** 2026-05-07  
**File:** `agent/voice/interview_agent.py` — `_classify_eac_date()` and `_classify_cam_response()`  
**Severity:** Medium → **High** (root cause of one confirmed test failure in addition to EAC date data loss)  
**Observed:** Production cycle `20260507T222726Z` — 10+ `eac_date_classify_failed` warnings. Also caused `test_after_correction_affirmative_closes` to fail: JSON parse failure in `_classify_cam_response` triggered the regex fallback, which classified "AI-07 should be risk-flagged, not AI-09" as `sentiment=unclear`, closing the interview prematurely instead of applying the correction.  
**Fix:** Applied the same `re.search(r'\{.*\}', raw, re.DOTALL)` extraction fallback that was already used in `_extract_and_apply_correction()` (lines 654–662) to both `_classify_cam_response()` and `_classify_eac_date()`. When `json.loads(raw)` raises `JSONDecodeError`, the code now extracts the first `{...}` block from the response string and retries — silently tolerating any trailing LLM explanation text. The outer `except Exception` regex fallback is only reached when no JSON object can be found at all.

---

### TD-046 — CAMSimulator eagerly constructs LLMInterface in __init__
**File:** `agent/voice/cam_simulator.py` — `CAMSimulator.__init__`  
**Severity:** Low (architectural smell; not causing CI failures when `ANTHROPIC_API_KEY` is present)  
**Description:** `CAMSimulator.__init__` calls `self._llm = LLMInterface(model=_SIM_MODEL)` immediately at construction time. `LLMInterface.__init__` raises `EnvironmentError` if neither `ANTHROPIC_API_KEY` nor `LLM_BASE_URL` is set. This means any test or offline environment that instantiates a `CAMSimulator` (even to test non-LLM methods) will fail unless credentials are available. The pattern is inconsistent with the rest of the codebase — all other callers create `LLMInterface` inside the method that needs it (`qa_engine.py`, `cycle_runner.py`, `variance_analyst.py`).  
**Why deferred:** Not blocking — CI has the API key. Affects only completely credential-free environments (local dev without `.env`, pure unit testing of simulator state, offline/ITAR deployments running only the simulator).  
**Suggested fix:** Move `LLMInterface` construction into `CAMSimulator.respond()`:
```python
def respond(self, conversation: list[dict], cam_question: str) -> str:
    if self._llm is None:
        from agent.llm_interface import LLMInterface
        self._llm = LLMInterface(model=_SIM_MODEL)
    ...
```
Set `self._llm = None` in `__init__`. No test changes required — lazy construction is transparent to callers.

---

### TD-047 — CI unit tests consistently fail because `ANTHROPIC_API_KEY` GitHub secret is not configured
**File:** `.github/workflows/ci.yml` — `env.ANTHROPIC_API_KEY`; `agent/voice/interview_agent.py` — `_classify_cam_response()`  
**Severity:** High (CI is permanently broken; every push produces a failing run)  
**Observed:** GitHub Actions job "Unit Tests (Python 3.13 · Windows)" fails across all recent commits (`ab0162b`, `3ebcf75`, `da87ecd`). Step "Run unit tests" completes in ~27 seconds — far shorter than the 6–7 minutes it takes when the Anthropic API is actually called. This timing mismatch is definitive proof no real LLM call is being made.

**Root cause chain:**
1. `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` in `ci.yml` evaluates to `""` (empty string) when the GitHub repository secret is not configured.
2. `LLMInterface.__init__` raises `EnvironmentError` for any falsy key value.
3. `_classify_cam_response()` (and `_classify_eac_date()`) wrap the entire LLM call in `except Exception`, catching `EnvironmentError` and falling through to the regex fallback.
4. The regex fallback correctly handles simple inputs ("yes", "no") but returns `sentiment="unclear"` for complex conversational inputs (e.g. "AI-07 should be risk-flagged, not AI-09").
5. `_handle_confirm` treats `"unclear"` the same as `"affirmative"` — closing the interview.
6. Tests that expect `InterviewState.CONFIRM` after a complex denial get `InterviewState.COMPLETE` → `AssertionError`.

**Why deferred:** Requires accessing GitHub repository settings (Settings → Secrets and variables → Actions) to add the secret, and a longer-term refactor to remove the live-API dependency from unit tests.

**Suggested fix (two-step):**
- **Immediate (unblocks CI):** Add `ANTHROPIC_API_KEY` as a GitHub Actions repository secret with a valid Anthropic API key. This alone will restore green CI.
- **Long-term (correct fix):** Refactor `TestConversationalContext` tests that rely on `_classify_cam_response` to mock the LLM response:
  ```python
  with patch("agent.voice.interview_agent._classify_cam_response",
             return_value={"sentiment": "negative", "percent": None, ...}):
      agent.process("AI-07 should be risk-flagged, not AI-09")
  ```
  Move any tests that *intentionally* exercise real LLM classification to `@pytest.mark.integration` so they are excluded from the CI unit-test run. This makes the suite fully deterministic and eliminates the API key dependency for `pytest tests/ -m "not integration"`.

---

### TD-048 — GitHub Actions CI uses deprecated Node.js 20 action versions (breaking June 2026)
**File:** `.github/workflows/ci.yml` — `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-java@v4`  
**Severity:** Medium (warning today; will hard-fail CI in September 2026)  
**Observed:** Every CI run includes the annotation: "Node.js 20 actions are deprecated. Actions will be forced to run with Node.js 24 by default starting June 2nd, 2026. Node.js 20 will be removed from the runner on September 16th, 2026."  
**Why deferred:** Currently only a warning; all three action versions (v4/v5) have Node.js 24 support available via the `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` env flag. Not urgent until June 2026.  
**Suggested fix:** Pin action versions that ship with Node.js 24 support, or add `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` to the workflow env block as an interim measure. Final fix: bump to the latest major versions once they are released with Node.js 24 as the default runtime.

---

## How to Use This Register

- When writing new code that cuts a corner, add an entry here in the same PR.
- When resolving a debt item, mark it **RESOLVED** with the PR number and date.
- Review this file at the start of each phase for items to prioritize in sprint 1.
- Severity guide: **High** = affects correctness / data integrity in production; **Medium** = affects reliability, cost, or maintainability; **Low** = polish / tech hygiene.
