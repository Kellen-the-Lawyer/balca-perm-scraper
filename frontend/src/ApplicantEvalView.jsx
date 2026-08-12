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


// ── Help popup: how the highlight rule works ─────────────────────────────────
// A stepped walkthrough of a miniature spreadsheet — the same columns, formula,
// and conditional formatting the generated workbook uses. Auto-advances gently;
// any click takes over. The one animation is the yellow row sweep (the payoff),
// disabled under prefers-reduced-motion.
const DEMO_COLS = [
  { key: "name", letter: "A", label: "Applicant",  w: 86 },
  { key: "edu",  letter: "B", label: "Edu",        w: 52 },
  { key: "exp",  letter: "C", label: "Exp",        w: 52 },
  { key: "s1",   letter: "D", label: "Skill 1",    w: 58 },
  { key: "s2",   letter: "E", label: "Skill 2",    w: 58 },
  { key: "s3",   letter: "F", label: "Skill 3",    w: 58 },
  { key: "q",    letter: "G", label: "Pre-Screen", w: 134 },
];
const DEMO_ROW = { name: "A. Rivera", edu: "YES", exp: "YES", s1: "YES", s2: "NO", s3: "YES" };
const DEMO_FORMULA = '=IF(AND(B2="YES",C2="YES",COUNTIF(D2:F2,"YES")>=2),"Send Questionnaire","Do Not Send")';

const DEMO_STEPS = [
  { focus: ["edu", "exp"], fx: "YES",
    caption: "Recruiters answer YES or NO for the primary education and experience requirements." },
  { focus: ["s1", "s2", "s3"], fx: "YES",
    caption: "Then each special-skill question. This applicant meets 2 of the 3 — at least 2 are required." },
  { focus: ["q"], fx: DEMO_FORMULA,
    caption: "Column G runs the recommendation formula for every row — no manual tallying." },
  { focus: [], fx: DEMO_FORMULA,
    caption: "When the rule passes, conditional formatting turns the whole row yellow: contact this applicant." },
];

function HelpPopup({ onClose }) {
  const [step, setStep] = useState(0);
  const [auto, setAuto] = useState(true);
  const reduceMotion = typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  useEffect(() => {
    if (!auto) return;
    const t = setInterval(() => setStep(s => (s + 1) % DEMO_STEPS.length), 3200);
    return () => clearInterval(t);
  }, [auto]);

  const go = (s) => { setAuto(false); setStep(((s % DEMO_STEPS.length) + DEMO_STEPS.length) % DEMO_STEPS.length); };
  const cur = DEMO_STEPS[step];
  const lit = step === 3;
  const mono = "'DM Mono', monospace";
  const focused = (key) => cur.focus.includes(key);

  const cell = (key, text, { header = false, letter = false } = {}) => (
    <div key={key + (header ? "h" : letter ? "l" : "d")} style={{
      width: DEMO_COLS.find(c => c.key === key)?.w, flexShrink: 0,
      padding: letter ? "2px 6px" : "5px 6px",
      fontSize: letter ? 9 : header ? 10 : 11,
      fontFamily: mono,
      fontWeight: header || (key === "q" && lit) ? 600 : 400,
      textAlign: key === "name" ? "left" : "center",
      color: letter ? "var(--text3)"
        : header ? "var(--text2)"
        : text === "NO" ? "#b04a4a"
        : lit && key === "q" ? "#3a3000" : "var(--text)",
      background: letter ? "transparent"
        : header ? "var(--bg3)"
        : "transparent",
      borderRight: letter ? "none" : "1px solid var(--border)",
      borderBottom: letter ? "none" : "1px solid var(--border)",
      outline: !letter && !header && focused(key) ? "2px solid var(--amber)" : "none",
      outlineOffset: -2,
      transition: "outline-color .25s",
      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
    }}>{text}</div>
  );

  const qValue = step >= 2 ? "Send Questionnaire" : "";

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 60,
      background: "rgba(0,0,0,.45)", display: "flex", alignItems: "center",
      justifyContent: "center", padding: 16 }}>
      <style>{`
        @keyframes aeSweep { from { background-position: 100% 0; }
                             to   { background-position: 0% 0; } }
      `}</style>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "var(--bg2)",
        border: "1px solid var(--border)", borderRadius: 12, padding: 22,
        width: 540, maxWidth: "94vw", boxShadow: "0 12px 40px rgba(0,0,0,.4)" }}>
        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>
          How the highlight rule works</div>

        {/* Formula bar */}
        <div style={{ display: "flex", alignItems: "center", gap: 8,
          border: "1px solid var(--border)", borderBottom: "none",
          borderRadius: "8px 8px 0 0", background: "var(--bg3)",
          padding: "5px 10px" }}>
          <span style={{ fontFamily: mono, fontSize: 10, fontStyle: "italic",
            color: "var(--text3)", flexShrink: 0 }}>fx</span>
          <span style={{ fontFamily: mono, fontSize: 10, color: "var(--text2)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {cur.fx}</span>
        </div>

        {/* Miniature sheet */}
        <div className="m-scroll-x" style={{ border: "1px solid var(--border)",
          borderRadius: "0 0 8px 8px", background: "var(--bg)", marginBottom: 12 }}>
          <div style={{ minWidth: 502 }}>
            <div style={{ display: "flex" }}>
              {DEMO_COLS.map(c => cell(c.key, c.letter, { letter: true }))}
            </div>
            <div style={{ display: "flex", borderTop: "1px solid var(--border)" }}>
              {DEMO_COLS.map(c => cell(c.key, c.label, { header: true }))}
            </div>
            <div style={{ display: "flex",
              background: lit
                ? (reduceMotion ? "#FFF3A0"
                   : "linear-gradient(90deg, #FFF3A0 0%, #FFF3A0 50%, transparent 50%, transparent 100%)")
                : "transparent",
              backgroundSize: "200% 100%",
              animation: lit && !reduceMotion ? "aeSweep .6s ease-out forwards" : "none" }}>
              {DEMO_COLS.map(c => cell(c.key, c.key === "q" ? qValue : DEMO_ROW[c.key]))}
            </div>
          </div>
        </div>

        {/* Step caption + controls */}
        <div style={{ fontSize: 12.5, color: "var(--text2)", lineHeight: 1.55,
          minHeight: 40 }}>{cur.caption}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12 }}>
          <div style={{ display: "flex", gap: 6 }}>
            {DEMO_STEPS.map((_, i) => (
              <button key={i} onClick={() => go(i)} aria-label={`Step ${i + 1}`}
                style={{ width: 8, height: 8, minHeight: "unset", padding: 0,
                  borderRadius: "50%", border: "none", cursor: "pointer",
                  background: i === step ? "var(--amber)" : "var(--border)" }} />
            ))}
          </div>
          <button onClick={() => go(step - 1)} style={{ ...btn(false),
            fontSize: 11, padding: "4px 10px" }}>‹ Back</button>
          <button onClick={() => go(step + 1)} style={{ ...btn(false),
            fontSize: 11, padding: "4px 10px" }}>Next ›</button>
          <div style={{ flex: 1 }} />
          <button style={btn(false)} onClick={onClose}>Close</button>
        </div>
        <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 10 }}>
          The evaluator still verifies every recommendation.</div>
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
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
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
          <div className="m-stack" style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
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
