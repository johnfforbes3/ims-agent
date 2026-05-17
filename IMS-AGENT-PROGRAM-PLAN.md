# IMS Agent — Enterprise Program Plan
**Program:** Integrated Master Schedule (IMS) AI Agent  
**Version:** 1.1  
**Created:** 2026-04-25  
**Updated:** 2026-05-08  
**Status:** Phase 15 COMPLETE + PM Portal alignment fix — **771/771 non-legacy tests passing** (0 failed) + 63 Phase 15 tests + 407 legacy tests (Phase 12/12.1/14) intentionally skipped via `@pytest.mark.legacy`. Zero open low/medium TDs. Phases 7.1–7.4, 8.3–8.5, 9.2–9.6, 10, 11, 12, 12.1, 14, 15 complete. Phase 15 rebuilt the dashboard from a user-supplied design zip — React 18 + Babel Standalone single-page app with terminal/aerospace aesthetic, all third-party deps vendored locally (no CDN). Core agent code (server.py, cycle_runner, interview agent, LLM interface, all backend modules) UNCHANGED. Phase 13 (visual layout redesign) was attempted and reverted. Phase 7.5 (First Customer Pilot) awaiting customer engagement. Phase 8.1–8.2 backlog. **Next: detailed observer-mode testing with user.**  
**Owner:** John Forbes  

---

## AGENT READING INSTRUCTIONS

This document is the authoritative, single source of truth for the IMS Agent program. If you are an AI agent working on this program, you must:

1. Read this entire document before taking any action
2. Check the status of each phase and task before starting work
3. Update checkboxes as tasks are completed (`[ ]` → `[x]`)
4. Never skip a phase gate without explicit human approval
5. When in doubt, stop and ask the human operator
6. All code, configs, and artifacts must be committed to the project repository
7. Reference the acceptance criteria before marking any phase complete

---

## EXECUTIVE SUMMARY

### The Problem

Defense program planners at large aerospace and defense contractors (e.g., L3Harris) manage Integrated Master Schedules (IMS) using Microsoft Project files. The current process for maintaining, updating, and analyzing the IMS is manual, time-consuming, and error-prone:

- **Program Managers** must interrupt their planners to get answers about critical path, schedule risk, and milestone status
- **Planners** spend significant time each week exporting the Project file to Excel, distributing filtered sheets to 15-25 Cost Account Managers (CAMs), collecting responses, manually re-integrating updates, and re-running analysis
- **CAMs** receive flat spreadsheets with no context, provide bare percent-complete numbers with no explanation, and have no mechanism to flag blockers or risks proactively
- **Program Teams** receive status information days after it is collected, by which time it may already be stale
- **Schedule Risk Assessments (SRA)** using Monte Carlo simulation are run infrequently because they require manual effort — meaning teams fly blind on schedule risk between formal reviews

### The Vision

An AI agent that:
1. **Conducts voice-based status interviews** with each CAM via Microsoft Teams — asking not just for percent complete but capturing blockers, risks, and context
2. **Automatically updates the IMS** with all collected data after validation
3. **Runs critical path analysis** and SRA (Monte Carlo) automatically after every full update cycle
4. **Synthesizes intelligence** by connecting schedule data with the contextual information captured in CAM conversations
5. **Delivers multi-channel output** — a live dashboard, Slack/email alerts with structured summaries, and an optional voice briefing for the program manager

### Why This Wins

- **Not a chatbot** — it acts autonomously on a recurring schedule
- **Not a dashboard** — it gathers the data that feeds the dashboard
- **Not a reporting tool** — it understands what the numbers mean and flags what matters
- **Defensible moat** — deep integration with defense program management workflows, ITAR-aware data handling, and audit trails make this hard to replicate quickly

### Target Users

| Role | Pain Solved |
|---|---|
| Program Manager | Gets instant answers about schedule health without interrupting the planner |
| Planner | Eliminates 4-8 hours/week of manual Excel orchestration |
| Cost Account Manager (CAM) | Short structured voice conversation replaces tedious spreadsheet updates |
| Program Control | Automatic SRA and critical path analysis available after every update cycle |
| Leadership | Live dashboard and weekly voice briefing replace static slide decks |

---

## ARCHITECTURE OVERVIEW

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    IMS AGENT CORE                           │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Schedule   │  │    Voice     │  │    Analysis      │  │
│  │  Manager   │  │  Interview   │  │    Engine        │  │
│  │            │  │    Agent     │  │                  │  │
│  │ Read/write │  │              │  │  Critical Path   │  │
│  │ .mpp files │  │ Teams calls  │  │  Monte Carlo SRA │  │
│  │ Parse IMS  │  │ Capture data │  │  Risk scoring    │  │
│  └─────────────┘  └──────────────┘  └──────────────────┘  │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Output    │  │    Audit     │  │   Q&A Interface  │  │
│  │   Engine    │  │    Logger    │  │                  │  │
│  │            │  │              │  │  PM asks agent   │  │
│  │ Dashboard  │  │ Immutable    │  │  questions about │  │
│  │ Slack/email│  │ action log   │  │  the schedule    │  │
│  │ Voice brief│  │              │  │                  │  │
│  └─────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
           │                    │                    │
    ┌──────┴──────┐    ┌────────┴──────┐   ┌────────┴──────┐
    │  Microsoft  │    │  Microsoft    │   │  Slack/Email  │
    │   Project   │    │    Teams      │   │   APIs        │
    │  .mpp files │    │  Voice API    │   │               │
    └─────────────┘    └───────────────┘   └───────────────┘
```

### Data Flow

```
IMS .mpp File
    │
    ▼
Parse Tasks → Identify Status-Due Tasks → Group by CAM
    │
    ▼
Voice Interview Loop (per CAM):
  → Initiate Teams call
  → Ask: percent complete
  → If behind: ask: what is blocking you?
  → Ask: any risks to flag?
  → Capture structured data + unstructured context
    │
    ▼
Validation Layer:
  → Flag anomalies (sudden changes, impossible values)
  → Human review gate (configurable)
    │
    ▼
Schedule Update:
  → Write percent completes to .mpp file
  → Write CAM notes to task comments
    │
    ▼
Analysis Engine:
  → Critical path recalculation
  → Monte Carlo SRA (N=1000 simulations)
  → Risk scoring per milestone
    │
    ▼
Intelligence Synthesis:
  → Connect schedule data + CAM context + risk scores
  → Identify top 5 risks
  → Draft PM briefing
    │
    ▼
Output Distribution:
  → Update live dashboard
  → Send Slack/email to stakeholders
  → Generate optional voice briefing (1-2 min)
  → Log all actions to audit trail
```

### Deployment Model

- **Containerized** — Docker container(s) deployable to client Kubernetes or standalone server
- **On-premises** — runs inside client network; no data leaves the boundary
- **Least-privilege access** — agent only has access to the specific files, APIs, and systems it needs
- **ITAR-aware** — no CUI/ITAR data sent to external APIs; all LLM inference via local or on-prem model
- **Audit trail** — every action logged with actor, timestamp, before/after state

---

## PHASE OVERVIEW

| Phase | Name | Description | Duration Estimate | Status |
|---|---|---|---|---|
| **1** | Proof of Concept | Local agent reads .mpp, parses tasks, simulates CAM input, runs analysis, outputs text report | 2-3 weeks | ✅ Complete |
| **2** | Voice Interview Layer | Agent conducts real Teams voice conversations with CAMs; captures structured + unstructured data | 4-6 weeks | ✅ Complete |
| **3** | Full Automation Loop | End-to-end: scheduled trigger → interviews → update → analysis → output → dashboard | 4-6 weeks | ✅ Complete |
| **4** | Q&A Interface | PM can ask the agent natural language questions about the schedule at any time | 3-4 weeks | ✅ Complete |
| **5** | Production Hardening | Containerization, security review, ITAR compliance, deployment playbook, customer handoff | 4-6 weeks | ✅ Complete |
| **6** | Productionization | Observability, security hardening, recovery, redundancy, IMS audit trail, first customer pilot | 8-12 weeks | ✅ Code complete — pilot execution pending |
| **7.1–7.4** | TD Sprint, Security & Compliance, Platform Enhancements, EAC Date Collection | CMMC gap closure, JWT auth, Q&A cache, per-CAM dashboard, EAC date interview state | 10-14 weeks | ✅ Complete — 404 tests |
| **7.5** | First Customer Pilot Execution | 4 cycles, real CAM data, acceptance criteria | — | ⏳ Awaiting customer engagement |
| **8.3** | Advanced SRA, Bootstrap CLI, Whisper tests | Beta-PERT SRA, `--bootstrap-sessions` CLI, Whisper integration tests | — | ✅ Complete — 424 tests |
| **8.4** | Latency & Reliability + Markdown Fix | `claude-haiku-4-5` model fix, validation fix, `force=true` trigger, Listen-In dropdown, CAM simulator markdown fix | — | ✅ Complete — 445 tests |
| **8.5** | CI & Infrastructure | GitHub Actions CI pipeline (Windows, Python 3.13), Dockerfile Python 3.13 | — | ✅ Complete — 445 tests |
| **9.2** | EVM Metrics Engine | BCWS/BCWP/SPI/SV/EAC/VAC/TCPI/BEI per-program and per-CAM; `agent/evm_engine.py`; `GET /api/evm` | — | ✅ Complete — 611 tests |
| **9.3** | DCMA 14-Point Assessment | Auto-scoring all 14 DCMA schedule quality checks from MSPDI; health thresholds GREEN/YELLOW/RED; `agent/dcma_assessment.py`; `GET /api/dcma` | — | ✅ Complete — 611 tests |
| **9.4** | Variance Analysis Narratives | LLM-backed CPR Format 5 (§1 Technical Perf, §2 Schedule, §3 Cost, §4 Summary, §5 Forward Look); `agent/variance_analyst.py`; `GET /api/variance` | — | ✅ Complete — 611 tests |
| **9.5** | Executive Briefing Generator | One-click self-contained HTML brief (health banner, EVM table, DCMA gauge, milestones, CAM status, top risks); `agent/executive_briefing.py`; `GET /api/briefing` | — | ✅ Complete — 611 tests |
| **9.6** | Portfolio View | Multi-program aggregation dashboard; `agent/portfolio.py`; `GET /api/portfolio`; `POST /api/portfolio/register` | — | ✅ Complete — 611 tests |
| **10** | Full System Integration Test Suite | Relay wiring, SSE stream, API smoke, E2E cycle; 110 new integration tests; 6 bug fixes | — | ✅ Complete — 721 tests |
| **11** | Comprehensive Dashboard UI Test Suite | 289 element-by-element dashboard tests (18 test classes covering all panels, KPIs, tables, JS API paths) | — | ✅ Complete — 1010 tests |
| **8.1–8.2** | Real ACS Voice, Multi-Tenant | Real Teams/ACS voice integration, multi-program support | TBD (post-pilot) | ⏳ Backlog |

**Total estimated duration:** 37-55 weeks (9-14 months)

---

## PHASE 1 — PROOF OF CONCEPT

### Objective

Prove that the agent logic works end-to-end on a local machine with a real or sample IMS file. No external integrations. No voice. No dashboard. Just: can the agent read the schedule, understand it, simulate status input, update it, run analysis, and produce a useful output?

**Phase Gate:** A planner or PM reviews the output and says "yes, this tells me something useful and accurate about the schedule."

---

### Phase 1 Checklist

#### 1.1 — Environment Setup
- [x] Create project repository (`ims-agent`)
- [x] Set up Python 3.11+ virtual environment
- [x] Install core dependencies: `anthropic`, `pandas`, `numpy`, `python-dotenv`, `pytest`
- [x] IMS file parser: MSPDI XML via stdlib `xml.etree.ElementTree` (see docs/decisions.md ADR-001)
- [x] Create `.env.example` with all required environment variables documented
- [x] Create `README.md` with setup instructions
- [x] Verify agent can run with `python main.py` from a clean clone

#### 1.2 — IMS File Parsing
- [x] Obtain a sample .mpp file (real or synthetic — must have 50+ tasks, multiple CAMs, dependencies)
- [x] Parse .mpp file and extract: task ID, task name, start date, finish date, percent complete, predecessor dependencies, assigned CAM/resource, baseline start, baseline finish
- [x] Identify which tasks are "status-due" for the current reporting period
- [x] Group tasks by CAM (Cost Account Manager)
- [x] Export grouped task list to structured Python dict/JSON
- [x] Unit test: parsed task count matches expected; no data loss
- [x] Unit test: CAM grouping is correct; every task assigned to exactly one CAM

#### 1.3 — Simulated CAM Status Input
- [x] Build a simple CLI interface: "Simulating CAM: [Name]. Task: [Task Name]. Current: [X]%. Expected: [Y]%. Enter actual percent complete:"
- [x] Accept percent complete input per task
- [x] If percent complete is behind expected: prompt for blocker reason (free text)
- [x] If percent complete is behind expected: prompt for risk flag (yes/no; if yes, describe)
- [x] Store all inputs in structured JSON: `{task_id, cam_name, percent_complete, blocker, risk_flag, risk_description, timestamp}`
- [x] Validate inputs: percent complete 0-100; no empty required fields
- [x] Unit test: validation catches invalid inputs

#### 1.4 — Schedule Update
- [x] Write updated percent completes back to the .mpp file (or a copy of it)
- [x] Write CAM notes/blockers to task notes field
- [x] Verify the updated .mpp file opens correctly in Microsoft Project — **deferred: no MS Project license on dev machine; XML round-trip verified programmatically; manual check scheduled for Phase 5 pre-flight**
- [x] Log every write operation: `{task_id, field, old_value, new_value, timestamp}`
- [x] Unit test: written values match input values when file is re-parsed

#### 1.5 — Critical Path Analysis
- [x] Calculate the critical path from the updated schedule
- [x] Identify which tasks are on the critical path
- [x] Identify which tasks moved onto or off the critical path since last update
- [x] Calculate total float for all non-critical tasks
- [x] Flag tasks with float < 5 days as "near-critical"
- [x] Unit test: critical path result matches known expected result on sample file

#### 1.6 — Schedule Risk Assessment (SRA)
- [x] Research and select SRA approach: Python Monte Carlo from scratch (see docs/decisions.md ADR-002)
- [x] Implement or integrate Monte Carlo simulation (N=1000 minimum)
- [x] Input: task duration distributions (use ±10% of remaining duration as default if no three-point estimates available)
- [x] Output per milestone: P50 date, P80 date, P95 date, probability of hitting baseline date
- [x] Flag milestones with <50% probability of hitting baseline as HIGH RISK
- [x] Flag milestones with 50-75% probability as MEDIUM RISK
- [x] Unit test: simulation output is reproducible within expected variance

#### 1.7 — Intelligence Synthesis (LLM Layer)
- [x] Connect to LLM (Claude claude-sonnet-4-6 via Anthropic API — see docs/decisions.md ADR-003)
- [x] Build system prompt: agent persona, program context, instructions for synthesizing schedule data + CAM inputs
- [x] Pass to LLM: critical path summary, SRA results, CAM blocker/risk inputs
- [x] Receive from LLM: narrative summary of top risks, recommended PM actions, key questions to investigate
- [x] Ensure LLM never hallucinates task data — all specific numbers come from the parsed schedule, not LLM generation
- [x] Unit test: LLM output references only tasks/dates/numbers that appear in input data — **verified via Phase 4 acceptance test (20 questions, 0% hallucination rate; agent correctly refused to fabricate data on deliberate trap question)**

#### 1.8 — Phase 1 Output: Text Report
- [x] Generate a structured text/markdown report containing:
  - [x] Report date and reporting period
  - [x] Overall schedule health (green/yellow/red with rationale)
  - [x] Critical path summary (which tasks, total duration, projected finish)
  - [x] Top 5 risks (from SRA + CAM inputs combined)
  - [x] Tasks behind schedule (list with CAM name, percent behind, blocker if provided)
  - [x] Milestones at risk (with P50/P80/P95 dates)
  - [x] Recommended actions for PM
- [x] Save report to `/reports/{date}_ims_report.md`
- [x] Unit test: report contains all required sections; no missing data

#### 1.9 — Phase 1 Acceptance Test
- [x] Run full Phase 1 flow on sample .mpp file end-to-end
- [x] Have a real planner or PM review the output report
- [x] Collect feedback: Is the data accurate? Is anything missing? Is anything confusing?
- [x] Document feedback in `PHASE1-FEEDBACK.md`
- [x] Address all critical feedback before proceeding to Phase 2
- [x] **Human approval granted 2026-04-25 — proceeding to Phase 2** ✅

---

### Phase 1 Dependencies

| Dependency | Owner | Status |
|---|---|---|
| Sample .mpp file (real or synthetic) | John Forbes | ✅ Complete — ATLAS 57-task synthetic IMS (`data/sample_ims.xml`) |
| Python MPXJ bridge working on dev machine | Engineering | ✅ Complete — MSPDI XML chosen (ADR-001); no Java bridge needed |
| Anthropic API key (or local Ollama setup) | John Forbes | ✅ Complete — Anthropic API (ADR-003) |
| SRA tool decision (build vs integrate) | John Forbes + Engineering | ✅ Complete — Python Monte Carlo built from scratch (ADR-002) |

### Phase 1 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| .mpp parsing library doesn't work reliably | Medium | High | Test early; fall back to Project XML export if needed |
| SRA from scratch takes too long | Medium | Medium | Use simplified ±10% distribution first; improve later |
| LLM hallucinates schedule data | Medium | High | Strict prompt engineering; all numbers injected, not generated |

---

## PHASE 2 — VOICE INTERVIEW LAYER

### Objective

Replace the simulated CLI input with real voice conversations via Microsoft Teams. The agent calls each CAM, conducts a structured but conversational interview, and captures the same structured data + rich unstructured context that would have been entered manually.

**Phase Gate:** Agent successfully conducts a real voice interview with a real CAM and captures accurate, usable data. The planner confirms the data quality matches or exceeds what they'd get from the Excel spreadsheet process.

---

### Phase 2 Checklist

#### 2.1 — Teams Integration Research
- [x] Research Microsoft Teams voice calling API options: Teams Bot Framework, Azure Communication Services, Power Automate
- [x] Evaluate: can the agent initiate outbound calls? What are the authentication requirements?
- [x] Evaluate: can the agent conduct real-time voice conversations (speech-to-text + text-to-speech)?
- [x] Document chosen approach and rationale in `docs/teams-integration-decision.md` — ADR-004 (ACS), ADR-005 (ElevenLabs TTS), ADR-006 (Whisper STT)
- [x] Obtain necessary API credentials — M365 Business Basic trial provisioned 2026-04-25 (tenant: intelligenceexpanse.onmicrosoft.com; expires 2026-05-25)
- [x] Build connector stub: `agent/voice/teams_connector.py` (`TeamsACSConnector`) — raises `NotImplementedError` pending full ACS implementation (TD-011); real call flow blocked on ACS subscription
- [x] Unit test: connector interface validated; real call integration test deferred to Phase 5

#### 2.2 — Speech-to-Text Pipeline
- [x] Select STT engine: Whisper (local) selected — ADR-006; `MockSTTEngine` for simulation
- [x] Implement STT abstraction: `agent/voice/stt_engine.py` (`WhisperSTTEngine`, `MockSTTEngine`)
- [x] Handle confidence scoring: log-probability confidence flag implemented in `WhisperSTTEngine`
- [x] Unit test: `MockSTTEngine` tested; `WhisperSTTEngine` real-audio integration test deferred (TD-010 — whisper package optional)

#### 2.3 — Text-to-Speech Pipeline
- [x] Select TTS engine: ElevenLabs selected for quality; Azure TTS as fallback — ADR-005
- [x] Implement TTS abstraction: `agent/voice/tts_engine.py` (`ElevenLabsTTSEngine`, `AzureTTSEngine`, `MockTTSEngine`)
- [x] Interview prompts built into `InterviewAgent` state machine
- [x] Unit test: `MockTTSEngine` tested; real TTS engines integration-tested manually

#### 2.4 — Interview Agent Logic
- [x] Build conversation state machine: `agent/voice/interview_agent.py` — greeting → task loop (TASK → BLOCKER → RISK → RISK_DESC → CONFIRM) → closing
- [x] Per task: ask percent complete → if behind, ask blocker → ask risk flag → confirm and move to next task
- [x] Handle: "I don't know" (flag no_response), corrections (CONFIRM re-ask loop), off-script responses (regex extraction)
- [x] Timeout handling: configurable response timeout with retry; after max attempts, mark as no_response
- [x] CAM-specific context injection: tasks pre-loaded per CAM before interview starts
- [x] Unit test: state machine paths covered (TD-004 CONFIRM loop bug fixed in Phase 3 sprint 1)

#### 2.5 — Data Extraction from Conversation
- [x] After each CAM call, transcript passed to LLM for structured data extraction (`agent/llm_interface.py`)
- [x] Extract: percent complete per task, blocker description, risk flag, risk description
- [x] LLM returns structured JSON matching Phase 1 format
- [x] Validate extracted data: validation layer in Phase 3 (`agent/validation.py`)
- [x] Extraction failures flagged as `no_response` in cycle state; logged for review
- [x] Unit test: extraction accuracy verified against simulated CAM transcripts

#### 2.6 — CAM Communication Management
- [x] Build CAM directory: `agent/cam_directory.py` — name, Teams ID, email, phone, timezone, business hours
- [x] Build scheduling logic: `can_call_now()` checks business hours (TD-002: uses local time, not CAM timezone — deferred)
- [x] Build retry logic: configurable retry count and delay; escalation after max retries
- [x] Build status tracking: call history per CAM per cycle; `should_retry()` and `should_escalate()` methods
- [x] Unit test: scheduling, retry, and escalation logic covered

#### 2.7 — Phase 2 Acceptance Test
- [x] Conduct interviews with 5 CAMs using ATLAS synthetic program data (simulator-based; real Teams calls deferred to Phase 5)
- [x] 50/50 tasks captured (100% completion rate); blockers and risks extracted correctly
- [x] Cross-functional risk synthesis working: RF specs dependency chain correctly identified across SE and HW CAMs
- [x] Document results in `PHASE2-FEEDBACK.md`
- [x] **Human approval granted 2026-04-25 — proceeding to Phase 3** ✅
- [ ] Real voice interviews with live CAM data — **deferred to Phase 5** (requires Azure ACS + Teams admin; see TD-011)

---

### Phase 2 Dependencies

| Dependency | Owner | Status |
|---|---|---|
| Microsoft Teams admin access for bot registration | Client IT / John Forbes | ⏳ Deferred to Phase 5 — M365 trial provisioned (expires 2026-05-25); full ACS integration pending |
| Azure subscription for Cognitive Services | John Forbes | ⏳ Deferred to Phase 5 — trial active; Whisper (local) used for Phase 2 |
| 3+ willing CAMs for acceptance test | John Forbes | ✅ Complete (simulator) — real CAM test deferred to Phase 5 |
| Real .mpp file with active program data for test | John Forbes | ✅ Complete — ATLAS synthetic IMS used; real file deferred to Phase 5 |

### Phase 2 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Teams bot API restrictions block outbound calls | High | High | Research thoroughly before committing; have email fallback ready |
| CAMs resist voice interviews vs spreadsheet habit | Medium | Medium | Keep calls short (<5 min); demonstrate time savings |
| STT accuracy poor on defense jargon | Medium | Medium | Fine-tune or build custom vocabulary; always show transcript to CAM for confirmation |
| Client IT blocks Teams bot registration | Medium | High | Engage IT early; document security posture of bot |

---

## PHASE 3 — FULL AUTOMATION LOOP

### Objective

The agent runs on a schedule without human initiation. The full cycle — trigger, interview all CAMs, update the schedule, run analysis, synthesize intelligence, and distribute output — happens automatically every reporting period.

**Phase Gate:** Agent completes one full unattended cycle end-to-end with no human intervention. Output is reviewed and approved by a real program manager.

---

### Phase 3 Checklist

#### 3.1 — Scheduler and Trigger System
- [x] Implement cron-based scheduler: configurable reporting period (weekly, biweekly, monthly)
- [x] Build trigger logic: at start of reporting period, automatically initiate the full cycle
- [x] Build status tracking for the full cycle: initiated, interviewing, updating, analyzing, distributing, complete
- [x] Implement cycle locking: prevent duplicate cycles from running simultaneously
- [x] Build admin override: human can manually trigger a cycle, pause a running cycle, or cancel
- [x] Unit test: scheduler fires at correct times; cycle locking works

#### 3.2 — CAM Interview Orchestration
- [x] Call all CAMs in parallel (configurable: sequential vs parallel with max concurrent calls)
- [x] Handle partial completion: if some CAMs are unreachable, proceed with available data; flag missing inputs
- [x] Build completion threshold: require X% of CAMs to respond before proceeding to update (configurable, default 80%)
- [x] If threshold not met: send escalation alert to planner before proceeding
- [x] Log every call attempt and outcome

#### 3.3 — Automated Schedule Update with Validation
- [x] After all CAM data collected: run validation pass before writing to schedule
- [x] Validation rules: no task can go backwards (percent complete can't decrease without explanation), no task can jump >50% in one period without explanation, all tasks in a CAM's scope must have a response
- [x] Flag validation failures for human review: hold update until human approves or overrides
- [x] Write updates to a STAGING copy of the .mpp file first
- [x] Diff staging vs previous: show what changed before committing
- [x] Commit final updates to the authoritative .mpp file only after validation passes
- [x] Version the .mpp file: save timestamped copy before every update
- [x] Unit test: validation catches all defined anomaly types

#### 3.4 — Automated Analysis Pipeline
- [x] After schedule update: automatically trigger critical path analysis
- [x] After critical path: automatically trigger SRA (Monte Carlo)
- [x] After SRA: automatically trigger intelligence synthesis (LLM layer)
- [x] Total analysis pipeline should complete within 10 minutes of schedule update
- [x] If analysis fails: alert planner; do not distribute output until resolved

#### 3.5 — Dashboard
- [x] Select dashboard technology: options are (a) simple HTML/JS served locally, (b) Grafana, (c) custom React app
- [x] Build dashboard showing:
  - [x] Schedule health indicator (green/yellow/red) with last-updated timestamp
  - [x] Critical path visualization (Gantt-style or list)
  - [x] Milestone risk table (milestone name, baseline date, P50/P80/P95 dates, risk level)
  - [x] Top 5 risks (with source: SRA or CAM input)
  - [x] Tasks behind schedule (table with CAM, percent behind, blocker)
  - [x] CAM response status (who responded, who didn't, when)
  - [x] Historical trend: schedule health over last N cycles
- [x] Dashboard auto-refreshes after each cycle completes
- [x] Dashboard is read-only for all users except admin

#### 3.6 — Slack/Email Output
- [x] Build Slack integration: post structured summary to designated channel after each cycle
- [x] Slack message format: overall health, top 3 risks, any milestones at risk, link to full dashboard
- [x] Build email integration: send same summary to stakeholder distribution list
- [x] Email format: concise, mobile-readable, key metrics in first 3 sentences, full details in attached report
- [x] Both Slack and email: include link to live dashboard

#### 3.7 — Voice Briefing (Optional)
- [x] After synthesis: LLM generates 1-2 minute voice briefing script for PM
- [x] TTS converts script to audio file
- [x] Audio file attached to email / linked in Slack message
- [x] Briefing covers: overall health, biggest risks, recommended actions

#### 3.8 — Phase 3 Acceptance Test
- [x] Run 3 consecutive automated cycles with no human intervention
- [x] Each cycle reviewed by a real PM for accuracy and usefulness
- [x] Measure: total cycle time from trigger to output distribution — **avg 7m 59s ✅**
- [x] Measure: data accuracy vs manual process baseline
- [x] Document results in `PHASE3-FEEDBACK.md`
- [x] **Human approval granted 2026-04-26 — proceeding to Phase 4** ✅

---

### Phase 3 Dependencies

| Dependency | Owner | Status |
|---|---|---|
| Phase 2 complete and stable | Engineering | ✅ Complete — Phase 2 approved 2026-04-25 |
| Slack workspace and bot token | Client / John Forbes | ✅ Complete — SLACK_BOT_TOKEN + SLACK_APP_TOKEN configured; Socket Mode |
| Email SMTP credentials | Client IT | ✅ Complete — SMTP configured in `.env` |
| Dashboard hosting decision | John Forbes | ✅ Complete — FastAPI on localhost:8080 (Phase 5 will containerize) |

### Phase 3 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Validation logic too strict (blocks valid updates) | Medium | Medium | Make all thresholds configurable; start permissive, tighten over time |
| Dashboard performance with large programs (500+ tasks) | Low | Medium | Paginate; lazy load; test with large files early |
| Cycle takes too long (CAMs don't answer promptly) | High | Medium | Make completion threshold configurable; allow partial cycles |

---

## PHASE 4 — Q&A INTERFACE

### Objective

The PM (and other authorized users) can ask the agent natural language questions about the schedule at any time — not just after a status cycle. The agent answers using the latest schedule data, CAM context, and analysis results.

**Phase Gate:** PM asks 20 real questions and receives accurate, useful answers. Zero hallucinated task data or dates.

---

### Phase 4 Checklist

#### 4.1 — Q&A Interface Build
- [x] Build chat interface — web chat widget on dashboard + Slack slash command `/ims`
- [x] Implement authentication: API key required on all `/api/*` routes (`DASHBOARD_API_KEY`); two-key RBAC model implemented in Phase 5 (5.2)
- [x] Build rate limiting: `QA_RATE_LIMIT_PER_HOUR` per-IP rolling window on `POST /api/ask`; HTTP 429 on excess — implemented in Phase 5 (5.2)

#### 4.2 — Schedule Context Retrieval
- [x] Load current schedule state (tasks, SRA, CAM inputs, synthesis) as retrieval source
- [x] Intent detection routes each query to the relevant context slice (no irrelevant data injected)
- [x] LLM answers using only retrieved context with strict grounding instructions
- [x] Every answer includes source citation (cycle ID)
- [x] Context automatically uses latest dashboard state after every cycle

#### 4.3 — Query Types Supported
- [x] "What is the current critical path?" → direct answer from state (no LLM call)
- [x] "What is the probability of hitting [milestone] on [date]?" → SRA context + LLM
- [x] "What is [CAM name] behind on?" → CAM status + tasks_behind context + LLM
- [x] "What are the top risks right now?" → direct answer from synthesis
- [x] "What changed since last cycle?" → cycle history diff context + LLM
- [x] "Show me all tasks with float less than 10 days" → tasks_behind context + LLM
- [x] "Why is [task name] behind?" → blocker context + LLM
- [x] "What should I focus on this week?" → direct answer from recommended_actions
- [x] Slack slash command: `/ims <question>` via Socket Mode (no public URL)

#### 4.5 — IMS Schedule Tool (Direct Q&A Against Raw Schedule Data)

**Problem:** The current Q&A engine answers from the synthesized dashboard state (health, risks, narrative, SRA results). It cannot answer questions that require the raw IMS data — task names, dependencies, predecessor/successor relationships, float values, baseline vs. actual dates, or resource assignments. Questions like "What are the successors of SE-03?" or "What is the total float on HW-02?" return "data not available."

**Solution:** Give the Q&A engine a set of callable tools (function calling via the Anthropic API tool_use feature) that query the live IMS XML file directly. The agent decides which tool(s) to invoke to answer the question, then synthesizes a grounded answer from the tool results.

**Tools to implement:**

| Tool | Description |
|------|-------------|
| `get_task(task_id)` | Return full task record: name, CAM, dates, percent complete, baseline, float, dependencies |
| `search_tasks(query)` | Fuzzy-search tasks by name or CAM name; return matching task list |
| `get_critical_path()` | Return ordered critical path with task names, dates, and float |
| `get_tasks_by_cam(cam_name)` | Return all tasks owned by a CAM with their current status |
| `get_float(task_id)` | Return total float and free float for a specific task |
| `get_dependencies(task_id)` | Return predecessor and successor task IDs and names |
| `get_milestones()` | Return all milestone tasks with baseline/forecast dates |
| `get_behind_tasks(threshold_pct)` | Return tasks behind expected progress by more than threshold |

**Integration points:**
- `agent/qa/ims_tools.py` — tool definitions + handlers (calls `IMSFileHandler.parse()`)
- `agent/qa/qa_engine.py` — extend `ask()` to use Anthropic tool_use when IMS-specific data is needed
- The agent auto-selects: dashboard state for synthesis/health/risks, IMS tools for raw schedule queries
- Dashboard chat and Slack `/ims` command both benefit automatically

**Acceptance criteria:**
- [x] "What is the float on task SE-03?" returns the correct calculated float value
- [x] "What are the successors of HW-01?" returns the correct dependency chain
- [x] "Show me all tasks with less than 5 days of float" returns a filtered task list
- [x] "What is Bob Martinez's schedule baseline vs. actuals?" returns a per-task comparison
- [x] Tool calls are logged; answers cite which tool provided the data
- [x] Hallucination rate remains 0% (tools return structured data, not LLM-generated values)

**Implementation completed 2026-04-26:**
- `agent/qa/ims_tools.py` — 8 tool handlers + Anthropic tool_use JSON schemas + `call_tool()` dispatcher
- `agent/llm_interface.py` — `ask_with_tools()` agentic loop (up to 5 rounds, capped)
- `agent/qa/qa_engine.py` — `ask()` now uses `ask_with_tools()` with full TOOL_SCHEMAS for all LLM-routed questions
- `tests/test_ims_tools.py` — 41 new tests covering all handlers, dispatcher, schemas, loop, and QAEngine integration
- Total test count: 205 (all passing)

#### 4.4 — Phase 4 Acceptance Test
- [x] PM asks 20 real questions using live program data
- [x] Evaluate: accuracy (data correct?), usefulness (answer actionable?), hallucination rate — **0% ✅**
- [x] Document results in `PHASE4-FEEDBACK.md`
- [x] **Human approval granted 2026-04-26 — proceeding to Phase 5** ✅

---

## PHASE 5 — PRODUCTION HARDENING

### Objective

The agent is ready to deploy at a real client. It is containerized, secured, documented, and compliant with defense contractor data handling requirements.

**Phase Gate:** A security-conscious senior engineer who did not build the system reviews it and signs off. A deployment playbook exists and has been tested by someone other than the builder.

---

### Phase 5 Checklist

#### 5.1 — Containerization
- [x] Dockerfile for agent core (Python FastAPI backend) — `python:3.11-slim`, non-root user, health check
- [x] Dockerfile for dashboard (if separate) — dashboard is part of the same container
- [x] `docker-compose.yml` for local development — bind-mount volumes for data/reports/logs
- [x] `docker-compose.prod.yml` for production deployment — named volumes, `unless-stopped`, resource limits
- [x] All secrets passed via environment variables (never hardcoded) — `.env` excluded from image via `.dockerignore`
- [x] Container runs as non-root user — `imsagent` uid 1001
- [x] Health check endpoints implemented — `GET /health` (unauthenticated)
- [x] Container image size minimized — `python:3.11-slim` base; pip cache cleared

#### 5.2 — Security Review
- [x] All API credentials stored in environment variables or secrets manager (never in code or config files)
- [x] All data in transit encrypted (HTTPS/TLS) — documented in SECURITY.md; enforced at reverse proxy layer (nginx/Caddy)
- [ ] All data at rest encrypted — deferred: no database yet; file-system encryption at host level recommended (Phase 5 follow-on)
- [x] Audit log is append-only — application only appends to log files; restrict OS write access in production
- [x] RBAC implemented — two-key model: `DASHBOARD_API_KEY` for read routes, `DASHBOARD_ADMIN_KEY` for write/admin routes (`/api/trigger`, `/api/admin/purge`); backward-compatible single-key fallback when admin key is not set
- [x] Input validation on all user-facing interfaces — `/api/ask` max 500 chars, non-empty; IMS XML parsed safely (no XXE)
- [x] LLM prompts reviewed for prompt injection vulnerabilities — documented in SECURITY.md; system prompt grounding limits blast radius
- [x] Dependency vulnerability scan — `pip-audit` run 2026-04-26; 0 runtime CVEs; pip CVE-2026-3219 (no fix available, no runtime impact); pip upgraded to 26.0.1
- [x] Network policy: outbound allowlist documented in SECURITY.md (Anthropic API, ElevenLabs, Slack, SMTP)

#### 5.3 — ITAR/CUI Compliance
- [ ] All LLM inference uses on-premises or air-gapped model — **deferred**: using Anthropic API (non-ITAR dev data only); swap path implemented via `LLM_BASE_URL` env var (single env var change routes all calls to local Ollama-compatible endpoint); documented in SECURITY.md and CONFIGURATION.md
- [x] Document data classification policy — documented in SECURITY.md (data types, classification, storage, transmission)
- [ ] Confirm: no ITAR-controlled technical data transmitted outside client network — **not yet confirmed**: requires client security officer review; depends on on-prem LLM swap
- [x] Data retention policy — `DATA_RETENTION_DAYS` env var (default 90); `CycleRunner.purge_old_data()` deletes cycle status JSONs and IMS snapshots older than the window; runs automatically at end of every cycle (Open Question #7 closed)
- [x] Data deletion capability — `POST /api/admin/purge` endpoint (admin key required) triggers immediate purge of all data outside the retention window

#### 5.4 — Observability
- [x] Structured logging: every agent action logged with `action=` prefix, timestamp, logger name
- [x] Log levels: DEBUG, INFO, WARNING, ERROR — configurable via `LOG_LEVEL` env var
- [x] Log output: configurable — stdout + file; `LOG_FORMAT=json` for log aggregators (Datadog, ELK, CloudWatch)
- [x] Key patterns documented in OPERATIONS.md — cycle start/complete/failed, validation holds, tool calls, LLM calls
- [x] Metrics endpoint — `GET /metrics` returns JSON snapshot of all in-memory counters (`cycles_completed`, `cycles_failed`, `qa_queries_total`, `qa_queries_direct`, `qa_queries_llm`, `last_cycle_id`, `last_cycle_duration_seconds`); requires API key auth; Prometheus-format export deferred to follow-on
- [x] Alerting: Slack + email notifications on cycle complete/fail; admin can monitor via `/health` endpoint

#### 5.5 — Documentation
- [x] `README.md` — complete setup and quick start guide
- [x] `DEPLOYMENT.md` — step-by-step production deployment guide
- [x] `OPERATIONS.md` — monitoring, troubleshooting, backup/restore, common issues
- [x] `SECURITY.md` — security architecture, data classification, ITAR posture, input validation, dependency audit
- [x] `API.md` — all endpoints documented with request/response examples and response times
- [x] `CONFIGURATION.md` — all 40+ variables with defaults, required/optional, descriptions
- [x] `CHANGELOG.md` — version history by phase

#### 5.6 — Deployment Playbook Test
- [ ] Have someone who did not build the system follow `DEPLOYMENT.md` on a clean machine
- [ ] They must complete deployment successfully without asking the builder for help
- [ ] Document any gaps or failures; fix and re-test
- [ ] Deployment must complete in under 4 hours following the playbook

#### 5.7 — Phase 5 Acceptance Test
- [x] Full end-to-end test on development environment — 255 tests passing (2026-05-03)
- [x] Security review sign-off — RBAC, rate limiting, data retention, dependency audit documented in SECURITY.md; accepted by John Forbes 2026-04-26
- [x] All documentation complete and reviewed — DEPLOYMENT.md, OPERATIONS.md, SECURITY.md, API.md, CONFIGURATION.md, CHANGELOG.md, TEST_RESULTS.md
- [ ] Deployment playbook verified by independent tester — **pending** (Section 5.6)
- [ ] Full end-to-end test on production deployment (containerized, clean machine)
- [ ] **Program complete — ready for first customer deployment** 🎉

---

## PHASE 6 — PRODUCTIONIZATION

### Objective

Transform the IMS Agent from a proven development system into a hardened, observable, recoverable production service ready for deployment at a real defense contractor. Phase 5 proved the system works correctly; Phase 6 proves it stays working under real-world conditions — outages, credential rotation, growing data volumes, audit demands, and multi-program scale.

**Phase Gate:** The system has been running unattended in a production-like environment for 30 days with zero unrecovered failures, a complete audit trail, and a verified disaster recovery procedure that meets the customer's RTO/RPO requirements.

---

### Phase 6 Checklist

> **Sequencing note:** Phase 6.0 (Core Integrity) is a hard gate for all subsequent sub-phases. Shipping observability infrastructure, DR procedures, or HA deployments on top of known integrity bugs creates false confidence. Complete and verify 6.0 before beginning 6.1.

---

#### 6.0 — Core Integrity (Gate for All Phase 6 Work)

**Context:** An independent technical review of the repo (2026-05-03) identified four confirmed bugs that represent foundational integrity gaps — not cosmetic issues. Two are confirmed FAIL items in the most recent test procedure run. All four are targeted, low-scope fixes that do not require new architecture. They must land before Phase 6.1 begins.

##### 6.0.1 — Fix IMS Master Custody
**Status:** ✅ FIXED 2026-05-03 — Root cause was Windows path case mismatch; `old != actual` Path comparison evaluated `True` for the new file when `xml_to_master()` returned an upper-cased path, deleting it alongside old ones.

`_export_ims_snapshot()` in `agent/cycle_runner.py` (cleanup loop, line ~182) deletes all `.mpp` and `.xml` files from `data/ims_master/` including the newly-written file, whenever `xml_to_master()` returns a path that does not compare equal to the `new_master` path (case, symlink, or normalization difference). The folder ends up empty after every cycle. For a system whose core product promise is schedule custody, this is the most critical open bug.

- [x] Diagnose root cause: add logging to compare `actual_path` vs `new_master`; determine whether case mismatch, symlink resolution, or path separator causes the inequality on Windows
- [x] Fix cleanup logic: resolve both paths with `Path.resolve()` before comparing; add a post-cleanup assertion that `master_dir` contains exactly one file before returning
- [x] Add unit test: assert `ims_master/` contains exactly one file after `_export_ims_snapshot()` completes, even when `xml_to_master()` returns a differently-cased path
- [x] Re-run TEST_RESULTS.md §4.7; verify PASS before proceeding — verified by `TestIMSMasterCustody` (2 tests); §4.7/§7.12/§12.5 now PASS

##### 6.0.2 — Make `LLM_BASE_URL` Genuinely Independent of Anthropic Credentials
**Status:** ✅ FIXED 2026-05-03 — `LLMInterface.__init__()` now accepts `"ollama"` as a sentinel key when `LLM_BASE_URL` is set; `ANTHROPIC_API_KEY` is not required for local endpoints. `CONFIGURATION.md` and `SECURITY.md` updated.

- [x] Change `LLMInterface.__init__()`: when `LLM_BASE_URL` is set, make `ANTHROPIC_API_KEY` optional — accept a sentinel value (e.g., `"ollama"`) or skip the key check entirely; confirm the Anthropic SDK accepts an empty/dummy key when a `base_url` override is provided
- [x] Add smoke test: assert `LLMInterface()` initializes without error when `LLM_BASE_URL` is set and `ANTHROPIC_API_KEY` is unset
- [ ] Manual verification: boot the full agent with only `LLM_BASE_URL` set (local Ollama instance); confirm `--run` completes a cycle without credential errors — DEFERRED: requires Ollama installation; code path verified by unit test
- [x] Update `CONFIGURATION.md` and `SECURITY.md`: explicitly state that `ANTHROPIC_API_KEY` is not required when `LLM_BASE_URL` points to a local endpoint

##### 6.0.3 — Collapse Transport Ambiguity Into One Safe Entry Path
**Status:** ✅ FIXED 2026-05-03 — `_run_trigger()` in `main.py` now reads `CALL_TRANSPORT`, logs it at INFO, and calls `sys.exit(1)` with a descriptive error if `teams_chat` transport is set in `--trigger` mode. `_run_schedule()` also logs transport explicitly.

- [x] In `main.py`, read `CALL_TRANSPORT` at startup, log it at INFO level, and validate against the launch mode: if `CALL_TRANSPORT=teams_chat` and the mode has no HTTP server (i.e., `--run` or legacy `--trigger`), emit a clear error and exit rather than running and silently failing
- [x] Add startup guard: guard implemented in `_run_trigger()` (CLI entry point); `--trigger` exits immediately with explanation and correct pattern (`POST /api/trigger`) — more user-friendly than a deep CycleRunner exception
- [x] Evaluate removing `--trigger`: retained for simulated/non-Teams transport; documented clearly in ARCHITECTURE.md §6 and `--trigger` help text
- [x] Unit test: `TestTransportStartupGuard` — asserts sys.exit(1) with teams_chat message; asserts no exit for simulated transport

##### 6.0.4 — Make Approval Application Transactional
**Status:** ✅ FIXED 2026-05-03 — `mark_approved()` moved to after all IMS writes succeed; full apply sequence wrapped in try/except; on failure the record remains `"pending"` with a retryable error response.

- [x] Move `mark_approved()` to after `apply_updates()` and `_export_ims_snapshot()` both succeed
- [x] Wrap the full apply sequence in try/except: on any exception, ensure the approval record remains in `"pending"` state so the PM can retry
- [x] Add unit test: mock `apply_updates` to raise; assert the approval store record is still retrievable with status `"pending"` after the exception
- [x] Verify that the approval endpoint returns a meaningful error response when the apply fails (not a 500) — returns `{"error": "IMS write failed for cycle ...: ... Record remains pending — correct the issue and retry the approval."}`

##### 6.0.5 — Resolve Documentation Drift
**Status:** ✅ FIXED 2026-05-03 — README.md, CONFIGURATION.md, SECURITY.md, and TEST_RESULTS.md updated to reflect current state (264 tests). `docs/STATUS.md` created as single-source-of-truth.

- [x] Fix `README.md` project structure section: "242 tests" → 264; "57-task ATLAS program IMS" → "100-task AI Agent Server Rack IMS"
- [x] Update `TEST_RESULTS.md`: Phase 6.0 run header added (2026-05-03); test count reconciled to 264/264; all Phase 6.0 FAIL items now PASS
- [x] Establish documentation accuracy rule: documented in `docs/STATUS.md` header; test count and procedure date are single-source fields that all other docs reference
- [x] Create `docs/STATUS.md` as single-line-of-truth: test count, last procedure run date, last production cycle date, open FAILs

---

#### 6.1 — Observability

##### Metrics & Dashboards
- [x] Expose Prometheus-format metrics endpoint (`GET /metrics?format=prometheus`) alongside the existing JSON endpoint — `prometheus_text()` in `agent/metrics.py`; `PlainTextResponse` with `text/plain; version=0.0.4` MIME type; tested in `TestObservability`
- [x] Define key SLIs: cycle success rate, cycle duration P50/P95, Q&A response latency P50/P95, interview completion rate, CAM response rate per cycle — all stored in `agent/metrics.py` ring buffers; computed in `snapshot()` and `prometheus_text()`; populated by `cycle_runner.py` after each cycle
- [ ] Deploy Grafana (or equivalent) with pre-built dashboards for each SLI — DEFERRED: infrastructure deployment; configure Grafana to scrape `GET /metrics?format=prometheus` in target environment
- [ ] Alert rules: cycle failure → PagerDuty/Slack within 5 minutes; cycle duration > 30 min → warning; CAM response rate < 60% → warning — DEFERRED: configure in Grafana/PagerDuty at deployment time; dead man's switch logic is in code (see below)

##### Distributed Tracing
- [ ] Instrument key code paths with OpenTelemetry spans: cycle start/end, per-CAM interview, LLM call, IMS write, SRA run — DEFERRED to 6.1 follow-on; structured `action=` log fields provide equivalent traceability today
- [ ] Export traces to a compatible backend (Jaeger, Tempo, or Datadog APM) — DEFERRED: infrastructure
- [ ] Trace IDs injected into structured log output so logs and traces correlate — DEFERRED: infrastructure; today's `action=` log key + `cycle_id` serve as a correlation token

##### Log Aggregation
- [ ] Deploy log aggregation (Datadog, ELK, or CloudWatch) in target environment — DEFERRED: infrastructure; `LOG_FORMAT=json` is already supported
- [x] Configure `LOG_FORMAT=json` and ship logs from all containers — already supported via `LOG_FORMAT=json` env var (Phase 5); all logs use structured `action=` fields
- [x] Define saved searches for operational patterns: cycle complete, validation hold, LLM failure, CAM no_response — key `action=` log values: `action=cycle_complete`, `action=cycle_failed`, `action=validation_hold`, `action=cam_no_response`, `action=master_custody_lost`, `action=approval_apply_failed`
- [ ] Log retention policy aligned with data retention policy (default 90 days) — DEFERRED: set at log aggregator level; application already purges cycle data per `DATA_RETENTION_DAYS`

##### Health & Alerting Verification
- [ ] End-to-end alert test: simulate cycle failure; verify PagerDuty/Slack fires within SLA — DEFERRED: requires deployed Grafana/PagerDuty
- [x] Dead man's switch: alert if no successful cycle within `2 × SCHEDULE_PERIOD` (configurable) — `deadman_alert` field in `GET /health`; period set by `DEADMAN_PERIOD_HOURS` override or 2 × weekly default; tested in `TestObservability.test_health_deadman_alert_when_stale_cycle`
- [x] `GET /health` extended: include last_cycle_age_seconds, sra_last_run_at, ims_last_write_at — `last_cycle_age_seconds`, `ims_last_write_at`, and `deadman_alert` added to `GET /health` response; tested in `TestObservability`

---

#### 6.2 — Security Hardening

##### Secrets Management
- [x] Replace `.env` file pattern with vault-ready secret accessor — `agent/secrets.py` provides `get_secret()` that reads from env at call time (not import time); swap `_BACKEND` to vault client with one-line change; 4 unit tests in `TestSecretsHelper`
- [ ] Implement secret rotation procedures: document rotation steps for ANTHROPIC_API_KEY, Teams bot credentials, SMTP password — DEFERRED: document in runbook when deploying to production
- [x] Rotation must not require downtime — `get_secret()` reads `os.getenv()` at call time; zero-downtime rotation verified by `test_reads_at_call_time_not_import_time`
- [x] Audit log entry generated for all admin actions — `action=audit_admin_trigger`, `action=audit_admin_purge`, `action=audit_admin_approve`, `action=audit_auth_failure`, `action=audit_rate_limit_exceeded`; 4 unit tests in `TestAuditLogging`

##### Network Security
- [ ] mTLS between all internal services — DEFERRED: infrastructure; `/internal/*` endpoints already restricted by `_require_api_key`
- [ ] Firewall rules: agent can only reach allowlisted external endpoints — DEFERRED: infrastructure; allowlist documented in SECURITY.md
- [ ] VPN or private network required for production deployment — DEFERRED: infrastructure; `/internal/*` endpoints are not in the public-facing allowlist
- [ ] Reverse proxy (nginx or Caddy) in front of FastAPI — DEFERRED: infrastructure; documented in STARTUP.md; rate limiting already in application layer

##### Compliance
- [x] CMMC Level 2 gap analysis: document controls required vs implemented — `docs/CMMC_GAP.md` created; 28 gaps identified; priority action items listed
- [x] ITAR compliance checklist: confirm on-prem LLM is deployed and `LLM_BASE_URL` is set — checklist in `SECURITY.md`; code verified in Phase 6.0.2; `docs/CMMC_GAP.md §ITAR` section
- [ ] Independent security review: third-party penetration test — DEFERRED: required before first customer CUI data; schedule at Phase 6.6 kickoff
- [x] SIEM integration: forward security events to customer SIEM — `action=audit_*` structured log events; configure SIEM to ingest `LOG_FORMAT=json` log stream; SIEM targets documented in `docs/CMMC_GAP.md`

##### Access Control
- [ ] Replace hardcoded API key model with short-lived JWTs or OAuth2 client credentials — DEFERRED to Phase 6.6 pre-pilot; gap documented in `docs/CMMC_GAP.md §IA`
- [ ] CAM identity federation via customer AAD — DEFERRED to Phase 6.6
- [ ] Admin actions require MFA-backed authentication — DEFERRED to Phase 6.6; gap documented in `docs/CMMC_GAP.md §AC`

---

#### 6.3 — Recovery

##### Backup Procedures
- [ ] IMS XML backup: after every successful cycle write, copy the updated IMS to an off-node backup location — DEFERRED: infrastructure; procedure documented in `docs/DR_RUNBOOK.md §8`
- [ ] Configuration backup: `cam_directory.json`, `cam_identity_map.json`, `.env`, Docker Compose files — DEFERRED: infrastructure; file list documented in `docs/DR_RUNBOOK.md §1`
- [ ] Cycle history backup: `cycle_history.json` backed up daily — DEFERRED: infrastructure; `data/ims_exports/` already provides per-cycle IMS versioning
- [ ] Automated backup verification: daily job validates backup integrity — DEFERRED: infrastructure; validation command documented in `docs/DR_RUNBOOK.md §8`

##### Disaster Recovery Runbook
- [x] Document RTO target — 4 hours; documented in `docs/DR_RUNBOOK.md`
- [x] Document RPO target — 1 cycle (at most one weekly update lost); documented in `docs/DR_RUNBOOK.md`
- [x] Write step-by-step DR runbook: start from a clean machine, restore from backup, verify system health — `docs/DR_RUNBOOK.md` created (8 sections; covers clean machine startup, data restore, storage full, pending approvals, LLM failure)
- [ ] Test DR runbook: have someone who did not write it execute it on a clean machine — DEFERRED: schedule at Phase 6.6 pre-pilot
- [x] DR runbook includes: secret injection, data restore, smoke test (GET /health, POST /api/trigger), handoff checklist

##### Graceful Failure Modes
- [x] LLM API failure: `_call_with_retry()` in `agent/llm_interface.py` retries up to 3× with exponential backoff (1s, 2s, 4s) on `RateLimitError`, `APIConnectionError`, and 5xx errors; fails cycle after exhaustion with `action=llm_exhausted_retries` log event; 6 unit tests in `TestLLMRetry`
- [x] Partial CAM failure: cycle proceeds with available data; `cams_responded < cams_total` logged at WARNING level; threshold (default 80%) from `CAM_THRESHOLD`; does not block distribution
- [x] IMS write failure (approval): `apply_approved()` leaves record in `"pending"` state on write failure; PM can retry via `POST /api/approvals/{id}/approve`; implemented in Phase 6.0.4
- [ ] Process crash recovery (phase checkpointing): DEFERRED — in-memory lock resets on restart; cycle must be manually re-triggered; full phase checkpointing requires a persistence layer (tracked as TD-003)

---

#### 6.4 — Redundancy

**Status:** Code complete for probe endpoints (already live in Phase 6.1). All infrastructure items DEFERRED to deployment.

##### High-Availability Deployment
- [ ] Evaluate HA requirements with the customer: single-instance with fast recovery vs active-active vs active-passive — DEFERRED to deployment
- [ ] If HA is required: deploy two instances behind a load balancer; implement distributed leader election for the scheduler (only one instance fires the cron at a time — e.g., via a distributed lock in Redis or PostgreSQL advisory lock) — DEFERRED to deployment
- [ ] `ChatInterviewManager` sessions must be persisted to shared storage (Redis or PostgreSQL) if HA is required, so a failover instance can resume in-flight interviews — DEFERRED to deployment

##### Database Backend
- [ ] Evaluate replacing JSON file state with PostgreSQL for production scale (addresses TD-003, TD-013, TD-016 simultaneously) — DEFERRED to deployment
- [ ] If PostgreSQL adopted: schema for cycle_history, dashboard_state, pending_approvals, cam_sessions; SQLAlchemy ORM; Alembic migrations — DEFERRED to deployment
- [ ] JSON file fallback retained for single-machine deployments (no external DB dependency for dev/small deployments) — DEFERRED to deployment

##### Container Orchestration
- [ ] Evaluate Kubernetes vs Docker Compose for target customer environment — DEFERRED to deployment
- [ ] If Kubernetes: Helm chart with configurable replicas, resource requests/limits, PersistentVolumeClaims for data, Secrets for credentials — DEFERRED to deployment
- [x] Liveness probe: `GET /health` returns 200 within 5 seconds — ✅ DONE (Phase 6.1, unauthenticated /health endpoint)
- [x] Readiness probe: `GET /health` returns `state_file_present: true` — ✅ DONE (Phase 6.1, state_file_present field in /health response)

---

#### 6.5 — IMS Audit Trail & Compare Files

**Status:** Core diff generation and dashboard API DONE (2026-05-03). Extended tracking and approval workflow extension DEFERRED.

##### Human-Auditable Diffs
- [x] After every cycle IMS write, generate a structured diff file: `data/ims_exports/{cycle_id}_diff.json` containing per-task changes (task_id, task_name, cam_name, field, old_value, new_value, change_reason) — ✅ DONE (`agent/ims_diff.py::generate_diff()`, integrated in `cycle_runner._run_inner()`)
- [x] Human-readable diff report: `data/ims_exports/{cycle_id}_diff.md` — Markdown table format, suitable for program review email attachment — ✅ DONE (`_write_diff_markdown()` called automatically alongside JSON)
- [x] Dashboard "What Changed" view: `GET /api/diff/{cycle_id}` returns the structured diff; dashboard renders it as a sortable table — ✅ DONE (`agent/dashboard/server.py::api_diff()`)
- [x] Diff includes metadata: cycle_id, timestamp, interviewer (always "ATLAS Scheduler"), approver (if validation-held cycle) — ✅ DONE (change_reason, cycle_id, timestamp fields in every change record)

##### Change Tracking
- [x] Every IMS field write logged with: task_id, field, old_value, new_value, cam_name, cycle_id, timestamp — ✅ DONE (persisted in `{cycle_id}_diff.json`; structured `action=ims_diff_written` log line)
- [ ] Cumulative change report: `GET /api/changes?from={cycle_id}&to={cycle_id}` returns all field changes between two cycles — DEFERRED (load multiple diff files and merge; infra task)
- [ ] Baseline drift report: quarterly comparison of current schedule vs the original baseline (percent complete, float, milestone dates) — DEFERRED

##### Approval Workflow Extension
- [x] PM can view the structured diff for any validation-held cycle before approving — ✅ DONE (`GET /api/diff/{cycle_id}` available before and after approval)
- [x] Approval captures: approver name, timestamp, optional comment — ✅ DONE (approval_store.mark_approved records approver + timestamp)
- [x] Rejection captures: reviewer name, timestamp, reason; rejected cycle data is archived (not deleted) — ✅ DONE (approval_store.mark_rejected)
- [ ] All approval/rejection events written to the append-only audit log — DEFERRED (structured action= log entries cover this; dedicated append-only file is an infra task)

---

#### 6.6 — First Customer Pilot

**Status:** Documentation complete (2026-05-03). Pilot execution pending customer engagement.

##### Onboarding Checklist
- [x] Customer IT provides: M365 tenant ID, Teams admin consent for bot, SMTP relay credentials, network allowlist for agent egress — ✅ DONE (checklist documented in `docs/ONBOARDING.md` §1)
- [x] Customer planner provides: real IMS file (MS Project XML export), CAM name list, reporting cycle (weekly/biweekly/monthly) — ✅ DONE (`docs/ONBOARDING.md` §2)
- [x] Agent team provisions: Azure Bot Service in customer tenant, CAM accounts (or federation with customer AAD), ngrok replacement with fixed FQDN — ✅ DONE (`docs/ONBOARDING.md` §3)
- [x] Security review: customer ISSO signs off on agent's network posture, data handling, and audit trail before any real data enters the system — ✅ DONE (`SECURITY.md` and `docs/CMMC_GAP.md` provide full posture; referenced in `docs/ONBOARDING.md` §4)

##### Pilot Acceptance Criteria
- [ ] 4 consecutive unattended cycles with real CAM data, zero manual interventions — PENDING pilot execution
- [ ] Planner confirms schedule data accuracy matches or exceeds the manual Excel process — PENDING pilot execution
- [ ] PM asks 10 questions via Q&A interface; all answered accurately; zero hallucinations — PENDING pilot execution
- [ ] DR runbook verified: standby engineer restores from backup within RTO on a simulated outage — PENDING pilot execution
- [ ] Audit diff reviewed by planner after each cycle; all changes traceable to CAM interviews — PENDING pilot execution

##### Feedback Capture
- [x] Weekly check-in with pilot PM and planner: what's working, what's confusing, what's missing — ✅ DONE (process defined in `PHASE6-FEEDBACK.md`)
- [x] Document feedback in `PHASE6-FEEDBACK.md` — ✅ DONE (template created at root of repo)
- [x] Triage feedback into: immediate fix (blocks adoption), Phase 6.x (near-term backlog), future phase (roadmap) — ✅ DONE (triage buckets defined in `PHASE6-FEEDBACK.md`)

---

### Phase 6 Dependencies

| Dependency | Owner | Status |
|------------|-------|--------|
| Customer IT engagement (M365, network allowlist) | John Forbes + Customer | ⏳ Not started |
| Real IMS file from customer planner | Customer | ⏳ Not started |
| Azure subscription for production Bot Service | John Forbes | ⏳ Not started |
| Secrets manager decision (Vault vs AWS vs Azure) | John Forbes | ⏳ Not started |
| Observability platform (Grafana vs Datadog vs CloudWatch) | John Forbes | ⏳ Not started |
| Independent security review / penetration test | Third party | ⏳ Not started |

### Phase 6 Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Customer IT takes > 4 weeks to enable bot / allowlist | High | High | Start IT engagement at Phase 6 kickoff; have fallback (email-based CAM input) ready |
| Real IMS file too complex for current parser (non-standard MS Project features) | Medium | High | Test with customer's actual export during onboarding; expand parser as needed |
| Real CAMs resistant to voice/chat interviews | Medium | Medium | Short (<5 min) interview; allow async (CAM replies when ready, not during a live call); demonstrate time savings vs spreadsheet |
| Customer security review identifies blockers | Medium | High | Share SECURITY.md and ARCHITECTURE.md early; pre-brief ISSO before formal review |
| On-prem LLM quality insufficient for synthesis tasks | Low | Medium | Test with Llama 3 / Mistral against sample IMS before committing; keep Anthropic API as fallback for non-ITAR programs |

---

## PHASE 7 — CONTINUOUS IMPROVEMENT, SECURITY & PILOT EXECUTION

### Objective

Resolve all open technical debt, close CMMC Level 2 security gaps, deploy the production infrastructure deferred from Phase 6, and execute the First Customer Pilot. Phase 7 converts the Phase 6 hardened codebase into a certified, auditable, continuously-running production service operating on real program data.

**Phase Gate:** Four consecutive unattended cycles on real customer data with zero manual interventions; all six HIGH-priority CMMC gaps remediated or formally accepted; planner confirms data quality meets or exceeds the manual process; PM Q&A verified at zero hallucinations; DR runbook executed successfully by an independent tester within 4-hour RTO.

> **Sequencing note:** Sub-phases 7.1 (Technical Debt) and 7.2 (Security) and 7.3 (Infrastructure) can run in parallel. Sub-phase 7.4 (Platform Enhancements) can start as soon as 7.1 is complete. Sub-phase 7.5 (Pilot Execution) is the only hard sequential dependency — it requires customer prerequisites (real IMS, M365 tenant, Azure Bot subscription) and cannot start until those are in hand. Work 7.1–7.4 while waiting on the customer.

---

### 7.1 — Technical Debt Sprint

**Duration:** 2 weeks  
**Goal:** Close the highest-value open technical debt items — all are code-only changes requiring no external infrastructure.

#### 7.1.1 — HIGH / MEDIUM Code Fixes

##### TD-001 — Deterministic Schedule Health Thresholds
**File:** `agent/cycle_runner.py`, `agent/llm_interface.py`
- [ ] Define threshold constants `HEALTH_GREEN_THRESHOLD` (default 0.75) and `HEALTH_YELLOW_THRESHOLD` (default 0.50) as env vars; document in `CONFIGURATION.md`
- [ ] Compute health deterministically in `cycle_runner._run_inner()` from SRA milestone `prob_on_baseline` values: GREEN if ≥75% of milestones have prob_on_baseline ≥ GREEN_THRESHOLD; YELLOW if ≥50%; RED otherwise
- [ ] Pass computed health label into the LLM synthesis prompt as a given — remove the "decide the health label" instruction from the system prompt in `llm_interface.py`
- [ ] Unit tests: assert GREEN/YELLOW/RED boundary transitions at correct thresholds (3 tests); assert LLM synthesis prompt contains the pre-computed label, not a directive to choose one
- [ ] Update `CONFIGURATION.md` with the two new env vars

##### TD-002 — CAM Business Hours Timezone Fix
**File:** `agent/cam_directory.py:can_call_now()`
- [ ] Replace `datetime.now().hour` with `datetime.now(ZoneInfo(cam.timezone)).hour` using stdlib `zoneinfo` (Python 3.9+; no new dependency)
- [ ] Default CAM timezone: `America/New_York`; read `timezone` field from `cam_identity_map.json` if present; fall back to default if absent or invalid
- [ ] Unit test: `can_call_now()` returns False for a CAM in `America/Los_Angeles` at 0600 UTC (10pm Pacific the prior evening); returns True at 1500 UTC (7am Pacific)

##### TD-003 — Persist CAM Call History
**File:** `agent/cam_directory.py`
- [ ] Extend `save_to_file()` to include `_call_history` dict as a `call_history` key in `data/cam_directory.json`
- [ ] Extend `load_from_ims()` / `load_from_file()` to restore `_call_history` from that key if present
- [ ] Unit test: record two call attempts, save, reload from file, assert `should_retry()` and `should_escalate()` return the same results as before the restart

##### TD-013 — Mark RESOLVED ✅
**Status:** RESOLVED by §4.2a fix (2026-05-03) — `os.replace(tmp, state_path)` with exponential-backoff retry loop replaced the prior `write_text()` call in `_update_dashboard_state()`. Dashboard state writes are now atomic on both POSIX and Windows.

##### TD-014 — Notifier Config at Import Time
**File:** `agent/notifier.py`
- [ ] Move all `os.getenv` calls for Slack/SMTP credentials inside `send_slack()` and `send_email()` function bodies (or into a `_get_config()` helper called at send time)
- [ ] Remove module-level `_SLACK_WEBHOOK`, `_EMAIL_HOST`, `_EMAIL_PORT`, `_EMAIL_USER`, `_EMAIL_PASS`, `_EMAIL_TO`, `_DASHBOARD_URL` globals
- [ ] Unit test: monkeypatch env var AFTER module import; assert notifier uses the updated value (not the import-time snapshot)

##### TD-015 — Validation Holds Not Surfaced on Dashboard
**File:** `agent/cycle_runner.py`, `agent/dashboard/templates/index.html`
- [ ] Add `"validation_holds": status.get("validation_holds", [])` to the dashboard state dict in `_update_dashboard_state()`
- [ ] Add a collapsible "⚠ Validation Alerts" section to `index.html` that renders each hold as a warning card (task name, rule, detail) when the list is non-empty; hidden when empty
- [ ] Unit test: after a cycle that triggers a backwards-movement hold, assert `dashboard_state.json` contains the `validation_holds` list with the expected entry

##### TD-021 — Dashboard Countdown Timer (REOPENED)
**File:** `agent/dashboard/templates/index.html`
- [ ] Replace `pollStatus()` + `window.location.reload()` with a `setInterval` AJAX loop that calls `GET /api/state` every 5s (active cycle) or every 60s (idle) and patches the DOM in-place
- [ ] Active cycle: update "Cycle In Progress" card fields (phase, cams_responded, tasks_captured) without a full reload
- [ ] Countdown badge: reset to the current interval (5 or 60) whenever the interval changes; badge accurately reflects next actual refresh
- [ ] Full page reload only when `cycle_active` transitions `true → false`, so final health / report data loads cleanly
- [ ] Manual test: run a cycle; verify phase and CAM count update live during the interview phase; countdown badge shows correct values

#### 7.1.2 — LOW Priority Code Polish

##### TD-005 — `_extract_percent` First-Match Bug
**File:** `agent/voice/interview_agent.py:_extract_percent()`
- [ ] Prefer numeric tokens immediately preceded by percent-context words ("is", "at", "about", "around", "currently", "approximately"); skip tokens that are part of task IDs (digits immediately following "SE-", "HW-", "SW-", "PROC-", etc.)
- [ ] Unit tests: `"SE-04 is 100%, not 4%"` → 100; `"it's about 75"` → 75; `"HW-03 is complete at 100"` → 100

##### TD-007 — Report Blocker Text Truncation
**File:** `agent/report_generator.py:_build_tasks_behind_section()`
- [ ] Truncate blocker text to first sentence or 120 characters in the table cell; append `*` footnote marker when truncated
- [ ] Add a "Blocker Details" appendix section at report end with full text for every truncated entry
- [ ] Unit test: report table cell ≤ 120 chars when blocker text is long; full text appears in appendix

##### TD-018 — Slack "Thinking…" UX
**File:** `agent/slack_command.py:_handle_ims_command()`
- [ ] Post initial message with `app.client.chat_postMessage` to get a `ts`; update in-place with `chat_update` when answer is ready
- [ ] Fallback to `response_url` with `replace_original: true` if `channel_id` is unavailable (DM context)
- [ ] Manual test: `/ims` slash command shows a single message that updates in-place, not two separate posts

##### TD-023 — Bootstrap First-Contact for New CAMs
**File:** `main.py`, `agent/voice/teams_chat_connector.py`
- [ ] Add `--bootstrap-sessions` CLI flag to `main.py`
- [ ] For each CAM in `cam_identity_map.json` with `auto_respond: true` and no entry in `cam_sessions.json`: send a Graph API email prompting them to message the bot; poll for first incoming bot message; save `conversation_id` to `cam_sessions.json`
- [ ] Update `TEAMS-SETUP.md` with the bootstrap procedure and when to run it

##### TD-024 — Eva Johnson Teams Session — **RESOLVED 2026-05-07**
- [x] Complete M365 account creation: `eva@intelligenceexpanse.onmicrosoft.com`
- [x] Run cam-responder for Eva; complete device-code auth; verify token cached in MSAL token cache
- [x] Bootstrap first 1:1 Teams contact with the bot; confirm `cam_sessions.json` entry created
- [x] Run one live `teams_chat` cycle; verify Eva's row in dashboard `cam_response_status` shows `completed` — verified in cycle `20260507T222726Z`

#### 7.1.3 — Phase 7.1 Acceptance Gate
- [ ] All HIGH/MEDIUM items above (TD-001, TD-002, TD-003, TD-014, TD-015, TD-021) checked off
- [ ] Unit test count ≥ 325 (minimum 11 new tests for the above items)
- [ ] `pytest -x -q` passes with zero failures
- [ ] `TECHNICAL-DEBT.md` updated: TD-013 marked RESOLVED; TD-001/002/003/014/015/021 marked RESOLVED with date
- [ ] `docs/STATUS.md` history row added

---

### 7.2 — Security & Compliance Hardening

**Duration:** 3-4 weeks (can run in parallel with 7.3)  
**Goal:** Close all six HIGH-priority CMMC Level 2 gaps identified in `docs/CMMC_GAP.md`. Must be complete before any real CUI or ITAR-controlled schedule data enters the system.

#### 7.2.1 — Short-Lived Token Authentication (CMMC AC.1.001, IA.3.083, IA.3.084)

**Replace static API key with JWT client credentials**
- [ ] Implement `POST /api/auth/token` endpoint: accepts `client_id` + `client_secret` from request body; returns a signed JWT (HS256) with 1-hour expiry; credentials stored in `AUTH_CLIENT_ID` / `AUTH_CLIENT_SECRET` env vars
- [ ] Implement admin-tier JWT: separate `ADMIN_CLIENT_ID` / `ADMIN_CLIENT_SECRET` env vars; admin JWT required for write/trigger/purge routes
- [ ] Replace `_require_api_key()` header check with JWT validation using `python-jose` or `PyJWT` (add to `requirements.txt`)
- [ ] Backward-compatible mode: `ENABLE_JWT=false` (default for this release) retains the existing `X-API-Key` model — no breaking change on upgrade; `ENABLE_JWT=true` activates JWT enforcement
- [ ] Unit tests `TestJWTAuth`: valid token passes (read and admin tiers); expired token rejected (401); wrong tier rejected (403); malformed token rejected (401); missing token rejected (401); minimum 6 tests
- [ ] Update `SECURITY.md` with JWT architecture; update `API.md` with `/api/auth/token` endpoint; update `CONFIGURATION.md` with new env vars

**MFA for admin routes (AC.1.002)**
- [ ] Add TOTP (RFC 6238) second-factor check for `POST /api/trigger`, `POST /api/admin/purge`, `POST /api/approvals/{id}/approve`; use stdlib `hmac` + `hashlib` (no new dependency); `ADMIN_TOTP_SECRET` env var (base32 seed)
- [ ] If `ADMIN_TOTP_SECRET` is not set, admin routes require admin JWT only (TOTP not enforced); `GET /health` includes `mfa_configured: false` warning
- [ ] Unit tests: valid TOTP (within ±1 window) passes; stale TOTP (>30s) rejected; no TOTP when secret not configured passes (with warning)

**Replay-resistant auth (IA.3.084)**
- [ ] JWTs include `jti` (JWT ID) UUID claim; maintain an in-memory LRU blocklist (max 10,000 entries, 1-hour TTL) to prevent token replay on admin actions
- [ ] `POST /api/auth/token` issues a fresh `jti` per token; on admin route use, JTI is checked against blocklist, then added to it
- [ ] Unit test: same admin JWT cannot be used twice for a protected route; read-tier JWTs are not blocklisted (performance)

#### 7.2.2 — Key Lifecycle Management (CMMC SC.3.187)
- [ ] Document API key rotation procedure in `docs/DR_RUNBOOK.md` — new §9 "Credential Rotation": step-by-step for rotating `ANTHROPIC_API_KEY`, `DASHBOARD_API_KEY`, Teams bot credentials, SMTP password; covers zero-downtime rotation using `get_secret()` hot-reload
- [ ] Implement key age alert: at startup and on each `GET /health` call, compute days since `ANTHROPIC_API_KEY` was set (`KEY_CREATED_AT` env var, ISO date string); if > 90 days, include `key_age_warning: true` and `key_age_days: N` in the `/health` response
- [ ] Unit test: `GET /health` includes `key_age_warning: true` and correct `key_age_days` when `KEY_CREATED_AT` is > 90 days ago; `key_age_warning: false` when recent

#### 7.2.3 — Incident Response Plan (CMMC IR.2.092)
- [ ] Write `docs/IR_PLAN.md`: incident classification (P1 data breach, P2 unauthorized access attempt, P3 data corruption, P4 service outage); detection sources (`action=audit_auth_failure` events, deadman alert, Slack cycle-failed notification); response procedures per severity; CSIRT contact list placeholder; post-incident review template
- [ ] Add IR plan reference link to `OPERATIONS.md §Incident Response` and `SECURITY.md §Incident Response`

#### 7.2.4 — SIEM Integration (CMMC AU.3.045)
- [ ] Add `SIEM_SYSLOG_HOST` and `SIEM_SYSLOG_PORT` env vars; if set, attach a `logging.handlers.SysLogHandler` that forwards all `action=audit_*` log events to the configured syslog endpoint at startup
- [ ] Document in `SECURITY.md §Log Integration`: target SIEM configuration; key `action=audit_*` fields to alert on; recommended saved searches
- [ ] Unit test: when `SIEM_SYSLOG_HOST` is set, a `SysLogHandler` is present in the root logger's handler list; audit log events at WARNING+ are forwarded

#### 7.2.5 — Phase 7.2 Acceptance Gate
- [ ] `docs/CMMC_GAP.md` updated: AC.1.001, AC.1.002, IA.3.083, IA.3.084, SC.3.187, IR.2.092, AU.3.045 all marked REMEDIATED (or ACCEPTED with rationale)
- [ ] `docs/IR_PLAN.md` created and reviewed by program owner
- [ ] JWT test suite ≥ 6 new tests; all existing tests still pass
- [ ] Penetration test scheduled (can remain PENDING for this gate; date must be documented in `docs/CMMC_GAP.md §Remaining Actions`)
- [ ] `docs/STATUS.md` history row added

---

### 7.3 — Infrastructure & Observability Deployment

**Duration:** 2-3 weeks (can run in parallel with 7.2)  
**Goal:** Deploy the production infrastructure items deferred from Phase 6.1, 6.3, and 6.4. These are environment-level tasks, not code changes.

#### 7.3.1 — Grafana Observability Stack
- [ ] Add Grafana service to `docker-compose.prod.yml` (or document standalone deployment); configure to scrape `GET /metrics?format=prometheus` from the agent container
- [ ] Build pre-built dashboard JSON (`docs/grafana_dashboard.json`) with panels for: cycle success rate, cycle duration P50/P95, CAM response rate per cycle, Q&A latency P50/P95, dead man's switch alert state
- [ ] Configure alert rules: cycle failure → Slack/email within 5 minutes; cycle duration > 30 min → warning; CAM response rate < 60% → warning
- [ ] Alert test: simulate a cycle failure (`POST /api/trigger` on an invalid IMS path); verify Slack alert fires within 5 minutes
- [ ] Commit `docs/grafana_dashboard.json` to repository; document setup in `OPERATIONS.md §Grafana`

#### 7.3.2 — Log Aggregation
- [ ] Deploy log aggregation in target environment (customer decision: Datadog, ELK Stack, or AWS CloudWatch)
- [ ] Configure all container log streams to ship with `LOG_FORMAT=json`
- [ ] Create saved searches / log filters for operational patterns: `action=cycle_complete`, `action=cycle_failed`, `action=validation_hold`, `action=cam_no_response`, `action=llm_exhausted_retries`, `action=audit_auth_failure`, `action=master_custody_lost`
- [ ] Log retention: align with `DATA_RETENTION_DAYS` (default 90 days) at the aggregator level
- [ ] Document aggregator configuration in `OPERATIONS.md §Log Aggregation`

#### 7.3.3 — Automated Backup
- [ ] Add `IMS_BACKUP_PATH` env var (file path, network share UNC, or S3 URI); document in `CONFIGURATION.md`
- [ ] In `cycle_runner._run_inner()`: after every successful IMS write, copy the updated IMS XML to `IMS_BACKUP_PATH/{cycle_id}_ims_backup.xml`
- [ ] Daily config backup via scheduler: tar `cam_directory.json`, `cam_identity_map.json`, `cam_sessions.json`, `.env`, Docker Compose files → `{backup_path}/config_{date}.tar.gz`
- [ ] Post-backup verification: parse the backup XML and assert valid; log `action=backup_verified` or `action=backup_failed` accordingly
- [ ] Cycle proceeds even if backup fails (log error, do not raise); a `backup_failed` event triggers a Slack/email alert via the notifier
- [ ] Unit test: after a successful mock cycle, assert backup file exists at `IMS_BACKUP_PATH` and parses without error; assert a backup failure logs the error and does not raise

#### 7.3.4 — DR Runbook Independent Test
- [ ] Identify an independent tester (someone who did not write the runbook)
- [ ] Tester executes `docs/DR_RUNBOOK.md` on a clean machine from scratch
- [ ] System must reach `GET /health → 200` + `POST /api/trigger` completing a successful cycle within the 4-hour RTO
- [ ] Document results in a new `docs/DR_RUNBOOK.md §Results` section: date, tester name, start/end times, any deviations from the documented steps
- [ ] Fix any gaps identified; re-test if material changes were required

#### 7.3.5 — Phase 7.3 Acceptance Gate
- [ ] Grafana dashboard is live and displaying real SLI data from at least one full cycle
- [ ] One alert rule verified to fire correctly on a simulated failure
- [ ] Backup automation running; backup file confirmed valid (parses as XML) after a live cycle
- [ ] DR runbook test complete; results documented; no critical gaps remaining
- [ ] `docs/STATUS.md` history row added

---

### 7.4 — Platform Enhancements

**Duration:** 4-6 weeks  
**Goal:** Deliver meaningful user-facing and pipeline improvements that increase PM/planner adoption and auditability. All items in this sub-phase are code improvements that do not require external infrastructure.

#### 7.4.1 — Dashboard Live Updates (TD-021 Extension)
- [ ] Complete TD-021 AJAX countdown fix (see 7.1.1 above)
- [ ] Add real-time per-CAM progress row during active cycle: display `Alice ✓ | Bob ⏳ | Carol ✓ | ...` as interviews complete, updating via AJAX without full reload
- [ ] "Validation Alerts" collapsible panel from TD-015 (see 7.1.1) integrated into the same AJAX state update
- [ ] Add a "What Changed" tab to the dashboard: renders `GET /api/diff/{cycle_id}` output as a sortable table; defaults to the latest completed cycle; cycle selector dropdown allows historical review
- [ ] Manual test: run a full cycle; verify CAM progress ticks live during the interview phase; "What Changed" tab populates after cycle complete

#### 7.4.2 — Cumulative Change Report (Phase 6.5 Deferred)
**File:** `agent/dashboard/server.py`, `agent/ims_diff.py`
- [ ] Implement `GET /api/changes?from={cycle_id}&to={cycle_id}` endpoint: load all `data/ims_exports/{cycle_id}_diff.json` files between the two cycle IDs (inclusive); merge by task_id + field; return per-task net change (earliest old_value → latest new_value), hop count, and list of contributing cycle IDs
- [ ] Dashboard "Change History" tab: date-range selector → calls `/api/changes` → renders merged diff table; exportable as CSV via `GET /api/changes?format=csv`
- [ ] Unit tests `TestCumulativeDiff`: merge two consecutive diff files; assert net field values correct; assert hop count = number of intermediate changes; assert correct contributing cycle IDs (minimum 4 tests)

#### 7.4.3 — Baseline Drift Report (Phase 6.5 Deferred)
**File:** `agent/dashboard/server.py`, `agent/ims_diff.py`
- [ ] Define baseline: IMS snapshot at program start, identified by `BASELINE_CYCLE_ID` env var; if not set, use the oldest snapshot in `data/ims_exports/`
- [ ] Implement `GET /api/baseline-drift` endpoint: compare current IMS task list vs baseline snapshot; report per-task slip in calendar days (finish date delta), percent complete delta, and tasks added/removed since baseline
- [ ] Dashboard "Baseline Drift" tab: table sorted by largest slip; highlight tasks > 14-day slip in amber, > 30-day in red; exportable as CSV
- [ ] Unit tests `TestBaselineDrift`: create two synthetic IMS snapshots with known date differences; assert drift report shows correct slip values and correct added/removed task lists (minimum 4 tests)

#### 7.4.4 — Q&A Context Caching (TD-016)
**File:** `agent/qa/context_builder.py`
- [ ] Cache dashboard state and cycle history in module-level variables with 30-second TTL; invalidate when `dashboard_state.json` modification time changes
- [ ] Unit test: call `load_state()` twice within TTL; assert only one file read occurs; update file; assert next call reads fresh data

#### 7.4.5 — CAM Simulator Rate Limiting (TD-009)
**File:** `agent/voice/cam_simulator.py`
- [ ] Add `SIMULATOR_CALL_DELAY_MS` env var (default 200ms); apply as `time.sleep(delay_s)` between successive `respond()` API calls within a single session
- [ ] Document in `CONFIGURATION.md`
- [ ] Unit test: mock `time.sleep`; assert it is called with the correct delay value for each turn in a multi-task session

#### 7.4.6 — Cycle Report Enhancements
**File:** `agent/report_generator.py`
- [ ] Add "IMS Diff Summary" section to each cycle report: table of first 5 field changes from `{cycle_id}_diff.md`; note total change count if > 5
- [ ] Add "Baseline Drift Alert" section when any milestone has slipped > 14 days from baseline (populate from `/api/baseline-drift` data); include milestone name, baseline date, current projected date, days slipped
- [ ] Unit test: report contains "IMS Diff Summary" section when diff file is present for the cycle; "Baseline Drift Alert" section appears when a milestone is > 14 days late

#### 7.4.7 — Phase 7.4 Acceptance Gate
- [ ] Dashboard live CAM progress confirmed working in a real cycle (no full-page reload during interview phase)
- [ ] `/api/changes` returns correct merged data across two real consecutive cycles
- [ ] `/api/baseline-drift` returns correct slip values on the ATLAS test IMS
- [ ] Cycle report contains "IMS Diff Summary" section
- [ ] Test count ≥ 14 new tests for this sub-phase
- [ ] `docs/STATUS.md` history row added

---

### 7.5 — First Customer Pilot Execution

**Duration:** 4-6 weeks (sequential; blocked on customer prerequisites)  
**Goal:** Execute the first real-world pilot on live program data with a paying customer. Validate the agent's core value proposition — does it save planner time, does it capture accurate data, does the PM trust the output?

> **This sub-phase cannot start until** all items in 7.5.1 Prerequisites are complete. Work 7.1–7.4 while waiting.

#### 7.5.1 — Prerequisites (Customer Dependencies)
- [ ] **Customer IT:** M365 tenant ID provided; Teams admin consent granted for bot app registration; SMTP relay credentials provided; network allowlist configured for agent egress (Anthropic API or on-prem LLM, Teams/Graph API, Slack, SMTP)
- [ ] **Customer planner:** Real IMS XML export (MS Project MSPDI format) provided; CAM name list with Teams account UPNs provided; reporting cycle defined (weekly/biweekly/monthly); interview window defined (day of week, time range)
- [ ] **Agent team:** Azure Bot Service provisioned in customer M365 tenant; `cam_identity_map.json` populated with real CAM names and UPNs; `cam_sessions.json` bootstrapped via `--bootstrap-sessions` after bot is live
- [ ] **Security gate:** Customer ISSO reviews `SECURITY.md` and `docs/CMMC_GAP.md`; signs off on network posture and data handling before any real schedule data enters the system
- [ ] **Smoke test:** `POST /api/trigger` in `CALL_TRANSPORT=simulated` mode on the customer's real IMS file; verify cycle completes, report is coherent, no parser errors

#### 7.5.2 — Pilot Cycle Execution
- [ ] **Cycle 1 (Supervised):** Agent team monitors all logs in real time; planner reviews cycle report same day; document any issues immediately in `PHASE6-FEEDBACK.md`
- [ ] **Cycle 2 (Semi-supervised):** Planner reviews report independently without prompt; PM uses Q&A interface for ≥5 questions; capture feedback in weekly check-in
- [ ] **Cycle 3 (Unattended):** No monitoring during execution; review output at completion only; confirm dead man's switch and alert system worked correctly
- [ ] **Cycle 4 (Acceptance):** Unattended; acceptance criteria formally evaluated at completion; sign-off required to close the pilot

#### 7.5.3 — Pilot Acceptance Criteria
- [ ] 4 consecutive unattended cycles with real CAM data, zero manual interventions required
- [ ] Planner confirms: schedule data accuracy matches or exceeds the manual Excel process; time savings are real and measurable
- [ ] PM asks ≥10 questions via Q&A interface; all answered accurately; zero hallucinated task names, dates, or percent-complete values
- [ ] DR runbook independently verified: standby engineer restores from backup within 4-hour RTO on a simulated outage
- [ ] Audit diff reviewed by planner after each cycle; every change is traceable to a specific CAM interview response
- [ ] No open P1 or P2 incidents during the pilot window

#### 7.5.4 — Phase 7.5 / Phase 7 Gate
- [ ] All 6 acceptance criteria signed off by customer planner and PM (written confirmation)
- [ ] `PHASE6-FEEDBACK.md` pilot summary section completed (wins, issues, backlog items)
- [ ] Post-pilot backlog triage: immediate fixes (blocks continued use) vs Phase 8 roadmap items; documented in `PHASE6-FEEDBACK.md §Triage`
- [ ] `docs/STATUS.md` updated: "Last production cycle" field, pilot sign-off date
- [ ] Phase 7 formally complete — program proceeds to Phase 8 based on customer and commercial priorities

---

### Phase 7 Dependencies

| Dependency | Owner | Status | Blocks |
|---|---|---|---|
| Customer IT engagement (M365, allowlist, SMTP) | John Forbes + Customer IT | ⏳ Not started | 7.5.1 |
| Real IMS XML from customer planner | Customer planner | ⏳ Not started | 7.5.1 |
| Azure Bot Service production subscription | John Forbes | ⏳ Not started | 7.5.1 |
| Secrets manager decision (Vault / AWS / Azure Key Vault) | John Forbes | ⏳ Not started | 7.2.1 |
| Observability platform decision (Grafana / Datadog / CloudWatch) | John Forbes | ⏳ Not started | 7.3.1–7.3.2 |
| Backup storage location (network share, S3, Azure Blob) | John Forbes | ⏳ Not started | 7.3.3 |
| Independent security review / penetration test | Third party | ⏳ Not started | 7.2.5 |
| DR runbook independent tester | John Forbes | ⏳ Not started | 7.3.4 |
| Customer ISSO security sign-off | Customer ISSO | ⏳ Not started | 7.5.1 |

### Phase 7 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Customer IT engagement takes > 4 weeks | High | Medium | 7.1–7.4 proceed in parallel; pilot is not on the critical path for code improvements |
| JWT implementation introduces auth regression | Medium | High | `ENABLE_JWT=false` default; full auth test suite before enabling; staged rollout |
| Real IMS too complex or non-standard for current parser | Medium | High | Smoke test on customer export in 7.5.1 before Cycle 1; expand parser if needed |
| CMMC pen test identifies a critical gap post-7.2 | Low | High | 7.2 closes all 6 HIGH-priority gaps first; pen test is verification, not discovery |
| DR runbook independent test fails (clean machine) | Medium | Medium | Gaps are likely minor (env var docs, path instructions); 4-hour RTO is generous |
| Customer CAMs resistant to chat/voice interviews | Medium | Medium | Short (<5 min) interview; async mode (reply when ready); show time savings vs Excel |

---

## PHASE 8 — ADVANCED CAPABILITIES

### Objective

Extend the IMS Agent into a multi-tenant, multi-integration platform capable of supporting real-time voice interviews via Azure ACS, ingesting schedules from Primavera P6 and Jira, and delivering ML-enhanced schedule forecasting. Phase 8 items are post-pilot roadmap — they are planned and sequenced here but do not activate until pilot feedback confirms customer demand.

**Phase Gate:** Each 8.x sub-phase has its own independent gate. There is no single gate for Phase 8 as a whole. Sub-phases activate based on pilot feedback priority and commercial commitments.

---

### 8.1 — Real Teams/ACS Voice Integration (TD-011)

**Context:** `agent/voice/teams_connector.py::TeamsACSConnector` is a documented stub that raises `NotImplementedError`. Full Tier 3 voice interviews require an Azure Communication Services subscription and real-time audio handling infrastructure.

**Phase Gate:** End-to-end live voice interview with one real CAM; all five tasks captured; transcript and structured data match what the chat interview would have produced.

- [ ] Obtain Azure ACS calling subscription; provision a calling-enabled resource
- [ ] Implement `TeamsACSConnector.__init__()`: initialise `azure.communication.callautomation.CallAutomationClient`; load `ACS_CONNECTION_STRING` env var
- [ ] Implement outbound call flow: `initiate_call(cam_teams_id)` → receive `CallConnected` event → play greeting TTS → process `SpeechRecognized` events through `InterviewAgent` state machine → play next prompt → `HangUp` on close
- [ ] Wire `WhisperSTTEngine` to real-time chunked ACS audio stream (or use ACS's built-in speech recognition if latency acceptable)
- [ ] Wire `ElevenLabsTTSEngine` or `AzureTTSEngine` to ACS TTS output; play pre-synthesized prompts to reduce latency
- [ ] Unit tests (mocked `CallAutomationClient`): validate connector state machine — `initiate_call`, receive `CallConnected`, play prompt, receive `SpeechRecognized`, advance state, `HangUp`; minimum 8 tests
- [ ] Integration test (ACS sandbox): agent calls a test PSTN number; full `InterviewAgent` state machine completes; transcript captured; structured data extracted correctly
- [ ] Update `CONFIGURATION.md` with ACS env vars; update `ARCHITECTURE.md §Voice` with Tier 3 call flow; update `TEAMS-SETUP.md` with ACS provisioning steps

---

### 8.2 — Multi-Tenant / Multi-Program Support

**Context:** Defense contractors manage dozens of programs simultaneously. The current agent is single-program (one IMS, one CAM set, one schedule). Multi-program support is the key unlock for enterprise licensing.

**Phase Gate:** Two programs running concurrently on independent schedules with separate IMS files, CAM sets, and notification targets; no data cross-contamination confirmed by test.

- [ ] Design tenant isolation model: evaluate options — (a) one agent process per program (namespace by env), (b) single shared process with program routing; document decision in `docs/decisions.md` as ADR-007
- [ ] Implement program registry: `data/programs.json` maps `program_id` → `{ims_path, cam_identity_map, cam_sessions, schedule_cron, notification_targets}`
- [ ] Multi-program scheduler: `CycleScheduler` fires a separate `CycleRunner` per program per configured cron; isolation confirmed by separate `cycle_id` namespaces
- [ ] Dashboard: program selector dropdown at top-right; all views (health, milestones, risks, Q&A) filtered to selected program
- [ ] Q&A: route question to correct program context based on user's authenticated program association (extend JWT claims with `program_id`)
- [ ] API: all `/api/*` routes accept optional `?program_id=` parameter; scoped API keys per program; cross-program access denied with 403
- [ ] Unit tests: two concurrent `CycleRunner` instances on different IMS paths do not share state; `/api/diff/{cycle_id}` returns 403 when `cycle_id` belongs to a different program

---

### 8.3 — Advanced SRA & Probabilistic Forecasting (TD-001 Extension)

**Context:** Current SRA uses ±10% uniform duration distribution for all tasks. Real programs use three-point estimates (optimistic / most likely / pessimistic) which produce materially different P80/P95 dates. This phase delivers risk accuracy that justifies SRA as a procurement differentiator.

**Phase Gate:** SRA with three-point estimates produces P80 dates within ±5% of an independently-calculated Monte Carlo on the same input data.

- [ ] Extend `IMSFileHandler.parse()` to extract three-point estimate fields from MS Project XML (`DurationVariance`, `OptimisticDuration`, `PessimisticDuration`) when present; store in `Task` dataclass as `duration_opt`, `duration_ml`, `duration_pess`
- [ ] Update `SRARunner` to use beta-PERT distribution when all three estimates are present; fall back to existing ±10% uniform distribution when they are absent
- [ ] Implement optional task-pair correlation matrix: `data/sra_correlations.json`; if present, apply Cholesky decomposition to correlated task duration samples
- [ ] Update deterministic health thresholds (from TD-001 / Phase 7.1) to use beta-PERT P50 in the GREEN/YELLOW/RED computation
- [ ] Unit tests `TestBetaPERT`: known optimistic/most-likely/pessimistic inputs produce P50/P80/P95 within analytically-expected bounds; correlation matrix shifts joint probability in the correct direction (minimum 6 tests)
- [ ] Update `API.md` to document new SRA fields in milestone responses; update `CONFIGURATION.md` with `sra_correlations.json` format

---

### 8.4 — Enterprise Schedule Integrations

**Context:** Customers outside the MS Project ecosystem use Primavera P6 (large defense programs), Jira (software programs), and various ERPs for resource planning. Each integration expands the addressable market.

#### 8.4.1 — Primavera P6 Integration
**Phase Gate:** End-to-end cycle on a P6 XML export; critical path matches P6's own output; report is indistinguishable from an MS Project-sourced run.
- [ ] Implement P6 XML ingestion in `agent/file_handler.py`: parse P6's `xer` or P6 XML schema; map P6 WBS activities → `Task` dataclass (activity ID, resource, start/finish, percent complete, predecessor links, baseline dates)
- [ ] Support P6 WBS hierarchy: summarise sub-activities into parent WBS elements for reporting
- [ ] Integration test: parse a sample P6 XML export; assert parsed task count, critical path, and float values match P6's own reports
- [ ] Document P6 setup in `CONFIGURATION.md §IMS Formats`

#### 8.4.2 — Jira Integration
**Phase Gate:** Jira-sourced cycle completes; Q&A can answer questions about Jira epics/stories; story status updated in Jira after cycle.
- [ ] Implement `agent/connectors/jira_connector.py`: pull epics and stories via Jira REST API v3; map story points and sprint velocity to percent complete; map Jira assignees to CAM names
- [ ] Bidirectional write: after cycle, update Jira story description/comment with CAM interview data (blocker, risk flag, updated percent complete)
- [ ] `JIRA_BASE_URL`, `JIRA_API_TOKEN`, `JIRA_EMAIL` env vars; document in `CONFIGURATION.md`
- [ ] Unit tests (mocked Jira API): task list parsed correctly; write-back updates correct story fields

#### 8.4.3 — WhisperSTTEngine Real-Audio Testing (TD-010)
**Phase Gate:** Integration test suite passes on a machine with `openai-whisper` installed.
- [ ] Add `@pytest.mark.integration` test suite for `WhisperSTTEngine`; auto-skip when `openai-whisper` is not installed
- [ ] Test with a short WAV file containing known phrases ("percent complete", "blocked", "risk"); assert transcript contains expected keywords
- [ ] Add `openai-whisper` and `sounddevice` to `requirements-optional.txt` with install instructions

---

### Phase 8 Dependencies

| Dependency | Owner | Status | Blocks |
|---|---|---|---|
| Azure ACS calling subscription | John Forbes | ⏳ Not started | 8.1 |
| Phase 7.5 pilot complete (confirms customer demand) | John Forbes + Customer | ⏳ Not started | 8.1, 8.2, 8.3 |
| Customer with P6-based program (validates 8.4.1) | Sales / John Forbes | ⏳ Not started | 8.4.1 |
| Customer with Jira-based program (validates 8.4.2) | Sales / John Forbes | ⏳ Not started | 8.4.2 |

### Phase 8 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ACS real-time audio latency unacceptable for CAM interviews | Medium | High | Test ACS audio round-trip early; Azure TTS pre-synthesized prompts reduce perceived latency |
| Multi-tenant isolation bug leaks data across programs | Low | Critical | Strict unit test for cross-program access before any multi-tenant deployment; default to process-per-program model |
| P6 XML schema varies across P6 versions | High | Medium | Test against multiple P6 export versions; fail gracefully with clear error message |
| Three-point estimate data not available from most customers | Medium | Medium | Uniform ±10% fallback already works; beta-PERT is an enhancement, not a dependency |

---

## APPENDIX A — TECHNOLOGY DECISIONS

| Component | Decision | Rationale | Revisit If |
|---|---|---|---|
| IMS file format | .mpp via MPXJ bridge | Most common format at L3Harris | Client uses Primavera P6 exclusively |
| LLM for air-gapped | Ollama + local model (Llama 3 or equivalent) | No CUI data leaves network | Model quality insufficient for synthesis tasks |
| LLM for non-CUI | Anthropic Claude API | Best in class for reasoning + synthesis | Cost becomes prohibitive at scale |
| Voice platform | Microsoft Teams Bot + Azure Cognitive Services | Already deployed at most defense contractors | Client doesn't use Teams |
| SRA implementation | Python Monte Carlo (custom) | No external tool dependency | Existing SRA tool has accessible API |
| Dashboard | React + FastAPI | Consistent with AIX platform stack | Simpler HTML sufficient for MVP |
| Database | PostgreSQL + pgvector | Persistent, proven, supports RAG | SQLite sufficient for single-program MVP |
| Container orchestration | Docker Compose (Phase 1-3), Kubernetes (Phase 5) | Right-sized for maturity level | Single client with existing K8s cluster |

---

## APPENDIX B — GLOSSARY

| Term | Definition |
|---|---|
| IMS | Integrated Master Schedule — the authoritative program schedule in Microsoft Project |
| CAM | Cost Account Manager — individual responsible for a subset of program tasks |
| SRA | Schedule Risk Assessment — probabilistic analysis of schedule risk using Monte Carlo simulation |
| Critical Path | The longest sequence of dependent tasks; any delay here delays the program |
| Float | The amount of time a task can slip without affecting the critical path |
| P50/P80/P95 | Probability levels from SRA: 50%/80%/95% chance of completing by that date |
| ITAR | International Traffic in Arms Regulations — export control law covering defense technical data |
| CUI | Controlled Unclassified Information — sensitive but unclassified government data |
| CMMC | Cybersecurity Maturity Model Certification — DoD cybersecurity compliance framework |
| Monte Carlo | Statistical simulation technique: run thousands of randomized scenarios to estimate outcomes |

---

## APPENDIX C — OPEN QUESTIONS

These must be resolved before or during the phase they impact.

| # | Question | Impact | Target Phase | Status |
|---|---|---|---|---|
| 1 | What SRA tool is currently used? Does it have an API or CLI interface? | Phase 1 | Phase 1 | ✅ Resolved — Built Python Monte Carlo from scratch (ADR-002); no external tool needed |
| 2 | Is Microsoft Teams the right voice platform, or do CAMs prefer phone/Zoom? | Phase 2 | Phase 2 | ❓ Open — Teams/ACS selected (ADR-004) but no real CAM feedback yet; confirm in Phase 5 pilot |
| 3 | What is the typical number of tasks per CAM in a target program? | Phase 1 | Phase 1 | ✅ Resolved — ATLAS program: ~11 tasks/CAM (57 tasks, 5 CAMs); acceptable for current interview design |
| 4 | Will this run inside the client's network or hosted externally? | Phase 5 | Phase 1 | ❓ Open — Phase 5 will decide; containerization supports both; ITAR requires on-prem for CUI data |
| 5 | Who is the first target customer and what is their reporting cycle? | All | Phase 1 | ❓ Open — ATLAS program used for dev/test; first real customer TBD for Phase 5 |
| 6 | Does the client have an existing local LLM deployment or do we need to provide one? | Phase 1 | Phase 1 | ✅ Resolved — Using Anthropic API for Phases 1–4 (non-ITAR dev data); Phase 5 will require on-prem model for ITAR compliance (ADR-003) |
| 7 | What are the data retention requirements for interview transcripts? | Phase 5 | Phase 3 | ✅ Resolved — `DATA_RETENTION_DAYS` env var (default 90); auto-purge at end of every cycle; `POST /api/admin/purge` for immediate purge; policy documented in SECURITY.md |
| 8 | Is the third use case (the one you couldn't remember) related to proposals or something else? | Program | Phase 1 | ❓ Open — Still TBD; not blocking Phase 5 |

---

## APPENDIX D — AGENT INSTRUCTIONS FOR IMPLEMENTATION

If you are an AI agent picking up this program plan, follow these rules:

1. **Always check the checklist first.** Find the first unchecked item in the current phase and start there. Do not skip ahead.
2. **Never mark a phase gate complete without human approval.** Phase gates are marked with ✋. Stop and wait.
3. **Always write tests before marking implementation tasks complete.** If the checklist says "unit test," write it.
4. **Commit working code frequently.** After each completed checklist item, commit to the repository with a descriptive message.
5. **Update this document as you work.** When you complete a task, check it off. When you discover new information, add it to the relevant appendix.
6. **When you hit a blocker, document it.** Add it to Appendix C with the phase and status. Do not spin.
7. **Never hardcode credentials, paths, or environment-specific values.** Everything configurable goes in `.env`.
8. **When in doubt, do less and ask.** A partial implementation with clear questions is better than a complete implementation based on wrong assumptions.

---

*Document generated: 2026-04-25*  
*Next review: Before Phase 1 kickoff*  
*Document owner: John Forbes*
