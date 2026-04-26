# Phase 5 — Production Hardening Acceptance

**Date:** 2026-04-26  
**Reviewer:** John Forbes  
**Environment:** Windows 11 / Python 3.13 / venv (Docker build verified; containerized runtime pending)

---

## What Was Built

Phase 5 hardened the Phase 4 agent for production readiness across five areas:

| Area | Deliverable |
|---|---|
| Containerization | `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`, `.dockerignore`; non-root user; health check |
| Security / RBAC | Two-key model: `DASHBOARD_API_KEY` (read) + `DASHBOARD_ADMIN_KEY` (admin); `QA_RATE_LIMIT_PER_HOUR` rate limiting on `/api/ask` |
| Data retention | `DATA_RETENTION_DAYS` env var; auto-purge at end of every cycle; `POST /api/admin/purge` endpoint |
| Observability | `GET /metrics` endpoint (7 counters); `LOG_FORMAT=json` structured logging; uptime in `/health` |
| On-prem LLM | `LLM_BASE_URL` env var routes all Anthropic SDK calls to any Ollama-compatible local endpoint |
| Q&A agentic loop | `LLMInterface.ask_with_tools()` + `agent/qa/ims_tools.py` — 8 IMS tool handlers; full metrics wiring |
| Documentation | `README.md`, `DEPLOYMENT.md`, `OPERATIONS.md`, `SECURITY.md`, `API.md`, `CONFIGURATION.md`, `CHANGELOG.md` |

---

## Acceptance Test Results

### Test Suite
- **242 tests, 0 failures** (`pytest tests/` on 2026-04-26)
- 37 new Phase 5 tests covering: metrics thread safety, purge logic, RBAC fallback, rate limiting, LLM_BASE_URL, metrics endpoint, QAEngine counter wiring

### RBAC Verification
- Read key (`X-API-Key`) accepted on `GET /api/state`, `GET /metrics`
- Read key **rejected** (401) on `POST /api/trigger`, `POST /api/admin/purge` when `DASHBOARD_ADMIN_KEY` is set
- Admin key (`X-Admin-Key`) accepted on all admin routes
- Single-key fallback: when `DASHBOARD_ADMIN_KEY` is empty, `DASHBOARD_API_KEY` covers all routes

### Rate Limiting Verification
- `QA_RATE_LIMIT_PER_HOUR=1` → first request succeeds, second returns HTTP 429
- Per-IP isolation: separate IPs share no rate limit state
- Stale entries (>1 hour old) correctly purged from window before counting

### Metrics Endpoint
- `GET /metrics` returns all 7 counters with correct initial values (0 / null)
- Counters increment correctly after direct Q&A and LLM-routed Q&A
- Thread-safe: 10 concurrent threads × 100 increments = exactly 1000 (verified)

### Data Retention
- Files older than `DATA_RETENTION_DAYS` are deleted; recent files preserved
- Purge runs automatically at end of every cycle (in `finally` block, errors logged but not re-raised)
- `POST /api/admin/purge` returns deleted counts for both `cycle_status` and `snapshots`

### LLM_BASE_URL
- When set, the `base_url` kwarg is passed to `anthropic.Anthropic()`; when unset, kwarg is omitted
- No behavioral change to any existing functionality

---

## Open Items (Not Blocking Acceptance)

| Item | Status |
|---|---|
| Deployment playbook test (Section 5.6) | Pending — requires independent tester on clean machine |
| Real Teams/ACS voice calls (TD-011) | Deferred — M365 trial expires 2026-05-25; Azure ACS not yet subscribed |
| ITAR on-prem LLM switch | `LLM_BASE_URL` env var ready; actual swap requires client security officer sign-off |
| Data at rest encryption | File-system level; deferred to host configuration |
| Prometheus-format metrics | `/metrics` returns JSON; Prometheus exporter deferred to follow-on |

---

## Verdict

**Phase 5 production hardening accepted.** All automated tests pass. RBAC, rate limiting, data retention, observability, and on-prem LLM swap path are implemented and tested. The agent is deployment-ready pending the Section 5.6 playbook test by an independent tester.

**John Forbes — 2026-04-26**
