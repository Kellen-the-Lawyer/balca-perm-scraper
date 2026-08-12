import { useState } from "react";
import { API } from "./apiBase";

const STATES = ["","AK","AL","AR","AZ","CA","CO","CT","DC","DE","FL","GA","GU","HI","IA",
  "ID","IL","IN","KS","KY","LA","MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE",
  "NH","NJ","NM","NV","NY","OH","OK","OR","PA","PR","RI","SC","SD","TN","TX","UT","VA",
  "VI","VT","WA","WI","WV","WY"];

const LEVEL_STYLE = {
  1: { bg: "#E6F1FB", border: "#B5D4F4", color: "#0C447C" },
  2: { bg: "#EAF3DE", border: "#C0DD97", color: "#27500A" },
  3: { bg: "#FAEEDA", border: "#FAC775", color: "#633806" },
  4: { bg: "#FCEBEB", border: "#F7C1C1", color: "#791F1F" },
};

const VERDICT_STYLE = {
  strong:   { bg: "#EAF3DE", border: "#C0DD97", color: "#27500A", label: "Strong match" },
  moderate: { bg: "#FAEEDA", border: "#FAC775", color: "#633806", label: "Moderate match" },
  weak:     { bg: "var(--bg3)", border: "var(--border)", color: "var(--text3)", label: "Weak match" },
};

const fmtA = n => "$" + Math.round(n).toLocaleString();
const label = { display: "block", fontSize: 12, color: "var(--text3)", marginBottom: 4, marginTop: 14 };
const panel = { background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 10, padding: 20 };
const chip = (bg, border, color) => ({ display: "inline-block", fontSize: 11, padding: "2px 8px",
  borderRadius: 999, background: bg, border: `1px solid ${border}`, color, marginRight: 6, marginBottom: 4 });

const DEGREE_LABELS = { none: "No degree", high_school: "High school / GED",
  associates: "Associate's", bachelors: "Bachelor's", masters: "Master's",
  doctorate: "Doctorate", professional: "First professional" };

export function SocSuggestView() {
  const [title, setTitle] = useState("");
  const [jd, setJd] = useState("");
  const [reqs, setReqs] = useState("");
  const [state, setState] = useState("");
  const [county, setCounty] = useState("");
  const [counties, setCounties] = useState([]);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);

  const onStateChange = async (st) => {
    setState(st); setCounty(""); setCounties([]);
    if (!st) return;
    try {
      const r = await fetch(`${API}/wage-level/counties/${st}`);
      if (r.ok) setCounties(await r.json());
    } catch { /* dropdown stays empty; suggest still works state-wide */ }
  };

  const suggest = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      const body = {
        job_title: title.trim(),
        job_description: jd.trim(),
        min_requirements: reqs.trim(),
        state_ab: state || null,
        county_name: county.trim() || null,
      };
      const r = await fetch(`${API}/soc-suggest`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      setRes(await r.json());
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };

  const w = res?.wage_determination;
  const ls = w ? LEVEL_STYLE[w.wage_level] : null;
  const pr = res?.parsed_requirements;

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "28px 24px 64px" }}>
        <h1 style={{ fontSize: 20, marginBottom: 4 }}>SOC Code &amp; Wage Level Suggester</h1>
        <div style={{ fontSize: 13, color: "var(--text3)", marginBottom: 24 }}>
          Paste the job description and minimum requirements. The tool matches against all
          1,016 O*NET-SOC occupations, ranks the candidates with a rationale for each, and
          runs the NPWHC wage-level worksheet on the top match. Every step is shown so it
          can be audited or overridden — this is an aid, not the determination.
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "400px 1fr", gap: 20, alignItems: "start" }}>
          {/* ── Inputs ── */}
          <div style={panel}>
            <label style={{ ...label, marginTop: 0 }}>Job title</label>
            <input value={title} onChange={e => setTitle(e.target.value)}
                   placeholder="e.g. Software Engineer" style={{ width: "100%" }} />

            <label style={label}>Job description / duties</label>
            <textarea value={jd} onChange={e => setJd(e.target.value)} rows={10}
                      placeholder="Paste the duties section of the job description…"
                      style={{ width: "100%", resize: "vertical", fontFamily: "inherit", fontSize: 13 }} />

            <label style={label}>Minimum requirements</label>
            <textarea value={reqs} onChange={e => setReqs(e.target.value)} rows={5}
                      placeholder="Degree, years/months of experience, specific skills, licenses…"
                      style={{ width: "100%", resize: "vertical", fontFamily: "inherit", fontSize: 13 }} />

            <div style={{ borderTop: "1px solid var(--border)", marginTop: 16, paddingTop: 4 }}>
              <label style={label}>Wage lookup (optional) — worksite state / county</label>
              <div style={{ display: "flex", gap: 8 }}>
                <select value={state} onChange={e => onStateChange(e.target.value)} style={{ width: 90 }}>
                  {STATES.map(s => <option key={s} value={s}>{s || "—"}</option>)}
                </select>
                <select value={county} onChange={e => setCounty(e.target.value)}
                        disabled={!state || counties.length === 0} style={{ flex: 1 }}>
                  <option value="">
                    {!state ? "Select a state first"
                            : counties.length === 0 ? "Loading counties…"
                            : "All of " + state + " (statewide match)"}
                  </option>
                  {counties.map(c => (
                    <option key={c.county_name} value={c.county_name}>
                      {c.county_name} — {c.area_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <button onClick={suggest} disabled={busy || !jd.trim()}
                    style={{ marginTop: 18, width: "100%", padding: "9px 0", borderRadius: 7,
                             background: "var(--amber)", color: "#1a1206", fontWeight: 600,
                             border: "none", cursor: "pointer", opacity: busy ? 0.6 : 1 }}>
              {busy ? "Analyzing…" : "Suggest SOC code & wage level"}
            </button>
            {err && <div style={{ fontSize: 12, color: "var(--red)", marginTop: 8 }}>{err}</div>}
          </div>

          {/* ── Results ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {!res && (
              <div style={{ ...panel, color: "var(--text3)", fontSize: 13, lineHeight: 1.7 }}>
                Suggestions appear here ranked best-first, each with the duties it covers,
                the duties it doesn't, and why it does or doesn't fit. The top match feeds
                the wage-level worksheet below it, using the degree and experience parsed
                from the minimum requirements.
              </div>
            )}

            {res && res.flags?.length > 0 && res.flags.map((f, i) => (
              <div key={i} style={{ ...panel, background: "#FCEBEB", border: "1px solid #F7C1C1",
                                    color: "#791F1F", fontSize: 13, lineHeight: 1.6 }}>
                <b>Flag:</b> {f}
              </div>
            ))}

            {res && res.llm_error && (
              <div style={{ ...panel, background: "#FAEEDA", border: "1px solid #FAC775",
                            color: "#633806", fontSize: 13 }}>
                AI re-rank unavailable ({res.llm_error}) — showing retrieval order without
                rationales. Wage worksheet needs the parsed requirements, run again or use
                the Wage Level Tool manually.
              </div>
            )}

            {res && res.suggestions.map((s, i) => {
              const v = VERDICT_STYLE[s.verdict] || null;
              return (
                <div key={s.onetsoc_code} style={{ ...panel, padding: 16,
                        borderLeft: i === 0 ? "3px solid var(--amber)" : undefined }}>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12, color: "var(--text3)" }}>#{i + 1}</span>
                    <span style={{ fontSize: 16, fontWeight: 700 }}>{s.soc_code}</span>
                    <span style={{ fontSize: 15 }}>{s.title}</span>
                    {v && <span style={chip(v.bg, v.border, v.color)}>{v.label}</span>}
                    {s.lexical_title_match &&
                      <span style={chip("var(--bg3)", "var(--border)", "var(--text2)")}>Title match</span>}
                    <span style={{ fontSize: 11, color: "var(--text3)", marginLeft: "auto" }}>
                      {s.job_zone ? `Zone ${s.job_zone}` : ""}
                      {s.similarity != null ? ` · sim ${s.similarity.toFixed(3)}` : ""}
                    </span>
                  </div>
                  {s.rationale && (
                    <div style={{ fontSize: 13, lineHeight: 1.6, marginTop: 8 }}>{s.rationale}</div>
                  )}
                  {s.duties_matched?.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <span style={{ fontSize: 11, color: "var(--text3)", marginRight: 6 }}>Covers:</span>
                      {s.duties_matched.map((d, j) =>
                        <span key={j} style={chip("#EAF3DE", "#C0DD97", "#27500A")}>{d}</span>)}
                    </div>
                  )}
                  {s.duties_not_covered?.length > 0 && (
                    <div style={{ marginTop: 4 }}>
                      <span style={{ fontSize: 11, color: "var(--text3)", marginRight: 6 }}>Outside scope:</span>
                      {s.duties_not_covered.map((d, j) =>
                        <span key={j} style={chip("#FCEBEB", "#F7C1C1", "#791F1F")}>{d}</span>)}
                    </div>
                  )}
                  <div style={{ fontSize: 12, color: "var(--text3)", marginTop: 8, lineHeight: 1.5 }}>
                    {s.description?.slice(0, 220)}{s.description?.length > 220 ? "…" : ""}
                  </div>
                </div>
              );
            })}

            {pr && (
              <div style={panel}>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
                  Parsed minimum requirements
                  <span style={{ fontWeight: 400, color: "var(--text3)" }}> — feeds the worksheet; verify before relying on it</span>
                </div>
                <div style={{ fontSize: 13, lineHeight: 1.8 }}>
                  <b>{DEGREE_LABELS[pr.degree_required] || pr.degree_required}</b>
                  {" · "}{pr.months_experience} months experience
                  {pr.foreign_language_required && " · foreign language required"}
                  {pr.supervisory_duties && " · supervisory duties"}
                  {" · "}Step-4 skills suggestion: {pr.special_skills_points} point(s)
                </div>
                {pr.special_skills?.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    {pr.special_skills.map((sk, j) =>
                      <span key={j} style={chip("var(--bg3)", "var(--border)", "var(--text2)")}>{sk}</span>)}
                  </div>
                )}
              </div>
            )}

            {w && ls && (
              <div style={{ ...panel, background: ls.bg, border: `1px solid ${ls.border}` }}>
                <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
                  <div style={{ fontSize: 26, fontWeight: 700, color: ls.color }}>{w.wage_level_label}</div>
                  <div style={{ fontSize: 13, color: ls.color, opacity: 0.85 }}>
                    {w.soc_code} {w.soc_title} · Job Zone {w.job_zone} · {w.total_points} points
                  </div>
                  {w.wage?.determined_annual != null && (
                    <div style={{ marginLeft: "auto", fontSize: 20, fontWeight: 700, color: ls.color }}>
                      {fmtA(w.wage.determined_annual)}/yr
                      <span style={{ fontSize: 12, fontWeight: 400, opacity: 0.8 }}>
                        {" "}(${w.wage.determined_hourly}/hr · {w.wage.area_name})
                      </span>
                    </div>
                  )}
                </div>
                <div className="m-scroll-x">
                <table style={{ width: "100%", marginTop: 14, fontSize: 13, borderCollapse: "collapse", minWidth: 480 }}>
                  <tbody>
                    {w.worksheet.map(row => (
                      <tr key={row.step} style={{ borderTop: `1px solid ${ls.border}` }}>
                        <td style={{ padding: "7px 8px 7px 0", whiteSpace: "nowrap",
                                     verticalAlign: "top", color: ls.color, fontWeight: 600 }}>
                          Step {row.step} — {row.label}
                        </td>
                        <td style={{ padding: "7px 8px", verticalAlign: "top", textAlign: "center",
                                     color: ls.color, fontWeight: 700 }}>+{row.points}</td>
                        <td style={{ padding: "7px 0", verticalAlign: "top", color: ls.color,
                                     opacity: 0.9, lineHeight: 1.5 }}>{row.rationale}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
                {w.wage?.levels_hourly && (
                  <div style={{ fontSize: 12, color: ls.color, opacity: 0.85, marginTop: 8 }}>
                    All levels (hourly): I ${w.wage.levels_hourly.i} · II ${w.wage.levels_hourly.ii} ·
                    III ${w.wage.levels_hourly.iii} · IV ${w.wage.levels_hourly.iv}
                  </div>
                )}
                <details style={{ marginTop: 10 }}>
                  <summary style={{ fontSize: 12, color: ls.color, cursor: "pointer" }}>
                    Caveats &amp; SVP analysis
                  </summary>
                  <ul style={{ fontSize: 12, color: ls.color, opacity: 0.9, lineHeight: 1.6,
                               margin: "8px 0 0 18px", padding: 0 }}>
                    {w.caveats.map((c, i) => <li key={i}>{c}</li>)}
                    {w.svp_analysis && (
                      <li>Combined SVP: {w.svp_analysis.combined_svp_months} mo
                          ({w.svp_analysis.combined_svp_years} yr) vs zone ceiling{" "}
                          {w.svp_analysis.zone_svp_ceiling_months ?? "—"} mo —{" "}
                          {w.svp_analysis.exceeds_zone_svp ? "EXCEEDS" : "within range"}.</li>
                    )}
                  </ul>
                </details>
              </div>
            )}

            {res && res.wage_determination_error && (
              <div style={{ ...panel, color: "var(--red)", fontSize: 13 }}>
                Wage worksheet failed: {res.wage_determination_error}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
