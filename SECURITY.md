# IMS Agent — Security Architecture

This document describes the security posture, data handling policy, and CMMC compliance considerations for the IMS Agent.

---

## Authentication and Authorization

### JWT Bearer Token Authentication (Phase 7.2 — primary)

The agent issues short-lived HS256 JWTs via `POST /api/auth/token`. All protected routes accept `Authorization: Bearer <token>` as the primary auth mechanism.

**Token issuance:**

```bash
curl -X POST http://localhost:9000/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"client_id": "YOUR_CLIENT_ID", "client_secret": "YOUR_CLIENT_SECRET", "tier": "read"}'
```

Response: `{"access_token": "eyJ...", "token_type": "bearer", "expires_in": 3600}`

**Token tiers:**

| Tier | Routes | JTI Blocklist |
|---|---|---|
| `read` | All read routes (`GET /api/*`, `POST /api/ask`) | No — tokens are reusable within their TTL |
| `admin` | All routes including `POST /api/trigger`, `POST /api/admin/purge` | **Yes** — JTI added to in-memory blocklist on first admin-route use (IA.3.084 replay resistance) |

**Configuration:**

```bash
AUTH_SECRET_KEY=<min-32-char-hex-secret>    # HS256 signing key
AUTH_CLIENT_ID=ims-agent-client             # Client identifier
AUTH_CLIENT_SECRET=<min-24-char-secret>     # Client password
JWT_EXPIRY_SECONDS=3600                     # 1-hour tokens
```

**Token security properties:**
- HS256 signatures — tampered tokens return HTTP 401
- `exp` claim enforced — expired tokens return HTTP 401
- `jti` claim unique per token — admin tokens are one-time-use
- JTI blocklist is in-memory; cleared on restart. For production CMMC deployments, persist the blocklist in Redis or a database.

### Static API Key Authentication (legacy / backward compat)

Retained for scripts and monitoring integrations that predate JWT. Evaluated after Bearer JWT fails or is absent.

| Key | Header | Grants Access To |
|---|---|---|
| `DASHBOARD_API_KEY` | `X-API-Key` | Read routes: `GET /api/state`, `GET /api/history`, `GET /api/status`, `GET /metrics`, `POST /api/ask` |
| `DASHBOARD_ADMIN_KEY` | `X-Admin-Key` | Admin routes: `POST /api/trigger`, `POST /api/admin/purge` |

**Single-key fallback:** if `DASHBOARD_ADMIN_KEY` is not set, `DASHBOARD_API_KEY` covers all routes.

**Generate keys:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Unauthenticated Endpoints

The `/health` and `/` (dashboard HTML) endpoints are unauthenticated by design — they contain no sensitive data and must be reachable by Docker health checks, load balancers, and browsers.

For production, protect the dashboard HTML behind a reverse proxy (nginx/Caddy) that enforces TLS and, optionally, HTTP Basic Auth or SSO before traffic reaches FastAPI.

---

## Key Age Tracking (SC.3.187)

`GET /health` includes key age fields when `KEY_CREATED_AT` is set in `.env`:

```json
{
  "key_age_days": 91,
  "key_age_warning": true
}
```

`key_age_warning: true` when `key_age_days > 90`. Set `KEY_CREATED_AT=YYYY-MM-DD` in `.env` after every credential rotation. See `docs/DR_RUNBOOK.md §9` for the full rotation procedure for all 6 credential types.

---

## SIEM Integration (AU.3.045)

When `SIEM_SYSLOG_HOST` is set, `agent/siem.py` attaches a `SysLogHandler` to the root logger at startup. All `WARNING+` events — including all `action=audit_*` log lines — are forwarded to the configured syslog endpoint via UDP.

```bash
SIEM_SYSLOG_HOST=192.168.1.100
SIEM_SYSLOG_PORT=514
```

The handler is idempotent — calling `configure_siem_logging()` twice does not add duplicate handlers.

**Key audit log events:**

| Pattern | Meaning |
|---|---|
| `action=audit_auth_failure` | JWT or API key rejected — investigate for brute force |
| `action=audit_token_issued` | JWT issued — correlate with client activity |
| `action=audit_admin_action` | Admin route used — track trigger and purge operations |
| `action=audit_jti_blocked` | Admin JTI replay attempt blocked |
| `action=cycle_start` / `cycle_complete` | Normal cycle lifecycle |
| `action=validation_hold` | Input flagged for PM review |

---

## Incident Response (IR.2.092)

See `docs/IR_PLAN.md` for the full incident response plan. Summary:

| Severity | Classification | Initial Response Time |
|---|---|---|
| P1 | Confirmed breach of CUI / schedule data | Immediate — isolate within 1 hour |
| P2 | Suspected breach or active attack | 4 hours |
| P3 | Single failed authentication / anomaly | 24 hours |
| P4 | Policy violation / misconfiguration | 72 hours |

Trigger an incident immediately if:
- `action=audit_auth_failure` rate exceeds normal baseline
- A credential is suspected of exposure
- `key_age_warning: true` in health check (> 90 day key)

---

## Secrets Management

**Rules:**
- All credentials are stored in environment variables, never hardcoded
- `.env` is gitignored and never committed
- Container images never contain secrets (`.env` excluded via `.dockerignore`)
- In production, use a secrets manager (AWS Secrets Manager, HashiCorp Vault, Kubernetes Secrets) to inject env vars

**Credentials the agent holds:**

| Credential | Env Var | Rotation Procedure |
|---|---|---|
| Anthropic API key | `ANTHROPIC_API_KEY` | `DR_RUNBOOK.md §9.1` |
| Dashboard read key | `DASHBOARD_API_KEY` | `DR_RUNBOOK.md §9.2` |
| Dashboard admin key | `DASHBOARD_ADMIN_KEY` | `DR_RUNBOOK.md §9.2` |
| JWT signing secret | `AUTH_SECRET_KEY` | `DR_RUNBOOK.md §9.3` |
| JWT client credentials | `AUTH_CLIENT_ID` / `AUTH_CLIENT_SECRET` | `DR_RUNBOOK.md §9.4` |
| Teams bot secret | `TEAMS_BOT_APP_SECRET` | `DR_RUNBOOK.md §9.5` |
| Slack webhook | `SLACK_WEBHOOK_URL` | `DR_RUNBOOK.md §9.6` |
| ElevenLabs | `ELEVENLABS_API_KEY` | Rotate in ElevenLabs console |
| Azure ACS | `ACS_CONNECTION_STRING` | Rotate in Azure Portal |

Rotate all credentials immediately on any P1/P2 incident declaration. Rotate proactively every 90 days — use `KEY_CREATED_AT` in `.env` and the `key_age_warning` health check field to track age.

---

## Data Classification and Handling

### Data in the system

| Data Type | Classification | Storage Location | Transmitted To |
|---|---|---|---|
| IMS XML (task names, dates, percent complete) | Sensitive — program schedule | `data/` directory | Anthropic API (cloud)* |
| CAM interview transcripts | Sensitive — personnel statements | Ephemeral (in-memory only during cycle) | Anthropic API (cloud)* |
| Cycle reports and analysis | Sensitive — schedule intelligence | `reports/` directory | Slack webhook, email SMTP |
| Dashboard state JSON | Sensitive — schedule intelligence | `data/dashboard_state.json` | Browser (read-only) |
| Per-cycle IMS diffs | Sensitive — change history | `data/ims_exports/*_diff.json` | None (local only) |
| Logs | Operational | `logs/` directory | SIEM syslog (if configured) |

\* **ITAR/CUI programs:** See section below.

### Data NOT stored

- Audio recordings of CAM calls (not yet implemented; when implemented, must be encrypted at rest and deleted after transcription)
- CAM personal data beyond name and contact info in CAM directory
- LLM conversation history (no persistent conversation context between Q&A queries)
- JWT JTI blocklist is in-memory only (cleared on restart)

---

## ITAR and CUI Compliance

**Current status: Non-compliant for ITAR/CUI data until all controls below are verified.**

All LLM inference uses the Anthropic cloud API by default. **IMS schedule data for ITAR-controlled programs must not be processed through the Anthropic cloud API.** The current configuration is suitable only for development/testing with synthetic data and unclassified, non-ITAR programs.

### Path to ITAR Compliance

1. **Replace the Anthropic API with an on-premises model.** All LLM calls route through `agent/llm_interface.py`. Single env var change:
   ```
   LLM_BASE_URL=http://your-ollama-host:11434
   ```
   When `LLM_BASE_URL` is set, `ANTHROPIC_API_KEY` is **not required** — all inference traffic goes to your local endpoint. No code changes required.

2. **Replace cloud TTS with on-premises TTS.** Set `VOICE_BRIEFING_ENABLED=false` or configure `AZURE_SPEECH_KEY` with an on-prem Azure Speech endpoint.

3. **Verify Slack/email content.** Review what schedule data is included in notifications; may require using internal endpoints.

4. **Complete pre-CUI checklist** (from `docs/CMMC_GAP.md`):
   - [ ] `LLM_BASE_URL` set to on-prem Ollama endpoint
   - [ ] `ANTHROPIC_API_KEY` not configured
   - [ ] ElevenLabs TTS replaced with on-prem TTS
   - [ ] Slack webhook pointing to internal Slack instance
   - [ ] SMTP pointing to internal mail server
   - [ ] Teams bot running in customer M365 tenant
   - [ ] Independent security review completed
   - [ ] Data-at-rest encryption confirmed at host level

---

## Network Security

### Port exposure

- Port **9000**: dashboard and API — **never expose directly to untrusted networks**
- All other services: no ports exposed by the agent

### Recommended network topology

```
Internet / Intranet
       │
    [nginx/Caddy — TLS termination, auth]
       │
    [ims-agent:9000 — internal only]
       │
    [Anthropic API / Slack / Email — outbound only]
```

### Outbound allowlist

The agent only needs outbound access to:

| Endpoint | Port | Purpose |
|---|---|---|
| `api.anthropic.com` | 443 | LLM inference |
| `api.elevenlabs.io` | 443 | TTS (optional) |
| Your Slack webhook URL | 443 | Cycle notifications |
| Your SMTP server | 587 | Email notifications |
| Your SIEM syslog host | 514 (UDP) | Audit log forwarding (if configured) |

Block all other outbound traffic at the host firewall or container network policy.

---

## Input Validation

- Q&A questions: max 500 characters, stripped of leading/trailing whitespace, must be non-empty
- JWT payloads: validated by PyJWT; `exp` and `iss` enforced automatically
- Cycle trigger: no input parameters; protected by admin key or admin-tier JWT
- IMS XML: parsed with stdlib `xml.etree.ElementTree` — no DTD processing, no external entity resolution (safe against XXE)

**LLM prompt injection:** The Q&A engine passes user questions to the Anthropic API with grounding instructions. The system prompt instructs the model to answer only from provided schedule data. Adversarial inputs are possible but limited in impact — the model has no ability to write files, execute code, or access external systems.

---

## Audit Trail

Every significant agent action is logged with `action=` prefix:

```
action=cycle_start, action=cycle_complete, action=cam_interview_start
action=validation_hold, action=llm_call, action=tool_call, action=manual_trigger_api
action=audit_auth_failure, action=audit_token_issued, action=audit_admin_action
action=audit_jti_blocked
```

Logs are append-only by the application. For production, direct log output (`LOG_FORMAT=json`) to an append-only log aggregator and configure `SIEM_SYSLOG_HOST` to forward `WARNING+` events to your SIEM platform.

---

## CMMC Level 2 Compliance Status

See `docs/CMMC_GAP.md` for the full gap analysis. Summary of Phase 7.2 remediations:

| Control | Status | Implementation |
|---|---|---|
| AC.1.001 — Authorized access | ✅ REMEDIATED | JWT Bearer tokens; all `/api/*` routes protected |
| IA.3.083 — Strong authentication | ✅ REMEDIATED | Admin-tier JWT (short-lived, signed) required for write routes |
| IA.3.084 — Replay resistance | ✅ REMEDIATED | Admin-tier JTI blocklisted after first use |
| SC.3.187 — Key management | ✅ REMEDIATED | `key_age_days` + `key_age_warning` in `/health`; rotation runbook in `DR_RUNBOOK.md §9` |
| IR.2.092 — Incident response | ✅ REMEDIATED | `docs/IR_PLAN.md` (P1–P4 classification, procedures, post-incident review) |
| AU.3.045 — SIEM / log review | ✅ REMEDIATED | `agent/siem.py` forwards `WARNING+` to configured syslog endpoint |

---

## Dependency Security

Last audit: **2026-05-03**

| Package | Version | CVEs | Status |
|---|---|---|---|
| PyJWT | 2.12.1 | None found | Clean |
| pip | 26.0.1 | CVE-2026-3219 (no fix available) | Monitor; no runtime impact |
| All other dependencies | — | None found | Clean |

Run `pip-audit` before each production deployment:
```bash
pip install pip-audit
pip-audit
```

Address any HIGH or CRITICAL findings before deploying.
