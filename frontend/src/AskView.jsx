import { useState, useEffect, useLayoutEffect, useRef } from "react";
import { API } from "./apiBase";

const CORPUS_COLORS = {
  balca:      { color: "var(--accent)", label: "BALCA" },
  aao:        { color: "var(--blue)", label: "AAO" },
  regulation: { color: "var(--green)", label: "Regulation" },
  policy:     { color: "#a78bfa", label: "Policy" },
  ina:        { color: "var(--amber)", label: "INA" },
};

const newConvId = () =>
  (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
        const r = Math.random() * 16 | 0; return (c === "x" ? r : (r & 0x3 | 0x8)).toString(16); });

// Survives unmount/remount so navigating to a source and back doesn't blank
// the thread. Backed by sessionStorage so it also survives a page refresh.
// turns: [{ question, condensed, answer, sources, savedRefs, error }]
const CACHE_KEY = "askview_cache_v2";
const askCache = (() => {
  const empty = { question: "", turns: [], corpusFilter: [], conversationId: newConvId() };
  try { return { ...empty, ...JSON.parse(sessionStorage.getItem(CACHE_KEY) || "{}") }; }
  catch { return empty; }
})();
const persistCache = () => {
  try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(askCache)); } catch {}
};

export function AskView({ onNavigate }) {
  const [question, setQuestion]         = useState(askCache.question);
  const [corpusFilter, setCorpusFilter] = useState(askCache.corpusFilter);
  const [turns, setTurns]               = useState(askCache.turns);
  const [conversationId, setConversationId] = useState(askCache.conversationId);
  const [loading, setLoading]           = useState(false);
  const [statusMsg, setStatusMsg]       = useState(null);
  const [ragStats, setRagStats]         = useState(null);
  const [popover, setPopover]           = useState(null);   // { turn, ref, top, left }
  const [projects, setProjects]         = useState(null);   // lazy-loaded list
  const [copiedTurn, setCopiedTurn]     = useState(null);
  const [openSources, setOpenSources]   = useState({});     // turnIdx -> bool (default: latest open)
  const inputRef  = useRef(null);
  const turnRefs  = useRef({});          // turnIdx -> element
  const pendingScrollRef = useRef(null); // turnIdx to bring to the top after it renders
  const [paneH, setPaneH] = useState(0);  // measured height of the thread pane
  const abortRef  = useRef(null);
  const popoverTimer = useRef(null);
  const resultsRef   = useRef(null);

  useEffect(() => {
    Object.assign(askCache, { question, turns, corpusFilter, conversationId });
    if (!loading) persistCache();   // skip per-token writes during streaming
  }, [question, turns, corpusFilter, conversationId, loading]);

  useEffect(() => {
    inputRef.current?.focus();
    fetch(`${API}/ask/stats`).then(r => r.json()).then(setRagStats).catch(() => {});
    return () => abortRef.current?.abort();   // navigating away mid-stream: stop cleanly, keep partial
  }, []);

  const toggleCorpus = (c) =>
    setCorpusFilter(f => f.includes(c) ? f.filter(x => x !== c) : [...f, c]);

  const patchTurn = (idx, fn) =>
    setTurns(ts => ts.map((t, i) => (i === idx ? fn(t) : t)));

  // Scroll policy: the ONLY automatic scroll is on submit — bring the new question to the
  // top of the pane so the answer reads top-down as it streams. Never follow the stream.
  useEffect(() => {
    const pane = resultsRef.current; if (!pane) return;
    const ro = new ResizeObserver(() => setPaneH(pane.clientHeight));
    ro.observe(pane); setPaneH(pane.clientHeight);
    return () => ro.disconnect();
  }, []);

  useLayoutEffect(() => {
    const idx = pendingScrollRef.current;
    if (idx == null) return;
    const el = turnRefs.current[idx], pane = resultsRef.current;
    if (!el || !pane) return;
    pendingScrollRef.current = null;
    pane.scrollTop = el.offsetTop - 24;
  }, [turns.length]);

  const newConversation = () => {
    abortRef.current?.abort();
    setTurns([]); setPopover(null); setStatusMsg(null); setLoading(false);
    setOpenSources({}); setConversationId(newConvId());
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const submit = async () => {
    const q = question.trim();
    if (!q || loading) return;
    const idx = turns.length;
    const history = turns.flatMap(t => [
      { role: "user", content: t.question },
      { role: "assistant", content: t.answer || "" },
    ]).filter(m => m.content);
    setTurns(ts => [...ts, { question: q, condensed: null, answer: "", sources: null, savedRefs: {}, error: null, tools: [] }]);
    setOpenSources({});
    setQuestion("");
    setLoading(true);
    setStatusMsg(null);
    setPopover(null);
    pendingScrollRef.current = idx;
    abortRef.current = new AbortController();

    try {
      const res = await fetch(`${API}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: abortRef.current.signal,
        body: JSON.stringify({
          question: q, corpus_filter: corpusFilter, top_k: 12, stream: true,
          history, conversation_id: conversationId,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        patchTurn(idx, t => ({ ...t, error: err.detail || `Server error ${res.status}` }));
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
            if (evt.type === "sources") patchTurn(idx, t => ({ ...t, sources: evt.sources }));
            else if (evt.type === "condensed") patchTurn(idx, t => ({ ...t, condensed: evt.query }));
            else if (evt.type === "status") {
              setStatusMsg(evt.text);
              patchTurn(idx, t => ({ ...t, tools: [...new Set([...(t.tools || []), evt.text])] }));
            }
            else if (evt.type === "error") patchTurn(idx, t => ({ ...t, error: evt.message }));
            else if (evt.type === "token") {
              setStatusMsg(null);
              patchTurn(idx, t => ({ ...t, answer: t.answer + evt.text }));
            }
          } catch {}
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") patchTurn(idx, t => ({ ...t, error: e.message || "Request failed" }));
    }
    setStatusMsg(null);
    setLoading(false);
  };

  const stopGeneration = () => { abortRef.current?.abort(); setStatusMsg(null); setLoading(false); };

  // ── Citation hover popover ──────────────────────────────────────────────
  const openPopover = (turnIdx, ref, el) => {
    clearTimeout(popoverTimer.current);
    const rect = el.getBoundingClientRect();
    const cont = resultsRef.current?.getBoundingClientRect();
    if (!cont) return;
    setPopover({
      turn: turnIdx, ref,
      top:  rect.bottom - cont.top + resultsRef.current.scrollTop + 6,
      left: Math.min(Math.max(rect.left - cont.left - 140, 8), cont.width - 380),
    });
    if (projects === null)
      fetch(`${API}/projects`).then(r => r.json()).then(setProjects).catch(() => setProjects([]));
  };
  const scheduleClosePopover = () => {
    clearTimeout(popoverTimer.current);
    popoverTimer.current = setTimeout(() => setPopover(null), 250);
  };
  const cancelClosePopover = () => clearTimeout(popoverTimer.current);

  const saveToProject = async (turnIdx, src, projectId, projectName) => {
    try {
      const r = await fetch(`${API}/projects/${projectId}/research`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          corpus: src.corpus, source_id: src.source_id,
          source_label: src.source_label, cfr_citation: src.cfr_citation,
          excerpt: src.excerpt, question: turns[turnIdx]?.question,
        }),
      });
      if (r.ok) patchTurn(turnIdx, t => ({ ...t, savedRefs: { ...t.savedRefs, [src.ref]: projectName } }));
    } catch {}
  };

  const copyAnswer = (turnIdx) => {
    const t = turns[turnIdx];
    let out = t.answer;
    if (t.sources?.length) {
      out += "\n\nSources:\n" + t.sources.map(s =>
        `[${s.ref}] ${s.source_label}${s.cfr_citation ? ` — ${s.cfr_citation}` : ""}`).join("\n");
    }
    navigator.clipboard.writeText(out).then(() => {
      setCopiedTurn(turnIdx);
      setTimeout(() => setCopiedTurn(null), 1600);
    });
  };

  // ── Inline pieces: citations + light markdown ───────────────────────────
  const renderInline = (text, keyBase, turnIdx, sources) => {
    const parts = text.split(/(\[\d+\]|\*\*[^*]+\*\*)/g);
    return parts.map((part, i) => {
      const cite = part.match(/^\[(\d+)\]$/);
      if (cite) {
        const ref = parseInt(cite[1]);
        const src = sources?.find(s => s.ref === ref);
        return (
          <span key={`${keyBase}-${i}`}
            onMouseEnter={e => src && openPopover(turnIdx, ref, e.currentTarget)}
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

  const renderAnswer = (text, turnIdx, sources) => {
    const blocks = [];
    const lines = text.split("\n");
    lines.forEach((line, li) => {
      const h = line.match(/^(#{1,3})\s+(.*)/);
      if (h) {
        blocks.push(
          <div key={li} style={{ fontWeight: 600, color: "var(--text)",
            fontSize: h[1].length === 1 ? 15 : h[1].length === 2 ? 14 : 13,
            margin: `${li === 0 ? 0 : 14}px 0 6px` }}>
            {renderInline(h[2], li, turnIdx, sources)}
          </div>);
        return;
      }
      const bullet = line.match(/^\s*[-•]\s+(.*)/);
      const numbered = line.match(/^\s*(\d+)\.\s+(.*)/);
      if (bullet || numbered) {
        blocks.push(
          <div key={li} style={{ display: "flex", gap: 8, margin: "3px 0", paddingLeft: 6 }}>
            <span style={{ color: "var(--text3)", flexShrink: 0 }}>{numbered ? `${numbered[1]}.` : "•"}</span>
            <span>{renderInline(bullet ? bullet[1] : numbered[2], li, turnIdx, sources)}</span>
          </div>);
        return;
      }
      if (!line.trim()) { blocks.push(<div key={li} style={{ height: 8 }} />); return; }
      blocks.push(<div key={li}>{renderInline(line, li, turnIdx, sources)}</div>);
    });
    return blocks;
  };

  const notReady = ragStats && ragStats.total_embedded === 0;
  const lastIdx  = turns.length - 1;
  const spinner  = <span style={{ animation: "spin 1s linear infinite", display: "inline-block" }}>⟳</span>;
  const TOOL_LABELS = {
    "Looking up employer representation…": "employer representation records",
    "Looking up the firm's clients…": "law-firm client records",
    "Querying OFLC disclosure data…": "OFLC disclosure data",
    "Checking DOL processing times…": "DOL processing times",
    "Checking the visa bulletin…": "the visa bulletin",
    "Looking up the decision…": "the decision text",
    "Searching the regulations and policy manuals…": "the regulations and policy manuals",
  };
  const COL = 860;   // reading column width
  const column = { maxWidth: COL, margin: "0 auto", width: "100%" };

  const submitLabel = loading ? "…" : turns.length ? "Ask" : "Ask";

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg)" }}>

      {/* Top bar: title, new conversation, index size */}
      <div style={{ flexShrink: 0, borderBottom: "1px solid var(--border)" }}>
        <div style={{ ...column, display: "flex", alignItems: "center", gap: 12, padding: "12px 24px" }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f472b6" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <span style={{ fontWeight: 600, fontSize: 14 }}>Ask AI</span>
          {turns.length > 0 && (
            <button onClick={newConversation} style={{ fontSize: 12, padding: "4px 10px", borderRadius: 6,
              border: "1px solid var(--border)", background: "transparent", color: "var(--text2)", cursor: "pointer" }}>
              New conversation
            </button>
          )}
          {ragStats && (
            <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text3)" }}>
              {ragStats.total_embedded.toLocaleString()} passages indexed
            </span>
          )}
        </div>
      </div>

      {/* Thread — the only automatic scroll is on submit (see useLayoutEffect) */}
      <div ref={resultsRef}
        style={{ flex: 1, minHeight: 0, overflowY: "auto", position: "relative", overflowAnchor: "none" }}>
        <div style={{ ...column, padding: "8px 24px 40px" }}>

          {turns.length === 0 && (
            <div style={{ paddingTop: 72, maxWidth: 560 }}>
              <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em", color: "var(--text)", lineHeight: 1.3 }}>
                Ask a research question.
              </div>
              <div style={{ fontSize: 14, color: "var(--text2)", lineHeight: 1.6, marginTop: 10 }}>
                Answers come from BALCA and AAO decisions, the regulations, USCIS and FAM policy, and live DOL filing
                data, with citations you can open. Follow-ups keep the context of the conversation.
              </div>
              <div style={{ marginTop: 28, display: "flex", flexDirection: "column", gap: 6 }}>
                {[
                  "What did BALCA decide in Solar Turbines?",
                  "Who represents Toyota Motor North America on their immigration filings?",
                  "Can an employer reduce an offered wage after a PERM is approved?",
                  "How long are PERMs taking to process right now?",
                ].map(q => (
                  <button key={q} onClick={() => { setQuestion(q); setTimeout(() => inputRef.current?.focus(), 0); }}
                    style={{ padding: "8px 0", fontSize: 13, textAlign: "left", border: "none", borderBottom: "1px solid var(--border)",
                      background: "transparent", color: "var(--text2)", cursor: "pointer", lineHeight: 1.4, whiteSpace: "normal", height: "auto" }}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t, idx) => {
            const isLast = idx === lastIdx;
            const streaming = loading && isLast;
            const citedRefs = new Set([...(t.answer || "").matchAll(/\[(\d+)\]/g)].map(m => parseInt(m[1])));
            const cited = (t.sources || []).filter(s => citedRefs.has(s.ref));
            const uncited = (t.sources || []).filter(s => !citedRefs.has(s.ref));
            const showAll = openSources[idx] ?? false;
            const chips = showAll ? (t.sources || []) : cited;
            const toolNames = [...new Set((t.tools || []).map(x => TOOL_LABELS[x] || x.replace(/…$/, "")))];
            return (
              <div key={idx} ref={el => { turnRefs.current[idx] = el; }}
                style={{ paddingTop: idx === 0 ? 28 : 40,
                         // the last entry fills the pane so its question can sit at the top on submit
                         // measured, not percentage: percentage heights don't resolve inside the column
                         minHeight: isLast && turns.length > 1 && paneH ? paneH - 40 : undefined }}>

                {/* Question — the heading of the entry */}
                <div style={{ fontSize: 19, fontWeight: 600, letterSpacing: "-0.01em", lineHeight: 1.35,
                              color: "var(--text)", maxWidth: "36em" }}>
                  {t.question}
                </div>
                {t.condensed && t.condensed !== t.question && (
                  <div style={{ fontSize: 12, color: "var(--text3)", marginTop: 6 }}>
                    Searched as: {t.condensed}
                  </div>
                )}

                {t.error && (
                  <div style={{ color: "var(--red,#bf4b4b)", fontSize: 13, marginTop: 14 }}>{t.error}</div>
                )}

                {streaming && !t.answer && !t.error && (
                  <div style={{ color: "var(--text3)", fontSize: 13, display: "flex", alignItems: "center", gap: 8, marginTop: 18 }}>
                    {spinner}{statusMsg || "Searching the corpus"}
                  </div>
                )}

                {/* Answer — the document */}
                {t.answer && (
                  <div style={{ fontSize: 14.5, lineHeight: 1.7, color: "var(--text)", marginTop: 18, maxWidth: "72ch" }}>
                    {renderAnswer(t.answer, idx, t.sources)}
                    {streaming && statusMsg && (
                      <div style={{ color: "var(--text3)", fontSize: 12, display: "flex", alignItems: "center", gap: 8, marginTop: 10 }}>
                        {spinner}{statusMsg}
                      </div>
                    )}
                  </div>
                )}

                {/* Provenance — one quiet line, after the answer finishes */}
                {t.answer && !streaming && (
                  <div style={{ marginTop: 18, paddingTop: 12, borderTop: "1px solid var(--border)", maxWidth: "72ch",
                                fontSize: 12, color: "var(--text3)", lineHeight: 1.8 }}>
                    {toolNames.length > 0 && (
                      <div>Data from {toolNames.join(", ")}.</div>
                    )}
                    {chips.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: toolNames.length ? 6 : 0 }}>
                        {chips.map(src => {
                          const cc = CORPUS_COLORS[src.corpus] || { color: "#888", label: src.corpus };
                          const saved = t.savedRefs?.[src.ref];
                          return (
                            <button key={src.ref}
                              onMouseEnter={e => openPopover(idx, src.ref, e.currentTarget)}
                              onMouseLeave={scheduleClosePopover}
                              onClick={() => onNavigate && onNavigate(src.corpus, src.source_id)}
                              title={saved ? `Saved to ${saved}` : src.source_label}
                              style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "2px 8px 2px 6px",
                                fontSize: 11.5, borderRadius: 5, cursor: "pointer", fontFamily: "inherit",
                                border: `1px solid ${cc.color}44`, background: `${cc.color}0f`, color: "var(--text2)" }}>
                              <span style={{ fontWeight: 700, color: cc.color }}>{src.ref}</span>
                              <span style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {src.source_label}
                              </span>
                              {src.outcome && <span style={{ color: "var(--text3)" }}>{src.outcome}</span>}
                              {saved && <span style={{ color: "var(--green)" }}>✓</span>}
                            </button>
                          );
                        })}
                      </div>
                    )}
                    <div style={{ display: "flex", gap: 14, marginTop: 6 }}>
                      <button onClick={() => copyAnswer(idx)} style={{ fontSize: 12, padding: 0, border: "none",
                        background: "transparent", color: copiedTurn === idx ? "var(--green)" : "var(--text3)", cursor: "pointer" }}>
                        {copiedTurn === idx ? "Copied" : "Copy answer"}
                      </button>
                      {uncited.length > 0 && (
                        <button onClick={() => setOpenSources(o => ({ ...o, [idx]: !showAll }))}
                          style={{ fontSize: 12, padding: 0, border: "none", background: "transparent", color: "var(--text3)", cursor: "pointer" }}>
                          {showAll ? "Hide uncited passages" : `${uncited.length} more retrieved passages`}
                        </button>
                      )}
                    </div>
                  </div>
                )}
                {streaming && t.answer && (
                  <div style={{ marginTop: 12 }}>
                    <button onClick={stopGeneration} style={{ fontSize: 12, padding: "3px 10px", borderRadius: 6,
                      border: "1px solid var(--border)", background: "transparent", color: "var(--text3)", cursor: "pointer" }}>
                      Stop
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Citation hover popover */}
        {popover && (() => {
          const t = turns[popover.turn];
          const src = t?.sources?.find(s => s.ref === popover.ref);
          if (!src) return null;
          const cc = CORPUS_COLORS[src.corpus] || { color: "#888", label: src.corpus };
          const saved = t.savedRefs?.[src.ref];
          return (
            <div onMouseEnter={cancelClosePopover} onMouseLeave={scheduleClosePopover}
              style={{ position: "absolute", top: popover.top, left: popover.left, width: 380,
                zIndex: 40, background: "var(--bg)", border: "1px solid var(--border2, var(--border))",
                borderRadius: 8, boxShadow: "0 8px 28px rgba(0,0,0,0.18)", padding: "12px 14px" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: cc.color }}>{cc.label}</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>
                  {src.source_label}{src.cfr_citation ? ` — ${src.cfr_citation}` : ""}
                </span>
                <span style={{ fontSize: 11, color: "var(--text3)", marginLeft: "auto" }}>
                  {src.match_type === "decision" ? "the decision itself" :
                   src.match_type === "keyword" ? "name match" : `${Math.round(src.similarity * 100)}% match`}
                </span>
              </div>
              <div style={{ fontSize: 12.5, lineHeight: 1.6, color: "var(--text2)", maxHeight: 170,
                overflowY: "auto", background: "var(--bg2)", borderRadius: 6,
                padding: "8px 10px", marginBottom: 10, whiteSpace: "pre-wrap" }}>
                {src.excerpt || "No preview available."}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {src.corpus !== "regulation" && src.corpus !== "policy" && src.corpus !== "ina" && (
                  <button onClick={() => onNavigate && onNavigate(src.corpus, src.source_id)}
                    style={{ fontSize: 12, padding: "3px 10px", borderRadius: 6, cursor: "pointer",
                      border: `1px solid ${cc.color}66`, background: "transparent", color: cc.color }}>
                    Open decision
                  </button>
                )}
                {saved ? (
                  <span style={{ fontSize: 12, color: "var(--green)", marginLeft: "auto" }}>Saved to {saved}</span>
                ) : (
                  <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 12, color: "var(--text3)" }}>Save to</span>
                    {projects === null && <span style={{ fontSize: 12, color: "var(--text3)" }}>…</span>}
                    {projects?.length === 0 && <span style={{ fontSize: 12, color: "var(--text3)" }}>no projects yet</span>}
                    {projects?.slice(0, 3).map(p => (
                      <button key={p.id} onClick={() => saveToProject(popover.turn, src, p.id, p.name)}
                        title={`Save to ${p.name}`}
                        style={{ fontSize: 12, padding: "3px 10px", borderRadius: 6, cursor: "pointer",
                          border: "1px solid var(--border)", background: "var(--bg2)",
                          color: "var(--text2)", maxWidth: 120, overflow: "hidden",
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
      </div>

      {/* Composer */}
      <div style={{ flexShrink: 0, borderTop: "1px solid var(--border)", background: "var(--bg)" }}>
        <div style={{ ...column, padding: "12px 24px 14px" }}>
          <div style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--bg)",
                        boxShadow: "0 1px 2px rgba(0,0,0,0.04)" }}>
            <textarea ref={inputRef} value={question} onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
              placeholder={turns.length ? "Ask a follow-up" : "Ask about a decision, a regulation, an employer, or a filing trend"}
              rows={2}
              style={{ display: "block", width: "100%", padding: "12px 14px 6px", fontSize: 14, border: "none",
                background: "transparent", color: "var(--text)", resize: "none", fontFamily: "inherit",
                lineHeight: 1.5, outline: "none", boxSizing: "border-box" }} />
            <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 10px 10px", flexWrap: "wrap" }}>
              <span style={{ fontSize: 11, color: "var(--text3)", marginRight: 2 }}>
                {corpusFilter.length ? "Searching" : "Search"}
              </span>
              {Object.entries(CORPUS_COLORS).map(([id, { color, label }]) => {
                const active = corpusFilter.includes(id);
                return (
                  <button key={id} onClick={() => toggleCorpus(id)} title={`${active ? "Exclude" : "Limit to"} ${label}`} style={{
                    padding: "2px 8px", fontSize: 11, borderRadius: 5, cursor: "pointer", fontFamily: "inherit",
                    border: `1px solid ${active ? color : "var(--border)"}`,
                    background: active ? `${color}18` : "transparent",
                    color: active ? color : "var(--text3)", fontWeight: active ? 600 : 400,
                  }}>
                    {label}
                  </button>
                );
              })}
              {corpusFilter.length > 0 && (
                <button onClick={() => setCorpusFilter([])} style={{ padding: "2px 6px", fontSize: 11,
                  border: "none", background: "transparent", color: "var(--text3)", cursor: "pointer" }}>
                  all
                </button>
              )}
              <button onClick={submit} disabled={loading || !question.trim() || notReady} style={{
                marginLeft: "auto", padding: "6px 16px", borderRadius: 7, border: "none", cursor: "pointer",
                background: loading ? "var(--bg2)" : "#f472b6",
                color: loading ? "var(--text3)" : "#fff", fontWeight: 600, fontSize: 13,
                opacity: (!question.trim() || notReady) ? 0.5 : 1 }}>
                {submitLabel}
              </button>
            </div>
          </div>
          {notReady && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--amber)" }}>
              The index is empty. Run <code>python3 ingest_rag.py --corpus regulation --corpus policy</code> first.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── NavDropdown ───────────────────────────────────────────────────────────────
