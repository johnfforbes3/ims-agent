// Tab 3: IMS Agent Controls
// Top: KPIs (CAMs Responded, Last Cycle, Schedule Health)
// Cycle In Progress (live), CAM Response Status,
// What Changed (IMS diff viewer), Change History (cumulative diff),
// Baseline Drift Report, Live Interview Listen-In (SSE stream)

function AgentControlsTab() {
  // ---- Cycle in progress (live simulation) ----
  const [cycleRunning, setCycleRunning] = useState(true);
  const [phaseIdx, setPhaseIdx] = useState(2); // INTERVIEW

  // CAM live progress (interview percent done)
  const [camProgress, setCamProgress] = useState(() => {
    const init = {};
    window.CAMS.forEach((c, i) => {
      init[c.cam] =
        c.responded ? (i < 5 ? 100 : 80 + i*2)
                    : 35 + i*3;
    });
    return init;
  });

  useEffect(() => {
    if (!cycleRunning) return;
    const t = setInterval(() => {
      setCamProgress(prev => {
        const next = { ...prev };
        let stillRunning = false;
        Object.keys(next).forEach(k => {
          if (next[k] < 100) {
            next[k] = Math.min(100, next[k] + Math.random() * 2.2);
            if (next[k] < 100) stillRunning = true;
          }
        });
        if (!stillRunning) setCycleRunning(false);
        return next;
      });
    }, 600);
    return () => clearInterval(t);
  }, [cycleRunning]);

  const respondedCount = window.CAMS.filter(c => c.responded).length;
  const totalCams = window.CAMS.length;

  // ---- Interview stream (Phase 15.5 — real SSE from /api/interview-stream) ----
  // Backfills last N turns via /api/interview-recent, then opens an SSE
  // EventSource for live turns.  Demo-loop fallback REMOVED in Phase 15.x
  // fix — it was prepending fake CAM-102/turbopump dialog on top of real
  // turns, which read like a bug.  Now: when no live turns arrive, the
  // panel shows a clear "Waiting for CAM responses" empty state and the
  // status badge stays accurate.  Demo loop is opt-in via ?demo=1 only.
  const [stream, setStream] = useState([]);
  const [typing, setTyping] = useState(false);
  const [streamMode, setStreamMode] = useState("connecting"); // connecting | live | backfill | empty | error | demo
  const [streamMeta, setStreamMeta] = useState({ backfilled: 0, liveTurns: 0, activeSessions: 0 });

  // Phase 15.x — per-CAM filter for the Listen-In transcript.
  // selectedCams is a Set of CAM names; empty Set means "show all".
  // The filter dropdown lets users watch one CAM, several, or all (default).
  // System messages (sys speaker) always show regardless of filter.
  const [selectedCams, setSelectedCams] = useState(() => new Set());
  const [filterOpen, setFilterOpen] = useState(false);
  // Derived: unique CAM names that have appeared in the stream so far,
  // sorted alphabetically.  Used to populate the dropdown checkboxes.
  const knownCams = useMemo(() => {
    const set = new Set();
    stream.forEach(m => { if (m.camName) set.add(m.camName); });
    return [...set].sort();
  }, [stream]);
  // Derived: the stream filtered by the active selection.  Empty selection
  // = pass everything through unchanged.
  const filteredStream = useMemo(() => {
    if (selectedCams.size === 0) return stream;
    return stream.filter(m => !m.camName || selectedCams.has(m.camName));
  }, [stream, selectedCams]);

  function toggleCamFilter(name) {
    setSelectedCams(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  }
  function selectAllCams()   { setSelectedCams(new Set(knownCams)); }
  function clearCamFilter()  { setSelectedCams(new Set()); }
  const streamRef = useRef(null);
  const evtSourceRef = useRef(null);
  const scriptIdxRef = useRef(0);
  const lastLiveSeqRef = useRef(0);

  // Demo mode is opt-in via ?demo=1 query param so the fake INTERVIEW_SCRIPT
  // only plays in obvious demo contexts (never in production with a live cycle).
  const demoModeEnabled = (() => {
    try { return new URLSearchParams(window.location.search).get("demo") === "1"; }
    catch (_) { return false; }
  })();

  function fmtTs(t) {
    const d = typeof t === "number" ? new Date(t * 1000) : new Date();
    const pad = n => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }
  function evtToMsg(ev) {
    const who = ev.speaker === "bot" ? "agent" : ev.speaker === "cam" ? "cam" : "sys";
    const name = ev.cam_name || ev.cam_email || "ATLAS";
    const body = who === "agent"
      ? `ATLAS → ${name}: ${ev.text}`
      : who === "cam"
        ? `${name}: ${ev.text}`
        : ev.text;
    // Phase 15.x — keep the CAM name on the message object so the per-CAM
    // filter dropdown can include/exclude turns cleanly without re-parsing
    // the body text.  "sys" messages keep camName=null and are always shown.
    const camName = (who === "agent" || who === "cam") ? name : null;
    return { who, body, ts: fmtTs(ev.timestamp), event_id: ev.event_id, camName };
  }

  useEffect(() => {
    let cancelled = false;
    let demoTimer = null;

    function startDemoLoop() {
      // Only runs when ?demo=1 — never in production
      if (cancelled || !demoModeEnabled) return;
      setStreamMode("demo");
      demoTimer = setInterval(() => {
        const script = window.INTERVIEW_SCRIPT || [];
        if (scriptIdxRef.current >= script.length) {
          setTimeout(() => { scriptIdxRef.current = 0; if (!cancelled) setStream([]); }, 5000);
          return;
        }
        setTyping(true);
        setTimeout(() => {
          if (cancelled) return;
          const next = script[scriptIdxRef.current];
          scriptIdxRef.current += 1;
          setStream(prev => [...prev, { ...next, ts: fmtTs() }]);
          setTyping(false);
        }, 700 + Math.random() * 500);
      }, 2200);
    }

    async function init() {
      // 1. Backfill — load the last 30 real turns (proactive greetings, prior
      //    CAM answers, system events) for transcript context.
      let backfilledCount = 0;
      try {
        const r = await fetch("/api/interview-recent?n=30");
        if (r.ok) {
          const data = await r.json();
          const events = data.events || [];
          if (!cancelled && events.length > 0) {
            setStream(events.map(evtToMsg));
            backfilledCount = events.length;
            lastLiveSeqRef.current = data.seq || 0;
          }
        }
      } catch (_) {}

      // 2. Probe active sessions so the empty-state can say something specific
      //    ("5 CAMs are interviewing — waiting for their replies")
      let activeSessions = 0;
      try {
        const r = await fetch("/api/interview-sessions");
        if (r.ok) {
          const sessions = await r.json();
          if (Array.isArray(sessions)) activeSessions = sessions.length;
        }
      } catch (_) {}

      if (!cancelled) {
        setStreamMeta(m => ({ ...m, backfilled: backfilledCount, activeSessions }));
        setStreamMode(backfilledCount > 0 ? "backfill" : "empty");
      }

      // 3. Open SSE for live turns.  Demo loop only kicks in when ?demo=1.
      try {
        const url = `/api/interview-stream?since=${lastLiveSeqRef.current}`;
        const es = new EventSource(url);
        evtSourceRef.current = es;
        let liveCount = 0;
        es.onopen = () => {
          if (!cancelled && backfilledCount === 0 && demoModeEnabled) {
            // Empty production → only start demo if ?demo=1
            setTimeout(() => {
              if (!cancelled && liveCount === 0 && backfilledCount === 0) startDemoLoop();
            }, 4000);
          }
        };
        es.onmessage = (e) => {
          liveCount++;
          try {
            const ev = JSON.parse(e.data);
            lastLiveSeqRef.current = Math.max(lastLiveSeqRef.current, (ev.seq || 0) + 1);
            setStream(prev => [...prev, evtToMsg(ev)]);
            if (!cancelled) {
              setStreamMode("live");
              setStreamMeta(m => ({ ...m, liveTurns: liveCount }));
            }
          } catch (_) {}
        };
        es.onerror = () => {
          if (!cancelled) setStreamMode(m => m === "live" ? "live" : "error");
        };
      } catch (_) {
        if (!cancelled) setStreamMode("error");
      }
    }

    init();
    return () => {
      cancelled = true;
      if (evtSourceRef.current) evtSourceRef.current.close();
      if (demoTimer) clearInterval(demoTimer);
    };
  }, [demoModeEnabled]);

  useEffect(() => {
    if (streamRef.current) {
      streamRef.current.scrollTop = streamRef.current.scrollHeight;
    }
  }, [stream, typing]);

  // ---- Diff viewer cycle selector ----
  const [diffCycle, setDiffCycle] = useState("C-2026-19 vs C-2026-18");
  const [cumRange, setCumRange] = useState("C-2026-15 → C-2026-19");

  // ---- Agent control actions ----
  const [agentMode, setAgentMode] = useState("auto"); // auto | manual | paused
  const [confirmOpen, setConfirmOpen] = useState(null);

  // Phase 15.x — listen for hero-button events so the DRY-RUN and
  // KILL SWITCH buttons in the page hero open the same modal as the
  // in-panel agent control bar.
  useEffect(() => {
    const onOpen = (e) => setConfirmOpen(e.detail?.kind || null);
    window.addEventListener("atlas:open-confirm", onOpen);
    return () => window.removeEventListener("atlas:open-confirm", onOpen);
  }, []);

  return (
    <div className="page stack" style={{gap: 24}}>

      {/* Agent control bar */}
      <Panel
        id="00"
        title="ATLAS AGENT · CONTROL"
        right={
          <span style={{display:"flex", alignItems:"center", gap: 8}}>
            <span className="dot live" /> CONNECTED · ATLAS-IMS v4.6.2
          </span>
        }
      >
        <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", gap: 24}}>
          <div style={{display:"flex", gap:24, alignItems:"center"}}>
            <div>
              <div className="hint">MODE</div>
              <div style={{marginTop: 6}}>
                <Seg
                  value={agentMode}
                  onChange={setAgentMode}
                  options={[
                    { value: "auto",   label: "▶ Autonomous" },
                    { value: "manual", label: "◐ Supervised" },
                    { value: "paused", label: "■ Paused"     },
                  ]}
                />
              </div>
            </div>
            <div>
              <div className="hint">NEXT SCHEDULED CYCLE</div>
              <div style={{fontFamily:"var(--mono)", fontSize:14, marginTop:8}}>2026-05-23 06:00Z · in 7d 0h</div>
            </div>
            <div>
              <div className="hint">SAFE-MODE</div>
              <div style={{marginTop:8}}><Pill tone="ok">ARMED · BASELINE LOCK</Pill></div>
            </div>
          </div>
          <div style={{display:"flex", gap: 8}}>
            <button className="btn" onClick={() => setConfirmOpen("dry")}>⏵ DRY-RUN</button>
            <button className="btn" onClick={() => setConfirmOpen("force")}>⟳ FORCE CYCLE</button>
            <button className="btn danger" onClick={() => setConfirmOpen("kill")}>■ KILL SWITCH</button>
          </div>
        </div>
      </Panel>

      {/* Three top KPIs */}
      <div className="row cols-3">
        <Panel id="01·a" title="CAMs RESPONDED · CURRENT CYCLE">
          <div className="kpi">
            <div className="kpi-label">RESPONDED / TOTAL</div>
            <div className="kpi-val">{respondedCount}<span className="unit">/ {totalCams}</span></div>
            <div className="bar ok" style={{marginTop:10}}><i style={{width: (respondedCount/totalCams*100)+"%"}}></i></div>
            <div className="kpi-sub" style={{marginTop:8}}>
              {totalCams - respondedCount} pending · {window.CAMS.filter(c => c.outcome === "ESCALATE").length} escalation{window.CAMS.filter(c => c.outcome === "ESCALATE").length === 1 ? "" : "s"}
            </div>
          </div>
        </Panel>
        <Panel id="01·b" title="LAST CYCLE">
          <div className="kpi">
            <div className="kpi-label">CYCLE ID · TIMESTAMP</div>
            <div className="kpi-val" style={{fontSize: 22, lineHeight: 1.3, fontFamily:"var(--mono)"}}>
              C-2026-18
            </div>
            <div style={{fontFamily:"var(--mono)", fontSize: 12, color:"var(--fg-3)", marginTop: 6}}>
              2026-05-09 06:00Z
            </div>
            <div className="kpi-sub" style={{marginTop: 12}}>10/10 CAMs · 2 escalations · 4 baseline updates</div>
          </div>
        </Panel>
        <Panel id="01·c" title="SCHEDULE HEALTH">
          <div style={{display:"flex", flexDirection:"column", gap:14}}>
            <div className="kpi-label">RYG · CURRENT CYCLE</div>
            <RYG status="warn" size="big" />
            <div className="kpi-sub">Worst-of-three: BEI <span style={{color:"var(--bad)"}}>RED</span> · SFA <span style={{color:"var(--ok)"}}>GREEN</span> · HRM <span style={{color:"var(--bad)"}}>RED</span></div>
          </div>
        </Panel>
      </div>

      {/* CYCLE IN PROGRESS (conditional, but always shown given live state) */}
      <Panel
        id="02"
        title={<span><span className="dot live" style={{marginRight:8, verticalAlign:1}} />CYCLE IN PROGRESS · C-2026-19</span>}
        right={
          <>
            <span>PHASE · <strong style={{color:"var(--accent)"}}>{window.CYCLE_PHASES[phaseIdx]}</strong></span>
            <span style={{color:"var(--fg-4)"}}>|</span>
            <span>{respondedCount}/{totalCams} CAMs</span>
            <span style={{color:"var(--fg-4)"}}>|</span>
            <span style={{color:"var(--accent)"}}>ELAPSED · 00:12:48</span>
          </>
        }
      >
        <div style={{display:"grid", gridTemplateColumns: "1fr 1fr", gap: 32}}>
          {/* Phase stepper */}
          <div>
            <div className="hint" style={{marginBottom:8}}>PIPELINE</div>
            <div style={{display:"flex", gap:0, marginBottom: 20}}>
              {window.CYCLE_PHASES.map((p, i) => (
                <div key={p} style={{
                  flex: 1, padding: "8px 10px",
                  borderTop: "2px solid " + (i < phaseIdx ? "var(--ok)" : i === phaseIdx ? "var(--accent)" : "var(--line-2)"),
                  borderRight: i < window.CYCLE_PHASES.length - 1 ? "1px solid var(--line)" : "none",
                  background: i === phaseIdx ? "var(--accent-soft)" : "transparent",
                  fontFamily:"var(--mono)", fontSize: 10, letterSpacing:"0.08em",
                  color: i < phaseIdx ? "var(--ok)" : i === phaseIdx ? "var(--accent)" : "var(--fg-4)",
                  display:"flex", alignItems:"center", gap: 6,
                }}>
                  <span>{i < phaseIdx ? "✓" : i === phaseIdx ? "●" : "○"}</span>
                  <span>{p}</span>
                </div>
              ))}
            </div>
            <div className="hint" style={{marginBottom:8}}>CONTROLS</div>
            <div style={{display:"flex", gap: 8}}>
              <button className="btn" onClick={() => setPhaseIdx(i => Math.max(0, i-1))}>◀ STEP</button>
              <button className="btn" onClick={() => setPhaseIdx(i => Math.min(window.CYCLE_PHASES.length-1, i+1))}>STEP ▶</button>
              <button className="btn">⏸ HOLD</button>
              <button className="btn primary" onClick={() => setCycleRunning(true)}>RESUME</button>
            </div>
          </div>

          <div>
            <div className="hint" style={{marginBottom: 8}}>PER-CAM LIVE PROGRESS</div>
            <div className="chipgrid">
              {window.CAMS.map(c => {
                const pct = Math.round(camProgress[c.cam] || 0);
                return (
                  <div key={c.cam} className="chip">
                    <span className="nm" style={{color: pct === 100 ? "var(--ok)" : pct >= 80 ? "var(--accent)" : "var(--fg-2)"}}>{c.cam}</span>
                    <span className="bar" style={{background: "var(--line)"}}>
                      <i style={{width: pct + "%", background: pct === 100 ? "var(--ok)" : "var(--accent)"}} />
                    </span>
                    <span className="pct">{pct}%</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </Panel>

      {/* CAM Response Status */}
      <Panel id="03" title="CAM RESPONSE STATUS · CURRENT CYCLE" flush>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{width:60}}>Status</th>
              <th>CAM</th>
              <th>Lead</th>
              <th>WBS</th>
              <th className="num">Attempts</th>
              <th>Outcome</th>
              <th style={{width: 220}}>Progress</th>
            </tr>
          </thead>
          <tbody>
            {window.CAMS.map(c => {
              const pct = Math.round(camProgress[c.cam] || 0);
              const dotClass = c.outcome === "ESCALATE" ? "bad" : c.outcome === "PENDING" ? "warn" : "ok";
              return (
                <tr key={c.cam}>
                  <td><span className={"statusdot " + dotClass} /></td>
                  <td style={{color:"var(--accent)"}}>{c.cam}</td>
                  <td>{c.lead}</td>
                  <td className="muted">{c.wbs}</td>
                  <td className="num">{c.attempts}</td>
                  <td>
                    <Pill tone={c.outcome === "ESCALATE" ? "bad" : c.outcome === "PENDING" ? "warn" : "ok"}>
                      {c.outcome}
                    </Pill>
                  </td>
                  <td>
                    <div style={{display:"flex", gap:8, alignItems:"center"}}>
                      <span className="bar" style={{flex:1}}><i style={{width: pct+"%", background: pct === 100 ? "var(--ok)" : "var(--accent)"}} /></span>
                      <span style={{fontVariantNumeric:"tabular-nums", width:36, textAlign:"right"}}>{pct}%</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>

      {/* IMS Diff Viewer */}
      <SectionHeader ix="04" label="DIFF & DRIFT" />
      <div className="row cols-2">
        <Panel
          id="04·a"
          title="WHAT CHANGED · IMS DIFF VIEWER"
          right={
            <select className="inp" value={diffCycle} onChange={e => setDiffCycle(e.target.value)}>
              <option>C-2026-19 vs C-2026-18</option>
              <option>C-2026-18 vs C-2026-17</option>
              <option>C-2026-17 vs C-2026-16</option>
            </select>
          }
          flush
        >
          <table className="tbl">
            <thead>
              <tr>
                <th>Task</th>
                <th>CAM</th>
                <th>Field</th>
                <th>Old</th>
                <th>New</th>
                <th className="num">Δ</th>
              </tr>
            </thead>
            <tbody>
              {window.DIFF_ROWS.map((r, i) => (
                <tr key={i}>
                  <td>{r.task}</td>
                  <td style={{color:"var(--info)"}}>{r.cam}</td>
                  <td className="muted">{r.field}</td>
                  <td className="muted">{r.oldv}</td>
                  <td>{r.newv}</td>
                  <td className="num" style={{color: /[+]\d+d/.test(r.delta) ? "var(--bad)" : /-\d+d/.test(r.delta) ? "var(--ok)" : "var(--fg-2)"}}>{r.delta}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel
          id="04·b"
          title="CHANGE HISTORY · CUMULATIVE DIFF"
          right={
            <select className="inp" value={cumRange} onChange={e => setCumRange(e.target.value)}>
              <option>C-2026-15 → C-2026-19</option>
              <option>C-2026-10 → C-2026-19</option>
              <option>C-2026-01 → C-2026-19</option>
            </select>
          }
          flush
        >
          <table className="tbl">
            <thead>
              <tr>
                <th>Task</th>
                <th>CAM</th>
                <th className="num">Finish Drift</th>
                <th className="num">Hops</th>
                <th>Contributing Cycles</th>
              </tr>
            </thead>
            <tbody>
              {window.CUM_DIFF.map((r, i) => (
                <tr key={i}>
                  <td>{r.task}</td>
                  <td style={{color:"var(--info)"}}>{r.cam}</td>
                  <td className="num" style={{color: r.finishDrift > 5 ? "var(--bad)" : r.finishDrift > 0 ? "var(--warn)" : "var(--ok)"}}>
                    {r.finishDrift > 0 ? "+" : ""}{r.finishDrift}d
                  </td>
                  <td className="num">{r.hops}</td>
                  <td className="muted">{r.cycles}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      {/* Baseline Drift */}
      <Panel
        id="05"
        title="BASELINE DRIFT REPORT"
        right={<span className="hint">vs. PMB · LOCKED 2026-01-05</span>}
        flush
      >
        <table className="tbl">
          <thead>
            <tr>
              <th>Task</th>
              <th>CAM</th>
              <th>Baseline Finish</th>
              <th>Current Finish</th>
              <th className="num">Slip (d)</th>
              <th className="num">Δ % Complete</th>
              <th style={{width: 220}}>Visual</th>
            </tr>
          </thead>
          <tbody>
            {window.DRIFT_ROWS.map((r, i) => {
              const maxSlip = 14;
              const widthPct = Math.min(100, Math.abs(r.slip)/maxSlip*100);
              return (
                <tr key={i}>
                  <td>{r.task}</td>
                  <td style={{color:"var(--info)"}}>{r.cam}</td>
                  <td className="muted">{r.baseFin}</td>
                  <td>{r.curFin}</td>
                  <td className="num" style={{color: r.slip > 5 ? "var(--bad)" : r.slip > 0 ? "var(--warn)" : "var(--ok)"}}>
                    {r.slip > 0 ? "+" : ""}{r.slip}
                  </td>
                  <td className="num" style={{color: r.pctDelta < 0 ? "var(--bad)" : r.pctDelta > 0 ? "var(--ok)" : "var(--fg-3)"}}>
                    {r.pctDelta > 0 ? "+" : ""}{r.pctDelta} pp
                  </td>
                  <td>
                    <div style={{position:"relative", height:8, background:"var(--line)", width:"100%"}}>
                      <span style={{position:"absolute", left:"50%", top:-2, bottom:-2, width:1, background:"var(--fg-3)"}}></span>
                      {r.slip !== 0 && (
                        <span style={{
                          position:"absolute", top:0, bottom:0,
                          left: r.slip > 0 ? "50%" : (50 - widthPct/2) + "%",
                          width: (widthPct/2) + "%",
                          background: r.slip > 0 ? "var(--bad)" : "var(--ok)",
                          opacity: 0.85,
                        }} />
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>

      {/* Live Interview Listen-In — Phase 15.5 (real SSE) + Phase 15.x (status badge) */}
      <Panel
        id="06"
        title={<span><span className="dot live" style={{marginRight: 8, verticalAlign:1}} />LIVE INTERVIEW LISTEN-IN · CAM ⇄ ATLAS</span>}
        right={
          <span style={{display:"flex", gap:8, alignItems:"center"}}>
            <span className="hint">SSE</span>
            {streamMode === "live" && (
              <span style={{color:"var(--ok)"}}>● LIVE · {streamMeta.liveTurns} new turn{streamMeta.liveTurns===1?"":"s"}</span>
            )}
            {streamMode === "backfill" && (
              <span style={{color:"var(--accent)"}}>● BACKFILL · {streamMeta.backfilled} turn{streamMeta.backfilled===1?"":"s"} loaded</span>
            )}
            {streamMode === "empty" && streamMeta.activeSessions > 0 && (
              <span style={{color:"var(--warn)"}}>● WAITING · {streamMeta.activeSessions} CAM{streamMeta.activeSessions===1?"":"s"} interviewing</span>
            )}
            {streamMode === "empty" && streamMeta.activeSessions === 0 && (
              <span className="muted">○ IDLE · no active interviews</span>
            )}
            {streamMode === "connecting" && <span className="muted">○ CONNECTING…</span>}
            {streamMode === "error" && <span style={{color:"var(--bad)"}}>✗ STREAM ERROR</span>}
            {streamMode === "demo" && <span style={{color:"var(--warn)"}}>⚠ DEMO MODE · scripted dialogue</span>}
            <span className="muted">·</span>
            {/* Phase 15.x — per-CAM filter dropdown */}
            <CamFilter
              knownCams={knownCams}
              selectedCams={selectedCams}
              isOpen={filterOpen}
              onToggleOpen={() => setFilterOpen(o => !o)}
              onToggleCam={toggleCamFilter}
              onSelectAll={selectAllCams}
              onClear={clearCamFilter}
            />
            <span className="muted">
              · {selectedCams.size === 0 ? `ALL ${stream.length}` : `${filteredStream.length} / ${stream.length}`}
            </span>
          </span>
        }
        flush
      >
        <div className="stream" ref={streamRef}>
          {filteredStream.map((m, i) => (
            <div key={i} className="msg">
              <span className="ts">{m.ts}</span>
              <span className={"who " + m.who}>{m.who.toUpperCase()}</span>
              <span className="body">{m.body}</span>
            </div>
          ))}
          {typing && (
            <div className="msg">
              <span className="ts">{(() => { const ts = new Date(); return [ts.getHours(), ts.getMinutes(), ts.getSeconds()].map(n => String(n).padStart(2,"0")).join(":"); })()}</span>
              <span className="who agent">ATLAS</span>
              <span className="body typing">▌ typing<TypingDots /></span>
            </div>
          )}
          {filteredStream.length === 0 && stream.length > 0 && (
            <div className="muted" style={{padding:"24px 12px", textAlign:"center"}}>
              ▸ No turns match the active CAM filter.
              <button className="btn" style={{marginLeft:10, padding:"2px 8px"}} onClick={clearCamFilter}>Clear filter</button>
            </div>
          )}
          {stream.length === 0 && !typing && (
            <div className="muted" style={{padding:"32px 12px", textAlign:"center", lineHeight:1.7}}>
              {streamMode === "connecting" && "▸ Connecting to interview stream…"}
              {streamMode === "empty" && streamMeta.activeSessions > 0 && (
                <>
                  <div>▸ {streamMeta.activeSessions} CAM interview{streamMeta.activeSessions===1?"":"s"} in flight.</div>
                  <div style={{marginTop:6, fontSize:11}}>Live turns will appear here as ATLAS and CAMs exchange messages in Teams chat.</div>
                </>
              )}
              {streamMode === "empty" && streamMeta.activeSessions === 0 && (
                <>
                  <div>▸ No interview cycle currently active.</div>
                  <div style={{marginTop:6, fontSize:11}}>Trigger a new cycle from the FORCE CYCLE button above to start interviews.</div>
                </>
              )}
              {streamMode === "error" && "✗ Stream error — backend unreachable. Check /api/interview-stream."}
            </div>
          )}
        </div>
        <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", padding:"10px 14px", borderTop:"1px solid var(--line)", background:"var(--panel-2)"}}>
          <span className="hint">
            CYCLE · {window.__IMS_CYCLE_ID || (window.__IMS_LIVE?.state?.cycle_id) || "—"} ·
            {streamMeta.activeSessions > 0 ? ` ${streamMeta.activeSessions} session${streamMeta.activeSessions===1?"":"s"}` : " no active sessions"}
          </span>
          <div style={{display:"flex", gap: 8}}>
            <button className="btn">PAUSE STREAM</button>
            <button className="btn">EXPORT TRANSCRIPT</button>
            <button className="btn danger">END SESSION</button>
          </div>
        </div>
      </Panel>

      {confirmOpen && (
        <ConfirmModal kind={confirmOpen} onClose={() => setConfirmOpen(null)} />
      )}
    </div>
  );
}

function TypingDots() {
  const [n, setN] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setN(v => (v+1) % 4), 250);
    return () => clearInterval(t);
  }, []);
  return <span>{".".repeat(n)}</span>;
}

/**
 * Phase 15.x — CAM filter dropdown for the Listen-In transcript.
 *
 * Displays as a small button that, when clicked, opens a popup with one
 * checkbox per CAM seen in the stream so far.  Empty selection = "ALL"
 * (no filter applied — pass everything through).
 *
 * @param {object} props
 * @param {string[]} props.knownCams    All CAM names that have appeared
 * @param {Set<string>} props.selectedCams  Currently-checked CAMs
 * @param {boolean} props.isOpen        Dropdown popup visibility
 * @param {function} props.onToggleOpen Toggle the popup
 * @param {function} props.onToggleCam  Toggle a single CAM (name => void)
 * @param {function} props.onSelectAll  Check every CAM
 * @param {function} props.onClear      Uncheck everything (= show all)
 */
function CamFilter({ knownCams, selectedCams, isOpen, onToggleOpen, onToggleCam, onSelectAll, onClear }) {
  const count = selectedCams.size;
  const total = knownCams.length;
  // Button label depends on how many are selected
  let label;
  if (count === 0)              label = `ALL CAMs (${total})`;
  else if (count === 1)         label = [...selectedCams][0];
  else if (count === total)     label = `ALL CAMs (${total})`;
  else                          label = `${count} of ${total} CAMs`;

  const popupStyle = {
    position: "absolute", top: "100%", right: 0, marginTop: 6,
    background: "var(--panel)", border: "1px solid var(--line-2)", borderRadius: 4,
    padding: "8px 0", minWidth: 200, zIndex: 50,
    boxShadow: "0 4px 14px rgba(0,0,0,0.4)",
    fontFamily: "var(--sans)", fontSize: 12, color: "var(--fg)",
  };
  const rowStyle = { display: "flex", alignItems: "center", gap: 8, padding: "5px 12px", cursor: "pointer", userSelect: "none" };

  return (
    <span style={{position:"relative", display:"inline-block"}}>
      <button
        onClick={onToggleOpen}
        title="Filter Listen-In by CAM"
        style={{
          background: count > 0 && count < total ? "var(--accent-soft)" : "var(--panel-2)",
          border: "1px solid var(--line-2)", borderRadius: 3,
          padding: "3px 10px", color: count > 0 && count < total ? "var(--accent)" : "var(--fg-2)",
          fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em",
          cursor: "pointer", textTransform: "uppercase",
        }}
        disabled={total === 0}
      >
        🔎 {label}
      </button>
      {isOpen && (
        <>
          {/* Backdrop to dismiss on outside click */}
          <span style={{position:"fixed", inset:0, zIndex:40}} onClick={onToggleOpen} />
          <div style={popupStyle}>
            <div style={{display:"flex", justifyContent:"space-between", padding:"4px 12px 8px", borderBottom:"1px solid var(--line)"}}>
              <button onClick={onSelectAll}
                      style={{background:"none", border:"none", color:"var(--accent)", fontSize:10, cursor:"pointer", padding:0, textTransform:"uppercase", letterSpacing:"0.06em"}}>
                Select all
              </button>
              <button onClick={onClear}
                      style={{background:"none", border:"none", color:"var(--fg-3)", fontSize:10, cursor:"pointer", padding:0, textTransform:"uppercase", letterSpacing:"0.06em"}}>
                Show all (clear)
              </button>
            </div>
            {total === 0 && (
              <div style={{padding:"8px 12px", color:"var(--fg-3)", fontStyle:"italic"}}>
                No CAMs in stream yet
              </div>
            )}
            {knownCams.map(name => (
              <label key={name} style={rowStyle} onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={selectedCams.has(name)}
                  onChange={() => onToggleCam(name)}
                  style={{margin:0, cursor:"pointer"}}
                />
                <span>{name}</span>
              </label>
            ))}
          </div>
        </>
      )}
    </span>
  );
}

function ConfirmModal({ kind, onClose }) {
  // Phase 15.6 — wire CTAs to real /api/* endpoints when available.
  // DRY-RUN and KILL SWITCH are display-only stubs (no backend endpoint
  // exists yet — would land in a future phase if/when the agent core
  // exposes those operations).  FORCE CYCLE calls /api/trigger?force=true.
  const [status, setStatus] = useState(null); // null | "pending" | "done" | "error"
  const [error, setError]   = useState(null);

  const copy = {
    dry:   { title: "DRY-RUN NEXT CYCLE", body: "Execute a full cycle in shadow mode. No CAMs will be contacted; no baselines will be touched. Output diff and proposed changes for inspection. (Stub — endpoint not implemented yet.)", cta: "Begin dry-run", danger: false, wired: false },
    force: { title: "FORCE CYCLE NOW",    body: "Begin a new cycle immediately, ahead of the next scheduled run. CAMs will receive interview prompts within 60 seconds. This calls the real /api/trigger endpoint.", cta: "Start cycle now", danger: false, wired: true },
    kill:  { title: "ENGAGE KILL SWITCH", body: "Immediately halt all agent activity. In-flight interviews will be closed with state preserved; no writes to baseline will occur until ATLAS is manually re-armed. (Stub — endpoint not implemented yet.)", cta: "Engage kill switch", danger: true, wired: false },
  }[kind];

  async function confirm() {
    if (!copy.wired) { onClose(); return; }
    setStatus("pending");
    setError(null);
    try {
      const r = await fetch("/api/trigger?force=true", { method: "POST" });
      const data = await r.json().catch(() => ({}));
      if (r.ok && (data.status === "triggered" || data.status === "queued")) {
        setStatus("done");
        setTimeout(() => onClose(), 1400);
      } else {
        setStatus("error");
        setError(data.detail || data.error || `HTTP ${r.status}`);
      }
    } catch (e) {
      setStatus("error");
      setError(String(e));
    }
  }

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{maxWidth: 540}}>
        <div className="modal-h">
          <span>{copy.title}</span>
          <button className="x" onClick={onClose}>×</button>
        </div>
        <div className="modal-b">
          <div className="prose"><p>{copy.body}</p></div>
          {status === "pending" && (
            <div style={{marginTop:12, color:"var(--accent)", fontFamily:"var(--mono)", fontSize:12}}>
              ▸ Calling /api/trigger?force=true …
            </div>
          )}
          {status === "done" && (
            <div style={{marginTop:12, color:"var(--ok)", fontFamily:"var(--mono)", fontSize:12}}>
              ✓ Cycle triggered. Closing…
            </div>
          )}
          {status === "error" && (
            <div style={{marginTop:12, color:"var(--bad)", fontFamily:"var(--mono)", fontSize:12}}>
              ✗ Trigger failed: {error}
            </div>
          )}
          <div style={{display:"flex", gap:10, justifyContent:"flex-end", marginTop: 20}}>
            <button className="btn" onClick={onClose} disabled={status === "pending"}>CANCEL</button>
            <button
              className={"btn " + (copy.danger ? "danger" : "primary")}
              onClick={confirm}
              disabled={status === "pending" || status === "done"}
            >
              {(copy.cta + (copy.wired ? "" : " (stub)")).toUpperCase()}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { AgentControlsTab });
