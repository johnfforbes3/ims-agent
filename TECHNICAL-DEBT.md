# IMS Agent — Technical Debt Register

Track known shortcuts, workarounds, and deferred improvements by phase.
Each entry: what it is, why it was deferred, and a suggested fix.

---

## Phase 1

### TD-001 — Schedule health threshold is manual / LLM-generated
**File:** `agent/llm_interface.py`, `agent/report_generator.py`  
**Severity:** Medium  
**Description:** The RED/YELLOW/GREEN schedule health label is assigned by the LLM based on its interpretation of the narrative. There are no deterministic thresholds — e.g., "RED if any milestone is <50% on-time probability." This means the label can vary between runs on the same data and is not auditable.  
**Why deferred:** Phase 1 scope was proof-of-concept. FB-001 from PHASE1-FEEDBACK.md.  
**Suggested fix:** Define thresholds in a config or constants file (e.g., `HEALTH_THRESHOLDS = {"GREEN": 0.75, "YELLOW": 0.50}`). Compute health deterministically from SRA probabilities and critical path float, then pass the computed value into the LLM prompt as a given — don't ask the LLM to decide it. Add unit tests for each threshold transition.

---

### TD-002 — `can_call_now()` uses local machine time, not CAM's timezone
**File:** `agent/cam_directory.py:184`  
**Severity:** Medium  
**Description:** Business hours check compares `datetime.now().hour` (local machine time) to the CAM's `business_hours_start/end`. If the agent runs on a server in a different timezone than the CAM, the check is wrong. The code comment acknowledges this.  
**Why deferred:** `pytz` / `zoneinfo` dependency avoided for Phase 2 simplicity. CAMs all default to `America/New_York` which matches the likely dev/server environment for now.  
**Suggested fix:** Use Python 3.9+ `zoneinfo` (stdlib) to convert `datetime.now(timezone.utc)` into the CAM's IANA timezone before comparing hours. No extra dependency required.

---

### TD-003 — CAM call history is in-memory only (not persisted between runs)
**File:** `agent/cam_directory.py` — `_call_history` dict  
**Severity:** Medium  
**Description:** `_call_history` lives in the `CAMDirectory` object and is lost when the process exits. Retry logic (`should_retry`, `should_escalate`) is only effective within a single run. If the orchestrator restarts mid-cycle, history is lost.  
**Why deferred:** Phase 2 scope focused on the interview loop, not persistence.  
**Suggested fix:** Extend `save_to_file`/`load_from_file` to include call history. Add a `call_history` key to the JSON. Alternatively, use a lightweight SQLite store via stdlib `sqlite3`.

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

### TD-005 — `_extract_percent` only returns first numeric match
**File:** `agent/voice/interview_agent.py:419`  
**Severity:** Low  
**Description:** The regex `r"\b(\d{1,3})\s*%?"` returns the first numeric token it finds. Responses like "SE-04 is 100%, not 4%" would return 4 (from "4%") after 100, depending on which comes first. Observed in demo: agent extracted "4%" from "SE-04 is 100%" due to task ID digit appearing before the actual percent.  
**Why deferred:** Edge case; doesn't affect most clean responses.  
**Suggested fix:** Prefer the number immediately following common percent-context words ("is", "at", "about", "around", "approximately", "currently"). Alternatively, skip numeric tokens that appear to be part of task IDs (e.g., digits directly following "SE-", "HW-", "SW-").

---

### TD-006 — CAM simulator re-explains same blocker for every task that shares it — **RESOLVED**
**Resolved:** Phase 5 sprint 2 — 2026-04-27  
**File:** `agent/voice/cam_simulator.py` — `_build_context`  
**Description:** `_build_context()` now passes the full conversation history (was last 6 turns / 3 exchanges) so all prior blocker explanations remain visible to Claude throughout the interview. An explicit instruction is appended: "if you have already explained a blocker or root cause earlier in this conversation, do not re-explain it in full — reference it briefly and move on." Together these eliminate the repeated full-blocker re-explanation when multiple tasks share the same root cause.

---

### TD-007 — Report blocker text is untruncated in table
**File:** `agent/report_generator.py` — `_build_tasks_behind_section`  
**Severity:** Low  
**Description:** Blocker text in the "Tasks Behind Schedule" table is the full raw CAM response — sometimes multiple paragraphs. This breaks table formatting and is hard to read.  
**Why deferred:** Phase 2 output focus. FB-2-005.  
**Suggested fix:** Truncate to first sentence or 120 characters in the table cell, with a `*` footnote. Render full blocker text in an appendix section at the end of the report.

---

### TD-008 — `_nearest_milestone_name()` always returns a generic string — **RESOLVED**
**Resolved:** Phase 5 sprint 2 — 2026-04-27  
**File:** `agent/interview_orchestrator.py`, `agent/voice/interview_agent.py`  
**Description:** `_nearest_milestone_name()` was already implemented correctly in `InterviewAgent` (filters `self._milestones` by `finish >= now`, returns shortened milestone name). The gap was that `InterviewOrchestrator._interview_one()` constructed `InterviewAgent(cam_name, cam_tasks)` without passing `all_tasks`, so `self._milestones` was always empty and the fallback "the next milestone" was always returned. Fixed by storing `tasks` as `self._all_tasks` at the start of `InterviewOrchestrator.run()` and passing `all_tasks=self._all_tasks` to every `InterviewAgent` constructor call.

---

### TD-009 — No rate limiting on CAM simulator API calls
**File:** `agent/voice/cam_simulator.py` — `respond()`  
**Severity:** Medium (cost risk)  
**Description:** Each CAM turn calls the Anthropic API synchronously with no throttling. A 5-CAM × 10-task interview cycle with blockers/risk descriptions generates ~80-120 API calls. At scale (20+ CAMs), this could be expensive and could hit API rate limits mid-cycle.  
**Why deferred:** Not a concern at Phase 2 demo scale.  
**Suggested fix:** Add configurable inter-call sleep (`SIMULATOR_CALL_DELAY_MS` env var, default 200ms). For production, batch non-dependent tasks using async calls. Consider caching persona context as a system prompt with the Anthropic API's prompt caching feature to reduce token costs.

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

### TD-013 — Dashboard state file write is not atomic
**File:** `agent/cycle_runner.py` — `_update_dashboard_state`, `_write_phase`  
**Severity:** Medium  
**Description:** `state_path.write_text(...)` and `history_path.write_text(...)` write JSON directly to the target file. If the process is killed (SIGKILL, power loss, OOM) mid-write, the file is left truncated or with invalid JSON. The dashboard will 500 on the next request until the file is manually repaired or a new cycle overwrites it.  
**Why deferred:** Acceptable risk for single-machine dev deployment; not a data-loss risk since the authoritative record is the IMS XML and cycle status JSONs in `reports/cycles/`.  
**Suggested fix:** Write to a temp file in the same directory, then `os.replace(tmp, target)`. `os.replace` is atomic on POSIX and atomic on Windows when src/dst are on the same volume. One-line change per write site.

---

### TD-014 — Notifier env vars loaded at module import time
**File:** `agent/notifier.py` — module-level globals `_SLACK_WEBHOOK`, `_EMAIL_HOST`, etc.  
**Severity:** Low  
**Description:** All notifier config (webhook URL, SMTP credentials, dashboard URL) is read from `os.getenv` at module import time. If `.env` is edited while the scheduler is running (e.g., to rotate a credential), the change does not take effect until the process restarts. Same issue applies to any other module that reads env vars at import scope.  
**Why deferred:** Uncommon in practice; credential rotation requires a restart in most service architectures anyway.  
**Suggested fix:** Move `load_dotenv(override=True)` and the `os.getenv` calls into `send_slack()` and `send_email()` function bodies, or into a `_get_config()` helper called at send time. This adds ~1ms of overhead per send but ensures the latest `.env` is always used.

---

### TD-015 — Validation holds not surfaced on the live dashboard
**File:** `agent/cycle_runner.py` — `_update_dashboard_state`, `agent/dashboard/templates/index.html`  
**Severity:** Low  
**Description:** When the validation layer logs holds (e.g., backwards movement, large jump), the count and detail are persisted to `reports/cycles/{cycle_id}_status.json` but are not included in `dashboard_state.json`. The dashboard has no indicator that the current cycle's data contains flagged anomalies; a planner must manually open the status JSON to see them.  
**Why deferred:** Phase 3 scope: validation holds log but do not block. Dashboard MVP did not include a holds panel.  
**Suggested fix:** Add `"validation_holds": status.get("validation_holds", [])` to the dashboard state dict in `_update_dashboard_state`. Add a collapsible "Validation Alerts" section to `index.html` that renders each hold as a warning card when the list is non-empty.

---

## Phase 4

### TD-016 — Q&A context builder loads full state on every query; no caching
**File:** `agent/qa/context_builder.py` — `load_state()`, `load_history()`  
**Severity:** Low  
**Description:** Every call to `build_context()` reads and JSON-parses `dashboard_state.json` and `cycle_history.json` from disk. At current scale (~50 KB combined) this is negligible. At production scale with many concurrent Slack/dashboard queries this adds unnecessary I/O per request.  
**Why deferred:** No observable performance issue at MVP scale.  
**Suggested fix:** Cache state in a module-level variable with a TTL (e.g., 30s). Invalidate cache when `_STATE_FILE` modification time changes. One decorator or `functools.lru_cache` variant with a time key.

---

### TD-017 — No authentication on /api/ask or dashboard — **RESOLVED**
**Resolved:** Phase 5 — 2026-04-26  
**File:** `agent/dashboard/server.py`  
**Description:** All `/api/*` routes now require `X-API-Key` (read) or `X-Admin-Key` (admin). Two-key RBAC model implemented: `DASHBOARD_API_KEY` grants access to read routes; `DASHBOARD_ADMIN_KEY` gates `POST /api/trigger` and `POST /api/admin/purge`. Per-IP rate limiting added to `POST /api/ask` via `QA_RATE_LIMIT_PER_HOUR`. Dashboard HTML at `/` still unprotected by API key (browsers don't send custom headers on page loads) — production deployments should put it behind a reverse proxy with TLS and auth (TD tracked in SECURITY.md §Dashboard HTML).

---

### TD-018 — Slack slash command sends "Thinking…" then overwrites it, creating a jarring UX
**File:** `agent/slack_command.py` — `_handle_ims_command`  
**Severity:** Low  
**Description:** Because Slack requires acknowledgement within 3 seconds and LLM calls take 5-15 seconds, the handler acks with `respond(text="Thinking…")` then calls `respond(blocks=...)` with the real answer. This creates two separate messages in the channel rather than updating the first in-place.  
**Why deferred:** Requires switching to `client.chat_update` with a message timestamp, which needs the channel ID from the command payload and an additional Slack API call.  
**Suggested fix:** Use `command["channel_id"]` + `app.client.chat_postMessage` to get a message `ts`, then `app.client.chat_update` with the answer. Alternatively, use Slack's `response_url` with `replace_original: true`.

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

### TD-021 — Dashboard countdown resets to 5 during active cycle instead of counting down — **REOPENED**
**Previously marked resolved:** Phase 5 sprint 2 — 2026-04-27  
**Reopened:** 2026-04-27 — fix was incomplete; countdown still bounces 5→0→5→0 during active cycles; "Cycle In Progress" card not updating live.  


**File:** `agent/dashboard/templates/index.html` — `pollStatus()`, countdown `setInterval`  
**Severity:** Medium  
**Description:** The dashboard has two independent timers: a 60-second full-page reload countdown and a one-shot `pollStatus()` call that triggers `window.location.reload()` after 5 seconds if a cycle is active. When a cycle is running, the page reloads every 5 seconds but the countdown still initialises at 60 and counts down from there — giving the impression of a stuck or restarting timer rather than the actual 5-second refresh cadence. More critically, the "Cycle In Progress" card (showing phase / CAMs responded) only updates on full reload; there is no live push or incremental AJAX update, so progress is only visible in arrears.  
**Why deferred:** The template uses server-side Jinja2 rendering; live updates require either SSE/WebSocket or an AJAX polling loop to fetch `/api/state` and patch the DOM without a full reload.  
**Suggested fix:**  
1. Replace `pollStatus()` + `window.location.reload()` with a `setInterval` (every 5s when active, every 60s when idle) that fetches `/api/state` via AJAX and updates only the "Cycle In Progress" card and the countdown badge in-place.  
2. Reset `seconds` to match the current interval (5 or 60) whenever the interval changes, so the badge accurately reflects the next actual refresh.  
3. Trigger a full page reload only when the cycle transitions from active → complete (i.e., `cycle_active` flips from `true` to `false`), so the final health/report data is loaded cleanly.

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

## How to Use This Register

- When writing new code that cuts a corner, add an entry here in the same PR.
- When resolving a debt item, mark it **RESOLVED** with the PR number and date.
- Review this file at the start of each phase for items to prioritize in sprint 1.
- Severity guide: **High** = affects correctness / data integrity in production; **Medium** = affects reliability, cost, or maintainability; **Low** = polish / tech hygiene.
