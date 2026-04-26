# IMS Agent — API Reference

Base URL: `http://localhost:8080` (or your deployment URL)

All `/api/*` endpoints require `X-API-Key: YOUR_KEY` header when `DASHBOARD_API_KEY` is configured. The `/health` and `/` endpoints are unauthenticated.

---

## GET /health

Health check. Unauthenticated. Safe to poll from load balancers and uptime monitors.

**Response 200:**
```json
{
  "status": "healthy",
  "uptime_seconds": 3601,
  "cycle_active": false,
  "state_file_present": true,
  "auth_enabled": true
}
```

| Field | Type | Description |
|---|---|---|
| `status` | string | Always `"healthy"` if the process is up |
| `uptime_seconds` | integer | Seconds since process start |
| `cycle_active` | boolean | `true` if a cycle is currently running |
| `state_file_present` | boolean | `false` before the first cycle completes |
| `auth_enabled` | boolean | `true` if `DASHBOARD_API_KEY` is set |

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

## POST /api/trigger

Fires a new cycle immediately in a background thread. Returns immediately; use `GET /api/status` to poll for completion.

**Response 200:**
```json
{
  "status": "triggered",
  "message": "Cycle started in background"
}
```

**Response 409:** `{"detail": "A cycle is already running"}` — wait for it to complete.

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
| 401 | Missing or invalid `X-API-Key` header |
| 404 | Resource not found (e.g., no cycle data) |
| 409 | Conflict (cycle already running) |
| 500 | Internal server error |
