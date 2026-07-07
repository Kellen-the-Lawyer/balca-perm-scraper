import { useState, useEffect, useRef } from "react";
import { API } from "./apiBase";

export const OUTCOME = {
  Affirmed:  { bg: "var(--green-dim)",  text: "var(--green)",  dot: "#27815f" },
  Reversed:  { bg: "var(--red-dim)",    text: "var(--red)",    dot: "#bf4b4b" },
  Remanded:  { bg: "var(--yellow-dim)", text: "#b47718",       dot: "#b47718" },
  Dismissed: { bg: "var(--bg4)",        text: "var(--text2)",  dot: "#5a5a68" },
};

export function Badge({ label, small }) {
  const c = OUTCOME[label] || { bg: "var(--bg4)", text: "var(--text2)", dot: "#5a5a68" };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, background: c.bg, color: c.text, fontSize: small ? 10 : 11, fontWeight: 500, padding: small ? "2px 6px" : "3px 8px", borderRadius: 4, letterSpacing: "0.03em" }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: c.dot, flexShrink: 0 }} />
      {label}
    </span>
  );
}

// ── Read Later hover popup ────────────────────────────────────────────────────

export function ReadLaterPopup({ caseNumber, caseId, caseSource, fromCaseNumber, fromSource, onNavigate, children }) {
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

export function useDocSearch() {
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

export function InDocSearch({ hook, accentColor = "var(--amber)" }) {
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

export function HighlightedText({ text, activeDocQ, matchIndex, resetMatches, registerRef }) {
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
              background: isActive ? "#315f7c" : "#315f7c44",
              color: isActive ? "#000" : "inherit",
              borderRadius: 2,
              outline: isActive ? "2px solid #315f7c" : "none",
            }}>
            {part}
          </mark>
        );
      })}
    </pre>
  );
}

export function RegBadge({ label }) {
  return <span style={{ background: "var(--amber-dim)", color: "var(--amber)", border: "1px solid #315f7c33", fontSize: 10, fontWeight: 500, padding: "2px 7px", borderRadius: 4 }}>{label}</span>;
}

export function useFetch(url) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!url) return;
    setLoading(true); setData(null);
    fetch(url).then(r => r.json()).then(d => { setData(d); setLoading(false); }).catch(() => setLoading(false));
  }, [url]);
  return { data, loading };
}

export function Spinner() {
  return (
    <div style={{ padding: "40px 20px", display: "flex", justifyContent: "center" }}>
      <div style={{ width: 20, height: 20, border: "2px solid var(--border2)", borderTopColor: "var(--amber)", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// ── Search view — owns all search + detail state ──────────────────────────────

export const PROJECT_COLORS_INLINE = ["#315f7c","#27815f","#315f7c","#bf4b4b","#a78bfa","#fb7185","#4ade80","#38bdf8"];

export function SaveToProject({ decisionId, searchQuery, small }) {
  const [projects, setProjects] = useState(null);
  const [saved, setSaved] = useState([]);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(PROJECT_COLORS_INLINE[0]);
  const ref = useRef(null);
  const newNameRef = useRef(null);

  const load = async () => {
    const [all, mine] = await Promise.all([
      fetch(`${API}/projects`).then(r => r.json()),
      fetch(`${API}/decisions/${decisionId}/projects`).then(r => r.json()),
    ]);
    setProjects(all);
    setSaved(mine.map(p => p.id));
  };

  useEffect(() => { if (open) load(); }, [open, decisionId]);

  useEffect(() => {
    if (!open) return;
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) { setOpen(false); setCreating(false); setNewName(""); } };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => { if (creating) setTimeout(() => newNameRef.current?.focus(), 40); }, [creating]);

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

  const createAndAdd = async () => {
    if (!newName.trim()) return;
    setSaving("new");
    const p = await fetch(`${API}/projects`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName.trim(), description: "", color: newColor }),
    }).then(r => r.json());
    await fetch(`${API}/projects/${p.id}/cases`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision_id: decisionId, search_query: searchQuery || "" }),
    });
    setProjects(prev => [...(prev || []), p]);
    setSaved(s => [...s, p.id]);
    setCreating(false);
    setNewName("");
    setNewColor(PROJECT_COLORS_INLINE[0]);
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
        border: isSaved ? "1px solid #315f7c44" : "1px solid var(--border)",
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
          borderRadius: "var(--radius-lg)", minWidth: 230, boxShadow: "0 8px 24px #00000044",
          animation: "fadeUp 0.12s ease",
        }}>
          <div style={{ padding: "10px 14px 6px", fontSize: 11, color: "var(--text3)", fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}>
            Save to project
          </div>
          {projects === null && <div style={{ padding: "8px 14px" }}><Spinner /></div>}
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
          <div style={{ borderTop: "1px solid var(--border)", padding: "8px 14px 10px" }}>
            {!creating ? (
              <button onClick={() => setCreating(true)} style={{
                display: "flex", alignItems: "center", gap: 6, fontSize: 12,
                color: "var(--text3)", background: "none", border: "none", padding: 0, cursor: "pointer",
              }}
                onMouseEnter={e => e.currentTarget.style.color = "var(--amber)"}
                onMouseLeave={e => e.currentTarget.style.color = "var(--text3)"}>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>
                </svg>
                New project
              </button>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, animation: "fadeUp 0.1s ease" }}>
                <input
                  ref={newNameRef}
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") createAndAdd(); if (e.key === "Escape") { setCreating(false); setNewName(""); } }}
                  placeholder="Project name"
                  style={{ fontSize: 12, height: 30 }}
                />
                <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                  {PROJECT_COLORS_INLINE.map(c => (
                    <div key={c} onClick={() => setNewColor(c)} style={{
                      width: 14, height: 14, borderRadius: "50%", background: c, cursor: "pointer",
                      outline: newColor === c ? `2px solid ${c}` : "none", outlineOffset: 2,
                    }} />
                  ))}
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button onClick={createAndAdd} disabled={!newName.trim() || saving === "new"}
                    className="primary" style={{ fontSize: 11, padding: "4px 12px", opacity: saving === "new" ? 0.6 : 1 }}>
                    {saving === "new" ? "Creating…" : "Create & add"}
                  </button>
                  <button onClick={() => { setCreating(false); setNewName(""); }}
                    style={{ fontSize: 11, padding: "4px 8px" }}>Cancel</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Projects view ─────────────────────────────────────────────────────────────

export const PROJECT_COLORS = ["#315f7c","#27815f","#315f7c","#bf4b4b","#a78bfa","#fb7185","#4ade80","#38bdf8"];
