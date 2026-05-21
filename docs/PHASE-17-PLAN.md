# Phase 17 — Voice Agent Upgrade

**Status:** Planning + overnight iteration approved
**Started:** 2026-05-17
**Rollback tag:** `pre-phase17-voice-upgrade-2026-05-17` (pushed)
**Backup branch:** `backup/pre-phase17-voice-upgrade` (pushed)
**Source article:** *"How to build a voice agent that actually answers the phone"* (May 2026)

---

## 1. Goal

Replace the text-only CAM interview path (`agent/voice/teams_chat_connector.py`)
with a **voice-driven** path that lets each CAM **speak** their status update
instead of typing it.

**Critical scope constraint from the user:** the CAM-facing channel is
**still Teams**, not a phone call. The agent sends a TTS voice message into
the CAM's Teams chat (same conversation thread as today's text bot); the CAM
replies with a Teams voice message; STT transcribes it; the existing
`InterviewAgent` consumes the transcript. **No ACS phone provisioning is
required for the iteration the user wants to test tonight.**

A secondary deliverable — a **web-based voice tester** at `/voice/test` —
gives the developer (and the user playing stand-in CAM) a fast iteration loop
without round-tripping through Teams for every test.

## 2. Why this matters

The Phase 12+ text path works but feels transactional. CAMs treat it like
a form. A voice path:
- Captures the **tone** that text strips out (frustration, hedging, "we're really stuck")
- Matches how CAMs already talk about schedule status (in standups, hallway conversations)
- Generates **richer notes** for the IMS — the variance narrative reads better when
  it's drawn from a transcript rather than a 40-character chat reply
- Establishes the foundation for **real phone calls** in Phase 18 (when ACS
  phone-number provisioning is finished)

## 3. Architecture — chained pipeline (per article §3)

Article recommendation: **start with the chained pipeline** (STT → LLM → TTS)
even though native speech-to-speech is faster. The chained pipeline is the
most controllable, the most debuggable, and the best-tooled in 2026. We move
to speech-to-speech in Phase 18 once the chained pipeline is validated.

```
CAM voice message (Teams or web)
   │
   ▼
┌─────────────────────────────────────────────────┐
│  agent/voice_v2/pipeline.py                      │
│                                                  │
│  1. Audio capture        (Teams attachment or    │
│                           WebRTC stream)         │
│  2. Streaming STT        (Deepgram Flux or       │
│                           local Whisper)         │
│  3. End-of-turn detect   (semantic, not silence) │
│  4. Input guard          (PII / injection)       │
│  5. InterviewAgent       (existing — Phase 12)   │
│      └─ state machine    (article §4 — tool      │
│         + tool scoping     scoping per state)    │
│  6. Output guard         (over-promise /         │
│                           hallucination check)   │
│  7. Streaming TTS        (ElevenLabs Turbo or    │
│                           Azure Speech)          │
│  8. Audio out            (Teams attachment or    │
│                           WebRTC playback)       │
│                                                  │
│  Side-channels:                                  │
│  - Turn log (JSONL, durable)                     │
│  - Async LLM judge (every 50th turn)             │
│  - Audit_log (Phase 16) for cycle.trigger etc.   │
└─────────────────────────────────────────────────┘
```

**Latency budget** (article §6) — for the **web tester** path (real-time):
- Transport (browser ↔ server): ~50 ms
- STT first interim: 150–250 ms
- End-of-turn detect: ~50 ms (semantic, not silence threshold)
- LLM time-to-first-token: 150–250 ms (Claude Haiku, not Sonnet)
- TTS time-to-first-audio: 60–100 ms (ElevenLabs Turbo)
- Network overhead: 40–80 ms
- **Target end-to-end: ~700 ms** ("conversational reply" threshold)

For the **Teams voice message** path: latency budget is generous (it's a voice
memo, not a live call). We optimize for transcript quality, not first-byte time.

## 4. Component selections

| Component | Choice | Why | Already configured? |
|---|---|---|---|
| **STT** | Deepgram Flux (primary), Whisper (fallback) | Flux ships semantic end-of-turn detection (article §4 — single biggest 2026 upgrade); Whisper is the existing fallback so the pipeline degrades gracefully if Deepgram is down | Whisper YES; **Deepgram key needed** |
| **TTS** | ElevenLabs Turbo v2 | Already in the codebase; 5 CAM voice IDs already configured per-CAM identity; fast first-audio | YES (key + voices configured) |
| **LLM** | Anthropic Claude Sonnet (interviews), Haiku (small-talk gate) | Reuse Phase 16 `llm_interface.py` + circuit breaker; Haiku for fast turns, Sonnet for variance-flagged turns | YES (key configured) |
| **Bot transport** | Existing Teams Bot Framework | Already working for text; adding voice-message attachments is a small Graph API change | YES (bot registered) |
| **Web transport** | FastAPI WebSocket + WebRTC | New code; no external dependency beyond a browser | New |
| **State machine** | New `voice_v2/state_machine.py` | Article §4 explicit recommendation: "the state machine is the safety rail, not the system prompt." Existing `interview_agent.py` has prose-encoded states — refactor into explicit transitions. | New |
| **RAG / context** | IMS data (CAM's tasks, prior cycles, schedule_health) | Our "knowledge base" is the IMS, not a vendor doc corpus. Dual-agent cache pattern (article §7) applies: while CAM answers Q1, prefetch Q2's task context. | New (pattern, not infra) |
| **Audit/identity** | Existing Phase 16 `audit_log.py` + `X-User-Email` | Reuse — every voice turn logs to the same audit table, attributed by CAM email | YES |

## 5. State machine design (article §4 + §11 #3)

The existing `InterviewAgent` encodes interview flow as prose in a system
prompt. The article's #1 most-quoted failure mode: "tools available in the
wrong state → LLM calls `book_appointment` while still collecting the
patient's name."

For our use case, the analogous failure is: LLM calls
`commit_baseline_update(task_id, percent_complete)` while still in the
greeting phase, or calls it with a `percent_complete` the CAM never
actually confirmed.

**New design** — explicit states, scoped functions per state:

```
GREETING                 → small_talk_response only
  ↓
OPEN_QUESTION            → record_general_status (just a freeform note)
  ↓                         capture_blocker_keyword (sets state flag)
TASK_BY_TASK_LOOP        → propose_percent_complete (LLM-extracted from speech)
  │                         confirm_percent_complete (only fires after CAM confirms)
  │                         capture_blocker_text
  │                         capture_risk_flag + capture_risk_description
  │                         ↳ NO commit yet — held in transient state
  ↓ (when all tasks covered)
CONFIRM_BLOCK            → repeat_back_all_updates (TTS reads them all)
  │                         user_confirmation_yes_no
  ↓ (only if YES)
COMMIT                   → write_updates_to_pending_cam_inputs
                           (still NOT writing to IMS — that requires PM approval per Phase 16)
  ↓
WRAPUP                   → graceful_close
```

**Tool scoping per state is enforced in Python**, not in the prompt. The
`StateMachine.allowed_tools(current_state)` returns the function list the
LLM call gets; tools from other states are physically absent from the API
call. The state machine is the safety rail; the prompt cannot bypass it.

**Validation in Python, not in prompts** (article §11 #4): `percent_complete`
must be 0–100 integer; CAM-spoken "fifty percent" → `"50"` → `int("50")`.
Anything that fails validation triggers a polite re-ask.

## 6. Safety guards (article §5)

Two checkpoints — input (before LLM sees turn) + output (after LLM writes
reply, before TTS speaks it).

### Input guard (`voice_v2/guards.py::check_input`)
- **Prompt injection**: "ignore previous instructions", "you are now…",
  "system: …" markers. Blocked → "I'm just here to capture your task
  status; let's stick to that."
- **PII spoken aloud**: SSN, credit card patterns (we don't expect any
  in a CAM interview, but the guard logs and redacts if it sees them).
- **Topic blocklist**: weekly-maintained JSON. Initial list: pricing,
  legal advice, HR complaints, anything that needs escalation rather
  than capture.

### Output guard (`voice_v2/guards.py::check_output`)
- **Over-promise language** — "I guarantee", "I promise", "definitely will" →
  rewritten to "I'll capture that" or "I'll flag it for the PM."
- **Hallucinated fact check** — any task_id or percent_complete the LLM
  mentions that isn't in the retrieved context (the CAM's actual task list)
  is rewritten or stripped. Article §5 cites this catching ~70% of
  confabulated answers.
- **Standard moderation** — sanity-check using a moderation endpoint
  (we can use Anthropic's content moderation prompt or skip; low risk
  on a structured interview).

### Escalation phrase (article §5 — exactly one)
> *"I want to make sure I give you accurate information. Let me flag this for
> your PM and we'll follow up."*

Hardcoded. Fired when any guard trips, or when the LLM returns
low-confidence (top BM25 score on retrieved context < 0.3).

## 7. Turn log + replay (article §11 #1 — "build this day one")

Article's single strongest recommendation: don't wait to design the turn
log schema. Every voice turn writes one row to a JSONL file at
`data/voice_turns/{cycle_id}.jsonl`:

```jsonl
{
  "turn_id": "20260517T194422Z-001",
  "cycle_id": "20260517T192800Z",
  "cam_email": "alice@program.mil",
  "cam_name": "Alice Nguyen",
  "state_before": "TASK_BY_TASK_LOOP",
  "state_after": "TASK_BY_TASK_LOOP",
  "audio_in_ms": 4200,
  "stt_first_partial_ms": 187,
  "stt_final_ms": 4310,
  "stt_transcript": "task two is at sixty percent, blocker is vendor still hasn't responded",
  "end_of_turn_signal": "semantic",
  "input_guard": {"passed": true, "categories": []},
  "llm_provider": "anthropic",
  "llm_model": "claude-3-5-sonnet",
  "llm_first_token_ms": 218,
  "llm_full_response_ms": 612,
  "llm_text_out": "Got it — task 2 at 60%. The blocker is the vendor hasn't responded. Anything else on task 2?",
  "llm_tool_calls": [{"name": "propose_percent_complete", "args": {"task_id": "2", "pct": 60}}],
  "output_guard": {"passed": true, "categories": []},
  "tts_first_audio_ms": 81,
  "tts_full_audio_ms": 1850,
  "tts_voice_id": "Xb7hH8MSUJpSbSDYk0k2",
  "end_to_end_ms": 911,
  "transport": "teams_voice_msg"
}
```

**Replay endpoint** — `POST /api/voice/replay/{turn_id}` re-runs the turn
against the **current** config. Lets us A/B test a system-prompt change
against last week's actual conversation without re-recording anything.

## 8. Web-based voice tester (`/voice/test`)

For overnight iteration speed, a developer-facing web page that the user
can also use as a CAM stand-in. **Not** in the production hot-path —
gated behind `VOICE_AGENT_V2_TESTER=true`.

- `agent/dashboard/static/voice_tester/index.html` — minimal UI: mic
  button, transcript pane, conversation history, "play as CAM" dropdown
- `voice_tester.js` — `getUserMedia` mic capture, WebSocket to
  `/api/voice/stream`, audio playback of TTS chunks
- `agent/dashboard/server.py` adds:
  - `GET /voice/test` — serves the page (auth-gated)
  - `WebSocket /api/voice/stream?cam=<email>` — bridges WebRTC ↔
    pipeline.py

**This is the artifact the user will hit tonight to verify the work**.
"Play as Alice Nguyen" → speak into mic → hear agent's voice response.

## 9. Teams voice-message integration

Builds on the existing Bot Framework path. Two small changes:

1. **Outbound** — `teams_chat_connector.proactive_send_message()` gains
   an optional `audio_bytes` parameter. When present, attaches the audio
   as a Teams chat attachment (`mp3` or `wav`) instead of text-only.
2. **Inbound** — `/bot/messages` handler now detects voice-message
   attachments on incoming activities, downloads them via Graph,
   runs STT, and routes the transcript into the existing
   `ChatInterviewSession` (which already calls `InterviewAgent.process`).

The text fallback stays — if a CAM types instead of speaking, it still
works exactly like today. **No regression**.

## 10. Feature flag + rollback strategy

Three env flags, all default OFF:

| Flag | Effect |
|---|---|
| `VOICE_AGENT_V2=true` | Enables the new pipeline as the default for `teams_chat` transport. When OFF, the existing text-only path runs unchanged. |
| `VOICE_AGENT_V2_TESTER=true` | Enables the `/voice/test` web page. Independent of the production flag so the tester can run while production stays on text. |
| `VOICE_AGENT_V2_DRY=true` | Pipeline runs end-to-end but **does not commit** updates to `pending_cam_inputs`. Logs everything to the turn log. For shadow-mode validation against a live cycle. |

**Rollback paths**:
- **Soft**: `VOICE_AGENT_V2=false` in `.env`, restart server. 0-second rollback.
- **Tag**: `git reset --hard pre-phase17-voice-upgrade-2026-05-17` returns to clean Phase 16.
- **Branch**: `backup/pre-phase17-voice-upgrade` for cherry-pick recovery of any non-voice work that lands during Phase 17.

## 11. Testing — article's 4-layer eval

| Layer | Metric | Target |
|---|---|---|
| **L1 Infrastructure** | WER on our domain (5 CAMs reading sample status updates) | < 8% |
| | p95 end-to-end latency (web tester) | < 900 ms |
| | TTS time-to-first-audio | < 120 ms |
| **L2 Execution** | Tool-call accuracy (right state, right args) | > 95% |
| | Groundedness (LLM-as-judge — answers from CAM's tasks only) | > 90% |
| **L3 User behavior** | Reprompt rate (CAM repeats themselves) | < 10% |
| | Barge-in recovery | works on 5/5 CAM voices |
| **L4 Business outcome** | Voice cycle completion rate vs text-only baseline | ≥ parity |

**Test set (article §5)**: 50 simulated conversations before the first
real CAM hears the new path:
- 40% happy path (each of 5 CAMs × 4 tasks)
- 30% edge cases (numbers spelled vs spoken, mid-sentence corrections,
  long pauses, two-question turns, "I don't know")
- 15% error handling (mic dropouts, silence, ambiguous %)
- 10% adversarial ("ignore previous instructions", asking the agent
  to send an email)
- 5% acoustic variation (background noise, accents — we can synthesize
  these via ElevenLabs voice cloning of the existing CAM voice IDs)

## 12. Out-of-scope (deferred to Phase 17.x or 18)

- **Real phone calls via ACS** — ACS connection string is provisioned
  but no phone number purchased. Phase 18.
- **Native speech-to-speech** (OpenAI Realtime / GPT-Realtime-2 / Claude
  voice) — article §3 says start with chained pipeline. Phase 18.
- **Dual-agent RAG cache** (article §7) — we have a small known set of
  tasks per CAM, so prefetch is easier than the general case. Phase 17.1.
- **Weekly review loop dashboard** (article §10) — manual review for now;
  dashboard tile in Phase 17.2.
- **Multi-lingual CAMs** — English-only for now.
- **Phone-tree IVR / callback** — we're not building a customer-service
  agent; CAMs are a known, small, identified group.

## 13. Acceptance criteria for "ready to test"

The user wakes up to a working iteration if all of these are true:

- [ ] `VOICE_AGENT_V2_TESTER=true python main.py --serve` runs without error
- [ ] `http://localhost:9000/voice/test` loads (auth-gated)
- [ ] "Play as Alice Nguyen" dropdown populates from real `CAMS`
- [ ] Mic button captures speech, transcribes in real-time, displays
- [ ] Agent replies via TTS using Alice's voice ID
- [ ] Conversation flows through GREETING → TASK_BY_TASK_LOOP → CONFIRM → COMMIT (dry mode)
- [ ] Every turn appears in `data/voice_turns/<cycle_id>.jsonl`
- [ ] `data/pending_cam_inputs/<cycle_id>/alice.json` is written at COMMIT
  state (dry mode: still written, but marked `"dry_run": true`)
- [ ] Pytest: at least one test per new module (`voice_v2/pipeline.py`,
  `state_machine.py`, `guards.py`, `turn_log.py`)
- [ ] No regression in the existing 708-test default suite
- [ ] Honest list of what didn't work or was deferred — written to
  `docs/PHASE-17-DAY1-REPORT.md` so the user sees the truth, not a
  marketing summary

## 14. Overnight iteration plan

Sequence I'll execute autonomously after the user provides the
dependency checklist below:

1. Install Python deps (`deepgram-sdk`, `websockets`, `pydub`, etc.)
2. Scaffold `agent/voice_v2/` package with stub modules
3. Build `turn_log.py` first (article §11 #1)
4. Build `state_machine.py` with explicit transitions
5. Build `guards.py` with input + output checks
6. Build `pipeline.py` orchestrator (mocked STT/TTS first)
7. Wire `transport_web.py` (FastAPI WebSocket)
8. Build the `/voice/test` web page (vanilla JS, no framework — fits
   the existing vendored / no-CDN constraint)
9. Wire real Deepgram STT (or Whisper fallback)
10. Wire real ElevenLabs TTS (existing module already works)
11. Connect `InterviewAgent` through the state machine
12. Write tests as I go (one per module, mocked externals)
13. Run the 50-conversation eval set against a mocked CAM (text in, text out — the audio layer is mocked here so the LLM/state-machine layer is independently validated)
14. Generate `docs/PHASE-17-DAY1-REPORT.md` — what worked, what didn't, what to look at first when the user wakes up
15. Commit + push at the end of each working milestone (granular history so any individual change can be reverted)

## 15. DEPENDENCIES ON USER — BEFORE-BED CHECKLIST

These are the only things I need from the user before they hand over for
the overnight run. Anything not on this list, I can do.

### Required (overnight blocks without these)

| # | Item | Why needed | How to provide |
|---|------|-----------|----------------|
| **1** | **STT decision** — Deepgram API key, OR explicit "use Whisper" | Deepgram Flux is the article's headline 2026 STT recommendation (semantic end-of-turn). Whisper works (already installed) but slower + no end-of-turn detect. | Either paste Deepgram key into `.env` as `DEEPGRAM_API_KEY=...`, OR tell me "use Whisper, that's fine" |
| **2** | **Confirm Claude is the LLM** | The article was provider-agnostic; we have a working Anthropic path with the Phase 16 circuit breaker. Confirming so I don't waste time integrating a second LLM provider tonight. | Reply "yes Claude" or name another provider |
| **3** | **Confirm test CAM stand-in identity** | I need to know which CAM email I should wire the web tester to so the user can play that CAM. The existing CAM directory has Alice/Bob/Carol/David/Eva — the user just needs to pick one (or say "any"). | Reply "play as Alice" (or whoever) |

### Optional (would be nice but not blocking)

| # | Item | Why nice-to-have |
|---|------|-----------------|
| **4** | OpenAI Realtime API key | Lets me prototype the speech-to-speech path in parallel as a Phase 18 spike. Skippable. |
| **5** | A 30-second voice sample from the user reading a test status update | Lets me clone a custom ElevenLabs voice for the "user-as-CAM" test path. The existing 5 CAM voice IDs work fine without this. |
| **6** | Phone number purchase for ACS | Unblocks Phase 18 (real phone calls). Not needed for tonight. |

### What I DON'T need

- Tenant admin changes
- New Azure subscriptions
- Code-signing certs
- Network/firewall changes
- Any payment activity beyond items #1 and #4

### What the user should know about cost

- **Deepgram Flux**: ~$0.0078/minute of audio. A typical 5-CAM cycle is ~80 minutes of audio total → ~$0.62/cycle.
- **ElevenLabs Turbo**: ~$0.06/1000 chars. Average agent reply ~80 chars × 100 turns/cycle → ~$0.48/cycle.
- **Anthropic Claude**: unchanged from today.
- **Total marginal cost per cycle vs Phase 16**: ~$1.10/cycle.
- Hard ceiling can be enforced via the existing circuit-breaker pattern (extend `circuit_breaker.py` with a per-provider monthly budget cap in Phase 17.x).

---

**Once the user hands off:**
1. I create branch `phase17/voice-upgrade` for the overnight work
2. I commit to that branch granularly (every working milestone)
3. I generate `PHASE-17-DAY1-REPORT.md` at the end of the run
4. User wakes up, reviews the report, runs the web tester, decides whether
   to merge to master or `git reset --hard pre-phase17-voice-upgrade-2026-05-17`.
