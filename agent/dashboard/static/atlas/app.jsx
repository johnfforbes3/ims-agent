// ATLAS IMS Agent Console — App shell with terminal-style tab navigation
// and per-tab hero blocks. Original design (not a recreation of any specific product).

// Tab metadata.  Phase 15.x — channel-number badges removed per user
// request; F-key hints kept (they're keyboard-shortcut indicators, not
// "channel" references).
const TABS = [
  { id: "stats",   label: "IMS Stats & Info",         hint: "F1" },
  { id: "portal",  label: "Program Management Portal",hint: "F2" },
  { id: "agent",   label: "Agent Controls",           hint: "F3" },
];

function useTheme() {
  const init = (() => {
    try {
      const stored = localStorage.getItem("atlas.theme");
      if (stored === "light" || stored === "dark") return stored;
    } catch (e) {}
    return "dark";
  })();
  const [theme, setTheme] = useState(init);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("atlas.theme", theme); } catch (e) {}
  }, [theme]);
  // also handle keyboard shortcut: Cmd/Ctrl + L
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "l" && !e.shiftKey) {
        e.preventDefault();
        setTheme(t => t === "dark" ? "light" : "dark");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return [theme, setTheme];
}

function ThemeToggle({ theme, onToggle }) {
  return (
    <button
      className="theme-toggle"
      onClick={onToggle}
      title={`Switch to ${theme === "dark" ? "light" : "dark"} theme (⌘L)`}
      aria-label="Toggle theme"
    >
      {theme === "dark" ? (
        // sun icon (will switch to light)
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
          <circle cx="8" cy="8" r="3" />
          <path d="M8 1.5V3 M8 13v1.5 M1.5 8H3 M13 8h1.5 M3.5 3.5l1 1 M11.5 11.5l1 1 M12.5 3.5l-1 1 M4.5 11.5l-1 1" strokeLinecap="round" />
        </svg>
      ) : (
        // moon icon (will switch to dark)
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M13 9.5A5.5 5.5 0 1 1 6.5 3a4.5 4.5 0 0 0 6.5 6.5z" strokeLinejoin="round" />
        </svg>
      )}
      <span>{theme === "dark" ? "LIGHT" : "DARK"}</span>
    </button>
  );
}

function useTab() {
  const init = (() => {
    const h = window.location.hash.replace("#","");
    return TABS.find(t => t.id === h) ? h : "stats";
  })();
  const [tab, setTab] = useState(init);
  useEffect(() => {
    window.location.hash = tab;
    const onKey = (e) => {
      if (e.key === "F1") { e.preventDefault(); setTab("stats"); }
      if (e.key === "F2") { e.preventDefault(); setTab("portal"); }
      if (e.key === "F3") { e.preventDefault(); setTab("agent"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tab]);
  return [tab, setTab];
}

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const pad = n => String(n).padStart(2,"0");
  return (
    <span>
      {now.getFullYear()}-{pad(now.getMonth()+1)}-{pad(now.getDate())} ·{" "}
      {pad(now.getHours())}:{pad(now.getMinutes())}:{pad(now.getSeconds())}
    </span>
  );
}

function HeroStats({ items }) {
  return (
    <div className="hero-stats">
      {items.map(it => (
        <div className="hero-stat" key={it.label}>
          <div className="label">{it.label}</div>
          <div className="val" style={{color: it.tone === "ok" ? "var(--ok)" : it.tone === "warn" ? "var(--warn)" : it.tone === "bad" ? "var(--bad)" : it.tone === "accent" ? "var(--accent)" : "var(--fg)"}}>
            {it.value}{it.unit && <span className="unit">{it.unit}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function Hero({ tab }) {
  if (tab === "stats") {
    return (
      <header className="hero">
        <div className="hero-inner">
          <h1 className="hero-title">IMS STATS &amp; INFO</h1>
          <div className="hero-row">
            <div className="hero-actions">
              <button className="btn primary">▶ JUMP TO SCHEDULE</button>
              <button className="btn">⇣ EXPORT CYCLE C-19</button>
              <button className="btn">⌘ CHANGE BASELINE</button>
            </div>
            <HeroStats items={[
              { label: "BEI",  value: window.BEI_HIST[window.BEI_HIST.length-1].toFixed(2), tone: "bad"  },
              { label: "SFA",  value: window.SFA_HIST[window.SFA_HIST.length-1].toFixed(2), tone: "ok"   },
              { label: "HIGH-RISK MILESTONES", value: window.HRM_HIST[window.HRM_HIST.length-1], tone: "bad" },
              { label: "P80 FINISH", value: "18 Aug 26", tone: "warn" },
            ]} />
          </div>
        </div>
      </header>
    );
  }
  if (tab === "portal") {
    return (
      <header className="hero">
        <div className="hero-inner">
          <h1 className="hero-title">PROGRAM MANAGEMENT PORTAL</h1>
          <div className="hero-row">
            <div className="hero-actions">
              <button className="btn primary">⌗ GENERATE EXECUTIVE BRIEFING</button>
              <button className="btn">⇣ EXPORT CPR FMT-5</button>
            </div>
            <HeroStats items={[
              { label: "OPEN RISKS", value: "14", tone: "warn" },
              { label: "HEALTH SCORE", value: "62", unit:"/100", tone: "bad"  },
              { label: "RECOMMENDED ACTIONS", value: "4", tone: "accent" },
              { label: "NEXT IPR", value: "28 Jul 26", tone: "ok" },
            ]} />
          </div>
        </div>
      </header>
    );
  }
  // Phase 15.6 — FORCE CYCLE on the hero calls the real /api/trigger endpoint.
  // Inline feedback right under the button row so users see ✓ / ✗ without a modal.
  const [triggerState, setTriggerState] = useState("idle"); // idle | pending | done | error
  const [triggerMsg, setTriggerMsg]   = useState("");
  async function fireForceCycle() {
    setTriggerState("pending"); setTriggerMsg("");
    try {
      const r = await fetch("/api/trigger?force=true", { method: "POST" });
      const data = await r.json().catch(() => ({}));
      if (r.ok && (data.status === "triggered" || data.status === "queued")) {
        setTriggerState("done");
        setTriggerMsg("Cycle " + (data.cycle_id || "") + " triggered.");
      } else {
        setTriggerState("error");
        setTriggerMsg(data.detail || data.error || ("HTTP " + r.status));
      }
    } catch (e) {
      setTriggerState("error");
      setTriggerMsg(String(e));
    }
  }
  // Live CAM count for the hero KPIs
  const camsList = window.CAMS || [];
  const camsResponded = camsList.filter(c => c.responded).length;
  const camsTotal     = camsList.length || 10;
  const escalations   = camsList.filter(c => c.outcome === "ESCALATE").length;

  return (
    <header className="hero">
      <div className="hero-inner">
        <h1 className="hero-title">AGENT CONTROLS</h1>
        <div className="hero-row">
          <div className="hero-actions">
            <button
              className="btn primary"
              onClick={fireForceCycle}
              disabled={triggerState === "pending" || triggerState === "done"}
            >
              {triggerState === "pending" ? "⏳ TRIGGERING…" :
               triggerState === "done"    ? "✓ TRIGGERED"     :
                                            "▶ FORCE CYCLE"}
            </button>
            {/* Phase 15.x fix: hero DRY-RUN and KILL SWITCH used to be
                inert.  Now they dispatch a custom DOM event that the
                AgentControlsTab confirm-modal listens for, so the hero
                buttons open the same dialogs as the in-panel buttons. */}
            <button className="btn" onClick={() => window.dispatchEvent(new CustomEvent("atlas:open-confirm", {detail:{kind:"dry"}}))}>⏵ DRY-RUN</button>
            <button className="btn danger" onClick={() => window.dispatchEvent(new CustomEvent("atlas:open-confirm", {detail:{kind:"kill"}}))}>■ KILL SWITCH</button>
          </div>
          <HeroStats items={[
            { label: "CAMS RESPONDED", value: String(camsResponded), unit:"/" + camsTotal, tone: camsResponded === camsTotal ? "ok" : "warn" },
            { label: "ESCALATIONS",    value: String(escalations),  tone: escalations > 0 ? "bad" : "ok" },
            { label: "AGENT MODE",     value: "AUTONOMOUS", tone: "accent" },
            { label: "BASELINE LOCK",  value: "ARMED", tone: "ok" },
          ]} />
        </div>
        {triggerMsg && (
          <div style={{
            marginTop: 12, fontFamily: "var(--mono)", fontSize: 11,
            color: triggerState === "error" ? "var(--bad)" : "var(--ok)"
          }}>
            {triggerState === "error" ? "✗ " : "✓ "}{triggerMsg}
          </div>
        )}
      </div>
    </header>
  );
}

function TickerBar() {
  const items = [
    { k: "BEI",  v: "0.76",        d: -0.01 },
    { k: "SFA",  v: "0.86",        d:  0.01 },
    { k: "SPI",  v: "0.87",        d: -0.02 },
    { k: "CPI",  v: "0.93",        d: -0.01 },
    { k: "BCWP", v: "$77,364k",    d:  0.04 },
    { k: "EAC",  v: "$192,740k",   d:  0.02 },
    { k: "VAC",  v: "-$8,540k",    d: -0.03 },
    { k: "P50",  v: "13-Aug-26",   d:  0    },
    { k: "P80",  v: "18-Aug-26" },
    { k: "DCMA-HF", v: "11.2%",    d:  0.04 },
    { k: "CAMs",    v: "9 / 10",   d:  0    },
    { k: "CYCLE",   v: "C-2026-19 · 06:00Z" },
    { k: "MODE",    v: "AUTONOMOUS" },
  ];
  return <Ticker items={items} />;
}

function App() {
  const [tab, setTab] = useTab();
  const [theme, setTheme] = useTheme();

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <div className="brand-mark"><span>A</span></div>
            <div className="brand-name">ATLAS<span> · IMS AGENT</span></div>
          </div>
          <nav className="tabs">
            {TABS.map(t => (
              <button
                key={t.id}
                className={"tab" + (tab === t.id ? " is-active" : "")}
                onClick={() => setTab(t.id)}
                data-screen-label={t.label}
              >
                <span>{t.label}</span>
                <span style={{color:"var(--fg-4)", fontSize:9, marginLeft:6}}>{t.hint}</span>
              </button>
            ))}
          </nav>
          <div className="topbar-meta">
            <span className="pulse"><span className="dot live" /> LIVE</span>
            <span>·</span>
            <Clock />
            <span>·</span>
            <span style={{color:"var(--fg-2)"}}>OP · M.OYELOWO</span>
            <ThemeToggle theme={theme} onToggle={() => setTheme(t => t === "dark" ? "light" : "dark")} />
          </div>
        </div>
      </header>

      {/* Phase 15.x — ticker bar removed per user request. */}

      <main>
        <Hero tab={tab} />
        <div data-screen-label={tab === "stats" ? "IMS Stats & Info" : tab === "portal" ? "PM Portal" : "Agent Controls"}>
          {tab === "stats"  && <IMSStatsTab />}
          {tab === "portal" && <PMPortalTab />}
          {tab === "agent"  && <AgentControlsTab />}
        </div>
      </main>

      <footer style={{borderTop:"1px solid var(--line)", padding: "16px 24px", background: "var(--bg-2)", fontFamily:"var(--mono)", fontSize: 10, color:"var(--fg-3)", letterSpacing:"0.06em", display:"flex", justifyContent:"space-between"}}>
        <span>ATLAS-IMS v4.6.2 · BUILD 2026.05.16 · UNCLASSIFIED // PROGRAM USE</span>
        <span>SHORTCUTS · F1 / F2 / F3 · CYCLE C-2026-19 · NEXT @ 2026-05-23 06:00Z</span>
      </footer>
    </>
  );
}

// Phase 15.4 — wait for /api/* hydration so the first paint has live data.
// __IMS_HYDRATE is set by /static/atlas/api.js; if api.js failed to load
// (legacy rollback / network error), fall back to immediate mount with mock.
(window.__IMS_HYDRATE || Promise.resolve()).finally(() => {
  ReactDOM.createRoot(document.getElementById("root")).render(<App />);
});
