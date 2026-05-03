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

### TD-010 — WhisperSTTEngine never tested with real audio
**File:** `agent/voice/stt_engine.py`  
**Severity:** Medium  
**Description:** `WhisperSTTEngine` is unit-tested at the mock level only. The real Whisper transcription path (model loading, actual audio file transcription, log-probability confidence scoring) has never been exercised in the test suite. The whisper package is also not in `requirements.txt` (commented as optional).  
**Why deferred:** Phase 2 uses `MockSTTEngine` exclusively in simulation mode.  
**Suggested fix:** Add an integration test marked `@pytest.mark.integration` that skips when `openai-whisper` is not installed. Test with a short WAV file containing a known phrase and assert transcription contains expected keywords. Add `openai-whisper` and `sounddevice` to `requirements-optional.txt`.

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
**Status:** IN PROGRESS — 2026-04-28. `cam_identity_map.json` updated: Eva now has `email: eva@intelligenceexpanse.onmicrosoft.com`, `auto_respond: true`, `responder_type: graph`. M365 account creation + first-contact bootstrap still pending (see TODAY_ACTIONS.txt Action 5).  
**Description:** Eva Johnson is registered as a CAM in `cam_identity_map.json` and appears in the CAM Response Status panel on the dashboard, but has no entry in `cam_sessions.json`. In `teams_chat` mode she falls back to the CAM simulator. Resolution requires: (1) create eva@intelligenceexpanse.onmicrosoft.com in M365 Admin, (2) run cam-responder for Eva and complete device-code auth, (3) bootstrap first 1:1 Teams contact with the bot.  
**Remaining fix:** See TODAY_ACTIONS.txt Action 5 for step-by-step instructions.

---

### TD-023 — Bootstrap first-contact required before Teams chat mode works for new CAMs
**File:** `data/cam_sessions.json`, `agent/voice/teams_chat_connector.py`  
**Severity:** Medium  
**Description:** `cam_sessions.json` must be seeded with real Teams chat IDs before `CycleRunner(mode="teams_chat")` can open conversations. These IDs are obtained from prior reactive contact (CAM messages the bot first) or extracted manually from responder logs. New CAMs added to the identity map cannot participate in Teams chat cycles until they have messaged the bot at least once.  
**Why deferred:** Acceptable for the current 4-CAM demo setup; all 4 sessions bootstrapped from responder logs.  
**Suggested fix:** Add a `--bootstrap-sessions` CLI flag that sends each CAM a "please message me back" notification via Graph API email, then polls for their first bot message and saves the resulting `conversation_id` to `cam_sessions.json` automatically.

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

## How to Use This Register

- When writing new code that cuts a corner, add an entry here in the same PR.
- When resolving a debt item, mark it **RESOLVED** with the PR number and date.
- Review this file at the start of each phase for items to prioritize in sprint 1.
- Severity guide: **High** = affects correctness / data integrity in production; **Medium** = affects reliability, cost, or maintainability; **Low** = polish / tech hygiene.
