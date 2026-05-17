// Tab 1: IMS Stats & Info
// Sections: Summary Schedule, BEI/SFA/HRM tiles, SRA, EVM, DCMA-14

function IMSStatsTab() {
  const [version, setVersion] = useState("current"); // current | prior
  const [ghost,   setGhost  ] = useState(true);

  const sched = version === "current" ? window.SCHED_CURRENT : window.SCHED_PRIOR;
  const ghostSched = ghost ? (version === "current" ? window.SCHED_PRIOR : window.SCHED_CURRENT) : null;

  // health derived from RYG inputs: BEI bad, SFA ok → overall warn-ish, take worst of three for indicator
  const bei = window.BEI_HIST[window.BEI_HIST.length - 1];
  const sfa = window.SFA_HIST[window.SFA_HIST.length - 1];
  const hrm = window.HRM_HIST[window.HRM_HIST.length - 1];
  const cb  = window.classifyBEI(bei);
  const cs  = window.classifySFA(sfa);
  const ch  = window.classifyHRM(hrm);
  const worst = [cb, cs, ch].includes("bad") ? "bad" : [cb,cs,ch].includes("warn") ? "warn" : "ok";

  const beiPrev = window.BEI_HIST[window.BEI_HIST.length - 2];
  const sfaPrev = window.SFA_HIST[window.SFA_HIST.length - 2];
  const hrmPrev = window.HRM_HIST[window.HRM_HIST.length - 2];

  return (
    <div className="page stack" style={{gap: 24}}>
      {/* Summary Schedule panel */}
      <Panel
        id="01"
        title="SUMMARY SCHEDULE · TIER-1 IMS · CRITICAL PATH HIGHLIGHTED"
        right={
          <div style={{display:"flex", gap:14, alignItems:"center"}}>
            <Seg
              value={version}
              onChange={setVersion}
              options={[
                { value: "current", label: "Current · " + window.SCHED_CURRENT.label },
                { value: "prior",   label: "Prior · " + window.SCHED_PRIOR.label },
              ]}
            />
            <label style={{display:"inline-flex", alignItems:"center", gap:6, cursor:"pointer", fontSize:10, letterSpacing:"0.08em"}}>
              <input type="checkbox" checked={ghost} onChange={e => setGhost(e.target.checked)} />
              GHOST OVERLAY
            </label>
            <span style={{marginLeft:8}}><RYG status={worst} /></span>
          </div>
        }
        flush
      >
        <SummaryScheduleGantt schedule={sched} ghost={ghostSched} />
      </Panel>

      {/* Three KPI tiles */}
      <div className="row cols-3">
        <Panel id="02·a" title="BEI · BASELINE EXECUTION INDEX" right={<span className="hint">6-MONTH TREND</span>}>
          <KPITile
            label="Current Cycle"
            value={bei.toFixed(2)}
            tone={cb}
            sub={"Threshold green ≥ 0.95 · yellow ≥ 0.85"}
            delta={+(bei - beiPrev).toFixed(2)}
            spark={window.BEI_HIST}
            sparkAxis={["DEC 2025", "MAY 2026"]}
          />
        </Panel>
        <Panel id="02·b" title="SFA · SCHEDULE FORECAST ACCURACY" right={<span className="hint">6-MONTH TREND</span>}>
          <KPITile
            label="Current Cycle"
            value={sfa.toFixed(2)}
            tone={cs}
            sub={"Threshold green ≥ 0.90 · yellow ≥ 0.80"}
            delta={+(sfa - sfaPrev).toFixed(2)}
            spark={window.SFA_HIST}
            sparkAxis={["DEC 2025", "MAY 2026"]}
          />
        </Panel>
        <Panel id="02·c" title="HIGH-RISK MILESTONES" right={<span className="hint">6-MONTH TREND</span>}>
          <KPITile
            label="Open · Severity ≥ HIGH"
            value={hrm.toString()}
            tone={ch}
            sub={"Threshold green ≤ 5 · yellow ≤ 10"}
            delta={hrm - hrmPrev}
            spark={window.HRM_HIST}
            sparkAxis={["DEC 2025", "MAY 2026"]}
          />
        </Panel>
      </div>

      {/* SRA */}
      <SectionHeader ix="03" label="SCHEDULE RISK ASSESSMENT · MONTE-CARLO" right={<span className="hint">10,000 SIMS · 16-MAY-2026</span>} />
      <Panel
        id="03·a"
        title="PROGRAM FINISH PROBABILITY (SRA)"
        right={
          <>
            <span>MEAN · {window.SRA_MEAN}</span>
            <span style={{color:"var(--fg-4)"}}>|</span>
            <span>σ · 5.4 days</span>
            <span style={{color:"var(--fg-4)"}}>|</span>
            <span>DETERMINISTIC · {fmtDate(window.SRA_DETERMINISTIC)} ({(window.SRA.find(d => d.date === window.SRA_DETERMINISTIC).pct*100).toFixed(0)}%)</span>
          </>
        }
        flush
      >
        <div style={{padding: "8px 16px 0"}}>
          <SRAProbChart data={window.SRA} />
        </div>
        <div style={{display:"grid", gridTemplateColumns:"repeat(6, 1fr)", borderTop:"1px solid var(--line)"}}>
          {window.SRA_PCTS.map((p, i) => {
            const date = (() => {
              for (let j=0; j<window.SRA.length; j++) if (window.SRA[j].pct >= p) return window.SRA[j].date;
              return window.SRA[window.SRA.length-1].date;
            })();
            return (
              <div key={p} style={{padding:"12px 14px", borderRight: i<5 ? "1px solid var(--line)" : "none", background:"var(--panel-2)"}}>
                <div className="hint">P{Math.round(p*100)} FINISH</div>
                <div style={{fontFamily:"var(--mono)", fontSize:14, marginTop:4}}>{fmtDate(date)}</div>
              </div>
            );
          })}
        </div>
      </Panel>

      {/* EVM */}
      <SectionHeader ix="04" label="EARNED VALUE MANAGEMENT · CURRENT CYCLE" />
      <Panel id="04·a" title="EVM KPIs · CYCLE C-2026-19" flush>
        <div style={{display:"grid", gridTemplateColumns:"repeat(8, 1fr)", borderBottom:"1px solid var(--line)"}}>
          {window.EVM_KPIS.map((k, i) => (
            <div key={k.key} style={{padding:"16px 14px", borderRight: i<7 ? "1px solid var(--line)" : "none"}}>
              <div className="hint">{k.key}</div>
              <div className={"kpi-val " + (k.tone === "neutral" ? "" : k.tone)} style={{fontSize: 22, marginTop: 4}}>
                {fmt(k.val, k.fmt)}
              </div>
              <div className="kpi-sub" style={{marginTop:6}}>{k.note}</div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel id="04·b" title="PER-CAM BREAKDOWN · WBS LEVEL 2" flush>
        <table className="tbl">
          <thead>
            <tr>
              <th>CAM</th>
              <th>Lead</th>
              <th>WBS</th>
              <th className="num">BAC</th>
              <th className="num">BCWS</th>
              <th className="num">BCWP</th>
              <th className="num">ACWP</th>
              <th className="num">SPI</th>
              <th className="num">CPI</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {window.CAMS.map(c => (
              <tr key={c.cam}>
                <td style={{color:"var(--accent)"}}>{c.cam}</td>
                <td>{c.lead}</td>
                <td className="muted">{c.wbs}</td>
                <td className="num">${c.bac.toLocaleString()}</td>
                <td className="num">${c.bcws.toLocaleString()}</td>
                <td className="num">${c.bcwp.toLocaleString()}</td>
                <td className="num">${c.acwp.toLocaleString()}</td>
                <td className="num" style={{color: c.spi < 0.85 ? "var(--bad)" : c.spi < 0.95 ? "var(--warn)" : "var(--ok)"}}>{c.spi.toFixed(2)}</td>
                <td className="num" style={{color: c.cpi < 0.85 ? "var(--bad)" : c.cpi < 0.95 ? "var(--warn)" : "var(--ok)"}}>{c.cpi.toFixed(2)}</td>
                <td><Pill tone={c.status}>{c.status === "ok" ? "GREEN" : c.status === "warn" ? "YELLOW" : "RED"}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {/* DCMA-14 */}
      <SectionHeader ix="05" label="DCMA 14-POINT ASSESSMENT" right={<span className="hint">10 PASS · 3 WARN · 2 FAIL</span>} />
      <Panel id="05·a" title="DCMA 14 · METRICS" flush>
        <div className="dcma">
          {window.DCMA14.map(m => (
            <div key={m.id} className={"cell " + m.pass}>
              <div className="name">{String(m.id).padStart(2,"0")} · {m.name}</div>
              <div className="val">{m.val}</div>
              <div className="tgt">target {m.target}</div>
              <div className="badge">{m.pass.toUpperCase()}</div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

Object.assign(window, { IMSStatsTab });
