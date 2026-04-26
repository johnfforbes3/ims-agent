# IMS Agent — Teams Interview Demo Setup Guide

This guide walks you through everything needed to run the Tier 3 live Teams
interview demo. Estimated time: **30–45 minutes**.

When complete, you will be able to join a Teams meeting, run:

```
python main.py --demo-interview \
  --meeting-url "https://teams.microsoft.com/l/meetup-join/..." \
  --callback-url "https://xxxx.ngrok.io"
```

...and hear both sides of the CAM interview played live into the meeting.

---

## What You Need

| Requirement | Status |
|---|---|
| Azure account (free tier works) | ⬜ |
| Azure Communication Services resource | ⬜ |
| ngrok installed (or Azure Dev Tunnels) | ⬜ |
| `.env` updated with ACS connection string | ⬜ |
| `pip install -r requirements.txt` run | ⬜ |
| Teams meeting with lobby set to "Everyone" | ⬜ |

---

## Step 1 — Create an Azure Account

If you already have an Azure subscription, skip to Step 2.

1. Go to [portal.azure.com](https://portal.azure.com)
2. Click **Start for free** — the free tier includes enough ACS minutes for demos
3. Sign in with your Microsoft account (the same one for your M365 trial at
   `intelligenceexpanse.onmicrosoft.com` works fine)

---

## Step 2 — Create an Azure Communication Services Resource

1. In the Azure portal, click **Create a resource**
2. Search for **Communication Services** and select it
3. Click **Create**
4. Fill in:
   - **Subscription**: your subscription (Free or Pay-As-You-Go)
   - **Resource group**: create new → name it `ims-agent-rg`
   - **Resource name**: `ims-agent-acs`
   - **Data location**: United States (or your nearest region)
5. Click **Review + Create** → **Create**
6. Wait ~1 minute for deployment to complete

---

## Step 3 — Copy the Connection String

1. Go to your new ACS resource: **portal.azure.com → ims-agent-acs**
2. In the left sidebar, under **Settings**, click **Keys**
3. Copy the **Primary connection string** — it looks like:
   ```
   endpoint=https://ims-agent-acs.communication.azure.com/;accesskey=abc123...==
   ```
4. Open your `.env` file and set:
   ```
   ACS_CONNECTION_STRING=endpoint=https://ims-agent-acs.communication.azure.com/;accesskey=abc123...==
   ```

---

## Step 4 — Install ngrok (Public Webhook Tunnel)

ACS needs to POST events to a **publicly reachable HTTPS URL**. ngrok creates
a secure tunnel from a public URL to your local machine.

### Option A: ngrok (recommended for Windows)

1. Download ngrok from [ngrok.com/download](https://ngrok.com/download)
2. Extract the executable to a folder on your PATH (e.g. `C:\ngrok\`)
3. Sign up for a free ngrok account at [dashboard.ngrok.com](https://dashboard.ngrok.com)
4. Connect your account:
   ```
   ngrok config add-authtoken <your-token>
   ```
5. **Every time you run the demo**, start ngrok first:
   ```
   ngrok http 8080
   ```
6. Copy the **Forwarding** URL — it looks like:
   ```
   https://abcd1234.ngrok-free.app
   ```
   This is your `--callback-url`.

### Option B: VS Code Dev Tunnels (no account needed)

1. Install the **Dev Tunnels** extension in VS Code
2. Open the Command Palette → **Dev Tunnels: Create Tunnel**
3. Set port **8080**, visibility **Public**
4. Copy the tunnel URL as your `--callback-url`

> **Note:** The ngrok/tunnel URL changes every time you restart it (on the
> free plan). Always use the current URL when running the demo.

---

## Step 5 — Install Dependencies

```bash
# Activate your virtual environment first
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

pip install -r requirements.txt
```

This adds `azure-communication-callautomation>=1.3.0`.

---

## Step 6 — Configure Teams Meeting Lobby Settings

By default, Teams places external participants (including ACS bots) in the
lobby. You need to admit the bot, or bypass the lobby entirely.

**For the demo (easiest):**

1. Open Teams and start a new meeting (or schedule one)
2. Once in the meeting, click **More → Meeting info → Meeting options**
3. Set **Who can bypass the lobby?** to **Everyone**
4. Click **Save**

**Alternative:** Leave the default lobby setting and manually admit the bot
when it appears in the lobby during the demo — you'll see a notification
"1 person is waiting in the lobby."

---

## Step 7 — Run the Demo

### Terminal 1 — Start ngrok

```
ngrok http 8080
```

Note the `https://xxxx.ngrok-free.app` URL.

### Terminal 2 — Join the Teams meeting yourself

Start or join your Teams meeting so you can hear both voices.

Copy the meeting join URL from the Teams invite or the meeting info panel.
It starts with `https://teams.microsoft.com/l/meetup-join/...`

### Terminal 3 — Run the agent

```bash
python main.py --demo-interview \
  --meeting-url "https://teams.microsoft.com/l/meetup-join/19%3ameeting_..." \
  --callback-url "https://abcd1234.ngrok-free.app" \
  --cam "Alice Nguyen"
```

**What happens:**
1. The agent joins your Teams meeting (you'll see a new participant appear)
2. If lobby is enabled, admit the participant
3. The agent speaks the greeting in Jenny's voice
4. The simulated CAM (Alice) responds in Aria's voice
5. The interview runs through all 8 of Alice's tasks
6. The agent hangs up and prints the extracted data + IMS impact analysis

---

## Available CAMs

All five ATLAS program CAMs are available:

| CAM | Role | Seeded scenario |
|---|---|---|
| `Alice Nguyen` | Systems Engineering | Blocked on RF specs from HW; PDR risk |
| `Bob Martinez` | Hardware Development | License contention; resource gap |
| `Carol Smith` | Software Development | Ahead of schedule; clean |
| `David Lee` | Integration and Test | On plan |
| `Eva Johnson` | Program Management | Minor schedule variance |

Run all five by omitting `--cam` and using `--cam "Bob Martinez"` etc. for each.

---

## Troubleshooting

### "Timed out waiting for Teams to accept the call"

- Check that the lobby is set to "Everyone can bypass" in Meeting Options
- Verify `ACS_CONNECTION_STRING` is correct (no trailing spaces/newlines)
- Verify the ngrok URL is current and the tunnel is running
- Check the ngrok web interface (http://localhost:4040) for incoming requests

### "azure-communication-callautomation is not installed"

```bash
pip install azure-communication-callautomation
```

### "ACS_CONNECTION_STRING is not set"

Make sure `.env` is in the `ims-agent/` directory (same folder as `main.py`)
and contains:
```
ACS_CONNECTION_STRING=endpoint=https://...;accesskey=...
```

### No audio heard in Teams

ACS TTS requires the call to be fully connected (CallConnected event received)
before play_media works. Check the agent console — it will print "Connected!"
before starting to speak. If you don't see this message, the call didn't
connect (see timeout troubleshooting above).

### Poor TTS voice quality

Add a Cognitive Services resource for higher-quality neural voices:
1. Azure portal → Create resource → **Speech** (Cognitive Services)
2. Copy the endpoint URL
3. Set `ACS_COGNITIVE_SERVICES_ENDPOINT=https://<name>.cognitiveservices.azure.com/`

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `ACS_CONNECTION_STRING` | Yes | Connection string from ACS resource Keys page |
| `ACS_COGNITIVE_SERVICES_ENDPOINT` | No | Cognitive Services endpoint for better TTS |
| `AGENT_TTS_VOICE` | No | Azure Neural voice for the agent (default: `en-US-JennyNeural`) |
| `CAM_TTS_VOICE` | No | Azure Neural voice for the CAM (default: `en-US-AriaNeural`) |
| `DEMO_TURN_PAUSE_SEC` | No | Silence between turns in seconds (default: `0.4`) |
| `DEMO_MAX_TURNS` | No | Safety cap on interview turns (default: `80`) |

Full list of Azure Neural voices: https://learn.microsoft.com/azure/ai-services/speech-service/language-support

---

## Architecture Notes

```
┌──────────────────────┐     HTTPS POST /acs/callback
│  Azure ACS           │ ──────────────────────────────► FastAPI server
│  Call Automation     │                                  (port 8080, via ngrok)
│                      │ ◄────────────────────────────── ACS SDK (Python)
│  Teams Meeting       │     play_media(TextSource)
└──────────────────────┘
         │ audio
         ▼
┌──────────────────────┐
│  Teams Meeting       │  ← You are here, listening
│  (all participants   │
│   hear both voices)  │
└──────────────────────┘
```

**Threading model:**
- `main()` starts uvicorn (ACS callback server) in a background thread
- Interview loop runs on the main thread
- `ACSEventBus` (`agent/acs_event_handler.py`) bridges events between threads
  using `threading.Event` — no async/await needed in the interview loop

**Data flow after the interview:**
The extracted `cam_input` dicts are passed to a temporary copy of the IMS XML.
Critical path (CPM) and Monte Carlo SRA are re-run on the updated schedule.
The original IMS file is **never modified** during the demo.
