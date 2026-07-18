import { useRef, useState } from "react";
import { API } from "./apiBase";
import { Spinner } from "./common";

const STATUS = {
  covered: { label: "Covered", color: "var(--green)", bg: "var(--green-dim)" },
  partial: { label: "Partial", color: "#b7791f", bg: "#b7791f18" },
  missing: { label: "Missing", color: "var(--red)", bg: "var(--red-dim)" },
  unclear: { label: "Needs review", color: "var(--blue)", bg: "var(--blue-dim)" },
  gaps: { label: "Gaps found", color: "var(--red)", bg: "var(--red-dim)" },
  review: { label: "Needs review", color: "var(--blue)", bg: "var(--blue-dim)" },
};

const card = {
  background: "var(--bg2)", border: "1px solid var(--border)",
  borderRadius: 10, padding: 16,
};

const scopeLabel = (requirement) => {
  const months = requirement.required_months;
  if (requirement.experience_scope === "base_experience") {
    return months ? `General qualifying experience · ${months} months` : "General qualifying experience";
  }
  if (requirement.experience_scope === "some_experience") {
    return "Must appear in qualifying experience · no full-term duration required";
  }
  if (requirement.experience_scope === "full_term") {
    return `Required throughout the full ${months || "stated"}-month experience term`;
  }
  if (requirement.experience_scope === "explicit_duration") {
    return months ? `Independent duration · ${months} months` : "Independent duration needs review";
  }
  if (requirement.experience_scope === "ambiguous") {
    return "PWD duration linkage needs review";
  }
  return "Express statement required";
};

function StatusBadge({ status }) {
  const tone = STATUS[status] || STATUS.review;
  return (
    <span style={{ display: "inline-flex", padding: "3px 8px", borderRadius: 5,
      color: tone.color, background: tone.bg, fontSize: 10, fontWeight: 700,
      letterSpacing: ".04em", textTransform: "uppercase", whiteSpace: "nowrap" }}>
      {tone.label}
    </span>
  );
}

function FilePicker({ label, hint, files, onFiles, accept, multiple = false }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);
  const selected = multiple ? files : (files ? [files] : []);
  const add = (incoming) => {
    const list = Array.from(incoming || []);
    if (!list.length) return;
    if (!multiple) return onFiles(list[0]);
    onFiles((current) => {
      const seen = new Set((current || []).map((f) => `${f.name}:${f.size}`));
      return [...(current || []), ...list.filter((f) => !seen.has(`${f.name}:${f.size}`))];
    });
  };
  const remove = (index) => {
    if (multiple) onFiles((current) => current.filter((_, i) => i !== index));
    else onFiles(null);
  };
  return (
    <div onClick={() => input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
      style={{ ...card, flex: 1, minWidth: 280, cursor: "pointer",
        borderStyle: "dashed", borderColor: over ? "var(--accent)" : "var(--border)",
        background: over ? "var(--accent-dim)" : "var(--bg2)" }}>
      <input ref={input} type="file" accept={accept} multiple={multiple}
        style={{ display: "none" }} onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
          stroke="var(--accent)" strokeWidth="1.6" style={{ flexShrink: 0 }}>
          <path d="M12 3v12"/><path d="m7 8 5-5 5 5"/><path d="M4 21h16"/>
        </svg>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 650, fontSize: 13 }}>{label}</div>
          {!selected.length && <div style={{ color: "var(--text3)", fontSize: 12,
            lineHeight: 1.5, marginTop: 3 }}>{hint}</div>}
          {selected.map((file, index) => (
            <div key={`${file.name}:${file.size}`} style={{ display: "flex", gap: 8,
              alignItems: "center", marginTop: 5, fontSize: 12 }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap" }}>{file.name}</span>
              <button type="button" onClick={(e) => { e.stopPropagation(); remove(index); }}
                aria-label={`Remove ${file.name}`} style={{ border: 0, background: "none",
                  color: "var(--red)", padding: 0, cursor: "pointer" }}>×</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Summary({ report }) {
  const s = report.summary;
  const tone = STATUS[s.status] || STATUS.review;
  return (
    <div style={{ ...card, borderLeft: `4px solid ${tone.color}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, fontSize: 17 }}>Coverage summary</h3>
        <StatusBadge status={s.status} />
        <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text3)" }}>
          {s.letters_reviewed} letter{s.letters_reviewed === 1 ? "" : "s"} reviewed
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(90px, 1fr))",
        gap: 8, marginTop: 14 }}>
        {[["covered", s.covered], ["partial", s.partial], ["missing", s.missing],
          ["unclear", s.unclear]].map(([key, count]) => (
          <div key={key} style={{ background: "var(--bg3)", borderRadius: 7, padding: "9px 10px" }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: STATUS[key].color }}>{count}</div>
            <div style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase",
              letterSpacing: ".05em" }}>{STATUS[key].label}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 11, fontSize: 12, color: "var(--text3)", lineHeight: 1.5 }}>
        A requirements route is complete only when every item in that route is expressly covered.
        Related duties and job titles are not treated as proof of an unstated requirement.
      </div>
    </div>
  );
}

function RequirementRow({ requirement, letters }) {
  const filenames = (requirement.evl_ids || []).map((id) =>
    letters.find((letter) => letter.id === id)?.filename || id);
  return (
    <div style={{ padding: "12px 0", borderTop: "1px solid var(--border)" }}>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <StatusBadge status={requirement.status} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.45 }}>
            {requirement.text}
          </div>
          <div style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase",
            letterSpacing: ".05em", marginTop: 3 }}>
            {requirement.category.replaceAll("_", " ")}
            {requirement.inherited_from_primary ? " · also applies from primary requirements" : ""}
          </div>
          <div style={{ fontSize: 11, color: requirement.experience_scope === "ambiguous"
            ? "#b7791f" : "var(--text3)", marginTop: 4 }}>
            {scopeLabel(requirement)}
          </div>
          {requirement.explanation && <div style={{ fontSize: 12.5, color: "var(--text2)",
            lineHeight: 1.5, marginTop: 7 }}>{requirement.explanation}</div>}
          {!!filenames.length && <div style={{ fontSize: 11.5, color: "var(--text3)", marginTop: 6 }}>
            Letter{filenames.length === 1 ? "" : "s"}: {filenames.join(", ")}
          </div>}
          {!!requirement.evidence_quotes?.length && (
            <div style={{ marginTop: 7, display: "flex", flexDirection: "column", gap: 5 }}>
              {requirement.evidence_quotes.map((quote, i) => (
                <div key={i} style={{ borderLeft: "2px solid var(--border)", paddingLeft: 9,
                  color: "var(--text3)", fontSize: 11.5, fontStyle: "italic", lineHeight: 1.45 }}>
                  “{quote}”
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RouteCard({ route, letters }) {
  return (
    <div style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 2 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 15 }}>{route.label}</h3>
          {route.selection_label && <div style={{ fontSize: 11.5, color: "var(--text3)",
            marginTop: 3 }}>{route.selection_label}</div>}
        </div>
        <StatusBadge status={route.status} />
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text3)" }}>
          {route.counts.covered}/{route.requirements.length} covered
        </span>
      </div>
      {route.requirements.map((requirement) =>
        <RequirementRow key={requirement.id} requirement={requirement} letters={letters} />)}
    </div>
  );
}

function QualificationOptions({ options, selected, onSelect }) {
  return (
    <div style={card}>
      <div style={{ fontWeight: 650, fontSize: 14 }}>Select the beneficiary’s PWD option</div>
      <div style={{ fontSize: 12, color: "var(--text3)", marginTop: 4, lineHeight: 1.5 }}>
        The degree selects the corresponding experience requirement. The EVLs are then reviewed
        only against that option; they are not expected to prove the degree itself.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
        gap: 10, marginTop: 12 }}>
        {options.map((route) => {
          const active = selected === route.id;
          return <button type="button" key={route.id} onClick={() => onSelect(route.id)}
            style={{ textAlign: "left", border: `1.5px solid ${active ? "var(--accent)" : "var(--border)"}`,
              background: active ? "var(--accent-dim)" : "var(--bg3)", color: "var(--text)",
              borderRadius: 8, padding: 12, cursor: "pointer" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span aria-hidden="true" style={{ width: 12, height: 12, borderRadius: "50%",
                border: `2px solid ${active ? "var(--accent)" : "var(--text3)"}`,
                boxShadow: active ? "inset 0 0 0 2px var(--bg2)" : "none",
                background: active ? "var(--accent)" : "transparent" }} />
              <span style={{ fontWeight: 650, fontSize: 13 }}>{route.selection_label}</span>
            </div>
            <div style={{ color: "var(--text3)", fontSize: 11.5, marginTop: 7, lineHeight: 1.45 }}>
              {route.requirements.map((requirement) => requirement.text).join(" · ")}
            </div>
          </button>;
        })}
      </div>
      <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 10 }}>
        Selection is by degree level. Confirm degree field, equivalency, and any second-degree
        requirement separately.
      </div>
    </div>
  );
}

function LetterCard({ letter, findings }) {
  const details = [
    ["Employer", letter.employer_name],
    ["Writer", [letter.writer_name, letter.writer_title].filter(Boolean).join(", ")],
    ["Writer role", letter.writer_relationship_label],
    ["Employment", [letter.start_date, letter.end_date || (letter.currently_employed ? "present" : null)]
      .filter(Boolean).join(" to ")],
    ["Work schedule", letter.hours_per_week ? `${letter.hours_per_week} hours/week`
      : letter.full_time === true ? "Full-time" : letter.full_time === false ? "Part-time" : null],
  ].filter(([, value]) => value);
  return (
    <div style={card}>
      <div style={{ fontWeight: 650, fontSize: 13, marginBottom: 10 }}>{letter.filename}</div>
      <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: "5px 10px",
        fontSize: 12 }}>
        {details.map(([label, value]) => <div key={label} style={{ display: "contents" }}>
          <span style={{ color: "var(--text3)" }}>{label}</span><span>{value}</span>
        </div>)}
      </div>
      {!!findings.length && <div style={{ marginTop: 11, display: "flex",
        flexDirection: "column", gap: 6 }}>
        {findings.map((finding) => <div key={finding.code} style={{ padding: "7px 9px",
          borderRadius: 6, background: finding.level === "missing" ? "var(--red-dim)" : "var(--blue-dim)",
          color: finding.level === "missing" ? "var(--red)" : "var(--text2)",
          fontSize: 11.5, lineHeight: 1.45 }}>{finding.message}</div>)}
      </div>}
    </div>
  );
}

export function EvlCompareView() {
  const [pwd, setPwd] = useState(null);
  const [evls, setEvls] = useState([]);
  const [pwdOptions, setPwdOptions] = useState(null);
  const [selectedRoute, setSelectedRoute] = useState("");
  const [readingPwd, setReadingPwd] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState(null);

  const changePwd = (file) => {
    setPwd(file); setPwdOptions(null); setSelectedRoute(""); setReport(null); setError("");
  };

  const readPwd = async () => {
    if (!pwd) return;
    setReadingPwd(true); setError(""); setPwdOptions(null); setSelectedRoute(""); setReport(null);
    const body = new FormData();
    body.append("form_9141", pwd);
    try {
      const response = await fetch(`${API}/perm-verify/evl-pwd-options`, { method: "POST", body });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || `PWD extraction failed (HTTP ${response.status})`);
      }
      const data = await response.json();
      setPwdOptions(data);
      if (data.route_options?.length === 1) setSelectedRoute(data.route_options[0].id);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setReadingPwd(false);
    }
  };

  const compare = async () => {
    if (!pwd || !evls.length || !pwdOptions || !selectedRoute) return;
    setBusy(true); setError(""); setReport(null);
    const body = new FormData();
    body.append("form_9141", pwd);
    evls.forEach((file) => body.append("evl_files", file));
    body.append("selected_route_id", selectedRoute);
    body.append("extracted_pwd_json", JSON.stringify(pwdOptions.pwd));
    try {
      const response = await fetch(`${API}/perm-verify/compare-evls`, { method: "POST", body });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || `Comparison failed (HTTP ${response.status})`);
      }
      setReport(await response.json());
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  };

  const download = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `evl-coverage-${report.pwd?.pwd_case_number || "report"}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <div style={{ maxWidth: 940, margin: "0 auto", padding: "24px 18px 64px",
        display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20 }}>PWD / EVL Coverage Review</h2>
          <div style={{ fontSize: 13, color: "var(--text3)", marginTop: 5, lineHeight: 1.5 }}>
            Compare the current ETA-9141 minimum and alternative requirements against one or more
            experience verification letters.
          </div>
        </div>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <FilePicker label="Prevailing wage determination *" hint="Upload the current ETA-9141 PDF"
            files={pwd} onFiles={changePwd} accept="application/pdf,.pdf" />
          <FilePicker label="Experience verification letters *" hint="Upload one or more PDF, image, or text letters"
            files={evls} onFiles={setEvls} multiple
            accept="application/pdf,image/jpeg,image/png,image/webp,.pdf,.jpg,.jpeg,.png,.webp,.txt,.md" />
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button onClick={readPwd} disabled={!pwd || readingPwd || busy}
            style={{ border: "1px solid var(--border)", borderRadius: 7, padding: "8px 13px",
              background: (!pwd || readingPwd || busy) ? "var(--bg3)" : "var(--bg2)",
              color: (!pwd || readingPwd || busy) ? "var(--text3)" : "var(--text)",
              fontWeight: 650, cursor: (!pwd || readingPwd || busy) ? "default" : "pointer" }}>
            {readingPwd ? "Reading PWD…" : pwdOptions ? "Read PWD again" : "Read PWD options"}
          </button>
          {readingPwd && <><Spinner /><span style={{ color: "var(--text3)", fontSize: 12 }}>
            Extracting education, experience, and duration-linked requirements…
          </span></>}
        </div>

        {pwdOptions?.route_options?.length > 0 && <QualificationOptions
          options={pwdOptions.route_options} selected={selectedRoute} onSelect={setSelectedRoute} />}

        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <button onClick={compare} disabled={!pwd || !evls.length || !selectedRoute || busy || readingPwd}
            style={{ border: 0, borderRadius: 7, padding: "9px 16px",
              background: (!pwd || !evls.length || !selectedRoute || busy || readingPwd)
                ? "var(--bg4)" : "var(--accent)",
              color: (!pwd || !evls.length || !selectedRoute || busy || readingPwd)
                ? "var(--text3)" : "white",
              fontWeight: 650,
              cursor: (!pwd || !evls.length || !selectedRoute || busy || readingPwd)
                ? "default" : "pointer" }}>
            {busy ? "Reviewing documents…" : "Compare letters to PWD"}
          </button>
          {busy && <><Spinner /><span style={{ color: "var(--text3)", fontSize: 12 }}>
            The local model reads each document separately; this can take several minutes.
          </span></>}
          {report && <button onClick={download} style={{ marginLeft: "auto", border: "1px solid var(--border)",
            borderRadius: 7, padding: "8px 12px", background: "var(--bg2)", color: "var(--text)",
            cursor: "pointer", fontSize: 12 }}>Download JSON report</button>}
        </div>

        {error && <div style={{ ...card, borderColor: "var(--red)", color: "var(--red)",
          fontSize: 12.5, lineHeight: 1.5 }}>{error}</div>}

        {report && <>
          <div style={{ fontSize: 12, color: "var(--text3)" }}>
            {report.pwd?.pwd_case_number && <>PWD <b style={{ color: "var(--text)" }}>
              {report.pwd.pwd_case_number}</b> · </>}
            {report.pwd?.requirements?.job_title || report.pwd?.job_title || "Job title not extracted"}
          </div>
          <Summary report={report} />

          <div>
            <h3 style={{ fontSize: 15, margin: "4px 0 9px" }}>Requirement-by-requirement report</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {report.routes.map((route) => <RouteCard key={route.id} route={route}
                letters={report.letters} />)}
            </div>
          </div>

          {!!report.supporting_evidence_advisories?.length && <div>
            <h3 style={{ fontSize: 15, margin: "4px 0 9px" }}>Supporting-evidence advisories</h3>
            {report.supporting_evidence_advisories.map((advisory) => (
              <div key={`${advisory.evl_id}-${advisory.code}`} style={{ ...card,
                borderLeft: "4px solid #b7791f", fontSize: 12.5, lineHeight: 1.55 }}>
                <div style={{ fontWeight: 650, marginBottom: 5 }}>{advisory.filename}</div>
                {advisory.message}
              </div>
            ))}
          </div>}

          <div>
            <h3 style={{ fontSize: 15, margin: "4px 0 9px" }}>Letter details</h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
              gap: 12 }}>
              {report.letters.map((letter) => <LetterCard key={letter.id} letter={letter}
                findings={report.document_findings.filter((finding) => finding.evl_id === letter.id)} />)}
            </div>
          </div>

          {!!report.pwd?.requirements?.extraction_notes?.length && <div style={card}>
            <div style={{ fontWeight: 650, fontSize: 13, marginBottom: 6 }}>PWD extraction notes</div>
            {report.pwd.requirements.extraction_notes.map((note, index) =>
              <div key={index} style={{ fontSize: 12, color: "var(--text3)", lineHeight: 1.5 }}>• {note}</div>)}
          </div>}

          <div style={{ fontSize: 11, color: "var(--text3)", lineHeight: 1.5 }}>
            This report identifies document coverage and review items. It does not make a legal
            conclusion about petition eligibility or sufficiency.
            {!!report.methodology?.authorities?.length && <div style={{ marginTop: 5 }}>
              Rules: {report.methodology.authorities.map((authority, index) => <span key={authority.citation}>
                {index > 0 ? " · " : ""}<a href={authority.url} target="_blank" rel="noreferrer"
                  style={{ color: "var(--accent)" }}>{authority.citation}</a>
              </span>)}
            </div>}
          </div>
        </>}
      </div>
    </div>
  );
}
