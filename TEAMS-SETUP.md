# IMS Agent — Teams Live Demo Setup Guide

This guide walks through provisioning the Azure infrastructure needed to run the
Teams interview demo. When complete, the **ATLAS Scheduler** bot joins a live
Teams meeting and plays both sides of the CAM interview as ElevenLabs TTS audio.

Estimated time: **45–60 minutes** (first time).

---

## Architecture Overview

```
  Demo script (main.py)
       │
       ├─ TeamsGraphConnector
       │     ├─ MSAL → Azure AD token
       │     ├─ POST /communications/calls  → bot joins Teams meeting
       │     ├─ ElevenLabs PCM → WAV → stored in audio cache
       │     └─ POST /calls/{id}/playPrompt → plays WAV into meeting
       │
       └─ FastAPI server (port 8080, exposed via ngrok)
             ├─ POST /graph/callback  ← Graph sends call-state events here
             └─ GET  /graph/audio/{id} ← Graph fetches WAV clips here
```

All participants in the Teams meeting hear both voices (agent + simulated CAM)
through the meeting audio stream.

---

## Prerequisites

| Item | Notes |
|------|-------|
| Microsoft 365 tenant | M365 Business Basic trial works |
| Azure subscription | Free tier sufficient |
| ElevenLabs API key | Free tier sufficient for demos |
| ngrok account | Free tier; URL changes each session |
| Python 3.11+ | With `pip install -r requirements.txt` |

---

## Step 1 — Azure AD App Registration

1. Go to **portal.azure.com → Microsoft Entra ID → App registrations → New registration**
2. Fill in:
   - **Name**: `ATLAS Scheduler`
   - **Supported account types**: Accounts in this organizational directory only
   - **Redirect URI**: leave blank
3. Click **Register**
4. Copy the **Application (client) ID** → this is `TEAMS_BOT_APP_ID`
5. Copy the **Directory (tenant) ID** → this is `TEAMS_TENANT_ID`

### Create a client secret
6. Left sidebar → **Certificates & secrets → New client secret**
7. Description: `demo`, Expires: 24 months → **Add**
8. **Copy the secret Value immediately** (it won't be shown again) → `TEAMS_BOT_APP_SECRET`

### Add API permissions
9. Left sidebar → **API permissions → Add a permission → Microsoft Graph → Application permissions**
10. Search for and add:
    - `Calls.JoinGroupCall.All`
11. Click **Grant admin consent for [your tenant]** → confirm
12. The permission row should show a green **"Granted"** checkmark

> **Verify consent was applied:** Run `python scripts/check_teams_auth.py` —
> step 5 should show `[OK] /communications/calls GET`.

---

## Step 2 — Azure Bot Service

The Bot Service registers your app with the Teams calling infrastructure.
Without it, `POST /communications/calls` returns error 7503.

1. **portal.azure.com → Create a resource → "Azure Bot"**
2. Fill in:
   - **Bot handle**: `atlas-scheduler-bot`
   - **Subscription / Resource group**: your existing group
   - **Type of App**: Multi Tenant
   - **Creation type**: Use existing app registration → paste `TEAMS_BOT_APP_ID`
3. Click **Review + Create → Create** (takes ~1 minute)
4. Go to the new Bot resource → **Channels → Microsoft Teams**
5. Enable **Calling** tab → set **Webhook URL**:
   ```
   https://<your-ngrok-url>.ngrok-free.app/graph/callback
   ```
6. Click **Apply / Save**

> **Note:** The ngrok URL changes every session on the free plan. Update
> the webhook URL in this step each time you restart ngrok.

---

## Step 3 — Configure .env

Add these variables to your `.env` file in the `ims-agent/` directory:

```
# Microsoft Graph Bot (Teams calling)
TEAMS_BOT_APP_ID=<Application (client) ID from Step 1>
TEAMS_BOT_APP_SECRET=<Client secret value from Step 1>
TEAMS_TENANT_ID=<Directory (tenant) ID from Step 1>
TEAMS_BOT_DISPLAY_NAME=ATLAS Scheduler

# ElevenLabs TTS
ELEVENLABS_API_KEY=<your ElevenLabs API key>
ELEVENLABS_MODEL=eleven_turbo_v2

# Voice IDs (defaults shown — override to change voices)
ELEVENLABS_AGENT_VOICE_ID=pFZP5JQG7iQjIQuC4Bku
ELEVENLABS_CAM_VOICE_ID=EXAVITQu4vr4xnSDxMaL

# Demo timing
DEMO_TURN_PAUSE_SEC=0.4
DEMO_MAX_TURNS=80
```

---

## Step 4 — Install Dependencies

```
pip install -r requirements.txt
```

Key packages added for Tier 3:
- `msal>=1.30.0` — MSAL token acquisition for Graph API
- `elevenlabs>=1.9.0` — TTS generation
- `sounddevice>=0.4.6` — local audio fallback (plays through speakers when Teams bot is unavailable)

---

## Step 5 — Start ngrok

```
ngrok http 8080
```

Copy the `https://xxxx.ngrok-free.app` URL. This is your `--callback-url`.

After starting ngrok, update the **Teams channel webhook URL** in Azure Bot Service
(Step 2, item 6) to match the new ngrok URL.

---

## Step 6 — Verify Credentials

```
python scripts/check_teams_auth.py
```

All five checks should pass. If step 5 fails with error 7504, the API permission
admin consent is missing — go back to Step 1 and click "Grant admin consent".

---

## Step 7 — Create a Teams Meeting

1. Open Teams and schedule or start a meeting
2. Copy the meeting join URL from the invite or **Meeting info** panel
   - Short format: `https://teams.microsoft.com/meet/12345678?p=AbcDef`
   - Long format: `https://teams.microsoft.com/l/meetup-join/19%3Ameeting_...`
3. Both URL formats are supported
4. Join the meeting yourself so you can hear the audio

**Lobby settings** (recommended): In the meeting → More → Meeting options →
set **"Who can bypass the lobby?"** to **Everyone** so the bot joins automatically.

---

## Step 8 — Run the Demo

```
python main.py --demo-interview \
  --meeting-url "https://teams.microsoft.com/meet/..." \
  --cam "Alice Nguyen" \
  --callback-url "https://xxxx.ngrok-free.app"
```

**What happens:**
1. Bot joins the meeting as "ATLAS Scheduler" (you'll see it appear in the participant list)
2. The agent speaks the greeting in Rachel's voice (ElevenLabs)
3. The simulated CAM responds in Bella's voice
4. The interview runs through all assigned tasks (~8 for Alice Nguyen)
5. The bot hangs up and prints extracted data + IMS impact analysis

---

## Available CAMs

| CAM | Tasks | Seeded scenario |
|-----|-------|-----------------|
| `Alice Nguyen` | 8 | Blocked on RF specs; PDR risk |
| `Bob Martinez` | varies | License contention; resource gap |
| `Carol Smith` | varies | Ahead of schedule; clean |
| `David Lee` | varies | On plan |
| `Eva Johnson` | varies | Minor schedule variance |

---

## Troubleshooting

### Bot does not appear in the meeting

- Verify `TEAMS_BOT_APP_ID`, `TEAMS_BOT_APP_SECRET`, `TEAMS_TENANT_ID` are correct
- Verify admin consent was granted for `Calls.JoinGroupCall.All` (run `check_teams_auth.py`)
- Verify ngrok is running and the webhook URL in Azure Bot Service matches
- Check ngrok dashboard at `http://localhost:4040` — you should see POST requests to `/graph/callback`
- Verify lobby is set to "Everyone can bypass" in Meeting Options

### Graph 403 error code 7504 "Insufficient enterprise tenant permissions"

Admin consent for `Calls.JoinGroupCall.All` was not granted.
- portal.azure.com → Entra ID → App registrations → ATLAS Scheduler → API permissions
- Click **"Grant admin consent for [tenant]"**

### Graph 403 error code 7503 "Application is not registered"

Azure Bot Service is missing or Teams channel calling is not enabled.
- Complete Step 2 and ensure the Teams channel has Calling enabled with the webhook URL set.

### No audio heard in Teams

1. Check Teams meeting volume — right-click the ATLAS Scheduler participant → adjust volume
2. Check Windows system volume (not muted)
3. Run `services.msc` → restart **Windows Audio** if system sounds are also silent
4. Verify the ngrok tunnel is still active and receiving requests

### "play_timeout" logged but no audio plays

The `PlayCompleted` event is not arriving from Graph. Check:
- ngrok is running and the webhook URL in Azure Bot Service is current
- `http://localhost:4040` shows incoming POST requests to `/graph/callback`
- The audio URL (`/graph/audio/{id}`) is publicly reachable — Graph must be able to fetch the WAV

### Latency between turns

Expected: ~8–14 seconds per turn due to ElevenLabs TTS generation × 2 + LLM classifier + Graph API round trips. This is inherent to the pipeline and not a bug.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TEAMS_BOT_APP_ID` | Yes | — | Azure AD App Registration client ID |
| `TEAMS_BOT_APP_SECRET` | Yes | — | Azure AD client secret value |
| `TEAMS_TENANT_ID` | Yes | — | Azure AD directory (tenant) ID |
| `TEAMS_BOT_DISPLAY_NAME` | No | `ATLAS Scheduler` | Bot display name in Teams |
| `ELEVENLABS_API_KEY` | Yes | — | ElevenLabs API key |
| `ELEVENLABS_MODEL` | No | `eleven_turbo_v2` | ElevenLabs model ID |
| `ELEVENLABS_AGENT_VOICE_ID` | No | `pFZP5JQG7iQjIQuC4Bku` | Agent voice (Rachel) |
| `ELEVENLABS_CAM_VOICE_ID` | No | `EXAVITQu4vr4xnSDxMaL` | CAM voice (Bella) |
| `DEMO_TURN_PAUSE_SEC` | No | `0.4` | Silence between turns (seconds) |
| `DEMO_MAX_TURNS` | No | `80` | Safety cap on interview turns |
| `DASHBOARD_PORT` | No | `8080` | Port for FastAPI callback server |
