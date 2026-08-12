import { useState, useEffect, useRef } from "react";
import { useNavigate as useRouterNavigate, useLocation } from "react-router-dom";
import { icon, MODULES_BY_ID, CARD_SECTIONS, VIEW_PATHS, PATH_VIEWS, LEGACY_PATHS, dropdownGroups, drawerGroups } from "./modules";
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
import { WageDashboard } from "./WageDashboard";
import { SocWageView } from "./SocWageView";
import { EbInventoryView } from "./EbInventoryView";
import { ProcessingTimesView } from "./ProcessingTimesView";

function LandingPage({ onNavigate }) {
  const { data: stats } = useFetch(`${API}/stats`);
  const { data: aaoStats } = useFetch(`${API}/aao/stats`);

  // Landing cards derive from the module registry; grouping and order come
  // from CARD_SECTIONS. Card content (label/description/icon/accent) is
  // unchanged from the flat layout.
  const counts = {
    balca: stats?.total_decisions,
    aao:   aaoStats?.total_decisions,
  };
  const card = (m) => ({
    id: m.id,
    label: m.card.label ?? m.label,
    description: m.card.description,
    accent: m.card.accent,
    accentDim: m.card.accentDim,
    icon: m.card.icon,
    count: m.card.countKey ? counts[m.card.countKey] : undefined,
    countLabel: m.card.countLabel,
    available: !m.comingSoon,
    comingSoon: m.comingSoon,
  });
  const sections = CARD_SECTIONS.map(s => ({
    ...s,
    cards: s.ids.map(id => MODULES_BY_ID[id]).filter(m => m?.card).map(card),
  }));

  return (
    <div className="grid-bg" style={{ height: "100%", overflowY: "auto" }}>
      <div style={{ maxWidth: 960, margin: "0 auto", padding: "48px 32px 64px" }}>
        <div style={{ marginBottom: 44, textAlign: "center" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, marginBottom: 12 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--amber)" }} />
            <span style={{ fontFamily: "'DM Serif Display', serif", fontSize: 36, color: "var(--text)", letterSpacing: "-0.01em" }}>Casebase</span>
          </div>
          <p style={{ fontSize: 15, color: "var(--text3)", maxWidth: 520, margin: "0 auto" }}>Immigration law research — decisions, regulations, policy, and AI-assisted drafting</p>
        </div>
        {sections.map(s => (
          <div key={s.label} style={{ marginBottom: 36 }}>
            <div className="landing-section-label">
              <span className="landing-section-dot" style={{ background: s.accent }} />
              {s.label}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
              {s.cards.map(m => (
                <div key={m.id} onClick={() => m.available && onNavigate(m.id)}
                  className={`landing-card${m.available ? " clickable" : ""}`}
                  style={{ padding: "24px", cursor: m.available ? "pointer" : "default",
                    opacity: m.available ? 1 : 0.55, position: "relative",
                    "--card-accent": m.accent, "--card-accent-dim": m.accentDim }}>
                  {m.comingSoon && <div style={{ position: "absolute", top: 14, right: 14, fontSize: 9, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text3)", border: "1px solid var(--border)", borderRadius: 3, padding: "2px 6px" }}>Soon</div>}
                  <div style={{ color: m.accent, marginBottom: 16 }}>{m.icon}</div>
                  <div style={{ fontSize: 15, fontWeight: 500, color: "var(--text)", marginBottom: 6 }}>{m.label}</div>
                  <div style={{ fontSize: 12, color: "var(--text3)", lineHeight: 1.6, marginBottom: 14 }}>{m.description}</div>
                  {m.count !== undefined && <div style={{ fontSize: 11, fontFamily: "'DM Mono', monospace", color: m.accent }}>{m.count?.toLocaleString()} {m.countLabel}</div>}
                </div>
              ))}
            </div>
          </div>
        ))}
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

  // Retired-tool paths redirect to their replacement
  useEffect(() => {
    const to = LEGACY_PATHS[location.pathname];
    if (to) routerNav(to, { replace: true });
  }, [location.pathname, routerNav]);

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
        {view === "wage-dashboard"  && <WageDashboard />}
        {view === "soc-wage" && <SocWageView />}
        {view === "eb-inventory" && <EbInventoryView />}
        {view === "projects" && <ProjectsView onOpenDecision={openDecision} />}
        {view === "oflc" && <OflcView />}
        {view === "processing-times" && <ProcessingTimesView onBack={goHome} backLabel="Casebase home" />}
        {view === "kanban" && <KanbanView />}
      </div>
    </div>
  );
}
