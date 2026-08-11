import { useEffect, useRef, useState } from "react";
import { API } from "./apiBase";

const panel = { background: "var(--bg2)", border: "1px solid var(--border)",
  borderRadius: 10, padding: 20, marginBottom: 16 };
const label = { display: "block", fontSize: 12, color: "var(--text3)",
  marginBottom: 4, marginTop: 14 };
const inp = { width: "100%", boxSizing: "border-box", background: "var(--bg3)",
  color: "var(--text1)", border: "1px solid var(--border)", borderRadius: 8,
  padding: "8px 10px", fontSize: 13, fontFamily: "inherit" };
const btn = (primary) => ({ padding: "9px 16px", borderRadius: 8, fontSize: 13,
  cursor: "pointer", border: `1px solid ${primary ? "var(--accent)" : "var(--border)"}`,
  background: primary ? "var(--accent)" : "var(--bg3)",
  color: primary ? "#fff" : "var(--text1)", fontWeight: 600 });

const wrapSkill = (line) => {
  let t = line.trim().replace(/[.;,]+$/, "");
  if (!t) return "";
  if (/\?$/.test(t)) return t;
  if (/^[A-Z][a-z]/.test(t)) t = t[0].toLowerCase() + t.slice(1);
  return `Does the applicant's experience involve ${t}?`;
};
const floorHalf = (n) => (n > 0 ? Math.max(1, Math.floor(n / 2)) : 0);


// Demo timeline: which cells are filled at each tick (500ms per tick).
// Skills 1,3,4,5 are YES and 2 is NO — threshold 3 of 5 is met at tick 7,
// the row sweeps yellow at tick 8, holds, then the loop resets.
const DEMO_SKILLS = ["YES", "NO", "YES", "YES", "YES"];
const DEMO_TICKS = 14;

function HelpPopup({ onClose }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick(v => (v + 1) % DEMO_TICKS), 500);
    return () => clearInterval(t);
  }, []);
  const eduOn = tick >= 1, expOn = tick >= 2;
  const skillsShown = Math.max(0, Math.min(5, tick - 2));
  const yesCount = DEMO_SKILLS.slice(0, skillsShown)
    .filter(v => v === "YES").length;
  const hit = expOn && yesCount >= 3;
  const lit = tick >= 8;

  const box = (filled, val) => ({
    minWidth: 40, padding: "6px 4px", fontSize: 11, fontWeight: 600,
    textAlign: "center", borderRadius: 6, border: "1px solid var(--border)",
    background: "var(--bg3)", color: val === "NO" ? "#c66" : "var(--text1)",
    opacity: filled ? 1 : 0.25,
    transform: filled ? "scale(1)" : "scale(.7)",
    transition: "opacity .3s, transform .3s cubic-bezier(.34,1.56,.64,1)",
  });
  const lbl = { fontSize: 9.5, color: "var(--text3)", textAlign: "center",
    marginBottom: 3, whiteSpace: "nowrap" };

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 60,
      background: "rgba(0,0,0,.45)", display: "flex", alignItems: "center",
      justifyContent: "center" }}>
      <style>{`
        @keyframes aeSweep { from { background-position: 100% 0; }
                             to   { background-position: 0% 0; } }
        @keyframes aePop { 0% { transform: scale(.6); opacity: 0; }
                           60% { transform: scale(1.12); opacity: 1; }
                           100% { transform: scale(1); opacity: 1; } }
        @keyframes aeGlow { 0%,100% { box-shadow: 0 0 0 0 rgba(250,204,21,0); }
                            50% { box-shadow: 0 0 14px 2px rgba(250,204,21,.45); } }
      `}</style>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "var(--bg2)",
        border: "1px solid var(--border)", borderRadius: 12, padding: 24,
        width: 480, maxWidth: "94vw", boxShadow: "0 12px 40px rgba(0,0,0,.4)" }}>
        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>
          Automatic highlight rule</div>

        <div style={{ borderRadius: 10, padding: "12px 12px 10px",
          border: "1px solid var(--border)",
          background: lit
            ? "linear-gradient(90deg, #FFF3A0 0%, #FFF3A0 50%, var(--bg3) 50%, var(--bg3) 100%)"
            : "var(--bg3)",
          backgroundSize: "200% 100%",
          animation: lit ? "aeSweep .7s ease-out forwards, aeGlow 1.6s ease-in-out .7s infinite" : "none",
          marginBottom: 12 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "flex-end",
            justifyContent: "center" }}>
            <div><div style={lbl}>Primary Edu</div>
              <div style={box(eduOn, "YES")}>YES</div></div>
            <div><div style={lbl}>Primary Exp</div>
              <div style={box(expOn, "YES")}>YES</div></div>
            <div style={{ width: 8 }} />
            {DEMO_SKILLS.map((v, i) => (
              <div key={i}><div style={lbl}>Skill {i + 1}</div>
                <div style={box(skillsShown > i, v)}>{v}</div></div>))}
            <div style={{ width: 8 }} />
            <div><div style={lbl}>Skills met</div>
              <div style={{ ...box(skillsShown > 0, "YES"),
                background: hit ? "#2e7d32" : "var(--bg3)",
                color: hit ? "#fff" : "var(--text2)",
                borderColor: hit ? "#2e7d32" : "var(--border)" }}>
                {yesCount} / 3</div></div>
          </div>
          <div style={{ textAlign: "center", marginTop: 10, minHeight: 26 }}>
            {lit
              ? <span style={{ display: "inline-block", fontSize: 12.5,
                  fontWeight: 700, color: "#3a3000", background: "#FFE94D",
                  border: "1px solid #E3C800", borderRadius: 6,
                  padding: "4px 12px", animation: "aePop .45s ease-out" }}>
                  ✓ Send Questionnaire — row highlighted</span>
              : <span style={{ fontSize: 11.5, color: lit ? "#3a3000" : "var(--text3)" }}>
                  {tick < 2 ? "Evaluating primary requirements…"
                    : skillsShown < 5 ? "Evaluating special skills…"
                    : "Requirements met — applying rule…"}</span>}
          </div>
        </div>

        <div style={{ fontSize: 12.5, color: "var(--text2)", lineHeight: 1.55 }}>
          When an applicant meets the primary or alternative requirements and at
          least your chosen number of special skills, the spreadsheet highlights
          the entire row yellow and flips the Pre-Screen Questionnaire column to
          &ldquo;Send Questionnaire.&rdquo; Recruiters instantly see who to
          contact — and the evaluator still verifies every recommendation.
        </div>
        <div style={{ textAlign: "right", marginTop: 16 }}>
          <button style={btn(false)} onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}


export function ApplicantEvalView() {
  const [jobTitle, setJobTitle] = useState("");
  const [reqNumber, setReqNumber] = useState("");
  const [pEdu, setPEdu] = useState("");
  const [pExp, setPExp] = useState("");
  const [hasAlt, setHasAlt] = useState(true);
  const [aEdu, setAEdu] = useState("");
  const [aExp, setAExp] = useState("");
  const [skills, setSkills] = useState([]);
  const [bulk, setBulk] = useState("");
  const [ruleOn, setRuleOn] = useState(true);
  const [threshold, setThreshold] = useState(0);
  const [thresholdTouched, setThresholdTouched] = useState(false);
  const [notes, setNotes] = useState([]);
  const [busy, setBusy] = useState(false);
  const [genBusy, setGenBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [help, setHelp] = useState(false);
  const fileInput = useRef(null);

  useEffect(() => {
    if (!thresholdTouched) setThreshold(floorHalf(skills.length));
    else if (threshold > skills.length) setThreshold(Math.max(1, skills.length));
  }, [skills.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadPwd = async (file) => {
    if (!file) return;
    setBusy(true); setErr(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const r = await fetch(`${API}/applicant-eval/from-pwd`, { method: "POST", body });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      const { config, extraction_notes } = await r.json();
      setJobTitle(config.job_title || "");
      setPEdu(config.primary?.education_question || "");
      setPExp(config.primary?.experience_question || "");
      setHasAlt(!!config.alternative);
      setAEdu(config.alternative?.education_question || "");
      setAExp(config.alternative?.experience_question || "");
      setSkills(config.special_skills || []);
      setRuleOn(!!config.highlight_rule?.enabled);
      setThreshold(config.highlight_rule?.threshold ||
        floorHalf((config.special_skills || []).length));
      setThresholdTouched(false);
      const extraNotes = [...(extraction_notes || [])];
      if ((config.conditions_excluded || []).length) {
        extraNotes.push("Excluded as conditions of employment (not skills): " +
          config.conditions_excluded.join("; "));
      }
      setNotes(extraNotes);
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };

  const addBulk = () => {
    const add = bulk.split("\n").map(wrapSkill).filter(Boolean);
    setSkills((s) => [...s, ...add.filter((q) => !s.includes(q))].slice(0, 26));
    setBulk("");
  };

  const generate = async () => {
    setGenBusy(true); setErr(null);
    try {
      const config = {
        job_title: jobTitle.trim(), req_number: reqNumber.trim(),
        primary: { education_question: pEdu.trim(), experience_question: pExp.trim() },
        alternative: hasAlt
          ? { education_question: aEdu.trim(), experience_question: aExp.trim() }
          : null,
        special_skills: skills,
        highlight_rule: { enabled: ruleOn, threshold },
      };
      const r = await fetch(`${API}/applicant-eval/generate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      const blob = await r.blob();
      const cd = r.headers.get("Content-Disposition") || "";
      const m = /filename="([^"]+)"/.exec(cd);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = m ? m[1] : "Applicant_Evaluation_Spreadsheet.xlsx";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { setErr(String(e.message || e)); }
    finally { setGenBusy(false); }
  };

  const canGenerate = pEdu.trim() && pExp.trim() &&
    (!hasAlt || (aEdu.trim() && aExp.trim()));

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "28px 24px 64px" }}>
        <h1 style={{ fontSize: 20, marginBottom: 4 }}>Applicant Evaluation Spreadsheet</h1>
        <div style={{ fontSize: 13, color: "var(--text3)", marginBottom: 24 }}>
          Build the recruiter review workbook for a PERM recruitment — load the
          requirements from a PWD, or paste them in, and download the finished
          Excel file.
        </div>
        {err && <div style={{ ...panel, borderColor: "#bf4b4b", color: "#f2b8b8" }}>{err}</div>}

        <div style={panel}>
          <div style={{ fontWeight: 650, fontSize: 13.5, marginBottom: 6 }}>
            1 · Load requirements</div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <input ref={fileInput} type="file" accept=".pdf" style={{ display: "none" }}
              onChange={(e) => { loadPwd(e.target.files?.[0]); e.target.value = ""; }} />
            <button style={btn(true)} disabled={busy}
              onClick={() => fileInput.current?.click()}>
              {busy ? "Parsing PWD…" : "Load from PWD PDF (ETA-9141)"}</button>
            <span style={{ fontSize: 12, color: "var(--text3)" }}>
              or fill in the sections below by hand / copy-paste.</span>
          </div>
          {!!notes.length && <div style={{ fontSize: 12, color: "var(--amber)",
            marginTop: 10 }}>Parser notes: {notes.join(" · ")}</div>}
        </div>

        <div style={panel}>
          <div style={{ fontWeight: 650, fontSize: 13.5 }}>2 · Position</div>
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
            <div><label style={label}>Job title</label>
              <input style={inp} value={jobTitle}
                onChange={(e) => setJobTitle(e.target.value)}
                placeholder="Senior Merchandising Analytics Manager" /></div>
            <div><label style={label}>Requisition #</label>
              <input style={inp} value={reqNumber}
                onChange={(e) => setReqNumber(e.target.value)}
                placeholder="R29297" /></div>
          </div>
        </div>

        <div style={panel}>
          <div style={{ fontWeight: 650, fontSize: 13.5 }}>3 · Primary requirements</div>
          <label style={label}>Education question</label>
          <textarea style={{ ...inp, minHeight: 54 }} value={pEdu}
            onChange={(e) => setPEdu(e.target.value)}
            placeholder="PRIMARY EDUCATION REQUIREMENT: Does the applicant have a Bachelor's degree in …, or a related field of study?" />
          <label style={label}>Experience question</label>
          <textarea style={{ ...inp, minHeight: 54 }} value={pExp}
            onChange={(e) => setPExp(e.target.value)}
            placeholder="PRIMARY EXPERIENCE REQUIREMENT: Does the applicant have N years of experience as a …, or related position/occupation?" />
        </div>

        <div style={panel}>
          <div style={{ display: "flex", justifyContent: "space-between",
            alignItems: "center" }}>
            <div style={{ fontWeight: 650, fontSize: 13.5 }}>
              4 · Alternative requirements</div>
            <label style={{ fontSize: 12.5, display: "inline-flex", gap: 6,
              alignItems: "center", cursor: "pointer", whiteSpace: "nowrap" }}>
              <input type="checkbox" style={{ width: "auto" }} checked={hasAlt}
                onChange={(e) => setHasAlt(e.target.checked)} />
              This PERM has an alternative requirement
            </label>
          </div>
          {hasAlt && <>
            <label style={label}>Education question</label>
            <textarea style={{ ...inp, minHeight: 54 }} value={aEdu}
              onChange={(e) => setAEdu(e.target.value)}
              placeholder="ALTERNATIVE EDUCATION REQUIREMENT: …" />
            <label style={label}>Experience question</label>
            <textarea style={{ ...inp, minHeight: 54 }} value={aExp}
              onChange={(e) => setAExp(e.target.value)}
              placeholder="ALTERNATIVE EXPERIENCE REQUIREMENT: …" />
          </>}
          {!hasAlt && <div style={{ fontSize: 12, color: "var(--text3)", marginTop: 8 }}>
            The alternative columns will be omitted from the spreadsheet and the
            recommendation formula will use the primary requirements only.</div>}
        </div>

        <div style={panel}>
          <div style={{ fontWeight: 650, fontSize: 13.5 }}>
            5 · Special skills ({skills.length})</div>
          {skills.map((s, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <textarea style={{ ...inp, minHeight: 38 }} value={s}
                onChange={(e) => setSkills(sk =>
                  sk.map((v, j) => (j === i ? e.target.value : v)))} />
              <button style={{ ...btn(false), padding: "4px 10px" }}
                aria-label="Remove skill"
                onClick={() => setSkills(sk => sk.filter((_, j) => j !== i))}>×</button>
            </div>
          ))}
          <label style={label}>Paste skills — one per line (they will be wrapped
            as &ldquo;Does the applicant&rsquo;s experience involve …?&rdquo;)</label>
          <textarea style={{ ...inp, minHeight: 72 }} value={bulk}
            onChange={(e) => setBulk(e.target.value)}
            placeholder={"SQL\n3 years managing analysts or data engineers\n…"} />
          <div style={{ marginTop: 8 }}>
            <button style={btn(false)} disabled={!bulk.trim()} onClick={addBulk}>
              Add pasted skills</button>
          </div>
        </div>

        <div style={panel}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ fontWeight: 650, fontSize: 13.5 }}>6 · Highlight rule</div>
            <button aria-label="What does the highlight rule do?"
              onClick={() => setHelp(true)}
              style={{ width: 20, height: 20, borderRadius: "50%", border:
                "1px solid var(--border)", background: "var(--bg3)",
                color: "var(--text2)", fontSize: 12, fontWeight: 700,
                cursor: "pointer", lineHeight: "18px", padding: 0 }}>?</button>
          </div>
          <label style={{ fontSize: 12.5, display: "inline-flex", gap: 6,
            alignItems: "center", cursor: "pointer", marginTop: 10 }}>
            <input type="checkbox" style={{ width: "auto" }} checked={ruleOn}
              onChange={(e) => setRuleOn(e.target.checked)} />
            <span>Highlight qualifying applicants and set the Pre-Screen
              Questionnaire column automatically</span>
          </label>
          {ruleOn && (
            <div style={{ display: "flex", gap: 10, alignItems: "center",
              marginTop: 12 }}>
              <span style={{ fontSize: 12.5, color: "var(--text2)" }}>
                Special skills required to highlight:</span>
              <input type="number" min={1} max={Math.max(1, skills.length)}
                value={skills.length ? threshold : 0}
                disabled={!skills.length}
                style={{ ...inp, width: 76,
                  opacity: skills.length ? 1 : 0.45 }}
                onChange={(e) => { setThresholdTouched(true);
                  setThreshold(Math.max(1, Math.min(skills.length,
                    Number(e.target.value) || 1))); }} />
              {skills.length > 0 ? (
                <span style={{ fontSize: 12, color: "var(--text3)" }}>
                  of {skills.length} · default {floorHalf(skills.length)} (at
                  least half, rounded down)</span>
              ) : (
                <span style={{ fontSize: 12, color: "var(--text3)" }}>
                  add special skills above to set this — until then the rule
                  uses the education and experience requirements only</span>
              )}
              {thresholdTouched && skills.length > 0 && (
                <button style={{ ...btn(false), padding: "4px 10px", fontSize: 12 }}
                  onClick={() => { setThresholdTouched(false);
                    setThreshold(floorHalf(skills.length)); }}>
                  Reset to default</button>)}
            </div>
          )}
          {!ruleOn && (
            <div style={{ fontSize: 12, color: "var(--text3)", marginTop: 8 }}>
              The spreadsheet will have a manual Send Questionnaire / Do Not
              Send dropdown instead of a formula, and no row highlighting.</div>)}
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button style={{ ...btn(true), opacity: canGenerate ? 1 : 0.5 }}
            disabled={!canGenerate || genBusy} onClick={generate}>
            {genBusy ? "Generating…" : "Generate spreadsheet"}</button>
          {!canGenerate && <span style={{ fontSize: 12, color: "var(--text3)" }}>
            Fill in the primary (and any alternative) questions first.</span>}
        </div>

        {help && <HelpPopup onClose={() => setHelp(false)} />}
      </div>
    </div>
  );
}
