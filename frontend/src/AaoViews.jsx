import { useState, useEffect, useCallback, useRef } from "react";
import { API } from "./apiBase";
import { ReadLaterPopup, Spinner, useFetch } from "./common";

export const AAO_OUTCOME = {
  Sustained: { bg: "var(--green-dim)",  text: "var(--green)",  dot: "#34d399" },
  Dismissed: { bg: "var(--bg4)",        text: "var(--text2)",  dot: "#5a5a68" },
  Remanded:  { bg: "var(--yellow-dim)", text: "#fbbf24",       dot: "#fbbf24" },
  Withdrawn: { bg: "var(--bg4)",        text: "var(--text3)",  dot: "#334155" },
};

export function AaoBadge({ label, small }) {
  const c = AAO_OUTCOME[label] || { bg: "var(--bg4)", text: "var(--text2)", dot: "#5a5a68" };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, background: c.bg, color: c.text, fontSize: small ? 10 : 11, fontWeight: 500, padding: small ? "2px 6px" : "3px 8px", borderRadius: 4, letterSpacing: "0.03em" }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: c.dot, flexShrink: 0 }} />
      {label}
    </span>
  );
}

// ── AAO Search View ───────────────────────────────────────────────────────────

export function AAOSearchView({ externalDecisionId, externalQuery, onViewGraph }) {
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
              <button onClick={() => setAdvOpen(o => !o)} style={{ fontSize: 11, padding: "3px 10px", height: "auto", background: advOpen || advancedCount > 0 ? "var(--amber-dim)" : "var(--bg3)", color: advOpen || advancedCount > 0 ? "var(--amber)" : "var(--text3)", border: advOpen || advancedCount > 0 ? "1px solid #2dd4bf44" : "1px solid var(--border)", borderRadius: 20, display: "flex", alignItems: "center", gap: 5 }}>
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
              <div style={{ padding: splitView ? "8px 12px 4px" : "10px 24px 4px", fontSize: 10, fontWeight: 600, color: "#2dd4bf", fontFamily: "'DM Mono', monospace", letterSpacing: "0.08em", textTransform: "uppercase", display: "flex", alignItems: "center", gap: 6 }}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="#2dd4bf"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                I&amp;N Dec. Precedents
              </div>
              {matchedPrecedents.map(p => (
                <div key={p.id} onClick={() => { setSelectedId(p.id); setPrecId(null); }}
                  style={{ padding: splitView ? "8px 12px" : "10px 24px", cursor: "pointer", display: "flex", alignItems: "flex-start", gap: 10, borderLeft: "2px solid #2dd4bf44", transition: "background 0.1s" }}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{p.party_name}</span>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: "#2dd4bf", fontWeight: 500 }}>{p.citation}</span>
                      {p.year && <span style={{ fontSize: 11, color: "var(--text3)" }}>{p.year}</span>}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 2 }}>
                      {p.decision_type === "adopted" ? "Adopted Decision" : "I&N Dec. Precedent"}
                      {p.cited_by_count > 0 && <span style={{ marginLeft: 8, color: "#2dd4bf88" }}>cited {p.cited_by_count.toLocaleString()}× in AAO decisions</span>}
                    </div>
                  </div>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#2dd4bf" strokeWidth="2" opacity="0.5" style={{ flexShrink: 0, marginTop: 2 }}><polyline points="9 18 15 12 9 6"/></svg>
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

export function AAOResultRow({ row, onSelect, selected, compact, index, activeQuery }) {
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

export function PrecedentDetail({ id, onClose, onViewGraph, showGraphButton }) {
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

export function AAODecisionDetail({ decisionId, query, onNavigate, precedentMap, onViewGraph }) {
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
