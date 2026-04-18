import { useState, useEffect, useCallback, useRef } from "react";
import "./index.css";

const API = "/api";

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
function SearchView({ externalDecisionId, externalQuery }) {
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
    setCaseNumber(""); setPanel(""); setHasCitations(""); setHasRegulations(""); setSortBy("relevance");
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
    if (sortBy !== "relevance") p.set("sort_by", sortBy);
    const res = await fetch(`${API}/search?${p}`);
    const data = await res.json();
    setResults(data); setPage(pg); setLoading(false);
    setActiveQuery(q);
  }, [q, outcome, regulation, dateFrom, dateTo, employer, caseNumber, panel, hasCitations, hasRegulations, sortBy]);

  const splitView = searched && selectedId;

  return (
    <div style={{ height: "100%", display: "flex", overflow: "hidden" }}>

      {/* ── Left panel ── */}
      <div style={{
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
                  placeholder={searched ? "New search…" : "Search opinions, employers, regulations…"}
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
        <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", animation: "fadeUp 0.18s ease" }}>
          <DecisionDetail
            decisionId={selectedId}
            query={activeQuery}
            onNavigate={(id) => setSelectedId(id)}
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
function DecisionDetail({ decisionId, query, onNavigate }) {
  const { data, loading } = useFetch(decisionId ? `${API}/decisions/${decisionId}` : null);
  const [activeTab, setActiveTab] = useState("text");
  const [newNote, setNewNote] = useState("");
  const [notes, setNotes] = useState(null);
  const firstMatchRef = useRef(null);
  const contentRef = useRef(null);

  useEffect(() => { if (data) { setNotes(data.notes); setActiveTab("text"); } }, [data]);

  useEffect(() => {
    if (activeTab === "text" && firstMatchRef.current) {
      setTimeout(() => firstMatchRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 120);
    }
  }, [activeTab, data]);

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
    if (!query?.trim()) return <pre style={ps}>{text}</pre>;
    const terms = query.trim().split(/\s+/).filter(t => t.length > 2);
    if (!terms.length) return <pre style={ps}>{text}</pre>;
    const pattern = new RegExp(`(${terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
    const parts = text.split(pattern);
    let firstMark = false;
    return (
      <pre style={ps}>
        {parts.map((part, i) => {
          if (pattern.test(part)) {
            pattern.lastIndex = 0;
            const isFirst = !firstMark;
            if (isFirst) firstMark = true;
            return <mark key={i} ref={isFirst ? firstMatchRef : null}>{part}</mark>;
          }
          pattern.lastIndex = 0;
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

  const load = () => {
    setLoading(true);
    fetch(`${API}/projects/${projectId}`).then(r => r.json()).then(d => { setProject(d); setLoading(false); });
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
export default function App() {
  const [view, setView] = useState("search");
  const [externalDecision, setExternalDecision] = useState(null); // {id, query}
  const [searchKey, setSearchKey] = useState(0);

  const goHome = () => { setView("search"); setExternalDecision(null); setSearchKey(k => k + 1); };

  // Open a decision from any view — switches to search and opens the case
  const openDecision = (id, query = "") => {
    setExternalDecision({ id, query });
    setView("search");
  };

  const navItems = [
    { id: "search", label: "Search", icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg> },
    { id: "regulations", label: "Regulations", icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg> },
    { id: "stats", label: "Overview", icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg> },
    { id: "projects", label: "Projects", icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> },
  ];

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", borderBottom: "1px solid var(--border)", padding: "0 20px", height: 46, flexShrink: 0, background: "var(--bg2)", gap: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginRight: 20 }}>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--amber)" }} />
          <span onClick={goHome} style={{ fontSize: 13, fontWeight: 600, color: "var(--text)", fontFamily: "'DM Serif Display', serif", cursor: "pointer" }}>BALCA Research</span>
        </div>
        {navItems.map(n => (
          <button key={n.id} onClick={() => setView(n.id)} style={{
            display: "flex", alignItems: "center", gap: 6, padding: "0 12px", height: 30, fontSize: 12,
            background: "none", border: view === n.id ? "1px solid var(--border2)" : "1px solid transparent",
            borderRadius: "var(--radius)", color: view === n.id ? "var(--text)" : "var(--text3)", fontWeight: view === n.id ? 500 : 400,
          }}>{n.icon}{n.label}</button>
        ))}
      </div>
      <div style={{ flex: 1, overflow: "hidden" }}>
        {view === "search" && (
          <SearchView key={searchKey}
            externalDecisionId={externalDecision?.id}
            externalQuery={externalDecision?.query}
          />
        )}
        {view === "regulations" && (
          <RegsBrowser onSelectDecision={id => openDecision(id, "")} />
        )}
        {view === "stats" && <div style={{ height: "100%", overflowY: "auto" }}><StatsDashboard /></div>}
        {view === "projects" && <ProjectsView onOpenDecision={openDecision} />}
      </div>
    </div>
  );
}
