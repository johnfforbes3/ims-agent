# IMS Agent — Master Test Procedure

**Document type:** Static test procedure (never modify this section; append run records to RUN HISTORY at the end)  
**Version:** 1.0  
**Created:** 2026-04-26  
**Coverage:** All features, all API endpoints, all UI elements, all CLI modes, all configuration paths  
**Total test cases:** 228  

---

## HOW TO USE THIS DOCUMENT

1. **Tester (human or AI):** Work through each section in order. For each TC, follow the steps exactly and record PASS, FAIL, or SKIP.
2. **Recording results:** Copy the RUN TEMPLATE at the end of this document, fill in every row, and append it as a new `## RUN N` section below the last run entry.
3. **SKIP:** Mark a TC SKIP only if the prerequisite cannot be met (e.g., a Slack token is not available). Always note the reason.
4. **FAIL:** Record the exact error message or observed vs. expected behavior in the Notes column.
5. **The test procedure itself (everything above RUN HISTORY) is never edited.** Only the RUN HISTORY section grows.

### Result Codes
| Code | Meaning |
|------|---------|
| PASS | Step executed; observed behavior exactly matches pass criteria |
| FAIL | Step executed; observed behavior does not match pass criteria — details in Notes |
| SKIP | TC not executed — prerequisite unavailable or explicitly out of scope for this run |

---

## TEST ENVIRONMENT REQUIREMENTS

### Required for all tests
- Python ≥ 3.11 installed
- Virtual environment activated (`.venv/Scripts/activate`)
- `pip install -r requirements.txt` complete
- `.env` file present with at minimum `ANTHROPIC_API_KEY` set
- `data/sample_ims.xml` present
- `reports/` and `logs/` directories writable

### Required for dashboard/API tests (Sections 4–7)
- Dashboard server running on port 8080 (`python main.py --serve`)
- Browser or `curl`/`httpie` available

### Required for auth tests (Section 7)
- `DASHBOARD_API_KEY` set to a known value (e.g., `test-read-key`)
- `DASHBOARD_ADMIN_KEY` set to a different known value (e.g., `test-admin-key`)

### Required for Docker tests (Section 14)
- Docker Desktop installed and running
- `docker` and `docker compose` CLI available

### Optional (mark SKIP if unavailable)
- Slack bot token + app token → Slack tests (Section 12)
- SMTP credentials → Email tests (Section 12)
- ElevenLabs API key → Voice briefing tests (Section 13)

---

## SECTION 1 — ENVIRONMENT & SETUP (TC-001 to TC-010)

### TC-001 — Python version and virtual environment
**Steps:**
1. Run `.venv/Scripts/python.exe --version`
2. Verify output is `Python 3.11.x` or higher

**Pass Criteria:** Python 3.11 or higher reported  
**Fail Criteria:** Python < 3.11 or command not found

---

### TC-002 — All dependencies installed
**Steps:**
1. Run `.venv/Scripts/pip.exe list`
2. Confirm the following packages are present: `anthropic`, `fastapi`, `uvicorn`, `apscheduler`, `python-dotenv`, `pydantic`, `jinja2`, `httpx`, `pytest`

**Pass Criteria:** All listed packages appear in output  
**Fail Criteria:** Any package missing

---

### TC-003 — Sample IMS file present and parseable
**Steps:**
1. Run `.venv/Scripts/python.exe -c "from agent.file_handler import IMSFileHandler; t = IMSFileHandler('data/sample_ims.xml').parse(); print(f'{len(t)} tasks loaded')"`
2. Observe output

**Pass Criteria:** Output is `57 tasks loaded` (or close — at least 50)  
**Fail Criteria:** Exception, FileNotFoundError, or 0 tasks

---

### TC-004 — Environment variables load correctly
**Steps:**
1. Run `.venv/Scripts/python.exe -c "from dotenv import load_dotenv; import os; load_dotenv(); print('KEY_SET' if os.getenv('ANTHROPIC_API_KEY') else 'MISSING')"`

**Pass Criteria:** Output is `KEY_SET`  
**Fail Criteria:** Output is `MISSING`

---

### TC-005 — Full test suite passes
**Steps:**
1. Run `.venv/Scripts/python.exe -m pytest tests/ -q`
2. Wait for completion

**Pass Criteria:** All tests pass; output ends with `N passed` and no failures  
**Fail Criteria:** Any test fails or errors before completing

---

### TC-006 — Logs directory created automatically
**Steps:**
1. Delete `logs/` directory if it exists (`rmdir /s logs`)
2. Run `python main.py --trigger`
3. Check whether `logs/` directory was created

**Pass Criteria:** `logs/` directory exists after run  
**Fail Criteria:** `logs/` not created; log-related error in output

---

### TC-007 — Reports directory created automatically
**Steps:**
1. Delete `reports/` directory if it exists (back up first if it has content you need)
2. Run `python main.py --trigger`
3. Check whether `reports/` directory was created with at least one `.md` file

**Pass Criteria:** `reports/*.md` file exists after run  
**Fail Criteria:** `reports/` not created or no report file generated

---

### TC-008 — Data directory and snapshot created
**Steps:**
1. Run `python main.py --trigger`
2. Check `data/snapshots/` for a new XML file named `{cycle_id}_sample_ims.xml`

**Pass Criteria:** Snapshot XML file exists in `data/snapshots/`  
**Fail Criteria:** No snapshot created; error in output

---

### TC-009 — Dashboard state file written after cycle
**Steps:**
1. Run `python main.py --trigger`
2. Run `.venv/Scripts/python.exe -c "import json; s=json.load(open('data/dashboard_state.json')); print(s['schedule_health'])"`

**Pass Criteria:** Output is `GREEN`, `YELLOW`, or `RED`  
**Fail Criteria:** FileNotFoundError, KeyError, or invalid JSON

---

### TC-010 — Cycle history file written and contains at least one entry
**Steps:**
1. Run `python main.py --trigger`
2. Run `.venv/Scripts/python.exe -c "import json; h=json.load(open('data/cycle_history.json')); print(len(h), 'entries')"`

**Pass Criteria:** Output is `N entries` with N ≥ 1  
**Fail Criteria:** FileNotFoundError or 0 entries

---

## SECTION 2 — CLI MODES (TC-011 to TC-030)

### TC-011 — `--trigger` mode: completes and exits
**Steps:**
1. Run `python main.py --trigger`
2. Observe stdout output and exit code

**Pass Criteria:** Process completes and exits; stdout shows `schedule_health`; exit code 0  
**Fail Criteria:** Process hangs, crashes, or exits with non-zero code

---

### TC-012 — `--trigger` mode: prints report path to stdout
**Steps:**
1. Run `python main.py --trigger 2>&1`
2. Search output for `report_path` or a path ending in `.md`

**Pass Criteria:** A report path appears in stdout  
**Fail Criteria:** No report path shown; cycle phase = `failed`

---

### TC-013 — `--trigger` mode with custom IMS file path
**Steps:**
1. Copy `data/sample_ims.xml` to `data/copy_ims.xml`
2. Run `python main.py --trigger --ims-file data/copy_ims.xml`
3. Verify a new report is generated

**Pass Criteria:** Cycle completes; report generated; no "file not found" errors  
**Fail Criteria:** Error about IMS file path; cycle fails

---

### TC-014 — `--trigger` with nonexistent IMS file
**Steps:**
1. Run `python main.py --trigger --ims-file data/nonexistent_xyz.xml`
2. Observe output

**Pass Criteria:** Cycle fails gracefully; stderr/stdout shows error about missing file; exit code 1  
**Fail Criteria:** Unhandled exception / traceback not related to missing file

---

### TC-015 — `--serve` mode: server starts and accepts connections
**Steps:**
1. Run `python main.py --serve` in background (or separate terminal)
2. Wait 3 seconds
3. Run `curl http://localhost:8080/health` or open in browser

**Pass Criteria:** HTTP 200 response with `{"status": "healthy", ...}` body  
**Fail Criteria:** Connection refused; server crashes on start; wrong response

---

### TC-016 — `--serve` mode: dashboard HTML loads at root
**Steps:**
1. Server running from TC-015
2. Open browser to `http://localhost:8080/`

**Pass Criteria:** IMS Agent dashboard HTML page renders; title visible; no 500 error  
**Fail Criteria:** HTTP error code; blank page; Python traceback in response

---

### TC-017 — `--schedule` mode: starts and shows next run time
**Steps:**
1. Run `python main.py --schedule` in background
2. Check log output or stdout for "next_run_time" or similar message
3. Send Ctrl+C after 5 seconds; verify clean shutdown

**Pass Criteria:** Server starts; log shows next scheduled run; clean shutdown on Ctrl+C  
**Fail Criteria:** Server crashes; no schedule message; cannot be stopped

---

### TC-018 — Default mode (no flags): runs Phase 1 pipeline and exits
**Steps:**
1. Run `python main.py` (no arguments)
2. Observe output; wait for completion

**Pass Criteria:** Process runs the full Phase 1 pipeline; prints synthesis output or report path; exits  
**Fail Criteria:** Server starts (wrong mode); hangs indefinitely; unhandled exception

---

### TC-019 — Log output in text format (default)
**Steps:**
1. Ensure `LOG_FORMAT=text` in `.env` (or not set)
2. Run `python main.py --trigger`
3. Open `logs/ims_agent.log` or read stderr

**Pass Criteria:** Log lines are human-readable (e.g., `2026-04-26 INFO agent.cycle_runner action=cycle_complete`)  
**Fail Criteria:** JSON objects logged instead of human-readable text; no log output

---

### TC-020 — Log output in JSON format
**Steps:**
1. Set `LOG_FORMAT=json` in `.env`
2. Run `python main.py --trigger`
3. Open `logs/ims_agent.log`; verify each line is valid JSON

**Pass Criteria:** Each log line is a valid JSON object with keys `ts`, `level`, `logger`, `msg`  
**Fail Criteria:** Non-JSON content in log; `json.loads()` raises exception on a log line

---

### TC-021 — LOG_LEVEL=DEBUG produces verbose output
**Steps:**
1. Set `LOG_LEVEL=DEBUG` in `.env`
2. Run `python main.py --trigger`
3. Check log for DEBUG-level entries

**Pass Criteria:** Log contains lines at `DEBUG` level; significantly more output than INFO mode  
**Fail Criteria:** No DEBUG lines in output

---

### TC-022 — LOG_LEVEL=WARNING suppresses INFO messages
**Steps:**
1. Set `LOG_LEVEL=WARNING` in `.env`
2. Run `python main.py --trigger`
3. Check log for INFO-level entries

**Pass Criteria:** No `INFO` lines in log; only `WARNING` and `ERROR` lines present  
**Fail Criteria:** INFO lines present in log output

---

### TC-023 — Cycle lock prevents duplicate concurrent cycles
**Steps:**
1. Start `python main.py --serve`
2. Send two `POST /api/trigger` requests in rapid succession (within 1 second)
3. Observe responses

**Pass Criteria:** First trigger returns 200; second returns 409 `{"detail": "A cycle is already running"}`  
**Fail Criteria:** Both succeed; both fail; incorrect HTTP status code

---

### TC-024 — `--trigger` duplicate prevention
**Steps:**
1. Launch two concurrent processes: `python main.py --trigger` and `python main.py --trigger`
2. Observe both outputs

**Pass Criteria:** One cycle completes successfully; the other fails with "already running" message  
**Fail Criteria:** Both complete (data corruption risk); both fail

---

### TC-025 — Cycle ID format is UTC timestamp
**Steps:**
1. Run `python main.py --trigger`
2. Check `data/dashboard_state.json` for `cycle_id` field

**Pass Criteria:** `cycle_id` matches pattern `\d{8}T\d{6}Z` (e.g., `20260426T060000Z`)  
**Fail Criteria:** `cycle_id` is missing, null, or in wrong format

---

## SECTION 3 — CYCLE RUNNER PHASES (TC-026 to TC-045)

### TC-026 — All 7 phases appear in cycle status file
**Steps:**
1. Run `python main.py --trigger`
2. Find the status file: `reports/cycles/{cycle_id}_status.json`
3. Check `phase` field

**Pass Criteria:** Final `phase` is `complete`; check that earlier phases (initiated, interviewing, validating, updating, analyzing, distributing) were logged (check logs for `action=phase_write`)  
**Fail Criteria:** Phase is `failed` or missing; not all phases reached

---

### TC-027 — Cycle status JSON has all required fields
**Steps:**
1. Open `reports/cycles/{cycle_id}_status.json` after a completed cycle

**Pass Criteria:** JSON contains all of: `cycle_id`, `phase`, `started_at`, `completed_at`, `cams_total`, `cams_responded`, `tasks_captured`, `report_path`, `schedule_health`  
**Fail Criteria:** Any field missing or null (except `error` which should be empty)

---

### TC-028 — CAM counts are correct
**Steps:**
1. Check `cams_total` and `cams_responded` in the cycle status JSON
2. Cross-reference with ATLAS sample IMS (5 CAMs)

**Pass Criteria:** `cams_total` = 5; `cams_responded` = 5 (simulated mode has 100% response rate)  
**Fail Criteria:** Values are 0 or null; `cams_responded` > `cams_total`

---

### TC-029 — IMS file is snapshotted before updates
**Steps:**
1. Note the cycle_id from a fresh trigger
2. Check `data/snapshots/{cycle_id}_sample_ims.xml` exists
3. Verify it is a valid XML file (non-empty)

**Pass Criteria:** Snapshot file exists; is valid XML; size > 0  
**Fail Criteria:** No snapshot; empty file; invalid XML

---

### TC-030 — IMS file is updated with CAM inputs
**Steps:**
1. Note the `percent_complete` of task ID 1 in `data/sample_ims.xml` before trigger
2. Run `python main.py --trigger`
3. Re-read the same task from the IMS file

**Pass Criteria:** At least some tasks show updated `percent_complete` values after the cycle (simulated CAMs report progress)  
**Fail Criteria:** No changes to IMS file; exception during update phase

---

### TC-031 — Critical path is calculated
**Steps:**
1. Run `python main.py --trigger`
2. Check `data/dashboard_state.json` for `critical_path_task_ids`

**Pass Criteria:** `critical_path_task_ids` is a non-empty list of task ID strings  
**Fail Criteria:** Field is empty list or null; CPM phase fails

---

### TC-032 — SRA milestones are generated
**Steps:**
1. Run `python main.py --trigger`
2. Check `data/dashboard_state.json` for `milestones` array

**Pass Criteria:** `milestones` contains 7 entries (one per ATLAS milestone); each has `p50_date`, `p80_date`, `p95_date`, `prob_on_baseline`, `risk_level`  
**Fail Criteria:** Empty array; missing fields; fewer than 7 milestones

---

### TC-033 — LLM synthesis produces schedule health
**Steps:**
1. Run `python main.py --trigger`
2. Check `data/dashboard_state.json` for `schedule_health`

**Pass Criteria:** `schedule_health` is exactly `GREEN`, `YELLOW`, or `RED`  
**Fail Criteria:** Field is empty string, `UNKNOWN`, or null

---

### TC-034 — LLM synthesis produces narrative
**Steps:**
1. Check `data/dashboard_state.json` for `narrative` field after a trigger

**Pass Criteria:** `narrative` is a non-empty string containing multiple sentences  
**Fail Criteria:** Field is empty; contains only a heading; is the raw prompt

---

### TC-035 — LLM synthesis produces top_risks
**Steps:**
1. Check `data/dashboard_state.json` for `top_risks` field

**Pass Criteria:** `top_risks` is a non-empty string with at least one numbered or bulleted item  
**Fail Criteria:** Field is empty; is a generic placeholder

---

### TC-036 — LLM synthesis produces recommended_actions
**Steps:**
1. Check `data/dashboard_state.json` for `recommended_actions` field

**Pass Criteria:** `recommended_actions` is a non-empty string with at least one action item  
**Fail Criteria:** Field is empty; is a generic placeholder

---

### TC-037 — Report file is created with correct naming
**Steps:**
1. Run `python main.py --trigger`
2. List files in `reports/`

**Pass Criteria:** File named `YYYY-MM-DD_ims_report.md` exists; date matches today  
**Fail Criteria:** No file; wrong name format; wrong date

---

### TC-038 — Report contains all major sections
**Steps:**
1. Open the generated `.md` report file
2. Search for section headings

**Pass Criteria:** Report contains headings: `# IMS Status Report`, `Executive Summary`, `Critical Path`, `Schedule Risk Analysis`, `CAM Status`, `Top Risks`, `Recommended Actions`  
**Fail Criteria:** Any required section missing

---

### TC-039 — Metrics incremented after successful cycle
**Steps:**
1. Start dashboard server
2. Note current `cycles_completed` from `GET /metrics`
3. Trigger a cycle via `POST /api/trigger`
4. Wait for completion; re-check `GET /metrics`

**Pass Criteria:** `cycles_completed` increased by exactly 1; `last_cycle_id` updated  
**Fail Criteria:** Counter not incremented; counter incremented more than once

---

### TC-040 — Metrics increment on failure
**Steps:**
1. Note `cycles_failed` from `GET /metrics`
2. Trigger a cycle with a bad IMS path (e.g., via direct code edit or temp rename of `data/sample_ims.xml`)
3. Re-check `GET /metrics`

**Pass Criteria:** `cycles_failed` increased by 1; `cycles_completed` unchanged  
**Fail Criteria:** Wrong counter incremented; no increment on failure

---

### TC-041 — Cycle history capped at 52 entries (rolling)
**Steps:**
1. Inspect `data/cycle_history.json`; note current entry count
2. If < 52 entries, run several triggers; verify the file grows
3. If ≥ 52 entries, run one more trigger; verify length stays at 52

**Pass Criteria:** History file never exceeds 52 entries; oldest entry dropped when full  
**Fail Criteria:** History grows unbounded past 52

---

### TC-042 — Validation holds are logged but do not block cycle
**Steps:**
1. Ensure at least one CAM response exists in the previous state (triggers `backwards_movement` or `large_jump` check)
2. Run `python main.py --trigger`
3. Check cycle status JSON for `validation_holds`; check that cycle phase = `complete`

**Pass Criteria:** Cycle completes with phase = `complete`; `validation_holds` may be non-empty but is an array (not null)  
**Fail Criteria:** Cycle blocked by validation; phase = `failed` due to validation

---

### TC-043 — Purge runs after every cycle
**Steps:**
1. Set `DATA_RETENTION_DAYS=0` in `.env` (purge everything)
2. Create a dummy old status file in `reports/cycles/`
3. Run `python main.py --trigger`
4. Verify the old file was deleted

**Pass Criteria:** Old dummy file deleted; new status file (from this cycle) remains  
**Fail Criteria:** Old file not deleted; purge error halts cycle

---

### TC-044 — Failed cycle still saves status file
**Steps:**
1. Rename `data/sample_ims.xml` to force failure
2. Run `python main.py --trigger`
3. Check `reports/cycles/` for a new `*_status.json` with `phase: failed`
4. Restore the renamed file

**Pass Criteria:** Status file created with `phase: failed` and non-empty `error` field  
**Fail Criteria:** No status file on failure; status file has wrong phase

---

### TC-045 — `last_cycle_duration_seconds` is reasonable
**Steps:**
1. Run `python main.py --trigger`
2. Check `GET /metrics` for `last_cycle_duration_seconds`

**Pass Criteria:** Value is a positive integer between 5 and 600 (5s–10min)  
**Fail Criteria:** null; negative; 0; > 3600 (1 hour)

---

## SECTION 4 — DASHBOARD UI — VISUAL ELEMENTS (TC-046 to TC-080)

*Prerequisite: Dashboard server running (`python main.py --serve`); at least one completed cycle (dashboard state exists). Open browser to `http://localhost:8080/`.*

### TC-046 — Page title displays correctly
**Steps:**
1. Open `http://localhost:8080/`
2. Read the browser tab title and the `<h1>` heading

**Pass Criteria:** Page title shows "IMS Agent — Schedule Dashboard"  
**Fail Criteria:** Wrong title; blank; shows "404" or error

---

### TC-047 — Auto-refresh countdown timer visible and counting
**Steps:**
1. Open dashboard
2. Look for the countdown timer (e.g., "Refreshing in 60s")
3. Wait 10 seconds; observe the timer decreasing

**Pass Criteria:** Timer is visible; decreases from 60 toward 0; page reloads at 0  
**Fail Criteria:** Timer not visible; value static; page does not refresh

---

### TC-048 — Last-updated timestamp reflects current cycle
**Steps:**
1. Open dashboard
2. Locate the "Last updated" timestamp

**Pass Criteria:** Timestamp matches the cycle ID or `last_updated` field in `data/dashboard_state.json`  
**Fail Criteria:** Timestamp shows wrong date; missing; shows "Invalid Date"

---

### TC-049 — Health banner renders with correct color (RED state)
**Steps:**
1. Manually set `schedule_health: "RED"` in `data/dashboard_state.json`
2. Refresh dashboard

**Pass Criteria:** Health banner background is red; red dot visible; text shows "RED"  
**Fail Criteria:** Wrong color; missing banner; shows "GREEN" or "YELLOW"

---

### TC-050 — Health banner renders with correct color (YELLOW state)
**Steps:**
1. Manually set `schedule_health: "YELLOW"` in `data/dashboard_state.json`
2. Refresh dashboard

**Pass Criteria:** Health banner background is yellow/amber; yellow dot visible; text shows "YELLOW"  
**Fail Criteria:** Wrong color; shows "RED" or "GREEN"

---

### TC-051 — Health banner renders with correct color (GREEN state)
**Steps:**
1. Manually set `schedule_health: "GREEN"` in `data/dashboard_state.json`
2. Refresh dashboard

**Pass Criteria:** Health banner background is green; green dot visible; text shows "GREEN"  
**Fail Criteria:** Wrong color; shows "RED" or "YELLOW"

---

### TC-052 — Cycle ID displayed in header/banner
**Steps:**
1. Note the `cycle_id` from `data/dashboard_state.json`
2. Open dashboard

**Pass Criteria:** Cycle ID is visible on the page (in banner or header)  
**Fail Criteria:** Cycle ID absent; shows wrong ID

---

### TC-053 — "Trigger Cycle Now" button visible in header
**Steps:**
1. Open dashboard
2. Find the "Trigger Cycle Now" button

**Pass Criteria:** Button visible in header area  
**Fail Criteria:** Button absent; button outside header area

---

### TC-054 — "Trigger Cycle Now" button fires a cycle
**Steps:**
1. Open dashboard
2. Click "Trigger Cycle Now"
3. Observe network request and response (browser DevTools → Network tab)
4. Watch for the "Current Cycle Progress" banner to appear

**Pass Criteria:** POST request sent to `/api/trigger`; 200 or 409 response; progress banner appears (or 409 if cycle already running)  
**Fail Criteria:** Button does nothing; page navigates away; JS error in console

---

### TC-055 — Statistics row: CAMs Responded card
**Steps:**
1. Open dashboard
2. Find the CAM response rate card in the statistics row

**Pass Criteria:** Card shows a ratio like "5/5" or "4/5"; value matches `completion_report` in state JSON  
**Fail Criteria:** Card missing; shows "0/0"; shows wrong value

---

### TC-056 — Statistics row: HIGH Risk Milestones count
**Steps:**
1. Count `milestones` in state JSON where `risk_level = "HIGH"`
2. Open dashboard; find the HIGH risk milestone count card

**Pass Criteria:** Count on card matches JSON count; card is red-colored when count > 0  
**Fail Criteria:** Wrong count; missing card; no red color when HIGH risks exist

---

### TC-057 — Statistics row: Tasks Behind with Blocker count
**Steps:**
1. Count entries in `tasks_behind` in state JSON
2. Open dashboard; find the "Tasks Behind" stat card

**Pass Criteria:** Card count matches `tasks_behind` length in JSON  
**Fail Criteria:** Wrong count; missing card

---

### TC-058 — Statistics row: Critical Path Tasks count
**Steps:**
1. Count `critical_path_task_ids` in state JSON
2. Open dashboard; find the critical path count card

**Pass Criteria:** Card count matches `critical_path_task_ids` length  
**Fail Criteria:** Wrong count; missing card

---

### TC-059 — Milestone Risk Summary table renders all milestones
**Steps:**
1. Note the number of milestones in state JSON
2. Count rows in the Milestone Risk Summary table on the dashboard

**Pass Criteria:** Table row count equals milestone count in JSON; each row has Milestone name, Baseline, P50, P95, On-Time %, Risk Badge  
**Fail Criteria:** Wrong row count; missing columns; empty table when data exists

---

### TC-060 — Risk badges are correct colors
**Steps:**
1. Find a HIGH-risk milestone row in the table
2. Verify badge color is red
3. Find a MEDIUM-risk milestone row; verify badge is yellow/amber
4. Find a LOW-risk milestone row (if any); verify badge is green

**Pass Criteria:** HIGH = red badge, MEDIUM = yellow badge, LOW = green badge  
**Fail Criteria:** Wrong colors; all same color; badges missing

---

### TC-061 — On-Time % values formatted correctly
**Steps:**
1. Note `prob_on_baseline` values from state JSON (decimal, e.g., `0.225`)
2. Open dashboard; read On-Time % column in milestone table

**Pass Criteria:** Values displayed as percentages (e.g., `22.5%`); matches JSON value × 100  
**Fail Criteria:** Shows raw decimal (e.g., `0.225`); wrong value

---

### TC-062 — Milestone table empty state
**Steps:**
1. Temporarily set `milestones: []` in `data/dashboard_state.json`
2. Refresh dashboard

**Pass Criteria:** Table shows a friendly empty-state message (e.g., "No milestone data yet")  
**Fail Criteria:** Table shows nothing; JavaScript error; broken layout

---

### TC-063 — CAM Response Status table: responded vs not-responded
**Steps:**
1. In state JSON, set one CAM's `responded: true` and one `responded: false`
2. Refresh dashboard; find CAM response table

**Pass Criteria:** Responded CAM shows green dot + "Responded"; non-responded shows red dot + "No Response"  
**Fail Criteria:** Wrong colors; all shown as same status; wrong text

---

### TC-064 — CAM attempt count displayed
**Steps:**
1. Check `attempts` value for a CAM in state JSON
2. Verify the displayed value in the CAM table

**Pass Criteria:** Displayed attempt count matches JSON value  
**Fail Criteria:** Wrong number; missing column; 0 when JSON shows > 0

---

### TC-065 — Top Risks section renders text
**Steps:**
1. Open dashboard; find "Top Risks" section

**Pass Criteria:** Non-empty text content from `top_risks` in state JSON is displayed  
**Fail Criteria:** Section missing; shows empty; shows "null" or "undefined"

---

### TC-066 — Top Risks section empty state
**Steps:**
1. Set `top_risks: ""` in state JSON; refresh dashboard

**Pass Criteria:** Section shows "No risk synthesis yet" or similar message  
**Fail Criteria:** Empty section; broken layout; JavaScript error

---

### TC-067 — Tasks Behind table: all columns present
**Steps:**
1. Open dashboard; find "Tasks Behind Schedule" table

**Pass Criteria:** Table has columns: Task ID, CAM, % Complete, Blocker  
**Fail Criteria:** Column missing; table absent when tasks_behind is non-empty

---

### TC-068 — Tasks Behind table: blocker text truncated
**Steps:**
1. Add a task in `tasks_behind` with a blocker string > 120 chars
2. Refresh dashboard

**Pass Criteria:** Blocker text is truncated in table (not full paragraph) with no layout overflow  
**Fail Criteria:** Full long text breaks table layout; text not truncated

---

### TC-069 — Tasks Behind table empty state
**Steps:**
1. Set `tasks_behind: []` in state JSON; refresh dashboard

**Pass Criteria:** Friendly message shown (e.g., "No tasks behind with blockers")  
**Fail Criteria:** Empty table with no message; broken layout

---

### TC-070 — Critical Path task IDs render as chips/badges
**Steps:**
1. Open dashboard; find Critical Path section

**Pass Criteria:** Task IDs appear as styled chips/badges (small colored rectangles with text)  
**Fail Criteria:** Task IDs shown as plain comma-separated text; missing section

---

### TC-071 — Critical Path empty state
**Steps:**
1. Set `critical_path_task_ids: []` in state JSON; refresh dashboard

**Pass Criteria:** Friendly message shown ("No critical path data available" or similar)  
**Fail Criteria:** Empty section; broken layout

---

### TC-072 — Recommended Actions section renders
**Steps:**
1. Open dashboard; find "Recommended Actions" section

**Pass Criteria:** Non-empty text from `recommended_actions` in JSON is displayed  
**Fail Criteria:** Section missing; empty content; shows "undefined"

---

### TC-073 — Cycle History section shows last N cycles
**Steps:**
1. Open dashboard; find the Cycle History section
2. Count history entries displayed

**Pass Criteria:** Number of rows matches `data/cycle_history.json` entry count (up to 52)  
**Fail Criteria:** Wrong count; empty history when JSON has entries

---

### TC-074 — Cycle history health badges correct color
**Steps:**
1. Note health values for each history entry in JSON
2. Check badge colors in history section

**Pass Criteria:** RED entries have red badge; YELLOW have yellow; GREEN have green  
**Fail Criteria:** Wrong colors; all same color

---

### TC-075 — Cycle history shows CAM response rate
**Steps:**
1. Check a history entry in JSON for `cams_responded` and `cams_total`
2. Find corresponding row in dashboard history section

**Pass Criteria:** Ratio displayed (e.g., "5/5") matches JSON values  
**Fail Criteria:** Missing; shows "0/0"; wrong value

---

### TC-076 — Current cycle progress banner appears during active cycle
**Steps:**
1. Trigger a cycle via `POST /api/trigger`
2. Immediately refresh the dashboard within a few seconds

**Pass Criteria:** Blue-bordered progress banner appears showing current phase and cycle ID  
**Fail Criteria:** No banner during active cycle; banner shows after cycle completes

---

### TC-077 — Current cycle progress banner disappears when cycle completes
**Steps:**
1. Wait for the active cycle to complete
2. Refresh dashboard

**Pass Criteria:** Progress banner is no longer visible after cycle completes  
**Fail Criteria:** Banner persists after completion; banner shows wrong phase

---

### TC-078 — Page renders correctly with no state data (first run)
**Steps:**
1. Delete `data/dashboard_state.json`
2. Refresh dashboard

**Pass Criteria:** Dashboard renders without crashing; empty-state messages shown in each section; no JavaScript errors  
**Fail Criteria:** HTTP 500; JavaScript console errors; broken layout

---

### TC-079 — Page is responsive (narrow viewport)
**Steps:**
1. Open dashboard
2. Resize browser to 375px width (mobile size)

**Pass Criteria:** No horizontal scrollbar; all content remains readable; grid collapses to single column  
**Fail Criteria:** Horizontal overflow; text overflows containers; overlapping elements

---

### TC-080 — Page is responsive (medium viewport)
**Steps:**
1. Open dashboard
2. Resize browser to 768px width (tablet size)

**Pass Criteria:** Layout adapts gracefully; stats cards reflow to 2 columns  
**Fail Criteria:** Broken layout; significant horizontal overflow

---

## SECTION 5 — Q&A CHAT WIDGET (TC-081 to TC-105)

*Prerequisite: Dashboard running; cycle completed; state data available.*

### TC-081 — Chat widget is visible on the page
**Steps:**
1. Open dashboard; scroll to bottom

**Pass Criteria:** Chat widget visible; contains example question chips, message area, input field, Ask button, Clear button  
**Fail Criteria:** Widget missing; partially hidden; only partially rendered

---

### TC-082 — All 8 example question chips visible
**Steps:**
1. Open dashboard; locate example question chips

**Pass Criteria:** 8 chips visible with text: "Critical path?", "Top risks?", "Focus this week?", "PDR probability?", "Alice Nguyen status?", "Why is SE-03 behind?", "Changes this cycle?", "Schedule health?"  
**Fail Criteria:** Fewer than 8 chips; wrong text; chips absent

---

### TC-083 — Clicking a chip populates the input and sends the question
**Steps:**
1. Click the "Schedule health?" chip
2. Observe the input field and the chat area

**Pass Criteria:** Question sent immediately (or populated in input); response appears in chat within 10 seconds  
**Fail Criteria:** Nothing happens; input not populated; no response appears

---

### TC-084 — Direct Q&A: "Schedule health?" returns health answer
**Steps:**
1. Type "What is the schedule health?" in the input; click Ask

**Pass Criteria:** Response includes the health value (RED, YELLOW, or GREEN) and the cycle ID  
**Fail Criteria:** Blank response; error; shows unrelated content

---

### TC-085 — Direct Q&A: "What are the top risks?" returns risks
**Steps:**
1. Ask "What are the top risks?"

**Pass Criteria:** Response contains risk text from `top_risks` in state JSON; `direct: true` visible or response is fast (<1s)  
**Fail Criteria:** Response is empty; shows "no risks" when risks exist

---

### TC-086 — Direct Q&A: "What should I focus on this week?" returns actions
**Steps:**
1. Ask "What should I focus on this week?"

**Pass Criteria:** Response contains recommended actions from state; direct answer (fast)  
**Fail Criteria:** Generic or empty response

---

### TC-087 — Direct Q&A: "Critical path tasks" returns task IDs
**Steps:**
1. Ask "What are the critical path tasks?"

**Pass Criteria:** Response lists critical path task IDs (matching `critical_path_task_ids` in state JSON)  
**Fail Criteria:** Empty response; wrong IDs; non-direct (slow LLM call for a simple question)

---

### TC-088 — LLM Q&A: complex question returns detailed answer
**Steps:**
1. Ask "Why is Alice Nguyen behind schedule?"
2. Wait up to 20 seconds for response

**Pass Criteria:** Response references Alice Nguyen; includes specific tasks or blockers; contains detail beyond the direct-answer patterns  
**Fail Criteria:** Timeout; error message; generic response about schedule health

---

### TC-089 — LLM Q&A: float question triggers tool use
**Steps:**
1. Ask "What is the total float on task SE-03?"
2. Wait for response

**Pass Criteria:** Response includes a specific float value in days (not "data unavailable"); sources the answer from IMS data  
**Fail Criteria:** "I don't have that information"; generic answer; error

---

### TC-090 — LLM Q&A: dependency question uses get_dependencies tool
**Steps:**
1. Ask "What are the successors of task 1?"

**Pass Criteria:** Response lists successor task IDs/names; specific data from IMS XML  
**Fail Criteria:** "I don't know"; generic; no task-specific answer

---

### TC-091 — LLM Q&A: milestone probability question
**Steps:**
1. Ask "What is the probability of hitting PDR on time?"

**Pass Criteria:** Response includes a specific probability value (e.g., "22.5%") matching the SRA data  
**Fail Criteria:** No probability value; "I don't know"; generic

---

### TC-092 — LLM Q&A: CAM workload question uses get_tasks_by_cam tool
**Steps:**
1. Ask "What tasks does Bob Martinez own?"

**Pass Criteria:** Response lists tasks assigned to Bob Martinez  
**Fail Criteria:** Wrong CAM's tasks; no tasks listed; error

---

### TC-093 — User message bubble aligned right
**Steps:**
1. Ask any question
2. Observe message bubble style

**Pass Criteria:** User message appears right-aligned with blue background  
**Fail Criteria:** Left-aligned; wrong background color; no visual distinction from AI messages

---

### TC-094 — AI response bubble aligned left with citation
**Steps:**
1. Ask any question; observe the AI response

**Pass Criteria:** AI response appears left-aligned with white/light background; source cycle ID shown below the response  
**Fail Criteria:** Right-aligned; no citation; no visual distinction from user message

---

### TC-095 — "Thinking…" indicator appears during processing
**Steps:**
1. Ask an LLM-routed question (complex, e.g., "Why is SE-03 behind?")
2. Watch chat area immediately after clicking Ask

**Pass Criteria:** "Thinking…" placeholder appears in chat area while LLM is processing; disappears when answer arrives  
**Fail Criteria:** No thinking indicator; input freezes; nothing happens during processing

---

### TC-096 — Input disabled while question is processing
**Steps:**
1. Ask a complex question
2. Immediately try to type another question while the first is processing

**Pass Criteria:** Input field and Ask button are disabled during processing  
**Fail Criteria:** Multiple simultaneous requests possible; no input disabling

---

### TC-097 — Input max length enforced (500 chars)
**Steps:**
1. Paste a 600-character string into the input
2. Click Ask

**Pass Criteria:** Either input truncates to 500 chars, or a client-side or server-side error prevents submission with a clear message  
**Fail Criteria:** Request submitted without truncation; silent failure

---

### TC-098 — Empty question rejected
**Steps:**
1. Click Ask with empty input

**Pass Criteria:** Error message shown ("question is required" or similar); no API call made  
**Fail Criteria:** Blank question submitted; API returns 400 silently; page broken

---

### TC-099 — Clear chat button (✕) clears all messages
**Steps:**
1. Ask 2–3 questions
2. Click the "✕" Clear button

**Pass Criteria:** All messages removed from chat area; input cleared; example chips visible again (or original state restored)  
**Fail Criteria:** Messages remain; button does nothing; page refresh needed to clear

---

### TC-100 — Chat history persists through auto-refresh (sessionStorage)
**Steps:**
1. Ask 2 questions and receive answers
2. Wait for the 60-second auto-refresh OR manually refresh the page (F5)
3. Observe chat state after refresh

**Pass Criteria:** Chat history is restored from sessionStorage; previous messages visible  
**Fail Criteria:** Chat history lost on refresh; empty chat after every reload

---

### TC-101 — Chat scrolls to latest message
**Steps:**
1. Ask many questions to fill the chat area
2. Verify the chat area scrolls to show the latest response

**Pass Criteria:** Latest message visible without manual scrolling after each response  
**Fail Criteria:** User must scroll down manually to see latest response

---

### TC-102 — Rate limiting: 429 shown in chat after limit exceeded
**Steps:**
1. Set `QA_RATE_LIMIT_PER_HOUR=2` in `.env`; restart server
2. Ask 3 questions from the same browser

**Pass Criteria:** Third question shows rate limit error message in chat (HTTP 429)  
**Fail Criteria:** Third question answered normally; chat shows generic error without explaining rate limit

---

### TC-103 — Q&A when no state data exists
**Steps:**
1. Delete `data/dashboard_state.json`; restart server
2. Ask "What is the schedule health?"

**Pass Criteria:** Response says "No schedule data is available yet. Run a cycle first." (or equivalent)  
**Fail Criteria:** Error; blank response; server crashes

---

### TC-104 — Q&A response shows source_cycle citation
**Steps:**
1. Perform a direct Q&A query and note the `source_cycle` in the response from `GET /api/ask`
2. Verify the chat widget shows this cycle ID below the answer

**Pass Criteria:** Cycle ID visible below AI response bubble; matches `cycle_id` in state JSON  
**Fail Criteria:** No citation; wrong cycle ID shown

---

### TC-105 — Q&A direct answer is visually distinct from LLM answer
**Steps:**
1. Ask "What is the schedule health?" (direct answer)
2. Ask "Why is task 3 behind?" (LLM answer)
3. Compare response times

**Pass Criteria:** Direct answer returns in < 1 second; LLM answer returns in 5–20 seconds  
**Fail Criteria:** Both take equal time; direct answer is as slow as LLM

---

## SECTION 6 — API ENDPOINTS (TC-106 to TC-130)

*Prerequisite: Server running. Use curl or any HTTP client.*

### TC-106 — GET /health returns 200 without auth
**Steps:**
1. Run `curl http://localhost:8080/health`

**Pass Criteria:** HTTP 200; JSON body has `status: "healthy"`; `uptime_seconds` > 0  
**Fail Criteria:** HTTP 401; HTTP 500; connection refused

---

### TC-107 — GET /health body fields are complete
**Steps:**
1. Run `curl http://localhost:8080/health`
2. Parse JSON response

**Pass Criteria:** Response contains `status`, `uptime_seconds`, `cycle_active`, `state_file_present`, `auth_enabled`  
**Fail Criteria:** Any field missing

---

### TC-108 — GET /health `cycle_active` reflects real cycle state
**Steps:**
1. Check `/health` when no cycle running → `cycle_active: false`
2. Trigger a cycle; check `/health` immediately → `cycle_active: true`

**Pass Criteria:** `cycle_active` changes state correctly  
**Fail Criteria:** Always false; always true; not updated in real time

---

### TC-109 — GET /metrics returns 200 (dev mode, no auth)
**Steps:**
1. Ensure `DASHBOARD_API_KEY` is empty; run `curl http://localhost:8080/metrics`

**Pass Criteria:** HTTP 200; JSON with all 7 metric keys  
**Fail Criteria:** HTTP 401; missing keys; non-JSON response

---

### TC-110 — GET /metrics requires auth when key is configured
**Steps:**
1. Set `DASHBOARD_API_KEY=mykey`; restart server
2. Run `curl http://localhost:8080/metrics` (no header)

**Pass Criteria:** HTTP 401  
**Fail Criteria:** HTTP 200 (auth bypass); HTTP 500

---

### TC-111 — GET /metrics with valid key succeeds
**Steps:**
1. Run `curl -H "X-API-Key: mykey" http://localhost:8080/metrics`

**Pass Criteria:** HTTP 200; JSON body contains `cycles_completed`, `qa_queries_total`, etc.  
**Fail Criteria:** HTTP 401 with valid key; missing fields

---

### TC-112 — GET /api/state returns current state
**Steps:**
1. Run `curl -H "X-API-Key: mykey" http://localhost:8080/api/state`

**Pass Criteria:** HTTP 200; JSON matches content of `data/dashboard_state.json`  
**Fail Criteria:** HTTP 404 when state exists; 401 with valid key; wrong data

---

### TC-113 — GET /api/state returns 404 when no state exists
**Steps:**
1. Delete `data/dashboard_state.json`
2. Run `curl -H "X-API-Key: mykey" http://localhost:8080/api/state`

**Pass Criteria:** HTTP 404; JSON body `{"error": "No cycle data yet"}`  
**Fail Criteria:** HTTP 200 with empty body; HTTP 500

---

### TC-114 — GET /api/history returns history array
**Steps:**
1. Run `curl -H "X-API-Key: mykey" http://localhost:8080/api/history`

**Pass Criteria:** HTTP 200; JSON array; each entry has `cycle_id`, `timestamp`, `schedule_health`, `cams_responded`, `cams_total`  
**Fail Criteria:** Not an array; missing required fields; HTTP 500

---

### TC-115 — GET /api/history returns empty array when no history
**Steps:**
1. Delete `data/cycle_history.json`
2. Run `curl -H "X-API-Key: mykey" http://localhost:8080/api/history`

**Pass Criteria:** HTTP 200; JSON body is `[]`  
**Fail Criteria:** HTTP 404; HTTP 500; null body

---

### TC-116 — GET /api/status returns cycle_active
**Steps:**
1. Run `curl -H "X-API-Key: mykey" http://localhost:8080/api/status`

**Pass Criteria:** HTTP 200; JSON body `{"cycle_active": false}` when idle  
**Fail Criteria:** Missing field; non-boolean value; HTTP 500

---

### TC-117 — POST /api/trigger fires a cycle
**Steps:**
1. Run `curl -X POST -H "X-Admin-Key: adminkey" http://localhost:8080/api/trigger`
2. Immediately run `curl -H "X-API-Key: mykey" http://localhost:8080/api/status`

**Pass Criteria:** Trigger returns 200 `{"status": "triggered"}`; status shows `cycle_active: true`  
**Fail Criteria:** Returns 500; status not updated

---

### TC-118 — POST /api/trigger 409 when cycle already running
**Steps:**
1. Trigger a cycle (TC-117)
2. Immediately trigger again

**Pass Criteria:** Second trigger returns HTTP 409 `{"detail": "A cycle is already running"}`  
**Fail Criteria:** 200 (second cycle launched); 500

---

### TC-119 — POST /api/admin/purge returns deleted counts
**Steps:**
1. Run `curl -X POST -H "X-Admin-Key: adminkey" http://localhost:8080/api/admin/purge`

**Pass Criteria:** HTTP 200; JSON body `{"status": "ok", "deleted": {"cycle_status": N, "snapshots": N}}`  
**Fail Criteria:** 500; wrong body structure; `deleted` missing

---

### TC-120 — POST /api/ask direct question returns quickly
**Steps:**
1. Run `curl -X POST -H "X-API-Key: mykey" -H "Content-Type: application/json" -d '{"question":"What is the schedule health?"}' http://localhost:8080/api/ask`

**Pass Criteria:** HTTP 200; JSON has `answer`, `source_cycle`, `intent`, `direct: true`; response time < 1 second  
**Fail Criteria:** `direct: false` for a simple health question; timeout; 500

---

### TC-121 — POST /api/ask LLM question returns detailed answer
**Steps:**
1. Run `curl ... -d '{"question":"What is the total float on task 3?"}'`

**Pass Criteria:** HTTP 200; `answer` contains specific float value; `direct: false`  
**Fail Criteria:** Empty answer; "data not available"; `direct: true`

---

### TC-122 — POST /api/ask 400 on empty question
**Steps:**
1. Run `curl ... -d '{"question":""}'`

**Pass Criteria:** HTTP 400 `{"detail": "question is required"}`  
**Fail Criteria:** HTTP 200 with empty answer; HTTP 500

---

### TC-123 — POST /api/ask 400 on question over 500 chars
**Steps:**
1. Run `curl ... -d '{"question":"'"$(python -c "print('x'*501)")"'"}'`

**Pass Criteria:** HTTP 400 `{"detail": "question too long (max 500 chars)"}`  
**Fail Criteria:** HTTP 200; question processed; HTTP 500

---

### TC-124 — POST /api/ask 429 on rate limit exceeded
**Steps:**
1. Set `QA_RATE_LIMIT_PER_HOUR=1`; restart server
2. Call `/api/ask` twice from same IP

**Pass Criteria:** First call returns 200; second returns HTTP 429  
**Fail Criteria:** Both 200; 500; wrong error code

---

### TC-125 — All read endpoints return 401 without key (auth enabled)
**Steps:**
1. Set `DASHBOARD_API_KEY=somekey`; restart server
2. Call each of: `GET /api/state`, `GET /api/history`, `GET /api/status`, `GET /metrics` without the `X-API-Key` header

**Pass Criteria:** All return HTTP 401  
**Fail Criteria:** Any returns 200; any returns 500

---

### TC-126 — Admin endpoints return 401 without admin key (two-key mode)
**Steps:**
1. Set `DASHBOARD_API_KEY=readkey` and `DASHBOARD_ADMIN_KEY=adminkey`; restart server
2. Call `POST /api/trigger` with only `X-API-Key: readkey` (no admin key)

**Pass Criteria:** HTTP 401  
**Fail Criteria:** HTTP 200 (RBAC bypassed)

---

### TC-127 — Wrong key returns 401
**Steps:**
1. Call `GET /api/state` with `X-API-Key: wrongkey`

**Pass Criteria:** HTTP 401  
**Fail Criteria:** HTTP 200; HTTP 403; HTTP 500

---

### TC-128 — GET /health is never authenticated
**Steps:**
1. Set `DASHBOARD_API_KEY=somekey`; restart server
2. Call `GET /health` without any header

**Pass Criteria:** HTTP 200 always — even with auth enabled  
**Fail Criteria:** HTTP 401; HTTP 403

---

### TC-129 — Invalid JSON body on /api/ask returns 422
**Steps:**
1. Run `curl -X POST -H "X-API-Key: mykey" -H "Content-Type: application/json" -d "not-json" http://localhost:8080/api/ask`

**Pass Criteria:** HTTP 422 (Unprocessable Entity) — FastAPI's default for invalid request body  
**Fail Criteria:** HTTP 200; HTTP 500; server crash

---

### TC-130 — Metrics counters reset on process restart
**Steps:**
1. Run several triggers; note `cycles_completed` from `/metrics`
2. Stop and restart the server
3. Re-check `/metrics`

**Pass Criteria:** `cycles_completed` = 0 after restart (in-memory counters)  
**Fail Criteria:** Counters persist across restart; show wrong value

---

## SECTION 7 — AUTHENTICATION & RBAC (TC-131 to TC-145)

### TC-131 — Dev mode: no keys, all routes accessible
**Steps:**
1. Set `DASHBOARD_API_KEY=` and `DASHBOARD_ADMIN_KEY=` (both empty)
2. Call all API routes without any headers

**Pass Criteria:** All routes return 200 (or 404/409 for legitimate reasons); no 401 responses  
**Fail Criteria:** Any 401 returned in dev mode

---

### TC-132 — Single-key mode: API key works for read routes
**Steps:**
1. Set `DASHBOARD_API_KEY=onekey`, `DASHBOARD_ADMIN_KEY=` (empty)
2. Call `GET /api/state` with `X-API-Key: onekey`

**Pass Criteria:** HTTP 200  
**Fail Criteria:** HTTP 401

---

### TC-133 — Single-key mode: API key works for admin routes (fallback)
**Steps:**
1. Same config as TC-132
2. Call `POST /api/trigger` with `X-API-Key: onekey`

**Pass Criteria:** HTTP 200 (triggered) — single key covers admin routes when no admin key set  
**Fail Criteria:** HTTP 401

---

### TC-134 — Two-key mode: read key covers read routes
**Steps:**
1. Set `DASHBOARD_API_KEY=readkey`, `DASHBOARD_ADMIN_KEY=adminkey`
2. Call `GET /api/state` with `X-API-Key: readkey`

**Pass Criteria:** HTTP 200  
**Fail Criteria:** HTTP 401

---

### TC-135 — Two-key mode: read key blocked on admin routes
**Steps:**
1. Same config as TC-134
2. Call `POST /api/trigger` with `X-API-Key: readkey` (no admin key)

**Pass Criteria:** HTTP 401  
**Fail Criteria:** HTTP 200 (RBAC defeated)

---

### TC-136 — Two-key mode: admin key accepted on admin routes (X-Admin-Key header)
**Steps:**
1. Same config as TC-134
2. Call `POST /api/trigger` with `X-Admin-Key: adminkey`

**Pass Criteria:** HTTP 200  
**Fail Criteria:** HTTP 401

---

### TC-137 — Two-key mode: admin key accepted on admin routes (X-API-Key header)
**Steps:**
1. Same config as TC-134
2. Call `POST /api/trigger` with `X-API-Key: adminkey` (admin key in the read header)

**Pass Criteria:** HTTP 200 — the effective admin key is accepted in either header  
**Fail Criteria:** HTTP 401

---

### TC-138 — Two-key mode: admin key does not grant read-route access via X-Admin-Key
**Steps:**
1. Same config as TC-134
2. Call `GET /api/state` with `X-Admin-Key: adminkey` (no read key)

**Pass Criteria:** HTTP 401 — admin key does not substitute for read key on read routes  
**Fail Criteria:** HTTP 200

---

### TC-139 — Wrong admin key is rejected
**Steps:**
1. Call `POST /api/admin/purge` with `X-Admin-Key: wrongkey`

**Pass Criteria:** HTTP 401  
**Fail Criteria:** HTTP 200; HTTP 500

---

### TC-140 — Rate limit is per-IP, not global
**Steps:**
1. Set `QA_RATE_LIMIT_PER_HOUR=2`
2. Make 2 requests from `127.0.0.1`
3. Make 1 request from a different IP (simulated by forwarded header or separate machine)

**Pass Criteria:** Third request from `127.0.0.1` gets 429; first request from other IP gets 200  
**Fail Criteria:** All requests blocked after global limit; rate limit not per-IP

---

### TC-141 — Rate limit counter resets after 1 hour window
**Steps:**
1. Set `QA_RATE_LIMIT_PER_HOUR=1`; make 1 request (now at limit)
2. Manually inject a stale timestamp into `_rate_limiter` via debug or restart with manipulated time
3. Make another request

**Pass Criteria:** New request within empty window succeeds  
**Fail Criteria:** Blocked even after window expires

---

### TC-142 — Rate limit of 0 disables limiting
**Steps:**
1. Set `QA_RATE_LIMIT_PER_HOUR=0`
2. Make 10 rapid requests to `/api/ask`

**Pass Criteria:** All 10 requests return 200  
**Fail Criteria:** 429 returned with limit=0

---

### TC-143 — auth_enabled flag reflects configuration
**Steps:**
1. Test with `DASHBOARD_API_KEY=` (empty): `GET /health` should return `auth_enabled: false`
2. Test with `DASHBOARD_API_KEY=somekey`: `GET /health` should return `auth_enabled: true`

**Pass Criteria:** `auth_enabled` correctly reflects whether a key is set  
**Fail Criteria:** `auth_enabled: false` when key is set; `auth_enabled: true` when no key set

---

### TC-144 — No API key configured — `/api/ask` accessible without header
**Steps:**
1. `DASHBOARD_API_KEY=` (empty); send `POST /api/ask` without any header

**Pass Criteria:** HTTP 200 (or 429 if rate limited, or 500 for LLM error)  
**Fail Criteria:** HTTP 401

---

### TC-145 — Case sensitivity: key values are case-sensitive
**Steps:**
1. Set `DASHBOARD_API_KEY=MySecretKey`
2. Call with `X-API-Key: mysecretkey` (wrong case)

**Pass Criteria:** HTTP 401 (keys are case-sensitive)  
**Fail Criteria:** HTTP 200 (case-insensitive match)

---

## SECTION 8 — Q&A ENGINE & IMS TOOLS (TC-146 to TC-165)

### TC-146 — Direct pattern: "schedule health" phrase
**Steps:**
1. Ask "What is the current schedule health?" via `/api/ask`
2. Check `direct: true` in response

**Pass Criteria:** `direct: true`; answer contains health value  
**Fail Criteria:** `direct: false` (routed to LLM unnecessarily)

---

### TC-147 — Direct pattern: "top risks" phrase
**Steps:**
1. Ask "What are the top risks?"

**Pass Criteria:** `direct: true`; answer contains text from `top_risks` in state  
**Fail Criteria:** `direct: false`; empty answer

---

### TC-148 — Direct pattern: "recommended actions"
**Steps:**
1. Ask "What are the recommended actions?"

**Pass Criteria:** `direct: true`; answer from `recommended_actions`  
**Fail Criteria:** `direct: false`; wrong content

---

### TC-149 — Direct pattern: "what should I do"
**Steps:**
1. Ask "What should I do this week?"

**Pass Criteria:** `direct: true`; answer from `recommended_actions`  
**Fail Criteria:** `direct: false`

---

### TC-150 — Direct pattern: "critical path tasks"
**Steps:**
1. Ask "What are the critical path tasks?"

**Pass Criteria:** `direct: true`; answer lists task IDs  
**Fail Criteria:** `direct: false`; missing task IDs

---

### TC-151 — Intent detection: "critical path" intent
**Steps:**
1. Ask "Tell me about the critical path"
2. Check `intent` array in response

**Pass Criteria:** `"critical_path"` in `intent`  
**Fail Criteria:** Intent array empty; wrong intents

---

### TC-152 — Intent detection: "milestone" intent
**Steps:**
1. Ask "What is the PDR probability?"

**Pass Criteria:** `"milestone"` in `intent`  
**Fail Criteria:** Wrong intent detected

---

### TC-153 — Intent detection: "blocker" intent
**Steps:**
1. Ask "Why is task SE-03 behind?"

**Pass Criteria:** `"blocker"` in `intent`  
**Fail Criteria:** Wrong or empty intent

---

### TC-154 — Tool: get_task returns full task detail
**Steps:**
1. Ask "What are the details of task 1?"
2. Check response for task-specific fields (name, CAM, percent complete, dates)

**Pass Criteria:** Response contains task name, CAM, percent_complete, start, finish  
**Fail Criteria:** Generic answer; "task not found"

---

### TC-155 — Tool: search_tasks returns matching results
**Steps:**
1. Ask "What tasks have 'Interface' in their name?"

**Pass Criteria:** Response lists tasks with "Interface" in the name  
**Fail Criteria:** Empty results when matching tasks exist

---

### TC-156 — Tool: get_critical_path returns ordered CP
**Steps:**
1. Ask "List all tasks on the critical path in order"

**Pass Criteria:** Response includes an ordered list of critical path tasks from IMS data  
**Fail Criteria:** Unordered; empty; mismatch with `critical_path_task_ids` in state

---

### TC-157 — Tool: get_tasks_by_cam returns CAM-specific tasks
**Steps:**
1. Ask "What tasks does Alice Nguyen own?"

**Pass Criteria:** Response lists only Alice Nguyen's tasks (WBS 1.x tasks)  
**Fail Criteria:** Tasks from other CAMs included; wrong CAM matched

---

### TC-158 — Tool: get_float returns float value
**Steps:**
1. Ask "How much total float does task 3 have?"

**Pass Criteria:** Response includes a specific numeric float value (days)  
**Fail Criteria:** "I don't know"; generic health summary

---

### TC-159 — Tool: get_dependencies returns predecessors and successors
**Steps:**
1. Ask "What are the predecessors and successors of task 5?"

**Pass Criteria:** Response identifies both predecessor and successor tasks  
**Fail Criteria:** Only one direction; empty; wrong task

---

### TC-160 — Tool: get_milestones returns all 7 milestones
**Steps:**
1. Ask "List all program milestones"

**Pass Criteria:** Response mentions 7 (or close) milestones including SRR, PDR, CDR  
**Fail Criteria:** Fewer than 5 milestones; wrong names

---

### TC-161 — Tool: get_behind_tasks returns tasks behind schedule
**Steps:**
1. Ask "Which tasks are most behind schedule?"

**Pass Criteria:** Response lists specific tasks with percent-behind values  
**Fail Criteria:** Empty list when tasks are behind; generic narrative only

---

### TC-162 — Multi-tool call in one question
**Steps:**
1. Ask "Show me the float on SE-03 and list all tasks Bob Martinez owns"

**Pass Criteria:** Response addresses both parts with specific data (two tool calls likely triggered)  
**Fail Criteria:** Only one part answered; hallucinated data

---

### TC-163 — No state data: graceful response
**Steps:**
1. Delete `data/dashboard_state.json`
2. Ask any question via `/api/ask`

**Pass Criteria:** Response: "No schedule data is available yet. Run a cycle first."  
**Fail Criteria:** HTTP 500; uncaught exception; blank response

---

### TC-164 — Tool cache invalidated after cycle
**Steps:**
1. Ask a question that uses tool data (e.g., float for task 1)
2. Run a new cycle that changes task 1's percent complete
3. Ask the same question again

**Pass Criteria:** Second answer reflects updated task data  
**Fail Criteria:** Second answer returns stale data from before the cycle

---

### TC-165 — Max tool rounds cap (5 rounds)
**Steps:**
1. Ask an extremely complex question likely to require multiple tool calls (e.g., "For each CAM, what is their most behind task and its predecessor?")
2. Verify a response is returned (not a timeout or empty)

**Pass Criteria:** Response returned; if data is insufficient, falls back to "Unable to complete analysis within allowed steps"  
**Fail Criteria:** Hangs indefinitely; server error; silent failure

---

## SECTION 9 — DATA RETENTION & PURGE (TC-166 to TC-175)

### TC-166 — Purge deletes old cycle status files
**Steps:**
1. Create an old file in `reports/cycles/` with mtime set to 100 days ago
2. Call `POST /api/admin/purge` (or run `CycleRunner.purge_old_data(90)`)
3. Check if old file was deleted; new files kept

**Pass Criteria:** Old file deleted; recent files intact  
**Fail Criteria:** Old file not deleted; recent files deleted

---

### TC-167 — Purge deletes old XML snapshots
**Steps:**
1. Create an old XML file in `data/snapshots/` with mtime set to 100 days ago
2. Run purge
3. Verify old snapshot deleted

**Pass Criteria:** Old snapshot deleted  
**Fail Criteria:** Snapshot not deleted

---

### TC-168 — Purge returns correct deletion counts
**Steps:**
1. Create 3 old cycle JSONs and 2 old snapshots
2. Run `POST /api/admin/purge`
3. Check `deleted` in response

**Pass Criteria:** Response shows `{"cycle_status": 3, "snapshots": 2}`  
**Fail Criteria:** Wrong counts; zero counts when files were deleted

---

### TC-169 — Auto-purge runs after every cycle
**Steps:**
1. Set `DATA_RETENTION_DAYS=0` (purge everything)
2. Create an old dummy file in `reports/cycles/`
3. Run a full cycle
4. Verify old file was deleted

**Pass Criteria:** Dummy file deleted after cycle  
**Fail Criteria:** Dummy file not deleted; cycle fails because of purge error

---

### TC-170 — DATA_RETENTION_DAYS=0 purges all old files immediately
**Steps:**
1. Set `DATA_RETENTION_DAYS=0`
2. Run purge

**Pass Criteria:** All files in `reports/cycles/` and `data/snapshots/` are deleted  
**Fail Criteria:** Files remain; error raised

---

### TC-171 — Purge does not fail when directories are empty
**Steps:**
1. Delete all files in `reports/cycles/` and `data/snapshots/`
2. Run purge

**Pass Criteria:** Returns `{"cycle_status": 0, "snapshots": 0}`; no error  
**Fail Criteria:** Exception; non-zero counts

---

### TC-172 — Purge does not fail when directories do not exist
**Steps:**
1. Delete `reports/cycles/` and `data/snapshots/` directories entirely
2. Run purge

**Pass Criteria:** Returns `{"cycle_status": 0, "snapshots": 0}`; no exception  
**Fail Criteria:** FileNotFoundError or other exception

---

### TC-173 — POST /api/admin/purge requires admin key
**Steps:**
1. Two-key mode configured
2. Call `POST /api/admin/purge` without any key header

**Pass Criteria:** HTTP 401  
**Fail Criteria:** HTTP 200 without authorization

---

### TC-174 — Data retention default is 90 days
**Steps:**
1. Do not set `DATA_RETENTION_DAYS` in `.env`
2. Check source at `agent/cycle_runner.py` line with `_RETENTION_DAYS`

**Pass Criteria:** Default value is 90  
**Fail Criteria:** Default is 0, null, or another value

---

### TC-175 — Purge error does not fail the cycle
**Steps:**
1. Make `reports/cycles/` read-only (or simulate a purge error in test)
2. Run a full cycle

**Pass Criteria:** Cycle completes with phase = `complete`; purge error only logged (not thrown)  
**Fail Criteria:** Cycle fails because of purge error

---

## SECTION 10 — VALIDATION (TC-176 to TC-185)

### TC-176 — Backwards movement flagged
**Steps:**
1. Run a cycle so task 1 has percent_complete > 0 in the IMS
2. Manually set a CAM input with a lower percent_complete than current
3. Run validation via unit test: `ScheduleValidator().validate(inputs, tasks)`

**Pass Criteria:** ValidationResult has at least one failure for the backwards-moving task  
**Fail Criteria:** No failure recorded; exception raised

---

### TC-177 — Backwards movement allowed when VALIDATION_ALLOW_BACKWARDS=true
**Steps:**
1. Set `VALIDATION_ALLOW_BACKWARDS=true`
2. Run the same scenario as TC-176

**Pass Criteria:** No failure for the backwards move  
**Fail Criteria:** Failure recorded despite config override

---

### TC-178 — Large jump flagged as warning
**Steps:**
1. Create a CAM input with percent jump > VALIDATION_MAX_JUMP_PCT (default 50)
2. Run validation

**Pass Criteria:** ValidationResult has a warning for the large jump; `passed` is still True  
**Fail Criteria:** Warning missing; `passed` is False (should not block)

---

### TC-179 — Large jump threshold configurable via VALIDATION_MAX_JUMP_PCT
**Steps:**
1. Set `VALIDATION_MAX_JUMP_PCT=10`
2. Create a CAM input with a 15% jump
3. Run validation

**Pass Criteria:** Warning flagged for 15% jump (exceeds 10% threshold)  
**Fail Criteria:** Jump not flagged at new threshold

---

### TC-180 — Missing response flagged as warning
**Steps:**
1. Create an input list that omits tasks from one CAM
2. Run validation

**Pass Criteria:** Warning for missing task response  
**Fail Criteria:** No warning for missing response

---

### TC-181 — Milestones excluded from coverage check
**Steps:**
1. Create inputs that omit all milestone tasks
2. Run validation

**Pass Criteria:** No warning for missing milestone responses  
**Fail Criteria:** Warnings for missing milestone responses

---

### TC-182 — Validation does not block cycle
**Steps:**
1. Trigger a cycle with data that generates validation failures
2. Verify cycle completes

**Pass Criteria:** Cycle phase = `complete`; validation_holds contains the failures but cycle not blocked  
**Fail Criteria:** Cycle phase = `failed` due to validation

---

### TC-183 — Validation holds persisted in status file
**Steps:**
1. Trigger a cycle with backwards movement
2. Open `reports/cycles/{cycle_id}_status.json`

**Pass Criteria:** `validation_holds` array is non-empty; contains descriptive strings  
**Fail Criteria:** Empty array despite failures; field missing

---

### TC-184 — No validation errors on clean data
**Steps:**
1. Ensure IMS file has no backwards movement and all tasks have responses
2. Run validation

**Pass Criteria:** ValidationResult `passed = True`; empty failures and warnings  
**Fail Criteria:** False positives; failures on clean data

---

### TC-185 — Validation failure detail format
**Steps:**
1. Trigger a backwards movement failure
2. Check the detail string in the ValidationFailure

**Pass Criteria:** Detail message includes old %, new %, and task context  
**Fail Criteria:** Vague message; missing percentages

---

## SECTION 11 — REPORTS (TC-186 to TC-195)

### TC-186 — Report filename is YYYY-MM-DD format
**Steps:**
1. Run `python main.py --trigger`
2. Check the filename of the new report

**Pass Criteria:** Filename: `YYYY-MM-DD_ims_report.md` where date is today  
**Fail Criteria:** Wrong date; wrong format; no date

---

### TC-187 — Report contains schedule health
**Steps:**
1. Open the generated report
2. Search for "Schedule Health" section

**Pass Criteria:** Section present; shows RED, YELLOW, or GREEN with emoji  
**Fail Criteria:** Section missing; shows "UNKNOWN"

---

### TC-188 — Report contains SRA data for each milestone
**Steps:**
1. Open report; find Schedule Risk Analysis section

**Pass Criteria:** 7 milestones listed; each has P50, P80, P95, and probability values  
**Fail Criteria:** Fewer than 7; missing probability values

---

### TC-189 — Report contains critical path section
**Steps:**
1. Open report; find Critical Path section

**Pass Criteria:** Section present; lists critical path tasks by name and ID  
**Fail Criteria:** Section missing; empty; no task names

---

### TC-190 — Report contains CAM response status
**Steps:**
1. Open report; find CAM Status section

**Pass Criteria:** All 5 CAMs listed; each shows responded/no-response and average percent complete  
**Fail Criteria:** Fewer than 5 CAMs; missing status

---

### TC-191 — Report contains LLM narrative
**Steps:**
1. Open report; find Executive Summary section

**Pass Criteria:** 2–3 paragraph narrative present; specific mention of at least one task or milestone  
**Fail Criteria:** Generic text; placeholder; prompt text in report

---

### TC-192 — Report path returned in cycle status
**Steps:**
1. Open `reports/cycles/{cycle_id}_status.json`
2. Check `report_path` field

**Pass Criteria:** Path is non-empty; file at that path exists  
**Fail Criteria:** Empty path; path points to non-existent file

---

### TC-193 — Multiple cycles produce separate report files
**Steps:**
1. Run two cycles
2. Check `reports/` directory

**Pass Criteria:** Two or more `.md` files; each named with its run date  
**Fail Criteria:** Only one file; second run overwrites first

---

### TC-194 — Report contains validation holds if present
**Steps:**
1. Trigger a cycle with at least one validation warning
2. Open the report

**Pass Criteria:** Validation section present when holds exist; lists each hold  
**Fail Criteria:** Validation section absent even when holds exist

---

### TC-195 — Report is valid Markdown
**Steps:**
1. Open the report in a Markdown renderer (VS Code, GitHub, etc.)

**Pass Criteria:** Report renders correctly; no broken tables; headings hierarchy correct  
**Fail Criteria:** Broken tables; unescaped characters breaking Markdown parsing

---

## SECTION 12 — NOTIFICATIONS (TC-196 to TC-205)

*Mark SKIP if Slack/SMTP credentials unavailable.*

### TC-196 — Slack notification skipped gracefully when webhook not configured
**Steps:**
1. Ensure `SLACK_WEBHOOK_URL` is empty in `.env`
2. Run a full cycle

**Pass Criteria:** Cycle completes; log shows "slack_skipped" or similar; no exception raised  
**Fail Criteria:** Cycle fails; exception about missing Slack URL

---

### TC-197 — Email notification skipped gracefully when SMTP not configured
**Steps:**
1. Ensure all `EMAIL_*` vars are empty
2. Run a full cycle

**Pass Criteria:** Cycle completes; log shows "email_skipped" or similar; no exception  
**Fail Criteria:** Cycle fails; exception about missing SMTP

---

### TC-198 — Slack webhook sends on cycle completion (if configured) [SKIP if no webhook]
**Steps:**
1. Configure `SLACK_WEBHOOK_URL`
2. Run a full cycle

**Pass Criteria:** Slack message received in the target channel within 30 seconds of cycle completion  
**Fail Criteria:** No message; error in log about Slack delivery

---

### TC-199 — Email sends on cycle completion (if configured) [SKIP if no SMTP]
**Steps:**
1. Configure all `EMAIL_*` vars
2. Run a full cycle

**Pass Criteria:** Email received at `EMAIL_TO` with subject `[IMS Agent] Schedule Cycle Complete — Health: ...`  
**Fail Criteria:** No email; wrong subject; email contains template placeholders

---

### TC-200 — Email subject includes schedule health
**Steps:**
1. Trigger a cycle; check email subject

**Pass Criteria:** Subject contains `GREEN`, `YELLOW`, or `RED`  
**Fail Criteria:** Health not in subject

---

### TC-201 — Slack message includes top risks (if configured) [SKIP if no webhook]
**Steps:**
1. Run a cycle with known top risks
2. Check Slack message body

**Pass Criteria:** Top 3 risks listed in Slack message  
**Fail Criteria:** Risks absent from message

---

### TC-202 — Slack command `/ims` responds (if configured) [SKIP if no Slack tokens]
**Steps:**
1. In Slack workspace, type `/ims What is the schedule health?`

**Pass Criteria:** Bot responds in-channel with schedule health answer within 15 seconds  
**Fail Criteria:** No response; error message; wrong answer

---

### TC-203 — Slack command: empty question shows usage hint (if configured) [SKIP if no tokens]
**Steps:**
1. Type `/ims` (no question)

**Pass Criteria:** Bot responds with usage instructions (e.g., "Usage: /ims <question>")  
**Fail Criteria:** No response; error; crash

---

### TC-204 — Slack command: question too long is rejected (if configured) [SKIP if no tokens]
**Steps:**
1. Type `/ims` followed by a 500+ character question

**Pass Criteria:** Bot responds with "question too long" or equivalent  
**Fail Criteria:** Question processed without error

---

### TC-205 — Voice briefing generated (if VOICE_BRIEFING_ENABLED=true) [SKIP if no ElevenLabs]
**Steps:**
1. Set `VOICE_BRIEFING_ENABLED=true` and provide `ELEVENLABS_API_KEY`
2. Run a full cycle

**Pass Criteria:** MP3 file created in `reports/briefings/{cycle_id}_briefing.mp3`; file size > 10KB  
**Fail Criteria:** No MP3 file; empty file; ElevenLabs error halts cycle

---

## SECTION 13 — LOGGING (TC-206 to TC-215)

### TC-206 — Log file created in LOGS_DIR
**Steps:**
1. Run `python main.py --trigger`
2. Check `logs/ims_agent.log`

**Pass Criteria:** File exists and contains log entries  
**Fail Criteria:** File not created; empty

---

### TC-207 — All cycle phases appear in log
**Steps:**
1. Run `python main.py --trigger`
2. Search log for each phase: `action=ims_parsed`, `action=cam_interview_`, `action=validation_`, `action=ims_updated`, `action=cpm_done`, `action=sra_done`, `action=synthesis_done`, `action=report_generated`, `action=cycle_complete`

**Pass Criteria:** All listed action= entries appear in log  
**Fail Criteria:** Any action missing; log is sparse

---

### TC-208 — JSON log format: all entries parse as valid JSON
**Steps:**
1. Set `LOG_FORMAT=json`; run a full trigger
2. Read `logs/ims_agent.log`; parse each line as JSON

**Pass Criteria:** Every line is valid JSON with `ts`, `level`, `logger`, `msg` keys  
**Fail Criteria:** Any line fails JSON parsing; missing keys

---

### TC-209 — Text log format: human-readable timestamps and levels
**Steps:**
1. Set `LOG_FORMAT=text`; run trigger
2. Read first 10 lines of log

**Pass Criteria:** Lines show `YYYY-MM-DD HH:MM:SS LEVEL module message` pattern  
**Fail Criteria:** JSON in text mode; no timestamps; garbled output

---

### TC-210 — DEBUG log includes LLM token counts
**Steps:**
1. Set `LOG_LEVEL=DEBUG`; run trigger
2. Search log for `tokens=`

**Pass Criteria:** Token count entries present in log (from LLM calls)  
**Fail Criteria:** No token entries even in DEBUG mode

---

### TC-211 — action=qa_direct logged for direct answers
**Steps:**
1. Ask "What is the schedule health?" via `/api/ask`
2. Search log for `action=qa_direct`

**Pass Criteria:** `action=qa_direct` entry appears with question text  
**Fail Criteria:** Missing log entry; wrong action tag

---

### TC-212 — action=qa_llm logged for LLM-routed answers
**Steps:**
1. Ask "Why is SE-03 behind?" via `/api/ask`
2. Search log for `action=qa_llm`

**Pass Criteria:** `action=qa_llm` entry appears  
**Fail Criteria:** Missing; uses wrong action tag

---

### TC-213 — action=tool_dispatch logged for each tool call
**Steps:**
1. Ask a question that requires tool use (e.g., float query)
2. Search log for `action=tool_dispatch`

**Pass Criteria:** One or more `action=tool_dispatch name=<toolname>` entries in log  
**Fail Criteria:** No tool_dispatch log entries even when tool calls happen

---

### TC-214 — action=manual_trigger_api logged when /api/trigger called
**Steps:**
1. Call `POST /api/trigger`
2. Search log for `action=manual_trigger_api`

**Pass Criteria:** Entry present  
**Fail Criteria:** Missing

---

### TC-215 — action=manual_purge logged when /api/admin/purge called
**Steps:**
1. Call `POST /api/admin/purge`
2. Search log for `action=manual_purge`

**Pass Criteria:** Entry present  
**Fail Criteria:** Missing

---

## SECTION 14 — DOCKER (TC-216 to TC-225)

*Mark SKIP if Docker not available.*

### TC-216 — Docker image builds successfully
**Steps:**
1. Run `docker build -t ims-agent:test .`

**Pass Criteria:** Build completes with exit code 0; no error layers  
**Fail Criteria:** Build fails; pip install errors; COPY errors

---

### TC-217 — Container runs as non-root user
**Steps:**
1. Run `docker run --rm ims-agent:test whoami`

**Pass Criteria:** Output is `imsagent`  
**Fail Criteria:** Output is `root`; command fails

---

### TC-218 — Health check passes inside container
**Steps:**
1. Start: `docker run -d -p 8080:8080 --env-file .env ims-agent:test`
2. Wait 20 seconds (health check start period)
3. Run `docker ps` and check health status

**Pass Criteria:** Container shows `(healthy)` in `docker ps`  
**Fail Criteria:** `(unhealthy)`; `(starting)` after 60 seconds; container exits

---

### TC-219 — Port 8080 is exposed and reachable
**Steps:**
1. Container running from TC-218
2. Run `curl http://localhost:8080/health`

**Pass Criteria:** HTTP 200 response  
**Fail Criteria:** Connection refused; timeout

---

### TC-220 — Container data volume persists across restart
**Steps:**
1. `docker compose up -d`
2. Trigger a cycle (cycle writes to `data/dashboard_state.json`)
3. `docker compose restart`
4. Check that `data/dashboard_state.json` still exists (volume preserved)

**Pass Criteria:** State file survives restart  
**Fail Criteria:** State file missing after restart

---

### TC-221 — docker-compose.yml starts and shows healthy
**Steps:**
1. Run `docker compose up -d`
2. Wait 30 seconds
3. Run `docker compose ps`

**Pass Criteria:** Service shows `running (healthy)`  
**Fail Criteria:** Exited; unhealthy; error in logs

---

### TC-222 — docker-compose.prod.yml uses `restart: unless-stopped`
**Steps:**
1. Read `docker-compose.prod.yml`
2. Find `restart` setting

**Pass Criteria:** `restart: unless-stopped`  
**Fail Criteria:** `restart: no`; missing restart policy

---

### TC-223 — Production compose sets LOG_FORMAT=json
**Steps:**
1. Read `docker-compose.prod.yml`
2. Find `LOG_FORMAT` environment variable

**Pass Criteria:** `LOG_FORMAT: json`  
**Fail Criteria:** Missing; set to `text`

---

### TC-224 — .dockerignore excludes .env and data directory
**Steps:**
1. Read `.dockerignore`
2. Confirm `.env` and `data/` are listed

**Pass Criteria:** Both `.env` and `data/` excluded from Docker context  
**Fail Criteria:** Either missing from `.dockerignore`

---

### TC-225 — Container runs CMD `python main.py --serve` by default
**Steps:**
1. Read `Dockerfile` for CMD line

**Pass Criteria:** `CMD ["python", "main.py", "--serve"]`  
**Fail Criteria:** Wrong CMD; no CMD set

---

## SECTION 15 — CONFIGURATION & EDGE CASES (TC-226 to TC-228)

### TC-226 — LLM_BASE_URL overrides Anthropic endpoint
**Steps:**
1. Set `LLM_BASE_URL=http://localhost:9999` (a non-existent endpoint)
2. Run `python main.py --trigger`

**Pass Criteria:** Cycle fails with a connection error to `localhost:9999` (confirms the env var was respected)  
**Fail Criteria:** Cycle succeeds (env var ignored; still using Anthropic cloud); cycle fails for an unrelated reason

---

### TC-227 — ANTHROPIC_MODEL env var selects the model
**Steps:**
1. Set `ANTHROPIC_MODEL=claude-haiku-4-5-20251001`
2. Run a full cycle
3. Check log for `action=llm_init model=claude-haiku-4-5-20251001`

**Pass Criteria:** Log shows the configured model name at init  
**Fail Criteria:** Log shows a different model; cycle errors because model name ignored

---

### TC-228 — SRA_ITERATIONS affects Monte Carlo precision
**Steps:**
1. Set `SRA_ITERATIONS=100` (low)
2. Run a full cycle; note P50 date for PDR
3. Set `SRA_ITERATIONS=10000` (high); run again
4. Compare P50 variance between runs

**Pass Criteria:** Higher iterations produce a more stable P50 value (less run-to-run variance); both cycles complete successfully  
**Fail Criteria:** Both produce identical results (iterations ignored); either cycle fails

---

---

# RUN HISTORY

*Instructions for AI testers: To record a run, copy the BLANK RUN TEMPLATE below in its entirety, paste it after the last run entry, fill in every field, and save. Do not modify the test cases above this line. Each run must include the metadata header, a complete result table, and a summary.*

---

## BLANK RUN TEMPLATE

```
---

## RUN N — YYYY-MM-DD

**Run number:** N  
**Date:** YYYY-MM-DD  
**Start time:** HH:MM UTC  
**End time:** HH:MM UTC  
**Tester:** [name or "Claude claude-sonnet-4-6" + session ID]  
**Commit / branch:** [git rev-parse --short HEAD]  
**Python version:** [e.g., 3.13.3]  
**OS:** [e.g., Windows 11 22H2]  
**Auth config:** [dev-mode / single-key / two-key-RBAC]  
**DASHBOARD_API_KEY set:** [yes / no]  
**DASHBOARD_ADMIN_KEY set:** [yes / no]  
**Docker available:** [yes / no]  
**Slack configured:** [yes / no]  
**SMTP configured:** [yes / no]  
**ElevenLabs configured:** [yes / no]  
**Notes:** [anything unusual about this run's environment]  

### Results

| TC     | Test Name                                                       | Result | Notes |
|--------|-----------------------------------------------------------------|--------|-------|
| TC-001 | Python version and virtual environment                          |        |       |
| TC-002 | All dependencies installed                                      |        |       |
| TC-003 | Sample IMS file present and parseable                           |        |       |
| TC-004 | Environment variables load correctly                            |        |       |
| TC-005 | Full test suite passes                                          |        |       |
| TC-006 | Logs directory created automatically                            |        |       |
| TC-007 | Reports directory created automatically                         |        |       |
| TC-008 | Data directory and snapshot created                             |        |       |
| TC-009 | Dashboard state file written after cycle                        |        |       |
| TC-010 | Cycle history file written and contains at least one entry      |        |       |
| TC-011 | --trigger mode: completes and exits                             |        |       |
| TC-012 | --trigger mode: prints report path to stdout                    |        |       |
| TC-013 | --trigger with custom IMS file path                             |        |       |
| TC-014 | --trigger with nonexistent IMS file                             |        |       |
| TC-015 | --serve mode: server starts and accepts connections             |        |       |
| TC-016 | --serve mode: dashboard HTML loads at root                      |        |       |
| TC-017 | --schedule mode: starts and shows next run time                 |        |       |
| TC-018 | Default mode (no flags): runs Phase 1 pipeline and exits        |        |       |
| TC-019 | Log output in text format (default)                             |        |       |
| TC-020 | Log output in JSON format                                       |        |       |
| TC-021 | LOG_LEVEL=DEBUG produces verbose output                         |        |       |
| TC-022 | LOG_LEVEL=WARNING suppresses INFO messages                      |        |       |
| TC-023 | Cycle lock prevents duplicate concurrent cycles                 |        |       |
| TC-024 | --trigger duplicate prevention                                  |        |       |
| TC-025 | Cycle ID format is UTC timestamp                                |        |       |
| TC-026 | All 7 phases appear in cycle status file                        |        |       |
| TC-027 | Cycle status JSON has all required fields                       |        |       |
| TC-028 | CAM counts are correct                                          |        |       |
| TC-029 | IMS file is snapshotted before updates                          |        |       |
| TC-030 | IMS file is updated with CAM inputs                             |        |       |
| TC-031 | Critical path is calculated                                     |        |       |
| TC-032 | SRA milestones are generated                                    |        |       |
| TC-033 | LLM synthesis produces schedule health                          |        |       |
| TC-034 | LLM synthesis produces narrative                                |        |       |
| TC-035 | LLM synthesis produces top_risks                                |        |       |
| TC-036 | LLM synthesis produces recommended_actions                      |        |       |
| TC-037 | Report file is created with correct naming                      |        |       |
| TC-038 | Report contains all major sections                              |        |       |
| TC-039 | Metrics incremented after successful cycle                      |        |       |
| TC-040 | Metrics increment on failure                                    |        |       |
| TC-041 | Cycle history capped at 52 entries (rolling)                    |        |       |
| TC-042 | Validation holds logged but do not block cycle                  |        |       |
| TC-043 | Purge runs after every cycle                                    |        |       |
| TC-044 | Failed cycle still saves status file                            |        |       |
| TC-045 | last_cycle_duration_seconds is reasonable                       |        |       |
| TC-046 | Page title displays correctly                                   |        |       |
| TC-047 | Auto-refresh countdown timer visible and counting               |        |       |
| TC-048 | Last-updated timestamp reflects current cycle                   |        |       |
| TC-049 | Health banner: RED state color                                  |        |       |
| TC-050 | Health banner: YELLOW state color                               |        |       |
| TC-051 | Health banner: GREEN state color                                |        |       |
| TC-052 | Cycle ID displayed in header/banner                             |        |       |
| TC-053 | "Trigger Cycle Now" button visible in header                    |        |       |
| TC-054 | "Trigger Cycle Now" button fires a cycle                        |        |       |
| TC-055 | Stats card: CAMs Responded                                      |        |       |
| TC-056 | Stats card: HIGH Risk Milestones count                          |        |       |
| TC-057 | Stats card: Tasks Behind with Blocker                           |        |       |
| TC-058 | Stats card: Critical Path Tasks count                           |        |       |
| TC-059 | Milestone table: all milestones rendered                        |        |       |
| TC-060 | Milestone table: risk badge colors correct                      |        |       |
| TC-061 | Milestone table: on-time % formatted correctly                  |        |       |
| TC-062 | Milestone table: empty state message                            |        |       |
| TC-063 | CAM table: responded vs not-responded indicators                |        |       |
| TC-064 | CAM table: attempt count displayed                              |        |       |
| TC-065 | Top Risks section renders text                                  |        |       |
| TC-066 | Top Risks section empty state                                   |        |       |
| TC-067 | Tasks Behind table: all columns present                         |        |       |
| TC-068 | Tasks Behind table: blocker text truncated                      |        |       |
| TC-069 | Tasks Behind table: empty state                                 |        |       |
| TC-070 | Critical Path task IDs render as chips/badges                   |        |       |
| TC-071 | Critical Path empty state                                       |        |       |
| TC-072 | Recommended Actions section renders                             |        |       |
| TC-073 | Cycle History: correct number of entries                        |        |       |
| TC-074 | Cycle History: health badge colors                              |        |       |
| TC-075 | Cycle History: CAM response rate displayed                      |        |       |
| TC-076 | Progress banner appears during active cycle                     |        |       |
| TC-077 | Progress banner disappears after cycle completes                |        |       |
| TC-078 | Page renders correctly with no state data                       |        |       |
| TC-079 | Responsive layout: 375px mobile                                 |        |       |
| TC-080 | Responsive layout: 768px tablet                                 |        |       |
| TC-081 | Chat widget visible on page                                     |        |       |
| TC-082 | All 8 example question chips visible                            |        |       |
| TC-083 | Clicking a chip sends the question                              |        |       |
| TC-084 | Direct Q&A: "Schedule health?" returns health answer            |        |       |
| TC-085 | Direct Q&A: "Top risks?" returns risks                          |        |       |
| TC-086 | Direct Q&A: "What should I focus on?" returns actions           |        |       |
| TC-087 | Direct Q&A: "Critical path tasks" returns IDs                   |        |       |
| TC-088 | LLM Q&A: complex question returns detailed answer               |        |       |
| TC-089 | LLM Q&A: float question triggers tool use                       |        |       |
| TC-090 | LLM Q&A: dependency question uses get_dependencies tool         |        |       |
| TC-091 | LLM Q&A: milestone probability returns specific value           |        |       |
| TC-092 | LLM Q&A: CAM workload question lists tasks                      |        |       |
| TC-093 | User message bubble aligned right (blue)                        |        |       |
| TC-094 | AI response bubble aligned left with citation                   |        |       |
| TC-095 | "Thinking…" indicator during processing                         |        |       |
| TC-096 | Input disabled during processing                                |        |       |
| TC-097 | Input max length 500 enforced                                   |        |       |
| TC-098 | Empty question rejected                                         |        |       |
| TC-099 | Clear chat button removes all messages                          |        |       |
| TC-100 | Chat history survives auto-refresh (sessionStorage)             |        |       |
| TC-101 | Chat scrolls to latest message                                  |        |       |
| TC-102 | Rate limit 429 shown in chat after limit exceeded               |        |       |
| TC-103 | Q&A graceful response when no state data                        |        |       |
| TC-104 | Q&A response shows source_cycle citation                        |        |       |
| TC-105 | Direct answer visually faster than LLM answer                   |        |       |
| TC-106 | GET /health returns 200 without auth                            |        |       |
| TC-107 | GET /health body fields complete                                |        |       |
| TC-108 | GET /health cycle_active reflects real state                    |        |       |
| TC-109 | GET /metrics returns 200 in dev mode                            |        |       |
| TC-110 | GET /metrics requires auth when key configured                  |        |       |
| TC-111 | GET /metrics with valid key succeeds                            |        |       |
| TC-112 | GET /api/state returns current state                            |        |       |
| TC-113 | GET /api/state returns 404 when no state                        |        |       |
| TC-114 | GET /api/history returns array with expected fields             |        |       |
| TC-115 | GET /api/history returns [] when empty                          |        |       |
| TC-116 | GET /api/status returns cycle_active                            |        |       |
| TC-117 | POST /api/trigger fires a cycle                                 |        |       |
| TC-118 | POST /api/trigger 409 when already running                      |        |       |
| TC-119 | POST /api/admin/purge returns deleted counts                    |        |       |
| TC-120 | POST /api/ask direct question returns quickly                   |        |       |
| TC-121 | POST /api/ask LLM question returns detailed answer              |        |       |
| TC-122 | POST /api/ask 400 on empty question                             |        |       |
| TC-123 | POST /api/ask 400 on question > 500 chars                       |        |       |
| TC-124 | POST /api/ask 429 on rate limit exceeded                        |        |       |
| TC-125 | All read endpoints return 401 without key (auth enabled)        |        |       |
| TC-126 | Admin endpoints 401 with read key in two-key mode               |        |       |
| TC-127 | Wrong key returns 401                                           |        |       |
| TC-128 | GET /health never requires auth                                 |        |       |
| TC-129 | Invalid JSON body on /api/ask returns 422                       |        |       |
| TC-130 | Metrics counters reset on process restart                       |        |       |
| TC-131 | Dev mode: all routes accessible without keys                    |        |       |
| TC-132 | Single-key: API key works for read routes                       |        |       |
| TC-133 | Single-key: API key works for admin routes (fallback)           |        |       |
| TC-134 | Two-key: read key covers read routes                            |        |       |
| TC-135 | Two-key: read key blocked on admin routes                       |        |       |
| TC-136 | Two-key: admin key via X-Admin-Key header                       |        |       |
| TC-137 | Two-key: admin key via X-API-Key header                         |        |       |
| TC-138 | Two-key: admin key does not grant read-route access             |        |       |
| TC-139 | Wrong admin key rejected                                        |        |       |
| TC-140 | Rate limit is per-IP not global                                 |        |       |
| TC-141 | Rate limit counter resets after 1-hour window                   |        |       |
| TC-142 | Rate limit = 0 disables limiting                                |        |       |
| TC-143 | auth_enabled flag reflects configuration                        |        |       |
| TC-144 | No key: /api/ask accessible without header                      |        |       |
| TC-145 | Key values are case-sensitive                                   |        |       |
| TC-146 | Direct: "schedule health" pattern                               |        |       |
| TC-147 | Direct: "top risks" pattern                                     |        |       |
| TC-148 | Direct: "recommended actions" pattern                           |        |       |
| TC-149 | Direct: "what should I do" pattern                              |        |       |
| TC-150 | Direct: "critical path tasks" pattern                           |        |       |
| TC-151 | Intent: critical_path detected                                  |        |       |
| TC-152 | Intent: milestone detected                                      |        |       |
| TC-153 | Intent: blocker detected                                        |        |       |
| TC-154 | Tool: get_task returns full task detail                         |        |       |
| TC-155 | Tool: search_tasks returns matching results                     |        |       |
| TC-156 | Tool: get_critical_path returns ordered CP                      |        |       |
| TC-157 | Tool: get_tasks_by_cam returns CAM-specific tasks               |        |       |
| TC-158 | Tool: get_float returns float value                             |        |       |
| TC-159 | Tool: get_dependencies returns predecessors and successors      |        |       |
| TC-160 | Tool: get_milestones returns all 7 milestones                   |        |       |
| TC-161 | Tool: get_behind_tasks returns behind-schedule tasks            |        |       |
| TC-162 | Multi-tool call in one question                                 |        |       |
| TC-163 | No state data: graceful Q&A response                            |        |       |
| TC-164 | Tool cache invalidated after cycle                              |        |       |
| TC-165 | Max tool rounds cap (5 rounds) respected                        |        |       |
| TC-166 | Purge deletes old cycle status files                            |        |       |
| TC-167 | Purge deletes old XML snapshots                                 |        |       |
| TC-168 | Purge returns correct deletion counts                           |        |       |
| TC-169 | Auto-purge runs after every cycle                               |        |       |
| TC-170 | DATA_RETENTION_DAYS=0 purges all files                          |        |       |
| TC-171 | Purge does not fail on empty directories                        |        |       |
| TC-172 | Purge does not fail when directories do not exist               |        |       |
| TC-173 | POST /api/admin/purge requires admin key                        |        |       |
| TC-174 | Data retention default is 90 days                               |        |       |
| TC-175 | Purge error does not fail the cycle                             |        |       |
| TC-176 | Backwards movement flagged                                      |        |       |
| TC-177 | Backwards movement allowed when VALIDATION_ALLOW_BACKWARDS=true |        |       |
| TC-178 | Large jump flagged as warning (not blocking)                    |        |       |
| TC-179 | Large jump threshold respects VALIDATION_MAX_JUMP_PCT           |        |       |
| TC-180 | Missing response flagged as warning                             |        |       |
| TC-181 | Milestones excluded from coverage check                         |        |       |
| TC-182 | Validation does not block cycle                                 |        |       |
| TC-183 | Validation holds persisted in status file                       |        |       |
| TC-184 | No validation errors on clean data                              |        |       |
| TC-185 | Validation failure detail format is descriptive                 |        |       |
| TC-186 | Report filename is YYYY-MM-DD format                            |        |       |
| TC-187 | Report contains schedule health with emoji                      |        |       |
| TC-188 | Report contains SRA data for each milestone                     |        |       |
| TC-189 | Report contains critical path section                           |        |       |
| TC-190 | Report contains CAM response status                             |        |       |
| TC-191 | Report contains LLM narrative                                   |        |       |
| TC-192 | Report path returned in cycle status                            |        |       |
| TC-193 | Multiple cycles produce separate report files                   |        |       |
| TC-194 | Report contains validation holds if present                     |        |       |
| TC-195 | Report is valid Markdown                                        |        |       |
| TC-196 | Slack skipped gracefully when not configured                    |        |       |
| TC-197 | Email skipped gracefully when not configured                    |        |       |
| TC-198 | Slack webhook sends on cycle completion [SKIP if no webhook]    |        |       |
| TC-199 | Email sends on cycle completion [SKIP if no SMTP]               |        |       |
| TC-200 | Email subject includes schedule health [SKIP if no SMTP]        |        |       |
| TC-201 | Slack message includes top risks [SKIP if no webhook]           |        |       |
| TC-202 | Slack /ims command responds [SKIP if no tokens]                 |        |       |
| TC-203 | Slack /ims: empty question shows usage hint [SKIP if no tokens] |        |       |
| TC-204 | Slack /ims: long question rejected [SKIP if no tokens]          |        |       |
| TC-205 | Voice briefing MP3 generated [SKIP if no ElevenLabs]            |        |       |
| TC-206 | Log file created in LOGS_DIR                                    |        |       |
| TC-207 | All cycle phases appear in log                                  |        |       |
| TC-208 | JSON log: all entries parse as valid JSON                       |        |       |
| TC-209 | Text log: human-readable format                                 |        |       |
| TC-210 | DEBUG log includes LLM token counts                             |        |       |
| TC-211 | action=qa_direct logged for direct answers                      |        |       |
| TC-212 | action=qa_llm logged for LLM-routed answers                     |        |       |
| TC-213 | action=tool_dispatch logged for each tool call                  |        |       |
| TC-214 | action=manual_trigger_api logged                                |        |       |
| TC-215 | action=manual_purge logged                                      |        |       |
| TC-216 | Docker image builds successfully [SKIP if no Docker]            |        |       |
| TC-217 | Container runs as non-root user [SKIP if no Docker]             |        |       |
| TC-218 | Health check passes inside container [SKIP if no Docker]        |        |       |
| TC-219 | Port 8080 reachable from container [SKIP if no Docker]          |        |       |
| TC-220 | Data volume persists across restart [SKIP if no Docker]         |        |       |
| TC-221 | docker-compose up shows healthy [SKIP if no Docker]             |        |       |
| TC-222 | prod compose uses restart: unless-stopped [SKIP if no Docker]   |        |       |
| TC-223 | prod compose sets LOG_FORMAT=json [SKIP if no Docker]           |        |       |
| TC-224 | .dockerignore excludes .env and data/ [SKIP if no Docker]       |        |       |
| TC-225 | Container CMD is python main.py --serve [SKIP if no Docker]     |        |       |
| TC-226 | LLM_BASE_URL overrides Anthropic endpoint                       |        |       |
| TC-227 | ANTHROPIC_MODEL env var selects the model                       |        |       |
| TC-228 | SRA_ITERATIONS affects Monte Carlo precision                    |        |       |

### Summary

| Metric | Count |
|--------|-------|
| Total TCs | 228 |
| PASS | |
| FAIL | |
| SKIP | |
| **Overall Result** | **PASS / FAIL** |

### Failed Tests — Detail

*(List each FAIL entry with TC ID, observed behavior, expected behavior, and any error message or screenshot reference.)*

| TC | Observed | Expected | Error / Notes |
|----|----------|----------|---------------|
|    |          |          |               |

### Skipped Tests — Reason

*(List each SKIP with reason.)*

| TC | Reason for Skip |
|----|-----------------|
|    |                 |

### Tester Sign-off

**Tester:** ___  
**Date:** ___  
**Overall assessment:** [Ready to ship / Ready with conditions / Not ready — N failures must be addressed]  
**Conditions (if any):** ___
```

---

*End of TEST-PROCEDURE.md — append completed run records below this line.*
