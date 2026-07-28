import { useState, useEffect, useRef } from "react";
import { API } from "./apiBase";

const CORPUS_COLORS = {
  balca:      { color: "var(--accent)", label: "BALCA" },
  aao:        { color: "var(--blue)", label: "AAO" },
  regulation: { color: "var(--green)", label: "Regulation" },
  policy:     { color: "#a78bfa", label: "Policy" },
  ina:        { color: "var(--amber)", label: "INA" },
};

// Survives unmount/remount so navigating to a source and back doesn't
// blank the results or force a re-query. Backed by sessionStorage so
// results also survive a page refresh (cleared when the tab closes).
const CACHE_KEY = "askview_cache_v1";
const askCache = (() => {
  const empty = { question: "", askedQuestion: "", answer: "", sources: null,
                  corpusFilter: [], savedRefs: {} };
  try { return { ...empty, ...JSON.parse(sessionStorage.getItem(CACHE_KEY) || "{}") }; }
  catch { return empty; }
})();
const persistCache = () => {
  try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(askCache)); } catch {}
};

export function AskView({ onNavigate }) {
  const [question, setQuestion]         = useState(askCache.question);
  const [corpusFilter, setCorpusFilter] = useState(askCache.corpusFilter);
  const [loading, setLoading]           = useState(false);
  const [statusMsg, setStatusMsg]       = useState(null);
  const [sources, setSources]           = useState(askCache.sources);
  const [answer, setAnswer]             = useState(askCache.answer);
  const [ragStats, setRagStats]         = useState(null);
  const [error, setError]               = useState(null);
  const [askedQuestion, setAskedQuestion] = useState(askCache.askedQuestion);
  const [popover, setPopover]           = useState(null);   // { ref, top, left }
  const [projects, setProjects]         = useState(null);   // lazy-loaded list
  const [savedRefs, setSavedRefs]       = useState(askCache.savedRefs);     // ref -> project name
  const [copied, setCopied]             = useState(false);
  const inputRef  = useRef(null);
  const answerRef = useRef(null);
  const abortRef  = useRef(null);
  const popoverTimer = useRef(null);
  const resultsRef   = useRef(null);

  // Keep the module cache current so results survive navigation and refresh.
  useEffect(() => {
    Object.assign(askCache, { question, askedQuestion, answer, sources, corpusFilter, savedRefs });
    if (!loading) persistCache();   // skip per-token writes during streaming
  }, [question, askedQuestion, answer, sources, corpusFilter, savedRefs, loading]);

  useEffect(() => {
    inputRef.current?.focus();
    fetch(`${API}/ask/stats`).then(r => r.json()).then(setRagStats).catch(() => {});
    return () => abortRef.current?.abort();   // navigating away mid-stream: stop cleanly, keep partial
  }, []);

  const toggleCorpus = (c) =>
    setCorpusFilter(f => f.includes(c) ? f.filter(x => x !== c) : [...f, c]);

  const submit = async () => {
    if (!question.trim() || loading) return;
    setLoading(true);
    setStatusMsg(null);
    setSources(null);
    setAnswer("");
    setError(null);
    setPopover(null);
    setSavedRefs({});
    setAskedQuestion(question.trim());
    abortRef.current = new AbortController();

    try {
      const res = await fetch(`${API}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: abortRef.current.signal,
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
            else if (evt.type === "status") setStatusMsg(evt.text);
            else if (evt.type === "token") {
              setStatusMsg(null);
              setAnswer(a => a + evt.text);
              setTimeout(() => answerRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), 0);
            }
          } catch {}
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") setError(e.message || "Request failed");
    }
    setStatusMsg(null);
    setLoading(false);
  };

  const stopGeneration = () => { abortRef.current?.abort(); setStatusMsg(null); setLoading(false); };

  // ── Citation hover popover ──────────────────────────────────────────────
  const openPopover = (ref, el) => {
    clearTimeout(popoverTimer.current);
    const rect = el.getBoundingClientRect();
    const cont = resultsRef.current?.getBoundingClientRect();
    if (!cont) return;
    setPopover({
      ref,
      top:  rect.bottom - cont.top + resultsRef.current.scrollTop + 6,
      left: Math.min(Math.max(rect.left - cont.left - 140, 8),
                     cont.width - 380),
    });
    if (projects === null)
      fetch(`${API}/projects`).then(r => r.json()).then(setProjects).catch(() => setProjects([]));
  };
  const scheduleClosePopover = () => {
    clearTimeout(popoverTimer.current);
    popoverTimer.current = setTimeout(() => setPopover(null), 250);
  };
  const cancelClosePopover = () => clearTimeout(popoverTimer.current);

  const saveToProject = async (src, projectId, projectName) => {
    try {
      const r = await fetch(`${API}/projects/${projectId}/research`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          corpus: src.corpus, source_id: src.source_id,
          source_label: src.source_label, cfr_citation: src.cfr_citation,
          excerpt: src.excerpt, question: askedQuestion,
        }),
      });
      if (r.ok) setSavedRefs(s => ({ ...s, [src.ref]: projectName }));
    } catch {}
  };

  const copyAnswer = () => {
    let out = answer;
    if (sources?.length) {
      out += "\n\nSources:\n" + sources.map(s =>
        `[${s.ref}] ${s.source_label}${s.cfr_citation ? ` — ${s.cfr_citation}` : ""}`).join("\n");
    }
    navigator.clipboard.writeText(out).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    });
  };

  // ── Inline pieces: citations + light markdown ───────────────────────────
  const renderInline = (text, keyBase) => {
    const parts = text.split(/(\[\d+\]|\*\*[^*]+\*\*)/g);
    return parts.map((part, i) => {
      const cite = part.match(/^\[(\d+)\]$/);
      if (cite) {
        const ref = parseInt(cite[1]);
        const src = sources?.find(s => s.ref === ref);
        return (
          <span key={`${keyBase}-${i}`}
            onMouseEnter={e => src && openPopover(ref, e.currentTarget)}
            onMouseLeave={scheduleClosePopover}
            onClick={() => src && onNavigate && onNavigate(src.corpus, src.source_id)}
            style={{ display: "inline-block", padding: "0 4px", fontSize: 11, fontWeight: 600,
                     background: src ? `${(CORPUS_COLORS[src.corpus]?.color) || "#888"}22` : "var(--bg2)",
                     color: src ? (CORPUS_COLORS[src.corpus]?.color || "#888") : "var(--text3)",
                     borderRadius: 4, cursor: src ? "pointer" : "default", margin: "0 1px" }}
          >{part}</span>
        );
      }
      const bold = part.match(/^\*\*([^*]+)\*\*$/);
      if (bold) return <strong key={`${keyBase}-${i}`}>{bold[1]}</strong>;
      return part;
    });
  };

  const renderAnswer = (text) => {
    const blocks = [];
    const lines = text.split("\n");
    lines.forEach((line, li) => {
      const h = line.match(/^(#{1,3})\s+(.*)/);
      if (h) {
        blocks.push(
          <div key={li} style={{ fontWeight: 600, color: "var(--text)",
            fontSize: h[1].length === 1 ? 15 : h[1].length === 2 ? 14 : 13,
            margin: `${li === 0 ? 0 : 14}px 0 6px` }}>
            {renderInline(h[2], li)}
          </div>);
        return;
      }
      const bullet = line.match(/^\s*[-•]\s+(.*)/);
      const numbered = line.match(/^\s*(\d+)\.\s+(.*)/);
      if (bullet || numbered) {
        blocks.push(
          <div key={li} style={{ display: "flex", gap: 8, margin: "3px 0", paddingLeft: 6 }}>
            <span style={{ color: "var(--text3)", flexShrink: 0 }}>{numbered ? `${numbered[1]}.` : "•"}</span>
            <span>{renderInline(bullet ? bullet[1] : numbered[2], li)}</span>
          </div>);
        return;
      }
      if (!line.trim()) { blocks.push(<div key={li} style={{ height: 8 }} />); return; }
      blocks.push(<div key={li}>{renderInline(line, li)}</div>);
    });
    return blocks;
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
            background: "var(--amber-dim,#315f7c22)", padding: "6px 10px", borderRadius: "var(--radius)" }}>
            RAG index is empty. Run <code>python3 ingest_rag.py --corpus regulation --corpus policy</code> to get started.
          </div>
        )}
      </div>

      {/* Results area */}
      <div ref={resultsRef} style={{ flex: 1, overflowY: "auto", padding: "20px 24px", position: "relative" }}>
        {error && (
          <div style={{ color: "var(--red,#bf4b4b)", background: "var(--red-dim,#bf4b4b22)",
            padding: "10px 14px", borderRadius: "var(--radius)", marginBottom: 16, fontSize: 13 }}>
            {error}
          </div>
        )}

        {loading && !answer && (
          <div style={{ color: "var(--text3)", fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ animation: "spin 1s linear infinite", display: "inline-block" }}>⟳</span>
            {statusMsg || <>Searching {ragStats?.total_embedded?.toLocaleString()} chunks…</>}
          </div>
        )}

        {/* Answer */}
        {answer && (
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)",
                textTransform: "uppercase", letterSpacing: "0.06em" }}>Answer</span>
              {loading && (
                <button onClick={stopGeneration} style={{ fontSize: 11, padding: "2px 10px",
                  borderRadius: 12, border: "1px solid var(--border)", background: "transparent",
                  color: "var(--text3)", cursor: "pointer" }}>■ Stop</button>
              )}
              {!loading && (
                <button onClick={copyAnswer} style={{ fontSize: 11, padding: "2px 10px",
                  borderRadius: 12, border: "1px solid var(--border)", background: "transparent",
                  color: copied ? "var(--green)" : "var(--text3)", cursor: "pointer" }}>
                  {copied ? "✓ Copied" : "Copy answer"}
                </button>
              )}
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.75, color: "var(--text)" }}>
              {renderAnswer(answer)}
            </div>
            {loading && statusMsg && (
              <div style={{ color: "var(--text3)", fontSize: 12, display: "flex",
                alignItems: "center", gap: 8, marginTop: 10 }}>
                <span style={{ animation: "spin 1s linear infinite", display: "inline-block" }}>⟳</span>
                {statusMsg}
              </div>
            )}
            <div ref={answerRef} />
          </div>
        )}

        {/* Citation hover popover */}
        {popover && (() => {
          const src = sources?.find(s => s.ref === popover.ref);
          if (!src) return null;
          const cc = CORPUS_COLORS[src.corpus] || { color: "#888", label: src.corpus };
          const saved = savedRefs[src.ref];
          return (
            <div onMouseEnter={cancelClosePopover} onMouseLeave={scheduleClosePopover}
              style={{ position: "absolute", top: popover.top, left: popover.left, width: 360,
                zIndex: 40, background: "var(--bg)", border: "1px solid var(--border2, var(--border))",
                borderRadius: "var(--radius-lg)", boxShadow: "0 8px 28px rgba(0,0,0,0.35)",
                padding: "12px 14px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 10,
                  background: `${cc.color}22`, color: cc.color, fontWeight: 600 }}>{cc.label}</span>
                <span style={{ fontSize: 10, color: "var(--text3)", marginLeft: "auto" }}>
                  {Math.round(src.similarity * 100)}% match
                </span>
              </div>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", marginBottom: 6 }}>
                {src.source_label}{src.cfr_citation ? ` — ${src.cfr_citation}` : ""}
              </div>
              <div style={{ fontSize: 12, lineHeight: 1.6, color: "var(--text2)", maxHeight: 150,
                overflowY: "auto", background: "var(--bg2)", borderRadius: "var(--radius)",
                padding: "8px 10px", marginBottom: 10, whiteSpace: "pre-wrap" }}>
                {src.excerpt || "No preview available."}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {src.corpus !== "regulation" && src.corpus !== "policy" && src.corpus !== "ina" && (
                  <button onClick={() => onNavigate && onNavigate(src.corpus, src.source_id)}
                    style={{ fontSize: 11, padding: "3px 10px", borderRadius: 12, cursor: "pointer",
                      border: `1px solid ${cc.color}55`, background: "transparent", color: cc.color }}>
                    Open source
                  </button>
                )}
                {saved ? (
                  <span style={{ fontSize: 11, color: "var(--green)", marginLeft: "auto" }}>✓ Saved to {saved}</span>
                ) : (
                  <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 11, color: "var(--text3)" }}>Save to:</span>
                    {projects === null && <span style={{ fontSize: 11, color: "var(--text3)" }}>…</span>}
                    {projects?.length === 0 && <span style={{ fontSize: 11, color: "var(--text3)" }}>no projects yet</span>}
                    {projects?.slice(0, 3).map(p => (
                      <button key={p.id} onClick={() => saveToProject(src, p.id, p.name)}
                        title={`Save to ${p.name}`}
                        style={{ fontSize: 11, padding: "3px 10px", borderRadius: 12, cursor: "pointer",
                          border: "1px solid var(--border)", background: "var(--bg2)",
                          color: "var(--text2)", maxWidth: 110, overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%",
                          background: p.color, marginRight: 5 }} />{p.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })()}

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
                          <span style={{ fontSize: 10, color: src.outcome === "Affirmed" ? "#27815f" :
                            src.outcome === "Reversed" ? "#bf4b4b" : "var(--text3)" }}>
                            {src.outcome}
                          </span>
                        )}
                        <span style={{ fontSize: 10, color: "var(--text3)", marginLeft: "auto" }}>
                          {Math.round(src.similarity * 100)}% match
                        </span>
                        <button
                          onClick={e => { e.stopPropagation(); openPopover(src.ref, e.currentTarget); }}
                          onMouseLeave={scheduleClosePopover}
                          title={savedRefs[src.ref] ? `Saved to ${savedRefs[src.ref]}` : "Preview & save to project"}
                          style={{ fontSize: 11, background: "none", border: "none", cursor: "pointer",
                            color: savedRefs[src.ref] ? "var(--green)" : "var(--text3)", padding: "0 2px" }}>
                          {savedRefs[src.ref] ? "✓" : "⤷ save"}
                        </button>
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
