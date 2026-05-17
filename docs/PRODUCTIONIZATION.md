# Productionization (Phase 16)

This document describes the three production-readiness tracks landed in
Phase 16, what each does, what's still scoped for the future, and how to
operate the new pieces.

## Track 1 — Real data on the dashboard

Five mock-data panels now hydrate from real backend endpoints. Each
gracefully falls back to its mock when the endpoint returns 404 / empty.

| Panel | Endpoint | Status |
|---|---|---|
| Schedule Health History | `GET /api/health/history?n=24` | ✅ real (already wired pre-Phase 16) |
| BEI / SFA sparklines (Tab 1) | `GET /api/evm/history?n=24` | ✅ real (cycle history now writes EVM block) |
| HRM sparkline (Tab 1) | `GET /api/hrm/history?n=24` | ✅ real (new endpoint + history field) |
| SRA milestone anchors | `GET /api/sra` | ✅ real (returns milestones[] from state) |
| Summary Schedule Gantt | `GET /api/schedule/summary` | ✅ real (parses latest IMS export) |
| Per-CAM live progress | `GET /api/interview-sessions` | ✅ real (polled every 5 s) |

**Out of scope for Phase 16** (still mocked):
- Full Monte-Carlo SRA histogram (no /api/sra/histogram endpoint yet —
  needs the MC engine to persist per-day buckets, not just percentile
  anchors).
- Cumulative diff over arbitrary cycle ranges (only "latest" is real).

## Track 2 — Pipeline resilience

### Cycle heartbeat (`agent/cycle_heartbeat.py`)

The cycle runner writes a persistent heartbeat file at
`data/cycle_heartbeat.json` at the start of each cycle and updates it as
phases progress. A cycle is **stalled** when:

- the heartbeat file exists, AND
- `now - last_heartbeat > ttl_seconds` (default 1800 s = 30 min)

The `/health` endpoint surfaces `cycle_stalled: true` + a heartbeat
snapshot so ops monitors can alert.

Operator override: delete `data/cycle_heartbeat.json` to manually clear a
stuck heartbeat after restarting the responder.

### Anthropic API circuit breaker (`agent/circuit_breaker.py`)

Errors from the LLM are categorized into three buckets:

- **TRANSIENT** — RateLimitError, APIConnectionError, 5xx → retry with backoff
- **TERMINAL** — bad prompt, auth failure → fail fast, no retry
- **BILLING** — "credit balance", "insufficient quota", payment required
  → **trip breaker**, fail fast for 15 minutes (configurable via
  `LLM_CIRCUIT_OPEN_SECONDS`)

When the breaker opens, all subsequent LLM calls fail immediately with
`CircuitOpenError` until the open window elapses, so we don't burn more
failed requests against a depleted account. The `/health` endpoint
exposes the breaker state under `llm_circuit_open` and `llm_circuit`.

Operator override: after topping up credits, either wait for the open
window to elapse or delete `data/llm_circuit.json` to reset immediately.

### Enhanced `/health`

```jsonc
{
  "status": "healthy" | "degraded",
  "cycle_active": false,
  "cycle_stalled": false,
  "cycle_heartbeat": { /* persistent state or null */ },
  "deadman_alert": false,
  "llm_circuit_open": false,
  "llm_circuit": { "status": "closed", ... }
}
```

`status` rolls up to `"degraded"` when any of `deadman_alert`,
`cycle_stalled`, or `llm_circuit_open` is true. Useful for a single
uptime-monitor pingdom-style check.

## Track 3 — Auth, audit, approval

### Two-person approval flow (pre-existing, now documented)

Baseline rewrites are gated by `agent/approval_store.py`. The flow:

1. Cycle runner detects a "risky" change set (large slip, milestone
   miss, etc.) and writes a pending record under `data/pending_approvals/`
   instead of applying the diff.
2. Dashboard fetches `GET /api/approvals` to surface pending items.
3. PM clicks approve → `POST /api/approvals/{cycle_id}/approve`
   (admin tier required, JTI replay protection on JWT tokens).
4. `CycleRunner.apply_approved()` runs the post-approval analysis
   (CPM + SRA + report) and writes the new baseline.
5. Reject path: `POST /api/approvals/{cycle_id}/reject` discards the
   pending cam_inputs without applying.

**Phase 16 addition:** every approve/reject is now recorded in the
immutable audit_log SQLite table (see below).

### Per-user identity

Clients pass `X-User-Email: alice@program.mil` on any request. The
value is captured into the audit log without being trusted for
authorization (which still comes from the API key / JWT tier). When
absent, the audit row records `actor_user: "anonymous"`.

**Production roadmap:** swap `X-User-Email` for SSO/OIDC claims pulled
from a verified JWT issued by the M365 tenant (Azure AD). The audit
log shape doesn't change — only the source of `actor_user`.

### Immutable audit log

SQLite table `audit_log` in `data/ims.db`. Schema is append-only with
no UPDATE path. Every sensitive admin action writes a row:

| Action name | Trigger |
|---|---|
| `cycle.trigger` | POST /api/trigger |
| `admin.purge` | POST /api/admin/purge |
| `approval.approve` | POST /api/approvals/{id}/approve |
| `approval.reject` | POST /api/approvals/{id}/reject |

Each row captures: timestamp_utc, action, actor_user, actor_ip,
actor_key_tier, target, outcome, detail (JSON).

Read via `GET /api/audit?limit=200&action=cycle.trigger&since=2026-05-01`.

### What's NOT in Phase 16

- **Real SSO/OIDC** — the user identity is still self-declared via
  header. A future phase wires the M365 tenant + OAuth code flow.
- **Per-user RBAC** — today there are still only two roles (read / admin)
  keyed by API key tier. A future phase keys roles to the SSO identity
  so individual PMs can be granted approve-only or read-only.
- **Audit log retention/rotation** — rows accumulate forever. A future
  phase adds a `/api/admin/audit/rotate` endpoint and a periodic export
  to long-term storage (e.g. WORM bucket).
- **Tamper-evidence on the audit log** — today rows are append-only by
  convention (no UPDATE/DELETE in the application layer). A future
  phase adds a hash chain so an attacker with DB access can't silently
  delete rows.

## Operator quick reference

```bash
# Reset a stalled cycle
rm data/cycle_heartbeat.json
# (then restart the responder)

# Reset the LLM circuit breaker after billing top-up
rm data/llm_circuit.json

# Pull recent audit trail
curl -H "X-API-Key: $DASHBOARD_API_KEY" \
     "http://localhost:9000/api/audit?limit=50"

# Pull trail for one specific cycle
curl -H "X-API-Key: $DASHBOARD_API_KEY" \
     "http://localhost:9000/api/audit?target=20260517T104629Z"
```
