import { useState, useEffect, useCallback, useRef } from "react";
import { API } from "./apiBase";
import { HighlightedText, InDocSearch, Spinner, useDocSearch, useFetch } from "./common";

export const AGENCY_COLORS = {
  "DHS / USCIS":      { accent: "#34d399", dim: "#34d39922" },
  "DOL / ETA":        { accent: "#34d399", dim: "#34d39922" },
  "DOL / WHD":        { accent: "#4ade80", dim: "#4ade8022" },
  "State Department": { accent: "#60a5fa", dim: "#60a5fa22" },
};

export function RegulationsView() {
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

export function RegulationDetail({ docId, query }) {
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

export const SOURCE_COLORS = {
  "FAM":      { accent: "#60a5fa", dim: "#60a5fa22", label: "Foreign Affairs Manual" },
  "USCIS_PM": { accent: "#a78bfa", dim: "#a78bfa22", label: "USCIS Policy Manual" },
};

export function PolicyView() {
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

export function PolicyDetail({ docId, query }) {
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
