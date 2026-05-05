# IMS Agent Dashboard — Feature Catalogue & Requirements Baseline

> **Purpose:** This document is the authoritative baseline for every feature visible in the
> IMS Agent Dashboard (`agent/dashboard/templates/index.html`).  
> It was written **before** the UI overhaul (Phase 9.1) and must be used as the acceptance
> checklist after any redesign or refactor. Every numbered requirement (REQ-D-NNN) must pass
> before a dashboard change can be merged.
>
> **Last updated:** 2026-05-04 (Phase 8.3 / 424 tests)

---

## Table of Contents

1. [Header Bar](#1-header-bar)
2. [Health Banner](#2-health-banner)
3. [Validation Alert Panel](#3-validation-alert-panel)
4. [KPI Cards](#4-kpi-cards)
5. [Milestone Risk Summary](#5-milestone-risk-summary)
6. [CAM Response Status](#6-cam-response-status)
7. [Top Risks](#7-top-risks)
8. [Tasks Behind Schedule](#8-tasks-behind-schedule)
9. [Critical Path Task List](#9-critical-path-task-list)
10. [Recommended Actions](#10-recommended-actions)
11. [Schedule Health History](#11-schedule-health-history)
12. [Q&A Chat Widget](#12-qa-chat-widget)
13. [Cycle-In-Progress Card](#13-cycle-in-progress-card)
14. [IMS Diff Viewer](#14-ims-diff-viewer)
15. [Change History (Cumulative Diff)](#15-change-history-cumulative-diff)
16. [Baseline Drift Report](#16-baseline-drift-report)
17. [Trigger Cycle Button](#17-trigger-cycle-button)
18. [Auto-Refresh](#18-auto-refresh)

---

## 1. Header Bar

**Feature:** Persistent top bar showing application identity, program name, refresh countdown,
last-updated timestamp, and the Trigger Cycle action button.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-001 | Header displays application title "IMS Agent — Schedule Dashboard" | Visual check |
| REQ-D-002 | Header displays program sub-label (e.g. "ATLAS Program") | Visual check |
| REQ-D-003 | Refresh countdown badge counts down from 60s to 0 and resets | Wait 65s, observe |
| REQ-D-004 | `last_updated` timestamp from `/api/state` is shown | Compare to `GET /api/state` |
| REQ-D-005 | Header is sticky — remains visible when page is scrolled | Scroll page to bottom |
| REQ-D-006 | Trigger Cycle button is present and functional (see §17) | Click and observe |

---

## 2. Health Banner

**Feature:** Full-width banner displaying the current schedule health status (RED / YELLOW /
GREEN / UNKNOWN) with color coding, cycle ID, and last-updated metadata.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-010 | Banner background color matches health status (RED=red tint, YELLOW=amber, GREEN=green, UNKNOWN=grey) | Run cycle, compare |
| REQ-D-011 | Health label text (RED / YELLOW / GREEN / UNKNOWN) is bold and prominent | Visual check |
| REQ-D-012 | Colored left border or border ring matches health status | Visual check |
| REQ-D-013 | Cycle ID from `/api/state` is displayed in banner meta line | Compare to `GET /api/state` |
| REQ-D-014 | Last-updated timestamp is displayed in banner meta line | Compare to `GET /api/state` |
| REQ-D-015 | `ims_master_dir` path is shown when present in state (for PM to locate .mpp) | Set env var, verify display |
| REQ-D-016 | Banner updates on every full-page reload without stale data | Hard-refresh after cycle |

---

## 3. Validation Alert Panel

**Feature:** Collapsible warning panel that appears only when the current cycle flagged one or
more validation failures (backwards movement, large jumps, etc.). Hidden when no holds exist.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-020 | Panel is hidden when `validation_holds` list in state is empty | Run clean cycle, confirm absent |
| REQ-D-021 | Panel is visible and expanded when one or more holds exist | Trigger backwards-movement hold |
| REQ-D-022 | Hold count is shown in the summary label ("N hold(s) flagged this cycle") | Compare count to holds list |
| REQ-D-023 | Table shows Task ID, CAM Name, Rule name, and detail text for each hold | Compare to approval JSON |
| REQ-D-024 | Rule column displays a styled badge (not plain text) | Visual check |
| REQ-D-025 | Panel is collapsible (click to hide / expand) | Click summary element |

---

## 4. KPI Cards

**Feature:** Row of summary metric cards providing at-a-glance program health.
Four metrics are always shown.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-030 | "CAMs Responded" card shows `responded / total` from `completion_report` in state | Compare to `GET /api/state` |
| REQ-D-031 | CAMs Responded value is green when all responded, amber when partial, red when zero | Vary cycle CAM response count |
| REQ-D-032 | "HIGH Risk Milestones" card shows count of milestones with `risk_level == "HIGH"` | Compare to milestone list |
| REQ-D-033 | HIGH Risk count is red when > 0, green when 0 | Visual check both states |
| REQ-D-034 | "Tasks Behind w/ Blocker" card shows count of items in `tasks_behind` list | Compare to state |
| REQ-D-035 | "Critical Path Tasks" card shows count of task IDs in `critical_path_task_ids` | Compare to CPM output |
| REQ-D-036 | KPI cards display sub-labels describing the metric unit | Visual check |
| REQ-D-037 | KPI cards render in a responsive grid (4-wide on desktop, narrower on mobile) | Resize browser |

---

## 5. Milestone Risk Summary

**Feature:** Table of all tracked milestones with SRA-derived risk assessment, showing baseline
date, P50/P95 finish dates, probability of on-time completion, and risk level badge.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-040 | Table displays all milestones from `milestones` in state | Compare count to SRA output |
| REQ-D-041 | Columns: Milestone name, Baseline date, P50 date, P95 date, On-Time %, Risk badge | Visual check |
| REQ-D-042 | Milestones are sorted ascending by `prob_on_baseline` (worst first) | Inspect row order |
| REQ-D-043 | Risk badge color: HIGH=red, MEDIUM=amber, LOW=green | Visual check |
| REQ-D-044 | On-Time % is formatted as an integer percentage (e.g. "4%") | Compare to raw `prob_on_baseline` × 100 |
| REQ-D-045 | Empty state "No milestone data — run a cycle first" shown before first cycle | Load blank state file |

---

## 6. CAM Response Status

**Feature:** Table showing response status for each registered CAM, updated live during an
active cycle. Each row shows responded/no-response indicator, attempt count, and last outcome.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-050 | Table shows one row per CAM in `cam_response_status` dict in state | Compare to state |
| REQ-D-051 | Green dot + "Responded" shown when `responded == true` | Post-cycle with all CAMs |
| REQ-D-052 | Red dot + "No Response" shown when `responded == false` | Post-cycle with missed CAM |
| REQ-D-053 | Attempts column shows integer attempt count | Compare to state |
| REQ-D-054 | Last Outcome column shows last outcome string or "—" | Compare to state |
| REQ-D-055 | During active cycle, status cells update live (Interviewing…/Responded/No Response) via AJAX | Trigger cycle, watch table |
| REQ-D-056 | AJAX live update does not cause full page reload during interviewing phase | Observe during cycle |

---

## 7. Top Risks

**Feature:** Narrative synthesis of the top schedule risks as generated by the LLM after each
cycle. Displayed as pre-formatted text preserving line breaks.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-060 | Top risks text from `top_risks` in state is displayed | Compare to `GET /api/state` |
| REQ-D-061 | Text preserves newlines and paragraph structure | Visual check |
| REQ-D-062 | Empty state "No risk synthesis yet — run a cycle first" shown before first cycle | Load blank state |

---

## 8. Tasks Behind Schedule

**Feature:** Table of work tasks that are behind schedule and have an active blocker reported
by the CAM. Only tasks with a non-empty blocker field are shown.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-070 | Table shows all tasks in `tasks_behind` list from state | Compare count to state |
| REQ-D-071 | Columns: Task ID, CAM Name, Percent Complete, Blocker description | Visual check |
| REQ-D-072 | Empty state shown when no tasks are behind with blockers | Run cycle with all tasks on track |
| REQ-D-073 | Percent complete shown as styled badge | Visual check |
| REQ-D-074 | Blocker text is readable at smaller font size (12px) and truncates gracefully | Visual check |

---

## 9. Critical Path Task List

**Feature:** Visual chip list of all task IDs currently on the critical path (zero total float),
derived from the CPM analysis. Count displayed in the section header.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-080 | All task IDs in `critical_path_task_ids` state field are shown | Compare count to CPM output |
| REQ-D-081 | Task IDs are rendered as distinct visual chips (not plain text) | Visual check |
| REQ-D-082 | Count of critical path tasks is shown in the card heading | Visual check |
| REQ-D-083 | Empty state shown when no critical path data available | Load blank state |

---

## 10. Recommended Actions

**Feature:** LLM-generated recommended PM actions from the synthesis step. Only shown when
`recommended_actions` is non-empty in state.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-090 | Section is hidden when `recommended_actions` is absent or empty | Load blank state |
| REQ-D-091 | Text content from state is displayed with newlines preserved | Visual check |
| REQ-D-092 | Section has a distinct visual indicator (e.g. accent border) | Visual check |

---

## 11. Schedule Health History

**Feature:** Chronological chart of all past cycles showing health status, CAM response
counts, cycle IDs, and timestamps. Most recent cycle displayed last (top → oldest).

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-100 | All cycles in `/api/history` response are shown | Compare count to `GET /api/history` |
| REQ-D-101 | Cycles are displayed most-recent-first | Inspect order of timestamps |
| REQ-D-102 | Health status shown as a colored bar and badge per row | Visual check |
| REQ-D-103 | Bar width or color encodes severity (RED > YELLOW > GREEN) | Visual check |
| REQ-D-104 | Each row shows date, CAMs responded/total, and cycle ID | Visual check |
| REQ-D-105 | Header shows count of cycles shown | Visual check |
| REQ-D-106 | Empty state shown when no cycle history available | Load blank state |

---

## 12. Q&A Chat Widget

**Feature:** Embedded chat interface allowing the PM to ask natural language questions about
the schedule. Backed by `/api/ask`. Includes quick-pick example chips, chat history
persistence across page reloads (sessionStorage), and a clear-chat button.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-110 | Chat input accepts text up to 500 characters | Type 501 characters |
| REQ-D-111 | Pressing Enter submits the question | Type question, press Enter |
| REQ-D-112 | Clicking Ask button submits the question | Click Ask |
| REQ-D-113 | "Thinking…" placeholder appears while waiting for response | Submit question, observe |
| REQ-D-114 | Answer from `/api/ask` is rendered in assistant bubble with newlines preserved | Ask any question |
| REQ-D-115 | Source cycle ID is shown below the answer when returned by API | Ask any schedule question |
| REQ-D-116 | Input and button are disabled while a request is in flight | Submit, quickly re-click |
| REQ-D-117 | Example chips auto-fill the input and submit the question | Click any chip |
| REQ-D-118 | Chat history is persisted to sessionStorage and restored on page reload | Ask question, reload page |
| REQ-D-119 | Clear chat (✕ button) removes sessionStorage and resets to welcome message | Click ✕, verify state |
| REQ-D-120 | Welcome message is shown on fresh load (no saved history) | Clear storage, reload |
| REQ-D-121 | Network errors display a red error message in the assistant bubble | Disconnect server, submit |

---

## 13. Cycle-In-Progress Card

**Feature:** Card shown only during an active cycle, updated every 5 seconds via AJAX.
Displays current phase, cycle ID, CAM responded count, and per-CAM progress pills.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-130 | Card is hidden when no cycle is active (`cycle_active == false`) | Load page between cycles |
| REQ-D-131 | Card appears when a cycle starts (within 5s of trigger) | Trigger cycle, wait 5s |
| REQ-D-132 | Phase, Cycle ID, and CAMs count update every 5 seconds | Watch during cycle |
| REQ-D-133 | Per-CAM pills show ✓ (complete), ✗ (no answer), ⏳ (pending) | Trigger cycle, observe pills |
| REQ-D-134 | Pill color matches status: green (complete), red (no answer), amber (pending) | Visual check |
| REQ-D-135 | Full page reload occurs when cycle transitions from active to complete | Watch end of cycle |
| REQ-D-136 | Poll interval is 5s during active cycle, 60s when idle | Network tab, count requests |

---

## 14. IMS Diff Viewer

**Feature:** Collapsible panel showing field-level changes for a single cycle. On page load,
automatically fetches and displays the most recent cycle that has a diff file. The PM can
also manually enter any cycle ID and reload.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-140 | Panel auto-loads the most recent cycle with a diff on page load (`/api/diff/latest`) | Load page, inspect panel |
| REQ-D-141 | Cycle ID input is pre-populated with the most-recent-diff cycle ID on load | Load page, inspect input |
| REQ-D-142 | Panel opens automatically when diff data with ≥1 change is found | Load page after write cycle |
| REQ-D-143 | Change count badge appears in panel header when changes > 0 | Verify badge vs table rows |
| REQ-D-144 | Load button reloads using the current value in the cycle ID input | Change input, click Load |
| REQ-D-145 | Table shows: Task name, CAM, Field, Old value, New value | Visual check |
| REQ-D-146 | Empty state "No field changes recorded" shown for cycles with 0 changes | Use a zero-change cycle |
| REQ-D-147 | Error state shown when cycle ID has no diff file | Enter invalid cycle ID |
| REQ-D-148 | `/api/diff/latest` endpoint returns most recent readable diff cycle | `curl /api/diff/latest` |
| REQ-D-149 | Panel is collapsible (click summary to open/close) | Click summary |

---

## 15. Change History (Cumulative Diff)

**Feature:** Collapsible panel showing the net cumulative changes across all cycles (or a
user-specified range). Includes CSV export. Auto-loads all-cycles view on page load.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-150 | Panel auto-loads full change history (blank from/to) on page load | Load page, inspect panel |
| REQ-D-151 | Panel opens automatically when cumulative changes > 0 | Load page with existing diffs |
| REQ-D-152 | Change count badge appears in panel header | Verify badge vs table rows |
| REQ-D-153 | "From" and "To" cycle ID inputs are blank by default (all cycles) | Visual check |
| REQ-D-154 | Load button reloads the table using current From/To values | Enter values, click Load |
| REQ-D-155 | Table shows: Task, CAM, Field, Old, New, Hop count, Contributing cycle IDs | Visual check |
| REQ-D-156 | Status line shows `N net change(s) · from_cycle → to_cycle` | Compare to API response |
| REQ-D-157 | CSV export link appears after load and downloads valid CSV | Click ⬇ CSV |
| REQ-D-158 | Error state shown when no diff files exist | Clear ims_exports, load |
| REQ-D-159 | Panel is collapsible | Click summary |

---

## 16. Baseline Drift Report

**Feature:** Collapsible panel comparing current task percent-complete and finish dates against
the baseline snapshot. Auto-loads on page load. Shows slip in days and delta-%.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-160 | Panel auto-loads baseline drift on page load | Load page, inspect panel |
| REQ-D-161 | Panel opens automatically when drifted tasks > 0 | Load page after baseline set |
| REQ-D-162 | Drift count badge appears in panel header when tasks > 0 | Verify badge |
| REQ-D-163 | Friendly message shown when no baseline snapshot exists yet | Fresh install, load page |
| REQ-D-164 | Table shows: Task, CAM, Baseline Finish, Current Finish, Slip (days), Δ% | Visual check |
| REQ-D-165 | Slip (days) color coded: ≥30 red, ≥14 amber, <14 default | Verify color thresholds |
| REQ-D-166 | Δ% column color coded: negative=red, positive=green | Visual check |
| REQ-D-167 | Milestone rows show ⛳ icon suffix | Verify milestone rows |
| REQ-D-168 | Empty state "No drift from baseline" shown when all tasks within tolerance | Run cycle with no drift |
| REQ-D-169 | Panel is collapsible | Click summary |

---

## 17. Trigger Cycle Button

**Feature:** Button in the header that immediately POSTs to `/api/trigger` to start a cycle
outside the normal scheduler window. Disabled during and after trigger, then auto-reloads.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-170 | Button posts to `/api/trigger` on click | Observe network tab |
| REQ-D-171 | Button is disabled and shows "Starting…" during the POST | Click, observe button state |
| REQ-D-172 | On success, button shows "✓ Cycle Started" then page auto-reloads after 2s | Observe |
| REQ-D-173 | On error, button shows error text and re-enables | Kill server, click button |
| REQ-D-174 | `action=audit_admin_trigger` is recorded in the server log | Check schedule_run.log |

---

## 18. Auto-Refresh

**Feature:** Page auto-polls the server to detect cycle state changes. During idle: 60s
full-page reload cycle. During active cycle: 5s AJAX-only update. Transitions to full reload
when cycle completes.

| REQ # | Requirement | Verification |
|-------|-------------|--------------|
| REQ-D-180 | Countdown badge counts down from 60s to 0 then resets | Wait 65s |
| REQ-D-181 | Poll interval switches to 5s when `cycle_active == true` | Trigger cycle, check network tab |
| REQ-D-182 | Poll interval returns to 60s when cycle completes | Wait for cycle to finish |
| REQ-D-183 | Full-page reload fires when cycle transitions from active→complete | Watch end of cycle |
| REQ-D-184 | Network error causes 10s back-off (no crash, no infinite loop) | Drop server briefly |
| REQ-D-185 | Concurrent poll guard prevents overlapping poll requests | Check timing edge case |

---

## Summary: Requirement Counts by Section

| Section | REQ count |
|---------|-----------|
| 1 Header Bar | 6 |
| 2 Health Banner | 7 |
| 3 Validation Alerts | 6 |
| 4 KPI Cards | 8 |
| 5 Milestone Risk | 6 |
| 6 CAM Response Status | 6 |
| 7 Top Risks | 3 |
| 8 Tasks Behind | 5 |
| 9 Critical Path | 4 |
| 10 Recommended Actions | 3 |
| 11 Health History | 7 |
| 12 Q&A Chat | 12 |
| 13 Cycle-In-Progress | 7 |
| 14 IMS Diff Viewer | 10 |
| 15 Change History | 10 |
| 16 Baseline Drift | 10 |
| 17 Trigger Button | 5 |
| 18 Auto-Refresh | 6 |
| **Total** | **121** |

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-05-04 | Initial baseline created — 121 requirements across 18 features | Claude (Phase 8.3) |
