import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import "./index.css";
import { VisaBulletinView } from "./VisaBulletinView";
import { OflcView } from "./OflcView";
import { API } from "./apiBase";

const OUTCOME = {
  Affirmed:  { bg: "var(--green-dim)",  text: "var(--green)",  dot: "#34d399" },
  Reversed:  { bg: "var(--red-dim)",    text: "var(--red)",    dot: "#f87171" },
  Remanded:  { bg: "var(--yellow-dim)", text: "#fbbf24",       dot: "#fbbf24" },
  Dismissed: { bg: "var(--bg4)",        text: "var(--text2)",  dot: "#5a5a68" },
};

function Badge({ label, small }) {
  const c = OUTCOME[label] || { bg: "var(--bg4)", text: "var(--text2)", dot: "#5a5a68" };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, background: c.bg, color: c.text, fontSize: small ? 10 : 11, fontWeight: 500, padding: small ? "2px 6px" : "3px 8px", borderRadius: 4, letterSpacing: "0.03em" }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: c.dot, flexShrink: 0 }} />
      {label}
    </span>
  );
}

// ── Read Later hover popup ────────────────────────────────────────────────────
function ReadLaterPopup({ caseNumber, caseId, caseSource, fromCaseNumber, fromSource, onNavigate, children }) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState(null);
  const [saved, setSaved] = useState([]); // pc_ids saved to read_later in any project
  const [saving, setSaving] = useState(null);
  const timerRef = useRef(null);
  const ref = useRef(null);

  const load = async () => {
    const all = await fetch(`${API}/projects`).then(r => r.json());
    setProjects(all);
    // Check which projects already have this case in read_later
    const checks = await Promise.all(
      all.map(p =>
        fetch(`${API}/projects/${p.id}/read-later`)
          .then(r => r.ok ? r.json() : [])
          .then(items => Array.isArray(items) ? items.filter(i =>
            (caseSource === 'balca' && i.decision_id === caseId) ||
            (caseSource === 'aao'   && i.aao_decision_id === caseId)
          ).map(i => ({ pcId: i.pc_id, projectId: p.id })) : [])
      )
    );
    setSaved(checks.flat());
  };

  const show = () => {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => { setOpen(true); load(); }, 350);
  };
  const hide = () => {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setOpen(false), 200);
  };
  const stayOpen = () => clearTimeout(timerRef.current);

  const toggle = async (project) => {
    setSaving(project.id);
    const existing = saved.find(s => s.projectId === project.id);
    if (existing) {
      await fetch(`${API}/projects/${project.id}/read-later/${existing.pcId}`, { method: "DELETE" });
      setSaved(s => s.filter(x => x.projectId !== project.id));
    } else {
      const body = {
        source: caseSource,
        saved_from_case_number: fromCaseNumber,
        saved_from_source: fromSource,
      };
      if (caseSource === 'balca') body.decision_id = caseId;
      else body.aao_decision_id = caseId;
      const res = await fetch(`${API}/projects/${project.id}/read-later`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(r => r.json());
      if (res.id) setSaved(s => [...s, { pcId: res.id, projectId: project.id }]);
    }
    setSaving(null);
  };

  const isAnySaved = saved.length > 0;

  return (
    <span ref={ref} style={{ position: "relative", display: "inline" }}
      onMouseEnter={show} onMouseLeave={hide}>
      {children}
      {open && (
        <span onMouseEnter={stayOpen} onMouseLeave={hide}
          style={{
            position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 300,
            background: "var(--bg2)", border: "1px solid var(--border2)",
            borderRadius: "var(--radius-lg)", minWidth: 230,
            boxShadow: "0 8px 24px #00000055",
            display: "flex", flexDirection: "column",
            animation: "fadeUp 0.12s ease",
            // prevent text selection / pre-wrap bleed
            whiteSpace: "normal", fontFamily: "inherit", fontSize: 12,
          }}>
          {/* Case header */}
          <span style={{ padding: "10px 13px 6px", display: "flex", alignItems: "center", gap: 8, borderBottom: "1px solid var(--border)" }}>
            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: caseSource === 'aao' ? "var(--blue)" : "var(--amber)", fontWeight: 600 }}>{caseNumber}</span>
            <span onClick={() => { onNavigate(caseId); setOpen(false); }}
              style={{ marginLeft: "auto", fontSize: 11, color: "var(--text3)", cursor: "pointer", textDecoration: "underline" }}>
              open
            </span>
          </span>
          {/* Saved-from context */}
          {fromCaseNumber && (
            <span style={{ padding: "5px 13px 4px", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace", borderBottom: "1px solid var(--border)" }}>
              while reading {fromCaseNumber}
            </span>
          )}
          {/* Project list */}
          <span style={{ padding: "6px 13px 4px", fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Save to Read Later
          </span>
          {projects === null && <span style={{ padding: "8px 13px" }}><Spinner /></span>}
          {projects?.length === 0 && (
            <span style={{ padding: "6px 13px 10px", fontSize: 12, color: "var(--text3)", display: "block" }}>No projects yet.</span>
          )}
          {projects?.map(p => {
            const inProject = saved.some(s => s.projectId === p.id);
            return (
              <span key={p.id} onClick={() => toggle(p)}
                style={{ padding: "7px 13px", cursor: "pointer", display: "flex", alignItems: "center", gap: 9, opacity: saving === p.id ? 0.5 : 1, background: inProject ? "var(--bg3)" : "transparent" }}
                onMouseEnter={e => { if (!inProject) e.currentTarget.style.background = "var(--bg3)"; }}
                onMouseLeave={e => { if (!inProject) e.currentTarget.style.background = "transparent"; }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: p.color, flexShrink: 0, display: "inline-block" }} />
                <span style={{ fontSize: 12, flex: 1, color: "var(--text)" }}>{p.name}</span>
                {inProject && (
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                )}
              </span>
            );
          })}
          <span style={{ borderTop: "1px solid var(--border)", padding: "6px 13px 8px", fontSize: 10, color: "var(--text3)", display: "block" }}>
            {isAnySaved ? `In ${saved.length} project read later` : "Hover a linked case to save"}
          </span>
        </span>
      )}
    </span>
  );
}

// ── In-document search ────────────────────────────────────────────────────────
function useDocSearch() {
  const [docQ, setDocQ] = useState("");
  const [activeDocQ, setActiveDocQ] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);
  const [matchCount, setMatchCount] = useState(0);
  const [open, setOpen] = useState(false);
  const inputRef = useRef(null);
  const matchRefs = useRef([]);

  const commit = (term) => {
    setActiveDocQ(term);
    setMatchIndex(0);
  };

  const toggle = () => {
    setOpen(o => {
      if (!o) setTimeout(() => inputRef.current?.focus(), 40);
      else { setDocQ(""); setActiveDocQ(""); setMatchCount(0); setMatchIndex(0); }
      return !o;
    });
  };

  const close = () => {
    setOpen(false); setDocQ(""); setActiveDocQ(""); setMatchCount(0); setMatchIndex(0);
  };

  const next = () => setMatchIndex(i => matchCount ? (i + 1) % matchCount : 0);
  const prev = () => setMatchIndex(i => matchCount ? (i - 1 + matchCount) % matchCount : 0);

  // Scroll active match into view whenever index or count changes
  useEffect(() => {
    const el = matchRefs.current[matchIndex];
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [matchIndex, matchCount]);

  // Register a ref for each match span (called during render)
  const registerRef = (idx, el) => { matchRefs.current[idx] = el; };

  // Reset match tracking when new doc loads
  const resetMatches = (count) => {
    matchRefs.current = new Array(count);
    setMatchCount(count);
    setMatchIndex(0);
  };

  return { docQ, setDocQ, activeDocQ, commit, matchIndex, matchCount,
           resetMatches, registerRef, open, toggle, close, next, prev, inputRef };
}

function InDocSearch({ hook, accentColor = "var(--amber)" }) {
  const { docQ, setDocQ, activeDocQ, commit, matchIndex, matchCount,
          open, toggle, close, next, prev, inputRef } = hook;

  // Keyboard shortcuts: Escape to close, Enter/Shift+Enter to navigate
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (e.key === "Escape") { close(); }
      else if (e.key === "Enter") { e.shiftKey ? prev() : next(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, matchCount]);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
      {open && (
        <div style={{ display: "flex", alignItems: "center", gap: 5, animation: "fadeUp 0.12s ease" }}>
          <div style={{ position: "relative" }}>
            <input
              ref={inputRef}
              value={docQ}
              onChange={e => { setDocQ(e.target.value); commit(e.target.value); }}
              onKeyDown={e => {
                if (e.key === "Enter") { e.shiftKey ? prev() : next(); }
                if (e.key === "Escape") close();
              }}
              placeholder="Find in document…"
              style={{ fontSize: 12, height: 30, width: 200, paddingRight: activeDocQ ? 60 : 8 }}
            />
            {activeDocQ && (
              <span style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)",
                fontSize: 10, color: matchCount > 0 ? accentColor : "var(--red)",
                fontFamily: "'DM Mono', monospace", pointerEvents: "none" }}>
                {matchCount > 0 ? `${matchIndex + 1}/${matchCount}` : "0"}
              </span>
            )}
          </div>
          <button onClick={prev} disabled={matchCount === 0}
            style={{ width: 26, height: 26, padding: 0, fontSize: 12, opacity: matchCount ? 1 : 0.3,
              display: "flex", alignItems: "center", justifyContent: "center" }}
            title="Previous (Shift+Enter)">↑</button>
          <button onClick={next} disabled={matchCount === 0}
            style={{ width: 26, height: 26, padding: 0, fontSize: 12, opacity: matchCount ? 1 : 0.3,
              display: "flex", alignItems: "center", justifyContent: "center" }}
            title="Next (Enter)">↓</button>
          <button onClick={close}
            style={{ width: 26, height: 26, padding: 0, fontSize: 14, lineHeight: 1,
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--text3)", background: "none", border: "1px solid var(--border)" }}>×</button>
        </div>
      )}
      <button onClick={toggle}
        style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11,
          padding: "4px 10px", height: "auto",
          background: open ? `${accentColor}22` : "var(--bg3)",
          color: open ? accentColor : "var(--text3)",
          border: open ? `1px solid ${accentColor}44` : "1px solid var(--border)",
          borderRadius: "var(--radius)" }}
        title="Find in document (⌘F)">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
        </svg>
        Find
      </button>
    </div>
  );
}

// Helper: render text with doc-search highlights
function HighlightedText({ text, activeDocQ, matchIndex, resetMatches, registerRef }) {
  const ps = {
    fontFamily: "'DM Mono', monospace", fontSize: 12, lineHeight: 1.8,
    whiteSpace: "pre-wrap", wordBreak: "break-word",
    padding: "20px 28px", color: "var(--text2)",
  };

  const escaped = activeDocQ?.trim()
    ? activeDocQ.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    : null;

  const parts = escaped
    ? text.split(new RegExp(`(${escaped})`, "gi"))
    : null;

  const counted = parts ? parts.filter((_, i) => i % 2 === 1).length : 0;

  useEffect(() => { resetMatches(counted); }, [activeDocQ, counted]);

  if (!escaped) return <pre style={ps}>{text}</pre>;

  let localIdx = 0;
  return (
    <pre style={ps}>
      {parts.map((part, i) => {
        if (i % 2 === 0) return part;
        const idx = localIdx++;
        const isActive = idx === matchIndex;
        return (
          <mark key={i}
            ref={el => registerRef(idx, el)}
            style={{
              background: isActive ? "#f59e0b" : "#f59e0b44",
              color: isActive ? "#000" : "inherit",
              borderRadius: 2,
              outline: isActive ? "2px solid #f59e0b" : "none",
            }}>
            {part}
          </mark>
        );
      })}
    </pre>
  );
}

function RegBadge({ label }) {
  return <span style={{ background: "var(--amber-dim)", color: "var(--amber)", border: "1px solid #f59e0b33", fontSize: 10, fontWeight: 500, padding: "2px 7px", borderRadius: 4 }}>{label}</span>;
}

function useFetch(url) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!url) return;
    setLoading(true); setData(null);
    fetch(url).then(r => r.json()).then(d => { setData(d); setLoading(false); }).catch(() => setLoading(false));
  }, [url]);
  return { data, loading };
}

function Spinner() {
  return (
    <div style={{ padding: "40px 20px", display: "flex", justifyContent: "center" }}>
      <div style={{ width: 20, height: 20, border: "2px solid var(--border2)", borderTopColor: "var(--amber)", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// ── Search view — owns all search + detail state ──────────────────────────────
function SearchView({ externalDecisionId, externalQuery, onViewGraph }) {
  const [q, setQ] = useState("");
  // Basic visible filters
  const [outcome, setOutcome] = useState("");
  // Advanced filters
  const [regulation, setReg] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [employer, setEmployer] = useState("");
  const [caseNumber, setCaseNumber] = useState("");
  const [panel, setPanel] = useState("");
  const [hasCitations, setHasCitations] = useState("");
  const [hasRegulations, setHasRegulations] = useState("");
  const [includeDocketing, setIncludeDocketing] = useState(false);
  const [sortBy, setSortBy] = useState("relevance");
  const [advOpen, setAdvOpen] = useState(false);

  const [page, setPage] = useState(1);
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [selectedId, setSelectedId] = useState(externalDecisionId || null);
  const [activeQuery, setActiveQuery] = useState("");
  const inputRef = useRef(null);

  useEffect(() => { if (!searched) inputRef.current?.focus(); }, [searched]);
  useEffect(() => {
    if (externalDecisionId) {
      setSelectedId(externalDecisionId);
      setSearched(true);
      if (externalQuery !== undefined) setActiveQuery(externalQuery || "");
    }
  }, [externalDecisionId, externalQuery]);

  const advancedCount = [regulation, dateFrom, dateTo, employer, caseNumber, panel, hasCitations, hasRegulations]
    .filter(Boolean).length + (sortBy !== "relevance" ? 1 : 0);

  const clearAdvanced = () => {
    setReg(""); setDateFrom(""); setDateTo(""); setEmployer("");
    setCaseNumber(""); setPanel(""); setHasCitations(""); setHasRegulations(""); setIncludeDocketing(false); setSortBy("relevance");
  };

  const search = useCallback(async (pg = 1) => {
    setLoading(true); setSearched(true); setSelectedId(null);
    const p = new URLSearchParams({ page: pg, page_size: 20 });
    if (q) p.set("q", q);
    if (outcome) p.set("outcome", outcome);
    if (regulation) p.set("regulation", regulation);
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    if (employer) p.set("employer", employer);
    if (caseNumber) p.set("case_number", caseNumber);
    if (panel) p.set("panel", panel);
    if (hasCitations) p.set("has_citations", hasCitations);
    if (hasRegulations) p.set("has_regulations", hasRegulations);
    if (includeDocketing) p.set("include_docketing_notices", "true");
    if (sortBy !== "relevance") p.set("sort_by", sortBy);
    try {
      const res = await fetch(`${API}/search?${p}`);
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      setResults(data); setPage(pg);
      setActiveQuery(q);
    } catch (err) {
      console.error("Search failed:", err);
      setResults({ total: 0, page: pg, page_size: 20, results: [], error: err.message });
    } finally {
      setLoading(false);
    }
  }, [q, outcome, regulation, dateFrom, dateTo, employer, caseNumber, panel, hasCitations, hasRegulations, includeDocketing, sortBy]);

  const splitView = selectedId && (searched || !!externalDecisionId);

  return (
    <div className="search-view-root" style={{ height: "100%", display: "flex", overflow: "hidden" }}>

      {/* ── Left panel ── */}
      <div className="search-list-panel" style={{
        display: "flex", flexDirection: "column", overflow: "hidden",
        width: splitView ? 340 : "100%", flexShrink: 0,
        borderRight: splitView ? "1px solid var(--border)" : "none",
        transition: "width 0.25s ease",
      }}>

        {/* Search bar area */}
        <div style={{
          padding: searched ? "12px 16px" : "0",
          flex: searched ? "0 0 auto" : "1",
          display: "flex", flexDirection: "column",
          justifyContent: searched ? "flex-start" : "center",
          alignItems: "center",
          borderBottom: searched ? "1px solid var(--border)" : "none",
        }}>
          {!searched && (
            <div style={{ marginBottom: 28, textAlign: "center" }}>
              <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 28, color: "var(--text)", marginBottom: 6 }}>BALCA Research</div>
              <div style={{ fontSize: 13, color: "var(--text3)" }}>7,334 decisions indexed</div>
            </div>
          )}

          <div style={{ width: "100%", maxWidth: searched ? "100%" : 680, padding: searched ? 0 : "0 24px" }}>
            {/* Main search row */}
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <div style={{ position: "relative", flex: 1 }}>
                <svg style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text3)", pointerEvents: "none" }} width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                </svg>
                <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && search(1)}
                  placeholder={searched ? "New search… (use \"quotes\" -exclude OR)" : "Search opinions, employers, regulations… (use \"quotes\" -exclude OR)"}
                  style={{ paddingLeft: 30, fontSize: searched ? 13 : 14, height: searched ? 36 : 42 }} />
              </div>
              <button onClick={() => search(1)} className="primary" style={{ height: searched ? 36 : 42, padding: "0 14px", fontSize: searched ? 13 : 14 }}>Search</button>
            </div>

            {/* Quick filters row */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              {/* Outcome pills */}
              {["Affirmed","Reversed","Remanded","Dismissed"].map(o => (
                <button key={o} onClick={() => setOutcome(outcome === o ? "" : o)} style={{
                  fontSize: 11, padding: "3px 10px", height: "auto",
                  background: outcome === o ? OUTCOME[o].bg : "var(--bg3)",
                  color: outcome === o ? OUTCOME[o].text : "var(--text3)",
                  border: outcome === o ? `1px solid ${OUTCOME[o].dot}44` : "1px solid var(--border)",
                  borderRadius: 20, fontWeight: outcome === o ? 500 : 400,
                  transition: "all 0.12s",
                }}>{o}</button>
              ))}

              <div style={{ flex: 1 }} />

              {/* Advanced toggle */}
              <button onClick={() => setAdvOpen(o => !o)} style={{
                fontSize: 11, padding: "3px 10px", height: "auto",
                background: advOpen || advancedCount > 0 ? "var(--amber-dim)" : "var(--bg3)",
                color: advOpen || advancedCount > 0 ? "var(--amber)" : "var(--text3)",
                border: advOpen || advancedCount > 0 ? "1px solid #f59e0b44" : "1px solid var(--border)",
                borderRadius: 20, display: "flex", alignItems: "center", gap: 5,
              }}>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="4" y1="6" x2="20" y2="6"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="11" y1="18" x2="13" y2="18"/>
                </svg>
                Advanced{advancedCount > 0 ? ` (${advancedCount})` : ""}
              </button>
            </div>

            {/* Advanced search drawer */}
            {advOpen && (
              <div style={{ marginTop: 10, padding: "14px 16px", background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", animation: "fadeUp 0.15s ease" }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>Advanced Search</div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
                  <div>
                    <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Case number</label>
                    <input value={caseNumber} onChange={e => setCaseNumber(e.target.value)} placeholder="e.g. 2020-PER-00123" style={{ fontSize: 12 }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Employer name</label>
                    <input value={employer} onChange={e => setEmployer(e.target.value)} placeholder="Partial match" style={{ fontSize: 12 }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Regulation citation</label>
                    <input value={regulation} onChange={e => setReg(e.target.value)} placeholder="e.g. 656.17" style={{ fontSize: 12 }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Panel / judge</label>
                    <input value={panel} onChange={e => setPanel(e.target.value)} placeholder="e.g. Vittone" style={{ fontSize: 12 }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Date from</label>
                    <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} style={{ fontSize: 12 }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Date to</label>
                    <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} style={{ fontSize: 12 }} />
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 12 }}>
                  <div>
                    <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Sort by</label>
                    <select value={sortBy} onChange={e => setSortBy(e.target.value)} style={{ fontSize: 12 }}>
                      <option value="relevance">Relevance</option>
                      <option value="date_desc">Newest first</option>
                      <option value="date_asc">Oldest first</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Has linked citations</label>
                    <select value={hasCitations} onChange={e => setHasCitations(e.target.value)} style={{ fontSize: 12 }}>
                      <option value="">Any</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Has regulations</label>
                    <select value={hasRegulations} onChange={e => setHasRegulations(e.target.value)} style={{ fontSize: 12 }}>
                      <option value="">Any</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  </div>
                </div>

                <div style={{ marginBottom: 12 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text2)", cursor: "pointer", userSelect: "none" }}>
                    <input type="checkbox" checked={includeDocketing} onChange={e => setIncludeDocketing(e.target.checked)} />
                    Include docketing notices
                    <span style={{ fontSize: 11, color: "var(--text3)" }}>(672 procedural notices hidden by default)</span>
                  </label>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <button onClick={clearAdvanced} style={{ fontSize: 11, color: "var(--text3)", background: "none", border: "none", padding: 0, cursor: "pointer" }}>
                    Clear all
                  </button>
                  <button onClick={() => { search(1); setAdvOpen(false); }} className="primary" style={{ fontSize: 12, padding: "6px 16px" }}>
                    Apply &amp; search
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Results list */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && <Spinner />}
          {!loading && searched && results && (
            <>
              <div style={{ padding: splitView ? "6px 12px" : "8px 24px", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace", letterSpacing: "0.05em" }}>
                {results.total?.toLocaleString()} DECISIONS
              </div>
              {results.results?.map((r, i) => (
                <ResultRow key={r.id} row={r} selected={r.id === selectedId} compact={splitView}
                  onSelect={() => setSelectedId(r.id)} index={i} activeQuery={activeQuery} />
              ))}
              {results.total > 20 && (
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: splitView ? "10px 12px" : "14px 24px", borderTop: "1px solid var(--border)" }}>
                  <button onClick={() => search(page - 1)} disabled={page <= 1} style={{ opacity: page <= 1 ? 0.3 : 1, fontSize: 12 }}>←</button>
                  <span style={{ flex: 1, textAlign: "center", fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
                    {page} / {Math.ceil(results.total / 20)}
                  </span>
                  <button onClick={() => search(page + 1)} disabled={page * 20 >= results.total} style={{ opacity: page * 20 >= results.total ? 0.3 : 1, fontSize: 12 }}>→</button>
                </div>
              )}
              {results.results?.length === 0 && (
                <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text3)", fontSize: 13 }}>No decisions found.</div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Right panel: decision detail ── */}
      {splitView && (
        <div className="search-detail-panel" style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", animation: "fadeUp 0.18s ease" }}>
          <DecisionDetail
            decisionId={selectedId}
            query={activeQuery}
            onNavigate={(id) => setSelectedId(id)}
            onViewGraph={onViewGraph}
          />
        </div>
      )}
    </div>
  );
}

function ResultRow({ row, onSelect, selected, compact, index, activeQuery }) {
  return (
    <div className="fade-up"
      style={{
        padding: compact ? "10px 12px" : "14px 24px",
        borderBottom: "1px solid var(--border)",
        borderLeft: selected ? "2px solid var(--amber)" : "2px solid transparent",
        cursor: "pointer",
        background: selected ? "var(--bg3)" : "transparent",
        animationDelay: `${index * 20}ms`,
        transition: "background 0.1s",
        position: "relative",
      }}
      onMouseEnter={e => { if (!selected) e.currentTarget.style.background = "var(--bg2)"; }}
      onMouseLeave={e => { if (!selected) e.currentTarget.style.background = "transparent"; }}
    >
      <div onClick={onSelect}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
          <span style={{ fontFamily: "'DM Mono', monospace", fontSize: compact ? 10 : 11, color: selected ? "var(--amber)" : "var(--text3)", letterSpacing: "0.02em" }}>{row.case_number}</span>
          {row.outcome && <Badge label={row.outcome} small />}
          {!compact && row.regulation_count > 0 && <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{row.regulation_count}§</span>}
        </div>
        {row.employer_name && (
          <div style={{ fontSize: compact ? 12 : 14, fontWeight: 500, color: "var(--text)", marginBottom: 2, fontFamily: compact ? "inherit" : "'DM Serif Display', serif", lineHeight: 1.3 }}>
            {row.employer_name}
          </div>
        )}
        {!compact && row.job_title && <div style={{ fontSize: 12, color: "var(--text2)", marginBottom: 4 }}>{row.job_title}</div>}
        {!compact && row.headline && <div style={{ fontSize: 11, color: "var(--text3)", lineHeight: 1.6, marginTop: 4 }} dangerouslySetInnerHTML={{ __html: row.headline }} />}
        {row.decision_date && <div style={{ fontSize: 10, color: "var(--text3)", marginTop: compact ? 2 : 6, fontFamily: "'DM Mono', monospace" }}>{row.decision_date}</div>}
      </div>
      {!compact && (
        <div style={{ marginTop: 8 }} onClick={e => e.stopPropagation()}>
          <SaveToProject decisionId={row.id} searchQuery={activeQuery} small />
        </div>
      )}
    </div>
  );
}

// ── Decision detail ───────────────────────────────────────────────────────────
function DecisionDetail({ decisionId, query, onNavigate, onViewGraph }) {
  const { data, loading } = useFetch(decisionId ? `${API}/decisions/${decisionId}` : null);
  const [activeTab, setActiveTab] = useState("text");
  const [newNote, setNewNote] = useState("");
  const [notes, setNotes] = useState(null);
  const firstMatchRef = useRef(null);
  const contentRef = useRef(null);
  const docSearch = useDocSearch();

  useEffect(() => { if (data) { setNotes(data.notes); setActiveTab("text"); docSearch.close(); } }, [data]);

  useEffect(() => {
    if (activeTab === "text" && firstMatchRef.current) {
      setTimeout(() => firstMatchRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 120);
    }
  }, [activeTab, data]);

  const [citeMap, setCiteMap] = useState({});
  useEffect(() => {
    if (!decisionId) return;
    fetch(`${API}/decisions/${decisionId}/citation-map`)
      .then(r => r.json()).then(setCiteMap).catch(() => {});
  }, [decisionId]);

  if (loading) return <Spinner />;
  if (!data) return null;

  const addNote = async () => {
    if (!newNote.trim()) return;
    const res = await fetch(`${API}/decisions/${decisionId}/notes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: newNote }) });
    const n = await res.json();
    setNotes(prev => [n, ...prev]); setNewNote("");
  };
  const deleteNote = async (id) => {
    await fetch(`${API}/notes/${id}`, { method: "DELETE" });
    setNotes(prev => prev.filter(n => n.id !== id));
  };

  const tabs = [
    { id: "text", label: "Opinion" },
    { id: "regulations", label: "Regulations", count: data.regulations?.length },
    { id: "citations", label: "Citations", count: (data.citations_made?.length || 0) + (data.cited_by?.length || 0) },
    { id: "notes", label: "Notes", count: (notes || []).length },
  ];

  const renderOpinion = () => {
    const text = data.full_text || "No text extracted.";
    const ps = { fontFamily: "'DM Mono', monospace", fontSize: 12, lineHeight: 1.8, whiteSpace: "pre-wrap", wordBreak: "break-word", padding: "20px 28px", color: "var(--text2)" };

    // ── In-document search mode ──────────────────────────────────────────
    if (docSearch.activeDocQ?.trim()) {
      return (
        <HighlightedText
          text={text}
          activeDocQ={docSearch.activeDocQ}
          matchIndex={docSearch.matchIndex}
          resetMatches={docSearch.resetMatches}
          registerRef={docSearch.registerRef}
        />
      );
    }

    // ── Normal mode (citation links + external query highlights) ─────────
    const terms = query?.trim() ? query.trim().split(/\s+/).filter(t => t.length > 2) : [];
    const caseNumPat = String.raw`\d{4}-PER-\d{4,6}`;
    const termPats = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const allPats = termPats.length ? [caseNumPat, ...termPats] : [caseNumPat];
    const splitPat = new RegExp(`(${allPats.join("|")})`, "gi");
    const caseOnlyPat = new RegExp(`^${caseNumPat}$`, "i");
    const termPat = terms.length ? new RegExp(`^(${termPats.join("|")})$`, "gi") : null;
    const parts = text.split(splitPat);
    let firstMark = false;

    return (
      <pre style={ps}>
        {parts.map((part, i) => {
          if (caseOnlyPat.test(part)) {
            const linkedId = citeMap[part.toUpperCase()] || citeMap[part];
            if (linkedId) {
              return (
                <ReadLaterPopup key={i}
                  caseNumber={part} caseId={linkedId} caseSource="balca"
                  fromCaseNumber={data.case_number} fromSource="balca"
                  onNavigate={onNavigate}>
                  <span
                    onClick={() => onNavigate(linkedId)}
                    style={{ color: "var(--amber)", textDecoration: "underline", textDecorationColor: "var(--amber-dim)", cursor: "pointer", fontWeight: 500 }}
                    title={`Open ${part}`}
                  >{part}</span>
                </ReadLaterPopup>
              );
            }
            return <span key={i} style={{ color: "var(--amber)", opacity: 0.5 }}>{part}</span>;
          }
          if (termPat) {
            termPat.lastIndex = 0;
            if (termPat.test(part)) {
              const isFirst = !firstMark;
              if (isFirst) firstMark = true;
              return <mark key={i} ref={isFirst ? firstMatchRef : null}>{part}</mark>;
            }
          }
          return part;
        })}
      </pre>
    );
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5, flexWrap: "wrap" }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: "var(--amber)", letterSpacing: "0.04em" }}>{data.case_number}</span>
              {data.outcome && <Badge label={data.outcome} />}
              {query && <span style={{ fontSize: 11, color: "var(--text3)", marginLeft: 4 }}>— <span style={{ color: "var(--amber)", fontFamily: "'DM Mono', monospace" }}>"{query}"</span></span>}
            </div>
            {data.employer_name && <div style={{ fontSize: 16, fontWeight: 400, color: "var(--text)", marginBottom: 3, fontFamily: "'DM Serif Display', serif" }}>{data.employer_name}</div>}
            {data.job_title && <div style={{ fontSize: 12, color: "var(--text2)", marginBottom: 3 }}>{data.job_title}</div>}
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              {data.decision_date && <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{data.decision_date}</span>}
              {data.panel && <span style={{ fontSize: 11, color: "var(--text3)" }}>{data.panel}</span>}
            </div>
          </div>
          <InDocSearch hook={docSearch} accentColor="var(--amber)" />
          {onViewGraph && data?.case_number && (
            <button onClick={() => onViewGraph(data.case_number)}
              style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--green)", padding: "5px 10px", border: "1px solid var(--green)", borderRadius: "var(--radius)", whiteSpace: "nowrap", flexShrink: 0, background: "none" }}
              onMouseEnter={e => e.currentTarget.style.background = "var(--green-dim)"}
              onMouseLeave={e => e.currentTarget.style.background = ""}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>
              Graph
            </button>
          )}
          <a href={`${API}/decisions/${decisionId}/pdf`} target="_blank" rel="noreferrer"
            style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--amber)", textDecoration: "none", padding: "5px 10px", border: "1px solid var(--amber)", borderRadius: "var(--radius)", whiteSpace: "nowrap", flexShrink: 0 }}
            onMouseEnter={e => e.currentTarget.style.background = "var(--amber-dim)"}
            onMouseLeave={e => e.currentTarget.style.background = ""}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            PDF
          </a>
          <SaveToProject decisionId={decisionId} searchQuery={query} />
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            padding: "9px 14px", fontSize: 12, background: "none", border: "none", borderRadius: 0,
            borderBottom: activeTab === t.id ? "2px solid var(--amber)" : "2px solid transparent",
            color: activeTab === t.id ? "var(--amber)" : "var(--text3)",
            fontWeight: activeTab === t.id ? 500 : 400,
            display: "flex", alignItems: "center", gap: 5,
          }}>
            {t.label}
            {t.count > 0 && <span style={{ fontSize: 10, background: activeTab === t.id ? "var(--amber-dim)" : "var(--bg4)", color: activeTab === t.id ? "var(--amber)" : "var(--text3)", borderRadius: 3, padding: "1px 5px", fontFamily: "'DM Mono', monospace" }}>{t.count}</span>}
          </button>
        ))}
      </div>

      {/* Content */}
      <div ref={contentRef} style={{ flex: 1, overflowY: "auto" }}>
        {activeTab === "text" && renderOpinion()}
        {activeTab === "regulations" && (
          <div style={{ padding: "14px 20px" }}>
            {!data.regulations?.length && <p style={{ color: "var(--text3)", fontSize: 13 }}>No regulations found.</p>}
            {data.regulations?.map(r => <RegCard key={r.id} reg={r} />)}
          </div>
        )}
        {activeTab === "citations" && (
          <div style={{ padding: "14px 20px" }}>
            {data.citations_made?.length > 0 && (
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>This decision cites</div>
                {data.citations_made.map(c => <CiteRow key={c.id} citation={c} onNavigate={onNavigate} direction="out" />)}
              </div>
            )}
            {data.cited_by?.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>Cited by</div>
                {data.cited_by.map(c => <CiteRow key={c.id} citation={c} onNavigate={onNavigate} direction="in" />)}
              </div>
            )}
            {!data.citations_made?.length && !data.cited_by?.length && <p style={{ color: "var(--text3)", fontSize: 13 }}>No citation links found.</p>}
          </div>
        )}
        {activeTab === "notes" && (
          <div style={{ padding: "14px 20px" }}>
            <div style={{ marginBottom: 14 }}>
              <textarea value={newNote} onChange={e => setNewNote(e.target.value)} placeholder="Add a research note…" rows={3} />
              <button onClick={addNote} className="primary" style={{ marginTop: 8 }}>Save note</button>
            </div>
            {(notes || []).map(n => (
              <div key={n.id} style={{ padding: "11px 13px", marginBottom: 8, background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", fontSize: 13, lineHeight: 1.6 }}>
                <p style={{ margin: "0 0 8px", color: "var(--text)" }}>{n.note}</p>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{new Date(n.created_at).toLocaleDateString()}</span>
                  <button onClick={() => deleteNote(n.id)} style={{ fontSize: 11, color: "var(--red)", background: "none", border: "none", padding: 0, cursor: "pointer" }}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function RegCard({ reg }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginBottom: 6, border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", overflow: "hidden" }}
      onMouseEnter={e => e.currentTarget.style.borderColor = "var(--border2)"}
      onMouseLeave={e => e.currentTarget.style.borderColor = "var(--border)"}>
      <div onClick={() => setOpen(o => !o)} style={{ padding: "9px 13px", cursor: "pointer", display: "flex", alignItems: "center", gap: 10, background: open ? "var(--bg3)" : "var(--bg2)" }}>
        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: "var(--amber)", fontWeight: 500 }}>{reg.citation}</span>
        {reg.category && <RegBadge label={reg.category} />}
        {reg.title && <span style={{ fontSize: 12, color: "var(--text3)", flex: 1 }}>{reg.title}</span>}
        <span style={{ fontSize: 10, color: "var(--text3)" }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && reg.context_snippet && (
        <div style={{ padding: "9px 13px", fontSize: 12, lineHeight: 1.7, color: "var(--text2)", borderTop: "1px solid var(--border)", background: "var(--bg)", fontStyle: "italic" }}>
          "…{reg.context_snippet}…"
        </div>
      )}
    </div>
  );
}

function CiteRow({ citation, onNavigate, direction }) {
  const caseNum = direction === "out" ? citation.cited_case_number : citation.citing_case_number;
  const linkedId = direction === "out" ? citation.cited_id : citation.citing_id;
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginBottom: 5, border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
      <div style={{ padding: "7px 11px", display: "flex", alignItems: "center", gap: 10, background: "var(--bg2)" }}>
        <span style={{ fontSize: 10, color: direction === "out" ? "var(--blue)" : "var(--green)", fontFamily: "'DM Mono', monospace", minWidth: 48 }}>
          {direction === "out" ? "→ CITES" : "← FROM"}
        </span>
        {linkedId
          ? <button onClick={() => onNavigate(linkedId)} style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, background: "none", border: "none", cursor: "pointer", color: "var(--amber)", padding: 0, textDecoration: "underline", textDecorationColor: "var(--amber-dim)" }}>
              {caseNum || citation.cited_raw}
            </button>
          : <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: "var(--text3)" }}>{citation.cited_raw} <span style={{ fontSize: 10 }}>(not yet indexed)</span></span>
        }
        {citation.context_snippet && (
          <button onClick={() => setOpen(o => !o)} style={{ marginLeft: "auto", fontSize: 10, color: "var(--text3)", background: "none", border: "1px solid var(--border)", padding: "2px 7px", borderRadius: 3 }}>
            {open ? "hide" : "context"}
          </button>
        )}
      </div>
      {open && <div style={{ padding: "7px 11px", fontSize: 11, lineHeight: 1.6, color: "var(--text3)", borderTop: "1px solid var(--border)", fontStyle: "italic" }}>"…{citation.context_snippet}…"</div>}
    </div>
  );
}

// ── Regulations browser ───────────────────────────────────────────────────────
function RegsBrowser({ onSelectDecision }) {
  const { data } = useFetch(`${API}/regulations`);
  const [selected, setSelected] = useState(null);
  const [selectedCitation, setSelectedCitation] = useState("");
  const { data: cases, loading } = useFetch(selected ? `${API}/regulations/${selected}/decisions?page_size=100` : null);
  const grouped = {};
  (data || []).forEach(r => { const c = r.category || "Uncategorized"; if (!grouped[c]) grouped[c] = []; grouped[c].push(r); });
  const cats = Object.keys(grouped).sort((a, b) => a === "Uncategorized" ? 1 : b === "Uncategorized" ? -1 : a.localeCompare(b));

  return (
    <div style={{ height: "100%", display: "flex", overflow: "hidden" }}>
      <div style={{ width: 260, borderRight: "1px solid var(--border)", overflowY: "auto", background: "var(--bg2)", flexShrink: 0 }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Regulations Index</div>
        </div>
        {cats.map(cat => (
          <div key={cat}>
            <div style={{ padding: "5px 16px", fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", background: "var(--bg)", borderBottom: "1px solid var(--border)", borderTop: "1px solid var(--border)" }}>{cat}</div>
            {grouped[cat].map(r => (
              <div key={r.id} onClick={() => { setSelected(r.id); setSelectedCitation(r.citation); }}
                style={{ padding: "8px 16px", cursor: "pointer", background: selected === r.id ? "var(--bg3)" : "transparent", borderLeft: selected === r.id ? "2px solid var(--amber)" : "2px solid transparent", transition: "background 0.1s" }}
                onMouseEnter={e => { if (selected !== r.id) e.currentTarget.style.background = "var(--bg3)"; }}
                onMouseLeave={e => { if (selected !== r.id) e.currentTarget.style.background = "transparent"; }}>
                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: selected === r.id ? "var(--amber)" : "var(--text2)" }}>{r.citation}</div>
                {r.title && <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 2, lineHeight: 1.3 }}>{r.title}</div>}
                <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 3, fontFamily: "'DM Mono', monospace" }}>{r.decision_count} decisions</div>
              </div>
            ))}
          </div>
        ))}
      </div>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)" }}>
          {selectedCitation
            ? <><span style={{ fontFamily: "'DM Mono', monospace", fontSize: 13, color: "var(--amber)" }}>{selectedCitation}</span><span style={{ fontSize: 12, color: "var(--text3)", marginLeft: 10 }}>{cases?.length || "…"} decisions</span></>
            : <span style={{ fontSize: 12, color: "var(--text3)" }}>Select a regulation to browse decisions</span>}
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && <Spinner />}
          {!loading && cases?.map((c, i) => (
            <div key={c.id} onClick={() => onSelectDecision(c.id)} className="fade-up"
              style={{ padding: "11px 20px", borderBottom: "1px solid var(--border)", cursor: "pointer", animationDelay: `${i * 15}ms` }}
              onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
              onMouseLeave={e => e.currentTarget.style.background = ""}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 3 }}>
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--text3)" }}>{c.case_number}</span>
                {c.outcome && <Badge label={c.outcome} small />}
              </div>
              {c.employer_name && <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 2 }}>{c.employer_name}</div>}
              {c.context_snippet && <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 3, lineHeight: 1.5, fontStyle: "italic" }}>"…{c.context_snippet.slice(0, 140)}…"</div>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatsDashboard() {
  const { data } = useFetch(`${API}/stats`);
  if (!data) return <Spinner />;
  const pct = n => data.total_decisions ? Math.round(n / data.total_decisions * 100) : 0;
  return (
    <div style={{ padding: "28px 32px", maxWidth: 860 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 20 }}>Database Overview</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 32 }}>
        {[["Total decisions", data.total_decisions?.toLocaleString(), "var(--text)"],["Fully indexed", data.indexed_decisions?.toLocaleString(), "var(--green)"],["Citation links", "39,826+", "var(--amber)"]].map(([label, val, color]) => (
          <div key={label} style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "16px 18px" }}>
            <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 500 }}>{label}</div>
            <div style={{ fontSize: 28, fontWeight: 300, color, fontFamily: "'DM Mono', monospace" }}>{val}</div>
          </div>
        ))}
      </div>
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 14 }}>Outcomes</div>
        {data.outcomes?.filter(o => o.outcome).map(o => {
          const c = OUTCOME[o.outcome] || { dot: "var(--text3)" };
          return (
            <div key={o.outcome} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
              <Badge label={o.outcome} />
              <div style={{ flex: 1, height: 4, background: "var(--bg4)", borderRadius: 2, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${pct(o.cnt)}%`, background: c.dot, borderRadius: 2 }} />
              </div>
              <span style={{ fontSize: 12, color: "var(--text3)", fontFamily: "'DM Mono', monospace", minWidth: 70, textAlign: "right" }}>{o.cnt.toLocaleString()} ({pct(o.cnt)}%)</span>
            </div>
          );
        })}
      </div>
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 14 }}>Most cited regulations</div>
        <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", overflow: "hidden" }}>
          {data.top_regulations?.map((r, i) => (
            <div key={r.citation} style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 16px", borderBottom: i < data.top_regulations.length - 1 ? "1px solid var(--border)" : "none", background: i % 2 === 0 ? "var(--bg2)" : "var(--bg)" }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: "var(--amber)", minWidth: 180 }}>{r.citation}</span>
              {r.category && <RegBadge label={r.category} />}
              <span style={{ marginLeft: "auto", fontFamily: "'DM Mono', monospace", fontSize: 12, color: "var(--text3)" }}>{r.cnt.toLocaleString()}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Save to Project button ────────────────────────────────────────────────────
function SaveToProject({ decisionId, searchQuery, small }) {
  const [projects, setProjects] = useState(null);
  const [saved, setSaved] = useState([]); // project ids that already contain this case
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(null);
  const ref = useRef(null);

  const load = async () => {
    const [all, mine] = await Promise.all([
      fetch(`${API}/projects`).then(r => r.json()),
      fetch(`${API}/decisions/${decisionId}/projects`).then(r => r.json()),
    ]);
    setProjects(all);
    setSaved(mine.map(p => p.id));
  };

  useEffect(() => {
    if (open) load();
  }, [open, decisionId]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const toggle = async (projectId) => {
    setSaving(projectId);
    if (saved.includes(projectId)) {
      await fetch(`${API}/projects/${projectId}/cases/${decisionId}`, { method: "DELETE" });
      setSaved(s => s.filter(id => id !== projectId));
    } else {
      await fetch(`${API}/projects/${projectId}/cases`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision_id: decisionId, search_query: searchQuery || "" }),
      });
      setSaved(s => [...s, projectId]);
    }
    setSaving(null);
  };

  const isSaved = saved.length > 0;

  return (
    <div ref={ref} style={{ position: "relative", flexShrink: 0 }}>
      <button onClick={() => setOpen(o => !o)} style={{
        display: "flex", alignItems: "center", gap: 5,
        fontSize: small ? 10 : 11, padding: small ? "3px 8px" : "5px 10px",
        height: "auto",
        background: isSaved ? "var(--blue-dim)" : "var(--bg3)",
        color: isSaved ? "var(--blue)" : "var(--text3)",
        border: isSaved ? "1px solid #60a5fa44" : "1px solid var(--border)",
        borderRadius: 4,
      }}>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
        </svg>
        {isSaved ? `In ${saved.length} project${saved.length > 1 ? "s" : ""}` : "Save to project"}
      </button>

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 100,
          background: "var(--bg2)", border: "1px solid var(--border2)",
          borderRadius: "var(--radius-lg)", minWidth: 220, boxShadow: "0 8px 24px #00000044",
          animation: "fadeUp 0.12s ease",
        }}>
          <div style={{ padding: "10px 14px 6px", fontSize: 11, color: "var(--text3)", fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}>
            Save to project
          </div>
          {projects === null && <div style={{ padding: "8px 14px" }}><Spinner /></div>}
          {projects?.length === 0 && (
            <div style={{ padding: "8px 14px 12px", fontSize: 12, color: "var(--text3)" }}>No projects yet. Create one first.</div>
          )}
          {projects?.map(p => {
            const inProject = saved.includes(p.id);
            return (
              <div key={p.id} onClick={() => toggle(p.id)} style={{
                padding: "8px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 10,
                background: inProject ? "var(--bg3)" : "transparent",
                opacity: saving === p.id ? 0.5 : 1,
              }}
                onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                onMouseLeave={e => { if (!inProject) e.currentTarget.style.background = "transparent"; }}>
                <div style={{ width: 8, height: 8, borderRadius: "50%", background: p.color, flexShrink: 0 }} />
                <span style={{ fontSize: 13, flex: 1 }}>{p.name}</span>
                {inProject && (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2.5">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                )}
              </div>
            );
          })}
          <div style={{ borderTop: "1px solid var(--border)", padding: "8px 14px" }}>
            <span style={{ fontSize: 11, color: "var(--text3)" }}>Go to Projects tab to create new</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Projects view ─────────────────────────────────────────────────────────────
const PROJECT_COLORS = ["#f59e0b","#34d399","#60a5fa","#f87171","#a78bfa","#fb7185","#4ade80","#38bdf8"];

function ProjectsView({ onOpenDecision }) {
  const [projects, setProjects] = useState(null);
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newColor, setNewColor] = useState(PROJECT_COLORS[0]);

  const load = () => fetch(`${API}/projects`).then(r => r.json()).then(setProjects);
  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!newName.trim()) return;
    const p = await fetch(`${API}/projects`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName, description: newDesc, color: newColor }),
    }).then(r => r.json());
    setNewName(""); setNewDesc(""); setNewColor(PROJECT_COLORS[0]); setCreating(false);
    await load();
    setSelected(p.id);
  };

  const deleteProject = async (id) => {
    if (!confirm("Delete this project? This cannot be undone.")) return;
    await fetch(`${API}/projects/${id}`, { method: "DELETE" });
    if (selected === id) setSelected(null);
    load();
  };

  if (selected) {
    return <ProjectDetail projectId={selected} onBack={() => { setSelected(null); load(); }} onOpenDecision={onOpenDecision} />;
  }

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "32px 32px" }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 24 }}>Projects</div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 16 }}>
          {/* New project card */}
          {!creating ? (
            <div onClick={() => setCreating(true)} style={{
              border: "1px dashed var(--border2)", borderRadius: "var(--radius-lg)", padding: "24px 20px",
              cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
              flexDirection: "column", gap: 8, minHeight: 140,
              transition: "border-color 0.15s, background 0.15s",
            }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--amber)"; e.currentTarget.style.background = "var(--amber-dim)"; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border2)"; e.currentTarget.style.background = ""; }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="1.5">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>
              </svg>
              <span style={{ fontSize: 13, color: "var(--text3)" }}>New project</span>
            </div>
          ) : (
            <div style={{ border: "1px solid var(--amber)", borderRadius: "var(--radius-lg)", padding: "20px", background: "var(--bg2)", minHeight: 140 }}>
              <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Project name"
                autoFocus onKeyDown={e => e.key === "Enter" && create()}
                style={{ marginBottom: 8, fontSize: 13 }} />
              <input value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder="Description (optional)"
                style={{ marginBottom: 10, fontSize: 12 }} />
              <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
                {PROJECT_COLORS.map(c => (
                  <div key={c} onClick={() => setNewColor(c)} style={{
                    width: 18, height: 18, borderRadius: "50%", background: c, cursor: "pointer",
                    outline: newColor === c ? `2px solid ${c}` : "none", outlineOffset: 2,
                  }} />
                ))}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={create} className="primary" style={{ fontSize: 12, padding: "5px 14px" }}>Create</button>
                <button onClick={() => setCreating(false)} style={{ fontSize: 12, padding: "5px 10px" }}>Cancel</button>
              </div>
            </div>
          )}

          {/* Existing projects */}
          {(projects || []).map(p => (
            <div key={p.id} onClick={() => setSelected(p.id)} style={{
              border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px",
              cursor: "pointer", background: "var(--bg2)", minHeight: 140,
              display: "flex", flexDirection: "column", gap: 0,
              transition: "border-color 0.15s, background 0.15s",
              position: "relative",
            }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = p.color; e.currentTarget.style.background = "var(--bg3)"; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.background = "var(--bg2)"; }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 10 }}>
                <div style={{ width: 10, height: 10, borderRadius: "50%", background: p.color, flexShrink: 0, marginTop: 3 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text)", marginBottom: 3 }}>{p.name}</div>
                  {p.description && <div style={{ fontSize: 12, color: "var(--text3)", lineHeight: 1.4 }}>{p.description}</div>}
                </div>
                <button onClick={e => { e.stopPropagation(); deleteProject(p.id); }} style={{
                  fontSize: 11, color: "var(--text3)", background: "none", border: "none", padding: "2px 4px", cursor: "pointer", opacity: 0.6,
                }}>✕</button>
              </div>
              <div style={{ marginTop: "auto", display: "flex", gap: 12 }}>
                <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{p.case_count} case{p.case_count !== 1 ? "s" : ""}</span>
                <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{p.note_count} note{p.note_count !== 1 ? "s" : ""}</span>
              </div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 6, fontFamily: "'DM Mono', monospace" }}>
                {new Date(p.updated_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Project detail ────────────────────────────────────────────────────────────
function ProjectDetail({ projectId, onBack, onOpenDecision }) {
  const [project, setProject] = useState(null);
  const [activeTab, setActiveTab] = useState("cases");
  const [newNote, setNewNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [readLater, setReadLater] = useState([]);

  const load = () => {
    setLoading(true);
    Promise.all([
      fetch(`${API}/projects/${projectId}`).then(r => r.json()),
      fetch(`${API}/projects/${projectId}/read-later`).then(r => r.ok ? r.json() : []),
    ]).then(([d, rl]) => { setProject(d); setReadLater(Array.isArray(rl) ? rl : []); setLoading(false); });
  };
  useEffect(() => { load(); }, [projectId]);

  const addNote = async () => {
    if (!newNote.trim()) return;
    await fetch(`${API}/projects/${projectId}/notes`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: newNote }),
    });
    setNewNote(""); load();
  };

  const deleteNote = async (id) => {
    await fetch(`${API}/project-notes/${id}`, { method: "DELETE" });
    load();
  };

  const removeCase = async (decisionId) => {
    await fetch(`${API}/projects/${projectId}/cases/${decisionId}`, { method: "DELETE" });
    load();
  };

  const removeReadLater = async (pcId) => {
    await fetch(`${API}/projects/${projectId}/read-later/${pcId}`, { method: "DELETE" });
    setReadLater(rl => rl.filter(r => r.pc_id !== pcId));
  };

  if (loading || !project) return <Spinner />;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", animation: "fadeUp 0.18s ease" }}>
      {/* Header */}
      <div style={{ padding: "14px 28px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button onClick={onBack} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "var(--text3)", background: "none", border: "none", padding: 0, cursor: "pointer" }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m15 18-6-6 6-6"/></svg>
            Projects
          </button>
          <div style={{ width: 1, height: 14, background: "var(--border2)" }} />
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: project.color }} />
          <span style={{ fontSize: 15, fontWeight: 500, color: "var(--text)" }}>{project.name}</span>
          {project.description && <span style={{ fontSize: 12, color: "var(--text3)" }}>{project.description}</span>}
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--bg2)", padding: "0 28px", flexShrink: 0 }}>
        {[
          { id: "cases", label: "Cases", count: project.cases?.length },
          { id: "read-later", label: "Read Later", count: readLater.length },
          { id: "notes", label: "Notes", count: project.notes?.length },
        ].map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            padding: "9px 14px", fontSize: 12, background: "none", border: "none", borderRadius: 0,
            borderBottom: activeTab === t.id ? "2px solid var(--amber)" : "2px solid transparent",
            color: activeTab === t.id ? "var(--amber)" : "var(--text3)",
            fontWeight: activeTab === t.id ? 500 : 400,
            display: "flex", alignItems: "center", gap: 5,
          }}>
            {t.label}
            <span style={{ fontSize: 10, background: activeTab === t.id ? "var(--amber-dim)" : "var(--bg4)", color: activeTab === t.id ? "var(--amber)" : "var(--text3)", borderRadius: 3, padding: "1px 5px", fontFamily: "'DM Mono', monospace" }}>{t.count}</span>
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: "auto" }}>
        {activeTab === "cases" && (
          <div style={{ padding: "16px 28px" }}>
            {project.cases?.length === 0 && (
              <p style={{ color: "var(--text3)", fontSize: 13 }}>No cases saved yet. Use "Save to project" when browsing search results or reading a case.</p>
            )}
            {project.cases?.map(c => (
              <div key={c.pc_id} style={{ padding: "12px 14px", marginBottom: 8, background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", display: "flex", alignItems: "flex-start", gap: 12 }}>
                <div style={{ flex: 1, cursor: "pointer" }} onClick={() => onOpenDecision(c.id, c.search_query)}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "var(--amber)" }}>{c.case_number}</span>
                    {c.outcome && <Badge label={c.outcome} small />}
                  </div>
                  {c.employer_name && <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 2 }}>{c.employer_name}</div>}
                  {c.job_title && <div style={{ fontSize: 12, color: "var(--text2)" }}>{c.job_title}</div>}
                  <div style={{ display: "flex", gap: 12, marginTop: 6 }}>
                    {c.decision_date && <span style={{ fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{c.decision_date}</span>}
                    {c.search_query && (
                      <span style={{ fontSize: 10, color: "var(--text3)" }}>
                        saved from: <span style={{ color: "var(--amber)", fontFamily: "'DM Mono', monospace" }}>"{c.search_query}"</span>
                      </span>
                    )}
                  </div>
                </div>
                <button onClick={() => removeCase(c.id)} style={{ fontSize: 11, color: "var(--text3)", background: "none", border: "none", padding: "2px 4px", cursor: "pointer", flexShrink: 0, opacity: 0.6 }}>✕</button>
              </div>
            ))}
          </div>
        )}

        {activeTab === "read-later" && (
          <div style={{ padding: "16px 28px" }}>
            {readLater.length === 0 && (
              <p style={{ color: "var(--text3)", fontSize: 13 }}>
                No cases saved to Read Later yet. Hover over a linked case number in any opinion and save it here.
              </p>
            )}
            {readLater.map(r => {
              const isBalca = r.source === "balca";
              const caseNum = isBalca ? r.case_number : (r.aao_title || r.form_type || "AAO Decision");
              const employer = isBalca ? r.employer_name : null;
              const date = isBalca ? r.decision_date : r.aao_decision_date;
              const outcome = isBalca ? r.outcome : r.aao_outcome;
              const accent = isBalca ? "var(--amber)" : "var(--blue)";
              const corpusLabel = isBalca ? "BALCA" : "AAO";
              return (
                <div key={r.pc_id} style={{ padding: "12px 14px", marginBottom: 8, background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", display: "flex", alignItems: "flex-start", gap: 12 }}>
                  <div style={{ flex: 1, cursor: "pointer" }} onClick={() => onOpenDecision(
                    r.source === "balca" ? r.decision_id : r.aao_decision_id,
                    "",
                    r.source === "balca" ? "balca" : "aao"
                  )}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: accent, padding: "1px 6px", background: `${accent}22`, borderRadius: 3 }}>{corpusLabel}</span>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: accent }}>{caseNum}</span>
                      {outcome && <Badge label={outcome} small />}
                    </div>
                    {employer && <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 2 }}>{employer}</div>}
                    {date && <div style={{ fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>{date}</div>}
                    {r.saved_from_case_number && (
                      <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 2, display: "flex", alignItems: "center", gap: 5 }}>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18 15 12 9 6"/></svg>
                        saved while reading
                        <span style={{ fontFamily: "'DM Mono', monospace", color: r.saved_from_source === "aao" ? "var(--blue)" : "var(--amber)" }}>
                          {r.saved_from_case_number}
                        </span>
                      </div>
                    )}
                  </div>
                  <button onClick={() => removeReadLater(r.pc_id)} style={{ fontSize: 11, color: "var(--text3)", background: "none", border: "none", padding: "2px 4px", cursor: "pointer", flexShrink: 0, opacity: 0.6 }}>✕</button>
                </div>
              );
            })}
          </div>
        )}

        {activeTab === "notes" && (
          <div style={{ padding: "16px 28px" }}>
            <div style={{ marginBottom: 16 }}>
              <textarea value={newNote} onChange={e => setNewNote(e.target.value)}
                placeholder="Add a project note…" rows={3} />
              <button onClick={addNote} className="primary" style={{ marginTop: 8 }}>Save note</button>
            </div>
            {project.notes?.length === 0 && <p style={{ color: "var(--text3)", fontSize: 13 }}>No notes yet.</p>}
            {project.notes?.map(n => (
              <div key={n.id} style={{ padding: "12px 14px", marginBottom: 8, background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", fontSize: 13, lineHeight: 1.6 }}>
                {n.case_number && (
                  <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 6, fontFamily: "'DM Mono', monospace" }}>
                    re: <span style={{ color: "var(--amber)", cursor: "pointer" }} onClick={() => onOpenDecision(n.decision_id, "")}>{n.case_number}</span>
                    {n.employer_name && <span style={{ color: "var(--text3)" }}> — {n.employer_name}</span>}
                  </div>
                )}
                <p style={{ margin: "0 0 8px", color: "var(--text)" }}>{n.note}</p>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{new Date(n.created_at).toLocaleDateString()}</span>
                  <button onClick={() => deleteNote(n.id)} style={{ fontSize: 11, color: "var(--red)", background: "none", border: "none", padding: 0, cursor: "pointer" }}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────
// ── Regulations View ─────────────────────────────────────────────────────────
const AGENCY_COLORS = {
  "DHS / USCIS":      { accent: "#34d399", dim: "#34d39922" },
  "DOL / ETA":        { accent: "#34d399", dim: "#34d39922" },
  "DOL / WHD":        { accent: "#4ade80", dim: "#4ade8022" },
  "State Department": { accent: "#60a5fa", dim: "#60a5fa22" },
};

function RegulationsView() {
  const [q, setQ] = useState("");
  const [agency, setAgency] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [activeQuery, setActiveQuery] = useState("");
  const { data: allDocs } = useFetch(!searched ? `${API}/regulations-docs` : null);
  const inputRef = useRef(null);

  useEffect(() => { if (!searched) inputRef.current?.focus(); }, [searched]);

  const search = useCallback(async () => {
    setLoading(true); setSearched(true); setSelectedId(null);
    const p = new URLSearchParams({ page_size: 60 });
    if (q) p.set("q", q);
    if (agency) p.set("agency", agency);
    const res = await fetch(`${API}/regulations-docs/search?${p}`);
    const data = await res.json();
    setResults(data); setLoading(false);
    setActiveQuery(q);
  }, [q, agency]);

  const docs = searched ? (results?.results || []) : (allDocs || []);
  const grouped = {};
  docs.forEach(d => { const g = d.agency || "Other"; if (!grouped[g]) grouped[g] = []; grouped[g].push(d); });
  const splitView = searched && !!selectedId;

  return (
    <div className="search-view-root" style={{ height: "100%", display: "flex", overflow: "hidden" }}>
      <div className="search-list-panel" style={{ display: "flex", flexDirection: "column", overflow: "hidden", width: splitView ? 340 : "100%", flexShrink: 0, borderRight: splitView ? "1px solid var(--border)" : "none", transition: "width 0.25s ease" }}>

        {/* Search bar — mirrors BALCA: centered landing, collapsed after search */}
        <div style={{ padding: searched ? "12px 16px" : "0", flex: searched ? "0 0 auto" : "1", display: "flex", flexDirection: "column", justifyContent: searched ? "flex-start" : "center", alignItems: "center", borderBottom: searched ? "1px solid var(--border)" : "none" }}>
          {!searched && (
            <div style={{ marginBottom: 28, textAlign: "center" }}>
              <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 28, color: "var(--text)", marginBottom: 6 }}>Regulations &amp; Statutes</div>
              <div style={{ fontSize: 13, color: "var(--text3)" }}>120 CFR parts · 2,301 pages · current as of 2026</div>
            </div>
          )}
          <div style={{ width: "100%", maxWidth: searched ? "100%" : 680, padding: searched ? 0 : "0 24px" }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <div style={{ position: "relative", flex: 1 }}>
                <svg style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text3)", pointerEvents: "none" }} width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && search()}
                  placeholder={searched ? "New search… (use \"quotes\" -exclude OR)" : "Search regulation text, section numbers… (use \"quotes\" -exclude OR)"}
                  style={{ paddingLeft: 30, fontSize: searched ? 13 : 14, height: searched ? 36 : 42 }} />
              </div>
              <button onClick={search} className="primary" style={{ height: searched ? 36 : 42, padding: "0 14px", fontSize: searched ? 13 : 14 }}>Search</button>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              {["DHS / USCIS", "DOL / ETA", "State Department"].map(ag => (
                <button key={ag} onClick={() => setAgency(agency === ag ? "" : ag)} style={{ fontSize: 11, padding: "3px 10px", height: "auto", background: agency === ag ? (AGENCY_COLORS[ag]?.dim || "var(--bg3)") : "var(--bg3)", color: agency === ag ? (AGENCY_COLORS[ag]?.accent || "var(--text)") : "var(--text3)", border: agency === ag ? `1px solid ${AGENCY_COLORS[ag]?.accent || "#fff"}44` : "1px solid var(--border)", borderRadius: 20, fontWeight: agency === ag ? 500 : 400, transition: "all 0.12s" }}>{ag}</button>
              ))}
              {searched && <button onClick={() => { setSearched(false); setResults(null); setQ(""); setAgency(""); setSelectedId(null); }} style={{ fontSize: 11, padding: "3px 10px", height: "auto", background: "var(--bg3)", color: "var(--text3)", border: "1px solid var(--border)", borderRadius: 20, marginLeft: "auto" }}>Clear</button>}
            </div>
          </div>
        </div>

        {/* Results list */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && <Spinner />}
          {!loading && (searched || allDocs) && (
            <>
              <div style={{ padding: splitView ? "6px 12px" : "8px 24px", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace", letterSpacing: "0.05em" }}>
                {searched ? `${results?.total?.toLocaleString() ?? "…"} PARTS MATCHED` : "120 PARTS"}
              </div>
              {Object.entries(grouped).map(([ag, items]) => {
                const color = AGENCY_COLORS[ag] || { accent: "var(--text3)", dim: "var(--bg3)" };
                return (
                  <div key={ag}>
                    <div style={{ padding: splitView ? "4px 12px" : "5px 24px", fontSize: 10, fontWeight: 600, color: color.accent, letterSpacing: "0.08em", textTransform: "uppercase", background: color.dim, borderBottom: "1px solid var(--border)", borderTop: "1px solid var(--border)" }}>
                      {ag} · {items.length} parts
                    </div>
                    {items.map((doc, i) => (
                      <div key={doc.id} onClick={() => setSelectedId(doc.id)} className="fade-up" style={{ padding: splitView ? "9px 12px" : "12px 24px", borderBottom: "1px solid var(--border)", borderLeft: selectedId === doc.id ? `2px solid ${color.accent}` : "2px solid transparent", cursor: "pointer", background: selectedId === doc.id ? "var(--bg3)" : "transparent", animationDelay: `${i * 8}ms`, transition: "background 0.1s" }}
                        onMouseEnter={e => { if (selectedId !== doc.id) e.currentTarget.style.background = "var(--bg2)"; }}
                        onMouseLeave={e => { if (selectedId !== doc.id) e.currentTarget.style.background = "transparent"; }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                          <span style={{ fontFamily: "'DM Mono', monospace", fontSize: splitView ? 10 : 11, color: selectedId === doc.id ? color.accent : "var(--text3)" }}>{doc.title}</span>
                          <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace", flexShrink: 0 }}>{doc.page_count}pp</span>
                        </div>
                        {doc.part_name && <div style={{ fontSize: splitView ? 11 : 12, color: "var(--text)", fontWeight: 500, lineHeight: 1.3 }}>{doc.part_name}</div>}
                        {!splitView && doc.headline && <div style={{ fontSize: 11, color: "var(--text3)", lineHeight: 1.5, marginTop: 4 }} dangerouslySetInnerHTML={{ __html: doc.headline }} />}
                        {!splitView && doc.as_of_date && <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "'DM Mono', monospace" }}>as of {doc.as_of_date}</div>}
                      </div>
                    ))}
                  </div>
                );
              })}
              {searched && docs.length === 0 && <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text3)", fontSize: 13 }}>No regulations matched.</div>}
            </>
          )}
        </div>
      </div>

      {splitView && (
        <div className="search-detail-panel" style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", animation: "fadeUp 0.18s ease" }}>
          <RegulationDetail docId={selectedId} query={activeQuery} />
        </div>
      )}
    </div>
  );
}

function RegulationDetail({ docId, query }) {
  const { data, loading } = useFetch(docId ? `${API}/regulations-docs/${docId}` : null);
  const docSearch = useDocSearch();

  useEffect(() => {
    if (data) docSearch.close();
  }, [data]);

  if (loading) return <Spinner />;
  if (!data) return null;

  const color = AGENCY_COLORS[data.agency] || { accent: "var(--green)", dim: "var(--green-dim)" };
  const sections = Array.isArray(data.sections) ? data.sections : (data.sections ? JSON.parse(data.sections) : []);
  const text = data.full_text || "No text extracted.";

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: color.accent, fontWeight: 500 }}>{data.title}</span>
              <span style={{ fontSize: 10, background: color.dim, color: color.accent, borderRadius: 3, padding: "2px 7px" }}>{data.agency}</span>
              {query && <span style={{ fontSize: 11, color: "var(--text3)" }}>— <span style={{ color: color.accent, fontFamily: "'DM Mono', monospace" }}>"{query}"</span></span>}
            </div>
            {data.part_name && <div style={{ fontSize: 15, color: "var(--text)", marginBottom: 3, fontFamily: "'DM Serif Display', serif" }}>{data.part_name}</div>}
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              {data.page_count && <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{data.page_count} pages</span>}
              {data.as_of_date && <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>as of {data.as_of_date}</span>}
              {sections.length > 0 && <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{sections.length} sections</span>}
            </div>
          </div>
          <InDocSearch hook={docSearch} accentColor={color.accent} />
          <a href={`${API}/regulations-docs/${docId}/pdf`} target="_blank" rel="noreferrer"
            style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: color.accent, textDecoration: "none", padding: "5px 10px", border: `1px solid ${color.accent}`, borderRadius: "var(--radius)", whiteSpace: "nowrap", flexShrink: 0 }}
            onMouseEnter={e => e.currentTarget.style.background = color.dim}
            onMouseLeave={e => e.currentTarget.style.background = ""}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            PDF
          </a>
        </div>
        {!query?.trim() && !docSearch.open && sections.length > 0 && (
          <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: "3px 10px" }}>
            {sections.map(s => <span key={s.section} style={{ fontSize: 11, fontFamily: "'DM Mono', monospace", color: color.accent }}>§ {s.section}</span>)}
          </div>
        )}
      </div>
      <div style={{ flex: 1, overflowY: "auto" }}>
        <HighlightedText
          text={text}
          activeDocQ={docSearch.activeDocQ}
          matchIndex={docSearch.matchIndex}
          resetMatches={docSearch.resetMatches}
          registerRef={docSearch.registerRef}
        />
      </div>
    </div>
  );
}

// ── Policy Manuals View ───────────────────────────────────────────────────────
const SOURCE_COLORS = {
  "FAM":      { accent: "#60a5fa", dim: "#60a5fa22", label: "Foreign Affairs Manual" },
  "USCIS_PM": { accent: "#a78bfa", dim: "#a78bfa22", label: "USCIS Policy Manual" },
};

function PolicyView() {
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [activeQuery, setActiveQuery] = useState("");
  const { data: allDocs } = useFetch(!searched ? `${API}/policy-docs` : null);
  const { data: stats } = useFetch(`${API}/policy-docs/stats/summary`);
  const inputRef = useRef(null);

  useEffect(() => { if (!searched) inputRef.current?.focus(); }, [searched]);

  const search = useCallback(async () => {
    setLoading(true); setSearched(true); setSelectedId(null);
    const p = new URLSearchParams({ page_size: 100 });
    if (q) p.set("q", q);
    if (source) p.set("source", source);
    const res = await fetch(`${API}/policy-docs/search?${p}`);
    const data = await res.json();
    setResults(data); setLoading(false);
    setActiveQuery(q);
  }, [q, source]);

  const docs = searched ? (results?.results || []) : (allDocs || []);
  const grouped = {};
  docs.forEach(d => { const g = d.source || "Other"; if (!grouped[g]) grouped[g] = []; grouped[g].push(d); });
  const splitView = searched && !!selectedId;
  const totalSections = stats?.total_sections ?? (allDocs?.length ?? "…");

  return (
    <div className="search-view-root" style={{ height: "100%", display: "flex", overflow: "hidden" }}>
      <div className="search-list-panel" style={{ display: "flex", flexDirection: "column", overflow: "hidden", width: splitView ? 340 : "100%", flexShrink: 0, borderRight: splitView ? "1px solid var(--border)" : "none", transition: "width 0.25s ease" }}>

        <div style={{ padding: searched ? "12px 16px" : "0", flex: searched ? "0 0 auto" : "1", display: "flex", flexDirection: "column", justifyContent: searched ? "flex-start" : "center", alignItems: "center", borderBottom: searched ? "1px solid var(--border)" : "none" }}>
          {!searched && (
            <div style={{ marginBottom: 28, textAlign: "center" }}>
              <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 28, color: "var(--text)", marginBottom: 6 }}>Policy Manuals</div>
              <div style={{ fontSize: 13, color: "var(--text3)" }}>{totalSections} sections · USCIS Policy Manual &amp; Foreign Affairs Manual</div>
            </div>
          )}
          <div style={{ width: "100%", maxWidth: searched ? "100%" : 680, padding: searched ? 0 : "0 24px" }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <div style={{ position: "relative", flex: 1 }}>
                <svg style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text3)", pointerEvents: "none" }} width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && search()}
                  placeholder={searched ? "New search… (use \"quotes\" -exclude OR)" : "Search policy text, section numbers… (use \"quotes\" -exclude OR)"}
                  style={{ paddingLeft: 30, fontSize: searched ? 13 : 14, height: searched ? 36 : 42 }} />
              </div>
              <button onClick={search} className="primary" style={{ height: searched ? 36 : 42, padding: "0 14px", fontSize: searched ? 13 : 14 }}>Search</button>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              {[["USCIS_PM", "USCIS Policy Manual"], ["FAM", "Foreign Affairs Manual"]].map(([id, label]) => {
                const color = SOURCE_COLORS[id];
                return (
                  <button key={id} onClick={() => setSource(source === id ? "" : id)} style={{ fontSize: 11, padding: "3px 10px", height: "auto", background: source === id ? color.dim : "var(--bg3)", color: source === id ? color.accent : "var(--text3)", border: source === id ? `1px solid ${color.accent}44` : "1px solid var(--border)", borderRadius: 20, fontWeight: source === id ? 500 : 400, transition: "all 0.12s" }}>{label}</button>
                );
              })}
              {searched && <button onClick={() => { setSearched(false); setResults(null); setQ(""); setSource(""); setSelectedId(null); }} style={{ fontSize: 11, padding: "3px 10px", height: "auto", background: "var(--bg3)", color: "var(--text3)", border: "1px solid var(--border)", borderRadius: 20, marginLeft: "auto" }}>Clear</button>}
            </div>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && <Spinner />}
          {!loading && (searched || allDocs) && (
            <>
              <div style={{ padding: splitView ? "6px 12px" : "8px 24px", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace", letterSpacing: "0.05em" }}>
                {searched ? `${results?.total?.toLocaleString() ?? "…"} SECTIONS MATCHED` : `${totalSections} SECTIONS`}
              </div>
              {Object.entries(grouped).map(([src, items]) => {
                const color = SOURCE_COLORS[src] || { accent: "var(--text3)", dim: "var(--bg3)", label: src };
                return (
                  <div key={src}>
                    <div style={{ padding: splitView ? "4px 12px" : "5px 24px", fontSize: 10, fontWeight: 600, color: color.accent, letterSpacing: "0.08em", textTransform: "uppercase", background: color.dim, borderBottom: "1px solid var(--border)", borderTop: "1px solid var(--border)" }}>
                      {color.label} · {items.length} sections
                    </div>
                    {items.map((doc, i) => (
                      <div key={doc.id} onClick={() => setSelectedId(doc.id)} className="fade-up" style={{ padding: splitView ? "9px 12px" : "11px 24px", borderBottom: "1px solid var(--border)", borderLeft: selectedId === doc.id ? `2px solid ${color.accent}` : "2px solid transparent", cursor: "pointer", background: selectedId === doc.id ? "var(--bg3)" : "transparent", animationDelay: `${i * 6}ms`, transition: "background 0.1s" }}
                        onMouseEnter={e => { if (selectedId !== doc.id) e.currentTarget.style.background = "var(--bg2)"; }}
                        onMouseLeave={e => { if (selectedId !== doc.id) e.currentTarget.style.background = "transparent"; }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                          {doc.section && <span style={{ fontFamily: "'DM Mono', monospace", fontSize: splitView ? 10 : 11, color: selectedId === doc.id ? color.accent : "var(--text3)" }}>{doc.section}</span>}
                          {doc.page_count && <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace", flexShrink: 0 }}>{doc.page_count}pp</span>}
                        </div>
                        {doc.subject && <div style={{ fontSize: splitView ? 11 : 12, color: "var(--text)", fontWeight: 500, lineHeight: 1.3 }}>{doc.subject}</div>}
                        {!splitView && doc.headline && <div style={{ fontSize: 11, color: "var(--text3)", lineHeight: 1.5, marginTop: 4 }} dangerouslySetInnerHTML={{ __html: doc.headline }} />}
                      </div>
                    ))}
                  </div>
                );
              })}
              {searched && docs.length === 0 && <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text3)", fontSize: 13 }}>No policy sections matched.</div>}
            </>
          )}
        </div>
      </div>

      {splitView && (
        <div className="search-detail-panel" style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", animation: "fadeUp 0.18s ease" }}>
          <PolicyDetail docId={selectedId} query={activeQuery} />
        </div>
      )}
    </div>
  );
}

function PolicyDetail({ docId, query }) {
  const { data, loading } = useFetch(docId ? `${API}/policy-docs/${docId}` : null);
  const docSearch = useDocSearch();

  useEffect(() => { if (data) docSearch.close(); }, [data]);

  if (loading) return <Spinner />;
  if (!data) return null;

  const color = SOURCE_COLORS[data.source] || { accent: "var(--text3)", dim: "var(--bg3)", label: data.source };
  const text = data.full_text || "No text extracted.";

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
              {data.section && <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: color.accent, fontWeight: 500 }}>{data.section}</span>}
              <span style={{ fontSize: 10, background: color.dim, color: color.accent, borderRadius: 3, padding: "2px 7px" }}>{color.label}</span>
              {query && <span style={{ fontSize: 11, color: "var(--text3)" }}>— <span style={{ color: color.accent, fontFamily: "'DM Mono', monospace" }}>"{query}"</span></span>}
            </div>
            {data.subject && <div style={{ fontSize: 15, color: "var(--text)", marginBottom: 3, fontFamily: "'DM Serif Display', serif" }}>{data.subject}</div>}
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              {data.page_count && <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{data.page_count} pages</span>}
              {data.as_of_date && <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>as of {data.as_of_date}</span>}
            </div>
          </div>
          <InDocSearch hook={docSearch} accentColor={color.accent} />
          <a href={`${API}/policy-docs/${docId}/pdf`} target="_blank" rel="noreferrer"
            style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: color.accent, textDecoration: "none", padding: "5px 10px", border: `1px solid ${color.accent}`, borderRadius: "var(--radius)", whiteSpace: "nowrap", flexShrink: 0 }}
            onMouseEnter={e => e.currentTarget.style.background = color.dim}
            onMouseLeave={e => e.currentTarget.style.background = ""}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            PDF
          </a>
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto" }}>
        <HighlightedText
          text={text}
          activeDocQ={docSearch.activeDocQ}
          matchIndex={docSearch.matchIndex}
          resetMatches={docSearch.resetMatches}
          registerRef={docSearch.registerRef}
        />
      </div>
    </div>
  );
}

// ── PERM Comparer ─────────────────────────────────────────────────────────────
function permSplitLines(t){return t.replace(/\r\n/g,'\n').split('\n');}
const PBULLET=/^[\s]*([-\u2022*]+|\d+[.)]|[a-zA-Z][.)])\s*/;
function permNorm(t){return permSplitLines(t).map(l=>l.replace(PBULLET,'').trim()).filter(l=>l.length>0).join(' ');}
function permTok(t,s){return s?Array.from(t):(t.match(/(\s+|[A-Za-z0-9_]+|[^A-Za-z0-9_\s])/g)??[]);}
function pLcs(l,r,ci){const eq=(a,b)=>ci?a.toLowerCase()===b.toLowerCase():a===b;const m=Array.from({length:l.length+1},()=>new Array(r.length+1).fill(0));for(let i=l.length-1;i>=0;i--)for(let j=r.length-1;j>=0;j--)m[i][j]=eq(l[i],r[j])?m[i+1][j+1]+1:Math.max(m[i+1][j],m[i][j+1]);return m;}
function pDiffTok(a,b,s,ci){const at=permTok(a,s),bt=permTok(b,s),m=pLcs(at,bt,ci),ar=[],br=[];const eq=(x,y)=>ci?x.toLowerCase()===y.toLowerCase():x===y;let ai=0,bi=0;while(ai<at.length&&bi<bt.length){if(eq(at[ai],bt[bi])){ar.push({t:at[ai],c:false});br.push({t:bt[bi],c:false});ai++;bi++;}else if(m[ai+1][bi]>=m[ai][bi+1])ar.push({t:at[ai++],c:true});else br.push({t:bt[bi++],c:true});}while(ai<at.length)ar.push({t:at[ai++],c:true});while(bi<bt.length)br.push({t:bt[bi++],c:true});return{ar,br};}
function pDiffLines(a,b,s,ci){const al=permSplitLines(a),bl=permSplitLines(b);const eqLine=(x,y)=>ci?x.toLowerCase()===y.toLowerCase():x===y;const m=pLcs(al,bl,ci),ops=[];let ai=0,bi=0;while(ai<al.length&&bi<bl.length){if(eqLine(al[ai],bl[bi])){ops.push({t:'eq',s:al[ai]});ai++;bi++;}else if(m[ai+1][bi]>=m[ai][bi+1])ops.push({t:'rm',s:al[ai++]});else ops.push({t:'add',s:bl[bi++]});}while(ai<al.length)ops.push({t:'rm',s:al[ai++]});while(bi<bl.length)ops.push({t:'add',s:bl[bi++]});const lines=[];let oi=0,rn=1,cn=1;while(oi<ops.length){const cur=ops[oi];if(cur.t==='eq'){lines.push({rn,cn,rt:[{t:cur.s,c:false}],ct:[{t:cur.s,c:false}],ch:false});rn++;cn++;oi++;continue;}const rm=[],add=[];while(oi<ops.length&&ops[oi].t!=='eq'){const p=ops[oi++];(p.t==='rm'?rm:add).push(p.s);}const sz=Math.max(rm.length,add.length);for(let k=0;k<sz;k++){const{ar,br}=pDiffTok(rm[k]??'',add[k]??'',s,ci);lines.push({rn:k<rm.length?rn:null,cn:k<add.length?cn:null,rt:ar,ct:br,ch:true});if(k<rm.length)rn++;if(k<add.length)cn++;}}return lines;}
function pSummarize(field,ref,cmp,strict,igFmt){const r=igFmt?permNorm(ref):ref,c=igFmt?permNorm(cmp):cmp,lines=pDiffLines(r,c,strict,igFmt),changed=lines.filter(l=>l.ch).length,exact=igFmt?r.toLowerCase()===c.toLowerCase():r===c;return{field,exact,status:exact?'Exact Match':'Differences Found',detail:exact?(igFmt?'Match when formatting ignored.':'Texts are identical.'):`${changed} differing line${changed===1?'':'s'}.`,lines};}
function PTokens({tokens,kind}){if(!tokens.length)return <span style={{color:'var(--text3)',fontStyle:'italic'}}>(no text)</span>;return tokens.map((tk,i)=><span key={i} style={tk.c?{display:'inline',borderRadius:4,padding:'0 1px',background:kind==='reference'?'var(--red-dim)':'var(--green-dim)',color:kind==='reference'?'var(--red)':'var(--green)'}:{}}>{tk.t}</span>);}
function pParseCur(v){const n=Number((v||'').replace(/[$,\s]/g,''));return isFinite(n)?n:null;}
function pFmt(v){const n=pParseCur(v);if(n===null)return v||'(empty)';return n.toLocaleString('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2});}

const PS={
  card:{background:'var(--bg2)',border:'1px solid var(--border)',borderRadius:'var(--radius-lg)',padding:18},
  cardRef:{background:'var(--bg3)',border:'1px solid var(--border)',borderRadius:'var(--radius-lg)',padding:18},
  label:{display:'block',marginBottom:8,fontSize:11,fontWeight:600,color:'var(--text2)'},
  input:{width:'100%',padding:'10px 12px',borderRadius:'var(--radius)',border:'1px solid var(--border)',background:'var(--bg)',color:'var(--text)',font:'inherit',fontSize:12},
  textarea:{width:'100%',padding:'12px 14px',borderRadius:'var(--radius-lg)',border:'1px solid var(--border)',background:'var(--bg)',color:'var(--text)',font:'inherit',fontSize:12,lineHeight:1.6,resize:'vertical',fontFamily:"'DM Mono',monospace"},
  badge:(match)=>({display:'inline-flex',alignItems:'center',borderRadius:999,padding:'4px 10px',fontSize:10,fontWeight:600,whiteSpace:'nowrap',background:match===null?'var(--bg4)':match?'var(--green-dim)':'var(--red-dim)',color:match===null?'var(--text3)':match?'var(--green)':'var(--red)'}),
  diffCell:{minWidth:0,padding:'10px 12px',border:'1px solid var(--border)',borderRadius:'var(--radius)',background:'var(--bg)'},
};

function PermDiffPanel({res,title}){
  return(
    <div style={PS.card}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:14}}>
        <div><div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:4}}>Highlighted Differences</div><div style={{fontSize:14,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>{title} Review</div></div>
        <span style={PS.badge(res.exact)}>{res.status}</span>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10,marginBottom:8,fontSize:10,fontWeight:600,letterSpacing:'.08em',textTransform:'uppercase',color:'var(--text3)',padding:'0 4px'}}>
        <div>Reference</div><div>Comparison</div>
      </div>
      <div style={{display:'grid',gap:8}}>
        {res.lines.map((line,i)=>(
          <div key={i} style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
            <div style={{...PS.diffCell,borderColor:line.ch?'var(--red)':'var(--border)'}}>
              <div style={{fontSize:10,fontWeight:600,color:'var(--text3)',fontFamily:"'DM Mono',monospace",marginBottom:6}}>{line.rn?`Line ${line.rn}`:' '}</div>
              <pre style={{margin:0,whiteSpace:'pre-wrap',wordBreak:'break-word',fontFamily:"'DM Mono',monospace",fontSize:12,lineHeight:1.6}}><PTokens tokens={line.rt} kind="reference"/></pre>
            </div>
            <div style={{...PS.diffCell,borderColor:line.ch?'var(--red)':'var(--border)'}}>
              <div style={{fontSize:10,fontWeight:600,color:'var(--text3)',fontFamily:"'DM Mono',monospace",marginBottom:6}}>{line.cn?`Line ${line.cn}`:' '}</div>
              <pre style={{margin:0,whiteSpace:'pre-wrap',wordBreak:'break-word',fontFamily:"'DM Mono',monospace",fontSize:12,lineHeight:1.6}}><PTokens tokens={line.ct} kind="comparison"/></pre>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Drop-target textarea ──────────────────────────────────────────────────────
// onPwdDrop(file)    — called when a PDF is dropped and this box handles PWD parsing
// onLetterDrop(file) — called when a PDF is dropped and this box handles letter parsing
// If neither is provided, falls back to generic /api/extract-text plain text dump.
function DropTextarea({ value, onChange, minHeight=260, borderColor, background, placeholder, onPwdDrop, onLetterDrop }){
  const [dragging, setDragging] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractErr, setExtractErr] = useState('');
  const fileRef = useRef(null);

  const handleFile = async (file) => {
    if (!file || file.type !== 'application/pdf') {
      setExtractErr('Only PDF files are supported for drag-and-drop.');
      return;
    }
    setExtracting(true);
    setExtractErr('');
    try {
      if (onPwdDrop) {
        await onPwdDrop(file);
      } else if (onLetterDrop) {
        await onLetterDrop(file);
      } else {
        const fd = new FormData();
        fd.append('file', file);
        const resp = await fetch('/api/extract-text', { method: 'POST', body: fd });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({ detail: 'Server error' }));
          throw new Error(err.detail || 'Extraction failed');
        }
        const data = await resp.json();
        if (data.text) onChange({ target: { value: data.text } });
        else setExtractErr('No text could be extracted from this PDF.');
      }
    } catch(e) {
      setExtractErr('Extraction failed: ' + e.message);
    } finally {
      setExtracting(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const dropStyle = {
    position: 'relative',
    borderRadius: 'var(--radius)',
    transition: 'box-shadow 0.15s',
    ...(dragging ? { boxShadow: '0 0 0 2px var(--amber)' } : {})
  };

  return (
    <div style={dropStyle}
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <textarea
        style={{
          ...PS.textarea,
          minHeight,
          borderColor: dragging ? 'var(--amber)' : (borderColor || 'var(--border)'),
          background: background || 'var(--bg)',
          opacity: extracting ? 0.5 : 1,
          transition: 'border-color 0.15s, opacity 0.2s',
        }}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        disabled={extracting}
      />
      {extracting && (
        <div style={{position:'absolute',inset:0,display:'flex',alignItems:'center',justifyContent:'center',borderRadius:'var(--radius)',background:'rgba(0,0,0,0.18)',pointerEvents:'none'}}>
          <div style={{display:'flex',alignItems:'center',gap:8,padding:'8px 16px',background:'var(--bg2)',borderRadius:20,border:'1px solid var(--border)',fontSize:12,color:'var(--text2)'}}>
            <div style={{width:12,height:12,border:'2px solid var(--amber)',borderTopColor:'transparent',borderRadius:'50%',animation:'spin 0.7s linear infinite'}}/>
            Extracting…
          </div>
        </div>
      )}
      {dragging && (
        <div style={{position:'absolute',inset:0,display:'flex',alignItems:'center',justifyContent:'center',borderRadius:'var(--radius)',background:'rgba(0,0,0,0.22)',pointerEvents:'none'}}>
          <div style={{padding:'10px 20px',background:'var(--bg2)',borderRadius:20,border:'1px solid var(--amber)',fontSize:13,color:'var(--amber)',fontWeight:600}}>
            Drop PDF to extract
          </div>
        </div>
      )}
      <input ref={fileRef} type="file" accept="application/pdf" style={{display:'none'}} onChange={e => handleFile(e.target.files[0])}/>
      {extractErr && <div style={{marginTop:6,fontSize:11,color:'var(--red)'}}>{extractErr}</div>}
    </div>
  );
}

// ── Experience Verification Modal ────────────────────────────────────────────
// TODO (Future): Implement automated experience comparison — compare the total
// months of experience across all uploaded letters against the years required
// by the PWD minimum requirements. Note: the language used in PERMs often
// phrases requirements as "X years in the field" vs "X years in specific
// skills", so automated comparison will need to account for that distinction.
// See journal.txt for context.

function expHighlightKeywords(text, keywords){
  if(!keywords||keywords.length===0)return [{text,hl:false}];
  const escaped=keywords.map(k=>k.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));
  const re=new RegExp(`(${escaped.join('|')})`, 'gi');
  const parts=text.split(re);
  return parts.map(p=>({text:p,hl:new RegExp(escaped.join('|'),'i').test(p)}));
}

function ExpHighlightedText({text,keywords}){
  const parts=expHighlightKeywords(text,keywords);
  return(
    <span>
      {parts.map((p,i)=>
        p.hl
          ?<mark key={i} style={{background:'#f59e0b44',color:'var(--amber)',borderRadius:3,padding:'0 2px',fontWeight:600}}>{p.text}</mark>
          :<span key={i}>{p.text}</span>
      )}
    </span>
  );
}

function ExperienceVerificationModal({pwdText,requirementsText,letters,onClose,onSaveLetter,onRemoveLetter}){
  const [activeIdx,setActiveIdx]=useState(0);
  const [uploading,setUploading]=useState(false);
  const [uploadErr,setUploadErr]=useState('');
  const fileRef=useRef(null);

  const activeLetter=letters[activeIdx]||null;

  // Extract meaningful words and short phrases from the requirements text.
  // We pull: capitalized terms, numbers+units ("3 years"), and any quoted phrases.
  const reqKeywords=useMemo(()=>{
    if(!requirementsText)return[];
    const words=new Set();
    // All words 3+ chars, excluding very common stop words
    const stop=new Set(['the','and','or','for','with','that','this','must','have',
      'will','shall','may','can','not','any','all','each','such','from','into',
      'which','been','has','its','their','they','are','was','were','but','per',
      'years','year','months','month','experience','required','requires','including',
      'knowledge','ability','skills','skill','related','equivalent','degree','field',
      'work','working','use','using','using','used','other','than','more','least',
      'one','two','three','four','five','six']);
    const wordRe=/\b([A-Za-z][A-Za-z0-9.+#\-]{2,})\b/g;
    let m;
    while((m=wordRe.exec(requirementsText))!==null){
      const w=m[1];
      if(!stop.has(w.toLowerCase()))words.add(w);
    }
    return Array.from(words);
  },[requirementsText]);

  // For each keyword, check if it appears (case-insensitive) in the active letter
  const kwResults=useMemo(()=>{
    if(!activeLetter||!reqKeywords.length)return[];
    const haystack=(activeLetter.fullText||'').toLowerCase();
    return reqKeywords.map(kw=>({
      word:kw,
      found:haystack.includes(kw.toLowerCase())
    }));
  },[activeLetter,reqKeywords]);

  const highlightWords=[...reqKeywords];

  const uploadLetter=async(file)=>{
    if(!file)return;
    setUploading(true);setUploadErr('');
    try{
      const fd=new FormData();
      fd.append('file',file);
      const resp=await fetch('/api/extract-experience-letter',{method:'POST',body:fd});
      if(!resp.ok){
        const err=await resp.json().catch(()=>({detail:'Server error'}));
        throw new Error(err.detail||'Extraction failed');
      }
      const parsed=await resp.json();
      onSaveLetter({fileName:file.name,...parsed,saved:false},null);
      setActiveIdx(letters.length);
    }catch(e){
      setUploadErr('Could not extract letter: '+e.message);
    }finally{
      setUploading(false);
      if(fileRef.current)fileRef.current.value='';
    }
  };

  const switchLetter=(i)=>{setActiveIdx(i);};
  const totalSavedMonths=letters.filter(l=>l.saved).reduce((s,l)=>s+(l.months||0),0);

  return(
    <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.72)',zIndex:9000,display:'flex',alignItems:'stretch',justifyContent:'center'}} onClick={e=>{if(e.target===e.currentTarget)onClose();}}>
      <div style={{display:'flex',flexDirection:'column',background:'var(--bg)',width:'100%',maxWidth:1400,margin:'0 auto',height:'100vh',overflow:'hidden'}}>
        {/* Header */}
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'14px 24px',borderBottom:'1px solid var(--border)',background:'var(--bg2)',flexShrink:0}}>
          <div>
            <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:2}}>Experience Verification</div>
            <div style={{fontSize:16,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>PWD Requirements vs. Experience Letters</div>
          </div>
          <div style={{display:'flex',gap:10,alignItems:'center'}}>
            {letters.length>0&&<div style={{fontSize:12,color:'var(--text2)',padding:'4px 12px',background:'var(--bg3)',borderRadius:20,border:'1px solid var(--border)'}}>
              <strong style={{color:'var(--green)'}}>{(totalSavedMonths/12).toFixed(1)} yrs</strong> saved across {letters.filter(l=>l.saved).length} letter{letters.filter(l=>l.saved).length!==1?'s':''}
            </div>}
            <input ref={fileRef} type="file" accept="application/pdf" style={{display:'none'}} onChange={e=>uploadLetter(e.target.files[0])}/>
            <button onClick={()=>fileRef.current?.click()} disabled={uploading} style={{fontSize:11,padding:'5px 14px',background:uploading?'var(--bg3)':'var(--green-dim)',color:uploading?'var(--text3)':'var(--green)',border:uploading?'1px solid var(--border)':'1px solid #34d39944',borderRadius:20,cursor:uploading?'default':'pointer',display:'flex',alignItems:'center',gap:6}}>
              {uploading?<><div style={{width:10,height:10,border:'1.5px solid currentColor',borderTopColor:'transparent',borderRadius:'50%',animation:'spin 0.7s linear infinite'}}/>  Extracting…</>:<>+ Upload Letter</>}
            </button>
            <button onClick={onClose} style={{background:'var(--bg3)',border:'1px solid var(--border)',borderRadius:8,color:'var(--text2)',cursor:'pointer',padding:'5px 12px',fontSize:12}}>✕ Close</button>
          </div>
        </div>
        {uploadErr&&<div style={{padding:'8px 24px',background:'var(--red-dim)',color:'var(--red)',fontSize:12,flexShrink:0}}>{uploadErr}</div>}

        {/* Letter tabs */}
        {letters.length>0&&(
          <div style={{display:'flex',gap:6,padding:'10px 24px',borderBottom:'1px solid var(--border)',background:'var(--bg2)',flexShrink:0,overflowX:'auto'}}>
            {letters.map((l,i)=>(
              <button key={i} onClick={()=>switchLetter(i)} style={{fontSize:11,padding:'4px 14px',borderRadius:20,cursor:'pointer',whiteSpace:'nowrap',background:activeIdx===i?'var(--amber-dim)':'var(--bg3)',color:activeIdx===i?'var(--amber)':'var(--text3)',border:activeIdx===i?'1px solid #f59e0b44':'1px solid var(--border)',fontWeight:activeIdx===i?600:400}}>
                {l.employerName||l.fileName||`Letter ${i+1}`}{l.months!=null&&<span style={{marginLeft:6,opacity:.7}}>{l.months}mo</span>}{l.saved&&<span style={{marginLeft:4,color:'var(--green)'}}>✓</span>}
              </button>
            ))}
          </div>
        )}

        {/* Columns */}
        <div style={{display:'flex',flex:1,overflow:'hidden',minHeight:0}}>
          {/* Left — PWD */}
          <div style={{flex:'0 0 42%',overflow:'auto',padding:'20px 24px',borderRight:'1px solid var(--border)'}}>
            <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:8}}>PWD — Minimum Requirements</div>
            {pwdText
              ?<pre style={{margin:0,whiteSpace:'pre-wrap',wordBreak:'break-word',fontFamily:"'DM Mono',monospace",fontSize:12,lineHeight:1.8,color:'var(--text)'}}>
                <ExpHighlightedText text={pwdText} keywords={highlightWords}/>
              </pre>
              :<div style={{color:'var(--text3)',fontSize:13,fontStyle:'italic'}}>No requirements text — paste the Minimum Requirements on the main page first.</div>
            }
          </div>

          {/* Right — Letter */}
          <div style={{flex:1,display:'flex',flexDirection:'column',overflow:'hidden'}}>
            {!activeLetter&&(
              <div style={{flex:1,display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',padding:40,color:'var(--text3)'}}>
                <div style={{fontSize:32,marginBottom:12}}>📄</div>
                <div style={{fontSize:14,marginBottom:6}}>No letters uploaded yet</div>
                <div style={{fontSize:12}}>Click <strong>+ Upload Letter</strong> to add an experience verification letter PDF.</div>
              </div>
            )}
            {activeLetter&&(
              <>
                {/* Metadata bar */}
                <div style={{padding:'12px 24px',borderBottom:'1px solid var(--border)',background:'var(--bg2)',flexShrink:0,display:'flex',gap:16,alignItems:'center',flexWrap:'wrap'}}>
                  <div><div style={{fontSize:10,color:'var(--text3)',marginBottom:2}}>Employer</div><div style={{fontSize:13,fontWeight:600,color:'var(--text)'}}>{activeLetter.employerName||'—'}</div></div>
                  <div><div style={{fontSize:10,color:'var(--text3)',marginBottom:2}}>Title</div><div style={{fontSize:13,color:'var(--text)'}}>{activeLetter.jobTitle||'—'}</div></div>
                  <div><div style={{fontSize:10,color:'var(--text3)',marginBottom:2}}>Period</div><div style={{fontSize:13,color:'var(--text)'}}>{activeLetter.startDate||'?'} – {activeLetter.endDate||'?'}</div></div>
                  {activeLetter.months!=null&&<div style={{padding:'4px 14px',borderRadius:20,background:'var(--amber-dim)',border:'1px solid #f59e0b44',color:'var(--amber)',fontSize:12,fontWeight:600}}>{activeLetter.months} mo ({(activeLetter.months/12).toFixed(1)} yrs)</div>}
                  <div style={{marginLeft:'auto',display:'flex',gap:8,alignItems:'center'}}>
                    {!activeLetter.saved
                      ?<button onClick={()=>onSaveLetter({...activeLetter,saved:true},activeIdx)} style={{fontSize:11,padding:'5px 14px',background:'var(--green-dim)',color:'var(--green)',border:'1px solid #34d39944',borderRadius:20,cursor:'pointer'}}>✓ Save Time</button>
                      :<span style={{fontSize:11,padding:'5px 10px',color:'var(--green)'}}>✓ Time saved</span>
                    }
                    <button onClick={()=>{onRemoveLetter(activeIdx);setActiveIdx(Math.max(0,activeIdx-1));}} style={{fontSize:11,padding:'5px 10px',background:'var(--red-dim)',color:'var(--red)',border:'1px solid #f8717144',borderRadius:20,cursor:'pointer'}}>✕</button>
                  </div>
                </div>

                {/* Keyword check panel */}
                {kwResults.length>0&&(
                  <div style={{padding:'12px 24px',borderBottom:'1px solid var(--border)',background:'var(--bg2)',flexShrink:0}}>
                    <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:8}}>Requirements Keyword Check</div>
                    <div style={{display:'flex',flexWrap:'wrap',gap:6}}>
                      {kwResults.map(({word,found})=>(
                        <span key={word} style={{
                          fontSize:11,padding:'2px 10px',borderRadius:20,fontWeight:500,
                          background:found?'var(--green-dim)':'var(--red-dim)',
                          color:found?'var(--green)':'var(--red)',
                          border:found?'1px solid #34d39944':'1px solid #f8717144',
                        }}>
                          {found?'✓':'✗'} {word}
                        </span>
                      ))}
                    </div>
                    <div style={{marginTop:8,fontSize:11,color:'var(--text3)'}}>
                      {kwResults.filter(r=>r.found).length} of {kwResults.length} requirement keywords found in this letter
                    </div>
                  </div>
                )}

                {/* Letter text */}
                <div style={{flex:1,overflow:'auto',padding:'20px 24px'}}>
                  <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:8}}>Letter Text</div>
                  <pre style={{margin:0,whiteSpace:'pre-wrap',wordBreak:'break-word',fontFamily:"'DM Mono',monospace",fontSize:12,lineHeight:1.8,color:'var(--text)'}}>
                    <ExpHighlightedText text={activeLetter.fullText||activeLetter.duties||'No text extracted.'} keywords={highlightWords}/>
                  </pre>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Equal Pay Transparency (EPT) data ────────────────────────────────────────
// Source: AILA Practice Pointer, Guide to Equal Pay Transparency Laws (Oct 2025)
// AILA Doc. No. 25110603
const EPT_DATA = {
  'CA': {
    state:'California', effectiveDate:'01/01/2023', citation:'SB 1162; Cal. Labor Code § 432.3',
    employerThreshold:'15+ employees (even if only 1 is in CA)',
    wagReq:'Pay scale (min/max salary or hourly range). No bonuses or benefits required. SB 642 (10/08/2025) revised definition to "good-faith estimate."',
    postingReq:'Pay scale must be included in all job postings (internal and external).',
    benefitsReq:false,
    longArm:true, longArmNote:'May apply to nationwide remote postings even without CA office if employer has 15+ employees.',
    remoteCoverage:'Remote jobs outside CA where worker reports to a CA supervisor or work site.',
    notes:'',
  },
  'CO': {
    state:'Colorado', effectiveDate:'01/01/2021', citation:'Equal Pay for Equal Work Act (EPEWA); POST Rules, 7 CCR 1103-18 (eff. 07/01/2024)',
    employerThreshold:'1+ employee in Colorado',
    wagReq:'Min/max annual or hourly range. General description of bonuses, commissions, and major benefits required.',
    postingReq:'Required for each new job, promotion, transfer, or other employment opportunity. Public and internal postings.',
    benefitsReq:true,
    longArm:false,
    remoteCoverage:'Remote jobs outside CO covered if employer has CO employees. Does not apply to jobs performed entirely outside CO.',
    notes:'Benefits and bonus description required — more than most states.',
  },
  'HI': {
    state:'Hawaii', effectiveDate:'01/01/2024', citation:'ACT 203 (SB1057), Hawaii Equal Pay Act',
    employerThreshold:'50+ employees (within or outside Hawaii)',
    wagReq:'Salary range or hourly rate reasonably reflecting actual expected compensation.',
    postingReq:'Any "job listing" (not specifically defined).',
    benefitsReq:false,
    longArm:false,
    remoteCoverage:'Not specified.',
    notes:'Excludes internal transfers/promotions and public jobs under collective bargaining.',
  },
  'IL': {
    state:'Illinois', effectiveDate:'01/01/2025', citation:'820 ILCS 112/ — Equal Pay Act of 2003',
    employerThreshold:'15+ employees (within or outside Illinois)',
    wagReq:'Wage/salary or range. General description of benefits, bonuses, stock options, and other incentives.',
    postingReq:'Any specific job posting. A hyperlink to the pay/benefits information is acceptable.',
    benefitsReq:true,
    longArm:false,
    remoteCoverage:'Jobs performed outside IL covered if employee reports to an IL supervisor, office, or work site.',
    notes:'Benefits and bonus description required.',
  },
  'MD': {
    state:'Maryland', effectiveDate:'10/01/2024', citation:'HB 649 and SB 525',
    employerThreshold:'Employers of any size',
    wagReq:'Min/max hourly rate or salary. No open-ended ranges (e.g., "up to $100k" not permitted). Other compensation excluded.',
    postingReq:'All job postings, internal and external. If multiple locations/seniority levels, separate range per location/level. Employer must complete and post a benefits/compensation form (link acceptable).',
    benefitsReq:true,
    longArm:false,
    remoteCoverage:'Jobs physically performed at least partially in MD. Occasional work in state (e.g., meetings) excluded.',
    notes:'Applies to employers of any size — lowest threshold among covered states. Form available at labor.maryland.gov.',
  },
  'MA': {
    state:'Massachusetts', effectiveDate:'10/29/2025', citation:'An Act Relative to Salary Range Transparency (H.4890)',
    employerThreshold:'25+ employees with primary place of work in MA (prior calendar year average)',
    wagReq:'"Pay range" = salary or hourly range employer reasonably and in good faith expects to pay. Bonuses/commissions not required.',
    postingReq:'Any advertisement or job posting intended to recruit for a specific position.',
    benefitsReq:false,
    longArm:false,
    remoteCoverage:'All positions where primary place of work is MA, including remote workers with MA primary worksite.',
    notes:'Very recently effective (10/29/2025). EEO reporting data may also be required.',
  },
  'MN': {
    state:'Minnesota', effectiveDate:'01/01/2025', citation:'CHAPTER 110 — S.F. No. 3852, Article 7',
    employerThreshold:'30+ employees at one or more MN work sites',
    wagReq:'Starting salary range or fixed pay rate (no open-ended ranges). General description of all benefits and other compensation including health and retirement.',
    postingReq:'Any solicitation intended to recruit applicants, electronic or printed, that includes qualifications.',
    benefitsReq:true,
    longArm:false,
    remoteCoverage:'Not specified.',
    notes:'Benefits description required.',
  },
  'NJ': {
    state:'New Jersey', effectiveDate:'06/01/2025', citation:'P.L. 2024, c. 91',
    employerThreshold:'10+ employees over 20 calendar weeks. Applies to employers doing business in NJ, employing people in NJ, or taking applications from NJ residents.',
    wagReq:'Hourly wage or salary, or range. General description of benefits and other compensation for first 12 months. Vague language like "great benefits offered" or "health insurance and more" not permitted.',
    postingReq:'All job postings, promotions, new jobs, and transfers, internal and external.',
    benefitsReq:true,
    longArm:true, longArmNote:'Applies to out-of-state employers incorporated/headquartered in NJ, with NJ employees, NJ contracts/sales, or NJ applicants.',
    remoteCoverage:'Covered if employer takes applications from NJ residents.',
    notes:'Very recently effective (06/01/2025). Long-arm reach for out-of-state employers.',
  },
  'NY': {
    state:'New York', effectiveDate:'09/17/2023', citation:'N.Y. Lab. Law § 194-b',
    employerThreshold:'4+ employees (not required to be in NY)',
    wagReq:'Actual compensation or min/max annual or hourly range. Excludes benefits and bonuses. Good-faith basis at time of posting.',
    postingReq:'Each single new job, promotion, or transfer opportunity, per location.',
    benefitsReq:false,
    longArm:false,
    remoteCoverage:'Remote jobs outside NY where worker reports to a NY supervisor, officer, or work site.',
    notes:'Lowest employee threshold (4+) among covered states.',
  },
  'VT': {
    state:'Vermont', effectiveDate:'07/01/2025', citation:'Act 155 (H.704)',
    employerThreshold:'5+ employees, at least one of whom works in Vermont',
    wagReq:'Min/max annual salary or hourly range (good-faith expectation). Commission-based jobs must state that range cannot be posted. Tipped jobs must disclose base wage.',
    postingReq:'Any written notice in any format for a specific job opening.',
    benefitsReq:false,
    longArm:false,
    remoteCoverage:'Remote positions predominantly performing work for a VT-based office or location.',
    notes:'Recently effective (07/01/2025). Employer may hire outside posted range due to applicant qualifications or market factors.',
  },
  'DC': {
    state:'Washington, D.C.', effectiveDate:'06/20/2024', citation:'D.C. Act 25-367; Wage Transparency Omnibus Amendment Act of 2023',
    employerThreshold:'1+ employee in DC (excludes DC/Federal Government as employer)',
    wagReq:'Min/max projected salary or hourly pay. Good-faith range from lowest to highest the employer believes it would pay.',
    postingReq:'All job listings and position descriptions advertised, regardless of how or where created/shared.',
    benefitsReq:false,
    longArm:false,
    remoteCoverage:'All postings soliciting DC employees.',
    notes:'Very broad coverage — applies to any posting soliciting DC workers, any size employer.',
  },
  'WA': {
    state:'Washington State', effectiveDate:'01/01/2023', citation:'RCW 49.58.110; Amended SSB 5408',
    employerThreshold:'15+ employees, with at least 1 WA-based employee',
    wagReq:'Opening wage scale or salary range (or fixed wage if no range). Min/max without open-ended phrases. General description of all benefits and other compensation.',
    postingReq:'Job postings for new jobs, promotions, or transfers. Any written medium (print or electronic), managed by employer or third party.',
    benefitsReq:true,
    longArm:false,
    remoteCoverage:'Any position that could be filled by a WA-based employee, including remote work. No disclosure needed for jobs performed entirely outside WA.',
    notes:'Benefits description required. If no existing range, create one before publishing.',
  },
};

// State abbreviation aliases (DC needs special handling)
const EPT_STATE_ALIASES = {
  'WASHINGTON DC':'DC','WASHINGTON D.C.':'DC','D.C.':'DC',
  'DISTRICT OF COLUMBIA':'DC','CALIFORNIA':'CA','COLORADO':'CO',
  'HAWAII':'HI','ILLINOIS':'IL','MARYLAND':'MD','MASSACHUSETTS':'MA',
  'MINNESOTA':'MN','NEW JERSEY':'NJ','NEW YORK':'NY','VERMONT':'VT',
  'WASHINGTON':'WA','WASHINGTON STATE':'WA',
};

function lookupEpt(stateVal, city) {
  if (!stateVal) return null;
  const s = stateVal.trim().toUpperCase();
  // Try 2-letter code first
  if (EPT_DATA[s]) return EPT_DATA[s];
  // Try alias
  const aliased = EPT_STATE_ALIASES[s];
  if (aliased && EPT_DATA[aliased]) return EPT_DATA[aliased];
  // Special case: Washington could be state or DC
  if (s === 'WA' || s === 'WASHINGTON STATE') return EPT_DATA['WA'];
  if (city && /washington.*d\.?c\.?|district.*columbia/i.test(city)) return EPT_DATA['DC'];
  return null;
}

function EptCard({ stateVal, city, telecommute, wageFrom, wageTo }) {
  const ept = lookupEpt(stateVal, city);

  const hasRange = wageFrom && wageTo && wageFrom.trim() && wageTo.trim();

  if (!stateVal || !stateVal.trim()) {
    return (
      <div style={{...PS.card, marginBottom:20, opacity:0.5}}>
        {cardHeaderStatic('Equal Pay Transparency', 'EPT Wage Posting Requirements', null)}
        <div style={{fontSize:12, color:'var(--text3)', fontStyle:'italic'}}>Enter a state in Case Inputs to check EPT requirements.</div>
      </div>
    );
  }

  if (!ept) {
    return (
      <div style={{...PS.card, marginBottom:20}}>
        {cardHeaderStatic('Equal Pay Transparency', 'EPT Wage Posting Requirements', true)}
        <div style={{fontSize:12, color:'var(--text2)'}}>
          <span style={{color:'var(--green)', fontWeight:600}}>No EPT law on record</span> for <strong>{stateVal}</strong> based on AILA's October 2025 guide. Verify independently — laws are frequently updated.
        </div>
      </div>
    );
  }

  const rangeFlag = ept && hasRange ? null : (ept ? false : null);

  return (
    <div style={{...PS.card, marginBottom:20}}>
      {cardHeaderStatic('Equal Pay Transparency', `EPT Requirements — ${ept.state}`, hasRange ? true : null)}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:16, marginBottom:14}}>
        <div>
          <div style={{fontSize:10, fontWeight:600, color:'var(--text3)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>Effective Date</div>
          <div style={{fontSize:13, color:'var(--text)'}}>{ept.effectiveDate}</div>
        </div>
        <div>
          <div style={{fontSize:10, fontWeight:600, color:'var(--text3)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>Covered Employers</div>
          <div style={{fontSize:13, color:'var(--text)'}}>{ept.employerThreshold}</div>
        </div>
      </div>

      <div style={{display:'grid', gap:10, marginBottom:14}}>
        <div style={{padding:'10px 12px', borderRadius:'var(--radius)', background:'var(--bg3)', border:'1px solid var(--border)'}}>
          <div style={{fontSize:10, fontWeight:600, color:'var(--text3)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>Posting Requirement</div>
          <div style={{fontSize:12, color:'var(--text2)', lineHeight:1.6}}>{ept.postingReq}</div>
        </div>
        <div style={{padding:'10px 12px', borderRadius:'var(--radius)', background: hasRange?'var(--green-dim)':'var(--amber-dim)', border:`1px solid ${hasRange?'#34d39944':'#f59e0b44'}`}}>
          <div style={{fontSize:10, fontWeight:600, color: hasRange?'var(--green)':'var(--amber)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>
            Wage Range Requirement {hasRange ? '✓ Range entered' : '⚠ No range entered yet'}
          </div>
          <div style={{fontSize:12, color:'var(--text2)', lineHeight:1.6}}>{ept.wagReq}</div>
        </div>
        {ept.benefitsReq && (
          <div style={{padding:'10px 12px', borderRadius:'var(--radius)', background:'var(--amber-dim)', border:'1px solid #f59e0b44'}}>
            <div style={{fontSize:10, fontWeight:600, color:'var(--amber)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>⚠ Benefits Description Required</div>
            <div style={{fontSize:12, color:'var(--text2)', lineHeight:1.6}}>This state requires a general description of benefits and other compensation in job postings, not just a wage range.</div>
          </div>
        )}
        {ept.longArm && (
          <div style={{padding:'10px 12px', borderRadius:'var(--radius)', background:'var(--red-dim)', border:'1px solid #f8717144'}}>
            <div style={{fontSize:10, fontWeight:600, color:'var(--red)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>⚠ Long-Arm Reach</div>
            <div style={{fontSize:12, color:'var(--text2)', lineHeight:1.6}}>{ept.longArmNote}</div>
          </div>
        )}
        {telecommute === 'yes' && ept.remoteCoverage && (
          <div style={{padding:'10px 12px', borderRadius:'var(--radius)', background:'var(--bg3)', border:'1px solid var(--border)'}}>
            <div style={{fontSize:10, fontWeight:600, color:'var(--text3)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>Remote / WFH Coverage</div>
            <div style={{fontSize:12, color:'var(--text2)', lineHeight:1.6}}>{ept.remoteCoverage}</div>
          </div>
        )}
        {ept.notes && (
          <div style={{fontSize:11, color:'var(--text3)', fontStyle:'italic', paddingTop:4}}>{ept.notes}</div>
        )}
      </div>
      <div style={{fontSize:10, color:'var(--text3)', borderTop:'1px solid var(--border)', paddingTop:10}}>
        Source: AILA Practice Pointer — Guide to Equal Pay Transparency Laws (Oct 2025), Doc. No. 25110603. Laws change frequently — verify with local employment counsel before recruitment.
      </div>
    </div>
  );
}

// Standalone cardHeader used outside PermComparer (no closure over local vars)
function cardHeaderStatic(kicker, title, match) {
  return (
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:14}}>
      <div>
        <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:4}}>{kicker}</div>
        <div style={{fontSize:14,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>{title}</div>
      </div>
      <span style={{display:'inline-flex',alignItems:'center',gap:5,fontSize:11,fontWeight:500,padding:'3px 8px',borderRadius:4,
        background: match===null?'var(--bg4)':match?'var(--green-dim)':'var(--red-dim)',
        color: match===null?'var(--text2)':match?'var(--green)':'var(--red)',
      }}>
        {match===null?'Not Checked':match?'Law in Effect — Compliant':'Law in Effect'}
      </span>
    </div>
  );
}

function PermComparer(){
  const [jobTitle,setJobTitle]=useState('');
  const [city,setCity]=useState('');
  const [stateVal,setStateVal]=useState('');
  const [telecommute,setTelecommute]=useState('no');
  const [jdRef,setJdRef]=useState('');
  const [jdCmp,setJdCmp]=useState('');
  const [mrRef,setMrRef]=useState('');
  const [mrCmp,setMrCmp]=useState('');
  const [primDeg,setPrimDeg]=useState('');
  const [secDeg,setSecDeg]=useState('');
  const [travel,setTravel]=useState('');
  const [strict,setStrict]=useState(false);
  const [ignoreFmt,setIgnoreFmt]=useState(false);
  const [pwdWage,setPwdWage]=useState('');
  const [wageFrom,setWageFrom]=useState('');
  const [wageTo,setWageTo]=useState('');
  const [results,setResults]=useState(null);
  const [expLetters,setExpLetters]=useState([]);
  const [showExpModal,setShowExpModal]=useState(false);
  const [droppedLetter,setDroppedLetter]=useState(null);

  const compare=()=>setResults({
    jd:pSummarize('Job Description',jdRef,jdCmp,strict,ignoreFmt),
    mr:pSummarize('Minimum Requirements',mrRef,mrCmp,strict,ignoreFmt),
  });
  const [pwdLoading,setPwdLoading]=useState(false);
  const [pwdError,setPwdError]=useState('');
  const pwdInputRef=useRef(null);

  const handleSaveLetter=(letter,idx)=>{
    if(idx===null||idx===undefined){
      setExpLetters(prev=>[...prev,letter]);
    } else {
      setExpLetters(prev=>prev.map((l,i)=>i===idx?letter:l));
    }
  };
  const handleRemoveLetter=(idx)=>setExpLetters(prev=>prev.filter((_,i)=>i!==idx));
  const savedMonths=expLetters.filter(l=>l.saved).reduce((s,l)=>s+(l.months||0),0);

  // Drop a PWD into the Reference box → same as Load PWD button
  const handlePwdDrop = async (file) => {
    setPwdLoading(true); setPwdError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const resp = await fetch('/api/extract-pwd', { method: 'POST', body: fd });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Server error' }));
        throw new Error(err.detail || 'Extraction failed');
      }
      const d = await resp.json();
      if (d.jobTitle) setJobTitle(d.jobTitle);
      if (d.city)     setCity(d.city);
      if (d.stateVal) setStateVal(d.stateVal);
      setTelecommute(d.travel === 'yes' ? 'yes' : 'no');
      if (d.jdRef)   setJdRef(d.jdRef);
      if (d.primDeg) setPrimDeg(d.primDeg);
      if (d.mrRef)   setMrRef(d.mrRef);
      if (d.pwdWage) setPwdWage(d.pwdWage);
    } catch(e) {
      setPwdError('Could not extract PWD: ' + e.message);
    } finally {
      setPwdLoading(false);
    }
  };

  // Drop an experience letter into the Comparison box → parse & store it,
  // put duties text in the box, pre-load it into the modal
  const handleLetterDrop = async (file) => {
    try {
      const fd = new FormData();
      fd.append('file', file);
      const resp = await fetch('/api/extract-experience-letter', { method: 'POST', body: fd });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Server error' }));
        throw new Error(err.detail || 'Extraction failed');
      }
      const parsed = await resp.json();
      const letterObj = { fileName: file.name, ...parsed, saved: false };
      setDroppedLetter(letterObj);
      // Populate the comparison textarea with the letter's duties / full text
      setJdCmp(parsed.duties || parsed.fullText || '');
    } catch(e) {
      throw e; // DropTextarea will surface the error
    }
  };

  const clearAll=()=>{setJobTitle('');setCity('');setStateVal('');setTelecommute('no');setJdRef('');setJdCmp('');setMrRef('');setMrCmp('');setPrimDeg('');setSecDeg('');setTravel('');setPwdWage('');setWageFrom('');setWageTo('');setResults(null);setPwdError('');setExpLetters([]);setShowExpModal(false);setDroppedLetter(null);};

  const loadPwd=async(file)=>{
    if(!file)return;
    setPwdLoading(true);setPwdError('');
    try{
      const fd=new FormData();
      fd.append('file',file);
      const resp=await fetch('/api/extract-pwd',{method:'POST',body:fd});
      if(!resp.ok){
        const err=await resp.json().catch(()=>({detail:'Server error'}));
        throw new Error(err.detail||'Extraction failed');
      }
      const d=await resp.json();
      if(d.jobTitle)setJobTitle(d.jobTitle);
      if(d.city)setCity(d.city);
      if(d.stateVal)setStateVal(d.stateVal);
      setTelecommute(d.travel==='yes'?'yes':'no');
      if(d.jdRef)setJdRef(d.jdRef);
      if(d.primDeg)setPrimDeg(d.primDeg);
      if(d.mrRef)setMrRef(d.mrRef);
      if(d.pwdWage)setPwdWage(d.pwdWage);
    }catch(e){
      setPwdError('Could not extract fields: '+e.message);
    }finally{
      setPwdLoading(false);
      if(pwdInputRef.current)pwdInputRef.current.value='';
    }
  };

  const wageStatus=(()=>{
    const pwd=pParseCur(pwdWage),from=pParseCur(wageFrom),to=pParseCur(wageTo);
    if(pwd===null||from===null||!wageFrom.trim())return{status:'Needs Input',detail:'Enter PWD wage and From wage to validate.',pass:false};
    if(from>pwd)return{status:'Pass',detail:to!==null?`Range ${pFmt(wageFrom)}–${pFmt(wageTo)} starts above PWD ${pFmt(pwdWage)}.`:`From wage ${pFmt(wageFrom)} exceeds PWD ${pFmt(pwdWage)}.`,pass:true};
    return{status:'Flag',detail:`From wage ${pFmt(wageFrom)} must exceed PWD ${pFmt(pwdWage)}.`,pass:false};
  })();

  const pillBtn=(label,active,onClick)=>(
    <button onClick={onClick} style={{fontSize:11,padding:'3px 10px',height:'auto',background:active?'var(--amber-dim)':'var(--bg3)',color:active?'var(--amber)':'var(--text3)',border:active?'1px solid #f59e0b44':'1px solid var(--border)',borderRadius:20,fontWeight:active?500:400,cursor:'pointer'}}>{label}</button>
  );

  const grid2={display:'grid',gridTemplateColumns:'1fr 1fr',gap:20,alignItems:'start'};
  const grid3={display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:16};
  const cardHeader=(kicker,title,match)=>(
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:14}}>
      <div><div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:4}}>{kicker}</div><div style={{fontSize:14,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>{title}</div></div>
      <span style={PS.badge(match)}>{match===null?'Source Text':match?'Exact Match':'Differences Found'}</span>
    </div>
  );

  return(
    <>
    <div style={{height:'100%',overflowY:'auto',padding:'32px 28px 48px',background:'var(--bg)'}}>
      <div style={{maxWidth:1360,margin:'0 auto'}}>

        {/* Hero */}
        <div style={{display:'flex',alignItems:'flex-end',justifyContent:'space-between',gap:24,marginBottom:24}}>
          <div>
            <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:6}}>PERM Labor Certification</div>
            <div style={{fontFamily:"'DM Serif Display',serif",fontSize:'clamp(1.6rem,3vw,2.4rem)',color:'var(--text)',lineHeight:1.1}}>Text Comparison Workspace</div>
            <div style={{fontSize:13,color:'var(--text3)',marginTop:8,maxWidth:600,lineHeight:1.6}}>Compare job description and requirements language, validate PWD wage positioning.</div>
          </div>
          <div style={{display:'flex',flexWrap:'wrap',justifyContent:'flex-end',gap:10,alignItems:'center',flexShrink:0}}>
            {pillBtn('Ignore Formatting',ignoreFmt,()=>setIgnoreFmt(v=>!v))}
            {pillBtn('Strict Mode',strict,()=>setStrict(v=>!v))}
            <input ref={pwdInputRef} type="file" accept="application/pdf" style={{display:'none'}} onChange={e=>loadPwd(e.target.files[0])}/>
          <button onClick={()=>pwdInputRef.current?.click()} disabled={pwdLoading} style={{fontSize:11,padding:'5px 14px',height:'auto',display:'flex',alignItems:'center',gap:6,background:pwdLoading?'var(--bg3)':'var(--green-dim)',color:pwdLoading?'var(--text3)':'var(--green)',border:pwdLoading?'1px solid var(--border)':'1px solid #34d39944',borderRadius:20,cursor:pwdLoading?'default':'pointer',opacity:pwdLoading?0.6:1}}>
            {pwdLoading?<><div style={{width:10,height:10,border:'1.5px solid currentColor',borderTopColor:'transparent',borderRadius:'50%',animation:'spin 0.7s linear infinite'}}/>{' Extracting…'}</>:<><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>{' Load PWD'}</>}
          </button>
          <button onClick={()=>{
            if(droppedLetter&&!expLetters.find(l=>l.fileName===droppedLetter.fileName)){
              setExpLetters(prev=>[...prev,droppedLetter]);
            }
            setShowExpModal(true);
          }} style={{fontSize:11,padding:'5px 14px',height:'auto',display:'flex',alignItems:'center',gap:6,background:'var(--bg3)',color:(expLetters.length>0||droppedLetter)?'var(--amber)':'var(--text2)',border:(expLetters.length>0||droppedLetter)?'1px solid #f59e0b44':'1px solid var(--border)',borderRadius:20,cursor:'pointer'}}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            {' Verify Experience'}{expLetters.length>0&&<span style={{marginLeft:4,padding:'1px 6px',background:'var(--amber)',color:'var(--bg)',borderRadius:10,fontSize:10,fontWeight:700}}>{expLetters.length}</span>}
          </button>
          <button onClick={clearAll} style={{fontSize:11,padding:'5px 14px',height:'auto',background:'var(--bg3)',color:'var(--text3)',border:'1px solid var(--border)',borderRadius:20,cursor:'pointer'}}>Clear All</button>
            <button onClick={compare} className="primary" style={{fontSize:12,padding:'7px 18px'}}>Compare Text</button>
          </div>
        </div>
        {pwdError&&<div style={{margin:'0 0 16px',padding:'10px 14px',background:'var(--red-dim)',color:'var(--red)',borderRadius:'var(--radius)',fontSize:12}}>{pwdError}</div>}

        {/* Case metadata */}
        <div style={{...PS.card,marginBottom:20}}>
          {cardHeader('Case Inputs','Location & Telecommute',null)}
          <div style={{marginBottom:14}}><label style={PS.label}>Job Title</label><input style={PS.input} value={jobTitle} onChange={e=>setJobTitle(e.target.value)}/></div>
          <div style={{...grid3,marginBottom:14}}>
            <div><label style={PS.label}>City</label><input style={PS.input} value={city} onChange={e=>setCity(e.target.value)}/></div>
            <div><label style={PS.label}>State</label><input style={PS.input} value={stateVal} onChange={e=>setStateVal(e.target.value)}/></div>
            <div><label style={PS.label}>Telecommute Language</label>
              <div style={{display:'flex',gap:8}}>
                {['yes','no'].map(v=>(
                  <label key={v} style={{display:'inline-flex',alignItems:'center',gap:6,padding:'6px 10px',borderRadius:10,background:'var(--bg3)',border:'1px solid var(--border)',fontSize:12,color:'var(--text2)',cursor:'pointer'}}>
                    <input type="radio" name="tc" checked={telecommute===v} onChange={()=>setTelecommute(v)} style={{accentColor:'var(--amber)'}}/>{v==='yes'?'Yes':'No'}
                  </label>
                ))}
              </div>
            </div>
          </div>
          <div><label style={PS.label}>Travel Requirement</label><textarea style={{...PS.textarea,minHeight:60}} value={travel} onChange={e=>setTravel(e.target.value)}/></div>
        </div>

        {/* Job Description pair */}
        <div style={{display:'grid',gap:16,marginBottom:20}}>
          <div style={grid2}>
            <div style={PS.cardRef}>
              {cardHeader('Reference','Job Description',null)}
              <label style={PS.label}>Paste the official job description, or drag and drop the PWD (PDF) — fields will populate automatically</label>
              <DropTextarea
                value={jdRef}
                onChange={e=>setJdRef(e.target.value)}
                placeholder="Paste job description text here, or drag and drop a PWD PDF to populate all fields automatically…"
                onPwdDrop={handlePwdDrop}
              />
            </div>
            <div style={PS.card}>
              {cardHeader('Comparison','Job Description Comparison',results?results.jd.exact:null)}
              <label style={PS.label}>Paste comparison text, or drag and drop an experience verification letter (PDF) — then click Verify Experience to check requirements</label>
              <DropTextarea
                value={jdCmp}
                onChange={e=>setJdCmp(e.target.value)}
                placeholder="Paste comparison text here, or drag and drop an experience verification letter PDF…"
                onLetterDrop={handleLetterDrop}
                borderColor={results&&!results.jd.exact?'var(--red)':'var(--border)'}
                background={results&&!results.jd.exact?'var(--red-dim)':'var(--bg)'}
              />
            </div>
          </div>
          {results&&<PermDiffPanel res={results.jd} title="Job Description"/>}
        </div>

        {/* Min Requirements pair */}
        <div style={{display:'grid',gap:16,marginBottom:20}}>
          <div style={grid2}>
            <div style={PS.cardRef}>
              {cardHeader('Reference','Minimum Requirements',null)}
              <div style={{display:'grid',gap:12,marginBottom:14}}>
                <div><label style={PS.label}>Primary Degree</label><textarea style={{...PS.textarea,minHeight:70}} value={primDeg} onChange={e=>setPrimDeg(e.target.value)}/></div>
                <div><label style={PS.label}>Secondary Degree (if any)</label><textarea style={{...PS.textarea,minHeight:70}} value={secDeg} onChange={e=>setSecDeg(e.target.value)}/></div>
              </div>
              <label style={PS.label}>Paste the minimum requirements</label>
              <textarea style={{...PS.textarea,minHeight:260}} value={mrRef} onChange={e=>setMrRef(e.target.value)}/>
            </div>
            <div style={PS.card}>
              {cardHeader('Comparison','Requirements Comparison',results?results.mr.exact:null)}
              <label style={PS.label}>Text to compare against</label>
              <textarea style={{...PS.textarea,minHeight:260,borderColor:results&&!results.mr.exact?'var(--amber)':'var(--border)',background:results&&!results.mr.exact?'var(--amber-dim)':'var(--bg)'}} value={mrCmp} onChange={e=>setMrCmp(e.target.value)}/>
            </div>
          </div>
          {results&&<PermDiffPanel res={results.mr} title="Minimum Requirements"/>}
        </div>

        {/* Wage check */}
        <div style={{...PS.card,marginBottom:20}}>
          {cardHeader('Wage Review','PWD Wage Check',wageStatus.pass?true:wageStatus.status==='Needs Input'?null:false)}
          <div style={grid3}>
            <div><label style={PS.label}>PWD Wage</label><input style={PS.input} placeholder="$0.00" value={pwdWage} onChange={e=>setPwdWage(e.target.value)}/></div>
            <div><label style={PS.label}>From</label><input style={PS.input} placeholder="$0.00" value={wageFrom} onChange={e=>setWageFrom(e.target.value)}/></div>
            <div><label style={PS.label}>To</label><input style={PS.input} placeholder="$0.00" value={wageTo} onChange={e=>setWageTo(e.target.value)}/></div>
          </div>
          <div style={{marginTop:14,padding:'12px 14px',borderRadius:'var(--radius)',background:wageStatus.pass?'var(--green-dim)':'var(--red-dim)',color:wageStatus.pass?'var(--green)':'var(--red)',fontSize:12,fontWeight:500}}>{wageStatus.detail}</div>
        </div>

        {/* EPT checker */}
        <EptCard stateVal={stateVal} city={city} telecommute={telecommute} wageFrom={wageFrom} wageTo={wageTo}/>

        {/* Summary */}
        {results&&(
          <div style={{...PS.card}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:14}}>
              <div><div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:4}}>Summary</div><div style={{fontSize:14,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>Comparison Results</div></div>
              <span style={PS.badge(null)}>{ignoreFmt?'Formatting Ignored':strict?'Strict Mode':'Standard Mode'}</span>
            </div>
            <div style={{display:'grid',gap:10}}>
              {[results.jd,results.mr].map(r=>(
                <div key={r.field} style={{display:'grid',gridTemplateColumns:'minmax(160px,1.1fr) minmax(120px,.7fr) minmax(0,2fr)',gap:12,alignItems:'center',padding:'12px 14px',borderRadius:'var(--radius)',background:'var(--bg3)',fontSize:12}}>
                  <strong style={{color:'var(--text)'}}>{r.field}</strong>
                  <div style={{fontWeight:600,color:r.exact?'var(--green)':'var(--red)'}}>{r.status}</div>
                  <div style={{color:'var(--text2)'}}>{r.detail}</div>
                </div>
              ))}
              <div style={{display:'grid',gridTemplateColumns:'minmax(160px,1.1fr) minmax(120px,.7fr) minmax(0,2fr)',gap:12,alignItems:'center',padding:'12px 14px',borderRadius:'var(--radius)',background:'var(--bg3)',fontSize:12}}>
                <strong style={{color:'var(--text)'}}>Wage Range Validation</strong>
                <div style={{fontWeight:600,color:wageStatus.pass?'var(--green)':'var(--red)'}}>{wageStatus.status}</div>
                <div style={{color:'var(--text2)'}}>{wageStatus.detail}</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
    {showExpModal&&(
      <ExperienceVerificationModal
        pwdText={mrRef}
        requirementsText={mrRef}
        letters={expLetters}
        onClose={()=>setShowExpModal(false)}
        onSaveLetter={handleSaveLetter}
        onRemoveLetter={handleRemoveLetter}
      />
    )}
    </>
  );
}

// ── AAO outcome colors ────────────────────────────────────────────────────────
const AAO_OUTCOME = {
  Sustained: { bg: "var(--green-dim)",  text: "var(--green)",  dot: "#34d399" },
  Dismissed: { bg: "var(--bg4)",        text: "var(--text2)",  dot: "#5a5a68" },
  Remanded:  { bg: "var(--yellow-dim)", text: "#fbbf24",       dot: "#fbbf24" },
  Withdrawn: { bg: "var(--bg4)",        text: "var(--text3)",  dot: "#3a3a3f" },
};

function AaoBadge({ label, small }) {
  const c = AAO_OUTCOME[label] || { bg: "var(--bg4)", text: "var(--text2)", dot: "#5a5a68" };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, background: c.bg, color: c.text, fontSize: small ? 10 : 11, fontWeight: 500, padding: small ? "2px 6px" : "3px 8px", borderRadius: 4, letterSpacing: "0.03em" }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: c.dot, flexShrink: 0 }} />
      {label}
    </span>
  );
}

// ── AAO Search View ───────────────────────────────────────────────────────────
function AAOSearchView({ externalDecisionId, externalQuery, onViewGraph }) {
  const [q, setQ] = useState("");
  const [outcome, setOutcome] = useState("");
  const [formType, setFormType] = useState("");
  const [regulation, setReg] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortBy, setSortBy] = useState("relevance");
  const [advOpen, setAdvOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [activeQuery, setActiveQuery] = useState("");
  const [precId, setPrecId] = useState(null);
  const [precedentMap, setPrecedentMap] = useState({});
  const [matchedPrecedents, setMatchedPrecedents] = useState([]);
  const inputRef = useRef(null);
  const FORM_TYPES = ["I-140","I-360","I-601","I-601A","I-129","I-290B","I-821","I-485","I-526","I-131"];

  useEffect(() => {
    fetch(`${API}/precedents/map`).then(r => r.json()).then(setPrecedentMap).catch(() => {});
  }, []);
  useEffect(() => { if (!searched) inputRef.current?.focus(); }, [searched]);
  useEffect(() => {
    if (externalDecisionId) {
      setSelectedId(externalDecisionId);
      setSearched(true);
      if (externalQuery !== undefined) setActiveQuery(externalQuery || "");
    }
  }, [externalDecisionId, externalQuery]);

  const advancedCount = [regulation, dateFrom, dateTo, formType].filter(Boolean).length + (sortBy !== "relevance" ? 1 : 0);

  const search = useCallback(async (pg = 1) => {
    setLoading(true); setSearched(true); setSelectedId(null);
    const p = new URLSearchParams({ page: pg, page_size: 20 });
    if (q) p.set("q", q);
    if (outcome) p.set("outcome", outcome);
    if (formType) p.set("form_type", formType);
    if (regulation) p.set("regulation", regulation);
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    if (sortBy !== "relevance") p.set("sort_by", sortBy);
    // Fire precedent search in parallel — only on page 1, only for text queries
    if (pg === 1 && q.trim()) {
      fetch(`${API}/precedents/search?q=${encodeURIComponent(q.trim())}&limit=4`)
        .then(r => r.json()).then(setMatchedPrecedents).catch(() => setMatchedPrecedents([]));
    } else if (pg === 1) {
      setMatchedPrecedents([]);
    }
    try {
      const res = await fetch(`${API}/aao/search?${p}`);
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      setResults(data); setPage(pg);
      setActiveQuery(q);
    } catch (err) {
      console.error("AAO search failed:", err);
      setResults({ total: 0, page: pg, page_size: 20, results: [], error: err.message });
    } finally {
      setLoading(false);
    }
    setActiveQuery(q);
  }, [q, outcome, formType, regulation, dateFrom, dateTo, sortBy]);

  const splitView = !!selectedId && (searched || !!externalDecisionId);

  return (
    <div className="search-view-root" style={{ height: "100%", display: "flex", overflow: "hidden" }}>
      <div className="search-list-panel" style={{ display: "flex", flexDirection: "column", overflow: "hidden", width: splitView ? 340 : "100%", flexShrink: 0, borderRight: splitView ? "1px solid var(--border)" : "none", transition: "width 0.25s ease" }}>
        <div style={{ padding: searched ? "12px 16px" : "0", flex: searched ? "0 0 auto" : "1", display: "flex", flexDirection: "column", justifyContent: searched ? "flex-start" : "center", alignItems: "center", borderBottom: searched ? "1px solid var(--border)" : "none" }}>
          {!searched && (
            <div style={{ marginBottom: 28, textAlign: "center" }}>
              <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 28, color: "var(--text)", marginBottom: 6 }}>AAO Decisions</div>
              <div style={{ fontSize: 13, color: "var(--text3)" }}>165,597 decisions indexed</div>
            </div>
          )}
          <div style={{ width: "100%", maxWidth: searched ? "100%" : 680, padding: searched ? 0 : "0 24px" }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <div style={{ position: "relative", flex: 1 }}>
                <svg style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text3)", pointerEvents: "none" }} width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && search(1)} placeholder={searched ? "New search… (use \"quotes\" -exclude OR)" : "Search AAO decisions, form types, INA sections… (use \"quotes\" -exclude OR)"} style={{ paddingLeft: 30, fontSize: searched ? 13 : 14, height: searched ? 36 : 42 }} />
              </div>
              <button onClick={() => search(1)} className="primary" style={{ height: searched ? 36 : 42, padding: "0 14px", fontSize: searched ? 13 : 14 }}>Search</button>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              {["Sustained","Dismissed","Remanded","Withdrawn"].map(o => (
                <button key={o} onClick={() => setOutcome(outcome === o ? "" : o)} style={{ fontSize: 11, padding: "3px 10px", height: "auto", background: outcome === o ? (AAO_OUTCOME[o]?.bg || "var(--bg3)") : "var(--bg3)", color: outcome === o ? (AAO_OUTCOME[o]?.text || "var(--text)") : "var(--text3)", border: outcome === o ? `1px solid ${AAO_OUTCOME[o]?.dot || "#fff"}44` : "1px solid var(--border)", borderRadius: 20, fontWeight: outcome === o ? 500 : 400, transition: "all 0.12s" }}>{o}</button>
              ))}
              <div style={{ flex: 1 }} />
              <button onClick={() => setAdvOpen(o => !o)} style={{ fontSize: 11, padding: "3px 10px", height: "auto", background: advOpen || advancedCount > 0 ? "var(--amber-dim)" : "var(--bg3)", color: advOpen || advancedCount > 0 ? "var(--amber)" : "var(--text3)", border: advOpen || advancedCount > 0 ? "1px solid #f59e0b44" : "1px solid var(--border)", borderRadius: 20, display: "flex", alignItems: "center", gap: 5 }}>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="4" y1="6" x2="20" y2="6"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="11" y1="18" x2="13" y2="18"/></svg>
                Advanced{advancedCount > 0 ? ` (${advancedCount})` : ""}
              </button>
            </div>
            {advOpen && (
              <div style={{ marginTop: 10, padding: "14px 16px", background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)" }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>Advanced Search</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
                  <div><label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Form type</label>
                    <select value={formType} onChange={e => setFormType(e.target.value)} style={{ fontSize: 12 }}><option value="">Any form</option>{FORM_TYPES.map(f => <option key={f} value={f}>{f}</option>)}</select></div>
                  <div><label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>INA section / regulation</label>
                    <input value={regulation} onChange={e => setReg(e.target.value)} placeholder="e.g. 203(b)(1)(A)" style={{ fontSize: 12 }} /></div>
                  <div><label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Date from</label>
                    <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} style={{ fontSize: 12 }} /></div>
                  <div><label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Date to</label>
                    <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} style={{ fontSize: 12 }} /></div>
                </div>
                <div style={{ marginBottom: 12 }}>
                  <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Sort by</label>
                  <select value={sortBy} onChange={e => setSortBy(e.target.value)} style={{ fontSize: 12, width: "50%" }}><option value="relevance">Relevance</option><option value="date_desc">Newest first</option><option value="date_asc">Oldest first</option></select>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <button onClick={() => { setReg(""); setDateFrom(""); setDateTo(""); setFormType(""); setSortBy("relevance"); }} style={{ fontSize: 11, color: "var(--text3)", background: "none", border: "none", padding: 0, cursor: "pointer" }}>Clear all</button>
                  <button onClick={() => { search(1); setAdvOpen(false); }} className="primary" style={{ fontSize: 12, padding: "6px 16px" }}>Apply &amp; search</button>
                </div>
              </div>
            )}
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && <Spinner />}
          {!loading && searched && matchedPrecedents.length > 0 && (
            <div style={{ borderBottom: "1px solid var(--border)" }}>
              <div style={{ padding: splitView ? "8px 12px 4px" : "10px 24px 4px", fontSize: 10, fontWeight: 600, color: "#f59e0b", fontFamily: "'DM Mono', monospace", letterSpacing: "0.08em", textTransform: "uppercase", display: "flex", alignItems: "center", gap: 6 }}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="#f59e0b"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                I&amp;N Dec. Precedents
              </div>
              {matchedPrecedents.map(p => (
                <div key={p.id} onClick={() => { setSelectedId(p.id); setPrecId(null); }}
                  style={{ padding: splitView ? "8px 12px" : "10px 24px", cursor: "pointer", display: "flex", alignItems: "flex-start", gap: 10, borderLeft: "2px solid #f59e0b44", transition: "background 0.1s" }}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{p.party_name}</span>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "#f59e0b", fontWeight: 500 }}>{p.citation}</span>
                      {p.year && <span style={{ fontSize: 11, color: "var(--text3)" }}>{p.year}</span>}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 2 }}>
                      {p.decision_type === "adopted" ? "Adopted Decision" : "I&N Dec. Precedent"}
                      {p.cited_by_count > 0 && <span style={{ marginLeft: 8, color: "#f59e0b88" }}>cited {p.cited_by_count.toLocaleString()}× in AAO decisions</span>}
                    </div>
                  </div>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2" opacity="0.5" style={{ flexShrink: 0, marginTop: 2 }}><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              ))}
            </div>
          )}
          {!loading && searched && results && (<>
            <div style={{ padding: splitView ? "6px 12px" : "8px 24px", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace", letterSpacing: "0.05em" }}>{results.total?.toLocaleString()} DECISIONS</div>
            {results.results?.map((r, i) => (<AAOResultRow key={r.id} row={r} selected={r.id === selectedId} compact={splitView} onSelect={() => { setSelectedId(r.id); setPrecId(null); }} index={i} activeQuery={activeQuery} />))}
            {results.total > 20 && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: splitView ? "10px 12px" : "14px 24px", borderTop: "1px solid var(--border)" }}>
                <button onClick={() => search(page - 1)} disabled={page <= 1} style={{ opacity: page <= 1 ? 0.3 : 1, fontSize: 12 }}>←</button>
                <span style={{ flex: 1, textAlign: "center", fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{page} / {Math.ceil(results.total / 20)}</span>
                <button onClick={() => search(page + 1)} disabled={page * 20 >= results.total} style={{ opacity: page * 20 >= results.total ? 0.3 : 1, fontSize: 12 }}>→</button>
              </div>
            )}
            {results.results?.length === 0 && <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text3)", fontSize: 13 }}>No decisions found.</div>}
          </>)}
        </div>
      </div>
      {splitView && (
        <div className="search-detail-panel" style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", animation: "fadeUp 0.18s ease" }}>
          <AAODecisionDetail decisionId={selectedId} query={activeQuery} precedentMap={precedentMap}
            onNavigate={(id) => setSelectedId(id)}
            onViewGraph={onViewGraph} />
        </div>
      )}
    </div>
  );
}

function AAOResultRow({ row, onSelect, selected, compact, index, activeQuery }) {
  return (
    <div className="fade-up" onClick={onSelect} style={{ padding: compact ? "10px 12px" : "14px 24px", borderBottom: "1px solid var(--border)", borderLeft: selected ? "2px solid var(--blue)" : "2px solid transparent", cursor: "pointer", background: selected ? "var(--bg3)" : "transparent", animationDelay: `${index * 20}ms`, transition: "background 0.1s" }}
      onMouseEnter={e => { if (!selected) e.currentTarget.style.background = "var(--bg2)"; }}
      onMouseLeave={e => { if (!selected) e.currentTarget.style.background = "transparent"; }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
        {row.form_type && <span style={{ fontFamily: "'DM Mono', monospace", fontSize: compact ? 10 : 11, color: selected ? "var(--blue)" : "var(--text3)" }}>{row.form_type}</span>}
        {row.outcome && <AaoBadge label={row.outcome} small />}
        {!compact && row.decision_date && <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{row.decision_date}</span>}
      </div>
      {row.title && <div style={{ fontSize: compact ? 12 : 13, fontWeight: 500, color: "var(--text)", marginBottom: 2, lineHeight: 1.3 }}>{row.title}</div>}
      {!compact && row.regulation && <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 4 }}>{row.regulation}</div>}
      {!compact && row.headline && <div style={{ fontSize: 11, color: "var(--text3)", lineHeight: 1.6, marginTop: 4 }} dangerouslySetInnerHTML={{ __html: row.headline }} />}
      {compact && row.decision_date && <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 2, fontFamily: "'DM Mono', monospace" }}>{row.decision_date}</div>}
    </div>
  );
}

function PrecedentDetail({ id, onClose, onViewGraph, showGraphButton }) {
  const { data, loading } = useFetch(id ? `${API}/precedents/${id}` : null);
  if (loading) return <div style={{ padding: 40, textAlign: "center" }}><Spinner /></div>;
  if (!data) return null;

  const isAdopted = data.decision_type === "adopted";
  const accentColor = isAdopted ? "var(--amber)" : "var(--blue)";
  const badge = isAdopted ? "Adopted" : "Precedent";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Header */}
      <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: accentColor, letterSpacing: "0.06em", textTransform: "uppercase" }}>{badge}</span>
            {data.year && <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{data.year}</span>}
            {data.body && <span style={{ fontSize: 11, color: "var(--text3)" }}>{data.body}</span>}
          </div>
          <div style={{ fontSize: 18, fontWeight: 400, color: "var(--text)", fontFamily: "'DM Serif Display', serif", marginBottom: 4 }}>
            Matter of {data.party_name}
          </div>
          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: accentColor }}>{data.citation}</div>
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0, alignItems: "center" }}>
          {showGraphButton && onViewGraph && (
            <button onClick={() => onViewGraph(data.party_name || data.citation)}
              title="Citation graph"
              style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "#34d399", background: "none", padding: "5px 10px", border: "1px solid #34d39944", borderRadius: "var(--radius)", cursor: "pointer", whiteSpace: "nowrap" }}
              onMouseEnter={e => e.currentTarget.style.background = "#34d39911"}
              onMouseLeave={e => e.currentTarget.style.background = ""}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>
              Graph
            </button>
          )}
          {data.pdf_path && (
            <a href={`${API}/precedents/${id}/pdf`} target="_blank" rel="noreferrer"
              style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: accentColor, textDecoration: "none", padding: "5px 10px", border: `1px solid ${accentColor}`, borderRadius: "var(--radius)", whiteSpace: "nowrap" }}
              onMouseEnter={e => e.currentTarget.style.background = isAdopted ? "var(--amber-dim)" : "var(--blue-dim)"}
              onMouseLeave={e => e.currentTarget.style.background = ""}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              PDF
            </a>
          )}
          <button onClick={onClose}
            style={{ fontSize: 18, lineHeight: 1, color: "var(--text3)", background: "none", border: "none", cursor: "pointer", padding: "2px 6px" }}>×</button>
        </div>
      </div>
      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {data.full_text ? (
          <pre style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, lineHeight: 1.8, whiteSpace: "pre-wrap", wordBreak: "break-word", padding: "20px 24px", color: "var(--text2)", margin: 0 }}>
            {data.full_text}
          </pre>
        ) : (
          <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text3)", fontSize: 13 }}>
            Full text not available for this decision.<br />
            {data.pdf_url && <a href={data.pdf_url} target="_blank" rel="noreferrer" style={{ color: accentColor, fontSize: 12, marginTop: 8, display: "inline-block" }}>View on DOJ website →</a>}
          </div>
        )}
      </div>
    </div>
  );
}

function AAODecisionDetail({ decisionId, query, onNavigate, precedentMap, onViewGraph }) {
  const { data, loading } = useFetch(decisionId ? `${API}/aao/decisions/${decisionId}` : null);
  const firstMatchRef = useRef(null);

  useEffect(() => {
    if (data && firstMatchRef.current) setTimeout(() => firstMatchRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 120);
  }, [data]);

  if (loading) return <Spinner />;
  if (!data) return null;

  const renderOpinion = () => {
    const text = data.full_text || "No text extracted.";
    const ps = { fontFamily: "'DM Mono', monospace", fontSize: 12, lineHeight: 1.8, whiteSpace: "pre-wrap", wordBreak: "break-word", padding: "20px 28px", color: "var(--text2)" };
    const terms = query?.trim() ? query.trim().split(/\s+/).filter(t => t.length > 2) : [];
    const map = precedentMap || {};

    // Pattern: "Matter of X, 25 I&N Dec. 369" or "Matter of X, Adopted Decision YYYY-NN"
    // We split on the I&N Dec. citation or Adopted Decision reference that follows a "Matter of"
    const precedentPat = String.raw`\d+ [Il]&N Dec\. \d+|Adopted Decision \d{4}-\d+`;
    const termPats = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const allPats = termPats.length ? [precedentPat, ...termPats] : [precedentPat];
    const splitPat = new RegExp(`(${allPats.join("|")})`, "gi");
    const precOnlyPat = new RegExp(`^(${precedentPat})$`, "i");
    const termPat = terms.length ? new RegExp(`^(${termPats.join("|")})$`, "gi") : null;

    const parts = text.split(splitPat);
    let firstMark = false;

    return (
      <pre style={ps}>
        {parts.map((part, i) => {
          // Precedent citation — check map
          if (precOnlyPat.test(part)) {
            // Normalise l&N → I&N for lookup
            const key = part.replace(/l&N/g, "I&N");
            const entry = map[key] || map[part];
            if (entry) {
              return (
                <ReadLaterPopup key={i}
                  caseNumber={part} caseId={entry.id} caseSource="aao"
                  fromCaseNumber={data.title || data.form_type || String(decisionId)} fromSource="aao"
                  onNavigate={(id) => onNavigate && onNavigate(id, entry.type)}>
                  <span
                    onClick={() => onNavigate && onNavigate(entry.id, entry.type)}
                    title={`${entry.party_name} — ${entry.citation}`}
                    style={{ color: "var(--blue)", textDecoration: "underline", textDecorationColor: "color-mix(in srgb, var(--blue) 40%, transparent)", cursor: "pointer", fontWeight: 500 }}
                  >{part}</span>
                </ReadLaterPopup>
              );
            }
            // Citation not in our DB — subtle blue, not clickable
            return <span key={i} style={{ color: "var(--blue)", opacity: 0.45 }}>{part}</span>;
          }
          // Search term highlight
          if (termPat) {
            termPat.lastIndex = 0;
            if (termPat.test(part)) {
              const isFirst = !firstMark;
              if (isFirst) firstMark = true;
              return <mark key={i} ref={isFirst ? firstMatchRef : null}>{part}</mark>;
            }
          }
          return part;
        })}
      </pre>
    );
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5, flexWrap: "wrap" }}>
              {data.form_type && <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: "var(--blue)", letterSpacing: "0.04em" }}>{data.form_type}</span>}
              {data.outcome && <AaoBadge label={data.outcome} />}
              {query && <span style={{ fontSize: 11, color: "var(--text3)" }}>— <span style={{ color: "var(--amber)", fontFamily: "'DM Mono', monospace" }}>"{query}"</span></span>}
            </div>
            {data.title && <div style={{ fontSize: 15, fontWeight: 400, color: "var(--text)", marginBottom: 3, fontFamily: "'DM Serif Display', serif" }}>{data.title}</div>}
            {data.regulation && <div style={{ fontSize: 12, color: "var(--text2)", marginBottom: 3 }}>{data.regulation}</div>}
            {data.decision_date && <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{data.decision_date}</span>}
          </div>
          {onViewGraph && (
            <button onClick={() => onViewGraph(data.is_precedent && data.party_name ? data.party_name : (data.title || data.form_type || String(decisionId)))}
              style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--green)", padding: "5px 10px", border: "1px solid var(--green)", borderRadius: "var(--radius)", whiteSpace: "nowrap", flexShrink: 0, background: "none" }}
              onMouseEnter={e => e.currentTarget.style.background = "var(--green-dim)"}
              onMouseLeave={e => e.currentTarget.style.background = ""}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>
              Graph
            </button>
          )}
          <a href={`${API}/aao/decisions/${decisionId}/pdf`} target="_blank" rel="noreferrer"
            style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--blue)", textDecoration: "none", padding: "5px 10px", border: "1px solid var(--blue)", borderRadius: "var(--radius)", whiteSpace: "nowrap", flexShrink: 0 }}
            onMouseEnter={e => e.currentTarget.style.background = "var(--blue-dim)"}
            onMouseLeave={e => e.currentTarget.style.background = ""}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            PDF
          </a>
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto" }}>{renderOpinion()}</div>
    </div>
  );
}

// ── Cross-corpus Search All ───────────────────────────────────────────────────
const CORPUS_META = {
  balca:      { label: "BALCA",       accent: "var(--amber)",  dim: "var(--amber-dim)",  dot: "#f59e0b" },
  aao:        { label: "AAO",         accent: "var(--blue)",   dim: "var(--blue-dim)",   dot: "#60a5fa" },
  regulation: { label: "Regulations", accent: "var(--green)",  dim: "var(--green-dim)",  dot: "#34d399" },
  policy:     { label: "Policy",      accent: "#a78bfa",       dim: "#a78bfa22",         dot: "#a78bfa" },
};

function SearchAllView({ onNavigate, initialQuery }) {
  const [q, setQ] = useState(initialQuery || "");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [page, setPage] = useState(1);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const search = useCallback(async (pg = 1) => {
    if (!q.trim()) return;
    setLoading(true); setSearched(true);
    const p = new URLSearchParams({ q: q.trim(), page: pg, page_size: 30 });
    const res = await fetch(`${API}/search-all?${p}`);
    const data = await res.json();
    setResults(data); setPage(pg); setLoading(false);
  }, [q]);

  useEffect(() => { if (initialQuery?.trim()) search(1); }, []);

  // Group by corpus while preserving rank order
  const grouped = {};
  (results?.results || []).forEach(r => {
    if (!grouped[r.corpus]) grouped[r.corpus] = [];
    grouped[r.corpus].push(r);
  });

  const handleOpen = (item) => {
    if (item.corpus === "balca") onNavigate("balca", item.id, q);
    else if (item.corpus === "aao") onNavigate("aao", item.id, q);
    else if (item.corpus === "regulation") onNavigate("regulations", item.id, null);
    else if (item.corpus === "policy") onNavigate("policy", item.id, null);
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Search bar */}
      <div style={{
        padding: searched ? "12px 20px" : "0",
        flex: searched ? "0 0 auto" : "1",
        display: "flex", flexDirection: "column",
        justifyContent: searched ? "flex-start" : "center",
        alignItems: "center",
        borderBottom: searched ? "1px solid var(--border)" : "none",
        background: searched ? "var(--bg2)" : "var(--bg)",
      }}>
        {!searched && (
          <div style={{ marginBottom: 28, textAlign: "center" }}>
            <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 28, color: "var(--text)", marginBottom: 6 }}>Search All</div>
            <div style={{ fontSize: 13, color: "var(--text3)" }}>
              Search across BALCA decisions, AAO decisions, regulations, and policy manuals simultaneously
            </div>
            <div style={{ marginTop: 14, display: "flex", justifyContent: "center", gap: 8, flexWrap: "wrap" }}>
              {Object.values(CORPUS_META).map(m => (
                <span key={m.label} style={{ fontSize: 11, padding: "3px 10px", background: m.dim, color: m.accent, borderRadius: 20, border: `1px solid ${m.dot}44` }}>{m.label}</span>
              ))}
            </div>
          </div>
        )}
        <div style={{ width: "100%", maxWidth: searched ? "100%" : 680, padding: searched ? 0 : "0 24px" }}>
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ position: "relative", flex: 1 }}>
              <svg style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text3)", pointerEvents: "none" }} width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
              <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)}
                onKeyDown={e => e.key === "Enter" && search(1)}
                placeholder={searched ? "New search…" : "Search everything — e.g. \"business necessity\" or \"extraordinary ability\""}
                style={{ paddingLeft: 30, fontSize: searched ? 13 : 14, height: searched ? 36 : 42 }} />
            </div>
            <button onClick={() => search(1)} className="primary" style={{ height: searched ? 36 : 42, padding: "0 14px", fontSize: searched ? 13 : 14 }}>Search</button>
          </div>
        </div>
      </div>

      {/* Results */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {loading && <Spinner />}
        {!loading && searched && results && (
          <>
            <div style={{ padding: "8px 24px", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace", letterSpacing: "0.05em", background: "var(--bg2)", borderBottom: "1px solid var(--border)" }}>
              {results.total?.toLocaleString()} RESULTS ACROSS ALL CORPORA
            </div>

            {/* Render grouped by corpus with corpus headers */}
            {Object.entries(CORPUS_META).map(([corpus, meta]) => {
              const items = grouped[corpus];
              if (!items || !items.length) return null;
              return (
                <div key={corpus}>
                  <div style={{ padding: "5px 24px", fontSize: 10, fontWeight: 600, color: meta.accent, letterSpacing: "0.08em", textTransform: "uppercase", background: meta.dim, borderBottom: "1px solid var(--border)", borderTop: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
                    {meta.label} — {items.length} result{items.length !== 1 ? "s" : ""}
                  </div>
                  {items.map((item, i) => (
                    <div key={`${corpus}-${item.id}`} className="fade-up"
                      onClick={() => handleOpen(item)}
                      style={{ padding: "13px 24px", borderBottom: "1px solid var(--border)", cursor: "pointer", animationDelay: `${i * 15}ms` }}
                      onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                      onMouseLeave={e => e.currentTarget.style.background = ""}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: meta.accent, fontWeight: 500 }}>{item.title}</span>
                        {item.outcome && (
                          <span style={{ fontSize: 10, fontWeight: 500, padding: "2px 6px", borderRadius: 4, background: "var(--bg4)", color: "var(--text3)" }}>{item.outcome}</span>
                        )}
                        {item.date && <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{item.date}</span>}
                      </div>
                      {item.subtitle && <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)", marginBottom: 4 }}>{item.subtitle}</div>}
                      {item.headline && <div style={{ fontSize: 11, color: "var(--text3)", lineHeight: 1.6, marginTop: 2 }} dangerouslySetInnerHTML={{ __html: item.headline }} />}
                    </div>
                  ))}
                </div>
              );
            })}

            {/* Pagination */}
            {results.total > 30 && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "14px 24px", borderTop: "1px solid var(--border)" }}>
                <button onClick={() => search(page - 1)} disabled={page <= 1} style={{ opacity: page <= 1 ? 0.3 : 1, fontSize: 12 }}>←</button>
                <span style={{ flex: 1, textAlign: "center", fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
                  {page} / {Math.ceil(results.total / 30)}
                </span>
                <button onClick={() => search(page + 1)} disabled={page * 30 >= results.total} style={{ opacity: page * 30 >= results.total ? 0.3 : 1, fontSize: 12 }}>→</button>
              </div>
            )}
            {results.results?.length === 0 && (
              <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text3)", fontSize: 13 }}>No results found.</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Citation Graph View ───────────────────────────────────────────────────────
const GRAPH_OUTCOME_COLOR = {
  Affirmed:  "#34d399",
  Reversed:  "#f87171",
  Remanded:  "#fbbf24",
  Dismissed: "#5a5a68",
};

function CitationGraphView({ onNavigate, initialQuery }) {
  const [q, setQ] = useState(initialQuery || "");
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);
  const [hovered, setHovered] = useState(null);
  const svgRef = useRef(null);
  const simRef = useRef(null);
  const containerRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const search = async () => {
    if (!q.trim()) return;
    setLoading(true); setSelectedNode(null); setHovered(null); setGraphData(null);
    const res = await fetch(`${API}/search/citation-graph?q=${encodeURIComponent(q.trim())}&limit=40`);
    const data = await res.json();
    setGraphData(data);
    setLoading(false);
  };

  useEffect(() => { if (initialQuery?.trim()) search(); }, []);

  useEffect(() => {
    if (!graphData || !svgRef.current || !graphData.nodes.length) return;
    const d3 = window.d3;
    if (!d3) return;

    const container = svgRef.current.parentElement;
    const width = container.clientWidth || 900;
    const height = container.clientHeight || 600;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    svg.attr("width", width).attr("height", height);

    // ── Compute citation counts ──────────────────────────────────────────
    // Count how many edges point INTO each node (in-degree across all nodes)
    const inDegree = {};
    graphData.nodes.forEach(n => { inDegree[n.id] = 0; });
    graphData.edges.forEach(e => {
      if (inDegree[e.target] !== undefined) inDegree[e.target]++;
    });

    // Node radius: size purely by in-degree (citations received), min 10
    const maxDegree = Math.max(...Object.values(inDegree), 1);
    const nodeRadius = (n) => {
      const deg = inDegree[n.id] || 0;
      // secondary nodes get bonus from their cited_by_count too
      const effectiveDeg = n.tier === "secondary"
        ? Math.max(deg, n.cited_by_count || 0)
        : deg;
      return 10 + (effectiveDeg / maxDegree) * 28;
    };

    // ── Zoom & pan ───────────────────────────────────────────────────────
    const zoom = d3.zoom().scaleExtent([0.25, 4]).on("zoom", e => {
      g.attr("transform", e.transform);
    });
    svg.call(zoom);

    const g = svg.append("g");

    // ── Arrow markers ─────────────────────────────────────────────────────
    const defs = svg.append("defs");
    // One marker per outcome color
    const markerColors = { default: "#4a4a6a", Affirmed: "#34d399", Reversed: "#f87171", Remanded: "#fbbf24", Dismissed: "#5a5a68" };
    Object.entries(markerColors).forEach(([key, color]) => {
      defs.append("marker")
        .attr("id", `arrow-${key}`)
        .attr("viewBox", "0 -4 8 8")
        .attr("refX", 10).attr("refY", 0)
        .attr("markerWidth", 7).attr("markerHeight", 7)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-4L8,0L0,4")
        .attr("fill", color)
        .attr("opacity", 0.7);
    });

    // ── Simulation ────────────────────────────────────────────────────────
    const nodes = graphData.nodes.map(n => ({ ...n }));
    const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
    const edges = graphData.edges
      .filter(e => nodeById[e.source] && nodeById[e.target])
      .map(e => ({ ...e }));

    const sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(edges)
        .id(n => n.id)
        .distance(d => {
          const sr = nodeRadius(nodeById[d.source.id ?? d.source]);
          const tr = nodeRadius(nodeById[d.target.id ?? d.target]);
          return sr + tr + 60; // edges scale with node size so big nodes don't overlap
        })
        .strength(0.5))
      .force("charge", d3.forceManyBody().strength(n => -(nodeRadius(n) * 18)))
      .force("center", d3.forceCenter(width / 2, height / 2).strength(0.08))
      .force("collision", d3.forceCollide().radius(n => nodeRadius(n) + 20).strength(0.9))
      .alphaDecay(0.02);

    simRef.current = sim;

    // ── Edges ─────────────────────────────────────────────────────────────
    const link = g.append("g").attr("class", "links")
      .selectAll("line")
      .data(edges).join("line")
      .attr("stroke", d => {
        const src = nodeById[d.source.id ?? d.source];
        return GRAPH_OUTCOME_COLOR[src?.outcome] ?? "#4a4a6a";
      })
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", 0.45)
      .attr("marker-end", d => {
        const src = nodeById[d.source.id ?? d.source];
        const key = GRAPH_OUTCOME_COLOR[src?.outcome] ? src.outcome : "default";
        return `url(#arrow-${key})`;
      });

    // ── Node groups ───────────────────────────────────────────────────────
    const node = g.append("g").attr("class", "nodes")
      .selectAll("g")
      .data(nodes).join("g")
      .style("cursor", "pointer")
      .call(d3.drag()
        .on("start", (event, d) => {
          if (!event.active) sim.alphaTarget(0.15).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end", (event, d) => {
          if (!event.active) sim.alphaTarget(0);
          d.fx = null; d.fy = null;
        })
      );

    // Circle
    node.append("circle")
      .attr("r", nodeRadius)
      .attr("fill", n => {
        const base = GRAPH_OUTCOME_COLOR[n.outcome] ?? "#5a5a68";
        return n.tier === "secondary" ? base + "55" : base + "cc";
      })
      .attr("stroke", n => GRAPH_OUTCOME_COLOR[n.outcome] ?? "#5a5a68")
      .attr("stroke-width", n => n.tier === "primary" ? 2 : 1)
      .attr("stroke-opacity", 0.9);

    // Citation count badge (centre of circle)
    node.append("text")
      .text(n => inDegree[n.id] || "")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "central")
      .attr("font-size", n => Math.max(8, nodeRadius(n) * 0.55))
      .attr("font-family", "'DM Mono', monospace")
      .attr("font-weight", "600")
      .attr("fill", "#fff")
      .attr("fill-opacity", 0.9)
      .style("pointer-events", "none");

    // Case number label below circle
    node.append("text")
      .text(n => {
        // Strip leading year+PER+zeros: "2019-PER-00042" → "2019-42"
        const m = n.case_number?.match(/^(\d{4})-PER-0*(\d+)$/);
        return m ? `${m[1]}-${m[2]}` : (n.case_number ?? "");
      })
      .attr("text-anchor", "middle")
      .attr("dy", n => nodeRadius(n) + 13)
      .attr("font-size", 9)
      .attr("font-family", "'DM Mono', monospace")
      .attr("fill", n => GRAPH_OUTCOME_COLOR[n.outcome] ?? "#8888aa")
      .attr("fill-opacity", n => n.tier === "primary" ? 0.85 : 0.55)
      .style("pointer-events", "none");

    // Employer name label (two lines max, only if node is big enough)
    node.each(function(n) {
      if (!n.employer_name) return;
      const r = nodeRadius(n);
      if (r < 18) return; // skip tiny nodes
      const label = n.employer_name.length > 22
        ? n.employer_name.slice(0, 20) + "…"
        : n.employer_name;
      d3.select(this).append("text")
        .text(label)
        .attr("text-anchor", "middle")
        .attr("dy", r + 24)
        .attr("font-size", 8.5)
        .attr("font-family", "sans-serif")
        .attr("fill", "var(--text3, #888)")
        .attr("fill-opacity", 0.7)
        .style("pointer-events", "none");
    });

    // ── Interactions ──────────────────────────────────────────────────────
    node.on("mouseenter", (event, d) => {
      setHovered(d);
      // Highlight connected edges
      link.attr("stroke-opacity", e => {
        const sid = e.source.id ?? e.source;
        const tid = e.target.id ?? e.target;
        return (sid === d.id || tid === d.id) ? 0.9 : 0.1;
      }).attr("stroke-width", e => {
        const sid = e.source.id ?? e.source;
        const tid = e.target.id ?? e.target;
        return (sid === d.id || tid === d.id) ? 2.5 : 1.5;
      });
      // Dim unconnected nodes
      const connected = new Set([d.id]);
      edges.forEach(e => {
        const sid = e.source.id ?? e.source;
        const tid = e.target.id ?? e.target;
        if (sid === d.id) connected.add(tid);
        if (tid === d.id) connected.add(sid);
      });
      node.attr("opacity", n => connected.has(n.id) ? 1 : 0.2);
    })
    .on("mouseleave", () => {
      setHovered(null);
      link.attr("stroke-opacity", 0.45).attr("stroke-width", 1.5);
      node.attr("opacity", 1);
    })
    .on("click", (event, d) => {
      event.stopPropagation();
      setSelectedNode(d);
    });

    svg.on("click", () => setSelectedNode(null));

    // ── Tick ─────────────────────────────────────────────────────────────
    sim.on("tick", () => {
      link
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => {
          const tr = nodeRadius(nodeById[d.target.id ?? d.target] ?? d.target);
          const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          return d.target.x - (dx / dist) * (tr + 10);
        })
        .attr("y2", d => {
          const tr = nodeRadius(nodeById[d.target.id ?? d.target] ?? d.target);
          const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          return d.target.y - (dy / dist) * (tr + 10);
        });
      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

    return () => { sim.stop(); };
  }, [graphData]);

  // Load D3 from CDN once
  useEffect(() => {
    if (window.d3) return;
    const script = document.createElement("script");
    script.src = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js";
    document.head.appendChild(script);
  }, []);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>

      {/* ── Search bar ── */}
      <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: graphData ? 8 : 0 }}>
          <div style={{ position: "relative", flex: 1, maxWidth: 600 }}>
            <svg style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text3)", pointerEvents: "none" }}
              width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
            </svg>
            <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)}
              onKeyDown={e => e.key === "Enter" && search()}
              placeholder="Search and map citations — e.g. 'business necessity' or 'Notice of Filing'"
              style={{ paddingLeft: 30, fontSize: 13, height: 36 }} />
          </div>
          <button onClick={search} className="primary" style={{ height: 36, padding: "0 18px", fontSize: 13 }}>Map</button>
          {graphData && (
            <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
              {graphData.primary_count} matched · {graphData.secondary_count} hub · {graphData.edges.length} links
            </span>
          )}
        </div>

        {/* Legend */}
        {graphData && (
          <div style={{ display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: 10 }}>
              {Object.entries(GRAPH_OUTCOME_COLOR).map(([outcome, color]) => (
                <span key={outcome} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
                  {outcome}
                </span>
              ))}
            </div>
            <span style={{ fontSize: 10, color: "var(--text3)" }}>circle size = citations received · number inside = citation count</span>
            <span style={{ fontSize: 10, color: "var(--text3)" }}>solid = matched search · faded = cited hub · hover or tap to highlight connections</span>
          </div>
        )}
      </div>

      {/* ── Graph canvas ── */}
      <div ref={containerRef} style={{ flex: 1, position: "relative", overflow: "hidden", background: "var(--bg)" }}>

        {/* Empty state */}
        {!graphData && !loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14 }}>
            <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="var(--border2)" strokeWidth="0.8">
              <circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="19" cy="19" r="2.5"/>
              <circle cx="12" cy="8" r="2"/><circle cx="12" cy="17" r="2"/>
              <line x1="7" y1="11.5" x2="10.2" y2="8.8"/><line x1="7" y1="12.5" x2="10.2" y2="16"/>
              <line x1="14" y1="8" x2="17" y2="6.2"/><line x1="14" y1="17" x2="17" y2="18.2"/>
            </svg>
            <div style={{ fontSize: 13, color: "var(--text3)", textAlign: "center" }}>
              Enter a search term to see how results cite each other
              <div style={{ fontSize: 11, marginTop: 4, color: "var(--border2)" }}>Try: "business necessity" · "alien labor certification" · "Notice of Filing"</div>
            </div>
          </div>
        )}

        {loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Spinner />
          </div>
        )}

        {graphData && !loading && graphData.nodes.length === 0 && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ fontSize: 13, color: "var(--text3)" }}>No results found.</div>
          </div>
        )}

        <svg ref={svgRef} className="citation-graph-svg" style={{ width: "100%", height: "100%", display: "block" }} />

        {/* Hover tooltip */}
        {hovered && !selectedNode && (
          <div style={{
            position: "absolute", bottom: 20, left: 20, zIndex: 10,
            background: "var(--bg2)", border: "1px solid var(--border2)",
            borderRadius: "var(--radius-lg)", padding: "10px 14px",
            maxWidth: 300, pointerEvents: "none",
            boxShadow: "0 4px 20px #00000055",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: GRAPH_OUTCOME_COLOR[hovered.outcome] ?? "var(--text3)", fontWeight: 600 }}>
                {hovered.case_number}
              </span>
              <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3,
                background: hovered.tier === "primary" ? "var(--amber-dim)" : "var(--bg4)",
                color: hovered.tier === "primary" ? "var(--amber)" : "var(--text3)" }}>
                {hovered.tier === "primary" ? "matched" : `hub · cited ${hovered.cited_by_count}×`}
              </span>
            </div>
            {hovered.employer_name && (
              <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", marginBottom: 4, fontFamily: "'DM Serif Display', serif" }}>
                {hovered.employer_name}
              </div>
            )}
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              {hovered.date && <span style={{ fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{hovered.date}</span>}
              {hovered.outcome && (
                <span style={{ fontSize: 10, color: GRAPH_OUTCOME_COLOR[hovered.outcome], fontWeight: 500 }}>● {hovered.outcome}</span>
              )}
            </div>
            <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 6, borderTop: "1px solid var(--border)", paddingTop: 6 }}>
              Tap to open details · drag to reposition
            </div>
          </div>
        )}

        {/* Selected node panel */}
        {selectedNode && (
          <div style={{
            position: "absolute", top: 16, right: 16, zIndex: 10,
            background: "var(--bg2)", border: `1px solid ${GRAPH_OUTCOME_COLOR[selectedNode.outcome] ?? "var(--border2)"}44`,
            borderRadius: "var(--radius-lg)", padding: "16px 18px", width: 270,
            boxShadow: "0 8px 28px #00000066", animation: "fadeUp 0.15s ease",
          }}>
            <div style={{ display: "flex", alignItems: "flex-start", marginBottom: 12 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: GRAPH_OUTCOME_COLOR[selectedNode.outcome] ?? "var(--text3)", fontWeight: 600 }}>
                    {selectedNode.case_number}
                  </span>
                  <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3,
                    background: selectedNode.tier === "primary" ? "var(--amber-dim)" : "var(--bg4)",
                    color: selectedNode.tier === "primary" ? "var(--amber)" : "var(--text3)" }}>
                    {selectedNode.tier === "primary" ? "matched" : `hub · cited ${selectedNode.cited_by_count}×`}
                  </span>
                </div>
                {selectedNode.employer_name && (
                  <div style={{ fontSize: 14, fontWeight: 400, color: "var(--text)", marginBottom: 4, fontFamily: "'DM Serif Display', serif", lineHeight: 1.3 }}>
                    {selectedNode.employer_name}
                  </div>
                )}
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                  {selectedNode.date && <span style={{ fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{selectedNode.date}</span>}
                  {selectedNode.outcome && (
                    <span style={{ fontSize: 10, color: GRAPH_OUTCOME_COLOR[selectedNode.outcome], fontWeight: 500 }}>● {selectedNode.outcome}</span>
                  )}
                </div>
              </div>
              <button onClick={() => setSelectedNode(null)}
                style={{ fontSize: 16, lineHeight: 1, color: "var(--text3)", background: "none", border: "none", cursor: "pointer", padding: "0 2px", marginLeft: 8, flexShrink: 0 }}>×</button>
            </div>
            <button
              onClick={() => { onNavigate(selectedNode.id); setSelectedNode(null); }}
              className="primary"
              style={{ width: "100%", fontSize: 12, padding: "8px 0" }}>
              Open decision →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}


// ── AAO Citation Graph View ───────────────────────────────────────────────────
function AAOCitationGraphView({ onNavigate, onOpenPrecedent, initialQuery }) {
  const [q, setQ] = useState(initialQuery || "");
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);
  const [hovered, setHovered] = useState(null);
  const svgRef = useRef(null);
  const simRef = useRef(null);
  const containerRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const search = async () => {
    if (!q.trim()) return;
    setLoading(true); setSelectedNode(null); setHovered(null); setGraphData(null);
    const res = await fetch(`${API}/aao/search/citation-graph?q=${encodeURIComponent(q.trim())}&limit=40`);
    const data = await res.json();
    setGraphData(data);
    setLoading(false);
  };

  useEffect(() => { if (initialQuery?.trim()) search(); }, []);

  useEffect(() => {
    if (!graphData || !svgRef.current || !graphData.nodes.length) return;
    const d3 = window.d3;
    if (!d3) return;

    const container = svgRef.current.parentElement;
    const width = container.clientWidth || 900;
    const height = container.clientHeight || 600;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    svg.attr("width", width).attr("height", height);

    const inDegree = {};
    graphData.nodes.forEach(n => { inDegree[n.id] = 0; });
    graphData.edges.forEach(e => { if (inDegree[e.target] !== undefined) inDegree[e.target]++; });

    const maxDegree = Math.max(...Object.values(inDegree), 1);
    const nodeRadius = (n) => {
      const deg = inDegree[n.id] || 0;
      const effectiveDeg = n.tier === "secondary" ? Math.max(deg, n.cited_by_count || 0) : deg;
      return 10 + (effectiveDeg / maxDegree) * 28;
    };

    const zoom = d3.zoom().scaleExtent([0.25, 4]).on("zoom", e => { g.attr("transform", e.transform); });
    svg.call(zoom);
    const g = svg.append("g");

    const defs = svg.append("defs");
    const markerColors = { default: "#4a4a6a", Dismissed: "#5a5a68", Sustained: "#34d399", Remanded: "#fbbf24", Withdrawn: "#a78bfa" };
    Object.entries(markerColors).forEach(([key, color]) => {
      defs.append("marker")
        .attr("id", `aao-arrow-${key}`)
        .attr("viewBox", "0 -4 8 8").attr("refX", 10).attr("refY", 0)
        .attr("markerWidth", 7).attr("markerHeight", 7).attr("orient", "auto")
        .append("path").attr("d", "M0,-4L8,0L0,4").attr("fill", color).attr("opacity", 0.7);
    });

    const nodes = graphData.nodes.map(n => ({ ...n }));
    const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
    const edges = graphData.edges.filter(e => nodeById[e.source] && nodeById[e.target]).map(e => ({ ...e }));

    const sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(edges).id(n => n.id)
        .distance(d => {
          const sr = nodeRadius(nodeById[d.source.id ?? d.source]);
          const tr = nodeRadius(nodeById[d.target.id ?? d.target]);
          return sr + tr + 60;
        }).strength(0.5))
      .force("charge", d3.forceManyBody().strength(n => -(nodeRadius(n) * 18)))
      .force("center", d3.forceCenter(width / 2, height / 2).strength(0.08))
      .force("collision", d3.forceCollide().radius(n => nodeRadius(n) + 20).strength(0.9))
      .alphaDecay(0.02);
    simRef.current = sim;

    const outcomeColor = (o) => ({ Dismissed: "#5a5a68", Sustained: "#34d399", Remanded: "#fbbf24", Withdrawn: "#a78bfa" }[o] || "#60a5fa");
    const nodeColor = (n) => n.node_type === "precedent" ? "#f59e0b" : outcomeColor(n.outcome);
    const nodeFill  = (n) => n.node_type === "precedent"
      ? (n.tier === "primary" ? "#f59e0b" : "#f59e0b88")
      : (n.tier === "primary" ? outcomeColor(n.outcome) : outcomeColor(n.outcome) + "66");

    const link = g.append("g").selectAll("line").data(edges).join("line")
      .attr("stroke", d => {
        const tgt = nodeById[d.target?.id ?? d.target];
        return tgt?.node_type === "precedent" ? "#f59e0b" : outcomeColor(tgt?.outcome);
      })
      .attr("stroke-opacity", 0.35).attr("stroke-width", 1.5)
      .attr("marker-end", d => {
        const tgt = nodeById[d.target?.id ?? d.target];
        if (tgt?.node_type === "precedent") return "url(#aao-arrow-default)";
        const key = markerColors[tgt?.outcome] ? tgt?.outcome : "default";
        return `url(#aao-arrow-${key})`;
      });

    const node = g.append("g").selectAll("g").data(nodes).join("g")
      .style("cursor", "pointer")
      .call(d3.drag()
        .on("start", (event, d) => { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag",  (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end",   (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }))
      .on("click", (event, d) => {
        event.stopPropagation();
        if (d.node_type === "precedent" && onOpenPrecedent) {
          onOpenPrecedent(d.prec_id);
        } else {
          setSelectedNode(d);
        }
      })
      .on("mouseover", (event, d) => setHovered(d))
      .on("mouseout",  () => setHovered(null));

    node.append("circle")
      .attr("r", nodeRadius)
      .attr("fill", nodeFill)
      .attr("stroke", d => d.tier === "primary" ? (d.node_type === "precedent" ? "#fde68a" : "#fff") : "none")
      .attr("stroke-width", d => d.tier === "primary" ? 2 : 0)
      .attr("opacity", d => d.tier === "primary" ? 1 : 0.65);

    node.append("text")
      .attr("dy", "0.35em").attr("text-anchor", "middle")
      .attr("font-size", d => Math.max(9, Math.min(13, nodeRadius(d) * 0.55)))
      .attr("fill", "#fff").attr("pointer-events", "none")
      .text(d => {
        const label = d.node_type === "precedent"
          ? (d.party_name || d.citation || "")
          : (d.form_type || d.label || d.filename || "");
        return label.length > 14 ? label.slice(0, 13) + "…" : label;
      });

    sim.on("tick", () => {
      link
        .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

    svg.on("click", () => setSelectedNode(null));
    return () => sim.stop();
  }, [graphData]);

  const accent = "#60a5fa";

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--bg)" }} ref={containerRef}>
      {/* Header */}
      <div style={{ padding: "20px 24px 16px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={accent} strokeWidth="1.8">
            <circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/>
            <line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/>
          </svg>
          <span style={{ fontFamily: "'DM Serif Display', serif", fontSize: 18, color: "var(--text)" }}>AAO Citation Graph</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <div style={{ flex: 1, position: "relative" }}>
            <svg style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", opacity: 0.4 }} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
            <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && search()}
              placeholder="Search AAO decisions or enter form type (I-140, I-485…)"
              style={{ width: "100%", paddingLeft: 30, fontSize: 13, height: 36, boxSizing: "border-box" }} />
          </div>
          <button onClick={search} disabled={loading} style={{ background: accent, color: "#fff", border: "none", borderRadius: 6, padding: "0 16px", fontSize: 13, cursor: "pointer", opacity: loading ? 0.6 : 1 }}>
            {loading ? "…" : "Graph"}
          </button>
        </div>
        {graphData && (
          <div style={{ marginTop: 10, fontSize: 11, color: "var(--text3)" }}>
            {graphData.primary_count} primary · {graphData.secondary_count} secondary · {graphData.edges.length} edges
          </div>
        )}
      </div>

      {/* Graph canvas */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
        {!graphData && !loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12, opacity: 0.5 }}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke={accent} strokeWidth="1"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>
            <span style={{ fontSize: 13, color: "var(--text3)" }}>Search to generate citation graph</span>
          </div>
        )}
        {loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <span style={{ fontSize: 13, color: "var(--text3)" }}>Building graph…</span>
          </div>
        )}
        <svg ref={svgRef} style={{ width: "100%", height: "100%", display: "block" }} />

        {/* Hover tooltip */}
        {hovered && (
          <div style={{ position: "absolute", bottom: 16, left: 16, background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 14px", maxWidth: 300, pointerEvents: "none" }}>
            {hovered.node_type === "precedent" ? (
              <>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#f59e0b", marginBottom: 3 }}>{hovered.party_name}</div>
                <div style={{ fontSize: 11, color: "var(--text2)", marginBottom: 3 }}>{hovered.citation} · {hovered.year}</div>
                <div style={{ fontSize: 11, color: "var(--text3)" }}>Cited by {hovered.cited_by_count} decisions in graph · I&N Dec. precedent</div>
              </>
            ) : (
              <>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", marginBottom: 3 }}>{hovered.form_type || hovered.label || hovered.filename}</div>
                {hovered.label && hovered.label !== hovered.form_type && <div style={{ fontSize: 11, color: "var(--text2)", marginBottom: 3 }}>{hovered.label.slice(0, 80)}</div>}
                <div style={{ fontSize: 11, color: "var(--text3)" }}>{hovered.date} · {hovered.outcome || "—"} · <span style={{ color: accent }}>{hovered.tier}</span></div>
              </>
            )}
          </div>
        )}

        {/* Selected node panel */}
        {selectedNode && (
          <div style={{ position: "absolute", top: 16, right: 16, width: 280, background: "var(--bg2)", border: `1px solid ${accent}44`, borderRadius: 10, padding: "14px 16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: selectedNode.node_type === "precedent" ? "#f59e0b" : "var(--text)", flex: 1, paddingRight: 8 }}>
                {selectedNode.node_type === "precedent" ? selectedNode.party_name : (selectedNode.form_type || selectedNode.filename)}
              </div>
              <button onClick={() => setSelectedNode(null)} style={{ background: "none", border: "none", color: "var(--text3)", cursor: "pointer", fontSize: 16, padding: 0, lineHeight: 1 }}>×</button>
            </div>
            {selectedNode.node_type === "precedent" ? (
              <>
                <div style={{ fontSize: 11, color: "var(--text2)", marginBottom: 4 }}>{selectedNode.citation} · {selectedNode.year}</div>
                <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 12 }}>Cited by {selectedNode.cited_by_count} decisions in this graph</div>
                {onOpenPrecedent && <button onClick={() => onOpenPrecedent(selectedNode.prec_id)}
                  style={{ width: "100%", padding: "7px 0", background: "#f59e0b22", color: "#f59e0b", border: "1px solid #f59e0b44", borderRadius: 6, fontSize: 12, cursor: "pointer", fontWeight: 500 }}>
                  Open precedent →
                </button>}
              </>
            ) : (
              <>
                {selectedNode.label && selectedNode.label !== selectedNode.form_type && (
                  <div style={{ fontSize: 11, color: "var(--text2)", marginBottom: 8 }}>{selectedNode.label.slice(0, 120)}</div>
                )}
                <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 12 }}>{selectedNode.date} · {selectedNode.outcome || "—"} · {selectedNode.tier}</div>
                <button onClick={() => onNavigate(selectedNode.id)}
                  style={{ width: "100%", padding: "7px 0", background: accent + "22", color: accent, border: `1px solid ${accent}44`, borderRadius: 6, fontSize: 12, cursor: "pointer", fontWeight: 500 }}>
                  Open decision →
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Landing page ──────────────────────────────────────────────────────────────
function LandingPage({ onNavigate }) {
  const { data: stats } = useFetch(`${API}/stats`);
  const { data: aaoStats } = useFetch(`${API}/aao/stats`);

  const modules = [
    { id: "balca", label: "BALCA / PERM Decisions", description: "Board of Alien Labor Certification Appeals — employer-sponsored green card appeals", count: stats?.total_decisions, countLabel: "decisions", accent: "#f59e0b", accentDim: "#f59e0b22", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>, available: true },
    { id: "aao", label: "AAO Decisions", description: "Administrative Appeals Office — USCIS benefit petition appeals across all visa categories", count: aaoStats?.total_decisions, countLabel: "decisions", accent: "#60a5fa", accentDim: "#60a5fa22", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>, available: true },
    { id: "regulations", label: "Regulations & Statutes", description: "8 CFR, 20 CFR, 22 CFR, and 29 CFR — full text search across 120 parts, 2,301 pages", accent: "#34d399", accentDim: "#34d39922", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>, available: true },
    { id: "policy", label: "Policy Manuals", description: "USCIS Policy Manual, Foreign Affairs Manual — agency guidance and adjudication policies", accent: "#a78bfa", accentDim: "#a78bfa22", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>, available: true },
    { id: "search-all", label: "Search All", description: "Cross-corpus search across decisions, regulations, and policy documents simultaneously", accent: "#fb7185", accentDim: "#fb718522", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>, available: true },
    { id: "aao-citation-graph", label: "AAO Citation Graph", description: "Map how AAO decisions cite each other — surface the most-referenced precedents and form-type patterns visually", accent: "#60a5fa", accentDim: "#60a5fa22", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>, available: true },
    { id: "citation-graph", label: "Citation Graph", description: "Map how search results cite each other — see the most-cited cases and citation branches emerge visually", accent: "#34d399", accentDim: "#34d39922", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>, available: true },
    { id: "perm-comparer", label: "PERM Comparer", description: "Compare job description and requirements language, validate PWD wage positioning, and export reports.", accent: "#f59e0b", accentDim: "#f59e0b22", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 1 1 0 10h-2"/><line x1="8" y1="12" x2="16" y2="12"/></svg>, available: true },
    { id: "visa-bulletin", label: "Visa Bulletin", description: "Monthly DOS priority dates — track cutoffs, retrogression, and backlog estimates for EB and family categories", accent: "#34d399", accentDim: "#34d39922", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>, available: true },
    { id: "oflc", label: "DOL Performance Data", description: "PERM, LCA, and Prevailing Wage disclosure data — 1.4M+ records across FY2020–FY2026. Dashboards, templates, and pivot builder.", accent: "#f59e0b", accentDim: "#f59e0b22", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>, available: true },
    { id: "ask", label: "Ask AI", description: "Ask a research question — get a cited answer synthesized across cases, regulations, and policy", accent: "#f472b6", accentDim: "#f472b622", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>, available: false, comingSoon: true },
    { id: "letter-assistant", label: "Letter Assistant", description: "AI-powered drafting and review for NIW and EB-1A support letters — powered by AAO precedent", accent: "#f59e0b", accentDim: "#f59e0b22", icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>, available: false, comingSoon: true },
  ];

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
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

const CORPUS_COLORS = {
  balca:      { color: "#f59e0b", label: "BALCA" },
  aao:        { color: "#60a5fa", label: "AAO" },
  regulation: { color: "#34d399", label: "Regulation" },
  policy:     { color: "#a78bfa", label: "Policy" },
};

function AskView({ onNavigate }) {
  const [question, setQuestion]         = useState("");
  const [corpusFilter, setCorpusFilter] = useState([]);
  const [loading, setLoading]           = useState(false);
  const [sources, setSources]           = useState(null);
  const [answer, setAnswer]             = useState("");
  const [ragStats, setRagStats]         = useState(null);
  const [error, setError]               = useState(null);
  const inputRef  = useRef(null);
  const answerRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
    fetch(`${API}/ask/stats`).then(r => r.json()).then(setRagStats).catch(() => {});
  }, []);

  const toggleCorpus = (c) =>
    setCorpusFilter(f => f.includes(c) ? f.filter(x => x !== c) : [...f, c]);

  const submit = async () => {
    if (!question.trim() || loading) return;
    setLoading(true);
    setSources(null);
    setAnswer("");
    setError(null);

    try {
      const res = await fetch(`${API}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: question.trim(),
          corpus_filter: corpusFilter,
          top_k: 12,
          stream: true,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError(err.detail || `Server error ${res.status}`);
        setLoading(false);
        return;
      }

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const evt = JSON.parse(line);
            if (evt.type === "sources") setSources(evt.sources);
            else if (evt.type === "token") {
              setAnswer(a => a + evt.text);
              setTimeout(() => answerRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), 0);
            }
          } catch {}
        }
      }
    } catch (e) {
      setError(e.message || "Request failed");
    }
    setLoading(false);
  };

  const renderAnswer = (text) => {
    const parts = text.split(/(\[\d+\])/g);
    return parts.map((part, i) => {
      const m = part.match(/^\[(\d+)\]$/);
      if (!m) return part;
      const ref = parseInt(m[1]);
      const src = sources?.find(s => s.ref === ref);
      return (
        <span key={i}
          title={src ? `${src.source_label}${src.cfr_citation ? ` — ${src.cfr_citation}` : ""}` : ""}
          style={{ display: "inline-block", padding: "0 4px", fontSize: 11, fontWeight: 600,
                   background: src ? `${CORPUS_COLORS[src.corpus]?.color}22` : "var(--bg2)",
                   color: src ? CORPUS_COLORS[src.corpus]?.color : "var(--text3)",
                   borderRadius: 4, cursor: src ? "pointer" : "default", margin: "0 1px" }}
          onClick={() => src && onNavigate && onNavigate(src.corpus, src.source_id)}
        >{part}</span>
      );
    });
  };

  const notReady = ragStats && ragStats.total_embedded === 0;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "20px 24px 16px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f472b6" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <span style={{ fontWeight: 600, fontSize: 15 }}>Ask AI</span>
          {ragStats && (
            <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text3)" }}>
              {ragStats.total_embedded.toLocaleString()} chunks indexed
            </span>
          )}
        </div>

        {/* Corpus filter pills */}
        <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
          {Object.entries(CORPUS_COLORS).map(([id, { color, label }]) => {
            const active = corpusFilter.includes(id);
            const stat   = ragStats?.by_corpus?.find(b => b.corpus === id);
            return (
              <button key={id} onClick={() => toggleCorpus(id)} style={{
                padding: "3px 10px", fontSize: 11, borderRadius: 20, cursor: "pointer",
                border: `1px solid ${active ? color : "var(--border)"}`,
                background: active ? `${color}22` : "transparent",
                color: active ? color : "var(--text3)", fontWeight: active ? 600 : 400,
              }}>
                {label}{stat ? ` · ${stat.embedded > 0 ? stat.chunks.toLocaleString() : "—"}` : ""}
              </button>
            );
          })}
          {corpusFilter.length > 0 && (
            <button onClick={() => setCorpusFilter([])} style={{ padding: "3px 10px", fontSize: 11,
              borderRadius: 20, border: "1px solid var(--border)", background: "transparent",
              color: "var(--text3)", cursor: "pointer" }}>
              Clear filter
            </button>
          )}
        </div>

        {/* Question input */}
        <div style={{ display: "flex", gap: 8 }}>
          <textarea ref={inputRef} value={question} onChange={e => setQuestion(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
            placeholder="Ask a research question… e.g. What is the standard for demonstrating specialty occupation for a software developer?"
            rows={2} style={{ flex: 1, padding: "10px 12px", fontSize: 13, borderRadius: "var(--radius)",
              border: "1px solid var(--border)", background: "var(--bg)", color: "var(--text)",
              resize: "none", fontFamily: "inherit", lineHeight: 1.5 }} />
          <button onClick={submit} disabled={loading || !question.trim() || notReady} style={{
            padding: "0 18px", borderRadius: "var(--radius)", border: "none", cursor: "pointer",
            background: loading ? "var(--bg2)" : "#f472b6",
            color: loading ? "var(--text3)" : "#fff", fontWeight: 600, fontSize: 13,
            opacity: (!question.trim() || notReady) ? 0.5 : 1 }}>
            {loading ? "…" : "Ask"}
          </button>
        </div>

        {notReady && (
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--amber)",
            background: "var(--amber-dim,#f59e0b22)", padding: "6px 10px", borderRadius: "var(--radius)" }}>
            RAG index is empty. Run <code>python3 ingest_rag.py --corpus regulation --corpus policy</code> to get started.
          </div>
        )}
      </div>

      {/* Results area */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        {error && (
          <div style={{ color: "var(--red,#f87171)", background: "var(--red-dim,#f8717122)",
            padding: "10px 14px", borderRadius: "var(--radius)", marginBottom: 16, fontSize: 13 }}>
            {error}
          </div>
        )}

        {loading && !answer && (
          <div style={{ color: "var(--text3)", fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ animation: "spin 1s linear infinite", display: "inline-block" }}>⟳</span>
            Searching {ragStats?.total_embedded?.toLocaleString()} chunks…
          </div>
        )}

        {/* Answer */}
        {answer && (
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 13, lineHeight: 1.75, color: "var(--text)", whiteSpace: "pre-wrap" }}>
              {renderAnswer(answer)}
            </div>
            <div ref={answerRef} />
          </div>
        )}

        {/* Sources */}
        {sources && sources.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)",
              textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>
              Sources retrieved ({sources.length})
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {sources.map(src => {
                const cc = CORPUS_COLORS[src.corpus] || { color: "#888", label: src.corpus };
                return (
                  <div key={src.ref} onClick={() => onNavigate && onNavigate(src.corpus, src.source_id)}
                    style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "8px 12px",
                      borderRadius: "var(--radius)", border: "1px solid var(--border)",
                      background: "var(--bg)", cursor: src.corpus === "regulation" || src.corpus === "policy" ? "default" : "pointer",
                      transition: "background 0.15s" }}
                    onMouseEnter={e => e.currentTarget.style.background = "var(--bg2)"}
                    onMouseLeave={e => e.currentTarget.style.background = "var(--bg)"}>
                    <span style={{ minWidth: 22, height: 22, borderRadius: 11, background: `${cc.color}22`,
                      color: cc.color, fontSize: 10, fontWeight: 700, display: "flex",
                      alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      {src.ref}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                        <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 10,
                          background: `${cc.color}22`, color: cc.color, fontWeight: 600 }}>
                          {cc.label}
                        </span>
                        {src.outcome && (
                          <span style={{ fontSize: 10, color: src.outcome === "Affirmed" ? "#34d399" :
                            src.outcome === "Reversed" ? "#f87171" : "var(--text3)" }}>
                            {src.outcome}
                          </span>
                        )}
                        <span style={{ fontSize: 10, color: "var(--text3)", marginLeft: "auto" }}>
                          {Math.round(src.similarity * 100)}% match
                        </span>
                      </div>
                      <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text)",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {src.source_label}
                      </div>
                      {(src.cfr_citation || src.source_date) && (
                        <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 1 }}>
                          {src.cfr_citation || src.source_date}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!loading && !answer && !error && (
          <div style={{ textAlign: "center", paddingTop: 60, color: "var(--text3)" }}>
            <div style={{ fontSize: 40, marginBottom: 16 }}>✦</div>
            <div style={{ fontSize: 15, fontWeight: 500, marginBottom: 8 }}>Ask anything about immigration law</div>
            <div style={{ fontSize: 13, maxWidth: 480, margin: "0 auto", lineHeight: 1.6 }}>
              Queries are answered from BALCA decisions, AAO decisions, federal regulations, and USCIS/FAM policy — with inline citations you can click to read the full source.
            </div>
            <div style={{ marginTop: 24, display: "flex", flexDirection: "column", gap: 8,
              maxWidth: 540, margin: "24px auto 0", textAlign: "left" }}>
              {[
                "What is the standard for demonstrating specialty occupation for a software developer?",
                "Can an employer reduce an offered wage after a PERM is approved?",
                "What recruitment steps are required before filing a PERM application?",
                "How does USCIS evaluate extraordinary ability claims under EB-1A?",
              ].map(q => (
                <button key={q} onClick={() => { setQuestion(q); setTimeout(() => inputRef.current?.focus(), 0); }}
                  style={{ padding: "8px 12px", fontSize: 12, textAlign: "left", borderRadius: "var(--radius)",
                    border: "1px solid var(--border)", background: "var(--bg)", color: "var(--text2)",
                    cursor: "pointer", lineHeight: 1.4 }}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── NavDropdown ───────────────────────────────────────────────────────────────
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
  const [view, setView] = useState("landing");
  const [externalDecision, setExternalDecision] = useState(null);
  const [searchKey, setSearchKey] = useState(0);
  const [headerQuery, setHeaderQuery] = useState("");
  const [graphSeed, setGraphSeed] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);

  const goHome = () => { setView("landing"); setExternalDecision(null); setSearchKey(k => k + 1); };
  const navigate = (id) => { if (id === "landing") { goHome(); } else { setView(id); } };
  const openDecision = (id, query = "", source = "balca") => { setExternalDecision({ id, query, source }); setView(source === "aao" ? "aao" : "balca"); };
  const openFromSearchAll = (corpus, id, query) => {
    if (corpus === "balca") { setExternalDecision({ id, query, source: "balca" }); setView("balca"); }
    else if (corpus === "aao") { setExternalDecision({ id, query, source: "aao" }); setView("aao"); }
    else setView(corpus === "regulation" ? "regulations" : "policy");
  };
  const openGraph    = (seed) => { setGraphSeed(seed); setSearchKey(k => k + 1); setView("citation-graph"); };
  const openGraphAAO = (seed) => { setGraphSeed(seed); setSearchKey(k => k + 1); setView("aao-citation-graph"); };

  const handleHeaderSearch = (e) => {
    e.preventDefault();
    if (!headerQuery.trim()) return;
    setSearchKey(k => k + 1);
    setView("search-all");
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
      { type: "sep" },
      { type: "item", id: "letter-assist",  label: "Letter Assist",      icon: icon.letter, disabled: true },
    ]},
    { label: "Data", items: [
      { type: "item", id: "oflc",           label: "DOL Data",           icon: icon.table },
      { type: "sep" },
      { type: "item", id: "uscis-data",     label: "USCIS Data",         icon: icon.table, disabled: true },
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
    ]},
    { section: "Data", items: [
      { id: "oflc",           label: "DOL Data",       icon: icon.table  },
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
          {/* Ask AI — commented out until built
          <button className={`header-icon-btn${view === "ask" ? " active" : ""}`}
            onClick={() => navigate("ask")} title="Ask AI" aria-label="Ask AI">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </button>
          */}
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
        {view === "citation-graph" && <CitationGraphView key={`graph-${searchKey}`} onNavigate={(id) => { setExternalDecision({ id, query: "", source: "balca" }); setView("balca"); }} initialQuery={graphSeed} />}
        {view === "aao-citation-graph" && <AAOCitationGraphView key={`aao-graph-${searchKey}`} onNavigate={(id) => { setExternalDecision({ id, query: "", source: "aao" }); setView("aao"); }} onOpenPrecedent={(id) => { setExternalDecision({ id, query: "", source: "aao" }); setView("aao"); }} initialQuery={graphSeed} />}
        {view === "ask" && <AskView onNavigate={(corpus, id) => { if (corpus === "balca") { setExternalDecision({ id, query: "", source: "balca" }); setView("balca"); } else if (corpus === "aao") { setExternalDecision({ id, query: "", source: "aao" }); setView("aao"); } else if (corpus === "regulation") { setView("regulations"); } else if (corpus === "policy") { setView("policy"); } }} />}
        {view === "perm-comparer" && <PermComparer />}
        {view === "visa-bulletin" && <VisaBulletinView />}
        {view === "projects" && <ProjectsView onOpenDecision={openDecision} />}
        {view === "oflc" && <OflcView />}
      </div>
    </div>
  );
}
