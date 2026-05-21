# Phase 17 — Live-Test Followups (Phase 17.1 candidates)

After Phase 17 iter 12b achieved 60/60 eval + 11/11 flow tester, the user
took the voice agent for a live test ride. The structured interview part
worked cleanly. After WRAPUP the user intentionally pushed the agent to
go off-topic to see how it would respond.

Findings + future enhancement candidates listed in priority order.

## Reference session

- `data/voice_sessions/20260521T223801Z_alice_at_program_mil.json`
- `data/voice_turns/20260521T223801Z_<alice>.jsonl`
- Cycle ID: `20260521T223801Z`

The conversation reached WRAPUP cleanly at T13 (Alice confirmed all 3
task updates). Then the user continued probing for 6 more turns
(T14–T19) to test off-topic resilience.

---

## 17.1.1 — Off-topic scope guard for WRAPUP and ESCALATE

**Priority: HIGH** (this is what the user explicitly asked us to track)

### What we observed

After the wrap-up exchange ("Updates submitted to your PM. Talk to you
next cycle."), the user kept the session alive and asked progressively
off-topic questions:

| Turn | CAM said | ATLAS replied (excerpt) |
|---|---|---|
| T15 | "Who are you going to talk to next?" | "I don't have specific conversations lined up, but I'm here to assist anyone who needs help. If you have more questions or need assistance later, feel free to reach out!" |
| T16 | "Can you help the team get the government-furnished equipment?" | "I can provide guidance on how to approach that process or suggest steps to take. Would you like some tips on how to request or manage government-furnished equipment?" |
| T17 | "Tell my PM too?" | (markdown bullet list — see 17.1.2) |
| T18 | "What else can we talk about?" | "We can discuss project management strategies, team collaboration tools, technical challenges you're facing, or any other topics you're interested in. What would you like to dive into?" |
| T19 | "Let's talk about why the sky is blue." | Full Rayleigh scattering lecture |

### Root cause

The `WRAPUP` state in `agent/voice_v2/state_machine.py` has no
`system_prompt_addendum` constraining the LLM to stay on topic. The
default OpenAI Chat Completions persona happily talks about anything.
The `allowed_tools` list for WRAPUP is empty (correct — no actions
should fire) but the LLM's text response isn't bounded.

The `reply_templates.reply_for_state(WRAPUP, ...)` function only
returns a deterministic reply when `just_entered=True`. After the
first WRAPUP turn, subsequent user messages hit the LLM with no
scope restriction.

### Fix proposal

Three options, ranked by effort:

1. **(Easy, 30 min)** Hard-stop after one WRAPUP turn. Return a
   deterministic "We're all done for this cycle — talk to you next
   week" on every subsequent message and skip the LLM call entirely.
   Pro: zero LLM cost, can't go off-topic. Con: stiff; user can't
   ask a quick follow-up like "wait, can you also note X for me?"

2. **(Medium, 1–2 hr)** Add an "in-scope?" classifier as the first
   step on WRAPUP-state turns. Pre-LLM Python regex/keyword check
   answers "does this transcript relate to IMS status / project
   risks / a task already covered?" If yes, run the LLM with a
   constrained prompt. If no, return the polite-deflection phrase.

3. **(Robust, 4 hr)** Add a `CamScopeGuard` LLM call that runs as a
   first pass for ANY turn (not just WRAPUP). Cheap gpt-4o-mini
   classification: "Is this CAM utterance about (a) their assigned
   IMS tasks, (b) blockers/risks on those tasks, (c) confirmation/
   wrap-up, (d) off-topic?" If (d), polite deflect with a fixed
   phrase. Could even bind to the topic blocklist already in
   `guards.py`.

### Recommended polite-deflection phrase

> "That's outside what I'm set up to cover. If you have more task
> updates this cycle, I'm happy to capture them; otherwise I'll
> circle back next cycle."

(Add as `_OUT_OF_SCOPE_PHRASE` constant in state_machine.py alongside
`ESCALATION_PHRASE`.)

### Test scenarios to add

Should land in both `scripts/test_conversation_flow.py` and
`scripts/eval_voice_v2.py` once the guard is built:

- `offtopic.after_wrapup.weather` — "what's the weather like?" after WRAPUP
- `offtopic.after_wrapup.cooking` — "tell me a recipe"
- `offtopic.during.gossip` — "did you hear about Bob from accounting?"
- `offtopic.during.help_request` — "can you help me with my expense report?"
- `offtopic.during.sky_blue` — the actual T19 from this session
- `inscope.after_wrapup.followup_task_update` — "wait, I forgot — task 2 is actually at 80% not 78%" — should re-open the interview gracefully

---

## 17.1.2 — Markdown leaked into voice reply

**Priority: MEDIUM** (sounds bad via TTS but only happens in off-topic
turns which 17.1.1 will block anyway)

### What we observed

T17 reply from the live session:

> "I can't directly communicate with your PM, but I can suggest some
> steps you can take to inform them. Here are some tips:\n\n1. **Identify
> Requirements**: Clearly outline what government-furnished equipm..."

The literal `**` and numbered list would be spoken character-by-character
by TTS ("asterisk asterisk identify requirements asterisk asterisk colon").

### Root cause

`guards.apply_output_guard()` does strip markdown (`*`, `_`) but only
when the LLM also fires a `markdown_in_voice` category match. The
current pattern misses bold + numbered-list combinations.

Also: the per-state prompts say "NO MARKDOWN" but only for the
`TASK_BY_TASK_LOOP` state. `WRAPUP` and the off-topic free-response
turns don't have the rule.

### Fix proposal

1. Strengthen `guards.check_output()` to strip *all* markdown
   constructs unconditionally (bold, italic, code, headers, numbered
   lists, bullet lists). Always-on, not category-conditional.
2. Add "NO MARKDOWN" to every per-state prompt in state_machine.py.

Probably lands as part of 17.1.1.

---

## 17.1.3 — Fewer redundant LLM calls inside a single turn

**Priority: LOW** (cosmetic — affects latency, not correctness)

### What we observed

Turn 6 in the live session showed 4 tool calls fired by the LLM:

```
T6 tools: ['capture_risk', 'propose_percent_complete', 'capture_blocker', 'capture_risk']
```

The LLM fired `capture_risk` twice in the same response. The dispatcher
silently overwrites the first with the second, so no data corruption,
but it suggests the prompt is encouraging redundant calls.

Turn 7 had 3 calls including 2× `propose_percent_complete`:

```
T7 tools: ['propose_percent_complete', 'propose_percent_complete', 'capture_blocker']
```

### Fix proposal

In `_dispatch_tool_calls`, dedupe by `(tool_name, task_id)` and keep
only the last call. Or instruct the prompt more strictly: "call each
tool at most ONCE per response."

Token cost impact is negligible (~$0.0001/turn) so this is purely a
cleanup item.

---

## 17.1.4 — Whisper STT batch latency is noticeable on voice

**Priority: MEDIUM** (already documented in PHASE-17-PLAN.md but
restating since user mentioned it earlier)

### What we observed

Each spoken utterance takes ~2–4 seconds to transcribe via Whisper API
(batch endpoint). For typed input (the dominant test mode so far),
this doesn't matter. For voice it adds noticeable lag before ATLAS
even starts processing.

### Fix proposal

Migrate to Deepgram Flux for STT — same wrapper pattern as
`stt_openai.py` makes this drop-in (~2 hr). Article §4 highlight:
Flux's semantic end-of-turn detection alone saves 200–400ms per
turn vs silence threshold. Drops total per-turn latency from
~3–5 sec to ~700–900 ms for voice.

---

## 17.1.5 — Session shouldn't auto-resume across cycles

**Priority: LOW** (a side effect of iter 3's session persistence
feature, only matters for stale UX)

### What we observed

The voice-tester resumes the last incomplete session when the same
CAM is selected. Good for "I closed the tab mid-call." Bad for
"new cycle, fresh start." There's a RESET button but it's a
manual step.

### Fix proposal

Auto-reset the session when the cycle_id has changed since the last
persisted state. Or only resume sessions less than N hours old.

---

## Estimated effort to address all 5 items

| Item | Effort | Impact |
|---|---|---|
| 17.1.1 off-topic guard | 1–4 hr | HIGH (visible in live testing) |
| 17.1.2 markdown stripping | 30 min | MEDIUM (only visible during off-topic; fixing 17.1.1 hides this) |
| 17.1.3 dedupe tool calls | 30 min | LOW (cosmetic) |
| 17.1.4 Deepgram migration | 2 hr | MEDIUM (voice-only) |
| 17.1.5 session staleness | 30 min | LOW (rare UX) |

Recommend bundling 17.1.1 + 17.1.2 + 17.1.3 as Phase 17.1 (~2–5 hr).
Defer 17.1.4 to Phase 18 (voice quality). Defer 17.1.5 indefinitely
unless it bites someone.
