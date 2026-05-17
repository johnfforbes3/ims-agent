// Shared UI components for ATLAS IMS console.
// All Babel files share global scope; export to window at the bottom.

const { useState, useEffect, useRef, useMemo, useCallback } = React;

function Panel({ id, title, right, children, flush, style }) {
  return (
    <section className="panel" style={style}>
      <header className="panel-h">
        <div className="left">
          <span className="corner l">{id || ""}</span>
          <span>{title}</span>
        </div>
        <div className="right">{right}</div>
      </header>
      <div className={"panel-b" + (flush ? " flush" : "")}>{children}</div>
    </section>
  );
}

function SectionHeader({ ix, label, right }) {
  return (
    <div className="section-h">
      <span className="ix">{ix}</span>
      <span>{label}</span>
      {right ? <span style={{flex:"none"}}>{right}</span> : null}
    </div>
  );
}

function Pill({ tone = "info", children }) {
  return <span className={"pill " + tone}>{children}</span>;
}

function Seg({ value, onChange, options }) {
  return (
    <div className="seg">
      {options.map(o => (
        <button
          key={o.value}
          className={value === o.value ? "is-on" : ""}
          onClick={() => onChange(o.value)}
        >{o.label}</button>
      ))}
    </div>
  );
}

function RYG({ status, size }) {
  // shows three orbs, one lit
  return (
    <div className="ryg" title={"Schedule health: " + status.toUpperCase()}>
      <span className={"ryg-orb" + (size==="big" ? " big" : "") + (status === "bad"  ? " on bad"  : "")} />
      <span className={"ryg-orb" + (size==="big" ? " big" : "") + (status === "warn" ? " on warn" : "")} />
      <span className={"ryg-orb" + (size==="big" ? " big" : "") + (status === "ok"   ? " on ok"   : "")} />
      <span style={{marginLeft: 6, color:
        status==="ok" ? "var(--ok)" : status==="warn" ? "var(--warn)" : "var(--bad)"}}>
        {status.toUpperCase()}
      </span>
    </div>
  );
}

// formatters
function fmt(v, mode) {
  if (mode === "ratio") return v.toFixed(2);
  if (mode === "pct")   return (v*100).toFixed(0) + "%";
  if (mode === "kusd")  return (v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString();
  if (mode === "int")   return v.toString();
  return v.toString();
}

// thin sparkline used in KPI tiles
// Phase 15.x — hardened against short/empty value arrays.  Previously empty
// arrays produced ±Infinity (Math.min/max), divide-by-zero on stepX, and
// crashed on pts[length-1].  Now: empty → friendly "NO HISTORY" message,
// single-point → flat baseline + dot, normal series unchanged.
function Sparkline({ values, tone = "neutral", height = 56, axis }) {
  const w = 320;
  const h = height;
  const pad = { t: 8, r: 6, b: axis ? 16 : 6, l: 6 };
  const color =
    tone === "ok"   ? "var(--ok)" :
    tone === "warn" ? "var(--warn)" :
    tone === "bad"  ? "var(--bad)" : "var(--accent)";
  const safeValues = Array.isArray(values) ? values.filter(v => typeof v === "number" && isFinite(v)) : [];

  // Empty-state: render a baseline + label so the tile doesn't go blank
  if (safeValues.length === 0) {
    return (
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{width:"100%", height, display:"block"}} className="kpi-spark">
        <line x1={pad.l} x2={w-pad.r} y1={h-pad.b} y2={h-pad.b} stroke="var(--line)" />
        <text x={w/2} y={h/2+3} fontSize="10" fill="var(--fg-4)" textAnchor="middle"
              fontFamily="var(--mono)" letterSpacing="0.06em">NO HISTORY</text>
      </svg>
    );
  }

  const min = Math.min(...safeValues);
  const max = Math.max(...safeValues);
  const span = max - min || 1;
  const stepX = safeValues.length > 1 ? (w - pad.l - pad.r) / (safeValues.length - 1) : 0;
  const pts = safeValues.map((v, i) => {
    const x = safeValues.length > 1 ? pad.l + i * stepX : (pad.l + (w - pad.l - pad.r) / 2);
    const y = pad.t + (1 - (v - min) / span) * (h - pad.t - pad.b);
    return [x, y];
  });
  const line = pts.length > 1
    ? pts.map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ")
    : "";
  const area = line && pts.length > 1
    ? line + " L" + pts[pts.length-1][0] + "," + (h - pad.b) + " L" + pts[0][0] + "," + (h - pad.b) + " Z"
    : "";

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{width:"100%", height, display:"block"}} className="kpi-spark">
      <defs>
        <linearGradient id={"g-" + tone} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* baseline grid */}
      <line x1={pad.l} x2={w-pad.r} y1={h-pad.b} y2={h-pad.b} stroke="var(--line)" />
      {axis && <line x1={pad.l} x2={pad.l} y1={pad.t} y2={h-pad.b} stroke="var(--line)" />}
      {area && <path d={area} fill={`url(#g-${tone})`} />}
      {line && <path d={line} stroke={color} fill="none" strokeWidth="1.5" />}
      {/* last dot — always render so a single-point series is still visible */}
      <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r="2.5" fill={color} />
      {axis && (
        <g fontSize="9" fill="var(--fg-4)" fontFamily="var(--mono)">
          <text x={pad.l} y={h-3}>{axis[0]}</text>
          <text x={w-pad.r} y={h-3} textAnchor="end">{axis[1]}</text>
        </g>
      )}
    </svg>
  );
}

// KPI tile with optional sparkline
function KPITile({ label, value, unit, tone = "neutral", spark, sparkAxis, sub, delta }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={"kpi-val " + (tone !== "neutral" ? tone : "")}>
        {value}{unit && <span className="unit">{unit}</span>}
      </div>
      {sub && <div className="kpi-sub">{sub}</div>}
      {delta != null && (
        <div className={"delta " + (delta >= 0 ? "up" : "dn")}>
          {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(2)} vs prior cycle
        </div>
      )}
      {spark && <Sparkline values={spark} tone={tone} axis={sparkAxis} />}
    </div>
  );
}

// ticker bar
function Ticker({ items }) {
  // duplicate items so the loop is seamless
  const doubled = [...items, ...items];
  return (
    <div className="ticker">
      <div className="ticker-track">
        {doubled.map((it, i) => (
          <span className="tk-item" key={i}>
            <span className="tk-key">{it.k}</span>
            <span className="tk-val">{it.v}</span>
            {it.d != null && (
              <span className={"tk-delta " + (it.d >= 0 ? "up" : "dn")}>
                {it.d >= 0 ? "▲" : "▼"} {Math.abs(it.d).toFixed(2)}
              </span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, {
  Panel, SectionHeader, Pill, Seg, RYG, KPITile, Sparkline, Ticker, fmt,
});
