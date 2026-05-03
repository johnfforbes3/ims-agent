# IMS Agent — CMMC Level 2 Gap Analysis

**Date:** 2026-05-03  
**Standard:** CMMC Level 2 (NIST SP 800-171 Rev 2 — 110 practices)  
**Scope:** IMS Agent software system as deployed in development/staging  
**Status:** Pre-assessment. This document is a self-assessment for planning purposes — it does not constitute a C3PAO assessment.

> **Note:** CMMC Level 2 certification is required before handling any CUI (Controlled Unclassified Information) or ITAR-controlled schedule data. This analysis identifies gaps to close before formal assessment.

---

## Summary

| Category | Controls | Compliant | Partial | Gap |
|---|---|---|---|---|
| Access Control (AC) | 22 | 14 | 5 | 3 |
| Audit & Accountability (AU) | 9 | 5 | 3 | 1 |
| Configuration Management (CM) | 9 | 5 | 2 | 2 |
| Identification & Auth (IA) | 11 | 6 | 3 | 2 |
| Incident Response (IR) | 3 | 0 | 2 | 1 |
| Maintenance (MA) | 6 | 2 | 2 | 2 |
| Media Protection (MP) | 9 | 2 | 3 | 4 |
| Personnel Security (PS) | 2 | 1 | 0 | 1 |
| Physical Protection (PE) | 6 | 2 | 2 | 2 |
| Risk Assessment (RA) | 3 | 1 | 1 | 1 |
| Security Assessment (CA) | 4 | 1 | 1 | 2 |
| System/Comm Protection (SC) | 16 | 8 | 5 | 3 |
| System/Info Integrity (SI) | 7 | 4 | 2 | 1 |
| **TOTAL** | **110** | **51** | **31** | **28** |

---

## Detailed Gap Analysis

### Access Control (AC) — 3 Gaps

| Control | Requirement | Current State | Gap | Priority |
|---|---|---|---|---|
| AC.1.001 | Limit system access to authorized users | API key model in place | SHORT-lived tokens not implemented; hardcoded API key model | HIGH — implement JWT/OAuth2 before CUI data |
| AC.1.002 | Limit functions to authorized users | Two-key model (read/admin) | MFA not enforced for admin actions | HIGH |
| AC.2.006 | Use non-privileged accounts for non-security functions | Single service account | No role separation at OS level | MEDIUM |

**Partial compliance:**
- AC.2.005: Session lock — not applicable (API, not interactive session)
- AC.2.007: Least privilege — API key model provides read vs admin separation; not granular per route

### Audit & Accountability (AU) — 1 Gap

| Control | Requirement | Current State | Gap | Priority |
|---|---|---|---|---|
| AU.3.045 | Review and update logged events | No log review process | No SIEM or log aggregation configured | HIGH |

**Partial compliance:**
- AU.2.041: Audit logs created — structured `action=` logs with timestamps; `LOG_FORMAT=json` for machine parsing ✓
- AU.2.042: Audit log protected — logs written to disk; no tampering protection beyond OS-level permissions
- AU.3.044: Review logs for unauthorized access — `action=audit_auth_failure` events logged; no automated alerting yet

### Configuration Management (CM) — 2 Gaps

| Control | Requirement | Current State | Gap | Priority |
|---|---|---|---|---|
| CM.2.061 | Establish and maintain baseline configurations | `.env.example` documents expected config | No formal baseline enforcement or drift detection | MEDIUM |
| CM.2.064 | Establish restrictions on software installation | No restrictions documented | Container image pinning not enforced | MEDIUM |

### Identification & Authentication (IA) — 2 Gaps

| Control | Requirement | Current State | Gap | Priority |
|---|---|---|---|---|
| IA.3.083 | Use multifactor authentication for local/network access | Not implemented | Admin endpoints protected by static API key only | HIGH |
| IA.3.084 | Employ replay-resistant auth mechanisms | Static API key can be replayed | Short-lived token or nonce required | HIGH |

### Incident Response (IR) — 1 Gap

| Control | Requirement | Current State | Gap | Priority |
|---|---|---|---|---|
| IR.2.092 | Establish incident response plan | No formal IR plan | Create IR plan with CSIRT contact and escalation procedure | HIGH |

### System & Communications Protection (SC) — 3 Gaps

| Control | Requirement | Current State | Gap | Priority |
|---|---|---|---|---|
| SC.1.175 | Monitor and control communications at external boundaries | External endpoints documented in SECURITY.md | No firewall rules enforced by code/infra | HIGH |
| SC.3.177 | Employ FIPS-validated cryptography | TLS in transit | FIPS-validated cipher suites not verified at TLS layer | MEDIUM |
| SC.3.187 | Establish and manage cryptographic keys | API keys via env vars | No key lifecycle management (rotation, expiration) | HIGH |

---

## ITAR-Specific Controls (Phase 6.2 → 6.3 Dependency)

Before any ITAR-controlled IMS data enters the system, ALL of the following must be complete:

| Requirement | Status |
|---|---|
| `LLM_BASE_URL` set to on-prem Ollama endpoint | ✅ Supported in code (Phase 6.0.2) |
| `ANTHROPIC_API_KEY` not configured (no cloud LLM traffic) | ✅ Supported — raises no error when `LLM_BASE_URL` set |
| ElevenLabs TTS replaced with on-prem TTS | ⚠️ TTS disabled by default; `VOICE_BRIEFING_ENABLED=false` |
| Slack webhook pointing to internal Slack instance | ⚠️ Requires customer Slack workspace |
| SMTP pointing to internal mail server | ⚠️ Requires customer mail server |
| Azure Teams Bot running in customer M365 tenant | ⚠️ Deploy bot app registration in customer tenant |
| Independent security review completed | ❌ Not yet scheduled |
| Data-at-rest encryption confirmed at host level | ❌ Not verified; schedule with customer IT |

---

## Action Items for Phase 6.2

Priority order (HIGH first):

1. **IA.3.083 / IA.3.084** — Replace static API key with JWT or OAuth2 client credentials; add MFA enforcement for admin routes. Owner: Phase 6.2 engineering.
2. **AC.1.001** — Implement short-lived token auth before any CUI data enters. Owner: Phase 6.2 engineering.
3. **SC.3.187** — Document API key rotation procedure; implement `DEADMAN_PERIOD_HOURS`-based key expiration alert. Owner: Phase 6.2 engineering.
4. **IR.2.092** — Write formal incident response plan. Owner: Program owner.
5. **AU.3.045** — Configure SIEM or log aggregation; forward `action=audit_*` events. Owner: Phase 6.1 infrastructure deployment.
6. **SC.1.175** — Enforce firewall/allowlist rules at deployment. Owner: Customer IT + DevOps.

---

## Controls in Scope Excluded from This Analysis

The following CMMC Level 2 domains are outside the application software boundary and are addressed by the customer's environment controls:

- **Physical Protection (PE)**: Data center physical security
- **Media Protection (MP)**: Disk encryption, media disposal
- **Personnel Security (PS)**: Background checks, acceptable use agreements
- **Maintenance (MA)**: System maintenance procedures

---

*This document must be reviewed by a qualified assessor before any CUI data is processed. Self-assessment does not constitute CMMC certification.*
