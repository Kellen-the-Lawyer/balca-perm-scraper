import { useState } from "react";
import { API } from "./apiBase";

const DEGREES = [
  ["none", "No degree requirement"],
  ["high_school", "High school / GED"],
  ["associates", "Associate's degree"],
  ["bachelors", "Bachelor's degree"],
  ["masters", "Master's degree"],
  ["doctorate", "Doctorate (Ph.D.)"],
  ["professional", "First professional (J.D., M.D., …)"],
];

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

const fmtA = n => "$" + Math.round(n).toLocaleString();

const label = { display: "block", fontSize: 12, color: "var(--text3)", marginBottom: 4, marginTop: 14 };
const panel = { background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 10, padding: 20 };

export function WageLevelView() {
  const [soc, setSoc] = useState("");
  const [occ, setOcc] = useState(null);          // occupation prefill
  const [occErr, setOccErr] = useState(null);
  const [degree, setDegree] = useState("bachelors");
  const [years, setYears] = useState("");
  const [skills, setSkills] = useState(0);
  const [lang, setLang] = useState(false);
  const [sup, setSup] = useState(false);
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
    } catch { /* dropdown stays empty; determine still works state-wide */ }
  };

  const lookupOcc = async () => {
    setOcc(null); setOccErr(null);
    if (!soc.trim()) return;
    try {
      const r = await fetch(`${API}/wage-level/occupation/${encodeURIComponent(soc.trim())}`);
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      setOcc(await r.json());
    } catch (e) { setOccErr(String(e.message || e)); }
  };

  const determine = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      const body = {
        soc_code: soc.trim() || null,
        degree_required: degree,
        years_experience_required: years === "" ? 0 : Number(years),
        special_skills_points: Number(skills),
        foreign_language_required: lang,
        supervisory_duties: sup,
        state_ab: state || null,
        county_name: county.trim() || null,
      };
      const r = await fetch(`${API}/wage-level/determine`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      setRes(await r.json());
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };

  const ls = res ? LEVEL_STYLE[res.wage_level] : null;

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "28px 24px 64px" }}>
        <h1 style={{ fontSize: 20, marginBottom: 4 }}>Wage Level Determination</h1>
        <div style={{ fontSize: 13, color: "var(--text3)", marginBottom: 24 }}>
          NPWHC 2009 guidance worksheet — start at Level I, add points for requirements
          beyond the O*NET Job Zone norm. An audit aid, not a substitute for judgment.
          {" "}Validated against 194K FY2025 DOL determinations: 82% exact, 96% within
          one level — misses run one level low (Step-4 skills judgment).
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: 20, alignItems: "start" }}>
          {/* ── Inputs ── */}
          <div style={panel}>
            <label style={{ ...label, marginTop: 0 }}>SOC code (or O*NET-SOC)</label>
            <input value={soc} onChange={e => setSoc(e.target.value)} onBlur={lookupOcc}
                   placeholder="e.g. 15-1252" style={{ width: "100%" }} />
            {occErr && <div style={{ fontSize: 12, color: "var(--red)", marginTop: 6 }}>{occErr}</div>}
            {occ && (
              <div style={{ fontSize: 12, marginTop: 8, padding: "8px 10px", background: "var(--bg3)",
                            border: "1px solid var(--border)", borderRadius: 6, lineHeight: 1.5 }}>
                <b>{occ.soc_title || occ.soc_code}</b>
                {occ.job_zone
                  ? <> — Job Zone {occ.job_zone} <span style={{ color: "var(--text3)" }}>
                      (SVP {occ.zone_reference?.svp_range})</span></>
                  : <span style={{ color: "var(--red)" }}> — no Job Zone found</span>}
                <div style={{ color: "var(--text3)" }}>
                  {occ.is_professional_occupation
                    ? <>Appendix D professional occupation — usual: {occ.appendix_d_category_label}
                        {occ.appendix_d_via !== occ.soc_code && <> (via {occ.appendix_d_via})</>}</>
                    : "Not on Appendix D — usual education taken from the Job Zone"}
                </div>
              </div>
            )}

            <label style={label}>Degree required by the job offer</label>
            <select value={degree} onChange={e => setDegree(e.target.value)} style={{ width: "100%" }}>
              {DEGREES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>

            <label style={label}>Years of experience required</label>
            <input type="number" min="0" step="0.5" value={years}
                   onChange={e => setYears(e.target.value)} placeholder="0" style={{ width: "100%" }} />

            <label style={label}>Special skills beyond entry level (Step 4 — your judgment)</label>
            <select value={skills} onChange={e => setSkills(e.target.value)} style={{ width: "100%" }}>
              <option value={0}>None</option>
              <option value={1}>Yes — 1 point</option>
              <option value={2}>Yes, substantial — 2 points</option>
            </select>

            <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8, fontSize: 13 }}>
              <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
                <input type="checkbox" checked={lang} onChange={e => setLang(e.target.checked)} />
                Foreign language required (generally +1)
              </label>
              <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
                <input type="checkbox" checked={sup} onChange={e => setSup(e.target.checked)} />
                Supervisory duties (+1 unless customary)
              </label>
            </div>

            <div style={{ borderTop: "1px solid var(--border)", marginTop: 16, paddingTop: 4 }}>
              <label style={label}>Wage lookup (optional) — state / county</label>
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

            <button onClick={determine} disabled={busy || (!soc.trim())}
                    style={{ marginTop: 18, width: "100%", padding: "9px 0", borderRadius: 7,
                             background: "var(--amber)", color: "#1a1206", fontWeight: 600,
                             border: "none", cursor: "pointer", opacity: busy ? 0.6 : 1 }}>
              {busy ? "Determining…" : "Determine wage level"}
            </button>
            {err && <div style={{ fontSize: 12, color: "var(--red)", marginTop: 8 }}>{err}</div>}
          </div>

          {/* ── Result ── */}
          <div>
            {!res && (
              <div style={{ ...panel, color: "var(--text3)", fontSize: 13, lineHeight: 1.7 }}>
                Enter the SOC code, the degree, and the years of experience the job offer
                requires, then run the determination. The worksheet on this side shows every
                point awarded with its rationale so each step can be audited or overridden.
              </div>
            )}
            {res && (
              <>
                <div style={{ ...panel, display: "flex", alignItems: "center", gap: 16,
                              background: ls.bg, border: `1px solid ${ls.border}` }}>
                  <div style={{ fontSize: 30, fontWeight: 700, color: ls.color }}>
                    {res.wage_level_label}
                  </div>
                  <div style={{ fontSize: 13, color: ls.color, opacity: 0.85 }}>
                    {res.soc_title || res.soc_code} · Job Zone {res.job_zone} ·{" "}
                    {res.total_points} point{res.total_points === 1 ? "" : "s"}
                    {res.total_points > 4 && " (capped at IV)"}
                    {res.wage_level < 4 && Number(skills) === 0 && (
                      <div style={{ fontSize: 12, marginTop: 4, opacity: 0.9 }}>
                        Treat as a floor — with no Step-4 skills points entered, DOL
                        lands one level higher in ~16% of comparable cases.
                      </div>
                    )}
                  </div>
                </div>

                {res.wage && (
                  <div style={{ ...panel, marginTop: 14 }}>
                    <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 10 }}>
                      OFLC {res.wage.wage_year - 1}–{String(res.wage.wage_year).slice(2)} wages —{" "}
                      {res.wage.area_name}{res.wage.county_name ? ` (${res.wage.county_name})` : ""}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10 }}>
                      {["i","ii","iii","iv"].map((k, i) => {
                        const st = LEVEL_STYLE[i + 1];
                        const active = i + 1 === res.wage_level;
                        const h = res.wage.levels_hourly[k];
                        return (
                          <div key={k} style={{ padding: "10px 12px", borderRadius: 8,
                                background: st.bg, border: `2px solid ${active ? st.color : st.border}`,
                                opacity: active ? 1 : 0.55 }}>
                            <div style={{ fontSize: 11, fontWeight: 600, color: st.color }}>
                              LEVEL {["I","II","III","IV"][i]}{active && " ✓"}</div>
                            <div style={{ fontSize: 16, fontWeight: 700, color: st.color }}>
                              {fmtA(h * 2080)}/yr</div>
                            <div style={{ fontSize: 11, color: st.color, opacity: 0.8 }}>
                              ${h.toFixed(2)}/hr</div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
                {res.wage === null && (state || county) && (
                  <div style={{ fontSize: 12, color: "var(--text3)", marginTop: 10 }}>
                    No wage row matched that state/county for {res.soc_code}.
                  </div>
                )}

                {res.svp_analysis && (
                  <div style={{ ...panel, marginTop: 14 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
                      SVP-equivalency analysis
                      <span style={{ color: "var(--text3)", fontWeight: 400 }}>
                        {" "}— informational, not scored
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 13 }}>
                      <div>Experience: <b>{res.svp_analysis.experience_months} mo</b></div>
                      <div>+ Education SVP-equiv: <b>{res.svp_analysis.education_svp_equivalent_months} mo</b></div>
                      <div>= Combined: <b>{res.svp_analysis.combined_svp_months} mo
                        {" "}({res.svp_analysis.combined_svp_years} yr)</b></div>
                      <div>Zone {res.job_zone} SVP ceiling:{" "}
                        <b>{res.svp_analysis.zone_svp_ceiling_months} mo</b></div>
                      <div style={{ fontWeight: 700,
                            color: res.svp_analysis.exceeds_zone_svp ? "var(--red)" : "var(--green)" }}>
                        {res.svp_analysis.exceeds_zone_svp ? "EXCEEDS SVP range" : "Within SVP range"}
                      </div>
                    </div>
                    <div style={{ fontSize: 11.5, color: "var(--text3)", marginTop: 8, lineHeight: 1.6 }}>
                      {res.svp_analysis.notes.map((n, i) => <div key={i}>• {n}</div>)}
                    </div>
                  </div>
                )}

                <div style={{ ...panel, marginTop: 14, padding: 0, overflowX: "auto", overflowY: "hidden" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                    <thead>
                      <tr style={{ background: "var(--bg3)", textAlign: "left" }}>
                        <th style={{ padding: "8px 14px", width: 44 }}>Step</th>
                        <th style={{ padding: "8px 6px", width: 200 }}>Item</th>
                        <th style={{ padding: "8px 6px", width: 44 }}>Pts</th>
                        <th style={{ padding: "8px 14px 8px 6px" }}>Rationale</th>
                      </tr>
                    </thead>
                    <tbody>
                      {res.worksheet.map(w => (
                        <tr key={w.step} style={{ borderTop: "1px solid var(--border)" }}>
                          <td style={{ padding: "9px 14px", color: "var(--text3)" }}>{w.step}</td>
                          <td style={{ padding: "9px 6px" }}>{w.label}</td>
                          <td style={{ padding: "9px 6px", fontWeight: 700,
                                       color: w.points ? "var(--amber)" : "var(--text3)" }}>
                            {w.points ? `+${w.points}` : "0"}</td>
                          <td style={{ padding: "9px 14px 9px 6px", color: "var(--text2)",
                                       lineHeight: 1.5 }}>{w.rationale}
                            {w.usual_source && (
                              <div style={{ fontSize: 11, color: "var(--text3)" }}>{w.usual_source}</div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div style={{ fontSize: 11.5, color: "var(--text3)", marginTop: 12, lineHeight: 1.6 }}>
                  {res.caveats.map((c, i) => <div key={i}>• {c}</div>)}
                  <div>• Source: {res.guidance}, Appendices A–E; O*NET Job Zones; 20 CFR 656.40.</div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
