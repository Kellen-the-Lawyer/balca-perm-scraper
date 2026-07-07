import { useState, useEffect, useRef, useCallback } from "react";
import { API } from "./apiBase";

const TOKEN_KEY = "kanban_token";
function getToken() { return localStorage.getItem(TOKEN_KEY) || ""; }

function kanbanFetch(path, opts = {}) {
  return fetch(`${API}/kanban${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", "x-kanban-token": getToken(), ...(opts.headers || {}) },
  });
}

const COLS = [
  { id: "todo",       label: "To Do",      accent: "#a4a4b3" },
  { id: "inprogress", label: "In Progress", accent: "#315f7c" },
  { id: "review",     label: "Review",      accent: "#315f7c" },
  { id: "done",       label: "Done",        accent: "#27815f" },
];

const PRIORITY = {
  high: { label: "High",   bg: "#bf4b4b18", text: "#bf4b4b", dot: "#bf4b4b" },
  med:  { label: "Medium", bg: "#315f7c18", text: "#315f7c", dot: "#315f7c" },
  low:  { label: "Low",    bg: "#27815f18", text: "#27815f", dot: "#27815f" },
};

const PROJECT = {
  graphite: { label: "Graphite", bg: "#a78bfa18", text: "#a78bfa", dot: "#a78bfa" },
  casebase: { label: "Casebase", bg: "#27815f18", text: "#27815f", dot: "#27815f" },
};

// ── Shared primitives ─────────────────────────────────────────────────────────

function PriBadge({ p, small }) {
  const c = PRIORITY[p] || PRIORITY.med;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, background: c.bg, color: c.text,
      fontSize: small ? 10 : 11, fontWeight: 500, padding: small ? "1px 5px" : "2px 7px", borderRadius: 4 }}>
      <span style={{ width: 4, height: 4, borderRadius: "50%", background: c.dot, flexShrink: 0 }} />
      {c.label}
    </span>
  );
}

function ProjBadge({ p }) {
  const c = PROJECT[p] || { label: p, bg: "var(--bg4)", text: "var(--text3)", dot: "var(--text3)" };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, background: c.bg, color: c.text,
      fontSize: 10, fontWeight: 500, padding: "1px 6px", borderRadius: 4 }}>
      <span style={{ width: 4, height: 4, borderRadius: "50%", background: c.dot, flexShrink: 0 }} />
      {c.label}
    </span>
  );
}

function Spinner() {
  return (
    <div style={{ padding: "40px 20px", display: "flex", justifyContent: "center" }}>
      <div style={{ width: 20, height: 20, border: "2px solid var(--border2)",
        borderTopColor: "var(--amber)", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
    </div>
  );
}

// ── Card ─────────────────────────────────────────────────────────────────────

function KanbanCard({ card, onEdit, onDelete, showProject, dragHandlers }) {
  const [hovered, setHovered] = useState(false);
  const dragEndTime = useRef(0);
  return (
    <div
      draggable
      onDragStart={dragHandlers.onDragStart}
      onDragEnd={(e) => { dragEndTime.current = Date.now(); dragHandlers.onDragEnd(e); }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => { if (Date.now() - dragEndTime.current > 200) onEdit(card); }}
      style={{ background: "var(--bg2)", border: "1px solid var(--border)",
        borderLeft: `3px solid ${PRIORITY[card.priority]?.dot || "var(--border)"}`,
        borderRadius: "var(--radius-lg)", padding: "10px 12px", cursor: "pointer",
        transition: "border-color 0.12s, background 0.12s", position: "relative",
        ...(hovered ? { borderColor: "var(--border2)", background: "var(--bg3)" } : {}) }}
    >
      {hovered && (
        <button onClick={(e) => { e.stopPropagation(); onDelete(card.id); }}
          style={{ position: "absolute", top: 7, right: 7, width: 20, height: 20, padding: 0,
            minHeight: "unset", background: "var(--bg4)", border: "1px solid var(--border2)",
            borderRadius: 4, fontSize: 12, display: "flex", alignItems: "center",
            justifyContent: "center", color: "var(--text3)" }}
          onMouseEnter={e => { e.currentTarget.style.color = "var(--red)"; e.currentTarget.style.borderColor = "var(--red)"; }}
          onMouseLeave={e => { e.currentTarget.style.color = "var(--text3)"; e.currentTarget.style.borderColor = "var(--border2)"; }}
        >×</button>
      )}
      <div style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.4, marginBottom: 8, paddingRight: 20,
        color: hovered ? "var(--amber)" : "var(--text)", transition: "color 0.12s" }}>
        {card.title}
      </div>
      {card.notes && (
        <div style={{ fontSize: 11, color: "var(--text3)", lineHeight: 1.5, marginBottom: 8,
          fontStyle: "italic", display: "-webkit-box", WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical", overflow: "hidden" }}>
          {card.notes}
        </div>
      )}
      <div style={{ display: "flex", gap: 5, flexWrap: "wrap", alignItems: "center" }}>
        <PriBadge p={card.priority} small />
        {showProject && card.project && <ProjBadge p={card.project} />}
        {card.assigned_to && (
          <span style={{ fontSize: 10, background: "var(--bg4)", color: "var(--text3)",
            border: "1px solid var(--border)", padding: "1px 6px", borderRadius: 4,
            fontFamily: "'DM Mono', monospace" }}>
            {card.assigned_to}
          </span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text3)",
          fontFamily: "'DM Mono', monospace" }}>#{card.id}</span>
      </div>
    </div>
  );
}

// ── Column ────────────────────────────────────────────────────────────────────

function KanbanColumn({ col, cards, onEdit, onDelete, onDrop, showProject }) {
  const [dragOver, setDragOver] = useState(false);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { e.preventDefault(); setDragOver(false); onDrop(col.id); }}
      style={{ display: "flex", flexDirection: "column", minHeight: 100,
        background: dragOver ? `${col.accent}0d` : "var(--bg3)",
        border: `1px solid ${dragOver ? col.accent + "44" : "var(--border)"}`,
        borderRadius: "var(--radius-lg)", padding: 10, transition: "background 0.15s, border-color 0.15s" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, padding: "0 2px" }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: col.accent, flexShrink: 0 }} />
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text2)",
          textTransform: "uppercase", letterSpacing: "0.07em", flex: 1 }}>{col.label}</span>
        <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace",
          background: "var(--bg4)", border: "1px solid var(--border)", padding: "1px 7px", borderRadius: 10 }}>
          {cards.length}
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 7, flex: 1 }}>
        {cards.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--text3)", textAlign: "center", padding: "14px 0", opacity: 0.5 }}>
            Empty
          </div>
        )}
        {cards.map(card => (
          <KanbanCard key={card.id} card={card} onEdit={onEdit} onDelete={onDelete}
            showProject={showProject}
            dragHandlers={{
              onDragStart: () => { window.__kanbanDragId = card.id; },
              onDragEnd: () => { window.__kanbanDragId = null; },
            }} />
        ))}
      </div>
    </div>
  );
}

// ── Card modal (project cards) ────────────────────────────────────────────────

function CardModal({ card, defaultProject, onSave, onClose, isBoard }) {
  const isNew = !card?.id;
  const [form, setForm] = useState({
    title:       card?.title       || "",
    project:     card?.project     || defaultProject || "casebase",
    col:         card?.col         || "todo",
    priority:    card?.priority    || "med",
    notes:       card?.notes       || "",
    assigned_to: card?.assigned_to || "",
  });
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const handleSave = () => { if (!form.title.trim()) return; onSave(isNew ? form : { ...card, ...form }); };
  const backdropRef = useRef(null);
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  const label = (txt) => <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 4, marginTop: 12 }}>{txt}</div>;
  const inp = { fontSize: 13, background: "var(--bg3)" };

  return (
    <div ref={backdropRef} onClick={(e) => { if (e.target === backdropRef.current) onClose(); }}
      style={{ position: "fixed", inset: 0, zIndex: 400, background: "rgba(0,0,0,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: "var(--bg2)", border: "1px solid var(--border2)", borderRadius: "var(--radius-lg)",
        padding: "20px 22px", width: 380, maxWidth: "92vw", boxShadow: "0 20px 50px rgba(0,0,0,0.6)" }}>
        <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text)", marginBottom: 4 }}>
          {isNew ? "New card" : "Edit card"}
        </div>
        <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 16 }}>
          {isNew ? "Add to the board" : `Card #${card.id}`}
        </div>
        {label("Title")}
        <input autoFocus value={form.title} onChange={e => set("title", e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleSave()} placeholder="What needs doing?" style={inp} />
        {!isBoard && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div>{label("Project")}
              <select value={form.project} onChange={e => set("project", e.target.value)} style={inp}>
                <option value="graphite">Graphite</option>
                <option value="casebase">Casebase</option>
              </select>
            </div>
            <div>{label("Column")}
              <select value={form.col} onChange={e => set("col", e.target.value)} style={inp}>
                {COLS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </div>
          </div>
        )}
        {isBoard && (
          <div>{label("Column")}
            <select value={form.col} onChange={e => set("col", e.target.value)} style={inp}>
              {COLS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div>{label("Priority")}
            <select value={form.priority} onChange={e => set("priority", e.target.value)} style={inp}>
              <option value="high">High</option>
              <option value="med">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
          <div>{label("Assigned to")}
            <input value={form.assigned_to} onChange={e => set("assigned_to", e.target.value)}
              placeholder="agent / person" style={inp} />
          </div>
        </div>
        {label("Notes")}
        <textarea value={form.notes} onChange={e => set("notes", e.target.value)}
          placeholder="Any context, links, or details…" rows={3} style={{ ...inp, resize: "vertical" }} />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={handleSave} disabled={!form.title.trim()}
            style={{ opacity: form.title.trim() ? 1 : 0.4 }}>
            {isNew ? "Add card" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Token gate ────────────────────────────────────────────────────────────────

function TokenGate({ onAuthenticated }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const attempt = async () => {
    setLoading(true); setError(false);
    localStorage.setItem(TOKEN_KEY, token);
    const res = await fetch(`${API}/kanban/stats`, { headers: { "x-kanban-token": token } });
    if (res.ok) { onAuthenticated(); } else { localStorage.removeItem(TOKEN_KEY); setError(true); }
    setLoading(false);
  };
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center", gap: 16 }}>
      <div style={{ textAlign: "center", marginBottom: 8 }}>
        <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 24, color: "var(--text)", marginBottom: 6 }}>Kanban</div>
        <div style={{ fontSize: 13, color: "var(--text3)" }}>Enter your board token to continue</div>
      </div>
      <div style={{ display: "flex", gap: 8, width: "100%", maxWidth: 340 }}>
        <input type="password" value={token} onChange={e => setToken(e.target.value)}
          onKeyDown={e => e.key === "Enter" && attempt()} placeholder="x-kanban-token" autoFocus
          style={{ flex: 1, fontFamily: "'DM Mono', monospace", fontSize: 13 }} />
        <button className="primary" onClick={attempt} disabled={!token || loading}>{loading ? "…" : "Enter"}</button>
      </div>
      {error && <div style={{ fontSize: 12, color: "var(--red)" }}>Invalid token. Try again.</div>}
    </div>
  );
}

// ── Board name modal ──────────────────────────────────────────────────────────

function BoardNameModal({ board, onSave, onClose }) {
  const [name, setName] = useState(board?.name || "");
  const backdropRef = useRef(null);
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div ref={backdropRef} onClick={(e) => { if (e.target === backdropRef.current) onClose(); }}
      style={{ position: "fixed", inset: 0, zIndex: 400, background: "rgba(0,0,0,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: "var(--bg2)", border: "1px solid var(--border2)",
        borderRadius: "var(--radius-lg)", padding: "20px 22px", width: 340, maxWidth: "90vw",
        boxShadow: "0 20px 50px rgba(0,0,0,0.6)" }}>
        <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text)", marginBottom: 16 }}>
          {board ? "Rename board" : "New board"}
        </div>
        <input autoFocus value={name} onChange={e => setName(e.target.value)}
          onKeyDown={e => e.key === "Enter" && name.trim() && onSave(name.trim())}
          placeholder="Board name…" style={{ fontSize: 13, background: "var(--bg3)", width: "100%" }} />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={() => name.trim() && onSave(name.trim())}
            disabled={!name.trim()} style={{ opacity: name.trim() ? 1 : 0.4 }}>
            {board ? "Rename" : "Create board"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Board view (personal boards) ──────────────────────────────────────────────

function BoardView({ board }) {
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await kanbanFetch(`/boards/${board.id}/cards`);
    const data = await res.json();
    setCards(data);
    setLoading(false);
  }, [board.id]);

  useEffect(() => { load(); }, [load]);

  const handleDrop = async (colId) => {
    const cardId = window.__kanbanDragId;
    if (!cardId) return;
    const card = cards.find(c => c.id === cardId);
    if (!card || card.col === colId) return;
    setCards(cs => cs.map(c => c.id === cardId ? { ...c, col: colId } : c));
    await kanbanFetch(`/boards/${board.id}/cards/${cardId}`, {
      method: "PATCH", body: JSON.stringify({ col: colId }),
    });
  };

  const handleSave = async (formData) => {
    if (formData.id) {
      const res = await kanbanFetch(`/boards/${board.id}/cards/${formData.id}`, {
        method: "PATCH", body: JSON.stringify(formData),
      });
      const updated = await res.json();
      setCards(cs => cs.map(c => c.id === updated.id ? updated : c));
    } else {
      const res = await kanbanFetch(`/boards/${board.id}/cards`, {
        method: "POST", body: JSON.stringify(formData),
      });
      const created = await res.json();
      setCards(cs => [...cs, created]);
    }
    setModal(null);
  };

  const handleDelete = async (id) => {
    setCards(cs => cs.filter(c => c.id !== id));
    await kanbanFetch(`/boards/${board.id}/cards/${id}`, { method: "DELETE" });
  };

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end",
        padding: "8px 16px 0", gap: 8 }}>
        <button onClick={load} disabled={loading}
          style={{ fontSize: 11, padding: "4px 10px", height: "auto", minHeight: "unset",
            background: "none", border: "1px solid var(--border)", color: "var(--text3)",
            opacity: loading ? 0.5 : 1 }}>↺</button>
        <button className="primary" onClick={() => setModal({ card: null })}
          style={{ fontSize: 12, padding: "5px 14px", height: "auto", minHeight: "unset" }}>
          + Add card
        </button>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "10px 16px 14px" }}>
        {loading && cards.length === 0 && <Spinner />}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10, alignItems: "start" }}>
          {COLS.map(col => (
            <KanbanColumn key={col.id} col={col}
              cards={cards.filter(c => c.col === col.id)}
              onEdit={(card) => setModal({ card })}
              onDelete={handleDelete}
              onDrop={handleDrop}
              showProject={false} />
          ))}
        </div>
      </div>
      {modal && (
        <CardModal card={modal.card} isBoard onSave={handleSave} onClose={() => setModal(null)} />
      )}
    </>
  );
}

// ── Main KanbanView ───────────────────────────────────────────────────────────

export function KanbanView() {
  const [authed, setAuthed] = useState(!!getToken());
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(false);
  const [project, setProject] = useState("casebase");
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);

  // Boards state
  const [boards, setBoards] = useState([]);
  const [activeBoard, setActiveBoard] = useState(null); // null = project view, board obj = board view
  const [boardModal, setBoardModal] = useState(null);   // null | { board: null } | { board: obj }
  const [renamingBoard, setRenamingBoard] = useState(null);

  const loadCards = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await kanbanFetch("/cards");
      if (res.status === 401) { setAuthed(false); return; }
      setCards(await res.json());
    } catch { setError("Failed to load cards."); }
    finally { setLoading(false); }
  }, []);

  const loadBoards = useCallback(async () => {
    const res = await kanbanFetch("/boards");
    if (res.ok) setBoards(await res.json());
  }, []);

  useEffect(() => { if (authed) { loadCards(); loadBoards(); } }, [authed, loadCards, loadBoards]);

  const visibleCards = project === "all" ? cards : cards.filter(c => c.project === project);

  const handleDrop = async (colId) => {
    const cardId = window.__kanbanDragId;
    if (!cardId) return;
    const card = cards.find(c => c.id === cardId);
    if (!card || card.col === colId) return;
    setCards(cs => cs.map(c => c.id === cardId ? { ...c, col: colId } : c));
    await kanbanFetch(`/cards/${cardId}`, { method: "PATCH", body: JSON.stringify({ col: colId }) });
  };

  const handleSave = async (formData) => {
    if (formData.id) {
      const res = await kanbanFetch(`/cards/${formData.id}`, { method: "PATCH", body: JSON.stringify(formData) });
      const updated = await res.json();
      setCards(cs => cs.map(c => c.id === updated.id ? updated : c));
    } else {
      const res = await kanbanFetch("/cards", { method: "POST", body: JSON.stringify(formData) });
      const created = await res.json();
      setCards(cs => [...cs, created]);
    }
    setModal(null);
  };

  const handleDelete = async (id) => {
    setCards(cs => cs.filter(c => c.id !== id));
    await kanbanFetch(`/cards/${id}`, { method: "DELETE" });
  };

  const handleCreateBoard = async (name) => {
    const res = await kanbanFetch("/boards", { method: "POST", body: JSON.stringify({ name }) });
    const board = await res.json();
    setBoards(bs => [...bs, board]);
    setBoardModal(null);
    setActiveBoard(board);
  };

  const handleRenameBoard = async (name) => {
    const res = await kanbanFetch(`/boards/${renamingBoard.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
    const updated = await res.json();
    setBoards(bs => bs.map(b => b.id === updated.id ? updated : b));
    if (activeBoard?.id === updated.id) setActiveBoard(updated);
    setRenamingBoard(null);
  };

  const handleDeleteBoard = async (board) => {
    if (!confirm(`Delete "${board.name}" and all its cards?`)) return;
    await kanbanFetch(`/boards/${board.id}`, { method: "DELETE" });
    setBoards(bs => bs.filter(b => b.id !== board.id));
    if (activeBoard?.id === board.id) setActiveBoard(null);
  };

  if (!authed) return <TokenGate onAuthenticated={() => setAuthed(true)} />;

  const projectTabs = [
    { id: "casebase", label: "Casebase", dot: "#27815f" },
    { id: "graphite", label: "Graphite", dot: "#a78bfa" },
    { id: "all",      label: "All",      dot: "var(--text3)" },
  ];
  const totalByCol = {};
  COLS.forEach(c => { totalByCol[c.id] = visibleCards.filter(card => card.col === c.id).length; });

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>

      {/* ── Header ── */}
      <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)", background: "var(--bg2)",
        flexShrink: 0, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>

        {/* Dev project tabs */}
        <div style={{ display: "flex", gap: 4 }}>
          {projectTabs.map(tab => (
            <button key={tab.id} onClick={() => { setActiveBoard(null); setProject(tab.id); }}
              style={{ fontSize: 12, padding: "4px 11px", height: "auto", minHeight: "unset",
                display: "flex", alignItems: "center", gap: 5,
                background: !activeBoard && project === tab.id ? "var(--bg4)" : "none",
                border: !activeBoard && project === tab.id ? "1px solid var(--border2)" : "1px solid transparent",
                color: !activeBoard && project === tab.id ? "var(--text)" : "var(--text3)",
                fontWeight: !activeBoard && project === tab.id ? 500 : 400, transition: "all 0.12s" }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: tab.dot, flexShrink: 0 }} />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Divider */}
        {boards.length > 0 && (
          <span style={{ width: 1, height: 16, background: "var(--border)", flexShrink: 0, margin: "0 2px" }} />
        )}

        {/* Personal board tabs */}
        {boards.map(board => (
          <div key={board.id} style={{ display: "flex", alignItems: "center", gap: 1 }}>
            <button onClick={() => setActiveBoard(board)}
              style={{ fontSize: 12, padding: "4px 10px", height: "auto", minHeight: "unset",
                display: "flex", alignItems: "center", gap: 5,
                background: activeBoard?.id === board.id ? "var(--bg4)" : "none",
                border: activeBoard?.id === board.id ? "1px solid var(--border2)" : "1px solid transparent",
                color: activeBoard?.id === board.id ? "var(--text)" : "var(--text3)",
                fontWeight: activeBoard?.id === board.id ? 500 : 400, transition: "all 0.12s",
                borderRadius: "var(--radius-md) 0 0 var(--radius-md)" }}>
              {board.name}
            </button>
            {activeBoard?.id === board.id && (
              <div style={{ display: "flex" }}>
                <button onClick={() => setRenamingBoard(board)}
                  title="Rename"
                  style={{ fontSize: 11, padding: "4px 5px", height: "auto", minHeight: "unset",
                    background: "var(--bg4)", border: "1px solid var(--border2)", borderLeft: "none",
                    color: "var(--text3)", borderRadius: 0 }}>✎</button>
                <button onClick={() => handleDeleteBoard(board)}
                  title="Delete board"
                  style={{ fontSize: 11, padding: "4px 5px", height: "auto", minHeight: "unset",
                    background: "var(--bg4)", border: "1px solid var(--border2)", borderLeft: "none",
                    color: "var(--text3)", borderRadius: "0 var(--radius-md) var(--radius-md) 0" }}
                  onMouseEnter={e => e.currentTarget.style.color = "var(--red)"}
                  onMouseLeave={e => e.currentTarget.style.color = "var(--text3)"}>×</button>
              </div>
            )}
          </div>
        ))}

        {/* New board button */}
        <button onClick={() => setBoardModal({ board: null })}
          title="New board"
          style={{ fontSize: 11, padding: "4px 8px", height: "auto", minHeight: "unset",
            background: "none", border: "1px dashed var(--border2)", color: "var(--text3)",
            display: "flex", alignItems: "center", gap: 4 }}>
          + board
        </button>

        <div style={{ flex: 1 }} />

        {/* Stats (project view only) */}
        {!activeBoard && (
          <div style={{ display: "flex", gap: 6 }}>
            {COLS.map(c => (
              <span key={c.id} style={{ fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace",
                display: "flex", alignItems: "center", gap: 3 }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: c.accent }} />
                {totalByCol[c.id]}
              </span>
            ))}
          </div>
        )}

        {/* Refresh (project view only) */}
        {!activeBoard && (
          <button onClick={loadCards} disabled={loading}
            style={{ fontSize: 11, padding: "4px 10px", height: "auto", minHeight: "unset",
              background: "none", border: "1px solid var(--border)", color: "var(--text3)",
              opacity: loading ? 0.5 : 1 }}>↺</button>
        )}

        {/* Add card (project view only) */}
        {!activeBoard && (
          <button className="primary" onClick={() => setModal({ card: null })}
            style={{ fontSize: 12, padding: "5px 14px", height: "auto", minHeight: "unset" }}>
            + Add card
          </button>
        )}
      </div>

      {/* ── Project board ── */}
      {!activeBoard && (
        <div style={{ flex: 1, overflowY: "auto", padding: "14px 16px" }}>
          {loading && cards.length === 0 && <Spinner />}
          {error && <div style={{ padding: 20, color: "var(--red)", fontSize: 13 }}>{error}</div>}
          {!loading && !error && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10, alignItems: "start" }}>
              {COLS.map(col => (
                <KanbanColumn key={col.id} col={col}
                  cards={visibleCards.filter(c => c.col === col.id)}
                  onEdit={(card) => setModal({ card })}
                  onDelete={handleDelete}
                  onDrop={handleDrop}
                  showProject={project === "all"} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Personal board ── */}
      {activeBoard && <BoardView key={activeBoard.id} board={activeBoard} />}

      {/* ── Modals ── */}
      {modal && (
        <CardModal card={modal.card} defaultProject={project === "all" ? "casebase" : project}
          onSave={handleSave} onClose={() => setModal(null)} />
      )}
      {boardModal && (
        <BoardNameModal board={null} onSave={handleCreateBoard} onClose={() => setBoardModal(null)} />
      )}
      {renamingBoard && (
        <BoardNameModal board={renamingBoard} onSave={handleRenameBoard} onClose={() => setRenamingBoard(null)} />
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

export default KanbanView;
