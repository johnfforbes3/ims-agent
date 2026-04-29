# IMS Agent — Startup Runbook

Use this document to bring the IMS Agent back up after any period of downtime, or hand it to an AI agent to drive the startup autonomously.

---

## The 10-Second Version

Double-click **`START.bat`** in the project root.

It will activate the venv, seed `data/ims_master/` if empty, start the scheduler + dashboard, and open http://localhost:9000 in your browser automatically.

---

## Full Manual Startup (step by step)

All commands are run from the project root:
```
C:\Users\forbe\OneDrive\Documents\AI Projects\04 - IMS AGENT\ims-agent\
```

### Step 1 — Activate the virtual environment

```bat
.venv\Scripts\activate.bat
```

Confirm it worked: `python --version` should show Python 3.13.x.

### Step 2 — Verify .env is populated

```bat
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('key:', os.getenv('ANTHROPIC_API_KEY','MISSING')[:8])"
```

Expected: first 8 characters of your key (not `MISSING`). If missing, edit `.env` and set `ANTHROPIC_API_KEY`.

### Step 3 — Check data/ims_master/ has a file

```bat
python -c "from pathlib import Path; files=list(Path('data/ims_master').glob('*.*')); print('master files:', len(files), [f.name for f in files])"
```

Expected: `master files: 1 ['IMS_YYYY-MM-DD_HHMMz.mpp']`

If it shows `master files: 0`, seed it:

```bat
python main.py --init-mpp
```

This converts `data/sample_ims.xml` into a timestamped `.mpp` in `data/ims_master/`. Requires MS Project (COM) or the MPXJ/JVM backend. See Troubleshooting if it fails.

### Step 4 — Run the unit tests (optional but recommended after a gap)

```bat
python -m pytest tests/ -q --tb=short
```

Expected: `242 passed`. If any fail, see the TECHNICAL-DEBT.md register for known issues.

### Step 5 — Start the agent

**Option A — Full production mode** (scheduler fires every Monday 06:00 + dashboard always live):
```bat
python main.py --schedule
```

**Option B — Dashboard only** (no automatic cycles; fire manually via the UI or API):
```bat
python main.py --serve
```

**Option C — Fire one cycle right now** (runs once, then exits):
```bat
python main.py --trigger
```

The dashboard is at **http://localhost:9000**

### Step 6 — Verify it's healthy

```bat
curl -s http://localhost:9000/health
```

Expected:
```json
{"status":"healthy","uptime_seconds":...,"cycle_active":false,"auth_enabled":false,"state_file_present":true}
```

Check the dashboard: `http://localhost:9000` should show:
- Schedule health (RED / YELLOW / GREEN)
- Last cycle ID and timestamp
- CAM response status for each CAM
- Master IMS path in the header

---

## Common Issues & Fixes

### "ims_master is empty" after coming back

The `data/ims_master/` folder only ever holds **one** file. If it's empty, run:
```bat
python main.py --init-mpp
```
This seeds it from `data/sample_ims.xml`. Only needed once — every cycle run after that keeps it updated automatically.

### COM backend says "BLOCKED (C2R AppV isolation)"

MS Project's Click-to-Run packaging occasionally needs a repair to allow COM automation:

1. Open **Settings → Apps → Microsoft Project Professional → ... → Modify → Quick Repair**
2. Wait 5–10 minutes for the repair to complete
3. Re-run `python main.py --init-mpp` to verify

The MPXJ/JVM backend (Java-based) is the fallback and works without this repair. Check which is active:
```bat
python -c "from agent.mpp_converter import diagnose; print(diagnose())"
```

### "No module named ..." / import errors

The venv is not active, or dependencies are stale:
```bat
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

### Dashboard returns 401 / Unauthorized

The `.env` has `DASHBOARD_API_KEY` set. Include it in requests:
```bat
curl -s -H "X-API-Key: YOUR_KEY" http://localhost:9000/api/state
```
Or temporarily unset `DASHBOARD_API_KEY` in `.env` for local dev.

### Port 9000 is already in use

Something else is on the port (maybe a previous server instance didn't exit):
```bat
REM Find the PID on port 9000 and kill it
for /f "tokens=5" %a in ('netstat -aon ^| findstr :9000') do taskkill /f /pid %a
```
Or change the port in `.env`: `DASHBOARD_PORT=9001`

### Cycle stuck / no report being generated

Check the log:
```bat
python -c "
from pathlib import Path
log = Path('logs/ims_agent.log')
lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
print('\n'.join(lines[-40:]))
"
```

Look for `[ERROR]` or `[WARNING]` lines. Common causes:
- LLM API key expired → regenerate at console.anthropic.com and update `.env`
- IMS file missing → `VALIDATION_ALLOW_BACKWARDS=false` and backward movement in schedule
- Lock stuck → restart the server (cycle lock resets on startup)

---

## Stopping the Agent

Press **Ctrl+C** in the terminal where `python main.py --schedule` is running.

The scheduler stops cleanly. The dashboard persists `data/dashboard_state.json` so the next startup picks up where it left off.

---

## Quick Reference — All CLI Modes

| Command | What it does |
|---------|-------------|
| `python main.py --schedule` | **Production**: cron scheduler + dashboard. Fires automatically every Monday 06:00 ET. |
| `python main.py --serve` | **Dashboard only**: no automatic cycles; use Trigger button or API to fire manually. |
| `python main.py --trigger` | **One shot**: fire one full cycle right now, then exit. Good for on-demand runs. |
| `python main.py --init-mpp` | **Seed**: convert `data/sample_ims.xml` → timestamped `.mpp` in `data/ims_master/`. Run after first checkout or if master folder is empty. |
| `python main.py --demo` | Phase 2 simulated voice interview demo (no Teams required). |
| `python main.py --demo-chat --cam "Alice Nguyen"` | Teams chat interview via Bot Framework (requires ngrok + Azure Bot Service). |
| `python main.py --cam-responder` | Start Graph API auto-responders for all configured fake CAM accounts. |
| `python -m pytest tests/ -q` | Run all 242 unit tests. |

---

## Quick Reference — Key URLs (server must be running)

| URL | What it shows |
|-----|--------------|
| http://localhost:9000 | Main dashboard (schedule health, milestones, CAM status) |
| http://localhost:9000/health | JSON health check (no auth required) |
| http://localhost:9000/api/state | Full dashboard state JSON |
| http://localhost:9000/api/history | Rolling cycle history |
| http://localhost:9000/metrics | Performance counters |

---

## Quick Reference — Key Data Files

| File | Purpose |
|------|---------|
| `data/sample_ims.xml` | Working IMS (edit this to change the schedule) |
| `data/ims_master/` | Single timestamped `.mpp` — the authoritative schedule written after each cycle |
| `data/ims_exports/` | All versioned XML + MPP copies per cycle; `latest_ims.xml` always current |
| `data/dashboard_state.json` | Live state written after every cycle; persists across restarts |
| `data/cycle_history.json` | Last 52 cycle summaries |
| `data/pending_approvals/` | Held cycles awaiting PM approval |
| `.env` | All secrets and configuration — **never commit this** |
| `logs/ims_agent.log` | Unified log (3–5 MB typical per week) |
| `reports/` | Generated Markdown reports (one per cycle) |

---

## Teams Chat Mode (when returning after a gap)

If the M365 trial tenant has gone stale:
1. Check tenant is still active at https://admin.microsoft.com (trial expires 2026-05-25)
2. If MSAL token cache is stale, re-run device-code auth: `python main.py --cam-responder`
3. ngrok URL changes on each restart — update Azure Bot Service messaging endpoint, or run `python main.py --demo-chat` which auto-updates via `ngrok_updater.py`

---

## Instructions for an AI Agent

If you are an AI agent reading this to bring the system up, follow these steps in order:

1. **Read environment**: Run `python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('key:', bool(os.getenv('ANTHROPIC_API_KEY')), 'port:', os.getenv('DASHBOARD_PORT','9000'))"`. Confirm `key: True`. If False, stop and tell the user to add `ANTHROPIC_API_KEY` to `.env`.

2. **Check master IMS**: Run `python -c "from pathlib import Path; f=list(Path('data/ims_master').glob('*.*')); print(len(f), [x.name for x in f])"`. If count is 0, run `python main.py --init-mpp`. If `--init-mpp` fails (no COM, no JVM), note the error but continue — the cycle runner will fall back to `data/sample_ims.xml`.

3. **Run unit tests**: Run `python -m pytest tests/ -q --tb=short 2>&1 | tail -5`. If all 242 pass, proceed. If failures exist, report them before starting the server.

4. **Start the server**: Run `python main.py --schedule` (blocks). The server is ready when you see "Dashboard: http://localhost:9000".

5. **Verify health**: In a separate context, `curl -s http://localhost:9000/health`. Confirm `"status":"healthy"`.

6. **Optional — fire a cycle immediately**: `curl -s -X POST http://localhost:9000/api/trigger`. Wait for the cycle to complete (check `/api/status` — `cycle_active: false` means done), then verify the report at `/api/state`.

All working directory paths are relative to the project root:
`C:\Users\forbe\OneDrive\Documents\AI Projects\04 - IMS AGENT\ims-agent\`

The `.env` file in that directory contains all secrets. Do not display secret values.

---

*Last updated: 2026-04-29*
