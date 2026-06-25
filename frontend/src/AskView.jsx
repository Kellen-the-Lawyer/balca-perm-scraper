import { useState, useEffect, useRef } from "react";
import { API } from "./apiBase";

export function AskView({ onNavigate }) {
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
            background: "var(--amber-dim,#2dd4bf22)", padding: "6px 10px", borderRadius: "var(--radius)" }}>
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
