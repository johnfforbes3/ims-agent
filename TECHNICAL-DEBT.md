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

### TD-006 — CAM simulator re-explains same blocker for every task that shares it
**File:** `agent/voice/cam_simulator.py` — `_build_context`  
**Severity:** Medium  
**Description:** Each task is asked independently. When multiple tasks share the same root blocker (e.g., Alice's SE-02, SE-03, SE-05, SE-06, SE-08 all blocked by missing RF specs), the simulator re-explains the full blocker each time because it has no memory of "I already told the agent this." This causes: (a) very long interviews, (b) the CAM persona becoming increasingly impatient at being asked the same thing repeatedly, (c) verbosity noise in the report's blocker table.  
**Why deferred:** Phase 2 simulator is intentionally stateless per task for simplicity. FB-2-004.  
**Suggested fix:** Pass the previously-captured blocker list into the simulator context: "You have already explained the following blockers in this call: [list]. For tasks with the same root cause, reference your earlier answer briefly rather than re-explaining in full."

---

### TD-007 — Report blocker text is untruncated in table
**File:** `agent/report_generator.py` — `_build_tasks_behind_section`  
**Severity:** Low  
**Description:** Blocker text in the "Tasks Behind Schedule" table is the full raw CAM response — sometimes multiple paragraphs. This breaks table formatting and is hard to read.  
**Why deferred:** Phase 2 output focus. FB-2-005.  
**Suggested fix:** Truncate to first sentence or 120 characters in the table cell, with a `*` footnote. Render full blocker text in an appendix section at the end of the report.

---

### TD-008 — `_nearest_milestone_name()` always returns a generic string
**File:** `agent/voice/interview_agent.py:398`  
**Severity:** Low  
**Description:** The risk flag prompt says "Is this something that could affect the **next program milestone** milestone?" — the word "milestone" is doubled (minor), and the function always returns the literal string "next program milestone" rather than finding the actual next upcoming milestone by date (e.g., "PDR on 2026-05-29").  
**Why deferred:** Required access to the full task list from within the InterviewAgent, which was a minor scope expansion.  
**Suggested fix:** Pass the full task list to `InterviewAgent.__init__`. Filter for `is_milestone=True`, sort by `finish` date, and return the name of the first milestone whose `finish` date is after today. Fall back to "next program milestone" if none found.

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

### TD-013 — Chat bot is reactive only; cannot initiate conversations proactively
**File:** `agent/voice/teams_chat_connector.py`, `agent/demo_chat.py`  
**Severity:** High  
**Description:** `ChatInterviewManager` only activates when a CAM sends the first message. The bot cannot open a conversation proactively. This means the trigger-cycle button cannot autonomously start chat interviews — it still uses `CAMSimulator`. Proactive messaging requires a stored `serviceUrl` + `conversationId` per CAM (only available after at least one prior conversation) and a `POST {serviceUrl}/v3/conversations` call with the bot/user member objects.  
**Why deferred:** Bot Framework proactive messaging requires first-contact data that only exists after a CAM has previously messaged the bot. Bootstrapping for new users needs a separate channel (e.g., a welcome message sent via Graph or a manual first-contact flow).  
**Suggested fix:**
1. Store `serviceUrl` + `conversationId` + `user.id` in a JSON file per CAM after their first chat contact
2. Add `ChatInterviewManager.proactive_start(cam_email, service_url, conversation_id)` that calls `POST {serviceUrl}/v3/conversations` and returns the new conversation ID
3. Modify `CycleRunner` to accept `mode="teams_chat"`, pre-register all CAM sessions, call `proactive_start()` for each, then block on `session.done` events in parallel before proceeding to analysis

---

### TD-014 — ngrok URL must be manually updated in Azure Bot Service on each restart
**File:** `.env`, Azure Bot Service configuration  
**Severity:** Medium  
**Description:** The free ngrok plan generates a new URL on every `ngrok http 9000` invocation. The Azure Bot Service messaging endpoint must be manually updated each time. This is acceptable for demos but breaks unattended production runs.  
**Why deferred:** ngrok paid plan ($10/month) supports static subdomains (`--subdomain`). Alternatively, a production deployment would use a fixed domain with a real TLS cert and no need for ngrok.  
**Suggested fix:** Either upgrade to ngrok paid plan and set `NGROK_SUBDOMAIN` in `.env`, or deploy to a VM/container with a fixed FQDN and eliminate ngrok entirely.

---

## How to Use This Register

- When writing new code that cuts a corner, add an entry here in the same PR.
- When resolving a debt item, mark it **RESOLVED** with the PR number and date.
- Review this file at the start of each phase for items to prioritize in sprint 1.
- Severity guide: **High** = affects correctness / data integrity in production; **Medium** = affects reliability, cost, or maintainability; **Low** = polish / tech hygiene.
