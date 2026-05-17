// Mock data layer for ATLAS IMS — exported to window for cross-script access
// All dates are ISO; UI computes positions/widths.

const PROGRAM_START = new Date("2026-01-05");
const PROGRAM_END   = new Date("2026-12-18");
const TODAY         = new Date("2026-05-16");

// ---------- Summary Schedule (Tier-1 IMS) ----------
// Two versions: current + prior (1 cycle back). Critical-path tasks in red, milestones as diamonds.
const SCHED_CURRENT = {
  label: "v2026.10",
  cycle: "C-2026-19",
  generated: "2026-05-16 06:00Z",
  rows: [
    { id: "L1", name: "Phase 1 · Requirements Lock", start: "2026-01-05", end: "2026-02-20", critical: false, complete: 1.0 },
    { id: "L2", name: "Phase 2 · System Definition", start: "2026-02-09", end: "2026-04-10", critical: true,  complete: 1.0 },
    { id: "L3", name: "Phase 3 · Preliminary Design", start: "2026-03-23", end: "2026-06-12", critical: true,  complete: 0.76 },
    { id: "L4", name: "Phase 4 · Critical Design",     start: "2026-05-18", end: "2026-08-21", critical: true,  complete: 0.04 },
    { id: "L5", name: "Phase 5 · Integration",         start: "2026-08-10", end: "2026-10-30", critical: true,  complete: 0.00 },
    { id: "L6", name: "Phase 6 · Verification",        start: "2026-10-12", end: "2026-12-04", critical: false, complete: 0.00 },
    { id: "L7", name: "Phase 7 · Handover",            start: "2026-11-23", end: "2026-12-18", critical: false, complete: 0.00 },
    { id: "L8", name: "Subsystem A · Avionics",        start: "2026-02-02", end: "2026-07-31", critical: false, complete: 0.42 },
    { id: "L9", name: "Subsystem B · Propulsion",      start: "2026-03-09", end: "2026-09-04", critical: true,  complete: 0.31 },
    { id: "L10",name: "Subsystem C · GN&C",            start: "2026-04-06", end: "2026-09-25", critical: false, complete: 0.18 },
  ],
  milestones: [
    { id: "M1", name: "SRR",   date: "2026-02-20", critical: false, met: true  },
    { id: "M2", name: "SDR",   date: "2026-04-10", critical: true,  met: true  },
    { id: "M3", name: "PDR",   date: "2026-06-12", critical: true,  met: false },
    { id: "M4", name: "CDR",   date: "2026-08-21", critical: true,  met: false },
    { id: "M5", name: "TRR",   date: "2026-10-30", critical: true,  met: false },
    { id: "M6", name: "FRR",   date: "2026-12-04", critical: false, met: false },
    { id: "M7", name: "OPR",   date: "2026-12-18", critical: false, met: false },
  ],
};
const SCHED_PRIOR = {
  label: "v2026.09",
  cycle: "C-2026-18",
  generated: "2026-05-09 06:00Z",
  rows: SCHED_CURRENT.rows.map((r, i) => ({
    ...r,
    start: shiftDays(r.start, [0,0,-3,-5,-7,-9,-9,-2,-4,-3][i] || 0),
    end:   shiftDays(r.end,   [0,0,-3,-5,-7,-9,-9,-2,-4,-3][i] || 0),
    complete: Math.max(0, r.complete - [0,0,0.08,0.04,0,0,0,0.05,0.04,0.03][i]),
  })),
  milestones: SCHED_CURRENT.milestones.map((m, i) => ({
    ...m,
    date: shiftDays(m.date, [0,-3,-5,-7,-9,-9,-9][i] || 0),
  })),
};
function shiftDays(iso, days) {
  const d = new Date(iso); d.setDate(d.getDate() + days);
  return d.toISOString().slice(0,10);
}

// ---------- KPI tiles (6-month trend) ----------
function gen(seed, n, base, vol) {
  let x = seed; const out = [];
  for (let i = 0; i < n; i++) {
    x = (x * 9301 + 49297) % 233280;
    const r = (x / 233280 - 0.5) * 2;
    out.push(+(base + r * vol).toFixed(3));
  }
  return out;
}
const BEI_HIST = [0.96, 0.95, 0.94, 0.93, 0.92, 0.91, 0.90, 0.89, 0.91, 0.90, 0.88, 0.87, 0.85, 0.86, 0.84, 0.83, 0.82, 0.83, 0.81, 0.80, 0.81, 0.79, 0.78, 0.77, 0.78, 0.76];
const SFA_HIST = [0.78, 0.80, 0.81, 0.79, 0.83, 0.85, 0.86, 0.84, 0.85, 0.83, 0.82, 0.84, 0.86, 0.87, 0.86, 0.85, 0.84, 0.85, 0.86, 0.87, 0.86, 0.85, 0.86, 0.87, 0.88, 0.86];
const HRM_HIST = [4, 5, 4, 6, 5, 7, 8, 7, 9, 8, 9, 10, 9, 10, 11, 12, 11, 12, 13, 12, 13, 14, 13, 14, 15, 14];

// classify thresholds
function classifyBEI(v) { return v >= 0.95 ? "ok" : v >= 0.85 ? "warn" : "bad"; }
function classifySFA(v) { return v >= 0.90 ? "ok" : v >= 0.80 ? "warn" : "bad"; }
function classifyHRM(v) { return v <= 5    ? "ok" : v <= 10   ? "warn" : "bad"; }

// ---------- SRA histogram (Monte Carlo, 10,000 sims) ----------
function buildSRA(seed) {
  // bell-skewed histogram over 24 days starting 02 Aug 2026
  const bins = [];
  const start = new Date("2026-08-02");
  const peak = 11; // peak index
  let total = 0;
  for (let i = 0; i < 24; i++) {
    const sigma = 4.2;
    const skew = i > peak ? 1.2 : 1.0;
    const y = Math.exp(-Math.pow((i - peak)/sigma, 2)/2) / skew;
    const noise = ((Math.sin(seed*i + 3) * 1000) % 1 + 1) % 1;
    const v = Math.max(0, y * 1100 + noise * 30 - 15);
    bins.push({ date: shiftDays(start.toISOString().slice(0,10), i), count: Math.round(v) });
    total += v;
  }
  let cum = 0;
  return bins.map(b => {
    cum += b.count;
    return { ...b, pct: cum / total };
  });
}
const SRA = buildSRA(7);
const SRA_DETERMINISTIC = "2026-08-12";
const SRA_MEAN = "2026-08-13 14:22";
const SRA_PCTS = [0.10, 0.30, 0.50, 0.70, 0.80, 0.90];

// ---------- EVM Metrics (current cycle) ----------
const EVM_KPIS = [
  { key: "SPI",        val: 0.87, fmt: "ratio",  tone: "warn",  note: "Schedule Perf. Index" },
  { key: "SV",         val: -1840, fmt: "kusd",  tone: "bad",   note: "Schedule Variance" },
  { key: "% Complete", val: 0.42, fmt: "pct",    tone: "ok",    note: "Weighted physical" },
  { key: "BEI",        val: 0.76, fmt: "ratio",  tone: "bad",   note: "Baseline Exec. Index" },
  { key: "BAC",        val: 184200, fmt: "kusd", tone: "neutral", note: "Budget At Completion" },
  { key: "EAC",        val: 192740, fmt: "kusd", tone: "warn",  note: "Estimate At Completion" },
  { key: "VAC",        val: -8540, fmt: "kusd",  tone: "bad",   note: "Variance At Completion" },
  { key: "BCWP",       val: 77364, fmt: "kusd",  tone: "neutral", note: "Earned Value" },
];

// ---------- CAM breakdown (also used by Agent Controls) ----------
const CAMS = [
  { cam: "CAM-101", lead: "K. Ramos",    wbs: "1.1 Avionics",        bac: 24800, bcwp: 11420, bcws: 12640, acwp: 12010, spi: 0.90, cpi: 0.95, status: "ok",   responded: true,  attempts: 1, outcome: "BASELINE",  drift: 0,  health: "green" },
  { cam: "CAM-102", lead: "S. Patel",    wbs: "1.2 Propulsion",      bac: 32100, bcwp: 12860, bcws: 16080, acwp: 14900, spi: 0.80, cpi: 0.86, status: "warn", responded: true,  attempts: 2, outcome: "BASELINE",  drift: 4,  health: "yellow" },
  { cam: "CAM-103", lead: "M. O'Neill",  wbs: "1.3 GN&C",            bac: 18200, bcwp: 6900,  bcws: 8650,  acwp: 7960,  spi: 0.80, cpi: 0.87, status: "warn", responded: true,  attempts: 1, outcome: "BASELINE",  drift: 3,  health: "yellow" },
  { cam: "CAM-104", lead: "R. Chen",     wbs: "1.4 Power",           bac: 14500, bcwp: 7250,  bcws: 7100,  acwp: 7430,  spi: 1.02, cpi: 0.97, status: "ok",   responded: true,  attempts: 1, outcome: "BASELINE",  drift: 0,  health: "green" },
  { cam: "CAM-105", lead: "T. Becker",   wbs: "1.5 Structure",       bac: 21400, bcwp: 11240, bcws: 11760, acwp: 11820, spi: 0.96, cpi: 0.95, status: "ok",   responded: true,  attempts: 1, outcome: "BASELINE",  drift: 0,  health: "green" },
  { cam: "CAM-106", lead: "A. Suzuki",   wbs: "1.6 Thermal",         bac: 11900, bcwp: 4280,  bcws: 5950,  acwp: 4910,  spi: 0.72, cpi: 0.87, status: "bad",  responded: true,  attempts: 3, outcome: "ESCALATE",  drift: 9,  health: "red" },
  { cam: "CAM-107", lead: "D. Hassan",   wbs: "1.7 SW & Ground",     bac: 26100, bcwp: 13580, bcws: 14070, acwp: 13710, spi: 0.97, cpi: 0.99, status: "ok",   responded: true,  attempts: 1, outcome: "BASELINE",  drift: 1,  health: "green" },
  { cam: "CAM-108", lead: "J. Cole",     wbs: "1.8 I&T",             bac: 19400, bcwp: 4640,  bcws: 5820,  acwp: 5340,  spi: 0.80, cpi: 0.87, status: "warn", responded: false, attempts: 2, outcome: "PENDING",   drift: 5,  health: "yellow" },
  { cam: "CAM-109", lead: "P. Iyer",     wbs: "1.9 Test Eq.",        bac: 9800,  bcwp: 4090,  bcws: 4280,  acwp: 4150,  spi: 0.96, cpi: 0.99, status: "ok",   responded: true,  attempts: 1, outcome: "BASELINE",  drift: 0,  health: "green" },
  { cam: "CAM-110", lead: "L. Vargas",   wbs: "1.10 Logistics",      bac: 6000,  bcwp: 1104,  bcws: 1420,  acwp: 1280,  spi: 0.78, cpi: 0.86, status: "warn", responded: true,  attempts: 1, outcome: "BASELINE",  drift: 2,  health: "yellow" },
];

// ---------- DCMA 14-point ----------
const DCMA14 = [
  { id: 1,  name: "Logic",                  val: "2.1%", target: "≤ 5%",   pass: "pass" },
  { id: 2,  name: "Leads",                  val: "0.4%", target: "≤ 5%",   pass: "pass" },
  { id: 3,  name: "Lags",                   val: "6.8%", target: "≤ 5%",   pass: "warn" },
  { id: 4,  name: "Relationship Types",     val: "92%",  target: "≥ 90% FS", pass: "pass" },
  { id: 5,  name: "Hard Constraints",       val: "3.0%", target: "≤ 5%",   pass: "pass" },
  { id: 6,  name: "High Float",             val: "11.2%",target: "≤ 5%",   pass: "fail" },
  { id: 7,  name: "Negative Float",         val: "0.8%", target: "0%",     pass: "warn" },
  { id: 8,  name: "High Duration",          val: "4.1%", target: "≤ 5%",   pass: "pass" },
  { id: 9,  name: "Invalid Dates",          val: "0",    target: "0",      pass: "pass" },
  { id: 10, name: "Resources",              val: "98%",  target: "≥ 95%",  pass: "pass" },
  { id: 11, name: "Missed Tasks",           val: "7.4%", target: "≤ 5%",   pass: "warn" },
  { id: 12, name: "Critical Path Test",     val: "OK",   target: "Pass",   pass: "pass" },
  { id: 13, name: "CPLI",                   val: "0.94", target: "≥ 0.95", pass: "warn" },
  { id: 14, name: "BEI",                    val: "0.76", target: "≥ 0.95", pass: "fail" },
];

// ---------- PM Portal ----------
const TOP_RISKS_PROSE = [
  { id: "R1", title: "Propulsion vendor schedule slip", body: "Subsystem B (Propulsion) is consuming 9 days of float against the critical path. Vendor's revised commit for the turbopump assembly drift confirms a probable PDR slip of 7–11 working days unless mitigated within 2 cycles.", impact: "Critical", probability: 0.78 },
  { id: "R2", title: "CDR resource saturation", body: "Three CAMs (Thermal, GN&C, I&T) are forecast to overlap peak demand the week of 24-Aug. Resource leveling indicates 1.4× FTE shortage on thermal-vac analysts, materially increasing CDR closure risk.", impact: "High", probability: 0.62 },
  { id: "R3", title: "Requirements churn in GFE interface", body: "Government-furnished equipment ICD has been amended 4× in the last 24 cycles. Each amendment adds a ~3-day rework loop in Avionics. Continued churn through July threatens BEI recovery.", impact: "Moderate", probability: 0.55 },
];
const PM_ACTIONS_PROSE = [
  { id: "A1", title: "Accelerate propulsion alternate sourcing", body: "Authorize CAM-102 to issue an alternate-source RFQ for turbopump bearing assemblies by 22-May. Parallel sourcing recovers approximately 6 working days against the critical path with marginal cost exposure ≤ $480k.", priority: "Now" },
  { id: "A2", title: "Re-baseline thermal CDR window",  body: "Move thermal CDR gate from 14-Aug to 21-Aug to absorb analyst shortfall and align with propulsion commit. Coordinate with the customer rep no later than next IPR.", priority: "This week" },
  { id: "A3", title: "Lock ICD revision through CDR",   body: "Negotiate ICD freeze with the GFE provider effective 01-Jun through CDR closure (no more than two delta amendments). Codify in PMP §5.4.", priority: "Within 2 cycles" },
  { id: "A4", title: "Initiate weekly DCMA-14 review",  body: "Stand up a weekly 30-min DCMA review with all CAMs starting Cycle-20 to drive High Float (11.2%) under threshold before CDR.", priority: "Recurring" },
];
const HEALTH_HISTORY = [
  82, 80, 78, 79, 77, 75, 74, 76, 78, 80, 81, 79, 76, 73, 70, 68, 67, 69, 71, 70, 68, 66, 64, 62,
];

// ---------- Agent Controls ----------
const CYCLE_PHASES = ["BOOT", "DISPATCH", "INTERVIEW", "DIFF", "VALIDATE", "PUBLISH"];

const DIFF_ROWS = [
  { task: "1.2.4 Turbopump qual",        cam: "CAM-102", field: "Finish",    oldv: "04-Aug-26", newv: "13-Aug-26", delta: "+9d" },
  { task: "1.2.4 Turbopump qual",        cam: "CAM-102", field: "Predecessor",oldv: "1.2.3 FS",   newv: "1.2.3 FS+3d", delta: "+3d lag" },
  { task: "1.6.2 TVAC analyst loading",  cam: "CAM-106", field: "Resource",  oldv: "2.0 FTE",    newv: "1.4 FTE",     delta: "-0.6 FTE" },
  { task: "1.6.2 TVAC analyst loading",  cam: "CAM-106", field: "Duration",  oldv: "12d",        newv: "18d",         delta: "+6d" },
  { task: "1.3.1 GN&C unit test",         cam: "CAM-103", field: "Finish",   oldv: "29-Jun-26",  newv: "02-Jul-26",   delta: "+3d" },
  { task: "1.8.1 I&T dry run",            cam: "CAM-108", field: "% Complete",oldv: "12%",       newv: "18%",         delta: "+6 pp" },
  { task: "1.4.3 PDU integration",        cam: "CAM-104", field: "Finish",   oldv: "11-Jul-26",  newv: "09-Jul-26",   delta: "-2d" },
  { task: "1.1.6 Avionics ICD freeze",    cam: "CAM-101", field: "Note",     oldv: "—",          newv: "ICD rev 12",  delta: "new" },
];

const CUM_DIFF = [
  { task: "1.2.4 Turbopump qual",   cam: "CAM-102", finishDrift: 12, hops: 4, cycles: "C-15 → C-19" },
  { task: "1.6.2 TVAC analyst",     cam: "CAM-106", finishDrift: 9,  hops: 3, cycles: "C-16 → C-19" },
  { task: "1.3.1 GN&C unit test",   cam: "CAM-103", finishDrift: 6,  hops: 2, cycles: "C-17 → C-19" },
  { task: "1.8.1 I&T dry run",      cam: "CAM-108", finishDrift: 5,  hops: 3, cycles: "C-15 → C-19" },
  { task: "1.5.2 Structure mate",   cam: "CAM-105", finishDrift: 1,  hops: 1, cycles: "C-19" },
  { task: "1.7.4 Ground SW build",  cam: "CAM-107", finishDrift: -2, hops: 1, cycles: "C-19" },
];

const DRIFT_ROWS = [
  { task: "1.2.4 Turbopump qual",     cam: "CAM-102", baseFin: "01-Aug-26", curFin: "13-Aug-26", slip: 12, pctDelta: -8 },
  { task: "1.6.2 TVAC analyst",       cam: "CAM-106", baseFin: "27-Jul-26", curFin: "05-Aug-26", slip: 9,  pctDelta: -6 },
  { task: "1.3.1 GN&C unit test",     cam: "CAM-103", baseFin: "26-Jun-26", curFin: "02-Jul-26", slip: 6,  pctDelta: -4 },
  { task: "1.8.1 I&T dry run",        cam: "CAM-108", baseFin: "21-Aug-26", curFin: "26-Aug-26", slip: 5,  pctDelta: 6  },
  { task: "1.5.2 Structure mate",     cam: "CAM-105", baseFin: "12-Jul-26", curFin: "13-Jul-26", slip: 1,  pctDelta: 0  },
  { task: "1.7.4 Ground SW build",    cam: "CAM-107", baseFin: "08-Sep-26", curFin: "06-Sep-26", slip: -2, pctDelta: 2  },
  { task: "1.4.3 PDU integration",    cam: "CAM-104", baseFin: "11-Jul-26", curFin: "09-Jul-26", slip: -2, pctDelta: 3  },
  { task: "1.10.1 Logistics readiness",cam:"CAM-110", baseFin: "03-Oct-26", curFin: "08-Oct-26", slip: 5,  pctDelta: -1 },
];

// scripted interview lines used by the SSE simulator
const INTERVIEW_SCRIPT = [
  { who: "sys",   body: "▸ Session opened. Cycle C-2026-19 · Phase: INTERVIEW" },
  { who: "agent", body: "ATLAS → CAM-102 (S. Patel): Last cycle you committed turbopump qual finish 04-Aug. Statusline still shows that?" },
  { who: "cam",   body: "CAM-102: Negative. Vendor pushed bearing lot delivery 9 days. New commit 13-Aug." },
  { who: "agent", body: "ATLAS → CAM-102: Acknowledged. Is the slip on critical path? Float remaining?" },
  { who: "cam",   body: "CAM-102: Critical path, yes. Float remaining is zero. Burning customer reserve." },
  { who: "agent", body: "ATLAS → CAM-102: Logging baseline drift +9d on 1.2.4. Any mitigation under way?" },
  { who: "cam",   body: "CAM-102: Issuing alt-source RFQ. Decision gate Friday." },
  { who: "agent", body: "ATLAS → CAM-102: Captured. Closing entry." },
  { who: "sys",   body: "▸ CAM-102 interview complete · 2 fields changed · outcome: BASELINE" },
  { who: "agent", body: "ATLAS → CAM-106 (A. Suzuki): TVAC analyst loading dropped from 2.0 to 1.4 FTE. Confirm?" },
  { who: "cam",   body: "CAM-106: Confirm. One analyst rotated to another program. Duration extended to 18d." },
  { who: "agent", body: "ATLAS → CAM-106: That's the third loading change this month. Escalating per policy." },
  { who: "sys",   body: "▸ CAM-106 interview complete · 2 fields changed · outcome: ESCALATE" },
  { who: "agent", body: "ATLAS → CAM-103 (M. O'Neill): GN&C unit test finish moved 29-Jun → 02-Jul. Cause?" },
  { who: "cam",   body: "CAM-103: Test rig calibration. Three day slip. Not critical path." },
];

// expose to other scripts
Object.assign(window, {
  PROGRAM_START, PROGRAM_END, TODAY,
  SCHED_CURRENT, SCHED_PRIOR,
  BEI_HIST, SFA_HIST, HRM_HIST,
  classifyBEI, classifySFA, classifyHRM,
  SRA, SRA_DETERMINISTIC, SRA_MEAN, SRA_PCTS,
  EVM_KPIS, CAMS, DCMA14,
  TOP_RISKS_PROSE, PM_ACTIONS_PROSE, HEALTH_HISTORY,
  CYCLE_PHASES, DIFF_ROWS, CUM_DIFF, DRIFT_ROWS, INTERVIEW_SCRIPT,
  shiftDays,
});
