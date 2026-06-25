import { useState, useEffect, useCallback, useRef } from "react";
import { API } from "./apiBase";
import { Spinner } from "./common";

export const CORPUS_META = {
  balca:      { label: "BALCA",       accent: "var(--amber)",  dim: "var(--amber-dim)",  dot: "#2dd4bf" },
  aao:        { label: "AAO",         accent: "var(--blue)",   dim: "var(--blue-dim)",   dot: "#60a5fa" },
  regulation: { label: "Regulations", accent: "var(--green)",  dim: "var(--green-dim)",  dot: "#34d399" },
  policy:     { label: "Policy",      accent: "#a78bfa",       dim: "#a78bfa22",         dot: "#a78bfa" },
};

export function SearchAllView({ onNavigate, initialQuery }) {
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
