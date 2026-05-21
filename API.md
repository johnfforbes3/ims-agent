# IMS Agent — API Reference

Base URL: `http://localhost:9000` (or your deployment URL)

## Authentication

The agent supports two authentication schemes, evaluated in priority order:

### 1. Bearer JWT (Phase 7.2 — recommended)

Obtain a token from `POST /api/auth/token`, then pass it as `Authorization: Bearer <token>`.

- **Read routes** accept tokens with `"tier": "read"` or `"tier": "admin"`.
- **Admin routes** accept tokens with `"tier": "admin"` only. Admin-tier JTI is blocklisted after first use (replay resistance, CMMC IA.3.084).
- Tokens expire after `JWT_EXPIRY_SECONDS` (default: 3600s). Obtain a new token before expiry.

### 2. Static API Key (legacy / backward compat)

**Read routes** (`GET /api/state`, `GET /api/history`, `GET /api/status`, `GET /metrics`, `POST /api/ask`) accept `X-API-Key: YOUR_READ_KEY`.

**Admin routes** (`POST /api/trigger`, `POST /api/admin/purge`) accept `X-Admin-Key: YOUR_ADMIN_KEY`. When `DASHBOARD_ADMIN_KEY` is not set, the read key is accepted on admin routes (single-key fallback).

---

The `/health` and `/` endpoints are unauthenticated.

---

## POST /api/auth/token

Obtain a signed JWT. Unauthenticated endpoint. Requires `AUTH_SECRET_KEY`, `AUTH_CLIENT_ID`, and `AUTH_CLIENT_SECRET` to be set in `.env`.

**Request:**
```json
{
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "tier": "read"
}
```

| Field | Values | Description |
|---|---|---|
| `tier` | `"read"` or `"admin"` | Requested privilege tier |

**Response 200:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

**Response 401:** Wrong `client_id` or `client_secret`.  
**Response 400:** Unknown `tier` value.

---

## GET /health

Health check. Unauthenticated. Safe to poll from load balancers and uptime monitors.

**Response 200:**
```json
{
  "status": "healthy",
  "uptime_seconds": 3601,
  "cycle_active": false,
  "cycle_stalled": false,
  "cycle_heartbeat": null,
  "state_file_present": true,
  "auth_enabled": true,
  "last_cycle_age_seconds": 7200,
  "ims_last_write_at": "2026-05-17T11:01:25Z",
  "deadman_alert": false,
  "key_age_days": 45,
  "key_age_warning": false,
  "llm_circuit_open": false,
  "llm_circuit": {
    "status": "closed",
    "opened_at": null,
    "reason": null,
    "opens_until": null
  }
}
```

| Field | Type | Description |
|---|---|---|
| `status` | string | `"healthy"` normally; `"degraded"` when any of `deadman_alert / cycle_stalled / llm_circuit_open` is true (Phase 16) |
| `uptime_seconds` | integer | Seconds since process start |
| `cycle_active` | boolean | `true` if a cycle is currently running |
| `cycle_stalled` | boolean | **(Phase 16)** `true` when a heartbeat file exists but `now - last_heartbeat > ttl_seconds` (default 1800 s = 30 min). Survives process restart so an external monitor can detect a stuck cycle that the in-memory `_active` flag would have lost. |
| `cycle_heartbeat` | object\|null | **(Phase 16)** Snapshot of `data/cycle_heartbeat.json` when present — `cycle_id`, `phase`, `started_at`, `last_heartbeat`, `age_seconds`, `process_id`, `host`. |
| `state_file_present` | boolean | `false` before the first cycle completes |
| `auth_enabled` | boolean | `true` if `DASHBOARD_API_KEY` is set |
| `last_cycle_age_seconds` | integer\|null | Seconds since last cycle completed |
| `ims_last_write_at` | string\|null | ISO timestamp of last IMS XML write |
| `deadman_alert` | boolean | `true` if no cycle in `DEADMAN_PERIOD_HOURS` (default 168h) |
| `key_age_days` | integer\|null | Days since `KEY_CREATED_AT`; null if env var not set |
| `key_age_warning` | boolean | `true` if `key_age_days > 90` (SC.3.187 rotation reminder) |
| `llm_circuit_open` | boolean | **(Phase 16)** `true` when the LLM circuit breaker has been tripped (typically by a billing error). All LLM calls fail fast while open. |
| `llm_circuit` | object | **(Phase 16)** `status` ("closed" / "open"), `opened_at` (ISO), `opens_until` (ISO; auto-closes after this), `reason`, `duration_seconds`. Tunable via `LLM_CIRCUIT_OPEN_SECONDS` (default 900 = 15 min). |

> **Operator override:** delete `data/cycle_heartbeat.json` to manually clear a stuck stall after restarting the responder; delete `data/llm_circuit.json` to reset the breaker after topping up Anthropic credit.

---

## GET /

Returns the HTML dashboard. No authentication required (protect at the reverse proxy layer for production).

---

## GET /api/state

Returns the current dashboard state from the latest completed cycle.

**Response 200:**
```json
{
  "cycle_id": "20260426T104747Z",
  "last_updated": "2026-04-26T10:56:33+00:00",
  "schedule_health": "RED",
  "narrative": "The program is in critical condition...",
  "top_risks": "1. RF Specs Dependency\n2. Near-Zero SAT probability",
  "recommended_actions": "1. Get committed RF specs date by EOB today.",
  "critical_path_task_ids": ["1", "3", "21", "22"],
  "milestones": [
    {
      "task_id": "52",
      "milestone_name": "MS-02 PDR Complete",
      "baseline_date": "2026-05-29",
      "p50_date": "2026-05-30",
      "p80_date": "2026-06-01",
      "p95_date": "2026-06-02",
      "prob_on_baseline": 0.225,
      "risk_level": "HIGH"
    }
  ],
  "tasks_behind": [
    {
      "task_id": "3",
      "cam_name": "Alice Nguyen",
      "percent_complete": 60,
      "blocker": "RF specs from Hardware not received."
    }
  ],
  "cam_response_status": {
    "Alice Nguyen": {"responded": true, "attempts": 1, "last_outcome": "completed"}
  }
}
```

**Response 404:** `{"error": "No cycle data yet"}` — no cycle has completed.

---

## GET /api/history

Returns the rolling cycle history (most recent cycles first).

**Response 200:**
```json
[
  {
    "cycle_id": "20260426T104747Z",
    "timestamp": "2026-04-26T10:56:33Z",
    "schedule_health": "RED",
    "cams_responded": 5,
    "cams_total": 5
  },
  {
    "cycle_id": "20260419T060000Z",
    "timestamp": "2026-04-19T06:00:00Z",
    "schedule_health": "YELLOW",
    "cams_responded": 4,
    "cams_total": 5
  }
]
```

---

## GET /api/status

Returns whether a cycle is currently running.

**Response 200:**
```json
{
  "cycle_active": false
}
```

---

## GET /api/changes

Returns the cumulative IMS change summary for all cycles that have a diff file, merged into a single list sorted by task ID. Requires read API key.

**Response 200:**
```json
[
  {
    "task_id": "3",
    "task_name": "SE-03 Interface Control Documents",
    "field": "percent_complete",
    "before": 0,
    "after": 60,
    "cycle_id": "20260503T191337Z"
  }
]
```

---

## GET /api/baseline-drift

Returns the baseline drift alert for the current cycle. Requires read API key.

**Response 200:**
```json
{
  "baseline_cycle_id": "20260503T060000Z",
  "drift_days": 12,
  "alert": true,
  "alert_threshold_days": 10
}
```

| Field | Description |
|---|---|
| `baseline_cycle_id` | The cycle ID used as the drift baseline (`BASELINE_CYCLE_ID` env var) |
| `drift_days` | Calendar days between baseline cycle date and today |
| `alert` | `true` when `drift_days` exceeds `BASELINE_DRIFT_ALERT_DAYS` |
| `alert_threshold_days` | The configured threshold (default: 30 days) |

---

## GET /api/diff/{cycle_id}

Returns the IMS change diff for a specific cycle. Requires read API key.

**Response 200:**
```json
[
  {
    "task_id": "3",
    "task_name": "SE-03 ICD",
    "field": "percent_complete",
    "before": 0,
    "after": 60
  }
]
```

**Response 404:** `{"detail": "Diff not found for cycle ..."}` — cycle has no diff file.

---

## GET /metrics

Returns a JSON snapshot of all in-memory agent counters. Requires read API key.

**Response 200:**
```json
{
  "cycles_completed": 12,
  "cycles_failed": 0,
  "last_cycle_id": "20260426T060000Z",
  "last_cycle_duration_seconds": 487,
  "qa_queries_total": 35,
  "qa_queries_direct": 28,
  "qa_queries_llm": 7
}
```

| Field | Description |
|---|---|
| `cycles_completed` | Successful cycles since process start |
| `cycles_failed` | Failed cycles since process start |
| `last_cycle_id` | ISO timestamp of the most recent completed cycle |
| `last_cycle_duration_seconds` | Wall-clock seconds for the last cycle |
| `qa_queries_total` | Total Q&A questions answered since process start |
| `qa_queries_direct` | Questions answered from state without an LLM call |
| `qa_queries_llm` | Questions routed through the LLM |

Counters reset on process restart (in-memory only).

---

## POST /api/trigger

Fires a new cycle immediately in a background thread. Requires **admin key**. Returns immediately; use `GET /api/status` to poll for completion.

**Query Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `force` | boolean | `false` | When `true`, clears `ChatInterviewManager._completed_cams` before starting so the same CAMs can be re-interviewed immediately. Use after a failed cycle to avoid the "already completed" guard skipping all CAMs. The dashboard Trigger Cycle button always sends `force=true`. |

**Example:**
```bash
# Normal trigger
curl -X POST -H "X-Admin-Key: KEY" http://localhost:9000/api/trigger

# Force re-run after a failed cycle
curl -X POST -H "X-Admin-Key: KEY" http://localhost:9000/api/trigger?force=true
```

**Response 200:**
```json
{
  "status": "triggered",
  "message": "Cycle started in background"
}
```

**Response 409:** `{"detail": "A cycle is already running"}` — wait for it to complete.

---

## POST /api/admin/purge

Deletes cycle status JSONs and IMS snapshots older than `DATA_RETENTION_DAYS`. Requires **admin key**.

**Response 200:**
```json
{
  "status": "ok",
  "deleted": {
    "cycle_status": 5,
    "snapshots": 3
  }
}
```

| Field | Description |
|---|---|
| `deleted.cycle_status` | Number of cycle status JSON files deleted |
| `deleted.snapshots` | Number of IMS XML snapshots deleted |

---

## POST /api/ask

Answer a natural language question about the schedule. The engine first tries to answer directly from the dashboard state (fast, no LLM call); if the question requires raw schedule data it invokes IMS schedule tools via the Anthropic tool_use API.

**Request:**
```json
{
  "question": "What is the total float on task SE-03?"
}
```

| Field | Type | Required | Constraints |
|---|---|---|---|
| `question` | string | Yes | Non-empty, max 500 characters |

**Response 200:**
```json
{
  "answer": "Task SE-03 (Interface Control Documents) has **0.0 days** of total float — it is on the critical path. Any slip to SE-03 directly delays PDR.",
  "source_cycle": "20260426T104747Z",
  "intent": ["float", "blocker"],
  "direct": false
}
```

| Field | Type | Description |
|---|---|---|
| `answer` | string | The answer in Markdown format |
| `source_cycle` | string | Cycle ID the answer is grounded in |
| `intent` | string[] | Detected query intents (used for context routing) |
| `direct` | boolean | `true` if answered without an LLM call (~2s); `false` if LLM-routed (~10s) |

**Response 400:** Question empty or over 500 characters.  
**Response 429:** Rate limit exceeded (`QA_RATE_LIMIT_PER_HOUR` reached for this IP).  
**Response 500:** LLM or schedule data error.

### Example questions

| Question | Route | Typical response time |
|---|---|---|
| `"What is the current schedule health?"` | Direct | ~0.1s |
| `"What are the top risks?"` | Direct | ~0.1s |
| `"What are the critical path tasks?"` | Direct | ~0.1s |
| `"What should I focus on this week?"` | Direct | ~0.1s |
| `"What is the float on task SE-03?"` | LLM + tools | ~8s |
| `"What are the successors of HW-01?"` | LLM + tools | ~8s |
| `"Why is Alice Nguyen behind schedule?"` | LLM + state | ~10s |
| `"What is the probability of hitting PDR on time?"` | LLM + state | ~10s |

---

## GET /api/evm

*(Phase 9.2)* Returns EVM metrics from the latest dashboard state. Requires read API key.

**Response 200:**
```json
{
  "program": {
    "label": "PROGRAM", "task_count": 92,
    "bac": 460.0, "bcwp": 215.3, "bcws": 230.0,
    "spi": 0.936, "sv": -14.7, "sv_pct": -6.4,
    "eac": 491.5, "vac": -31.5, "tcpi": 1.13,
    "completion_pct": 46.8, "health": "YELLOW", "bei": 0.91
  },
  "by_cam": {
    "Alice": { "spi": 0.90, "sv": -5.0, "bac": 110.0, "health": "YELLOW" }
  },
  "task_detail": [...],
  "data_unit": "work-days",
  "reference_date": "2026-05-06T12:00:00+00:00",
  "computed_at": "2026-05-06T12:01:00+00:00"
}
```

**Response 404:** No state file yet — run a cycle first.

---

## GET /api/dcma

*(Phase 9.3)* Returns DCMA 14-point assessment from the latest dashboard state. Requires read API key.

**Response 200:**
```json
{
  "score": 10, "total_checks": 14, "score_pct": 71.4,
  "health": "YELLOW",
  "summary": "10/14 checks passed — YELLOW",
  "checks": [
    { "check_id": 1, "name": "Logic (Missing Predecessors/Successors)", "passed": true,
      "violations": 0, "threshold": "≤5% orphan tasks", "flagged_tasks": [], "note": "..." }
  ],
  "thresholds": { "high_float_days": 44, "high_duration_days": 44 },
  "computed_at": "2026-05-06T12:01:00+00:00"
}
```

**Response 404:** No state file yet — run a cycle first.

---

## GET /api/variance

*(Phase 9.4)* Returns the auto-generated variance analysis narrative from the latest dashboard state. Requires read API key.

**Response 200:**
```json
{
  "narrative": "Schedule performance for the current period reflects...",
  "variance_summary": {
    "spi": 0.936, "sv": -14.7, "bei": 0.91, "dcma_score": 10,
    "blockers": 23, "risk_flags": 5, "worst_cams": ["Alice", "Bob"]
  }
}
```

**Response 404:** No variance narrative yet — run a cycle first.

---

## GET /api/briefing

*(Phase 9.5)* Generates and returns a self-contained HTML executive briefing for the latest cycle. Requires read API key.

**Response 200:** `Content-Type: text/html` — a fully self-contained HTML document (no CDN dependencies). Saved to `reports/briefings/{cycle_id}_brief.html`.

**Response 404:** No state available — run a cycle first.

---

## GET /api/briefing/{cycle_id}

*(Phase 9.5)* Generates and returns an executive briefing for a specific cycle ID. Useful for recreating historical briefs. Requires read API key.

**Response 200:** `Content-Type: text/html`
**Response 404:** No state available.

---

## GET /api/sra

*(Phase 16)* Returns milestone-level SRA results (P50/P80/P95/prob_on_baseline/risk_level) from the current cycle. Requires read API key.

**Response 200:**
```json
{
  "cycle_id": "20260517T104629Z",
  "generated_at": "2026-05-17T11:01:25+00:00",
  "milestones": [
    {
      "task_id": "52", "milestone_name": "MS-02 PDR Complete",
      "baseline_date": "2026-05-29", "p50_date": "2026-05-30",
      "p80_date": "2026-06-01", "p95_date": "2026-06-02",
      "prob_on_baseline": 0.225, "risk_level": "HIGH"
    }
  ]
}
```

**Response 404:** `{"error": "No SRA results yet. Run a cycle first."}`

> **Note:** This endpoint returns the milestone P50/P80/P95 anchors from the cycle's SRA run. A full per-day Monte-Carlo histogram (every finish date in the distribution) is **not** yet exposed — would require persisting MC bucket counts in `dashboard_state.json`, scoped for a future phase.

---

## GET /api/schedule/summary

*(Phase 16)* Parses the latest IMS export and returns a compact summary the dashboard Gantt chart can render. Requires read API key.

**Response 200:**
```json
{
  "cycle_id": "20260517T104629Z",
  "generated": "2026-05-17T11:01:25+00:00",
  "program_start": "2026-01-05",
  "program_end": "2026-06-25",
  "label": "v20260517T",
  "rows": [
    {
      "id": "1", "name": "Power Subsystem Design",
      "start": "2026-01-05", "end": "2026-02-14",
      "complete": 0.85, "critical": true, "cam": "Alice Nguyen"
    }
  ],
  "milestones": [
    {
      "id": "52", "name": "MS-02 PDR Complete",
      "date": "2026-05-29", "met": false, "critical": true,
      "risk_level": "HIGH", "p80_date": "2026-06-01"
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `program_start` / `program_end` | string | Min/max of task start/finish dates (ISO yyyy-mm-dd) |
| `rows` | array | Non-milestone tasks (duration > 0); capped at 30 for payload bounds |
| `milestones` | array | Tasks with duration_days = 0; capped at 20; enriched with SRA P80 + risk_level when present in state |
| `complete` | number | Percent complete as 0.0–1.0 (note: API.md uses fraction, not percent) |
| `critical` | boolean | `true` when task_id appears in `dashboard_state.critical_path_task_ids` |

**Response 404:** `{"error": "IMS export not found at <path>. Run a cycle first."}` or `{"error": "IMS parsed but contains no tasks."}`
**Response 500:** `{"detail": "IMS parse failed: <error>"}` — surfaces XML parse errors from `IMSFileHandler`.

---

## GET /api/hrm/history

*(Phase 16)* Companion to `/api/evm/history`. Returns last N cycles' high-risk-milestone counts for the HRM sparkline. Requires read API key.

**Query params:**
| Param | Default | Description |
|---|---|---|
| `n` | 24 | Max cycles to return; capped at 100 |

**Response 200:**
```json
{
  "history": [
    {"cycle_id": "20260510T060000Z", "timestamp": "2026-05-10T06:14:22Z", "high_risk_milestones": 6},
    {"cycle_id": "20260517T104629Z", "timestamp": "2026-05-17T11:01:25Z", "high_risk_milestones": 5}
  ],
  "n": 2
}
```

> **Note:** Cycles persisted **before** Phase 16 don't have `high_risk_milestones` in their history row and are omitted from the response. The first few cycles after the Phase 16 upgrade will return a shorter series until enough cycles have run.

---

## GET /api/audit

*(Phase 16)* Returns rows from the immutable `audit_log` SQLite table. Requires read API key.

**Query params:**
| Param | Default | Description |
|---|---|---|
| `limit` | 200 | Max rows to return; capped at 1000 |
| `action` | — | Filter by action name (e.g. `cycle.trigger`, `approval.approve`) |
| `actor_user` | — | Filter by X-User-Email value |
| `target` | — | Filter by target (typically a `cycle_id`) |
| `since` | — | ISO timestamp; only rows newer than this |

**Response 200:**
```json
{
  "rows": [
    {
      "id": 42,
      "timestamp_utc": "2026-05-17T11:02:00.123456+00:00",
      "action": "cycle.trigger",
      "actor_user": "alice@program.mil",
      "actor_ip": "10.0.0.42",
      "actor_key_tier": "admin",
      "target": "manual",
      "outcome": "success",
      "detail": "{\"force\": true, \"transport\": \"teams_chat\"}"
    }
  ],
  "count": 1
}
```

**Recognized action names:**
| Action | Triggered by |
|---|---|
| `cycle.trigger` | POST /api/trigger |
| `admin.purge` | POST /api/admin/purge |
| `approval.approve` | POST /api/approvals/{id}/approve |
| `approval.reject` | POST /api/approvals/{id}/reject |

**Per-user attribution:** clients pass `X-User-Email: alice@program.mil` on any request; the value is captured into `actor_user` without being trusted for authorization (still comes from the API key / JWT tier). When absent, `actor_user: "anonymous"`. Production roadmap swaps the header for SSO/OIDC claims from a verified JWT.

> **Operator note:** the table is append-only by application convention (no UPDATE/DELETE in the codebase). Tamper-evidence via a hash chain is on the Phase 16+ roadmap, not yet implemented.

---

## GET /api/portfolio

*(Phase 9.6)* Returns the multi-program portfolio health summary. Requires read API key.

**Response 200:**
```json
{
  "programs": [
    {
      "program_id": "ims-1", "name": "AI Agent Server Rack",
      "health": "YELLOW", "spi": 0.936, "completion_pct": 46.8,
      "dcma_score": "10/14", "dcma_health": "YELLOW",
      "high_risk_milestones": 2, "medium_risk_milestones": 1,
      "cam_rate": "4/5", "is_stale": false
    }
  ],
  "portfolio_health": "YELLOW",
  "total_programs": 1,
  "programs_at_risk": 1,
  "computed_at": "2026-05-06T12:01:00+00:00"
}
```

**Portfolio health logic:** Any RED → RED; all GREEN → GREEN; else YELLOW. Falls back to single-program view when `data/portfolio.json` does not exist.

---

## POST /api/portfolio/register

*(Phase 9.6)* Register a new program in the portfolio registry. Requires **admin key**.

**Request:**
```json
{
  "program_id": "prog-002",
  "name": "Ground System Upgrade",
  "state_file": "/opt/ims-agent-prog2/data/dashboard_state.json",
  "description": "Option B ground system"
}
```

**Response 200:** `{"status": "registered", "program_id": "prog-002"}`
**Response 400:** Missing required field.

---

## Error Responses

All error responses follow FastAPI's default format:

```json
{
  "detail": "Human-readable error message"
}
```

| Status | Meaning |
|---|---|
| 400 | Bad request (missing or invalid input) |
| 401 | Missing or invalid `Authorization: Bearer` token, or `X-API-Key` / `X-Admin-Key` header |
| 403 | Authenticated but insufficient tier (e.g., read-tier JWT on admin route) |
| 404 | Resource not found (e.g., no cycle data) |
| 409 | Conflict (cycle already running) |
| 429 | Rate limit exceeded (Q&A endpoint) |
| 500 | Internal server error |
