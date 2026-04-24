import { useState, useEffect, useRef } from "react";
import { API } from "./apiBase";

// ── Template catalog ──────────────────────────────────────────────────────────
export const TEMPLATES = [
  // ── PERM ──────────────────────────────────────────────────────────────────
  {
    id: "perm_outcomes", group: "PERM", color: "var(--amber)",
    label: "PERM Case Outcomes",
    description: "Certified, denied, withdrawn, and certified-expired breakdown with % of total.",
    dataset: "perm", rows: ["case_status"], cols: null,
    metrics: [{ agg: "count", field: null, label: "Count" }, { agg: "pct_of_total", field: null, label: "% of Total" }],
    filters: [], params: [],
  },
  {
    id: "perm_outcomes_by_year", group: "PERM", color: "var(--amber)",
    label: "PERM Outcomes by Fiscal Year",
    description: "Certification and denial trends across fiscal years.",
    dataset: "perm", rows: ["fiscal_year"], cols: "case_status",
    metrics: [{ agg: "count", field: null, label: "Count" }],
    filters: [], params: [],
  },
  {
    id: "perm_top_firms", group: "PERM", color: "var(--amber)",
    label: "Top Law Firms by Volume + Cert Rate",
    description: "Law firms ranked by PERM filing volume with case status breakdown.",
    dataset: "perm", rows: ["atty_law_firm"], cols: "case_status",
    metrics: [{ agg: "count", field: null, label: "Count" }],
    filters: [], params: [],
  },
  {
    id: "perm_top_employers", group: "PERM", color: "var(--amber)",
    label: "Top Employers by Filing Volume",
    description: "Companies with the most PERM filings and their outcomes.",
    dataset: "perm", rows: ["employer_name"], cols: "case_status",
    metrics: [{ agg: "count", field: null, label: "Count" }],
    filters: [], params: [],
  },
  {
    id: "perm_soc_outcomes", group: "PERM", color: "var(--amber)",
    label: "PERM Outcomes by SOC Code",
    description: "Which occupations have the highest denial rates.",
    dataset: "perm", rows: ["soc_code", "soc_title"], cols: "case_status",
    metrics: [{ agg: "count", field: null, label: "Count" }],
    filters: [], params: [],
  },
  {
    id: "perm_employer_detail", group: "PERM", color: "var(--amber)",
    label: "Employer PERM History",
    description: "All PERM filings for a specific employer across fiscal years.",
    dataset: "perm", rows: ["fiscal_year", "case_status"], cols: null,
    metrics: [{ agg: "count", field: null, label: "Count" }],
    filters: [{ field: "employer_name", op: "ILIKE", value: "Google" }],
    params: [{ field: "employer_name", label: "Employer Name", op: "ILIKE" }],
  },
  {
    id: "perm_wage_by_soc", group: "PERM", color: "var(--amber)",
    label: "Wage Ranges by SOC Code",
    description: "Average, min, and max offered annual wages per SOC code.",
    dataset: "perm", rows: ["soc_code", "soc_title"], cols: null,
    metrics: [
      { agg: "count", field: null, label: "Cases" },
      { agg: "avg", field: "wage_from", label: "Avg Wage" },
      { agg: "min", field: "wage_from", label: "Min Wage" },
      { agg: "max", field: "wage_from", label: "Max Wage" },
    ],
    filters: [{ field: "wage_per", op: "=", value: "Year" }],
    params: [],
  },
  {
    id: "perm_occupation_type", group: "PERM", color: "var(--amber)",
    label: "Occupation Type Breakdown",
    description: "Professional vs non-professional PERM filings and their outcomes.",
    dataset: "perm", rows: ["occupation_type"], cols: "case_status",
    metrics: [{ agg: "count", field: null, label: "Count" }, { agg: "pct_of_total", field: null, label: "%" }],
    filters: [], params: [],
  },

  // ── PW ────────────────────────────────────────────────────────────────────
  {
    id: "pw_soc_drift_rate", group: "PW", color: "var(--green)",
    label: "SOC Drift — Highest Change Rate",
    description: "SOC codes most frequently changed from suggested. Shows total PWDs, changed count, and change rate %.",
    dataset: "pw", rows: ["suggested_soc_code", "suggested_soc_title"], cols: null,
    metrics: [{ agg: "count", field: null, label: "Total PWDs" }],
    filters: [], params: [],
    customQuery: "soc_drift_rate",
  },
  {
    id: "pw_soc_drift_detail", group: "PW", color: "var(--green)",
    label: "SOC Drift Detail by Suggested Code",
    description: "For a given suggested SOC, shows every assigned SOC code DOL used and how often.",
    dataset: "pw", rows: ["suggested_soc_code", "soc_code", "soc_title"], cols: null,
    metrics: [{ agg: "count", field: null, label: "Count" }],
    filters: [{ field: "suggested_soc_code", op: "=", value: "15-1299.00" }],
    params: [{ field: "suggested_soc_code", label: "Suggested SOC Code", op: "=" }],
  },
  {
    id: "pw_wage_level_dist", group: "PW", color: "var(--green)",
    label: "PWD Wage Level Distribution",
    description: "Percentage of PWDs returned at Level I, II, III, and IV.",
    dataset: "pw", rows: ["pw_wage_level"], cols: null,
    metrics: [{ agg: "count", field: null, label: "Count" }, { agg: "pct_of_total", field: null, label: "% of Total" }],
    filters: [], params: [],
  },
  {
    id: "pw_wage_source", group: "PW", color: "var(--green)",
    label: "Wage Source Usage",
    description: "Breakdown of OES vs alternative survey vs CBA vs SCA with percentages.",
    dataset: "pw", rows: ["wage_source"], cols: null,
    metrics: [{ agg: "count", field: null, label: "Count" }, { agg: "pct_of_total", field: null, label: "% of Total" }],
    filters: [], params: [],
  },
  {
    id: "pw_alt_survey_detail", group: "PW", color: "var(--green)",
    label: "Alternative Wage Survey Usage",
    description: "When employers use non-OES sources — which surveys, at what wage levels, vs OES.",
    dataset: "pw", rows: ["survey_name", "pw_wage_level"], cols: null,
    metrics: [
      { agg: "count", field: null, label: "Count" },
      { agg: "avg", field: "pwd_wage_rate", label: "Avg PWD Wage" },
    ],
    filters: [{ field: "wage_source", op: "!=", value: "OES" }, { field: "wage_source", op: "IS NOT NULL", value: "" }],
    params: [],
  },
  {
    id: "pw_firm_volume", group: "PW", color: "var(--green)",
    label: "Law Firm PW Volume",
    description: "Law firms ranked by PWD filings with wage level breakdown.",
    dataset: "pw", rows: ["law_firm_name"], cols: "pw_wage_level",
    metrics: [{ agg: "count", field: null, label: "Count" }],
    filters: [], params: [],
  },

  // ── LCA ───────────────────────────────────────────────────────────────────
  {
    id: "lca_wage_source", group: "LCA", color: "var(--blue)",
    label: "LCA Wage Source Breakdown",
    description: "Percentage of LCAs using OES, alternative survey, CBA, SCA, and other sources.",
    dataset: "lca", rows: ["pw_wage_level"], cols: null,
    metrics: [{ agg: "count", field: null, label: "Count" }, { agg: "pct_of_total", field: null, label: "% of Total" }],
    filters: [], params: [],
  },
  {
    id: "lca_by_visa_class", group: "LCA", color: "var(--blue)",
    label: "LCA Outcomes by Visa Class",
    description: "H-1B vs E-3 vs H-1B1 volume and status breakdown by fiscal year.",
    dataset: "lca", rows: ["fiscal_year", "visa_class"], cols: "case_status",
    metrics: [{ agg: "count", field: null, label: "Count" }],
    filters: [], params: [],
  },
  {
    id: "lca_h1b_dependent", group: "LCA", color: "var(--blue)",
    label: "H-1B Dependent Employers",
    description: "Employers flagged as H-1B dependent with their LCA filing volume.",
    dataset: "lca", rows: ["employer_name", "h1b_dependent"], cols: null,
    metrics: [{ agg: "count", field: null, label: "LCA Count" }],
    filters: [{ field: "h1b_dependent", op: "=", value: "Y" }],
    params: [],
  },
  {
    id: "lca_wage_gap", group: "LCA", color: "var(--blue)",
    label: "Wage Offered vs Prevailing Wage Gap",
    description: "How much above or below prevailing wage employers are offering, by SOC code.",
    dataset: "lca", rows: ["soc_code", "soc_title"], cols: null,
    metrics: [
      { agg: "count", field: null, label: "Cases" },
      { agg: "avg", field: "prevailing_wage", label: "Avg PW" },
      { agg: "avg", field: "wage_from", label: "Avg Offered" },
    ],
    filters: [{ field: "wage_unit", op: "=", value: "Year" }],
    params: [],
  },
  {
    id: "lca_top_employers", group: "LCA", color: "var(--blue)",
    label: "Top Employers by LCA Volume",
    description: "Companies with the most LCA filings, with willful violator flag surfaced.",
    dataset: "lca", rows: ["employer_name", "willful_violator"], cols: "fiscal_year",
    metrics: [{ agg: "count", field: null, label: "Count" }],
    filters: [], params: [],
  },
  {
    id: "lca_firm_by_year", group: "LCA", color: "var(--blue)",
    label: "Law Firm LCA Volume by Fiscal Year",
    description: "Law firm filing trends over time.",
    dataset: "lca", rows: ["law_firm_name"], cols: "fiscal_year",
    metrics: [{ agg: "count", field: null, label: "Count" }],
    filters: [], params: [],
  },
  // ── Cross-cutting ─────────────────────────────────────────────────────────
  {
    id: "firm_360", group: "Cross", color: "var(--purple, #a78bfa)",
    label: "Firm 360 — PERM + LCA + PW",
    description: "For a given law firm: PERM volume + cert rate, LCA volume, PW wage levels in one view.",
    dataset: "perm", rows: ["atty_law_firm", "case_status"], cols: null,
    metrics: [{ agg: "count", field: null, label: "PERM Count" }],
    filters: [{ field: "atty_law_firm", op: "ILIKE", value: "Fragomen" }],
    params: [{ field: "atty_law_firm", label: "Law Firm Name", op: "ILIKE" }],
    isFirm360: true,
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatVal(v) {
  if (v === null || v === undefined) return "—";
  const n = parseFloat(v);
  if (!isNaN(n) && n > 999) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (!isNaN(n)) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return String(v);
}

function exportCSV(columns, rows, filename) {
  const escape = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [columns.map(escape).join(","), ...rows.map(r => columns.map(c => escape(r[c] ?? "")).join(","))].join("\n");
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: filename });
  a.click(); URL.revokeObjectURL(a.href);
}

// ── Template runner ───────────────────────────────────────────────────────────
function TemplateRunner({ template, onBack, onOpenInBuilder }) {
  const [paramValues, setParamValues] = useState(
    Object.fromEntries((template.params || []).map(p => [p.field, template.filters.find(f => f.field === p.field)?.value || ""]))
  );
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [suggestions, setSuggestions] = useState({});
  const [showSug, setShowSug] = useState({});
  const tableMap = { perm: "oflc_perm", lca: "oflc_lca", pw: "oflc_pw" };

  const fetchSug = async (field, val) => {
    if (!val || val.length < 1) { setSuggestions(s => ({ ...s, [field]: [] })); return; }
    try {
      const r = await fetch(`${API}/oflc/field-values/${template.dataset}?field=${field}&q=${encodeURIComponent(val)}&limit=8`);
      if (r.ok) { const d = await r.json(); setSuggestions(s => ({ ...s, [field]: d.values || [] })); setShowSug(s => ({ ...s, [field]: true })); }
    } catch {}
  };

  const run = async () => {
    setLoading(true); setError(null);
    const params = new URLSearchParams();
    params.set("table", tableMap[template.dataset]);
    params.set("mode", "pivot");
    params.set("limit", "500");
    template.rows.forEach(r => params.append("rows", r));
    if (template.cols) params.set("cols", template.cols);
    template.metrics.forEach((m, i) => {
      params.set(`vm_agg_${i}`, m.agg);
      params.set(`vm_field_${i}`, m.field || "");
      params.set(`vm_label_${i}`, m.label);
    });
    // Merge template filters with param overrides
    let fi = 0;
    template.filters.forEach(f => {
      const val = template.params?.find(p => p.field === f.field) ? paramValues[f.field] : f.value;
      if (f.op === "IS NOT NULL" || f.op === "IS NULL" || val) {
        params.set(`f_field_${fi}`, f.field); params.set(`f_op_${fi}`, f.op); params.set(`f_val_${fi}`, val || ""); fi++;
      }
    });
    try {
      const r = await fetch(`${API}/oflc/query?${params}`);
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || `Error ${r.status}`); }
      setResults(await r.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  // Auto-run on mount if no params
  useEffect(() => { if (!template.params?.length) run(); }, []);

  // Derive columns from results
  const columns = results?.rows?.length
    ? Object.keys(results.rows[0])
    : [];

  const color = template.color;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "10px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0, display: "flex", alignItems: "center", gap: 12 }}>
        <button onClick={onBack} style={{ background: "none", border: "1px solid var(--border)", fontSize: 11, padding: "3px 10px", height: "auto", color: "var(--text3)" }}>← Templates</button>
        <div style={{ width: 1, height: 16, background: "var(--border)" }} />
        <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color }}>{template.group}</span>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>{template.label}</span>
        <div style={{ flex: 1 }} />
        <button onClick={() => onOpenInBuilder(template)} style={{ fontSize: 11, padding: "4px 12px", height: "auto", color: "var(--text3)", border: "1px solid var(--border)", background: "none" }}>Open in Builder ↗</button>
        {results?.rows?.length > 0 && (
          <button onClick={() => exportCSV(columns, results.rows, `${template.id}.csv`)} style={{ fontSize: 11, padding: "4px 12px", height: "auto", display: "flex", alignItems: "center", gap: 5 }}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            CSV
          </button>
        )}
      </div>

      {/* Params bar */}
      {template.params?.length > 0 && (
        <div style={{ padding: "10px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg3)", flexShrink: 0, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, color: "var(--text3)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em" }}>Parameters</span>
          {template.params.map(p => (
            <div key={p.field} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 11, color: "var(--text2)" }}>{p.label}:</span>
              <div style={{ position: "relative" }}>
                <input value={paramValues[p.field] || ""} onChange={e => { setParamValues(v => ({ ...v, [p.field]: e.target.value })); fetchSug(p.field, e.target.value); }}
                  onBlur={() => setTimeout(() => setShowSug(s => ({ ...s, [p.field]: false })), 150)}
                  style={{ fontSize: 12, padding: "4px 10px", minWidth: 200, borderColor: color }}
                  placeholder={`e.g. ${template.filters.find(f => f.field === p.field)?.value || "..."}`} />
                {showSug[p.field] && suggestions[p.field]?.length > 0 && (
                  <div style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50, background: "var(--bg2)", border: "1px solid var(--border2)", borderRadius: "var(--radius)", maxHeight: 160, overflowY: "auto", boxShadow: "0 6px 20px #00000066" }}>
                    {suggestions[p.field].map(v => (
                      <div key={v} onMouseDown={() => { setParamValues(pv => ({ ...pv, [p.field]: v })); setShowSug(s => ({ ...s, [p.field]: false })); }}
                        style={{ padding: "6px 10px", fontSize: 12, cursor: "pointer", color: "var(--text2)" }}
                        onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                        onMouseLeave={e => e.currentTarget.style.background = ""}>{v}</div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          <button onClick={run} className="primary" style={{ fontSize: 12, padding: "5px 16px", height: "auto", background: color, borderColor: color }}>
            {loading ? "Running…" : "▶ Run"}
          </button>
        </div>
      )}

      {/* Results */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {loading && (
          <div style={{ padding: "60px", display: "flex", justifyContent: "center" }}>
            <div style={{ width: 20, height: 20, border: "2px solid var(--border2)", borderTopColor: color, borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
          </div>
        )}
        {error && <div style={{ margin: 16, padding: "10px 14px", background: "var(--red-dim)", border: "1px solid var(--red)", borderRadius: "var(--radius)", fontSize: 12, color: "var(--red)", fontFamily: "'DM Mono', monospace" }}>{error}</div>}
        {!loading && !error && results?.rows?.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  {columns.map(c => (
                    <th key={c} style={{ padding: "8px 14px", textAlign: "left", fontWeight: 600, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--text3)", background: "var(--bg3)", borderBottom: "1px solid var(--border2)", position: "sticky", top: 0, whiteSpace: "nowrap" }}>
                      {c.replace(/__/g, " · ")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.rows.map((row, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}
                    onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                    onMouseLeave={e => e.currentTarget.style.background = ""}>
                    {columns.map((c, j) => (
                      <td key={c} style={{ padding: "7px 14px", color: j === 0 ? color : "var(--text2)", fontFamily: j < template.rows.length ? "'DM Mono', monospace" : "inherit", fontWeight: j === 0 ? 500 : 400 }}>
                        {formatVal(row[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              {results.grand_total && (
                <tfoot>
                  <tr style={{ borderTop: "2px solid var(--border2)", background: "var(--bg3)" }}>
                    {columns.map((c, j) => (
                      <td key={c} style={{ padding: "8px 14px", fontFamily: "'DM Mono', monospace", color, fontWeight: 700 }}>
                        {j === 0 ? "Grand Total" : formatVal(results.grand_total[c])}
                      </td>
                    ))}
                  </tr>
                </tfoot>
              )}
            </table>
            <div style={{ padding: "8px 14px", fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
              {results.total_rows?.toLocaleString()} rows{results.limited ? ` · showing top 500` : ""}
            </div>
          </div>
        )}
        {!loading && !error && results?.rows?.length === 0 && (
          <div style={{ padding: "60px", textAlign: "center", color: "var(--text3)", fontSize: 13 }}>No results found.</div>
        )}
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// ── Template Gallery ──────────────────────────────────────────────────────────
const GROUPS = ["PERM", "PW", "LCA", "Cross"];
const GROUP_LABELS = { PERM: "PERM", PW: "Prevailing Wage", LCA: "LCA (H-1B)", Cross: "Cross-cutting" };

export function OflcTemplates({ onBack, onOpenInBuilder }) {
  const [selected, setSelected] = useState(null);
  const [activeGroup, setActiveGroup] = useState("PERM");
  const [hovered, setHovered] = useState(null);

  if (selected) {
    return <TemplateRunner template={selected} onBack={() => setSelected(null)} onOpenInBuilder={t => { setSelected(null); onOpenInBuilder(t); }} />;
  }

  const visible = TEMPLATES.filter(t => t.group === activeGroup);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "10px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0, display: "flex", alignItems: "center", gap: 12 }}>
        <button onClick={onBack} style={{ background: "none", border: "1px solid var(--border)", fontSize: 11, padding: "3px 10px", height: "auto", color: "var(--text3)" }}>← Back</button>
        <div style={{ width: 1, height: 16, background: "var(--border)" }} />
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text3)" }}>Template Reports</span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: "var(--text3)" }}>{TEMPLATES.length} templates</span>
      </div>

      {/* Group tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
        {GROUPS.map(g => {
          const count = TEMPLATES.filter(t => t.group === g).length;
          const col = TEMPLATES.find(t => t.group === g)?.color || "var(--text3)";
          return (
            <button key={g} onClick={() => setActiveGroup(g)} style={{
              padding: "8px 16px", fontSize: 12, background: "none", border: "none", borderRadius: 0,
              borderBottom: activeGroup === g ? `2px solid ${col}` : "2px solid transparent",
              color: activeGroup === g ? col : "var(--text3)",
              fontWeight: activeGroup === g ? 500 : 400,
            }}>
              {GROUP_LABELS[g]} <span style={{ fontSize: 10, opacity: 0.6 }}>({count})</span>
            </button>
          );
        })}
      </div>

      {/* Cards grid */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
          {visible.map(t => (
            <div key={t.id} onClick={() => setSelected(t)}
              onMouseEnter={() => setHovered(t.id)} onMouseLeave={() => setHovered(null)}
              style={{
                padding: "20px", borderRadius: "var(--radius)", cursor: "pointer",
                border: `1px solid ${hovered === t.id ? t.color + "88" : "var(--border)"}`,
                background: hovered === t.id ? `${t.color}06` : "var(--bg2)",
                transition: "all 0.12s", display: "flex", flexDirection: "column", gap: 10,
                boxShadow: hovered === t.id ? `0 4px 20px #00000033` : "none",
              }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text)", lineHeight: 1.4 }}>{t.label}</span>
                {t.params?.length > 0 && (
                  <span style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, background: `${t.color}22`, color: t.color, fontWeight: 600, letterSpacing: "0.06em", whiteSpace: "nowrap", flexShrink: 0 }}>PARAM</span>
                )}
              </div>
              <span style={{ fontSize: 11, color: "var(--text3)", lineHeight: 1.6 }}>{t.description}</span>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                {t.rows.map(r => <span key={r} style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, background: "var(--bg4)", color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{r}</span>)}
                {t.cols && <span style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, background: `${t.color}18`, color: t.color, fontFamily: "'DM Mono', monospace" }}>÷ {t.cols}</span>}
              </div>
              <div style={{ marginTop: "auto", fontSize: 11, fontWeight: 500, color: t.color }}>Run report →</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
