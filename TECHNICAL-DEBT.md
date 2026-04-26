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

### TD-004 — `CONFIRM` state handler loops indefinitely on negative responses
**File:** `agent/voice/interview_agent.py:280` — `_handle_confirm`  
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

### TD-012 — IMS-AGENT-PROGRAM-PLAN.md lives outside the repo
**File:** `IMS-AGENT-PROGRAM-PLAN.md` (located in `..` relative to `ims-agent/`)  
**Severity:** Low  
**Description:** The authoritative program plan is one directory level above the Git repo root. The agent reads it at `../IMS-AGENT-PROGRAM-PLAN.md`. This means it's not version-controlled alongside the code, and a fresh clone of `ims-agent` would not include it.  
**Why deferred:** File placement was set in the initial project brief; not changed to avoid disrupting the user's reference location.  
**Suggested fix:** Copy into repo as `docs/program-plan.md` (or symlink). Keep the original in its reference location if needed, but ensure the committed version tracks changes via git.

---

## How to Use This Register

- When writing new code that cuts a corner, add an entry here in the same PR.
- When resolving a debt item, mark it **RESOLVED** with the PR number and date.
- Review this file at the start of each phase for items to prioritize in sprint 1.
- Severity guide: **High** = affects correctness / data integrity in production; **Medium** = affects reliability, cost, or maintainability; **Low** = polish / tech hygiene.
