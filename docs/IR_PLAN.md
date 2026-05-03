# IMS Agent — Incident Response Plan

**Version:** 1.0  
**Date:** 2026-05-03  
**Owner:** Program Owner / Security Lead  
**Standard:** CMMC Level 2 — IR.2.092  
**Review cycle:** Annual or after any P1/P2 incident

---

## 1. Purpose and Scope

This Incident Response (IR) Plan establishes the process for detecting, classifying, responding to, and recovering from security and operational incidents affecting the IMS Agent system and the schedule data it processes.

**In scope:**
- IMS Agent process (all transports: simulated, teams_chat, ACS)
- Dashboard server (`GET /`, `/api/*`, `/bot/messages`)
- All data files under `data/` (IMS XML, CAM sessions, cycle history)
- Anthropic API credentials, Teams bot credentials, Slack webhook

**Out of scope:**
- Customer M365 tenant security (customer responsibility)
- Host OS security (customer IT responsibility)
- Physical security (data center — customer responsibility)

---

## 2. Incident Classification

| Severity | Code | Definition | Target Response Time |
|----------|------|------------|---------------------|
| Critical | **P1** | Data breach — CUI/ITAR schedule data exposed to unauthorized parties; credential compromise confirmed | **1 hour** |
| High     | **P2** | Unauthorized access attempt confirmed; IMS data corrupted or deleted; service unavailable > 4 hours | **4 hours** |
| Medium   | **P3** | Data integrity issue (IMS write inconsistency, duplicate cycle); partial service degradation | **Next business day** |
| Low      | **P4** | Service outage < 4 hours; single-cycle failure with automatic recovery; performance degradation | **72 hours** |

---

## 3. Detection Sources

| Source | Signal | Classification |
|--------|--------|---------------|
| `action=audit_auth_failure` log events | Repeated failures from single IP in short window | P2 → investigate |
| `deadman_alert: true` in `GET /health` | No successful cycle > 2× schedule period | P4 → investigate |
| `action=cycle_failed` log events | Repeated cycle failures | P3/P4 → investigate |
| `action=master_custody_lost` log event | IMS write custody failure | P3 → investigate |
| `action=audit_admin_trigger` from unexpected IP | Unauthorized admin action | P1/P2 → escalate |
| Slack cycle-failed notification | Cycle did not complete | P4 → investigate |
| SIEM alert on `action=audit_*` pattern | Aggregated security event | Per classification |
| CAM reports unexpected schedule change | Data integrity concern | P3 → investigate |

---

## 4. Response Procedures

### P1 — Critical (Data Breach / Credential Compromise)

**Immediate (< 1 hour):**
1. **Isolate** — stop the IMS Agent process: `Ctrl-C` or `kill <pid>`; disable public network access to the dashboard port.
2. **Rotate credentials immediately** — see §9 of `docs/DR_RUNBOOK.md`:
   - Rotate `ANTHROPIC_API_KEY` in Anthropic Console
   - Rotate `DASHBOARD_API_KEY` and `DASHBOARD_ADMIN_KEY` in `.env`
   - Rotate Teams bot client secret in Azure App Registration
   - Rotate `AUTH_SECRET_KEY` (invalidates all outstanding JWTs)
3. **Preserve evidence** — copy log files before restarting:
   ```
   xcopy /E /I logs\ incident_logs\<date>\
   ```
4. **Notify** — contact CSIRT (see §6) within 1 hour of discovery.
5. **Assess scope** — determine what data was accessible; identify affected records.

**Short-term (< 24 hours):**
6. Conduct root cause analysis with CSIRT.
7. Submit breach notification per applicable regulations (DFARS 252.204-7012 — 72-hour requirement for CUI).
8. Document timeline and evidence in incident log.

---

### P2 — High (Unauthorized Access / Data Corruption)

**Response (< 4 hours):**
1. Identify the affected route and timeframe from logs:
   ```
   grep "action=audit_auth_failure" logs/ims-agent.log | tail -100
   ```
2. If access was confirmed (not just attempts): treat as P1 and escalate.
3. If data corruption detected: stop agent, restore from last-known-good IMS backup (`data/ims_exports/{latest}_diff.json`).
4. If service unavailable: follow `docs/DR_RUNBOOK.md` recovery procedure.
5. Notify CSIRT.

---

### P3 — Medium (Data Integrity / Partial Degradation)

**Response (next business day):**
1. Review `action=cycle_failed` and `action=master_custody_lost` log events.
2. Compare current IMS XML against the last diff file in `data/ims_exports/`.
3. If IMS state is inconsistent: run a manual cycle via `POST /api/trigger` after restoring from the most recent `*_snapshot.json`.
4. If duplicate cycle data: purge via `POST /api/admin/purge` with appropriate retention window.
5. Document root cause and apply fix.

---

### P4 — Low (Outage < 4 hours / Single Cycle Failure)

**Response (< 72 hours):**
1. Check `GET /health` for `deadman_alert`, `last_cycle_age_seconds`.
2. Review recent logs for the failure cause.
3. Retry the cycle: `POST /api/trigger`.
4. If agent process crashed: restart via `python main.py --serve`.
5. Log the incident and resolution in the incident register below.

---

## 5. Post-Incident Review

After any P1 or P2 incident (and optionally P3), conduct a post-incident review within **5 business days**:

| Item | Detail |
|------|--------|
| Incident date/time | |
| Detection method | |
| Root cause | |
| Data exposed (if any) | |
| Containment actions taken | |
| Credential rotations performed | |
| Time to containment | |
| Time to recovery | |
| Lessons learned | |
| Process improvements | |

---

## 6. CSIRT Contact List

> **Note:** Replace placeholder entries with actual personnel before handling any CUI/ITAR data.

| Role | Name | Phone | Email |
|------|------|-------|-------|
| Program Owner / Incident Commander | _[TBD]_ | _[TBD]_ | _[TBD]_ |
| Security Lead | _[TBD]_ | _[TBD]_ | _[TBD]_ |
| DevOps / System Admin | _[TBD]_ | _[TBD]_ | _[TBD]_ |
| Legal / Compliance | _[TBD]_ | _[TBD]_ | _[TBD]_ |
| Customer ISSO | _[TBD]_ | _[TBD]_ | _[TBD]_ |

**External contacts:**
| Resource | Contact |
|----------|---------|
| Anthropic support (API key compromise) | https://support.anthropic.com |
| Microsoft security (Teams/M365) | https://msrc.microsoft.com |
| US-CERT (CUI breach reporting) | https://www.cisa.gov/report |
| DoD DIBNET (DFARS 252.204-7012 reporting) | https://dibnet.dod.mil |

---

## 7. Incident Register

| Date | Severity | Summary | Resolution | Duration |
|------|----------|---------|------------|----------|
| _(none)_ | | | | |

---

## 8. Plan Maintenance

- Review this plan annually and after any P1/P2 incident.
- Update CSIRT contacts whenever personnel change.
- Test the P4 recovery procedure (restart from crash) quarterly.
- Reference: `docs/DR_RUNBOOK.md` for detailed recovery steps.

---

*This plan must be reviewed by the Program Owner before any CUI or ITAR-controlled data is processed by the IMS Agent.*
