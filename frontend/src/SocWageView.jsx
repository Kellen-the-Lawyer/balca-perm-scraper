import { useEffect, useRef, useState } from "react";
import { API } from "./apiBase";

// ── SOC & Wage Level — merge prototype v2 ────────────────────────────────────
// No modes. One pipeline: 1 Occupation → 2 Requirements → 3 Wage.
// The occupation box takes a SOC code OR title words (live typeahead against
// /wage-level/occupations); "match from the job description" is an expandable
// assist under it, not a separate tool. Requirements auto-recompute the
// worksheet as you type (no submit button — /wage-level/determine is local and
// cheap). The wage renders as a climbable level ladder: the worksheet's level
// carries a flag, any step is clickable, and the readout follows your click.

const STATES = ["","AK","AL","AR","AZ","CA","CO","CT","DC","DE","FL","GA","GU","HI","IA",
  "ID","IL","IN","KS","KY","LA","MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE",
  "NH","NJ","NM","NV","NY","OH","OK","OR","PA","PR","RI","SC","SD","TN","TX","UT","VA",
  "VI","VT","WA","WI","WV","WY"];

const DEGREES = [
  ["none", "No degree"],
  ["high_school", "High school / GED"],
  ["associates", "Associate's"],
  ["bachelors", "Bachelor's"],
  ["masters", "Master's"],
  ["doctorate", "Doctorate"],
  ["professional", "First professional"],
];

const LEVEL_STYLE = {
  1: { bg: "#E6F1FB", border: "#B5D4F4", color: "#0C447C" },
  2: { bg: "#EAF3DE", border: "#C0DD97", color: "#27500A" },
  3: { bg: "#FAEEDA", border: "#FAC775", color: "#633806" },
  4: { bg: "#FCEBEB", border: "#F7C1C1", color: "#791F1F" },
};
const ROMAN = ["I", "II", "III", "IV"];
const LKEYS = ["i", "ii", "iii", "iv"];

const VERDICT_STYLE = {
  strong:   { bg: "#EAF3DE", border: "#C0DD97", color: "#27500A", label: "Strong" },
  moderate: { bg: "#FAEEDA", border: "#FAC775", color: "#633806", label: "Moderate" },
  weak:     { bg: "var(--bg3)", border: "var(--border)", color: "var(--text3)", label: "Weak" },
};

const fmtA = n => "$" + Math.round(n).toLocaleString();
const lbl = { display: "block", fontSize: 11, color: "var(--text3)", marginBottom: 4 };
const panel = { background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 12, padding: 20 };
const chip = (bg, border, color) => ({ display: "inline-block", fontSize: 11, padding: "2px 8px",
  borderRadius: 999, background: bg, border: `1px solid ${border}`, color, marginRight: 6, marginBottom: 4 });

function StageLabel({ n, title, sub }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 12 }}>
      <span style={{ width: 22, height: 22, borderRadius: "50%", background: "var(--amber-dim)",
        color: "var(--amber)", fontSize: 12, fontWeight: 700, display: "inline-flex",
        alignItems: "center", justifyContent: "center", flexShrink: 0, transform: "translateY(3px)" }}>{n}</span>
      <span style={{ fontSize: 15, fontWeight: 700 }}>{title}</span>
      {sub && <span style={{ fontSize: 12, color: "var(--text3)" }}>{sub}</span>}
    </div>
  );
}

export function SocWageView() {
  // ── Stage 1: occupation ──
  const [socQuery, setSocQuery] = useState("");
  const [matches, setMatches] = useState([]);           // typeahead results
  const [showMatches, setShowMatches] = useState(false);
  const [occ, setOcc] = useState(null);                 // selected occupation detail
  const [occErr, setOccErr] = useState(null);
  const [matcherOpen, setMatcherOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [jd, setJd] = useState("");
  const [reqs, setReqs] = useState("");
  const [sugBusy, setSugBusy] = useState(false);
  const [sugRes, setSugRes] = useState(null);
  const [sugErr, setSugErr] = useState(null);
  const [openRat, setOpenRat] = useState(null);         // which suggestion's details are open

  // ── Stage 2: requirements ──
  const [degree, setDegree] = useState("bachelors");
  const [years, setYears] = useState("");
  const [skills, setSkills] = useState(0);
  const [lang, setLang] = useState(false);
  const [sup, setSup] = useState(false);

  // ── Stage 3: wage ──
  const [state, setState] = useState("");
  const [county, setCounty] = useState("");
  const [counties, setCounties] = useState([]);
  const [det, setDet] = useState(null);
  const [detErr, setDetErr] = useState(null);
  const [computing, setComputing] = useState(false);
  const [levelView, setLevelView] = useState(null);

  const debounceRef = useRef(null);
  const searchRef = useRef(null);
  const runSeq = useRef(0);
  const boxRef = useRef(null);

  // ── Typeahead: SOC code prefix or title words ──
  // Pasting a whole job description here (long / multiline) flips straight
  // into the matcher with the text carried over — the box takes anything.
  const onQueryChange = (v) => {
    if (v.length > 90 || v.includes("\n")) {
      setJd(v.trim()); setSocQuery(""); setMatches([]); setShowMatches(false);
      setMatcherOpen(true);
      return;
    }
    setSocQuery(v);
    clearTimeout(searchRef.current);
    if (v.trim().length < 2) { setMatches([]); setShowMatches(false); return; }
    searchRef.current = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/wage-level/occupations?q=${encodeURIComponent(v.trim())}`);
        if (r.ok) { const rows = await r.json(); setMatches(rows); setShowMatches(rows.length > 0); }
      } catch { /* typeahead is best-effort */ }
    }, 250);
  };

  // Close the typeahead on outside click
  useEffect(() => {
    const h = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setShowMatches(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const selectOcc = async (soc_code, soc_title) => {
    setSocQuery(`${soc_code} — ${soc_title ?? ""}`.trim());
    setShowMatches(false); setOccErr(null);
    try {
      const r = await fetch(`${API}/wage-level/occupation/${encodeURIComponent(soc_code)}`);
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      setOcc(await r.json());
    } catch (e) { setOcc({ soc_code, soc_title }); setOccErr(String(e.message || e)); }
  };

  // ── Job-description matcher (LLM — explicit button, never automatic) ──
  const suggest = async () => {
    setSugBusy(true); setSugErr(null); setSugRes(null);
    try {
      const r = await fetch(`${API}/soc-suggest`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_title: title.trim(), job_description: jd.trim(),
          min_requirements: reqs.trim(),
          state_ab: state || null, county_name: county.trim() || null,
        }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      const data = await r.json();
      setSugRes(data);
      const pr = data.parsed_requirements;
      if (pr) {
        setDegree(pr.degree_required || "bachelors");
        setYears(pr.months_experience ? String(Math.round((pr.months_experience / 12) * 10) / 10) : "0");
        setSkills(pr.special_skills_points || 0);
        setLang(!!pr.foreign_language_required);
        setSup(!!pr.supervisory_duties);
      }
      const top = data.suggestions?.[0];
      if (top) selectOcc(top.soc_code, top.title);
    } catch (e) { setSugErr(String(e.message || e)); }
    finally { setSugBusy(false); }
  };

  const onStateChange = async (st) => {
    setState(st); setCounty(""); setCounties([]);
    if (!st) return;
    try {
      const r = await fetch(`${API}/wage-level/counties/${st}`);
      if (r.ok) setCounties(await r.json());
    } catch { /* dropdown stays empty; determine still works state-wide */ }
  };

  // ── Live worksheet: recompute whenever occupation or inputs change ──
  useEffect(() => {
    if (!occ?.soc_code) return;
    clearTimeout(debounceRef.current);
    const seq = ++runSeq.current;
    setComputing(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/wage-level/determine`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            soc_code: occ.soc_code,
            degree_required: degree,
            years_experience_required: years === "" ? 0 : Number(years),
            special_skills_points: Number(skills),
            foreign_language_required: lang,
            supervisory_duties: sup,
            state_ab: state || null,
            county_name: county.trim() || null,
          }),
        });
        if (seq !== runSeq.current) return;               // stale response
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        setDet(await r.json()); setDetErr(null); setLevelView(null);
      } catch (e) {
        if (seq === runSeq.current) { setDetErr(String(e.message || e)); }
      } finally {
        if (seq === runSeq.current) setComputing(false);
      }
    }, 400);
    return () => clearTimeout(debounceRef.current);
  }, [occ?.soc_code, degree, years, skills, lang, sup, state, county]);

  const viewLevel = levelView ?? det?.wage_level ?? null;
  const overridden = det && levelView != null && levelView !== det.wage_level;
  const viewHourly = det?.wage?.levels_hourly ? det.wage.levels_hourly[LKEYS[viewLevel - 1]] : null;
  const vls = viewLevel ? LEVEL_STYLE[viewLevel] : null;

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <div style={{ maxWidth: 880, margin: "0 auto", padding: "28px 24px 64px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <h1 style={{ fontSize: 20, margin: 0 }}>SOC &amp; Wage Level</h1>
        </div>
        <div style={{ fontSize: 13, color: "var(--text3)", margin: "6px 0 24px", maxWidth: 700 }}>
          The SOC Suggester and Wage Level Tool, combined. Pick the occupation, set the
          requirements, read the wage — the worksheet recomputes live as you change
          anything. An aid, not the determination.
        </div>

        {/* ══ 1 · Occupation ══ */}
        <div style={{ ...panel, marginBottom: 16 }}>
          <StageLabel n={1} title="Occupation"
            sub="type a SOC code or job title — or paste the whole job description" />

          <div style={{ display: "flex", gap: 10, alignItems: "stretch", flexWrap: "wrap" }}>
            <div ref={boxRef} style={{ position: "relative", flex: "1 1 320px" }}>
              <input value={socQuery} onChange={e => onQueryChange(e.target.value)}
                     onFocus={() => matches.length > 0 && setShowMatches(true)}
                     placeholder='Try "15-1252", "software" — or paste a job description'
                     style={{ width: "100%", fontSize: 15, padding: "12px 14px", height: "auto" }} />
            {showMatches && (
              <div style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 30,
                            background: "var(--bg2)", border: "1px solid var(--border)",
                            borderRadius: 10, marginTop: 4, overflow: "hidden",
                            boxShadow: "0 10px 30px rgba(0,0,0,.25)" }}>
                {matches.map(m => (
                  <div key={m.soc_code} onClick={() => selectOcc(m.soc_code, m.soc_title)}
                       style={{ padding: "9px 14px", cursor: "pointer", display: "flex", gap: 10,
                                borderBottom: "1px solid var(--border)", fontSize: 13 }}
                       onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                       onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                    <span style={{ fontFamily: "'DM Mono', monospace", color: "var(--amber)" }}>{m.soc_code}</span>
                    <span>{m.soc_title}</span>
                  </div>
                ))}
              </div>
            )}
            </div>

            {/* First-class second entry: the JD matcher */}
            <button onClick={() => setMatcherOpen(o => !o)}
              style={{ flex: "0 0 auto", padding: "0 18px", borderRadius: 8, fontSize: 13,
                fontWeight: 600, cursor: "pointer",
                background: matcherOpen ? "var(--amber-dim)" : "var(--bg3)",
                color: matcherOpen ? "var(--amber)" : "var(--text2)",
                border: matcherOpen ? "1px solid #315f7c44" : "1px solid var(--border)" }}>
              {matcherOpen ? "▾ " : ""}Match from job description
            </button>
          </div>

          {occ && (
            <div style={{ marginTop: 12, padding: "10px 14px", background: "var(--bg3)",
                          border: "1px solid var(--border)", borderRadius: 8, fontSize: 13,
                          display: "flex", gap: 14, flexWrap: "wrap", alignItems: "baseline" }}>
              <b>{occ.soc_title || occ.soc_code}</b>
              <span style={{ fontFamily: "'DM Mono', monospace", color: "var(--text3)" }}>{occ.soc_code}</span>
              {occ.job_zone
                ? <span>Job Zone {occ.job_zone}
                    <span style={{ color: "var(--text3)" }}> · SVP {occ.zone_reference?.svp_range}</span></span>
                : <span style={{ color: "var(--red)" }}>no Job Zone found</span>}
              <span style={{ color: "var(--text3)", fontSize: 12 }}>
                {occ.is_professional_occupation
                  ? `Appendix D professional — usual: ${occ.appendix_d_category_label}`
                  : "Not on Appendix D — usual education from the Job Zone"}
              </span>
            </div>
          )}
          {occErr && <div style={{ fontSize: 12, color: "var(--red)", marginTop: 8 }}>{occErr}</div>}

          {matcherOpen && (
            <div style={{ marginTop: 12, paddingTop: 14, borderTop: "1px dashed var(--border)" }}>
              <div style={{ marginBottom: 12 }}>
                <label style={lbl}>Job title</label>
                <input value={title} onChange={e => setTitle(e.target.value)}
                       placeholder="e.g. Senior Software Engineer (optional)"
                       style={{ width: "100%", maxWidth: 420 }} />
              </div>
              <div className="m-stack" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <label style={lbl}>Job description / duties</label>
                  <textarea value={jd} onChange={e => setJd(e.target.value)} rows={6}
                            placeholder="Paste the duties section…"
                            style={{ width: "100%", resize: "vertical", fontFamily: "inherit", fontSize: 13 }} />
                </div>
                <div>
                  <label style={lbl}>Minimum requirements</label>
                  <textarea value={reqs} onChange={e => setReqs(e.target.value)} rows={6}
                            placeholder="Degree, years of experience, skills, licenses…"
                            style={{ width: "100%", resize: "vertical", fontFamily: "inherit", fontSize: 13 }} />
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10 }}>
                <button onClick={suggest} disabled={sugBusy || !jd.trim()}
                        style={{ padding: "7px 18px", borderRadius: 7, background: "var(--amber)",
                                 color: "#1a1206", fontWeight: 600, border: "none", cursor: "pointer",
                                 opacity: sugBusy ? 0.6 : 1 }}>
                  {sugBusy ? "Analyzing…" : "Rank SOC matches"}
                </button>
                <span style={{ fontSize: 11.5, color: "var(--text3)" }}>
                  Also parses the requirements into stage 2 — verify before relying on it.</span>
              </div>
              {sugErr && <div style={{ fontSize: 12, color: "var(--red)", marginTop: 8 }}>{sugErr}</div>}

              {sugRes?.flags?.map((f, i) => (
                <div key={i} style={{ marginTop: 10, padding: "8px 12px", borderRadius: 8,
                      background: "#FCEBEB", border: "1px solid #F7C1C1", color: "#791F1F",
                      fontSize: 12.5 }}><b>Flag:</b> {f}</div>
              ))}
              {sugRes?.llm_error && (
                <div style={{ marginTop: 10, padding: "8px 12px", borderRadius: 8,
                      background: "#FAEEDA", border: "1px solid #FAC775", color: "#633806",
                      fontSize: 12.5 }}>
                  AI re-rank unavailable ({sugRes.llm_error}) — retrieval order, no rationales,
                  stage 2 not seeded.</div>
              )}

              {sugRes?.suggestions?.map((s, i) => {
                const v = VERDICT_STYLE[s.verdict] || null;
                const selected = occ?.soc_code === s.soc_code;
                const open = openRat === s.onetsoc_code;
                return (
                  <div key={s.onetsoc_code}
                    style={{ marginTop: 8, borderRadius: 10, border: selected
                        ? "2px solid var(--amber)" : "1px solid var(--border)",
                      background: "var(--bg)", overflow: "hidden" }}>
                    <div onClick={() => selectOcc(s.soc_code, s.title)}
                      style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px",
                               cursor: "pointer", flexWrap: "wrap" }}>
                      <span style={{ fontSize: 11, color: "var(--text3)", width: 18 }}>#{i + 1}</span>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontWeight: 700 }}>{s.soc_code}</span>
                      <span style={{ fontSize: 13.5 }}>{s.title}</span>
                      {v && <span style={{ ...chip(v.bg, v.border, v.color), marginBottom: 0 }}>{v.label}</span>}
                      {selected && <span style={{ ...chip("var(--amber-dim)", "#315f7c44", "var(--amber)"),
                        marginBottom: 0 }}>Selected ✓</span>}
                      <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text3)",
                                     fontFamily: "'DM Mono', monospace" }}>
                        {s.job_zone ? `Zone ${s.job_zone}` : ""}
                        {s.similarity != null ? ` · sim ${s.similarity.toFixed(3)}` : ""}</span>
                      {(s.rationale || s.duties_matched?.length > 0) && (
                        <button onClick={(e) => { e.stopPropagation();
                                  setOpenRat(open ? null : s.onetsoc_code); }}
                          style={{ background: "none", border: "none", padding: "0 2px", height: "auto",
                                   minHeight: "unset", fontSize: 11.5, color: "var(--text3)", cursor: "pointer" }}>
                          {open ? "hide ▴" : "why ▾"}
                        </button>
                      )}
                    </div>
                    {open && (
                      <div style={{ padding: "0 12px 12px 40px", fontSize: 12.5, lineHeight: 1.6 }}>
                        {s.rationale}
                        {s.duties_matched?.length > 0 && (
                          <div style={{ marginTop: 6 }}>
                            {s.duties_matched.map((d, j) =>
                              <span key={j} style={chip("#EAF3DE", "#C0DD97", "#27500A")}>{d}</span>)}
                          </div>
                        )}
                        {s.duties_not_covered?.length > 0 && (
                          <div style={{ marginTop: 2 }}>
                            {s.duties_not_covered.map((d, j) =>
                              <span key={j} style={chip("#FCEBEB", "#F7C1C1", "#791F1F")}>{d}</span>)}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ══ 2 · Requirements ══ */}
        <div style={{ ...panel, marginBottom: 16, opacity: occ ? 1 : 0.5 }}>
          <StageLabel n={2} title="Requirements of the job offer"
            sub={sugRes ? "seeded from the parsed requirements — edit freely" : "the worksheet recomputes as you change these"} />
          <div className="m-stack" style={{ display: "grid",
                gridTemplateColumns: "1.3fr 1fr 1.3fr", gap: 14 }}>
            <div>
              <label style={lbl}>Degree required</label>
              <select value={degree} onChange={e => setDegree(e.target.value)} style={{ width: "100%" }}>
                {DEGREES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label style={lbl}>Years of experience</label>
              <input type="number" min="0" step="0.5" value={years}
                     onChange={e => setYears(e.target.value)} placeholder="0" style={{ width: "100%" }} />
            </div>
            <div>
              <label style={lbl}>Special skills beyond entry (Step 4 — your judgment)</label>
              <select value={skills} onChange={e => setSkills(e.target.value)} style={{ width: "100%" }}>
                <option value={0}>None</option>
                <option value={1}>Yes — 1 point</option>
                <option value={2}>Yes, substantial — 2 points</option>
              </select>
            </div>
          </div>
          <div style={{ display: "flex", gap: 22, marginTop: 12, fontSize: 13, flexWrap: "wrap" }}>
            <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
              <input type="checkbox" style={{ width: "auto" }} checked={lang} onChange={e => setLang(e.target.checked)} />
              Foreign language required
            </label>
            <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
              <input type="checkbox" style={{ width: "auto" }} checked={sup} onChange={e => setSup(e.target.checked)} />
              Supervisory duties
            </label>
          </div>
        </div>

        {/* ══ 3 · Wage ══ */}
        <div style={{ ...panel, opacity: occ ? 1 : 0.5 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
            <StageLabel n={3} title="Wage" />
            <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
              <label style={{ ...lbl, marginBottom: 0 }}>Worksite</label>
              <select value={state} onChange={e => onStateChange(e.target.value)} style={{ width: 70 }}>
                {STATES.map(s => <option key={s} value={s}>{s || "—"}</option>)}
              </select>
              <select value={county} onChange={e => setCounty(e.target.value)}
                      disabled={!state || counties.length === 0} style={{ maxWidth: 250 }}>
                <option value="">
                  {!state ? "Select state" : counties.length === 0 ? "Loading…" : "All of " + state}
                </option>
                {counties.map(c => (
                  <option key={c.county_name} value={c.county_name}>
                    {c.county_name} — {c.area_name}</option>
                ))}
              </select>
            </div>
          </div>

          {!occ && (
            <div style={{ fontSize: 13, color: "var(--text3)", lineHeight: 1.7 }}>
              Choose an occupation above — the level ladder and worksheet appear here and
              stay live as you change the requirements.
            </div>
          )}
          {detErr && <div style={{ fontSize: 12, color: "var(--red)" }}>{detErr}</div>}

          {det && (
            <>
              {/* Readout */}
              <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap",
                            minHeight: 44, opacity: computing ? 0.45 : 1, transition: "opacity .2s" }}>
                <span style={{ fontSize: 30, fontWeight: 700, color: vls?.color }}>
                  Level {ROMAN[viewLevel - 1]}
                </span>
                {viewHourly != null && (
                  <span style={{ fontSize: 24, fontWeight: 700 }}>
                    {fmtA(viewHourly * 2080)}<span style={{ fontSize: 13, fontWeight: 400 }}>/yr</span>
                    <span style={{ fontSize: 13, fontWeight: 400, color: "var(--text3)" }}>
                      {" "}· ${viewHourly.toFixed(2)}/hr · {det.wage.area_name}</span>
                  </span>
                )}
                {det.wage == null && (state || county) && (
                  <span style={{ fontSize: 12.5, color: "var(--text3)" }}>
                    No wage row matched that area for {det.soc_code}.</span>
                )}
                {det.wage == null && !state && !county && (
                  <span style={{ fontSize: 12.5, color: "var(--text3)" }}>
                    Pick a worksite (top right) to light up the level ladder with dollars.</span>
                )}
              </div>
              <div style={{ fontSize: 12.5, marginTop: 2, minHeight: 18,
                            color: overridden ? vls?.color : "var(--text3)" }}>
                {overridden
                  ? <>Your selection — the worksheet computed <b>{det.wage_level_label}</b> ({det.total_points} pts). Click its rung to return.</>
                  : <>{det.total_points} point{det.total_points === 1 ? "" : "s"} on the NPWHC worksheet
                      {det.total_points > 4 && " (capped at IV)"}
                      {det.wage_level < 4 && Number(skills) === 0 &&
                        " · treat as a floor — with no Step-4 points, DOL lands one level higher in ~16% of comparable cases"}</>}
              </div>

              {/* The ladder */}
              {det.wage?.levels_hourly && (
                <div style={{ display: "flex", alignItems: "flex-end", gap: 10, marginTop: 18 }}>
                  {LKEYS.map((k, i) => {
                    const st = LEVEL_STYLE[i + 1];
                    const h = det.wage.levels_hourly[k];
                    const computed = i + 1 === det.wage_level;
                    const viewing = i + 1 === viewLevel;
                    const hMax = det.wage.levels_hourly.iv || h;
                    const barH = 58 + Math.round((h / hMax) * 66);
                    return (
                      <div key={k} onClick={() => setLevelView(i + 1)}
                        style={{ flex: 1, cursor: "pointer" }}>
                        <div style={{ textAlign: "center", fontSize: 11, marginBottom: 4, height: 16,
                                      color: st.color, fontWeight: 700 }}>
                          {computed && "▼ worksheet"}
                        </div>
                        <div style={{ height: barH, borderRadius: "10px 10px 0 0",
                              background: st.bg,
                              border: `2px solid ${viewing ? st.color : st.border}`,
                              borderBottomWidth: viewing ? 4 : 2,
                              opacity: viewing ? 1 : 0.55,
                              transition: "opacity .15s, border-color .15s, height .3s",
                              display: "flex", flexDirection: "column", justifyContent: "flex-end",
                              padding: "8px 10px" }}>
                          <div style={{ fontSize: 11, fontWeight: 700, color: st.color }}>
                            LEVEL {ROMAN[i]}</div>
                          <div style={{ fontSize: 15, fontWeight: 700, color: st.color }}>
                            {fmtA(h * 2080)}</div>
                          <div style={{ fontSize: 10.5, color: st.color, opacity: 0.8 }}>
                            ${h.toFixed(2)}/hr</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Worksheet detail + SVP — the audit trail */}
              <details open style={{ marginTop: 18 }}>
                <summary style={{ fontSize: 12.5, fontWeight: 600, cursor: "pointer",
                                  color: "var(--text2)" }}>
                  Worksheet detail — every point with its rationale
                </summary>
                <div style={{ marginTop: 10, border: "1px solid var(--border)", borderRadius: 8,
                              overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 480 }}>
                    <thead>
                      <tr style={{ background: "var(--bg3)", textAlign: "left" }}>
                        <th style={{ padding: "8px 14px", width: 44 }}>Step</th>
                        <th style={{ padding: "8px 6px", width: 200 }}>Item</th>
                        <th style={{ padding: "8px 6px", width: 44 }}>Pts</th>
                        <th style={{ padding: "8px 14px 8px 6px" }}>Rationale</th>
                      </tr>
                    </thead>
                    <tbody>
                      {det.worksheet.map(w => (
                        <tr key={w.step} style={{ borderTop: "1px solid var(--border)" }}>
                          <td style={{ padding: "9px 14px", color: "var(--text3)" }}>{w.step}</td>
                          <td style={{ padding: "9px 6px" }}>{w.label}</td>
                          <td style={{ padding: "9px 6px", fontWeight: 700,
                                       color: w.points ? "var(--amber)" : "var(--text3)" }}>
                            {w.points ? `+${w.points}` : "0"}</td>
                          <td style={{ padding: "9px 14px 9px 6px", color: "var(--text2)", lineHeight: 1.5 }}>
                            {w.rationale}
                            {w.usual_source && (
                              <div style={{ fontSize: 11, color: "var(--text3)" }}>{w.usual_source}</div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>

              {det.svp_analysis && (
                <details style={{ marginTop: 10 }}>
                  <summary style={{ fontSize: 12.5, fontWeight: 600, cursor: "pointer",
                                    color: det.svp_analysis.exceeds_zone_svp ? "var(--red)" : "var(--text2)" }}>
                    SVP-equivalency analysis —{" "}
                    {det.svp_analysis.exceeds_zone_svp ? "EXCEEDS SVP range" : "within SVP range"}
                    {" "}(informational, not scored)
                  </summary>
                  <div style={{ marginTop: 8, display: "flex", gap: 18, flexWrap: "wrap", fontSize: 13 }}>
                    <div>Experience: <b>{det.svp_analysis.experience_months} mo</b></div>
                    <div>+ Education SVP-equiv: <b>{det.svp_analysis.education_svp_equivalent_months} mo</b></div>
                    <div>= Combined: <b>{det.svp_analysis.combined_svp_months} mo
                      {" "}({det.svp_analysis.combined_svp_years} yr)</b></div>
                    <div>Zone {det.job_zone} SVP ceiling:{" "}
                      <b>{det.svp_analysis.zone_svp_ceiling_months ?? "—"} mo</b></div>
                  </div>
                  {det.svp_analysis.notes?.length > 0 && (
                    <div style={{ fontSize: 11.5, color: "var(--text3)", marginTop: 8, lineHeight: 1.6 }}>
                      {det.svp_analysis.notes.map((n, i) => <div key={i}>• {n}</div>)}
                    </div>
                  )}
                </details>
              )}

              <div style={{ fontSize: 11.5, color: "var(--text3)", lineHeight: 1.6, marginTop: 14 }}>
                {det.caveats?.map((c, i) => <div key={i}>• {c}</div>)}
                {det.guidance && <div>• Source: {det.guidance}, Appendices A–E; O*NET Job Zones; 20 CFR 656.40.</div>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
