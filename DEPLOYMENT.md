# IMS Agent — Deployment Guide

This guide walks through deploying the IMS Agent on a single Linux host using Docker Compose. Estimated time: 30-60 minutes on a clean machine.

**Prerequisites:** Docker 24+, Docker Compose v2, and a copy of the `.env` file with all required secrets filled in.

---

## 1. Prepare the Host

```bash
# Recommended: Ubuntu 22.04 LTS or RHEL 8+
# Minimum specs: 2 vCPU, 4 GB RAM, 20 GB disk

# Install Docker (if not already installed)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect

# Verify
docker --version          # Docker version 24+
docker compose version    # Docker Compose version v2+
```

---

## 2. Clone the Repository

```bash
git clone https://github.com/johnfforbes3/ims-agent.git
cd ims-agent
```

---

## 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set the following **required** variables:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key (obtain from console.anthropic.com) |
| `IMS_FILE_PATH` | Path to IMS XML file inside the container (e.g., `data/sample_ims.xml`) |
| `DASHBOARD_API_KEY` | Random secret for API auth — generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SLACK_BOT_TOKEN` | Slack bot token (xoxb-…) for cycle summary posts and /ims slash command |
| `SLACK_APP_TOKEN` | Slack app-level token (xapp-…) for Socket Mode |

See `CONFIGURATION.md` for the full variable reference.

---

## 4. Place the IMS File

Copy the program's IMS XML file into `data/`:

```bash
mkdir -p data
cp /path/to/your/program.xml data/sample_ims.xml
```

Update `IMS_FILE_PATH=data/sample_ims.xml` in `.env` to match.

---

## 5. Build the Image

```bash
docker build -t ims-agent:latest .
```

Expected output: image builds in 2-3 minutes. Final line should be `naming to docker.io/library/ims-agent:latest`.

---

## 6. Start the Service

```bash
# Production mode: scheduler + dashboard, auto-restart on failure
docker compose -f docker-compose.prod.yml up -d

# Check that the container started
docker compose -f docker-compose.prod.yml ps
```

Expected status: `ims-agent   running (healthy)` within 30 seconds.

---

## 7. Verify Health

```bash
curl http://localhost:8080/health
```

Expected response:
```json
{
  "status": "healthy",
  "uptime_seconds": 12,
  "cycle_active": false,
  "state_file_present": false,
  "auth_enabled": true
}
```

`state_file_present` will be `false` until the first cycle completes.

---

## 8. Set Up Reverse Proxy (Recommended for Production)

Never expose port 8080 directly. Put nginx or Caddy in front with TLS:

**Caddy (simplest):**

```
# /etc/caddy/Caddyfile
ims.yourdomain.com {
    reverse_proxy localhost:8080
}
```

```bash
sudo systemctl reload caddy
```

Caddy automatically obtains a Let's Encrypt certificate.

---

## 9. Trigger the First Cycle

```bash
# Via API (requires DASHBOARD_API_KEY in X-API-Key header)
curl -X POST http://localhost:8080/api/trigger \
     -H "X-API-Key: YOUR_DASHBOARD_API_KEY"
```

Or via the dashboard at `http://localhost:8080` (Trigger Cycle button).

Watch logs while the cycle runs:

```bash
docker compose -f docker-compose.prod.yml logs -f
```

A full cycle takes approximately 8-10 minutes.

---

## 10. Verify Output

After the first cycle completes:

```bash
# Dashboard state should now be populated
curl -H "X-API-Key: YOUR_KEY" http://localhost:8080/api/state | python -m json.tool | head -20

# Reports directory inside the volume
docker compose -f docker-compose.prod.yml exec ims-agent ls reports/cycles/
```

---

## Updating the Agent

```bash
git pull
docker build -t ims-agent:latest .
docker compose -f docker-compose.prod.yml up -d --no-deps ims-agent
```

The container restarts with zero data loss (named volumes persist).

---

## Stopping the Service

```bash
docker compose -f docker-compose.prod.yml down
# Data is preserved in named volumes.

# To also remove volumes (DESTRUCTIVE — deletes all data):
docker compose -f docker-compose.prod.yml down -v
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Container exits immediately | Missing env var or bad API key | `docker compose logs ims-agent` |
| Health check fails | App not listening on 8080 | Check `DASHBOARD_PORT` in `.env` |
| 401 on API calls | `DASHBOARD_API_KEY` mismatch | Verify header: `-H "X-API-Key: VALUE"` |
| Cycle never starts | Scheduler not configured | Use `--schedule` command or set `CYCLE_CRON` |
| No Slack messages | Webhook URL or bot token wrong | Check `SLACK_WEBHOOK_URL` in `.env` |

For more detail see `OPERATIONS.md`.
