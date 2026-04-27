# IMS Agent — Configuration Reference

All configuration is via environment variables. Copy `.env.example` to `.env` and edit. Never commit `.env`.

Variables marked **Required** have no safe default and the agent will not start or function correctly without them. All others have defaults shown.

---

## Core

| Variable | Default | Required | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Yes** | Anthropic API key. Obtain at console.anthropic.com. Replace with local model endpoint for ITAR compliance. |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | No | Claude model ID. Change to test other models. |
| `LLM_BASE_URL` | *(empty)* | No | Override the Anthropic API base URL. Set to an Ollama-compatible endpoint for on-prem/ITAR deployments (e.g., `http://localhost:11434`). Empty = Anthropic cloud. |
| `IMS_FILE_PATH` | `data/sample_ims.xml` | **Yes** | Path to the IMS XML file (MSPDI format). Relative to the project root. |
| `REPORTS_DIR` | `reports` | No | Directory for generated reports and cycle status JSONs. |
| `LOGS_DIR` | `logs` | No | Directory for log files. Created automatically if missing. |
| `LOG_LEVEL` | `INFO` | No | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `LOG_FORMAT` | `text` | No | `text` — human-readable. `json` — structured JSON for log aggregators. |

---

## Analysis

| Variable | Default | Required | Description |
|---|---|---|---|
| `REPORTING_PERIOD_END` | today | No | Override the reporting period end date (`YYYY-MM-DD`). |
| `SRA_ITERATIONS` | `1000` | No | Monte Carlo simulation iterations. Higher = more accurate but slower. |
| `SRA_DURATION_UNCERTAINTY` | `0.10` | No | Default ±fraction for task duration distributions (0.10 = ±10%). |
| `SRA_HIGH_RISK_THRESHOLD` | `0.50` | No | Milestones with on-time probability below this are HIGH risk. |
| `SRA_MEDIUM_RISK_THRESHOLD` | `0.75` | No | Milestones with probability between this and HIGH threshold are MEDIUM risk. |
| `NEAR_CRITICAL_FLOAT_DAYS` | `5` | No | Tasks with total float ≤ this value are flagged near-critical. |

---

## Voice Interview

| Variable | Default | Required | Description |
|---|---|---|---|
| `CALL_TRANSPORT` | `simulated` | No | `simulated` — Claude-powered CAM simulator (dev/test). `teams_acs` — real Azure ACS calls (Phase 5). |
| `INTERVIEW_RESPONSE_TIMEOUT_SEC` | `15` | No | Seconds to wait for a CAM response before re-prompting. |
| `INTERVIEW_MAX_RETRIES` | `3` | No | Max re-prompts per question before marking as no-response. |
| `INTERVIEW_MAX_CONCURRENT` | `5` | No | Max simultaneous CAM calls. |
| `CAM_DIRECTORY_PATH` | `data/cam_directory.json` | No | JSON file defining CAMs, Teams IDs, emails, timezones. Auto-generated from IMS if missing. |

---

## TTS / STT

| Variable | Default | Required | Description |
|---|---|---|---|
| `ELEVENLABS_API_KEY` | — | If TTS used | ElevenLabs API key. |
| `ELEVENLABS_VOICE_ID` | `21m00Tcm4TlvDq8ikWAM` | No | ElevenLabs voice ID (default: Rachel). |
| `ELEVENLABS_MODEL` | `eleven_turbo_v2` | No | `eleven_turbo_v2` (fast) or `eleven_multilingual_v2` (higher quality). |
| `AZURE_SPEECH_KEY` | — | If Azure TTS | Azure Cognitive Services key (Phase 5 ITAR migration path). |
| `AZURE_SPEECH_REGION` | `eastus` | No | Azure region for Cognitive Services. |
| `AZURE_TTS_VOICE` | `en-US-BrianMultilingualNeural` | No | Azure TTS voice name. |
| `WHISPER_MODEL` | `base` | No | Whisper model size: `tiny`, `base`, `small`, `medium`, `large`. |
| `WHISPER_INITIAL_PROMPT` | *(defense jargon)* | No | Context hint fed to Whisper to improve accuracy on defense vocabulary. |

---

## Teams Chat Bot (Tier 4)

| Variable | Default | Required | Description |
|---|---|---|---|
| `TEAMS_BOT_APP_ID` | — | **Yes** for chat bot | Azure AD App Registration client ID. Must match the `id`/`botId` in the Teams app manifest and the Azure Bot Service registration. |
| `TEAMS_BOT_APP_SECRET` | — | **Yes** for chat bot | Client secret for the App Registration. Used by MSAL to acquire Bot Framework connector tokens. |
| `TEAMS_TENANT_ID` | — | **Yes** for chat bot | Azure AD tenant ID (`ac1eafc0-…`). MSAL acquires tokens from `login.microsoftonline.com/<tenant-id>`, not the generic `botframework.com` authority. |

> **Note:** The `DASHBOARD_PORT` must match the ngrok tunnel pointed at in Azure Bot Service → Configuration → Messaging endpoint (`https://<ngrok-url>/bot/messages`). Update the Azure Bot Service endpoint whenever ngrok restarts (free plan changes the URL on restart).

---

## Teams / ACS Integration (Tier 3 — Voice)

| Variable | Default | Required | Description |
|---|---|---|---|
| `ACS_CONNECTION_STRING` | — | If `CALL_TRANSPORT=teams_acs` | Azure Communication Services connection string. |
| `ACS_PHONE_NUMBER` | — | If `CALL_TRANSPORT=teams_acs` | ACS phone number in E.164 format (e.g., `+12025550100`). |
| `TEAMS_AGENT_USER_ID` | — | If `CALL_TRANSPORT=teams_acs` | Teams user object ID for the agent bot. |

---

## Scheduler

| Variable | Default | Required | Description |
|---|---|---|---|
| `SCHEDULE_CRON` | `0 6 * * 1` | No | Cron expression for recurring cycles. Default: every Monday at 06:00. |
| `SCHEDULE_TIMEZONE` | `America/New_York` | No | IANA timezone for the cron trigger. |
| `INTERVIEW_COMPLETION_THRESHOLD` | `0.80` | No | Fraction of CAMs that must respond before the cycle proceeds (0.0–1.0). |

---

## Validation

| Variable | Default | Required | Description |
|---|---|---|---|
| `VALIDATION_MAX_JUMP_PCT` | `50` | No | Max percent-complete increase in one cycle before flagging as anomaly. |
| `VALIDATION_ALLOW_BACKWARDS` | `false` | No | Whether to allow percent-complete decreases without flagging. |

---

## Dashboard

| Variable | Default | Required | Description |
|---|---|---|---|
| `DASHBOARD_PORT` | `9000` | No | TCP port for the FastAPI server. |
| `DASHBOARD_URL` | `http://localhost:9000` | No | Public URL used in Slack/email links. Update for production. |
| `DASHBOARD_STATE_FILE` | `data/dashboard_state.json` | No | Path to the live dashboard state written after each cycle. |
| `CYCLE_HISTORY_FILE` | `data/cycle_history.json` | No | Path to the rolling cycle history. |
| `DASHBOARD_API_KEY` | *(empty)* | **Yes (production)** | API key for all `/api/*` read routes. Empty = auth disabled. **Must be set in any networked deployment.** |
| `DASHBOARD_ADMIN_KEY` | *(empty)* | No | Separate key for write/admin routes (`/api/trigger`, `/api/admin/purge`). Falls back to `DASHBOARD_API_KEY` when not set (single-key mode). |
| `QA_RATE_LIMIT_PER_HOUR` | `60` | No | Max Q&A questions per IP per hour on `POST /api/ask`. Set to `0` to disable rate limiting. |
| `DATA_RETENTION_DAYS` | `90` | No | Cycle status JSONs and IMS snapshots older than this many days are deleted on each cycle. |

---

## Notifications

| Variable | Default | Required | Description |
|---|---|---|---|
| `SLACK_WEBHOOK_URL` | — | No | Incoming webhook URL for cycle summary channel posts. |
| `SLACK_BOT_TOKEN` | — | If `/ims` command used | Bot OAuth token (xoxb-…). Required for Slack slash command. |
| `SLACK_APP_TOKEN` | — | If `/ims` command used | App-level token (xapp-…). Required for Socket Mode. |
| `EMAIL_SMTP_HOST` | — | No | SMTP server hostname. |
| `EMAIL_SMTP_PORT` | `587` | No | SMTP port (587 = STARTTLS, 465 = SSL). |
| `EMAIL_SMTP_USER` | — | No | SMTP authentication username. |
| `EMAIL_SMTP_PASS` | — | No | SMTP authentication password. |
| `EMAIL_FROM` | — | No | From address shown in outbound emails. |
| `EMAIL_TO` | — | No | Comma-separated list of notification recipients. |

---

## Voice Briefing

| Variable | Default | Required | Description |
|---|---|---|---|
| `VOICE_BRIEFING_ENABLED` | `false` | No | Set to `true` to generate a 60–90 second MP3 briefing after each cycle. Requires `ELEVENLABS_API_KEY`. |
