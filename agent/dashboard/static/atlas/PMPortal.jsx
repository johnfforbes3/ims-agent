// Tab 2: Program Management Portal
// Top Risks, Recommended Actions, Schedule Health History, Executive Briefing, Variance Narrative

function PMPortalTab() {
  const [briefOpen, setBriefOpen] = useState(false);
  const [briefGenerating, setBriefGenerating] = useState(false);
  const [brief, setBrief] = useState(null);

  function generateBrief() {
    setBriefGenerating(true);
    setBriefOpen(true);
    // simulate LLM streaming completion
    setTimeout(() => {
      setBrief({
        generated: "2026-05-16 09:42Z",
        cycle: "C-2026-19",
      });
      setBriefGenerating(false);
    }, 1400);
  }

  const last = window.HEALTH_HISTORY[window.HEALTH_HISTORY.length - 1];
  const start = window.HEALTH_HISTORY[0];

  return (
    <div className="page stack" style={{gap: 24}}>

      {/* Generate Executive Briefing CTA */}
      <Panel
        id="01"
        title="EXECUTIVE BRIEFING · ONE-CLICK"
        right={<span className="hint">LAST RUN · 2026-05-09 09:00Z</span>}
      >
        <div style={{display:"flex", alignItems:"center", justifyContent:"space-between", gap:24}}>
          <div style={{maxWidth: 760}}>
            <div style={{fontFamily:"var(--cond)", fontSize: 28, letterSpacing:"-0.01em", marginBottom: 6}}>
              Generate this cycle's executive briefing.
            </div>
            <div className="prose">
              <p>Single-page HTML packet for the program review. Pulls the latest summary schedule, EVM and DCMA scores, the top three risks, and ATLAS-synthesized recommended actions. Ready in under five seconds.</p>
            </div>
          </div>
          <div style={{display:"flex", gap:10}}>
            <button className="btn" onClick={() => alert("Briefing scheduled for daily auto-generation at 06:00Z.")}>
              SCHEDULE AUTO
            </button>
            <button className="btn primary" onClick={generateBrief}>
              ⌗ GENERATE BRIEFING
              <span className="kbd">⌘ G</span>
            </button>
          </div>
        </div>
      </Panel>

      <SectionHeader ix="02" label="LLM-SYNTHESIZED INTELLIGENCE" />

      {/* Top Risks + Recommended Actions */}
      <div className="row cols-2">
        <Panel
          id="02·a"
          title="TOP RISKS · ATLAS-SYNTHESIZED"
          right={<span className="hint">SOURCE · IMS + EVM + INTERVIEW LOGS</span>}
        >
          <div className="prose">
            <p>The narrative below is generated from <strong>this cycle's IMS diff</strong>, CAM interview outcomes, and a 24-cycle horizon of EVM movements. Confidence and impact are stated; treat as decision support, not authority.</p>
          </div>
          <ol className="enum" style={{marginTop:12}}>
            {window.TOP_RISKS_PROSE.map(r => (
              <li key={r.id}>
                <span></span>
                <div>
                  <div style={{color:"var(--fg)", fontWeight:600, marginBottom:4}}>{r.title}</div>
                  <div>{r.body}</div>
                </div>
                <div style={{display:"flex", flexDirection:"column", gap:6, alignItems:"flex-end"}}>
                  <Pill tone={r.impact === "Critical" ? "bad" : r.impact === "High" ? "warn" : "info"}>{r.impact}</Pill>
                  <span className="hint">P · {(r.probability * 100).toFixed(0)}%</span>
                </div>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel
          id="02·b"
          title="RECOMMENDED ACTIONS · NEXT-STEP PLAYBOOK"
          right={<span className="hint">CONFIDENCE · MED-HIGH</span>}
        >
          <div className="prose">
            <p>Prioritized actions are ranked by expected schedule-recovery (working-days saved) and feasibility within the stated horizon. Each maps to a specific CAM and risk above.</p>
          </div>
          <ol className="enum" style={{marginTop:12}}>
            {window.PM_ACTIONS_PROSE.map(a => (
              <li key={a.id}>
                <span></span>
                <div>
                  <div style={{color:"var(--fg)", fontWeight:600, marginBottom:4}}>{a.title}</div>
                  <div>{a.body}</div>
                </div>
                <Pill tone={a.priority === "Now" ? "bad" : a.priority === "This week" ? "warn" : "info"}>{a.priority}</Pill>
              </li>
            ))}
          </ol>
        </Panel>
      </div>

      <SectionHeader ix="03" label="HEALTH HISTORY · TREND" />

      <Panel id="03·a" title="SCHEDULE HEALTH HISTORY · LAST 24 CYCLES" right={
        <div style={{display:"flex", gap: 12, alignItems:"center"}}>
          <span className="hint">CURRENT · {last}</span>
          <span style={{color: last - start < 0 ? "var(--bad)" : "var(--ok)", fontFamily:"var(--mono)", fontSize:11}}>
            {last - start >= 0 ? "▲" : "▼"} {Math.abs(last - start)} pts · 24-cycle
          </span>
        </div>
      } flush>
        <div style={{padding: 16}}>
          <LineChart values={window.HEALTH_HISTORY} w={1300} h={220} yMin={50} yMax={90} label="HEALTH SCORE · 0-100" tone={last < 70 ? "bad" : last < 80 ? "warn" : "ok"} />
        </div>
        <div style={{display:"grid", gridTemplateColumns:"repeat(4, 1fr)", borderTop:"1px solid var(--line)"}}>
          {[
            { k: "PEAK", v: Math.max(...window.HEALTH_HISTORY), c: "ok" },
            { k: "TROUGH", v: Math.min(...window.HEALTH_HISTORY), c: "bad" },
            { k: "MEAN", v: Math.round(window.HEALTH_HISTORY.reduce((a,b)=>a+b,0)/window.HEALTH_HISTORY.length), c: "warn" },
            { k: "DELTA 4-CYC", v: window.HEALTH_HISTORY[23] - window.HEALTH_HISTORY[19], c: "bad", suffix: " pts" },
          ].map((s, i) => (
            <div key={s.k} style={{padding:"12px 14px", borderRight: i<3 ? "1px solid var(--line)" : "none", background:"var(--panel-2)"}}>
              <div className="hint">{s.k}</div>
              <div className="kpi-val" style={{fontSize: 22, marginTop:4, color: s.c === "ok" ? "var(--ok)" : s.c === "bad" ? "var(--bad)" : "var(--warn)"}}>
                {s.v > 0 && s.suffix ? "+" : ""}{s.v}{s.suffix || ""}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <SectionHeader ix="04" label="SCHEDULE VARIANCE NARRATIVE · CPR FORMAT 5" />

      <Panel id="04·a" title="VARIANCE NARRATIVE · LLM-DRAFTED · PM REVIEW REQUIRED" right={<span className="hint">CYCLE C-2026-19 · 5,420 char</span>}>
        <div className="prose" style={{maxWidth: 1100}}>
          <p><strong className="accent">Cumulative SV at Period 19:</strong> The program is reporting a cumulative schedule variance of <strong>−$1,840k (−8.4% of BCWS)</strong>, driven primarily by Subsystem B (Propulsion) and Subsystem C (Thermal). Propulsion is the dominant contributor, accounting for approximately 62% of the unfavorable variance. The current trend is unfavorable and worsening on a 4-cycle moving average.</p>
          <p><strong className="accent">Root cause:</strong> A turbopump bearing supply disruption originating with the Tier-2 vendor on Cycle 15 cascaded into a 12-day cumulative slip on the critical-path task 1.2.4 (Turbopump qual). Concurrently, Subsystem C absorbed a 0.6-FTE reduction in thermal-vac analyst loading after a cross-program reallocation, extending task 1.6.2 by six days. Both items consume schedule reserve previously allocated to absorb PDR closure findings.</p>
          <p><strong className="accent">Impact:</strong> PDR is forecast to slip from <strong>12-Jun-2026</strong> to <strong>21-Jun-2026</strong> with 78% probability per the 10,000-run Monte-Carlo SRA. CDR exposure is preliminary at 7-9 working days. No customer milestone is impacted at this time; the IPR delivery on 28-Jul remains protected by 6 days of recovered float.</p>
          <p><strong className="accent">Corrective actions:</strong> ATLAS recommends (1) authorizing alternate sourcing for the turbopump bearing assembly within the current cycle, with cost exposure capped at $480k; (2) re-baselining the thermal CDR gate from 14-Aug to 21-Aug; (3) freezing the GFE ICD revision cadence through CDR closure. If actions are taken within the next two cycles, recovery of 6 working days on the critical path is achievable, returning BEI to ≥ 0.85 by Cycle 23.</p>
          <p><strong className="accent">Forecast:</strong> Without intervention, the Estimate at Completion drifts to <strong>$192,740k</strong> (VAC −$8,540k) and the 80th-percentile finish moves from 13-Aug to 18-Aug. With the recommended actions, EAC returns to <strong>$186,910k</strong> (VAC −$2,710k) and the 80th-percentile finish recovers to 14-Aug.</p>
          <hr style={{border:"none", borderTop:"1px dashed var(--line-2)", margin:"16px 0"}} />
          <div style={{display:"flex", gap:12, alignItems:"center"}}>
            <Pill tone="warn">DRAFT</Pill>
            <span className="hint">Generated by ATLAS · Confidence MED-HIGH · 16-MAY 09:42Z</span>
            <span style={{flex:1}}></span>
            <button className="btn">REGENERATE</button>
            <button className="btn">EDIT</button>
            <button className="btn primary">APPROVE FOR REPORT</button>
          </div>
        </div>
      </Panel>

      {briefOpen && (
        <BriefingModal generating={briefGenerating} brief={brief} onClose={() => setBriefOpen(false)} />
      )}
    </div>
  );
}

function BriefingModal({ generating, brief, onClose }) {
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-h">
          <span>EXECUTIVE BRIEFING · CYCLE C-2026-19 · GENERATED HTML</span>
          <button className="x" onClick={onClose}>×</button>
        </div>
        <div className="modal-b">
          {generating ? (
            <div>
              <div style={{fontFamily:"var(--mono)", color:"var(--accent)", marginBottom: 12}}>▸ ATLAS · drafting briefing…</div>
              <GeneratingLines />
            </div>
          ) : (
            <div className="prose">
              <div className="hint" style={{marginBottom: 12}}>{brief && brief.generated} · ATLAS-GENERATED · UNCLASSIFIED // PROGRAM USE</div>
              <h2>Program Executive Briefing</h2>
              <p>Cycle <strong>{brief && brief.cycle}</strong>. Schedule health is <strong>YELLOW</strong>, trending downward over the last 4 cycles. Propulsion remains the principal contributor to the unfavorable variance.</p>

              <h3>Where we stand</h3>
              <p>BEI is at <strong>0.76</strong> against a green threshold of 0.95; SFA holds at <strong>0.86</strong>. Cumulative SV is <strong>−$1,840k</strong>. PDR is forecast 9 days late at the 50th percentile and the 80th-percentile program finish has moved from <strong>13-Aug</strong> to <strong>18-Aug</strong>.</p>

              <h3>What changed this cycle</h3>
              <p>Turbopump qual (1.2.4) consumed 9 additional days of float after a vendor bearing supply commitment moved. TVAC analyst loading on 1.6.2 dropped from 2.0 to 1.4 FTE, extending duration by six days. PDU integration (1.4.3) recovered two days against baseline.</p>

              <h3>Recommended posture</h3>
              <p>Authorize alternate-source RFQ for the turbopump bearing assembly this week with a $480k cap. Re-baseline thermal CDR gate from 14-Aug to 21-Aug. Negotiate a six-week ICD freeze through CDR closure. Combined recovery is approximately 6 working days on the critical path, returning BEI ≥ 0.85 by Cycle 23.</p>

              <h3>Asks of the executive</h3>
              <p>(1) Approval to commit up to $480k for alternate sourcing. (2) Endorsement of CDR gate re-baseline ahead of customer IPR. (3) Concurrence on the GFE ICD freeze posture for negotiation.</p>

              <div style={{display:"flex", gap:10, marginTop:24}}>
                <button className="btn primary">⇣ DOWNLOAD HTML</button>
                <button className="btn">COPY LINK</button>
                <button className="btn">SEND TO PROGRAM CHAIR</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function GeneratingLines() {
  const lines = [
    "▸ Loading IMS diff C-19 vs C-18",
    "▸ Pulling EVM cumulatives · 19 cycles",
    "▸ Sweeping interview outcomes · 10 CAMs",
    "▸ Querying SRA · 10,000 Monte-Carlo sims",
    "▸ Synthesizing top-3 risks",
    "▸ Drafting actions · ranked by recovery",
    "▸ Composing executive briefing…",
  ];
  const [n, setN] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setN(v => Math.min(v + 1, lines.length)), 180);
    return () => clearInterval(t);
  }, []);
  return (
    <div style={{fontFamily:"var(--mono)", fontSize:12, color:"var(--fg-2)", lineHeight: 1.8}}>
      {lines.slice(0, n).map((l, i) => (
        <div key={i}>
          <span style={{color: i === n-1 ? "var(--accent)" : "var(--ok)", marginRight: 6}}>{i === n-1 ? "◆" : "✓"}</span>
          {l}
        </div>
      ))}
    </div>
  );
}

Object.assign(window, { PMPortalTab });
