import { useMemo, useRef, useState } from "react";
import { API } from "./apiBase";
import { Spinner } from "./common";

/* ---------------------------------------------------------------- helpers */
const LEVEL_STYLE = {
  RED:    { color: "var(--red)",   bg: "var(--red-dim)",   label: "RED" },
  YELLOW: { color: "#b07d2b",      bg: "#b07d2b18",        label: "YELLOW" },
};
const fmtMoney = (v) =>
  v == null ? "—" : `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
const fmtDate = (s) => (s ? s : "—");

function FileDrop({ label, hint, file, setFile, required, multiple }) {
  const inputRef = useRef(null);
  const [over, setOver] = useState(false);
  const files = multiple ? (file || []) : (file ? [file] : []);
  const has = files.length > 0;
  const addFiles = (list) => {
    const pdfs = Array.from(list || [])
      .filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!pdfs.length) return;
    if (multiple) {
      setFile((prev) => {
        const cur = prev || [];
        const seen = new Set(cur.map((f) => `${f.name}:${f.size}`));
        return [...cur, ...pdfs.filter((f) => !seen.has(`${f.name}:${f.size}`))];
      });
    } else {
      setFile(pdfs[0]);
    }
  };
  const removeAt = (i) => {
    if (multiple) setFile((prev) => (prev || []).filter((_, j) => j !== i));
    else setFile(null);
  };
  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault(); setOver(false);
        addFiles(e.dataTransfer.files);
      }}
      style={{
        flex: 1, minWidth: 260, cursor: "pointer", borderRadius: 10,
        border: `1.5px dashed ${over ? "var(--accent)" : has ? "var(--green)" : "var(--bg4)"}`,
        background: over ? "var(--bg3)" : "var(--bg2)",
        padding: "18px 16px", transition: "border-color .15s, background .15s",
      }}
    >
      <input ref={inputRef} type="file" accept="application/pdf"
        multiple={!!multiple} style={{ display: "none" }}
        onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
          stroke={has ? "var(--green)" : "var(--ink3, #888)"} strokeWidth="1.5">
          {has
            ? <path d="M20 6L9 17l-5-5" />
            : <><path d="M12 3v12" /><path d="M7 8l5-5 5 5" /><path d="M4 21h16" /></>}
        </svg>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>
            {label}{required && <span style={{ color: "var(--red)" }}> *</span>}
            {multiple && has && (
              <span style={{ opacity: 0.6, fontWeight: 400 }}>
                {" "}· {files.length} file{files.length > 1 ? "s" : ""}
              </span>
            )}
          </div>
          {!has && (
            <div style={{ fontSize: 12, opacity: 0.65, overflow: "hidden",
              textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {hint}
            </div>
          )}
          {has && files.map((f, i) => (
            <div key={`${f.name}:${f.size}`}
              style={{ fontSize: 12, opacity: 0.8, display: "flex",
                alignItems: "center", gap: 6, marginTop: i === 0 ? 2 : 1 }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap" }}>{f.name}</span>
              <button
                onClick={(e) => { e.stopPropagation(); removeAt(i); }}
                style={{ border: "none", background: "none",
                  color: "var(--red)", cursor: "pointer", fontSize: 11,
                  padding: 0, flexShrink: 0 }}>
                ✕
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* Filing-window rail: first-day ─── filing ─── last-day */
function FilingWindowRail({ window: w }) {
  const { first_day_to_file: a, last_day_to_file: b,
          review_date_presumed_filing: f, in_window } = w || {};
  const pct = useMemo(() => {
    if (!a || !b || !f) return null;
    const [ta, tb, tf] = [a, b, f].map((d) => new Date(d).getTime());
    if (tb <= ta) return null;
    return Math.max(0, Math.min(100, ((tf - ta) / (tb - ta)) * 100));
  }, [a, b, f]);
  const tone = in_window ? "var(--green)" : "var(--red)";
  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--bg4)",
      borderRadius: 10, padding: "14px 18px" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "baseline", marginBottom: 10 }}>
        <div style={{ fontWeight: 700, fontSize: 13 }}>
          Filing window
          <span style={{ marginLeft: 10, color: tone, fontWeight: 700 }}>
            {in_window ? "IN WINDOW" : "OUT OF WINDOW"}
          </span>
        </div>
        <div style={{ fontSize: 12, opacity: 0.7 }}>
          presumed filing (review date): <b>{fmtDate(f)}</b>
        </div>
      </div>
      <div style={{ position: "relative", height: 8, borderRadius: 4,
        background: "var(--bg3)", margin: "6px 2px 4px" }}>
        <div style={{ position: "absolute", inset: 0, borderRadius: 4,
          background: `${tone}22`, border: `1px solid ${tone}55` }} />
        {pct != null && (
          <div title={`Filing: ${f}`} style={{ position: "absolute",
            left: `calc(${pct}% - 6px)`, top: -4, width: 12, height: 16,
            borderRadius: 3, background: tone }} />
        )}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between",
        fontSize: 11.5, opacity: 0.75 }}>
        <span>first day to file: <b>{fmtDate(a)}</b></span>
        <span>last day to file: <b>{fmtDate(b)}</b></span>
      </div>
    </div>
  );
}

function FlagCard({ flag }) {
  const [open, setOpen] = useState(false);
  const s = LEVEL_STYLE[flag.level] || LEVEL_STYLE.YELLOW;
  const support = flag.support || [];
  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--bg4)",
      borderLeft: `4px solid ${s.color}`, borderRadius: 8, padding: "12px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ background: s.bg, color: s.color, fontWeight: 700,
          fontSize: 11, padding: "2px 8px", borderRadius: 5 }}>{s.label}</span>
        <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 12,
          fontWeight: 600 }}>{flag.rule_id}</span>
        <span style={{ fontSize: 12, opacity: 0.65 }}>§ {flag.section_item}</span>
        <span style={{ marginLeft: "auto", fontSize: 11, opacity: 0.55 }}>
          {flag.citation_type}
        </span>
      </div>
      <div style={{ fontSize: 13.5, margin: "8px 0 6px", lineHeight: 1.45 }}>
        {flag.message}
      </div>
      <div style={{ fontSize: 12, opacity: 0.75 }}>
        <b>Cite:</b> {flag.citation}
      </div>
      {support.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <button onClick={() => setOpen(!open)}
            style={{ border: "none", background: "none", color: "var(--accent)",
              cursor: "pointer", fontSize: 12, padding: 0 }}>
            {open ? "▾" : "▸"} {support.length} supporting source{support.length > 1 ? "s" : ""}
          </button>
          {open && support.map((ch) => (
            <div key={ch.chunk_id} style={{ marginTop: 6, padding: "8px 10px",
              background: "var(--bg3)", borderRadius: 6, fontSize: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 3 }}>
                [{ch.corpus}] {ch.source_label}
                {ch.cfr_citation && <span style={{ opacity: 0.6 }}> · {ch.cfr_citation}</span>}
                <span style={{ opacity: 0.45 }}> · chunk {ch.chunk_id}</span>
              </div>
              <div style={{ opacity: 0.8, lineHeight: 1.4 }}>{ch.snippet}…</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------- missing-data sidebar */
function setDeep(obj, path, value) {
  const parts = path.split(".");
  const out = { ...obj };
  let cur = out;
  for (let i = 0; i < parts.length - 1; i++) {
    cur[parts[i]] = { ...(cur[parts[i]] || {}) };
    cur = cur[parts[i]];
  }
  cur[parts[parts.length - 1]] = value;
  return out;
}

function MissingDataSidebar({ needs, onApply, applying }) {
  const [open, setOpen] = useState(true);
  const [values, setValues] = useState({});
  if (!needs?.length) return null;
  const key = (e) => `${e.scope}:${e.path}`;
  const groups = [
    ["form", "ETA-9089", needs.filter((e) => e.scope === "form")],
    ["pwd", "ETA-9141 (PWD)", needs.filter((e) => e.scope === "pwd")],
  ].filter(([, , g]) => g.length);
  const filled = Object.entries(values)
    .filter(([, v]) => v != null && String(v).trim() !== "");
  const inputStyle = { width: "100%", padding: "6px 8px", borderRadius: 6,
    border: "1px solid var(--bg4)", background: "var(--bg)",
    color: "inherit", fontSize: 12.5, boxSizing: "border-box" };
  return (
    <div style={{ position: "fixed", top: 70, right: open ? 0 : -318,
      bottom: 16, width: 318, zIndex: 40,
      transition: "right .25s ease", display: "flex" }}>
      <button onClick={() => setOpen(!open)}
        title={open ? "Collapse" : "Missing information"}
        style={{ alignSelf: "flex-start", marginTop: 18,
          border: "1px solid var(--bg4)", borderRight: "none",
          background: "#b07d2b", color: "#fff", cursor: "pointer",
          borderRadius: "8px 0 0 8px", padding: "10px 7px",
          fontWeight: 700, fontSize: 12, writingMode: "vertical-rl",
          transform: "rotate(180deg)", letterSpacing: 0.5 }}>
        Missing info · {needs.length}
      </button>
      <div style={{ flex: 1, background: "var(--bg2)",
        border: "1px solid var(--bg4)", borderRight: "none",
        borderRadius: "10px 0 0 10px", boxShadow: "-6px 0 24px rgba(0,0,0,.18)",
        display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "12px 14px 10px",
          borderBottom: "1px solid var(--bg4)" }}>
          <div style={{ fontWeight: 700, fontSize: 13.5 }}>
            Missing information
          </div>
          <div style={{ fontSize: 11.5, opacity: 0.65, marginTop: 3,
            lineHeight: 1.4 }}>
            These fields could not be read from the uploaded PDFs. Fill in
            what you know and re-verify — the checks that need them will run.
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "10px 14px" }}>
          {groups.map(([scope, title, items]) => (
            <div key={scope} style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 10.5, fontWeight: 700,
                textTransform: "uppercase", letterSpacing: 0.6,
                opacity: 0.55, margin: "4px 0 8px" }}>{title}</div>
              {items.map((e) => (
                <div key={key(e)} style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600,
                    marginBottom: 3 }}>
                    {e.label}
                    <span style={{ opacity: 0.5, fontWeight: 400 }}>
                      {" "}· {e.section_item}
                    </span>
                  </div>
                  {e.kind === "select" ? (
                    <select style={inputStyle}
                      value={values[key(e)] ?? ""}
                      onChange={(ev) => setValues((v) =>
                        ({ ...v, [key(e)]: ev.target.value }))}>
                      <option value="">— leave blank —</option>
                      {(e.options || []).map((o) => (
                        <option key={o} value={o}>{o}</option>
                      ))}
                    </select>
                  ) : (
                    <input style={inputStyle}
                      type={e.kind === "date" ? "date"
                            : e.kind === "number" ? "number" : "text"}
                      placeholder={e.kind === "money" ? "$" :
                                   e.kind === "date" ? "" : ""}
                      value={values[key(e)] ?? ""}
                      onChange={(ev) => setValues((v) =>
                        ({ ...v, [key(e)]: ev.target.value }))} />
                  )}
                  <div style={{ fontSize: 10.5, opacity: 0.5,
                    marginTop: 2, lineHeight: 1.35 }}>
                    Used by: {e.why}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div style={{ padding: "10px 14px",
          borderTop: "1px solid var(--bg4)" }}>
          <button disabled={!filled.length || applying}
            onClick={() => onApply(Object.fromEntries(filled), needs)}
            style={{ width: "100%", padding: "9px 0", borderRadius: 8,
              border: "none", fontWeight: 700, fontSize: 13,
              cursor: filled.length && !applying ? "pointer" : "default",
              background: filled.length && !applying
                ? "var(--accent)" : "var(--bg4)", color: "#fff" }}>
            {applying ? "Re-verifying…"
              : `Apply ${filled.length || ""} & re-verify`}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- main view */
export function PermVerifyView() {
  const [f9089, setF9089] = useState([]);
  const [f9141, setF9141] = useState(null);
  const [filingDate, setFilingDate] = useState("");
  const [cite, setCite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportAll, setExportAll] = useState(false);
  const [applying, setApplying] = useState(false);

  // Sidebar "Apply & re-verify": merge user-supplied values into the
  // extracted dicts and re-run the structured endpoint.  The page-image
  // overlay from the original run is kept (it reflects the PDFs).
  const applyMissing = async (vals, needs) => {
    if (!result) return;
    setApplying(true); setError(null);
    let form2 = result.form || {};
    let pwd2 = result.pwd ? { ...result.pwd } : null;
    const supplied = [];
    for (const [k, v] of Object.entries(vals)) {
      const [scope, ...rest] = k.split(":");
      const path = rest.join(":");
      const entry = needs.find((e) => e.scope === scope && e.path === path);
      let val = v;
      if (entry?.kind === "money" || entry?.kind === "number") {
        const n = Number(String(v).replace(/[$,\s]/g, ""));
        if (!Number.isNaN(n)) val = n;
      }
      if (entry?.kind === "date" && /^\d{4}-\d{2}-\d{2}$/.test(v)) {
        const [y, m, d] = v.split("-");
        val = `${Number(m)}/${Number(d)}/${y}`;   // engine expects M/D/YYYY
      }
      if (scope === "form") form2 = setDeep(form2, path, val);
      else if (pwd2) pwd2[path] = val;
      supplied.push(`${scope}.${path}`);
    }
    form2 = setDeep(form2, "meta.user_supplied",
      [...(form2.meta?.user_supplied || []), ...supplied]);
    try {
      const r = await fetch(`${API}/perm-verify/verify-data`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ form: form2, pwd: pwd2 || undefined,
          filing_date: filingDate || undefined, cite }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail
        || `HTTP ${r.status}`);
      const fresh = await r.json();
      setResult((prev) => ({ ...fresh, overlay: prev?.overlay }));
    } catch (e) {
      setError(`Re-verification failed: ${e.message || e}`);
    } finally {
      setApplying(false);
    }
  };

  const exportPdf = async () => {
    if (!result) return;
    setExporting(true);
    try {
      const r = await fetch(`${API}/perm-verify/export-pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...result, include_all_pages: exportAll }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `perm-verify-${result.form?.meta?.perm_case_number || "report"}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(`PDF export failed: ${e.message || e}`);
    } finally {
      setExporting(false);
    }
  };

  const run = async () => {
    if (!f9089.length) return;
    setBusy(true); setError(null); setResult(null);
    const body = new FormData();
    f9089.forEach((f) => body.append("form_9089", f));
    if (f9141) body.append("form_9141", f9141);
    if (filingDate) body.append("filing_date", filingDate);
    body.append("cite", cite ? "true" : "false");
    body.append("render", "true");
    try {
      const r = await fetch(`${API}/perm-verify/run`, { method: "POST", body });
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail
        || `HTTP ${r.status}`);
      setResult(await r.json());
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const form = result?.form || {};
  const pwd = result?.pwd;
  const flags = result?.flags || [];
  const reds = flags.filter((f) => f.level === "RED");
  const yellows = flags.filter((f) => f.level === "YELLOW");

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
    <div style={{ maxWidth: 940, margin: "0 auto", padding: "22px 18px 60px",
      display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 20 }}>PERM Verification</h2>
        <div style={{ fontSize: 13, opacity: 0.7, marginTop: 4 }}>
          Check a completed ETA-9089 for denial risks and audit flags. Add the
          ETA-9141 determination to enable wage, validity, and O*NET checks.
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <FileDrop label="ETA-9089" required multiple file={f9089} setFile={setF9089}
          hint="Drop the 9089 PDF(s) — final form, or FLAG draft print + appendices" />
        <FileDrop label="ETA-9141 (optional)" file={f9141} setFile={setF9141}
          hint="PWD determination — enables Tier 3 wage checks" />
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ fontSize: 13, display: "flex", gap: 8, alignItems: "center" }}>
          Filing date
          <input type="date" value={filingDate}
            onChange={(e) => setFilingDate(e.target.value)}
            style={{ padding: "6px 8px", borderRadius: 6,
              border: "1px solid var(--bg4)", background: "var(--bg2)",
              color: "inherit", fontSize: 13 }} />
          <span style={{ fontSize: 11.5, opacity: 0.55 }}>
            blank = today (pre-filing review)
          </span>
        </label>
        <label style={{ fontSize: 13, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={cite}
            onChange={(e) => setCite(e.target.checked)} />
          Cite sources (regs · instructions · BALCA)
        </label>
        <button onClick={run} disabled={!f9089.length || busy}
          style={{ marginLeft: "auto", padding: "9px 22px", borderRadius: 8,
            border: "none", cursor: f9089.length && !busy ? "pointer" : "default",
            background: f9089.length && !busy ? "var(--accent)" : "var(--bg4)",
            color: "#fff", fontWeight: 700, fontSize: 13.5 }}>
          {busy ? "Verifying…" : "Run verification"}
        </button>
      </div>

      {busy && <div style={{ display: "flex", justifyContent: "center",
        padding: 30 }}><Spinner /></div>}
      {error && (
        <div style={{ background: "var(--red-dim)", border: "1px solid var(--red)",
          color: "var(--red)", borderRadius: 8, padding: "10px 14px", fontSize: 13 }}>
          {error}
        </div>
      )}

      {result && !busy && (
        <>
          <MissingDataSidebar needs={result.needs_input}
            onApply={applyMissing} applying={applying} />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10,
            marginBottom: -6 }}>
            <label style={{ fontSize: 12, display: "flex", gap: 5,
              alignItems: "center", opacity: 0.8 }}>
              <input type="checkbox" checked={exportAll}
                onChange={(e) => setExportAll(e.target.checked)} />
              all pages in PDF
            </label>
            <button onClick={exportPdf} disabled={exporting}
              style={{ padding: "6px 14px", borderRadius: 7,
                border: "1px solid var(--bg4)", background: "var(--bg2)",
                color: "inherit", cursor: "pointer", fontSize: 12.5,
                fontWeight: 600 }}>
              {exporting ? "Building PDF…" : "Export PDF report"}
            </button>
          </div>
          <FilingWindowRail window={result.filing_window} />

          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <SummaryStat label="RED flags" value={reds.length}
              tone={reds.length ? "var(--red)" : "var(--green)"} />
            <SummaryStat label="YELLOW flags" value={yellows.length}
              tone={yellows.length ? "#b07d2b" : "var(--green)"} />
            <SummaryStat label="Case" value={form.meta?.perm_case_number || "—"} mono />
            <SummaryStat label="Employer"
              value={form.A_employer?.legal_business_name || "—"} />
            <SummaryStat label="Offered wage"
              value={`${fmtMoney(form.E_job_wage?.offered_wage_from)} / ${form.E_job_wage?.wage_per || "yr"}`} />
            {pwd && <SummaryStat label="Prevailing wage"
              value={`${fmtMoney(pwd.pw_minimum)}${pwd.pw_alternative ? ` · alt ${fmtMoney(pwd.pw_alternative)}` : ""}`} />}
            {pwd && <SummaryStat label="PWD validity"
              value={`${fmtDate(pwd.validity_from)} – ${fmtDate(pwd.validity_to)}`} />}
          </div>

          {result.overlay && (
            <FormOverlay overlay={result.overlay}
              onJump={(i) => document.getElementById(`flag-${i}`)
                ?.scrollIntoView({ behavior: "smooth", block: "center" })} />
          )}

          {flags.length === 0 ? (
            <div style={{ background: "var(--green-dim)", border: "1px solid var(--green)",
              color: "var(--green)", borderRadius: 8, padding: "14px 16px",
              fontWeight: 600, fontSize: 14 }}>
              No flags. Form is facially certifiable as of the review date.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {reds.map((f) => (
                <div key={`f${flags.indexOf(f)}`} id={`flag-${flags.indexOf(f)}`}>
                  <FlagCard flag={f} />
                </div>
              ))}
              {yellows.map((f) => (
                <div key={`f${flags.indexOf(f)}`} id={`flag-${flags.indexOf(f)}`}>
                  <FlagCard flag={f} />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
    </div>
  );
}

function SummaryStat({ label, value, tone, mono }) {
  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--bg4)",
      borderRadius: 8, padding: "10px 14px", minWidth: 130, flex: "1 1 auto" }}>
      <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5,
        opacity: 0.55 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, marginTop: 2,
        color: tone || "inherit",
        fontFamily: mono ? "ui-monospace, monospace" : undefined,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {value}
      </div>
    </div>
  );
}

/* ------------------------------------------------- annotated form overlay */
const MARKER_TONE = {
  RED:    { bg: "var(--red)",   fg: "#fff", glyph: "!" },
  YELLOW: { bg: "#b07d2b",      fg: "#fff", glyph: "!" },
  OK:     { bg: "var(--green)", fg: "#fff", glyph: "✓" },
};

function Marker({ m, onSelect, active }) {
  const t = MARKER_TONE[m.kind] || MARKER_TONE.OK;
  const flag = m.kind !== "OK";
  return (
    <div
      title={flag ? undefined : `${m.section_item} — ${m.message}`}
      onClick={flag ? (e) => { e.stopPropagation(); onSelect?.(m); } : undefined}
      style={{
        position: "absolute",
        left: `calc(${m.xPct}% - ${flag ? 22 : 16}px)`,
        top: `calc(${m.yPct}% - ${flag ? 4 : 2}px)`,
        width: flag ? 18 : 13, height: flag ? 18 : 13,
        borderRadius: "50%", background: t.bg, color: t.fg,
        fontSize: flag ? 12 : 9, fontWeight: 800, lineHeight: 1,
        display: "flex", alignItems: "center", justifyContent: "center",
        cursor: flag ? "pointer" : "default",
        boxShadow: flag
          ? `0 0 0 ${active ? 5 : 3}px ${t.bg}${active ? "55" : "33"}, 0 1px 3px rgba(0,0,0,.35)`
          : "0 1px 2px rgba(0,0,0,.25)",
        zIndex: flag ? 3 : 2,
      }}>
      {t.glyph}
    </div>
  );
}

function MarkerPopover({ m, onClose, onJumpToCard }) {
  const t = MARKER_TONE[m.kind] || MARKER_TONE.YELLOW;
  const left = m.xPct > 55;   // flip side near right edge
  return (
    <div onClick={(e) => e.stopPropagation()}
      style={{ position: "absolute", zIndex: 6,
        left: left ? undefined : `calc(${m.xPct}% + 6px)`,
        right: left ? `calc(${100 - m.xPct}% + 26px)` : undefined,
        top: `calc(${m.yPct}% - 8px)`,
        width: 300, background: "var(--bg2)", color: "inherit",
        border: `1px solid var(--bg4)`, borderTop: `3px solid ${t.bg}`,
        borderRadius: 8, boxShadow: "0 6px 22px rgba(0,0,0,.28)",
        padding: "10px 12px", fontSize: 12.5, lineHeight: 1.45 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ background: t.bg, color: "#fff", fontWeight: 700,
          fontSize: 10.5, padding: "1px 7px", borderRadius: 4 }}>{m.kind}</span>
        <b style={{ fontFamily: "ui-monospace, monospace" }}>{m.rule_id}</b>
        <span style={{ opacity: 0.6 }}>§ {m.section_item}</span>
        <button onClick={onClose} style={{ marginLeft: "auto", border: "none",
          background: "none", cursor: "pointer", color: "inherit",
          opacity: 0.6, fontSize: 14, lineHeight: 1 }}>×</button>
      </div>
      <div style={{ margin: "7px 0 8px" }}>{m.message}</div>
      <button onClick={() => onJumpToCard?.(m.flag_index)}
        style={{ border: "none", background: "none", padding: 0,
          color: "var(--accent)", cursor: "pointer", fontSize: 12 }}>
        Full details & citations ↓
      </button>
    </div>
  );
}

function FormOverlay({ overlay, onJump }) {
  const [selected, setSelected] = useState(null);   // marker w/ page+pcts
  const [showOk, setShowOk] = useState(true);
  const [pageFilter, setPageFilter] = useState("flagged");
  if (!overlay?.images?.length) return null;
  const flaggedPages = new Set(
    overlay.markers.filter((m) => m.kind !== "OK").map((m) => m.page));
  const visible = overlay.images
    .map((img, i) => ({ img, i }))
    .filter(({ i }) => pageFilter === "all" || flaggedPages.has(i));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>Annotated form</div>
        <label style={{ fontSize: 12.5, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={showOk}
            onChange={(e) => setShowOk(e.target.checked)} />
          show passing checks (✓)
        </label>
        <label style={{ fontSize: 12.5, display: "flex", gap: 6, alignItems: "center" }}>
          <select value={pageFilter} onChange={(e) => setPageFilter(e.target.value)}
            style={{ padding: "3px 6px", borderRadius: 5, fontSize: 12.5,
              border: "1px solid var(--bg4)", background: "var(--bg2)", color: "inherit" }}>
            <option value="flagged">flagged pages only</option>
            <option value="all">all pages</option>
          </select>
        </label>
      </div>
      {visible.length === 0 && (
        <div style={{ fontSize: 13, opacity: 0.65 }}>
          No flagged pages. Switch to “all pages” to review the full form.
        </div>
      )}
      {visible.map(({ img, i }) => {
        const meta = overlay.pages[i] || { w: 612, h: 792 };
        const marks = overlay.markers
          .filter((m) => m.page === i && (showOk || m.kind !== "OK"))
          .map((m) => ({ ...m, xPct: (m.x / meta.w) * 100, yPct: (m.y / meta.h) * 100 }));
        return (
          <div key={i} onClick={() => setSelected(null)}
            style={{ position: "relative", border: "1px solid var(--bg4)",
            borderRadius: 8, overflow: "visible", background: "#fff" }}>
            <div style={{ position: "absolute", top: 8, right: 10, zIndex: 4,
              background: "var(--bg2)", border: "1px solid var(--bg4)",
              borderRadius: 5, fontSize: 11, padding: "2px 8px", opacity: 0.85 }}>
              page {i + 1}
            </div>
            <img src={`data:image/png;base64,${img}`} alt={`ETA-9089 page ${i + 1}`}
              style={{ width: "100%", display: "block" }} />
            {marks.map((m, k) => (
              <Marker key={k} m={m}
                active={selected && selected.page === i &&
                        selected.rule_id === m.rule_id &&
                        selected.section_item === m.section_item}
                onSelect={(mm) => setSelected(
                  selected && selected.rule_id === mm.rule_id &&
                  selected.section_item === mm.section_item ? null : mm)} />
            ))}
            {selected && selected.page === i && (
              <MarkerPopover m={selected} onClose={() => setSelected(null)}
                onJumpToCard={(fi) => { setSelected(null); onJump?.(fi); }} />
            )}
          </div>
        );
      })}
    </div>
  );
}
