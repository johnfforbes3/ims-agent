# IMS Agent — Disaster Recovery Runbook

**Version:** 1.0  
**Date:** 2026-05-03  
**Owner:** Program owner / DevOps lead  
**RTO Target:** 4 hours (schedule agent back online; first CAM interview delayed by ≤1 cycle)  
**RPO Target:** 1 cycle (at most one week of IMS updates lost; all prior cycles are in `data/ims_exports/`)

---

## When to Use This Runbook

Use this runbook when:
- The IMS Agent process has crashed and does not self-recover
- The host machine is unresponsive or destroyed
- A data directory has been accidentally deleted or corrupted
- A storage volume is full and the agent cannot write

Do NOT use this runbook for:
- Normal cycle failures (check `GET /health` and logs; retry `POST /api/trigger`)
- Network connectivity issues to Teams/Anthropic (transient; agent retries automatically)
- A single CAM not responding (below threshold; cycle proceeds without them)

---

## Section 1: Prerequisites

Before starting recovery, gather:

| Item | Where to find it |
|---|---|
| Last known IMS file | `data/ims_exports/` directory on the failed host, or off-node backup |
| `.env` file | Backup copy (never in git); or reconstruct from secrets manager |
| `data/cam_directory.json` | Backup copy |
| `data/cam_identity_map.json` | Backup copy |
| Python 3.12+ | Install from python.org if not on new machine |
| Git access | Clone from `https://github.com/johnfforbes3/ims-agent.git` |

---

## Section 2: Startup from a Clean Machine

### Step 1: Clone and install

```bash
git clone https://github.com/johnfforbes3/ims-agent.git
cd ims-agent
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### Step 2: Restore `.env`

Copy `.env` from backup or rebuild from secrets manager.

```bash
# Minimum required variables for production:
ANTHROPIC_API_KEY=sk-ant-...     # or LLM_BASE_URL for on-prem
IMS_FILE_PATH=data/sample_ims.xml
SCHEDULE_CRON=0 6 * * 1
CALL_TRANSPORT=teams_chat        # or simulated
MSAL_CLIENT_ID=...
MSAL_TENANT_ID=...
```

Verify: `python main.py --trigger` (simulated transport) → should produce a report.

### Step 3: Restore data directory

From the failed host (if accessible) or from backup:

```bash
# Copy the last known good IMS files
cp backup/ims_exports/latest_ims.xml data/sample_ims.xml
cp -r backup/ims_exports/ data/ims_exports/
cp -r backup/ims_master/ data/ims_master/
cp backup/cam_directory.json data/cam_directory.json
cp backup/cam_identity_map.json data/cam_identity_map.json
cp backup/cycle_history.json data/cycle_history.json
```

Verify IMS file is parseable:
```bash
python -c "from agent.file_handler import IMSFileHandler; print(len(IMSFileHandler('data/sample_ims.xml').parse()), 'tasks')"
```

### Step 4: Verify IMS master

```bash
python main.py --init-mpp
```

Expected output: `Done. Master IMS folder: data/ims_master/`

### Step 5: Start the agent

```bash
python main.py --schedule
```

Expected output:
```
Transport: teams_chat
Scheduler started — cron='0 6 * * 1' tz=America/New_York
Next cycle: YYYY-MM-...
Dashboard: http://localhost:9000
```

### Step 6: Smoke test

```bash
curl http://localhost:9000/health
# Expected: {"status":"healthy", "state_file_present":..., "cycle_active":false}

curl -X POST http://localhost:9000/api/trigger
# Expected: {"status":"triggered","message":"Cycle started in background"}
```

### Step 7: Verify cycle completes

Monitor `GET /api/status` until `cycle_active: false`.
Check `GET /api/state` for `schedule_health`, `report_path`, and `cams_responded`.

---

## Section 3: Data Directory Corruption

### Lost `data/cycle_history.json`

Impact: Dashboard history will be empty. No functional impact — next cycle re-creates the file.

```bash
echo '[]' > data/cycle_history.json
```

### Lost `data/dashboard_state.json`

Impact: Dashboard shows no data until next cycle completes. No functional impact.

```bash
# Just delete it; it will be recreated on next cycle
rm data/dashboard_state.json
```

### Lost `data/sample_ims.xml` (working XML)

Restore from `data/ims_master/` (most recent timestamped file):

```bash
# Find the most recent master
ls data/ims_master/
# Copy it to the working XML
cp "data/ims_master/IMS_YYYY-MM-DD_HHMMz.xml" data/sample_ims.xml
```

### Lost `data/ims_master/` (master source-of-truth)

Restore from `data/ims_exports/` (versioned copies):

```bash
# Find the most recent export
ls data/ims_exports/
# Re-seed ims_master from the most recent versioned export
mkdir -p data/ims_master/
cp "data/ims_exports/CYCLE_ID_sample_ims.xml" data/sample_ims.xml
python main.py --init-mpp
```

### Lost `data/pending_approvals/`

Approval records are lost. CAM inputs from the held cycle cannot be replayed.
Action: Re-run the affected cycle via `POST /api/trigger` after the data directory is restored.

---

## Section 4: Storage Full

### Symptom
`action=cycle_failed error=OSError(28, 'No space left on device')` in logs.

### Resolution
```bash
# Check disk usage
df -h .

# Run purge to remove old cycle data
python -c "from agent.cycle_runner import CycleRunner; print(CycleRunner.purge_old_data())"

# Or via API if server is still running
curl -X POST http://localhost:9000/api/admin/purge -H "X-Admin-Key: $DASHBOARD_ADMIN_KEY"

# Compress old IMS exports
gzip data/ims_exports/OLD_CYCLE_ID_*.xml

# If still full, move logs off-box
mv logs/ims_agent.log /tmp/ims_agent_backup.log && touch logs/ims_agent.log
```

---

## Section 5: Pending Approval During Recovery

If a cycle was in validation hold (waiting for PM approval) when the process crashed:

1. Check `data/pending_approvals/` — approval records persist across restarts.
2. Restart the agent: `python main.py --schedule`
3. Check `GET /api/approvals` — pending records will reappear.
4. PM can approve via `POST /api/approvals/{cycle_id}/approve`.

The approval is re-entrant — the record stays `"pending"` until the IMS write succeeds (Phase 6.0.4 fix).

---

## Section 6: LLM API Failure During Cycle

The agent now retries LLM calls up to 3 times with exponential backoff (1s, 2s, 4s) before failing the cycle. If the cycle still fails:

1. Check logs for `action=llm_exhausted_retries` — this confirms the API was unreachable after all retries.
2. Verify `ANTHROPIC_API_KEY` is valid: `curl https://api.anthropic.com/v1/messages -H "x-api-key: $ANTHROPIC_API_KEY"`
3. Check Anthropic status page: https://status.anthropic.com
4. If using `LLM_BASE_URL` (local Ollama): verify the Ollama service is running.
5. Once the LLM is reachable, re-trigger: `POST /api/trigger`.

---

## Section 7: Post-Recovery Checklist

After completing recovery steps, verify:

- [ ] `GET /health` returns `{"status":"healthy"}`
- [ ] `GET /api/state` returns valid state (or 404 if no cycle yet — acceptable)
- [ ] One full cycle completed successfully (`GET /api/status` → `cycle_active: false` after trigger)
- [ ] `data/ims_master/` contains exactly one file
- [ ] Report generated at `reports/YYYY-MM-DD_ims_report.md`
- [ ] Slack notification sent (if configured)
- [ ] Dead man's switch not alarming: `GET /health` → `deadman_alert: false`
- [ ] Next scheduled cycle confirmed: check logs for `Scheduler started — next=...`

---

## Section 8: Backup Procedure

Run after every successful cycle (or automate with cron):

```bash
# Off-node backup target (set IMS_BACKUP_PATH in .env)
BACKUP_DIR=/path/to/backup/$(date +%Y%m%d)
mkdir -p "$BACKUP_DIR"

# IMS source of truth
cp -r data/ims_master/ "$BACKUP_DIR/"
cp -r data/ims_exports/ "$BACKUP_DIR/"

# Configuration
cp data/cam_directory.json "$BACKUP_DIR/"
cp data/cam_identity_map.json "$BACKUP_DIR/"
cp data/cycle_history.json "$BACKUP_DIR/"

# Verify backup is valid
python -c "import json; json.load(open('$BACKUP_DIR/cycle_history.json'))" && echo "BACKUP OK"
```

For cloud backup, replace `cp -r` with `aws s3 sync` / `az storage blob upload-batch` as appropriate.

---

*This runbook was written for Windows deployment. Adjust paths for Linux (use `/` separators, `source .venv/bin/activate`).*

---

## Section 9: Credential Rotation (SC.3.187)

Rotate credentials immediately if any of the following occur:
- A P1/P2 security incident is declared (see `docs/IR_PLAN.md`)
- A credential is suspected of exposure (log review, audit alert)
- Any team member with credential access departs
- Proactively every 90 days (set `KEY_CREATED_AT` in `.env` to track age)

The `GET /health` endpoint includes `key_age_days` and `key_age_warning: true`
when `KEY_CREATED_AT` is older than 90 days.

### 9.1 — Anthropic API Key

1. Go to https://console.anthropic.com → **API Keys** → **Create Key**.
2. Copy the new key.
3. Update `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-<new-key>
   KEY_CREATED_AT=<YYYY-MM-DD>
   ```
4. Restart the agent: `python main.py --serve` (hot-reload via `load_dotenv(override=True)` picks up the new key on the next LLM call without restart, but restart is recommended after a suspected breach).
5. Revoke the old key in the Anthropic Console.

### 9.2 — Dashboard API Keys

1. Generate a new key:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Update `.env`:
   ```
   DASHBOARD_API_KEY=<new-read-key>
   DASHBOARD_ADMIN_KEY=<new-admin-key>
   ```
3. Distribute new keys to all API consumers (monitoring scripts, Grafana, CI).
4. Restart the dashboard server to pick up the new values.

### 9.3 — JWT Signing Secret (AUTH_SECRET_KEY)

Rotating this key **immediately invalidates all outstanding JWTs**. All
API clients must re-authenticate via `POST /api/auth/token`.

1. Generate a new secret (minimum 32 bytes):
   ```
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Update `.env`:
   ```
   AUTH_SECRET_KEY=<new-hex-secret>
   ```
3. Restart the dashboard server.
4. All existing Bearer tokens are now invalid. Clients must call
   `POST /api/auth/token` with their `AUTH_CLIENT_ID` / `AUTH_CLIENT_SECRET`
   to obtain fresh tokens.

### 9.4 — JWT Client Credentials (AUTH_CLIENT_ID / AUTH_CLIENT_SECRET)

1. Choose a new `AUTH_CLIENT_SECRET` (minimum 24 chars):
   ```
   python -c "import secrets; print(secrets.token_urlsafe(24))"
   ```
2. Update `.env`:
   ```
   AUTH_CLIENT_ID=<client-id>
   AUTH_CLIENT_SECRET=<new-secret>
   ```
3. Restart the dashboard server.
4. Distribute the new secret to all JWT-using clients.

### 9.5 — Teams Bot Client Secret

1. Go to Azure Portal → **App Registrations** → select the IMS Agent bot app.
2. **Certificates & secrets** → **New client secret** → set expiry → **Add**.
3. Copy the new secret value (shown once).
4. Update `.env`:
   ```
   TEAMS_BOT_CLIENT_SECRET=<new-secret>
   ```
5. Restart the agent.
6. Delete the old secret in Azure Portal.

### 9.6 — Slack Webhook URL

1. Go to https://api.slack.com/apps → select your app → **Incoming Webhooks**.
2. Deactivate the old webhook URL.
3. Create a new webhook for the same channel.
4. Update `.env`:
   ```
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/<new-path>
   ```
5. The next `send_slack()` call picks up the new URL automatically (hot-reload).

### 9.7 — Rotation Verification

After any credential rotation, verify the system is operational:

```bash
# Health check — confirm key_age_warning is false after updating KEY_CREATED_AT
curl http://localhost:9000/health

# Trigger a test cycle (requires admin key or admin JWT)
curl -X POST http://localhost:9000/api/trigger \
     -H "X-Admin-Key: <new-admin-key>"

# Confirm Slack notification arrives within 5 minutes
```

If any step fails, check logs for `action=audit_auth_failure` or
`action=llm_exhausted_retries` events and address the root cause before
declaring the rotation complete.
