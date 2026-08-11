import { useState, useEffect, useRef } from "react";
import { useNavigate as useRouterNavigate, useLocation } from "react-router-dom";

const VIEW_PATHS = {
  "landing":            "/",
  "balca":              "/balca",
  "aao":               "/aao",
  "regulations":        "/regulations",
  "policy":             "/policy",
  "citation-graph":     "/citation-graph",
  "aao-citation-graph": "/aao-citation-graph",
  "perm-comparer":      "/perm-comparer",
  "perm-verify":        "/perm-verify",
  "evl-compare":        "/evl-compare",
  "applicant-eval":     "/applicant-eval",
  "visa-bulletin":      "/visa-bulletin",
  "wage-forecaster":    "/wage-forecaster",
  "wage-dashboard":     "/wage-dashboard",
  "wage-level":         "/wage-level",
  "soc-suggest":        "/soc-suggest",
  "eb-inventory":       "/eb-inventory",
  "projects":           "/projects",
  "oflc":               "/oflc",
  "processing-times":   "/processing-times",
  "kanban":             "/kanban",
  "ask":               "/ask",
  "search-all":         "/search-all",
};
const PATH_VIEWS = Object.fromEntries(Object.entries(VIEW_PATHS).map(([k, v]) => [v, k]));
import "./index.css";
import { API } from "./apiBase";
import { KanbanView } from "./KanbanView";
import { OflcView } from "./OflcView";
import { VisaBulletinView } from "./VisaBulletinView";
import { AAOSearchView } from "./AaoViews";
import { AskView } from "./AskView";
import { SearchView } from "./BalcaViews";
import { AAOCitationGraphView, CitationGraphView } from "./CitationGraphs";
import { PermComparer } from "./PermComparer";
import { PermVerifyView } from "./PermVerifyView";
import { EvlCompareView } from "./EvlCompareView";
import { ApplicantEvalView } from "./ApplicantEvalView";
import { ProjectsView } from "./ProjectsViews";
import { PolicyView, RegulationsView } from "./RegulationPolicyViews";
import { SearchAllView } from "./SearchAllView";
import { useFetch } from "./common";
import { WageForecaster } from "./WageForecaster";
import { WageDashboard } from "./WageDashboard";
import { WageLevelView } from "./WageLevelView";
import { SocSuggestView } from "./SocSuggestView";
import { EbInventoryView } from "./EbInventoryView";
import { ProcessingTimesView } from "./ProcessingTimesView";

function LandingPage({ onNavigate }) {
  const { data: stats } = useFetch(`${API}/stats`);
  const { data: aaoStats } = useFetch(`${API}/aao/stats`);

  const modules = [
    { id: "balca", label: "BALCA / PERM Decisions", description: "Board of Alien Labor Certification Appeals — employer-sponsored green card appeals", count: stats?.total_decisions, countLabel: "decisions", accent: "var(--accent)", accentDim: "var(--accent-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>, available: true },
    { id: "aao", label: "AAO Decisions", description: "Administrative Appeals Office — USCIS benefit petition appeals across all visa categories", count: aaoStats?.total_decisions, countLabel: "decisions", accent: "var(--blue)", accentDim: "var(--blue-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>, available: true },
    { id: "regulations", label: "Regulations & Statutes", description: "8 CFR, 20 CFR, 22 CFR, and 29 CFR — full text search across 120 parts, 2,301 pages", accent: "var(--green)", accentDim: "var(--green-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>, available: true },
    { id: "policy", label: "Policy Manuals", description: "USCIS Policy Manual, Foreign Affairs Manual — agency guidance and adjudication policies", accent: "#a78bfa", accentDim: "#a78bfa22", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>, available: true },
    { id: "search-all", label: "Search All", description: "Cross-corpus search across decisions, regulations, and policy documents simultaneously", accent: "#fb7185", accentDim: "#fb718522", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>, available: true },
    { id: "aao-citation-graph", label: "AAO Citation Graph", description: "Map how AAO decisions cite each other — surface the most-referenced precedents and form-type patterns visually", accent: "var(--blue)", accentDim: "var(--blue-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>, available: true },
    { id: "citation-graph", label: "Citation Graph", description: "Map how search results cite each other — see the most-cited cases and citation branches emerge visually", accent: "var(--accent)", accentDim: "var(--accent-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>, available: true },
    { id: "perm-comparer", label: "PERM Comparer", description: "Compare job description and requirements language, validate PWD wage positioning, and export reports.", accent: "var(--accent)", accentDim: "var(--accent-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 1 1 0 10h-2"/><line x1="8" y1="12" x2="16" y2="12"/></svg>, available: true },
    { id: "perm-verify", label: "PERM Verify", description: "Upload a completed ETA-9089 (and its PWD) to flag denial risks, timing violations, and audit exposure — with citations.", accent: "var(--accent)", accentDim: "var(--accent-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M9 12l2 2 4-5"/><path d="M12 3l7 4v5c0 4.5-3 8-7 9-4-1-7-4.5-7-9V7z"/></svg>, available: true },
    { id: "evl-compare", label: "PWD / EVL Review", description: "Compare every current PWD requirement against experience verification letters and report what is covered, unclear, or missing.", accent: "var(--blue)", accentDim: "var(--blue-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 4h6v16H4zM14 4h6v16h-6z"/><path d="m6 10 1.5 1.5L9 9M16 10h2M16 14h2"/></svg>, available: true },
    { id: "applicant-eval", label: "Applicant Evaluation", description: "Generate the recruiter applicant-review spreadsheet from a PWD or pasted requirements — YES/NO evaluation columns, auto-recommendation formula, and row highlighting.", accent: "var(--amber)", accentDim: "var(--amber-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/><path d="m5.5 13.5 1 1 2-2"/></svg>, available: true },
    { id: "visa-bulletin", label: "Visa Bulletin", description: "Monthly DOS priority dates — track cutoffs, retrogression, and backlog estimates for EB and family categories", accent: "var(--green)", accentDim: "var(--green-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>, available: true },
    { id: "wage-dashboard", label: "July 1 Wage Comparer", description: "2026-27 vs 2025-26 prevailing wage changes — US heat map, metro-level SOC comparisons, top movers, and employer exposure analysis", accent: "var(--green)", accentDim: "var(--green-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>, available: true },
    { id: "wage-forecaster", label: "Upcoming Wage Estimator", description: "July 2026 prevailing wage projections — all 619 H-1B/PERM occupation codes across 530 metro areas, current OFLC 2025-26 floors and ECI-calibrated estimates", accent: "var(--green)", accentDim: "var(--green-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>, available: true },
    { id: "wage-level", label: "Wage Level Tool", description: "NPWHC 2009 worksheet — SOC code, degree, and experience in; OES wage level (I–IV) out, with the point-by-point rationale and prevailing wage dollars.", accent: "var(--green)", accentDim: "var(--green-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/></svg>, available: true },
    { id: "soc-suggest", label: "SOC Suggester", description: "Job description and minimum requirements in; ranked SOC code matches out, each with the duties it covers and why it fits — top match runs the wage-level worksheet with prevailing wage dollars.", accent: "var(--amber)", accentDim: "var(--amber-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>, available: true },
    { id: "oflc", label: "DOL Performance Data", description: "PERM, LCA, and Prevailing Wage disclosure data — 1.4M+ records across FY2020–FY2026. Dashboards, templates, and pivot builder.", accent: "var(--accent)", accentDim: "var(--accent-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>, available: true },
    { id: "processing-times", label: "Case Processing Times", description: "Historical USCIS and DOL timelines — compare H-1B, O, PERM, prevailing wage, and other case types with methodology and volume context.", accent: "#a78bfa", accentDim: "#a78bfa22", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 3v18h18"/><path d="m7 16 4-5 3 3 5-7"/><circle cx="7" cy="16" r="1"/><circle cx="11" cy="11" r="1"/><circle cx="14" cy="14" r="1"/><circle cx="19" cy="7" r="1"/></svg>, available: true },
    { id: "eb-inventory", label: "EB Inventory", description: "Priority date queue analysis — 74K observations across 5 countries and 7 categories. Tier 1 forecaster for Philippines/Mexico, regime monitor for India/China, queue position for all.", accent: "var(--blue)", accentDim: "var(--blue-dim)", icon: <svg width='28' height='28' viewBox='0 0 24 24' fill='none' stroke='currentColor' strokeWidth='1.5'><rect x='3' y='4' width='18' height='18' rx='2' ry='2'/><line x1='16' y1='2' x2='16' y2='6'/><line x1='8' y1='2' x2='8' y2='6'/><line x1='3' y1='10' x2='21' y2='10'/></svg>, available: true },
    { id: "ask", label: "Ask AI", description: "Ask a research question — get a cited answer synthesized across cases, regulations, and policy", accent: "#f472b6", accentDim: "#f472b622", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>, available: true },
    { id: "letter-assistant", label: "Letter Assistant", description: "AI-powered drafting and review for NIW and EB-1A support letters — powered by AAO precedent", accent: "var(--accent)", accentDim: "var(--accent-dim)", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>, available: false, comingSoon: true },
  ];

  return (
    <div className="grid-bg" style={{ height: "100%", overflowY: "auto" }}>
      <div style={{ maxWidth: 960, margin: "0 auto", padding: "48px 32px 64px" }}>
        <div style={{ marginBottom: 48, textAlign: "center" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, marginBottom: 12 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--amber)" }} />
            <span style={{ fontFamily: "'DM Serif Display', serif", fontSize: 36, color: "var(--text)", letterSpacing: "-0.01em" }}>Casebase</span>
          </div>
          <p style={{ fontSize: 15, color: "var(--text3)", maxWidth: 520, margin: "0 auto" }}>Immigration law research — decisions, regulations, policy, and AI-assisted drafting</p>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
          {modules.map(m => (
            <div key={m.id} onClick={() => m.available && onNavigate(m.id)}
              style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "24px", background: "var(--bg2)", cursor: m.available ? "pointer" : "default", opacity: m.available ? 1 : 0.55, transition: "border-color 0.15s, background 0.15s, transform 0.15s", position: "relative" }}
              onMouseEnter={e => { if (!m.available) return; e.currentTarget.style.borderColor = m.accent; e.currentTarget.style.background = m.accentDim; e.currentTarget.style.transform = "translateY(-2px)"; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.background = "var(--bg2)"; e.currentTarget.style.transform = ""; }}>
              {m.comingSoon && <div style={{ position: "absolute", top: 14, right: 14, fontSize: 9, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text3)", border: "1px solid var(--border)", borderRadius: 3, padding: "2px 6px" }}>Soon</div>}
              <div style={{ color: m.accent, marginBottom: 16 }}>{m.icon}</div>
              <div style={{ fontSize: 15, fontWeight: 500, color: "var(--text)", marginBottom: 6 }}>{m.label}</div>
              <div style={{ fontSize: 12, color: "var(--text3)", lineHeight: 1.6, marginBottom: 14 }}>{m.description}</div>
              {m.count !== undefined && <div style={{ fontSize: 11, fontFamily: "'DM Mono', monospace", color: m.accent }}>{m.count?.toLocaleString()} {m.countLabel}</div>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Ask AI View ───────────────────────────────────────────────────────────────

function NavDropdown({ label, items, currentView, onNavigate }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const openTimer = useRef(null);
  const closeTimer = useRef(null);

  const isActive = items.some(it => it.type === "item" && it.id === currentView);

  const scheduleOpen  = () => { clearTimeout(closeTimer.current); openTimer.current  = setTimeout(() => setOpen(true),  120); };
  const scheduleClose = () => { clearTimeout(openTimer.current);  closeTimer.current = setTimeout(() => setOpen(false), 180); };

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="nav-dropdown"
      onMouseEnter={scheduleOpen} onMouseLeave={scheduleClose}>
      <button
        className={`nav-dropdown-btn${isActive ? " active" : ""}${open ? " open" : ""}`}
        onClick={() => setOpen(o => !o)}>
        {label}
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {open && (
        <div className="nav-dropdown-menu" onMouseEnter={scheduleOpen} onMouseLeave={scheduleClose}>
          {items.map((item, i) => {
            if (item.type === "sep") return <div key={i} className="nav-dropdown-sep" />;
            if (item.disabled) return (
              <div key={item.id} className="nav-dropdown-item disabled">
                <span style={{ display: "flex", alignItems: "center", gap: 9 }}>{item.icon}{item.label}</span>
                <span className="nav-dropdown-soon">Soon</span>
              </div>
            );
            return (
              <button key={item.id}
                className={`nav-dropdown-item${item.id === currentView ? " active" : ""}`}
                onClick={() => { setOpen(false); onNavigate(item.id); }}>
                {item.icon}{item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────

export default function App() {
  const routerNav = useRouterNavigate();
  const location  = useLocation();
  const view = PATH_VIEWS[location.pathname] ?? "landing";

  const [externalDecision, setExternalDecision] = useState(null);
  const [searchKey, setSearchKey] = useState(0);
  const [headerQuery, setHeaderQuery] = useState("");
  const [graphSeed, setGraphSeed] = useState("");
  const [aaoGraphKey, setAaoGraphKey] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [theme, setTheme] = useState("light");
  const toggleTheme = () => setTheme(t => {
    const next = t === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    return next;
  });

  const goTo   = (id) => routerNav(VIEW_PATHS[id] ?? "/");
  const goHome = () => { setExternalDecision(null); setSearchKey(k => k + 1); routerNav("/"); };
  const navigate = (id) => { if (id === "landing") { goHome(); } else { goTo(id); } };
  const openDecision = (id, query = "", source = "balca") => { setExternalDecision({ id, query, source }); goTo(source === "aao" ? "aao" : "balca"); };
  const openFromSearchAll = (corpus, id, query) => {
    if (corpus === "balca") { setExternalDecision({ id, query, source: "balca" }); goTo("balca"); }
    else if (corpus === "aao") { setExternalDecision({ id, query, source: "aao" }); goTo("aao"); }
    else goTo(corpus === "regulation" ? "regulations" : "policy");
  };
  const openGraph    = (seed) => { setGraphSeed(seed); setSearchKey(k => k + 1); goTo("citation-graph"); };
  const openGraphAAO = (seed) => { setGraphSeed(seed); setAaoGraphKey(k => k + 1); goTo("aao-citation-graph"); };

  const handleHeaderSearch = (e) => {
    e.preventDefault();
    if (!headerQuery.trim()) return;
    setSearchKey(k => k + 1);
    goTo("search-all");
  };

  const icon = {
    file:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>,
    globe:  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>,
    book:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>,
    books:  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>,
    link:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>,
    tool:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 1 1 0 10h-2"/><line x1="8" y1="12" x2="16" y2="12"/></svg>,
    letter: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>,
    table:  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>,
    cal:    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>,
    folder: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>,
    chat:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
    home:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>,
    search: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>,
  };

  const dropdownGroups = [
    { label: "Case Law", items: [
      { type: "item", id: "balca",          label: "BALCA Decisions",    icon: icon.file  },
      { type: "item", id: "aao",            label: "AAO Decisions",      icon: icon.globe },
      { type: "sep" },
      { type: "item", id: "citation-graph", label: "Citation Graph",     icon: icon.link  },
      { type: "item", id: "aao-citation-graph", label: "AAO Citation Graph", icon: icon.link  },
    ]},
    { label: "Statutes & Regs", items: [
      { type: "item", id: "regulations",    label: "Regulations (CFR)",  icon: icon.book  },
      { type: "item", id: "policy",         label: "Policy Manuals",     icon: icon.books },
    ]},
    { label: "Tools", items: [
      { type: "item", id: "perm-comparer",  label: "PERM Comparer",      icon: icon.tool  },
      { type: "item", id: "perm-verify",    label: "PERM Verify",        icon: icon.tool  },
      { type: "item", id: "evl-compare",    label: "PWD / EVL Review",   icon: icon.letter },
      { type: "item", id: "applicant-eval", label: "Applicant Evaluation", icon: icon.tool },
      { type: "item", id: "wage-forecaster", label: "Upcoming Wage Estimator", icon: icon.cal },
      { type: "item", id: "wage-dashboard",   label: "July 1 Wage Comparer",    icon: icon.cal },
      { type: "item", id: "wage-level",       label: "Wage Level Tool",          icon: icon.tool },
      { type: "item", id: "soc-suggest",      label: "SOC Suggester",            icon: icon.tool },
      { type: "item", id: "ask",            label: "Ask AI",             icon: icon.tool  },
      { type: "sep" },
      { type: "item", id: "letter-assist",  label: "Letter Assist",      icon: icon.letter, disabled: true },
    ]},
    { label: "Data", items: [
      { type: "item", id: "oflc",           label: "DOL Data",           icon: icon.table },
      { type: "sep" },
      { type: "item", id: "eb-inventory",  label: "EB Inventory",       icon: icon.table },
    ]},
  ];

  const drawerGroups = [
    { section: null, items: [
      { id: "landing",        label: "Home",           icon: icon.home   },
    ]},
    { section: "Case Law", items: [
      { id: "balca",          label: "BALCA Decisions",icon: icon.file   },
      { id: "aao",            label: "AAO Decisions",  icon: icon.globe  },
      { id: "citation-graph", label: "Citation Graph", icon: icon.link   },
      { id: "aao-citation-graph", label: "AAO Citation Graph", icon: icon.link },
    ]},
    { section: "Statutes & Regs", items: [
      { id: "regulations",    label: "Regulations (CFR)", icon: icon.book  },
      { id: "policy",         label: "Policy Manuals",    icon: icon.books },
    ]},
    { section: "Tools", items: [
      { id: "perm-comparer",  label: "PERM Comparer",  icon: icon.tool   },
      { id: "perm-verify",    label: "PERM Verify",    icon: icon.tool   },
      { id: "evl-compare",    label: "PWD / EVL Review", icon: icon.letter },
      { id: "applicant-eval", label: "Applicant Evaluation", icon: icon.tool },
      { id: "wage-forecaster", label: "Upcoming Wage Estimator", icon: icon.cal },
      { id: "wage-level",     label: "Wage Level Tool", icon: icon.tool   },
      { id: "soc-suggest",    label: "SOC Suggester",  icon: icon.tool   },
    ]},
    { section: "Data", items: [
      { id: "oflc",           label: "DOL Data",       icon: icon.table  },      { id: "eb-inventory",   label: "EB Inventory",   icon: icon.table  },
    ]},
    { section: "Other", items: [
      { id: "visa-bulletin",  label: "Visa Bulletin",  icon: icon.cal    },
      { id: "projects",       label: "Projects",       icon: icon.folder },
    ]},
  ];

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", borderBottom: "1px solid var(--border)", padding: "0 16px", height: 46, flexShrink: 0, background: "var(--bg2)", gap: 8 }}>
        {/* Hamburger — mobile only */}
        <button className="mobile-hamburger" aria-label="Menu" onClick={() => setDrawerOpen(true)}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
        </button>

        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 7, flexShrink: 0, cursor: "pointer" }} onClick={goHome}>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--amber)" }} />
          <span style={{ fontSize: 14, fontWeight: 700, color: "var(--text)", fontFamily: "'DM Serif Display', serif" }}>Casebase</span>
        </div>

        {/* Persistent Search All */}
        <form className="header-search" onSubmit={handleHeaderSearch}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
          <input
            value={headerQuery}
            onChange={e => setHeaderQuery(e.target.value)}
            placeholder="Search all…"
            aria-label="Search all"
          />
          {headerQuery && (
            <button type="button" className="header-search-clear" onClick={() => setHeaderQuery("")} aria-label="Clear">×</button>
          )}
        </form>

        {/* Desktop grouped nav */}
        <nav className="desktop-nav" style={{ display: "flex", alignItems: "center", gap: 2 }}>
          {dropdownGroups.map(g => (
            <NavDropdown key={g.label} label={g.label} items={g.items} currentView={view} onNavigate={navigate} />
          ))}
          <button className={`nav-dropdown-btn${view === "visa-bulletin" ? " active" : ""}`}
            onClick={() => navigate("visa-bulletin")} style={{ gap: 6 }}>
            {icon.cal} Visa Bulletin
          </button>
        </nav>

        {/* Right icons */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 4 }}>
          {/* Projects folder — always visible */}
          <button className={`header-icon-btn${view === "projects" ? " active" : ""}`}
            onClick={() => navigate("projects")} title="Projects" aria-label="Projects">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          </button>
          {/* Kanban board */}
          <button className={`header-icon-btn${view === "kanban" ? " active" : ""}`}
            onClick={() => navigate("kanban")} title="Kanban" aria-label="Kanban board">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="18" rx="1"/><rect x="14" y="3" width="7" height="11" rx="1"/></svg>
          </button>
          {/* Ask AI */}
          <button className={`header-icon-btn${view === "ask" ? " active" : ""}`}
            onClick={() => navigate("ask")} title="Ask AI" aria-label="Ask AI">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </button>
          {/* Theme toggle */}
          <button className="header-icon-btn" onClick={toggleTheme} title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} aria-label="Toggle theme">
            {theme === "dark"
              ? <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
              : <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
            }
          </button>
        </div>
      </div>

      {/* ── Mobile drawer ── */}
      {drawerOpen && (
        <div className="mobile-drawer-overlay" onClick={() => setDrawerOpen(false)}>
          <div className="mobile-drawer" onClick={e => e.stopPropagation()}>
            <div className="mobile-drawer-header">
              <div className="mobile-drawer-logo">
                <div style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--amber)" }} />
                Casebase
              </div>
              <button className="mobile-drawer-close" onClick={() => setDrawerOpen(false)} aria-label="Close menu">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            {drawerGroups.map((g, gi) => (
              <div key={gi}>
                {g.section && <div className="mobile-drawer-section">{g.section}</div>}
                {g.items.map(item => (
                  <button key={item.id}
                    className={`mobile-drawer-item${view === item.id ? " active" : ""}`}
                    onClick={() => { navigate(item.id); setDrawerOpen(false); }}>
                    {item.icon}{item.label}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Main content ── */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        {view === "landing" && <LandingPage onNavigate={navigate} />}
        {view === "balca" && <SearchView key={`balca-${searchKey}`} externalDecisionId={externalDecision?.source === "balca" ? externalDecision?.id : null} externalQuery={externalDecision?.source === "balca" ? externalDecision?.query : null} onViewGraph={openGraph} />}
        {view === "aao" && <AAOSearchView key={`aao-${searchKey}`} externalDecisionId={externalDecision?.source === "aao" ? externalDecision?.id : null} externalQuery={externalDecision?.source === "aao" ? externalDecision?.query : null} onViewGraph={openGraphAAO} />}
        {view === "search-all" && <SearchAllView key={`search-all-${searchKey}`} onNavigate={openFromSearchAll} initialQuery={headerQuery} />}
        {view === "regulations" && <RegulationsView />}
        {view === "policy" && <PolicyView />}
        {view === "citation-graph" && <CitationGraphView key={`graph-${searchKey}`} onNavigate={(id) => { setExternalDecision({ id, query: "", source: "balca" }); goTo("balca"); }} initialQuery={graphSeed} />}
        {view === "aao-citation-graph" && <AAOCitationGraphView key={`aao-graph-${aaoGraphKey}`} onNavigate={(id) => { setExternalDecision({ id, query: "", source: "aao" }); goTo("aao"); }} onOpenPrecedent={(id) => { setExternalDecision({ id, query: "", source: "aao" }); goTo("aao"); }} initialQuery={graphSeed} />}
        {view === "ask" && <AskView onNavigate={(corpus, id) => { if (corpus === "balca") { setExternalDecision({ id, query: "", source: "balca" }); goTo("balca"); } else if (corpus === "aao") { setExternalDecision({ id, query: "", source: "aao" }); goTo("aao"); } else if (corpus === "regulation") { goTo("regulations"); } else if (corpus === "policy") { goTo("policy"); } }} />}
        {view === "perm-comparer" && <PermComparer />}
        {view === "perm-verify" && <PermVerifyView />}
        {view === "evl-compare" && <EvlCompareView />}
        {view === "applicant-eval" && <ApplicantEvalView />}
        {view === "visa-bulletin" && <VisaBulletinView />}
        {view === "wage-forecaster" && <WageForecaster />}
        {view === "wage-dashboard"  && <WageDashboard />}
        {view === "wage-level" && <WageLevelView />}
        {view === "soc-suggest" && <SocSuggestView />}
        {view === "eb-inventory" && <EbInventoryView />}
        {view === "projects" && <ProjectsView onOpenDecision={openDecision} />}
        {view === "oflc" && <OflcView />}
        {view === "processing-times" && <ProcessingTimesView onBack={goHome} backLabel="Casebase home" />}
        {view === "kanban" && <KanbanView />}
      </div>
    </div>
  );
}
