# IMS Agent — Operations Guide

Day-to-day monitoring, troubleshooting, and maintenance for a running IMS Agent deployment.

---

## Health Check

The `/health` endpoint is unauthenticated and safe to poll from any uptime monitor:

```bash
curl http://localhost:8080/health
```

```json
{
  "status": "healthy",
  "uptime_seconds": 3601,
  "cycle_active": false,
  "state_file_present": true,
  "auth_enabled": true
}
```

`cycle_active: true` means a cycle is currently running — normal during the 8-10 minute window.

---

## Logs

### Viewing live logs

```bash
# Docker deployment
docker compose -f docker-compose.prod.yml logs -f ims-agent

# Bare process
tail -f logs/ims_agent.log
```

### Log format

Default format (text):
```
2026-04-26 10:47:47 INFO     agent.cycle_runner action=cycle_start cycle_id=20260426T104747Z
```

JSON format (set `LOG_FORMAT=json` in `.env`):
```json
{"ts": "2026-04-26T10:47:47", "level": "INFO", "logger": "agent.cycle_runner", "msg": "action=cycle_start cycle_id=20260426T104747Z"}
```

### Key log patterns to watch

| Pattern | Meaning |
|---|---|
| `action=cycle_start` | Cycle began |
| `action=cycle_complete` | Cycle finished successfully |
| `action=cycle_failed` | Cycle failed — check surrounding lines for cause |
| `action=validation_hold` | Input flagged; admin review needed |
| `action=tool_call` | Q&A tool invoked (float, dependencies, etc.) |
| `action=llm_call` | Anthropic API called |
| `level=ERROR` | Any error requiring attention |

---

## Cycle Management

### Check current status

```bash
curl -H "X-API-Key: KEY" http://localhost:8080/api/status
```

### Trigger a manual cycle

```bash
curl -X POST -H "X-API-Key: KEY" http://localhost:8080/api/trigger
```

Returns immediately; cycle runs in the background. Watch with `logs -f`.

### View cycle history

```bash
curl -H "X-API-Key: KEY" http://localhost:8080/api/history | python -m json.tool
```

### Cycle status files

Every cycle writes a status JSON to `reports/cycles/{cycle_id}_status.json`:

```bash
ls -lt reports/cycles/ | head -5       # most recent cycles
cat reports/cycles/20260426T104747Z_status.json | python -m json.tool
```

Key fields: `phase`, `cam_responses`, `validation_holds`, `timestamp`.

---

## Q&A Interface

### Via dashboard

Open `http://localhost:8080` — chat widget is in the bottom-right of the page.

### Via API

```bash
curl -X POST http://localhost:8080/api/ask \
     -H "X-API-Key: KEY" \
     -H "Content-Type: application/json" \
     -d '{"question": "What is the current schedule health?"}'
```

### Via Slack

```
/ims What are the top risks right now?
/ims What is the float on task SE-03?
/ims Who is behind schedule?
```

---

## Validation Holds

When the validation layer flags an anomaly, it logs a hold but does **not** block the cycle by default. To review:

```bash
grep "validation_hold" logs/ims_agent.log | tail -20
cat reports/cycles/$(ls -t reports/cycles/ | head -1) | python -m json.tool | grep -A5 "validation_holds"
```

Holds are logged but not currently surfaced on the dashboard (TD-015 — Phase 5 improvement).

---

## Backup and Restore

### What to back up

| Path | Contents | Frequency |
|---|---|---|
| `data/dashboard_state.json` | Latest cycle analysis | After each cycle |
| `data/cycle_history.json` | Rolling history | After each cycle |
| `data/snapshots/` | Timestamped IMS copies | After each cycle |
| `reports/cycles/` | Per-cycle status JSONs | After each cycle |
| `.env` | All credentials | On any change (store in secrets manager) |

### Docker volume backup

```bash
# Backup named volume to a tar archive
docker run --rm -v ims_data:/data -v $(pwd):/backup alpine \
    tar czf /backup/ims_data_$(date +%Y%m%d).tar.gz -C /data .
```

### Restore

```bash
# Restore from archive
docker run --rm -v ims_data:/data -v $(pwd):/backup alpine \
    tar xzf /backup/ims_data_20260426.tar.gz -C /data
```

---

## Rotating the API Key

1. Generate a new key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Update `DASHBOARD_API_KEY` in `.env`
3. Restart the container: `docker compose -f docker-compose.prod.yml up -d`
4. Update any scripts or integrations that use the old key

---

## Rotating the Anthropic API Key

1. Revoke the old key at console.anthropic.com
2. Generate a new key
3. Update `ANTHROPIC_API_KEY` in `.env`
4. Restart the container

---

## Updating the IMS File

1. Export the updated IMS from Microsoft Project as XML (File → Save As → XML)
2. Copy to `data/` (Docker deployment: `docker cp new.xml ims-agent:/app/data/sample_ims.xml`)
3. The next cycle will use the new file automatically
4. To trigger an immediate cycle: `POST /api/trigger`

---

## Common Issues

### Cycle starts but no CAM data collected

- Check that `CALL_TRANSPORT=mock` is set (simulator mode) or that ACS credentials are correct
- Look for `action=cam_interview_failed` in logs

### Slack messages not appearing

- Verify `SLACK_WEBHOOK_URL` is correct (for channel posts)
- For `/ims` command, verify `SLACK_APP_TOKEN` and `SLACK_BOT_TOKEN` are set and Socket Mode is enabled on the Slack app

### Dashboard shows stale data

- Check that the scheduler is running: `GET /api/status`
- Manually trigger a cycle to force an update
- If `dashboard_state.json` is corrupted, delete it and trigger a fresh cycle

### "No schedule data available" on Q&A

- No cycle has completed yet — trigger one first
- Or `data/dashboard_state.json` is missing/empty

### High Anthropic API costs

- Each Q&A question with tool use makes 1-5 API calls
- Direct-answer queries (health, top risks, critical path) make 0 API calls
- Review `LOG_LEVEL=DEBUG` output to count `action=llm_call` entries per cycle
