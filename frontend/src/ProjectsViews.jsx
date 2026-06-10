import { useState, useEffect } from "react";
import { API } from "./apiBase";
import { Badge, PROJECT_COLORS, Spinner } from "./common";

export function ProjectsView({ onOpenDecision }) {
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

export function ProjectDetail({ projectId, onBack, onOpenDecision }) {
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
