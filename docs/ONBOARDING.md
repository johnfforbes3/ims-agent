# IMS Agent — Customer Onboarding Checklist

**Version:** 1.0  
**Date:** 2026-05-03  
**Owner:** John Forbes  

This checklist covers everything needed to stand up the IMS Agent for a new customer (pilot or production). Work through each section in order — later sections depend on earlier ones.

---

## Section 1: Customer IT Prerequisites

These items must be completed by the customer's IT team before any agent setup begins.

| Item | Owner | Status | Notes |
|------|-------|--------|-------|
| M365 tenant ID provided to agent team | Customer IT | ⬜ | Format: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX |
| Azure Bot Service registration approved | Customer IT | ⬜ | Requires AAD Global Admin or Application Administrator |
| Teams admin consent for bot (allow external bot in tenant) | Customer IT | ⬜ | Teams Admin Center → Apps → Permission Policies |
| SMTP relay credentials provided (for email reports) | Customer IT | ⬜ | Or configure SMTP_HOST/SMTP_USER/SMTP_PASS in .env |
| Outbound network allowlist: `api.anthropic.com:443` | Customer IT | ⬜ | Required for Anthropic API; skip if using LLM_BASE_URL |
| Outbound network allowlist: `smba.trafficmanager.net:443` | Customer IT | ⬜ | Teams Bot Framework relay endpoint |
| Inbound HTTPS to agent host (port 443 or configured port) | Customer IT | ⬜ | For Teams bot webhook; requires fixed FQDN |
| CAM M365 accounts (or federation with customer AAD) | Customer IT | ⬜ | Needed for Teams chat interviews |

---

## Section 2: Customer Planner Prerequisites

| Item | Owner | Status | Notes |
|------|-------|--------|-------|
| Real IMS file exported from MS Project as XML | Customer Planner | ⬜ | File → Save As → XML Format (.xml) |
| CAM name list with task assignments | Customer Planner | ⬜ | Used to build `data/cam_directory.json` |
| Reporting cycle confirmed (weekly / biweekly / monthly) | PM + Planner | ⬜ | Sets `SCHEDULE_CRON` in .env |
| Interview window defined (day/time CAMs are available) | PM | ⬜ | Schedule cron to fire at start of interview window |

---

## Section 3: Agent Team Setup

### 3.1 Infrastructure

| Item | Owner | Status | Notes |
|------|-------|--------|-------|
| Agent host provisioned (VM or bare metal) | Agent Team | ⬜ | Minimum: 2 vCPU, 4 GB RAM, 20 GB disk |
| Python 3.12+ installed | Agent Team | ⬜ | `python --version` to verify |
| Fixed FQDN or ngrok-equivalent configured | Agent Team | ⬜ | Teams webhook requires a stable HTTPS endpoint |
| TLS certificate installed (not self-signed) | Agent Team | ⬜ | Let's Encrypt or customer PKI |
| Azure Bot Service created in customer tenant | Agent Team | ⬜ | Bot registration → Messaging Endpoint: `https://{FQDN}/bot/messages` |

### 3.2 Code Deployment

```bash
git clone https://github.com/johnfforbes3/ims-agent.git
cd ims-agent
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 3.3 Environment Configuration

Copy `.env.example` to `.env` and fill in all required values:

```bash
# LLM
ANTHROPIC_API_KEY=sk-ant-...    # or LLM_BASE_URL for on-prem

# IMS
IMS_FILE_PATH=data/sample_ims.xml

# Schedule
SCHEDULE_CRON=0 6 * * 1         # weekly Monday 6 AM
CALL_TRANSPORT=teams_chat        # or simulated for test runs

# Teams / Bot Framework
MSAL_CLIENT_ID=...
MSAL_TENANT_ID=...
MSAL_AUTHORITY=https://login.microsoftonline.com/{tenant-id}
BOT_APP_ID=...
BOT_APP_SECRET=...

# Dashboard auth
DASHBOARD_API_KEY=...
DASHBOARD_ADMIN_KEY=...

# Notifications
SLACK_WEBHOOK_URL=...            # optional
SMTP_HOST=...                    # optional
SMTP_USER=...
SMTP_PASS=...
PM_EMAIL=pm@customer.com
```

### 3.4 Data Initialization

```bash
# Copy customer IMS XML
cp /path/to/customer_ims.xml data/sample_ims.xml

# Verify it parses correctly
python -c "from agent.file_handler import IMSFileHandler; tasks = IMSFileHandler('data/sample_ims.xml').parse(); print(len(tasks), 'tasks loaded')"

# Initialize ims_master (creates data/ims_master/)
python main.py --init-mpp
```

Build `data/cam_directory.json` from planner's CAM list, or let the agent auto-build from IMS:

```bash
python -c "from agent.cam_directory import CAMDirectory; from agent.file_handler import IMSFileHandler; d=CAMDirectory(); d.load_from_ims(IMSFileHandler('data/sample_ims.xml').parse()); print(d.get_all_cams())"
```

### 3.5 Smoke Test (Simulated)

Before going live with Teams, run one simulated cycle:

```bash
CALL_TRANSPORT=simulated python main.py --trigger
```

Expected: a report appears in `reports/`, dashboard state written to `data/dashboard_state.json`, no errors in logs.

---

## Section 4: Pilot Go-Live

### 4.1 Pre-Launch Checklist

- [ ] Smoke test passes (Section 3.5)
- [ ] `GET /health` returns `{"status":"healthy"}`
- [ ] Teams bot responds to a test message in a direct chat
- [ ] PM notified of first cycle time
- [ ] CAMs briefed on interview format and expected response time
- [ ] Backup configured (Section 8 of DR_RUNBOOK.md)
- [ ] ISSO sign-off on SECURITY.md posture

### 4.2 First Live Cycle

1. `POST /api/trigger` or wait for scheduled cron
2. Monitor `GET /api/status` → `cycle_active` until false
3. Check `GET /api/state` → `schedule_health`, `cams_responded`
4. Review report at `GET /api/state` → `report_path`
5. Review diff at `GET /api/diff/{cycle_id}`

### 4.3 Pilot Acceptance Criteria

| Criterion | Target | Status |
|-----------|--------|--------|
| 4 consecutive unattended cycles, zero manual interventions | 4/4 | ⬜ |
| Planner confirms schedule accuracy ≥ manual Excel process | Pass | ⬜ |
| PM Q&A: 10 questions, all accurate, zero hallucinations | 10/10 | ⬜ |
| DR runbook: restore within RTO (4h) on simulated outage | < 4h | ⬜ |
| Audit diff reviewed each cycle; all changes traceable to CAM | Pass | ⬜ |

---

## Section 5: Contacts and Escalation

| Role | Name | Contact |
|------|------|---------|
| Agent Team Lead | John Forbes | forbes3x3@gmail.com |
| Customer PM | TBD | TBD |
| Customer Planner | TBD | TBD |
| Customer IT Lead | TBD | TBD |

---

*Refer to `docs/DR_RUNBOOK.md` for recovery procedures and `docs/SECURITY.md` for security posture.*
