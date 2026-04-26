# IMS Agent — Security Architecture

This document describes the security posture, data handling policy, and compliance considerations for the IMS Agent.

---

## Authentication and Authorization

### API Authentication (Phase 5)

All `/api/*` endpoints are protected by an API key passed in the `X-API-Key` request header. Set `DASHBOARD_API_KEY` in `.env` to a strong random value:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

If `DASHBOARD_API_KEY` is empty, auth is disabled — **acceptable only on a loopback-only local dev machine, never in any networked deployment.**

The `/health` endpoint is unauthenticated by design — it contains no sensitive data and must be reachable by Docker health checks and load balancers without credentials.

### Dashboard HTML

The dashboard HTML at `/` is currently not protected by the API key (browsers don't send custom headers on page loads). For production:

- Put the dashboard behind a reverse proxy (nginx/Caddy) that enforces HTTP Basic Auth or SSO before traffic reaches the FastAPI app
- Or add session/cookie authentication as a Phase 5 follow-on (tracked in TD-017)

### Role-Based Access Control

RBAC is not yet implemented (planned for Phase 5). Current effective roles:

| Role | Access |
|---|---|
| Anyone with `DASHBOARD_API_KEY` | Full API access (read state, trigger cycles, ask questions) |
| Anyone who can reach port 8080 | Dashboard HTML (read-only view) |

---

## Secrets Management

**Rules:**
- All credentials are stored in environment variables, never hardcoded
- `.env` is gitignored and never committed
- Container images never contain secrets (`.env` excluded via `.dockerignore`)
- In production, use a secrets manager (AWS Secrets Manager, HashiCorp Vault, Kubernetes Secrets) to inject env vars rather than passing a `.env` file to Docker

**Credentials the agent holds:**
- `ANTHROPIC_API_KEY` — LLM inference (outbound)
- `DASHBOARD_API_KEY` — API authentication
- `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` — Slack integration
- `EMAIL_USER`, `EMAIL_PASSWORD` — SMTP
- `ELEVENLABS_API_KEY` — TTS voice synthesis
- `ACS_CONNECTION_STRING` — Azure ACS (when real voice enabled)

---

## Data Classification and Handling

### Data in the system

| Data Type | Classification | Storage Location | Transmitted To |
|---|---|---|---|
| IMS XML (task names, dates, percent complete) | Sensitive — program schedule | `data/` directory | Anthropic API (cloud)* |
| CAM interview transcripts | Sensitive — personnel statements | Ephemeral (in-memory only during cycle) | Anthropic API (cloud)* |
| Cycle reports and analysis | Sensitive — schedule intelligence | `reports/` directory | Slack webhook, email SMTP |
| Dashboard state JSON | Sensitive — schedule intelligence | `data/dashboard_state.json` | Browser (read-only) |
| Logs | Operational | `logs/` directory | None |

\* **ITAR/CUI programs:** See section below.

### Data NOT stored

- Audio recordings of CAM calls (not yet implemented; when implemented, must be encrypted at rest and deleted after transcription)
- CAM personal data beyond name and contact info in CAM directory
- LLM conversation history (no persistent conversation context between Q&A queries)

---

## ITAR and CUI Compliance

**Current status (Phases 1–4): Non-compliant for ITAR data.**

All LLM inference uses the Anthropic cloud API. **IMS schedule data for ITAR-controlled programs must not be processed through the Anthropic API.** The current configuration is suitable only for:
- Development and testing with synthetic data
- Unclassified, non-ITAR programs

### Path to ITAR Compliance (Phase 5)

1. **Replace the Anthropic API with an on-premises model.** All LLM calls are routed through `agent/llm_interface.py`. The swap requires:
   - Deploy an Ollama instance (or similar) inside the client network
   - Set `ANTHROPIC_BASE_URL` to the local endpoint, or replace the client initialization in `LLMInterface.__init__()`
   - Test synthesis quality with the local model; adjust prompts if needed

2. **Confirm no other outbound calls carry program data.** Current outbound calls:
   - Anthropic API (LLM inference) — replace with on-prem
   - ElevenLabs API (TTS) — replace with Azure TTS (on-prem capable) or local TTS
   - Slack webhook (cycle summaries) — review what data is included; may be acceptable on unclassified networks
   - SMTP (email) — review what data is included

3. **Document data flow for program security officer review.**

---

## Network Security

### Port exposure

- Port 8080: dashboard and API — **never expose directly to untrusted networks**
- All other services: no ports exposed by the agent

### Recommended network topology

```
Internet / Intranet
       │
    [nginx/Caddy — TLS termination, auth]
       │
    [ims-agent:8080 — internal only]
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

Block all other outbound traffic at the host firewall or container network policy.

---

## Input Validation

- Q&A questions: max 500 characters, stripped of leading/trailing whitespace, must be non-empty
- Cycle trigger: no input parameters; protected by API key
- IMS XML: parsed with stdlib `xml.etree.ElementTree` — no DTD processing, no external entity resolution (safe against XXE)

**LLM prompt injection:** The Q&A engine passes user questions to the Anthropic API with grounding instructions. The system prompt instructs the model to answer only from provided schedule data. Adversarial inputs are possible but limited in impact — the model has no ability to write files, execute code, or access external systems.

---

## Audit Trail

Every significant agent action is logged with `action=` prefix:

```
action=cycle_start, action=cycle_complete, action=cam_interview_start
action=validation_hold, action=llm_call, action=tool_call, action=manual_trigger_api
```

Logs are append-only by the application. For production, direct log output to an append-only log aggregator (Datadog, CloudWatch, ELK) and restrict write access on the `logs/` directory.

---

## Dependency Security

Last audit: **2026-04-26**

| Package | Version | CVEs | Status |
|---|---|---|---|
| pip | 26.0.1 | CVE-2026-3219 (no fix available) | Monitor; no impact on runtime |
| All other dependencies | — | None found | Clean |

Run `pip-audit` before each production deployment:
```bash
pip install pip-audit
pip-audit
```

Address any HIGH or CRITICAL findings before deploying.
