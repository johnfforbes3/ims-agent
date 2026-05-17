// Charts for ATLAS: Summary Schedule Gantt, SRA Probability histogram, Health line.
// Pure SVG; all interactive.

function dateToFrac(iso, start, end) {
  const t = new Date(iso).getTime();
  const a = start.getTime();
  const b = end.getTime();
  return (t - a) / (b - a);
}

function fmtDate(iso) {
  const d = new Date(iso);
  const m = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getMonth()];
  return d.getDate().toString().padStart(2,"0") + " " + m + " " + d.getFullYear().toString().slice(2);
}

function SummaryScheduleGantt({ schedule, ghost }) {
  const start = window.PROGRAM_START;
  const end   = window.PROGRAM_END;
  const today = window.TODAY;
  const rows  = schedule.rows;
  const milestones = schedule.milestones;

  const rowH = 32;
  const headH = 36;
  const padL = 220;
  const padR = 24;
  const padT = 12;
  const w    = 1340;
  const innerW = w - padL - padR;
  const h    = padT + headH + rows.length * rowH + 16;

  const xOf = iso => padL + dateToFrac(iso, start, end) * innerW;

  // month ticks
  const months = [];
  let cur = new Date(start.getFullYear(), start.getMonth(), 1);
  while (cur <= end) {
    months.push(new Date(cur));
    cur = new Date(cur.getFullYear(), cur.getMonth()+1, 1);
  }

  const [hover, setHover] = useState(null);

  return (
    <div style={{position:"relative"}}>
      <svg viewBox={`0 0 ${w} ${h}`} style={{width:"100%", height:"auto", display:"block"}}>
        {/* header: months */}
        <g>
          {months.map((d, i) => {
            const x = xOf(d.toISOString().slice(0,10));
            const lbl = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getMonth()];
            return (
              <g key={i}>
                <line x1={x} x2={x} y1={padT+headH-6} y2={h-8} stroke="var(--line)" strokeDasharray="2 4" />
                <text x={x+4} y={padT+20} fontSize="10" fill="var(--fg-3)" letterSpacing="0.06em">
                  {lbl.toUpperCase()} {d.getFullYear().toString().slice(2)}
                </text>
              </g>
            );
          })}
          {/* today line */}
          <g>
            <line x1={xOf(today.toISOString().slice(0,10))} x2={xOf(today.toISOString().slice(0,10))}
                  y1={padT+headH-12} y2={h-8} stroke="var(--accent)" strokeWidth="1" strokeDasharray="3 3" />
            <rect x={xOf(today.toISOString().slice(0,10)) - 22} y={padT} width="44" height="14"
                  fill="var(--accent)" />
            <text x={xOf(today.toISOString().slice(0,10))} y={padT+10} fontSize="9"
                  fill="var(--bg)" textAnchor="middle" fontWeight="600" letterSpacing="0.1em">TODAY</text>
          </g>
        </g>

        {/* divider */}
        <line x1={0} x2={w} y1={padT+headH} y2={padT+headH} stroke="var(--line-2)" />
        <line x1={padL} x2={padL} y1={0} y2={h} stroke="var(--line-2)" />

        {/* rows */}
        {rows.map((r, i) => {
          const y = padT + headH + i * rowH;
          const x1 = xOf(r.start);
          const x2 = xOf(r.end);
          const bw = Math.max(2, x2 - x1);
          const compW = bw * r.complete;
          const color = r.critical ? "var(--bad)" : "var(--info)";
          const compColor = r.critical ? "#ff7878" : "#9ec5ff";

          // ghost (prior version)
          let gx1=null, gx2=null;
          if (ghost) {
            const gr = ghost.rows.find(x => x.id === r.id);
            if (gr) {
              gx1 = xOf(gr.start); gx2 = xOf(gr.end);
            }
          }

          return (
            <g key={r.id}>
              {/* row label */}
              <text x={16} y={y+rowH/2+4} fontSize="11" fill="var(--fg-2)" fontFamily="var(--mono)">
                {r.id} · {r.name}
              </text>
              {/* row band */}
              <rect x={padL} y={y+4} width={innerW} height={rowH-8} fill={i%2 ? "var(--row-band)" : "transparent"} />
              {/* ghost prior */}
              {gx1 != null && (
                <rect x={gx1} y={y+rowH/2-3} width={Math.max(2, gx2-gx1)} height={6}
                      fill="none" stroke="var(--fg-4)" strokeDasharray="3 2" />
              )}
              {/* current bar */}
              <g onMouseEnter={() => setHover({ kind: "task", r })}
                 onMouseLeave={() => setHover(null)}>
                <rect x={x1} y={y+rowH/2-7} width={bw} height={14}
                      fill={color} opacity="0.22" stroke={color} strokeWidth="1" />
                <rect x={x1} y={y+rowH/2-7} width={compW} height={14} fill={color} />
              </g>
            </g>
          );
        })}

        {/* milestones */}
        {milestones.map((m, i) => {
          const mx = xOf(m.date);
          // place diamonds in their own lane just below the months row, vertically aligned with bars
          // we'll mark on the topmost relevant row visually but easier: stack at top of chart area
          const y = padT + headH - 4;
          const color = m.critical ? "var(--bad)" : "var(--accent)";
          const fill = m.met ? color : "var(--bg)";
          return (
            <g key={m.id} transform={`translate(${mx},${y})`}
               onMouseEnter={() => setHover({ kind: "ms", m })}
               onMouseLeave={() => setHover(null)}
               style={{cursor:"pointer"}}>
              <polygon points="0,-9 9,0 0,9 -9,0" fill={fill} stroke={color} strokeWidth="1.5" />
              <text x={0} y={-12} textAnchor="middle" fontSize="9" fill={color}
                    fontFamily="var(--mono)" fontWeight="600" letterSpacing="0.08em">{m.name}</text>
            </g>
          );
        })}

        {/* connector lines from each milestone down to its row */}
        {milestones.map((m, i) => {
          const idx = rows.findIndex(r => r.end === m.date);
          if (idx < 0) return null;
          const mx = xOf(m.date);
          const y1 = padT + headH;
          const y2 = padT + headH + idx*rowH + rowH/2 + 7;
          const color = m.critical ? "var(--bad)" : "var(--accent)";
          return <line key={"c"+m.id} x1={mx} x2={mx} y1={y1} y2={y2} stroke={color} strokeOpacity="0.4" strokeDasharray="2 3" />;
        })}
      </svg>

      {hover && hover.kind === "task" && (
        <div className="tt" style={{left:"50%", top:64}}>
          <div><span className="tt-key">{hover.r.id}</span> · {hover.r.name}</div>
          <div><span className="tt-key">start</span> {fmtDate(hover.r.start)} · <span className="tt-key">end</span> {fmtDate(hover.r.end)} · <span className="tt-key">cp</span> {hover.r.critical ? "Y" : "N"} · <span className="tt-key">complete</span> {(hover.r.complete*100).toFixed(0)}%</div>
        </div>
      )}
      {hover && hover.kind === "ms" && (
        <div className="tt" style={{left:"50%", top:64}}>
          <div><span className="tt-key">{hover.m.name}</span> · {fmtDate(hover.m.date)} · {hover.m.met ? "MET" : "PENDING"}{hover.m.critical ? " · CRITICAL" : ""}</div>
        </div>
      )}

      {/* legend */}
      <div style={{display:"flex", gap:18, padding:"10px 16px", borderTop:"1px solid var(--line)", background:"var(--panel-2)", fontFamily:"var(--mono)", fontSize:11, color:"var(--fg-3)", letterSpacing:"0.06em"}}>
        <span><span style={{display:"inline-block", width:18, height:6, background:"var(--bad)", marginRight:6}}></span>CRITICAL PATH</span>
        <span><span style={{display:"inline-block", width:18, height:6, background:"var(--info)", marginRight:6}}></span>NON-CRITICAL</span>
        <span><svg width="14" height="14" style={{verticalAlign:"-3px", marginRight:4}}><polygon points="7,2 12,7 7,12 2,7" fill="var(--accent)" /></svg>MILESTONE</span>
        {ghost && <span><span style={{display:"inline-block", width:18, height:0, borderTop:"2px dashed var(--fg-4)", marginRight:6, verticalAlign:"middle"}}></span>PRIOR VERSION (GHOST)</span>}
        <span style={{marginLeft:"auto"}}>UPDATED {schedule.generated}</span>
      </div>
    </div>
  );
}

// SRA: histogram of finish dates + cumulative line up to 100%
function SRAProbChart({ data }) {
  const w = 1100, h = 360;
  const pad = { l: 56, r: 110, t: 30, b: 44 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const N = data.length;
  const totalHits = data.reduce((s,d)=>s+d.count,0);
  const maxPctHits = Math.max(...data.map(d => d.count/totalHits));
  const barW = innerW / N;

  const xOf = i => pad.l + i * barW;
  const yHit = pct => pad.t + (1 - pct / maxPctHits) * innerH;
  const yCum = pct => pad.t + (1 - pct) * innerH;

  // line points (use right edge of each bar)
  const linePts = data.map((d, i) => [xOf(i) + barW, yCum(d.pct)]);
  const linePath = linePts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");

  // percentile horizontal markers
  const percentiles = window.SRA_PCTS;
  function dateAtPct(p) {
    for (let i=0; i<data.length; i++) if (data[i].pct >= p) return data[i].date;
    return data[data.length-1].date;
  }

  const [hover, setHover] = useState(null);

  // y-axis ticks for % hits
  const hitTicks = [];
  for (let pct = 0; pct <= maxPctHits + 0.001; pct += 0.02) {
    hitTicks.push(pct);
  }

  return (
    <div style={{position:"relative"}}>
      <svg viewBox={`0 0 ${w} ${h}`} style={{width:"100%", height:"auto", display:"block"}}>
        {/* gridlines */}
        {hitTicks.map((t, i) => (
          <g key={i}>
            <line x1={pad.l} x2={w-pad.r} y1={yHit(t)} y2={yHit(t)} stroke="var(--line)" />
            <text x={pad.l - 8} y={yHit(t)+3} fontSize="10" fill="var(--fg-3)" textAnchor="end">{Math.round(t*100)}%</text>
          </g>
        ))}
        {/* cumulative right axis */}
        {[0,0.25,0.5,0.75,1].map((t, i) => (
          <g key={i}>
            <line x1={w-pad.r} x2={w-pad.r+4} y1={yCum(t)} y2={yCum(t)} stroke="var(--fg-3)" />
            <text x={w-pad.r+8} y={yCum(t)+3} fontSize="10" fill="var(--fg-3)">{Math.round(t*100)}%</text>
          </g>
        ))}
        <text x={pad.l - 36} y={pad.t-8} fontSize="9" fill="var(--fg-3)" letterSpacing="0.06em">% OF HITS</text>
        <text x={w-pad.r + 8} y={pad.t-8} fontSize="9" fill="var(--fg-3)" letterSpacing="0.06em">CUMULATIVE</text>

        {/* bars */}
        {data.map((d, i) => {
          const pct = d.count / totalHits;
          const x = xOf(i) + 2;
          const y = yHit(pct);
          const isDeterministic = d.date === window.SRA_DETERMINISTIC;
          return (
            <g key={d.date}
               onMouseEnter={() => setHover({i, d, pct})}
               onMouseLeave={() => setHover(null)}>
              <rect x={x} y={y} width={Math.max(1, barW-4)} height={h - pad.b - y}
                    fill={isDeterministic ? "var(--accent)" : "var(--info)"} opacity="0.55"
                    stroke={isDeterministic ? "var(--accent)" : "var(--info)"} strokeWidth="0.5" />
            </g>
          );
        })}

        {/* percentile dashed verticals */}
        {percentiles.map(p => {
          const date = dateAtPct(p);
          const i = data.findIndex(d => d.date === date);
          const x = xOf(i) + barW;
          return (
            <g key={p}>
              <line x1={x} x2={x} y1={pad.t} y2={yCum(p)} stroke="var(--fg-4)" strokeDasharray="2 3" />
              <line x1={x} x2={w-pad.r} y1={yCum(p)} y2={yCum(p)} stroke="var(--fg-4)" strokeDasharray="2 3" />
              <text x={w-pad.r+8} y={yCum(p)-4} fontSize="10" fill="var(--accent-2)" fontFamily="var(--mono)">
                {Math.round(p*100)}% ({fmtDate(date)})
              </text>
            </g>
          );
        })}

        {/* cumulative line */}
        <path d={linePath} stroke="var(--ok)" strokeWidth="1.8" fill="none" />

        {/* x axis */}
        {data.map((d, i) => {
          if (i % 4 !== 0) return null;
          const x = xOf(i) + barW/2;
          return (
            <text key={i} x={x} y={h-pad.b+14} fontSize="10" fill="var(--fg-3)" textAnchor="middle">
              {fmtDate(d.date).slice(0,6)}
            </text>
          );
        })}
        <line x1={pad.l} x2={w-pad.r} y1={h-pad.b} y2={h-pad.b} stroke="var(--line-2)" />
        <text x={pad.l + innerW/2} y={h-8} fontSize="10" fill="var(--fg-3)" textAnchor="middle">
          PROGRAM FINISH DATE · Each bar = 1 day · 10,000 Monte-Carlo simulations
        </text>

        {/* deterministic marker */}
        <g>
          {(() => {
            const i = data.findIndex(d => d.date === window.SRA_DETERMINISTIC);
            const x = xOf(i) + barW/2;
            return (
              <g>
                <line x1={x} x2={x} y1={pad.t-12} y2={h-pad.b} stroke="var(--accent)" strokeWidth="1" strokeDasharray="2 2" />
                <rect x={x-40} y={pad.t-20} width="80" height="14" fill="var(--accent)" />
                <text x={x} y={pad.t-10} fontSize="9" fill="var(--bg)" textAnchor="middle" fontWeight="600" letterSpacing="0.06em">
                  DETERMINISTIC
                </text>
              </g>
            );
          })()}
        </g>
      </svg>

      {hover && (
        <div className="tt" style={{left:"50%", top:24}}>
          <span className="tt-key">{fmtDate(hover.d.date)}</span> · {hover.d.count} sims ({(hover.pct*100).toFixed(1)}%) · cum {(hover.d.pct*100).toFixed(1)}%
        </div>
      )}
    </div>
  );
}

// generic line chart for "Schedule Health History — last N cycles"
// Phase 15.x — added optional `zones` prop for R/Y/G health-band backgrounds.
// Each zone: { from, to, color }.  Rendered as semi-transparent rectangles
// behind the line so the user can see at a glance whether values are RED /
// YELLOW / GREEN territory.
function LineChart({ values, w = 800, h = 200, label, yMin = 0, yMax = 100, tone = "accent", zones }) {
  const pad = { l: 40, r: 16, t: 16, b: 24 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const stepX = values.length > 1 ? innerW / (values.length - 1) : innerW;
  const yOf = v => pad.t + (1 - (v - yMin)/(yMax - yMin)) * innerH;
  const xOf = i => pad.l + i * stepX;
  const pts = values.map((v, i) => [xOf(i), yOf(v)]);
  const path = pts.length > 1
    ? pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ")
    : "";
  const color =
    tone === "ok" ? "var(--ok)" : tone === "bad" ? "var(--bad)" :
    tone === "warn" ? "var(--warn)" : "var(--accent)";

  const ticks = [yMin, (yMin+yMax)/2, yMax];

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{width:"100%", height:"auto", display:"block"}}>
      {/* Health-band backgrounds (rendered first so the grid lines / data overlay them). */}
      {zones && zones.map((z, i) => {
        const yTop = yOf(z.to);
        const yBot = yOf(z.from);
        return (
          <g key={i}>
            <rect x={pad.l} y={Math.min(yTop, yBot)} width={innerW}
                  height={Math.abs(yBot - yTop)} fill={z.color} opacity="0.12" />
            {z.label && (
              <text x={w - pad.r - 6} y={(yTop + yBot) / 2 + 3}
                    fontSize="9" fill={z.color} opacity="0.7" textAnchor="end"
                    fontFamily="var(--mono)" letterSpacing="0.08em">
                {z.label}
              </text>
            )}
          </g>
        );
      })}
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={pad.l} x2={w-pad.r} y1={yOf(t)} y2={yOf(t)} stroke="var(--line)" />
          <text x={pad.l - 6} y={yOf(t)+3} fontSize="10" fill="var(--fg-3)" textAnchor="end">{t}</text>
        </g>
      ))}
      {path && <path d={path} stroke={color} strokeWidth="1.6" fill="none" />}
      {pts.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r="2.5" fill={color} />
      ))}
      <text x={pad.l} y={h-6} fontSize="10" fill="var(--fg-3)">CYCLE −{Math.max(0, values.length-1)}</text>
      <text x={w-pad.r} y={h-6} fontSize="10" fill="var(--fg-3)" textAnchor="end">CURRENT</text>
      {label && (
        <text x={w-pad.r} y={pad.t-4} fontSize="10" fill="var(--fg-3)" textAnchor="end" letterSpacing="0.06em">{label}</text>
      )}
    </svg>
  );
}

Object.assign(window, { SummaryScheduleGantt, SRAProbChart, LineChart, fmtDate, dateToFrac });
