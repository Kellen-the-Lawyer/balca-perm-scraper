import { useState, useEffect } from "react";
import { API } from "./apiBase";

const FISCAL_YEARS = ["All", "FY2026", "FY2025", "FY2024", "FY2023", "FY2022", "FY2021", "FY2020"];

function useQuery(table, rows, cols, metrics, filters, fy, deps) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams();
    params.set("table", table); params.set("mode", "pivot"); params.set("limit", "25");
    rows.forEach(r => params.append("rows", r));
    if (cols) params.set("cols", cols);
    metrics.forEach((m, i) => { params.set(`vm_agg_${i}`, m.agg); params.set(`vm_field_${i}`, m.field || ""); params.set(`vm_label_${i}`, m.label); });
    let fi = 0;
    filters.forEach(f => { params.set(`f_field_${fi}`, f.field); params.set(`f_op_${fi}`, f.op); params.set(`f_val_${fi}`, f.value); fi++; });
    if (fy && fy !== "All") { params.set(`f_field_${fi}`, "fiscal_year"); params.set(`f_op_${fi}`, "="); params.set(`f_val_${fi}`, fy); }
    fetch(`${API}/oflc/query?${params}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [fy, ...deps]);

  return { data, loading };
}

// ── Mini bar chart ────────────────────────────────────────────────────────────
function MiniBar({ rows, labelKey, valueKey, color, horizontal = true, maxRows = 12 }) {
  const data = (rows || [])
    .map(r => ({ label: String(r[labelKey] ?? "—").slice(0, 35), value: parseFloat(r[valueKey]) || 0 }))
    .sort((a, b) => b.value - a.value)
    .slice(0, maxRows);
  const max = Math.max(...data.map(d => d.value), 1);
  if (!data.length) return <div style={{ color: "var(--text2)", fontSize: 12, padding: "20px 0" }}>No data</div>;

  if (!horizontal) {
    return (
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 120, paddingBottom: 24, overflowX: "auto" }}>
        {data.map((d, i) => (
          <div key={i} title={`${d.label}: ${d.value.toLocaleString()}`} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, flex: "0 0 auto", minWidth: 28 }}>
            <span style={{ fontSize: 8, color: "var(--text2)", fontFamily: "'DM Mono', monospace" }}>{d.value > 999 ? (d.value/1000).toFixed(1)+"k" : d.value}</span>
            <div style={{ width: 24, background: color, borderRadius: "2px 2px 0 0", height: `${Math.max(3,(d.value/max)*90)}px`, opacity: 0.85 }} />
            <span style={{ fontSize: 8, color: "var(--text)", writingMode: "vertical-lr", transform: "rotate(180deg)", maxHeight: 40, overflow: "hidden" }}>{d.label}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      {data.map((d, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 10, color: "var(--text)", flex: "0 0 160px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "right", fontFamily: "'DM Mono', monospace" }}>{d.label}</span>
          <div style={{ flex: 1, height: 16, background: "var(--bg4)", borderRadius: 2, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${(d.value/max)*100}%`, background: color, borderRadius: 2, transition: "width 0.4s" }} />
          </div>
          <span style={{ fontSize: 10, color, fontFamily: "'DM Mono', monospace", flex: "0 0 52px", textAlign: "right" }}>{d.value > 999 ? d.value.toLocaleString() : d.value}</span>
        </div>
      ))}
    </div>
  );
}

// ── Widget card wrapper ───────────────────────────────────────────────────────
function Widget({ title, subtitle, loading, color, children, span = 1 }) {
  return (
    <div style={{ gridColumn: `span ${span}`, background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
      <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text)", letterSpacing: "0.02em" }}>{title}</div>
          {subtitle && <div style={{ fontSize: 10, color: "var(--text2)", marginTop: 2 }}>{subtitle}</div>}
        </div>
        {loading && <div style={{ width: 12, height: 12, border: `2px solid var(--border2)`, borderTopColor: color, borderRadius: "50%", animation: "spin 0.7s linear infinite", flexShrink: 0 }} />}
      </div>
      <div style={{ padding: "14px 16px" }}>{children}</div>
    </div>
  );
}

// ── KPI card ─────────────────────────────────────────────────────────────────
function KPI({ label, value, color, sub }) {
  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "16px 20px", borderTop: `3px solid ${color}` }}>
      <div style={{ fontSize: 22, fontWeight: 700, color, fontFamily: "'DM Mono', monospace", lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 10, color: "var(--text2)", textTransform: "uppercase", letterSpacing: "0.07em", marginTop: 6 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text2)", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ── Pie chart ─────────────────────────────────────────────────────────────────
const STATUS_COLORS = {
  "Certified":            "#22c55e",
  "Certified-Expired":    "#86efac",
  "Certified - Expired":  "#86efac",
  "Withdrawn":            "#f59e0b",
  "Denied":               "#ef4444",
  "Certified - Withdrawn":"#fbbf24",
  "Determination Issued": "#22c55e",
  "Redetermination Affirmed": "#86efac",
  "Redetermination Modified": "#f59e0b",
  "Center Director Review Affirmed Determination": "#86efac",
  "Center Director Review Modified Determination": "#f59e0b",
};
const FALLBACK_COLORS = ["#6366f1","#8b5cf6","#a78bfa","#c4b5fd","#60a5fa","#34d399"];

function PieChart({ rows, labelKey, valueKey }) {
  const raw = (rows || []).map(r => ({ label: String(r[labelKey] ?? "—"), value: parseFloat(r[valueKey]) || 0 }));
  const total = raw.reduce((s, d) => s + d.value, 0);
  if (!total) return <div style={{ color: "var(--text2)", fontSize: 12 }}>No data</div>;

  // Build SVG arcs
  const cx = 80, cy = 80, r = 68, ri = 40;
  let angle = -Math.PI / 2;
  const slices = raw.map((d, i) => {
    const sweep = (d.value / total) * 2 * Math.PI;
    const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
    angle += sweep;
    const x2 = cx + r * Math.cos(angle), y2 = cy + r * Math.sin(angle);
    const xi1 = cx + ri * Math.cos(angle - sweep), yi1 = cy + ri * Math.sin(angle - sweep);
    const xi2 = cx + ri * Math.cos(angle), yi2 = cy + ri * Math.sin(angle);
    const large = sweep > Math.PI ? 1 : 0;
    const path = `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} L ${xi2} ${yi2} A ${ri} ${ri} 0 ${large} 0 ${xi1} ${yi1} Z`;
    const color = STATUS_COLORS[d.label] || FALLBACK_COLORS[i % FALLBACK_COLORS.length];
    const pct = ((d.value / total) * 100).toFixed(1);
    return { ...d, path, color, pct };
  });

  return (
    <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
      <svg width="160" height="160" viewBox="0 0 160 160" style={{ flexShrink: 0 }}>
        {slices.map((s, i) => (
          <path key={i} d={s.path} fill={s.color} stroke="var(--bg2)" strokeWidth="1.5">
            <title>{s.label}: {s.pct}% ({s.value.toLocaleString()})</title>
          </path>
        ))}
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, justifyContent: "center" }}>
        {slices.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: s.color, flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: "var(--text)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.label}</span>
            <span style={{ fontSize: 11, fontFamily: "'DM Mono', monospace", color: "var(--text)", fontWeight: 600 }}>{s.pct}%</span>
            <span style={{ fontSize: 10, fontFamily: "'DM Mono', monospace", color: "var(--text2)", flex: "0 0 60px", textAlign: "right" }}>{s.value.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── PERM Dashboard panel ──────────────────────────────────────────────────────
function PermPanel({ fy }) {
  const { data: outcomes, loading: l1 } = useQuery("oflc_perm", ["case_status"], null, [{ agg: "count", field: null, label: "Count" }, { agg: "pct_of_total", field: null, label: "Pct" }], [], fy, []);
  const { data: firms, loading: l2 } = useQuery("oflc_perm", ["atty_law_firm"], null, [{ agg: "count", field: null, label: "Count" }], [], fy, []);
  const { data: soc, loading: l3 } = useQuery("oflc_perm", ["soc_code", "soc_title"], null, [{ agg: "count", field: null, label: "Count" }], [], fy, []);
  const { data: employers, loading: l4 } = useQuery("oflc_perm", ["employer_name"], null, [{ agg: "count", field: null, label: "Count" }], [], fy, []);

  // Combine both "Certified-Expired" variants and compute true cert rate
  const certCount = outcomes?.rows
    ?.filter(r => r.case_status?.startsWith("Certified"))
    .reduce((s, r) => s + (parseFloat(r.Count) || 0), 0) ?? 0;
  const deniedRow = outcomes?.rows?.find(r => r.case_status === "Denied");
  const total = outcomes?.grand_total?.Count ?? 0;
  const certPct = total ? ((certCount / total) * 100).toFixed(1) : "—";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <KPI label="Total Filings" value={total?.toLocaleString() ?? "—"} color="var(--amber)" />
        <KPI label="All Certified" value={certPct !== "—" ? `${certPct}%` : "—"} color="var(--green)" sub={`${certCount.toLocaleString()} cases (incl. expired)`} />
        <KPI label="Denied" value={deniedRow ? `${parseFloat(deniedRow.Pct).toFixed(1)}%` : "—"} color="var(--red)" sub={deniedRow?.Count?.toLocaleString()} />
        <KPI label="Unique Firms" value={firms?.total_rows?.toLocaleString() ?? "—"} color="var(--amber)" />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
        <Widget title="Case Outcomes" subtitle="All statuses" loading={l1} color="var(--amber)">
          <PieChart rows={outcomes?.rows} labelKey="case_status" valueKey="Count" />
        </Widget>
        <Widget title="Top Law Firms" subtitle="by filing volume" loading={l2} color="var(--amber)">
          <MiniBar rows={firms?.rows} labelKey="atty_law_firm" valueKey="Count" color="var(--amber)" />
        </Widget>
        <Widget title="Top Employers" subtitle="by filing volume" loading={l4} color="var(--amber)">
          <MiniBar rows={employers?.rows} labelKey="employer_name" valueKey="Count" color="var(--amber)" />
        </Widget>
      </div>
      <Widget title="Top SOC Codes Filed" subtitle="by volume" loading={l3} color="var(--amber)">
        <MiniBar rows={soc?.rows} labelKey="soc_code" valueKey="Count" color="var(--amber)" horizontal={false} maxRows={20} />
      </Widget>
    </div>
  );
}

// ── LCA Dashboard panel ───────────────────────────────────────────────────────
function LcaPanel({ fy }) {
  const { data: outcomes, loading: l1 } = useQuery("oflc_lca", ["case_status"], null, [{ agg: "count", field: null, label: "Count" }, { agg: "pct_of_total", field: null, label: "Pct" }], [], fy, []);
  const { data: visaClass, loading: l2 } = useQuery("oflc_lca", ["visa_class"], null, [{ agg: "count", field: null, label: "Count" }], [], fy, []);
  const { data: firms, loading: l3 } = useQuery("oflc_lca", ["law_firm_name"], null, [{ agg: "count", field: null, label: "Count" }], [], fy, []);
  const { data: wageLevels, loading: l4 } = useQuery("oflc_lca", ["pw_wage_level"], null, [{ agg: "count", field: null, label: "Count" }, { agg: "pct_of_total", field: null, label: "Pct" }], [], fy, []);

  const certRow = outcomes?.rows?.find(r => r.case_status === "Certified");
  const total = outcomes?.grand_total?.Count;
  const certPct = total && certRow ? ((parseFloat(certRow.Count) / total) * 100).toFixed(1) : "—";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <KPI label="Total LCAs" value={total?.toLocaleString() ?? "—"} color="var(--blue)" />
        <KPI label="Certified" value={`${certPct}%`} color="var(--green)" sub={certRow?.Count?.toLocaleString()} />
        <KPI label="Visa Classes" value={visaClass?.total_rows ?? "—"} color="var(--blue)" />
        <KPI label="Unique Firms" value={firms?.total_rows?.toLocaleString() ?? "—"} color="var(--blue)" />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
        <Widget title="Case Outcomes" loading={l1} color="var(--blue)">
          <PieChart rows={outcomes?.rows} labelKey="case_status" valueKey="Count" />
        </Widget>
        <Widget title="By Visa Class" loading={l2} color="var(--blue)">
          <MiniBar rows={visaClass?.rows} labelKey="visa_class" valueKey="Count" color="var(--blue)" />
        </Widget>
        <Widget title="PW Wage Levels" subtitle="% distribution" loading={l4} color="var(--blue)">
          <PieChart rows={wageLevels?.rows} labelKey="pw_wage_level" valueKey="Count" />
        </Widget>
      </div>
      <Widget title="Top Law Firms" subtitle="by LCA volume" loading={l3} color="var(--blue)">
        <MiniBar rows={firms?.rows} labelKey="law_firm_name" valueKey="Count" color="var(--blue)" />
      </Widget>
    </div>
  );
}

// ── PW Dashboard panel ────────────────────────────────────────────────────────
function PwPanel({ fy }) {
  const { data: wageLevels, loading: l1 } = useQuery("oflc_pw", ["pw_wage_level"], null, [{ agg: "count", field: null, label: "Count" }, { agg: "pct_of_total", field: null, label: "Pct" }], [], fy, []);
  const { data: wageSrc, loading: l2 } = useQuery("oflc_pw", ["wage_source"], null, [{ agg: "count", field: null, label: "Count" }, { agg: "pct_of_total", field: null, label: "Pct" }], [], fy, []);
  const { data: firms, loading: l3 } = useQuery("oflc_pw", ["law_firm_name"], null, [{ agg: "count", field: null, label: "Count" }], [], fy, []);
  const { data: topSoc, loading: l4 } = useQuery("oflc_pw", ["suggested_soc_code", "suggested_soc_title"], null, [{ agg: "count", field: null, label: "Count" }], [], fy, []);

  const total = wageLevels?.grand_total?.Count;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <KPI label="Total PWDs" value={total?.toLocaleString() ?? "—"} color="var(--green)" />
        <KPI label="OES Usage" value={wageSrc?.rows?.find(r => r.wage_source === "OES")?.Pct ? `${wageSrc.rows.find(r => r.wage_source === "OES").Pct}%` : "—"} color="var(--green)" sub="of all PWDs" />
        <KPI label="Unique Firms" value={firms?.total_rows?.toLocaleString() ?? "—"} color="var(--green)" />
        <KPI label="SOC Codes" value={topSoc?.total_rows?.toLocaleString() ?? "—"} color="var(--green)" sub="suggested" />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
        <Widget title="Wage Level Distribution" subtitle="Level I–IV" loading={l1} color="var(--green)">
          <PieChart rows={wageLevels?.rows} labelKey="pw_wage_level" valueKey="Count" />
        </Widget>
        <Widget title="Wage Source Usage" subtitle="OES vs alternatives" loading={l2} color="var(--green)">
          <PieChart rows={wageSrc?.rows} labelKey="wage_source" valueKey="Count" />
        </Widget>
        <Widget title="Top Law Firms" subtitle="by PWD volume" loading={l3} color="var(--green)">
          <MiniBar rows={firms?.rows} labelKey="law_firm_name" valueKey="Count" color="var(--green)" />
        </Widget>
      </div>
      <Widget title="Top Suggested SOC Codes" subtitle="by volume" loading={l4} color="var(--green)">
        <MiniBar rows={topSoc?.rows} labelKey="suggested_soc_code" valueKey="Count" color="var(--green)" horizontal={false} maxRows={20} />
      </Widget>
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export function OflcDashboard({ onBack }) {
  const [program, setProgram] = useState("perm");
  const [fy, setFy] = useState("All");

  const PROGRAMS = [
    { id: "perm", label: "PERM", color: "var(--amber)" },
    { id: "lca",  label: "LCA (H-1B)", color: "var(--blue)" },
    { id: "pw",   label: "Prevailing Wage", color: "var(--green)" },
  ];
  const activeColor = PROGRAMS.find(p => p.id === program)?.color || "var(--amber)";

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "10px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0, display: "flex", alignItems: "center", gap: 12 }}>
        <button onClick={onBack} style={{ background: "none", border: "1px solid var(--border)", fontSize: 11, padding: "3px 10px", height: "auto", color: "var(--text3)" }}>← Back</button>
        <div style={{ width: 1, height: 16, background: "var(--border)" }} />
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase" }}>Dashboard</span>

        {/* Program toggle */}
        <div style={{ display: "flex", gap: 3, marginLeft: 8 }}>
          {PROGRAMS.map(p => (
            <button key={p.id} onClick={() => setProgram(p.id)} style={{
              padding: "4px 12px", height: "auto", fontSize: 12, borderRadius: 4,
              background: program === p.id ? `${p.color}18` : "var(--bg3)",
              color: program === p.id ? p.color : "var(--text3)",
              border: `1px solid ${program === p.id ? p.color + "44" : "var(--border)"}`,
              fontWeight: program === p.id ? 600 : 400,
            }}>{p.label}</button>
          ))}
        </div>

        <div style={{ flex: 1 }} />

        {/* FY filter */}
        <span style={{ fontSize: 11, color: "var(--text3)" }}>Fiscal Year:</span>
        <div style={{ display: "flex", gap: 2 }}>
          {FISCAL_YEARS.map(f => (
            <button key={f} onClick={() => setFy(f)} style={{
              padding: "3px 8px", height: "auto", fontSize: 11, borderRadius: 3,
              background: fy === f ? `${activeColor}18` : "var(--bg3)",
              color: fy === f ? activeColor : "var(--text3)",
              border: `1px solid ${fy === f ? activeColor + "44" : "var(--border)"}`,
              fontWeight: fy === f ? 600 : 400,
            }}>{f}</button>
          ))}
        </div>
      </div>

      {/* Panel */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        {program === "perm" && <PermPanel fy={fy} />}
        {program === "lca"  && <LcaPanel  fy={fy} />}
        {program === "pw"   && <PwPanel   fy={fy} />}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
