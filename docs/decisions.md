# Architecture Decision Records

## ADR-001 — IMS File Format: MSPDI XML Instead of Binary .mpp

**Date:** 2026-04-25  
**Status:** Accepted  
**Phase:** 1

### Context

Microsoft Project stores schedules in a binary `.mpp` format. Two main options exist for reading `.mpp` files in Python:

1. **python-mpxj** — a Python wrapper around the MPXJ Java library, which can read and write `.mpp` files natively. Requires a JRE 11+ on every machine that runs the agent.
2. **MSPDI XML export** — Microsoft Project can export/import the full schedule as an XML file (Microsoft Project Data Interchange format). This is the same XML format MPXJ uses internally. Pure Python parsing with `xml.etree.ElementTree`; no Java dependency.

### Decision

Use **MSPDI XML** for Phase 1.

### Rationale

- Zero external runtime dependency (no JRE required on dev or deployment machines)
- Standard XML is easy to inspect, test against, and commit to source control
- MSPDI is the format MS Project uses natively for XML import/export — any planner can produce one from File → Save As → XML
- MPXJ Java bridge remains the Phase 2+ upgrade path once live `.mpp` files need to be read directly without a manual export step
- The synthetic test file can be authored as MSPDI XML directly, making test data fully readable and version-controlled

### Consequences

- Phase 1 requires the planner to export the `.mpp` file to XML before the agent can read it (one extra step)
- Write-back in Phase 1 updates the XML copy; the planner imports it back into MS Project (manual round-trip)
- Phase 2 will evaluate adding `python-mpxj` to eliminate the manual export step

---

## ADR-002 — SRA: Python Monte Carlo From Scratch

**Date:** 2026-04-25  
**Status:** Accepted  
**Phase:** 1

### Context

The program plan lists three SRA options: (a) Python Monte Carlo from scratch, (b) subprocess/API to an existing SRA tool, (c) OpenPlan or similar. Open Question #1 in Appendix C asks what SRA tool is currently in use.

### Decision

Build **Python Monte Carlo from scratch** for Phase 1.

### Rationale

- No dependency on any external SRA tool (which may not be accessible, licensed, or available in the dev environment)
- Full control over the simulation logic and output format
- Sufficient for Phase 1 validation; the ±10% duration uncertainty default matches the plan's specified approach
- Easy to test deterministically by seeding the random number generator

### Consequences

- Does not replicate the exact methodology of any specific SRA tool a client may use
- If a client uses a specific SRA tool (e.g., Acumen Risk, Polaris), integration can replace this implementation in Phase 2+

---

## ADR-003 — LLM: Anthropic API with claude-sonnet-4-6

**Date:** 2026-04-25  
**Status:** Accepted  
**Phase:** 1

### Context

Phase 1 is a local PoC with synthetic (non-ITAR) data. Two options: Anthropic cloud API or local Ollama model.

### Decision

Use **Anthropic API** (`claude-sonnet-4-6`) for Phase 1.

### Rationale

- Phase 1 uses only synthetic data — no ITAR/CUI concerns
- Simpler setup than local Ollama (no GPU required, no model download)
- `claude-sonnet-4-6` provides strong reasoning at lower cost than Opus
- Model is configurable via `ANTHROPIC_MODEL` env var — swapping to a local model requires only changing that variable and updating `llm_interface.py`

### Consequences

- Phase 5 production hardening will require replacing with an on-prem model for ITAR compliance
- All LLM calls are routed through `agent/llm_interface.py` to make this swap easy
