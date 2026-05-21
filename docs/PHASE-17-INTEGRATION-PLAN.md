# Phase 17 — Integration Plan (voice as a channel on the existing flow)

**Status:** Planning. **No code lands until explicit go-ahead.**
**Branch when work begins:** new branch `phase17/voice-integration` off
`phase17/voice-upgrade` (so the standalone tester history is preserved).

## Guiding principles (locked from user direction)

1. **Tester aligned with production.** `/voice/test` must exercise the *same*
   `InterviewAgent` and the *same* edge shims that production uses. No
   divergent code paths.
2. **Voice-out default ON.** ATLAS speaks every question as a Teams voice
   message in addition to (or eventually instead of) text. CAMs implicitly
   switch back to text by typing — no preference flag needed, no setting to
   toggle.
3. **17.1 (off-topic guard + markdown stripper) is bundled in** because both
   issues affect the path text-CAMs already use today, not just the
   standalone tester.
4. **Existing flow is preserved.** `cycle_runner.py`, `teams_chat_connector.py`,
   `interview_agent.py`, `cam_inputs` shape, dashboard endpoints, all
   downstream analysis steps — *zero changes to interfaces or behavior on
   the text path*.

## What the existing CONOPS does (unchanged)

```
CycleRunner.run()
   ├─ parse IMS (file_handler)
   ├─ for each CAM:
   │     ChatInterviewManager.start_proactive(cam)
   │        → teams_chat_connector sends first Q via Teams Bot
   │     /bot/messages receives CAM reply
   │        → ChatInterviewSession.handle_incoming(text)
   │           → InterviewAgent.process(text) → AgentTurn
   │           → ChatInterviewSession sends reply text via Teams Bot
   │     loop until InterviewState.CLOSING
   │     return cam_inputs (list of dicts)
   ├─ apply_updates(cam_inputs) → IMS XML → .mpp
   ├─ analysis: CPM / SRA / EVM / DCMA / variance
   ├─ persist dashboard_state.json + cycle_history.json
   └─ render PM dashboard via existing /api/* endpoints
```

**Everything labeled "unchanged" stays unchanged.**

## What we're adding — voice as edge shims

Two surgical insertions at the seams of `/bot/messages`. Nothing inside
`InterviewAgent` or `ChatInterviewSession` changes.

```
                Teams chat
                ───────────
   ┌─────────────────────────────────────────────┐
   │  CAM message arrives → /bot/messages         │
   └───────────────┬─────────────────────────────┘
                   │
   ┌───────────────▼──────────────────────────────┐
   │  VOICE-IN SHIM (new — Phase 17.2)             │
   │  if message has audio attachment:             │
   │     audio = graph_download(attachment_url)    │
   │     text  = stt_openai.transcribe(audio)      │
   │     log: voice turn with transcript           │
   │  else:                                        │
   │     text = message.text  (existing path)      │
   └───────────────┬──────────────────────────────┘
                   │
   ┌───────────────▼──────────────────────────────┐
   │  EXISTING — unchanged                          │
   │  ChatInterviewSession.handle_incoming(text)   │
   │    → InterviewAgent.process(text)             │
   │    → AgentTurn(reply_text, new_state)         │
   └───────────────┬──────────────────────────────┘
                   │
   ┌───────────────▼──────────────────────────────┐
   │  OUTPUT GUARD (new for both channels — 17.1)  │
   │  - strip ALL markdown unconditionally          │
   │  - block over-promise phrases                 │
   │  - if state is CLOSING and CAM tries to chat: │
   │       deflect with fixed phrase                │
   └───────────────┬──────────────────────────────┘
                   │
   ┌───────────────▼──────────────────────────────┐
   │  VOICE-OUT SHIM (new — Phase 17.3)            │
   │  always send_text(clean_reply)  (existing)    │
   │  if TEAMS_VOICE_OUT enabled:                  │
   │     audio = tts.synthesize(clean_reply)       │
   │     send_audio_attach(audio) via Bot Framework│
   └──────────────────────────────────────────────┘
```

## Sub-phase breakdown

### 17.1 — Output guard + scope guard at the InterviewAgent reply seam
**Scope:** Apply unconditional markdown stripping and an off-topic deflection
guard to **every** reply text from `InterviewAgent.process()` — covering both
text-CAM and voice-CAM paths from a single chokepoint.

| Item | What | Where | Files touched |
|---|---|---|---|
| 17.1.1 | Always-on markdown stripper | new module `agent/voice/reply_sanitizer.py` (placed under `agent/voice/` so it's owned by the same package as InterviewAgent) | new file + 1-line call in `teams_chat_connector.ChatInterviewSession._send_reply` |
| 17.1.2 | Off-topic / CLOSING-state deflection | same `reply_sanitizer.py` | same chokepoint |

**Effort:** 2 hr. **Risk:** LOW — pure post-processing, additive, behind no flag (or behind `INTERVIEW_OUTPUT_SANITIZER=true` default ON if you want it flag-controlled for safety).

**Eval coverage:** add 4 scenarios to existing `scripts/eval_voice_v2.py`
that exercise the markdown-leak and off-topic patterns. Verify all eval +
flow tester suites still green.

**Rollback:** unset env flag, revert one commit.

---

### 17.2 — Voice-IN shim (CAM can reply via Teams voice message)
**Scope:** `/bot/messages` detects an audio attachment, downloads it via
Microsoft Graph, runs Whisper STT, and passes the transcript to the existing
`ChatInterviewSession.handle_incoming()`.

| Item | What | Where | Files touched |
|---|---|---|---|
| 17.2.1 | Attachment detector | `agent/dashboard/server.py /bot/messages` route | modify route (small) |
| 17.2.2 | Graph audio download helper | new file `agent/voice/teams_voice_io.py` | new file |
| 17.2.3 | Reuse existing `agent/voice_v2/stt_openai.py` for Whisper | unchanged | import from existing module |
| 17.2.4 | Log voice turns to `data/voice_turns/<cycle_id>.jsonl` via existing `agent/voice_v2/turn_log.py` | unchanged | import from existing module |
| 17.2.5 | Env flag `TEAMS_VOICE_IN=true` defaults ON | `.env.example` | doc + default value |

**Effort:** 2-3 hr. **Risk:** LOW — text path entirely unchanged; voice path
is purely additive.

**Eval coverage:** new test file `tests/test_voice_in_shim.py` covering:
- text message → existing path unchanged
- audio attachment → STT → handle_incoming called with transcript
- audio download failure → graceful fallback to "[unable to transcribe]"
- Whisper error → same fallback

**Rollback:** `TEAMS_VOICE_IN=false` in `.env`, restart server.

---

### 17.3 — Voice-OUT shim (ATLAS speaks every reply, CAM can reply by typing)
**Scope:** After `ChatInterviewSession._send_reply` posts the text message,
also synthesize TTS and send as an audio attachment in the same Teams chat.

| Item | What | Where | Files touched |
|---|---|---|---|
| 17.3.1 | Per-reply TTS synthesis | reuse `agent/voice_v2/tts.py` | import |
| 17.3.2 | Send audio attachment via Bot Framework REST | extend `agent/voice/teams_voice_io.py` | same new file as 17.2 |
| 17.3.3 | Skip TTS for very short acknowledgments (< 12 chars) | logic inside shim | small heuristic |
| 17.3.4 | Env flag `TEAMS_VOICE_OUT=true` defaults ON | `.env.example` | doc + default value |
| 17.3.5 | Per-CAM voice ID (already configured in `ELEVENLABS_CAM_VOICES`) | existing | no change |

**Effort:** 1-2 hr. **Risk:** LOW — text reply still sent; audio is supplementary.

**Implicit text-switch behavior (per user decision #2):** there is no flag
to set per CAM. If a CAM types a reply, the next turn still includes
audio-out (because the agent has no way to know if the CAM listened to
the audio or read the text). ATLAS just always provides both — the CAM
picks whichever they prefer in real time.

**Eval coverage:** integration test that posts a synthetic /bot/messages
event and verifies (a) text reply lands, (b) audio attachment lands, (c)
audio is valid mp3 bytes.

**Rollback:** `TEAMS_VOICE_OUT=false` in `.env`, restart server.

---

### 17.4 — Re-align `/voice/test` with the production path (per user decision #1)
**Scope:** Retire `agent/voice_v2/pipeline.py` (the standalone Session
engine) for the tester. The tester now drives the production
`InterviewAgent` through the same shims as the Teams path, so it exercises
the same code that ships.

| Item | What | Where | Files touched |
|---|---|---|---|
| 17.4.1 | Tester WebSocket reroutes to InterviewAgent | `agent/voice_v2/transport_web.py` | rewrite the session handler |
| 17.4.2 | Web tester UI keeps its existing widgets (mic, dropdown, telemetry) | `agent/dashboard/static/voice_tester/*` | mostly unchanged |
| 17.4.3 | Mark `pipeline.py`, `state_machine.py`, `field_router.py`, `reply_templates.py`, `small_talk.py` as DEPRECATED in `agent/voice_v2/` | header comments | doc only |
| 17.4.4 | `scripts/test_conversation_flow.py` updated to drive `InterviewAgent` instead of `pipeline.Session` | rewrite assertions if needed | one file |

**Effort:** 3-4 hr. **Risk:** MEDIUM — this is the largest change because it
swaps the tester engine. Mitigated by:
- branch isolation (no master impact)
- the 11/11 flow-tester scenarios become the acceptance bar for the rewired tester
- existing standalone voice_v2 code is *kept on disk* (just deprecated) so we
  can revert if the alignment surfaces an InterviewAgent gap that the
  voice_v2 engine handles better — in that case we know exactly which gap
  to fix in InterviewAgent

**Eval coverage:** flow tester must still pass 11/11 against InterviewAgent.
If specific scenarios fail, those failures point at gaps in InterviewAgent
that need a fix before 17.4 ships.

**Rollback:** revert the commit; voice_v2/pipeline.py is still on disk and
the tester reverts to using it.

---

### 17.5 — Concrete decisions resolved by user direction

| Question | Decision | Implementation |
|---|---|---|
| Standalone tester fate | Keep | 17.4 aligns it with production |
| Voice-out default | ON for everyone | 17.3 default `TEAMS_VOICE_OUT=true` |
| Per-CAM voice/text preference flag | Not needed | Implicit text-switch by typing |
| Bundle 17.1 | Yes | Lands first, before any voice plumbing |
| Touch existing text path / interview agent | NO | All sub-phases preserve existing behavior |

## What gets retired and what stays from Phase 17 work

| Phase 17 component | Decision | Reasoning |
|---|---|---|
| `agent/voice_v2/stt_openai.py` (Whisper) | **KEEP** | Used by 17.2 voice-in shim |
| `agent/voice_v2/tts.py` (ElevenLabs + OpenAI fallback) | **KEEP** | Used by 17.3 voice-out shim |
| `agent/voice_v2/turn_log.py` | **KEEP** | Used by 17.2 for voice-turn logging |
| `agent/voice_v2/llm_openai.py` (spend cap) | **KEEP** | $25 hard cap on STT/TTS cost |
| `agent/voice_v2/guards.py` | **MERGE INTO 17.1** | The sanitizer + scope guard inherit this logic |
| `agent/voice_v2/audit_log.py` integration | **KEEP** (Phase 16 module) | Voice events get logged like any other admin event |
| `agent/voice_v2/cycle_heartbeat.py`, `circuit_breaker.py` | **KEEP** (Phase 16) | Production infrastructure |
| `agent/voice_v2/pipeline.py` (Session engine) | **DEPRECATE in 17.4** | Replaced by InterviewAgent in the tester |
| `agent/voice_v2/state_machine.py` | **DEPRECATE in 17.4** | Replaced by InterviewAgent's state machine |
| `agent/voice_v2/field_router.py` | **DEPRECATE in 17.4** | Replaced by InterviewAgent's classifiers |
| `agent/voice_v2/reply_templates.py` | **DEPRECATE in 17.4** | Replaced by InterviewAgent's reply generation |
| `agent/voice_v2/small_talk.py` | **DEPRECATE in 17.4** | InterviewAgent's GREETING state handles this |
| `agent/voice_v2/judge.py` (LLM-as-judge sampling) | **KEEP** | Useful observability for voice turns |
| `agent/voice_v2/transport_web.py` (WebSocket) | **REWIRE in 17.4** | Bridge to InterviewAgent instead of pipeline.Session |

**Deprecation policy:** files marked deprecate are kept on disk with a
`# DEPRECATED — see PHASE-17-INTEGRATION-PLAN.md` header. Not deleted in case
we need to reference the prompt engineering or state-machine design.

## Sequencing

```
17.1 ──► 17.2 ──► 17.3 ──► 17.4
(sanitize) (voice-in) (voice-out) (tester realign)
```

Each step is independent enough that we could ship 17.1 alone, then pause
and gather feedback, before continuing.

## Total effort + risk

| Sub-phase | Effort | Risk | Touches production cycle? |
|---|---|---|---|
| 17.1 | 2 hr | LOW | Sanitizer at reply seam — affects text replies too |
| 17.2 | 2-3 hr | LOW | Adds STT branch at `/bot/messages`; text path unchanged |
| 17.3 | 1-2 hr | LOW | Adds TTS+audio-attach; text reply still sent |
| 17.4 | 3-4 hr | MEDIUM | Tester rewired (not production); branch-isolated |
| **TOTAL** | **8-11 hr** | **LOW overall** | Production text path stays identical |

## Rollback summary

| Layer | How |
|---|---|
| Soft (per-sub-phase) | Flip env flag, restart server (10 s) |
| Branch | Stay on `master` (Phase 16 production); `phase17/voice-integration` branch isolated |
| Tag | `git reset --hard pre-phase17-voice-upgrade-2026-05-17` |
| Per-CAM dynamic | No flag — implicit. CAM types → text reply route used. CAM voice-memos → STT route used. ATLAS always sends both text and audio out (when 17.3 enabled). |

## Acceptance criteria for the bundle

Before merging to master:
1. Existing `tests/test_voice_v2.py` (58 tests) passing.
2. Existing 60-scenario eval passing.
3. Existing 11-scenario flow tester passing — even after 17.4 rewires the tester onto InterviewAgent.
4. New voice-shim tests passing (17.2 + 17.3 add their own).
5. A live cycle (`force=true`) completes end-to-end via Teams with:
   - At least one CAM reply received as a voice message → STT → InterviewAgent → IMS update
   - At least one ATLAS question sent as audio attachment → CAM listens to / reads either modality
   - cycle_history.json + dashboard_state.json updated with NO format changes
   - PM dashboard renders correctly with no new panels needed
6. `/voice/test` tester drives a 3-task interview to completion through the production `InterviewAgent` (proving alignment).

## Open / deferred items (NOT part of this plan)

- Deepgram Flux STT migration (perf win, low priority — Phase 17.5 or 18)
- Real phone calls via ACS (separate transport — Phase 18+)
- Cross-modal session resume (voice CAM closes phone, reopens Teams chat — Phase 18+)
- Multi-language voice (English-only for now — Phase 19+)

## Ready for go-ahead

This is the plan. **No code lands until explicit approval.** Question for
you before I start any branch: should 17.1 (sanitizer) ship to **master**
on its own as a small standalone improvement to the existing text path,
or do you want all four sub-phases bundled as a single integration PR?

Recommendation: ship 17.1 to master independently. It's an immediate
improvement to text-CAM replies (cleaner formatting, scoped to status
topics), has no voice dependencies, and trades zero risk for real polish.
17.2-17.4 then go in as a separate `phase17/voice-integration` PR.
