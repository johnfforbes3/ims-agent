# ADR-004 — Teams Integration: Azure Communication Services (Scaffolded)

**Date:** 2026-04-25  
**Status:** Active — Azure subscription and ACS resource provisioned 2026-04-25  
**Phase:** 2

## Context

Phase 2 requires the agent to initiate outbound voice calls to CAMs. Three options were evaluated:

### Option A — Teams Bot Framework
Build a bot registered in Azure Bot Service and surfaced in Teams as a bot app. Strong for chat and text interactions; however, it cannot initiate outbound *voice* calls to Teams users. Ruled out for Phase 2.

### Option B — Azure Communication Services (ACS)
ACS is Microsoft's cloud communication platform. It can:
- Initiate outbound VoIP calls to Teams users via the ACS → Teams interoperability bridge
- Stream real-time audio for STT/TTS
- Run entirely within the Azure/M365 tenant boundary (ITAR-compatible on-prem later)

Requires: Azure subscription, ACS resource, Teams-ACS interop enabled by Teams admin.

### Option C — Power Automate
Low-code trigger layer; cannot do real-time voice streaming. Ruled out.

## Decision

**Azure Communication Services (ACS)** is the target production transport for Phase 2+.

As of 2026-04-25:
- Azure subscription active (free trial, $200 credit, tenant: intelligenceexpanse.onmicrosoft.com)
- ACS resource `ims-agent-acs` deployed in resource group `ims-agent-rg`
- `ACS_CONNECTION_STRING` and `TEAMS_TENANT_ID` populated in `.env`
- Remaining: Teams-ACS interop enable, agent identity, `TeamsACSConnector` implementation

All interview logic, TTS, STT, and extraction modules are built against an abstract
`CallTransport` interface. The `TeamsACSConnector` is a documented stub.

## Migration path when Azure is available

1. ~~Create an Azure subscription and resource group~~ ✅ Done 2026-04-25
2. ~~Provision an ACS resource~~ ✅ `ims-agent-acs` deployed 2026-04-25
3. Enable Teams-ACS interoperability in the Teams admin center ⬅ next
4. Obtain an ACS user identity for the agent (via ACS Identity SDK)
5. ~~Populate `.env` with `ACS_CONNECTION_STRING`, `TEAMS_TENANT_ID`~~ ✅ Done 2026-04-25
6. Implement `TeamsACSConnector` (currently a stub in `agent/voice/teams_connector.py`)
7. Activate by setting `CALL_TRANSPORT=teams_acs` in `.env`
8. The rest of the pipeline (interview agent, STT, TTS, extraction) is unchanged

## Current transport

`SimulatedTransport` — Claude generates CAM responses; no audio infrastructure required.
Activated by `CALL_TRANSPORT=simulated` (default).

---

# ADR-005 — TTS: ElevenLabs Now, Azure Neural TTS Later

**Date:** 2026-04-25  
**Status:** Accepted  
**Phase:** 2

## Decision

Use **ElevenLabs API** for Phase 2 TTS. Migrate to **Azure Cognitive Services Neural TTS**
in Phase 5 production hardening.

## Rationale

- ElevenLabs voice quality is noticeably better than Azure's standard voices for
  conversational interactions; this matters for CAM adoption
- User already has an ElevenLabs account
- Azure Neural TTS is the correct long-term choice for on-prem/ITAR compliance
  (can run on Azure Government or on-prem via Azure Stack)
- The `TTSEngine` abstract base class makes swapping trivial — one env var change

## Migration path

Set `TTS_PROVIDER=azure` in `.env` and provide `AZURE_SPEECH_KEY` +
`AZURE_SPEECH_REGION`. `AzureNeuralTTSEngine` (implemented in tts_engine.py) activates
automatically.

---

# ADR-006 — STT: OpenAI Whisper (Local)

**Date:** 2026-04-25  
**Status:** Accepted  
**Phase:** 2

## Decision

Use **openai-whisper** running locally for speech-to-text.

## Rationale

- No API key required — runs on CPU (no GPU needed for `base` model)
- ITAR-compatible: audio never leaves the machine
- Handles domain-specific jargon better than cloud STT when a custom vocabulary
  is added via prompt injection (Whisper supports an `initial_prompt` parameter)
- Azure Cognitive Services Speech is the Phase 5 upgrade for real-time streaming

## Requirements

- `pip install openai-whisper` — pulls in PyTorch automatically
- `ffmpeg` must be on PATH for audio file decoding
- In simulation mode (no real audio), Whisper is bypassed entirely;
  `MockSTTEngine` is used automatically
