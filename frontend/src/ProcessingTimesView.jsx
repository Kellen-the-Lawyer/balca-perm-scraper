import { useEffect, useState } from "react";
import { API } from "./apiBase";

const COLORS = ["var(--amber)", "var(--blue)", "var(--green)", "#a78bfa"];

function useJson(url) {
  const [state, setState] = useState({ url: null, data: null, loading: true, error: null });
  useEffect(() => {
    let active = true;
    fetch(url).then(async response => {
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || "Unable to load data");
      return response.json();
    }).then(data => active && setState({ url, data, loading: false, error: null }))
      .catch(error => active && setState({ url, data: null, loading: false, error: error.message }));
    return () => { active = false; };
  }, [url]);
  return state.url === url ? state : { url, data: null, loading: true, error: null };
}

const fmtDate = value => value ? new Date(`${value}T12:00:00`).toLocaleDateString("en-US", { month: "short", year: "numeric" }) : "—";
const fmtValue = (value, unit) => unit === "proportion" ? `${(Number(value) * 100).toFixed(1)}%` : Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 });
const fmtFiscalQuarter = value => {
  if (!value) return "—";
  const date = new Date(`${value}T12:00:00`), month = date.getMonth(), year = date.getFullYear();
  const quarter = month >= 9 ? 1 : month >= 6 ? 4 : month >= 3 ? 3 : 2;
  const fiscalYear = month >= 9 ? year + 1 : year;
  return `FY${String(fiscalYear).slice(-2)} Q${quarter}`;
};

function BackButton({ onBack, label }) {
  return <button onClick={onBack} style={{ border: 0, background: "transparent", color: "var(--text2)", cursor: "pointer", padding: 0, fontSize: 12 }}>← {label}</button>;
}

function Segmented({ value, onChange, options }) {
  return <div style={{ display: "inline-flex", flexWrap: "wrap", padding: 3, border: "1px solid var(--border)", borderRadius: 8, background: "var(--bg3)" }}>
    {options.map(option => <button key={option.value} onClick={() => onChange(option.value)} style={{ border: 0, borderRadius: 6, padding: "7px 13px", cursor: "pointer", fontSize: 11, fontWeight: value === option.value ? 600 : 400, color: value === option.value ? "var(--text)" : "var(--text3)", background: value === option.value ? "var(--bg2)" : "transparent", boxShadow: value === option.value ? "0 1px 4px #0002" : "none" }}>{option.label}</button>)}
  </div>;
}

function LineChart({ points, lines, unit, height = 280 }) {
  const width = 960, pad = { left: 56, right: 22, top: 18, bottom: 38 };
  const valid = points.filter(point => lines.some(line => Number.isFinite(Number(point[line.key]))));
  if (!valid.length) return <div style={{ height, display: "grid", placeItems: "center", color: "var(--text3)", fontSize: 12 }}>No observations for this selection.</div>;
  const values = valid.flatMap(point => lines.map(line => Number(point[line.key])).filter(Number.isFinite));
  const minValue = Math.min(0, ...values), maxValue = Math.max(...values) || 1;
  const x = index => pad.left + index * (width - pad.left - pad.right) / Math.max(1, valid.length - 1);
  const y = value => pad.top + (maxValue - value) * (height - pad.top - pad.bottom) / Math.max(1, maxValue - minValue);
  const ticks = [0, .25, .5, .75, 1].map(f => minValue + (maxValue - minValue) * f);
  const labelIndexes = [...new Set([0, Math.floor((valid.length - 1) / 2), valid.length - 1])];
  return <div style={{ width: "100%", overflowX: "auto" }}>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Historical values in ${unit}`} style={{ width: "100%", minWidth: 620, display: "block" }}>
      {ticks.map((tick, index) => <g key={index}>
        <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} stroke="var(--border)" strokeDasharray="3 5" />
        <text x={pad.left - 9} y={y(tick) + 4} textAnchor="end" fill="var(--text3)" fontSize="10">{unit === "proportion" ? `${Math.round(tick * 100)}%` : tick.toFixed(maxValue < 20 ? 1 : 0)}</text>
      </g>)}
      {lines.map((line, lineIndex) => {
        const path = valid.map((point, index) => `${index ? "L" : "M"}${x(index)},${y(Number(point[line.key]))}`).join(" ");
        return <g key={line.key}>
          <path d={path} fill="none" stroke={line.color || COLORS[lineIndex]} strokeWidth="2.25" strokeLinejoin="round" />
          {valid.map((point, index) => <circle key={index} cx={x(index)} cy={y(Number(point[line.key]))} r={valid.length < 20 ? 3 : 1.8} fill={line.color || COLORS[lineIndex]}><title>{`${fmtDate(point.period_start)}: ${fmtValue(point[line.key], unit)} ${unit === "proportion" ? "" : unit}`}</title></circle>)}
        </g>;
      })}
      {labelIndexes.map(index => <text key={index} x={x(index)} y={height - 12} textAnchor={index === 0 ? "start" : index === valid.length - 1 ? "end" : "middle"} fill="var(--text3)" fontSize="10">{fmtDate(valid[index].period_start)}</text>)}
    </svg>
    <div style={{ display: "flex", gap: 18, justifyContent: "center", flexWrap: "wrap", marginTop: -4 }}>
      {lines.map((line, index) => <span key={line.key} style={{ fontSize: 11, color: "var(--text2)", display: "flex", alignItems: "center", gap: 6 }}><i style={{ width: 14, height: 2, background: line.color || COLORS[index], display: "inline-block" }} />{line.label}</span>)}
    </div>
  </div>;
}

function MultiSeriesChart({ series, unit = "months", height = 300 }) {
  const width = 960, pad = { left: 56, right: 22, top: 18, bottom: 38 };
  const allPoints = series.flatMap(item => item.points.map(point => ({ ...point, seriesKey: item.series_key })));
  if (!allPoints.length) return <div style={{ height, display: "grid", placeItems: "center", color: "var(--text3)", fontSize: 12 }}>No historical observations available.</div>;
  const dates = [...new Set(allPoints.map(point => point.period_start))].sort();
  const dateIndex = new Map(dates.map((date, index) => [date, index]));
  const maxValue = Math.max(...allPoints.map(point => Number(point.value))) || 1;
  const x = date => pad.left + dateIndex.get(date) * (width - pad.left - pad.right) / Math.max(1, dates.length - 1);
  const y = value => pad.top + (maxValue - value) * (height - pad.top - pad.bottom) / maxValue;
  const ticks = [0, .25, .5, .75, 1].map(fraction => maxValue * fraction);
  const labelDates = [dates[0], dates[Math.floor((dates.length - 1) / 2)], dates[dates.length - 1]];
  return <div style={{ width: "100%", overflowX: "auto" }}>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="USCIS historical processing-time comparison" style={{ width: "100%", minWidth: 620, display: "block" }}>
      {ticks.map(tick => <g key={tick}>
        <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} stroke="var(--border)" strokeDasharray="3 5" />
        <text x={pad.left - 9} y={y(tick) + 4} textAnchor="end" fill="var(--text3)" fontSize="10">{tick.toFixed(maxValue < 20 ? 1 : 0)}</text>
      </g>)}
      {series.map((item, index) => {
        const color = COLORS[index % COLORS.length];
        const path = item.points.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${x(point.period_start)},${y(Number(point.value))}`).join(" ");
        return <g key={item.series_key}>
          <path d={path} fill="none" stroke={color} strokeWidth="2.2" strokeLinejoin="round" />
          {item.points.map(point => <circle key={point.period_start} cx={x(point.period_start)} cy={y(Number(point.value))} r="2" fill={color}><title>{`${item.series_label} · ${fmtDate(point.period_start)}: ${fmtValue(point.value, unit)} ${unit}`}</title></circle>)}
        </g>;
      })}
      {labelDates.map((date, index) => <text key={date} x={x(date)} y={height - 12} textAnchor={index === 0 ? "start" : index === 2 ? "end" : "middle"} fill="var(--text3)" fontSize="10">{fmtDate(date)}</text>)}
    </svg>
    <div style={{ display: "flex", gap: 16, justifyContent: "center", flexWrap: "wrap", marginTop: -4 }}>
      {series.map((item, index) => <span key={item.series_key} style={{ fontSize: 10, color: "var(--text2)", display: "flex", alignItems: "center", gap: 6 }}><i style={{ width: 14, height: 2, background: COLORS[index % COLORS.length], display: "inline-block" }} />{item.series_label}</span>)}
    </div>
  </div>;
}

function VolumeChart({ points, height = 210 }) {
  const width = 960, pad = { left: 62, right: 22, top: 15, bottom: 36 };
  if (!points?.length) return null;
  const maxValue = Math.max(...points.map(point => Number(point.case_count))) || 1;
  const chartWidth = width - pad.left - pad.right;
  const barWidth = Math.max(1.5, chartWidth / points.length - 1);
  const x = index => pad.left + index * chartWidth / points.length;
  const y = value => pad.top + (maxValue - value) * (height - pad.top - pad.bottom) / maxValue;
  const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  return <div style={{ width: "100%", overflowX: "auto" }}><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Completed case volume by month" style={{ width: "100%", minWidth: 620, display: "block" }}>
    {[0, .5, 1].map(fraction => <g key={fraction}><line x1={pad.left} x2={width - pad.right} y1={y(maxValue * fraction)} y2={y(maxValue * fraction)} stroke="var(--border)" /><text x={pad.left - 9} y={y(maxValue * fraction) + 4} textAnchor="end" fill="var(--text3)" fontSize="10">{Math.round(maxValue * fraction).toLocaleString()}</text></g>)}
    {points.map((point, index) => <rect key={point.period_start} x={x(index)} y={y(Number(point.case_count))} width={barWidth} height={height - pad.bottom - y(Number(point.case_count))} fill="var(--green)" opacity=".72"><title>{`${fmtDate(point.period_start)}: ${Number(point.case_count).toLocaleString()} completed cases`}</title></rect>)}
    {labelIndexes.map(index => <text key={index} x={x(index)} y={height - 11} textAnchor={index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"} fill="var(--text3)" fontSize="10">{fmtDate(points[index].period_start)}</text>)}
  </svg></div>;
}

function Panel({ children, style }) {
  return <section style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 20, ...style }}>{children}</section>;
}

function DolView() {
  const [program, setProgram] = useState("perm");
  const [visaClass, setVisaClass] = useState("");
  const query = new URLSearchParams({ program });
  if (visaClass) query.set("visa_class", visaClass);
  const { data, loading, error } = useJson(`${API}/processing-times/dol?${query}`);
  const latest = data?.points?.[data.points.length - 1];
  return <>
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
      <select value={program} onChange={event => { setProgram(event.target.value); setVisaClass(""); }} style={selectStyle}>
        <option value="perm">PERM</option><option value="pw">Prevailing Wage</option><option value="lca">LCA</option>
      </select>
      {!!data?.visa_classes?.length && <select value={visaClass} onChange={event => setVisaClass(event.target.value)} style={selectStyle}>
        <option value="">All visa classes</option>{data.visa_classes.map(item => <option key={item.visa_class} value={item.visa_class}>{item.visa_class} ({item.count.toLocaleString()})</option>)}
      </select>}
    </div>
    {loading && <Loading />}{error && <ErrorText message={error} />}
    {data && <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 12 }}>
        <Stat label="Latest monthly median" value={latest ? `${latest.median} days` : "—"} color="var(--amber)" />
        <Stat label="75% completed within" value={latest ? `${latest.p75} days` : "—"} color="var(--blue)" />
        <Stat label="90% completed within" value={latest ? `${latest.p90} days` : "—"} color="#a78bfa" />
        <Stat label="Completed cases" value={latest?.case_count?.toLocaleString() || "—"} color="var(--green)" />
      </div>
      <Panel>
        <div style={panelTitleStyle}>{data.label} completed-case duration</div>
        <div style={panelSubStyle}>{data.methodology}</div>
        <LineChart points={data.points} unit="days" lines={[{ key: "median", label: "Median", color: "var(--amber)" }, { key: "p75", label: "75th percentile", color: "var(--blue)" }, { key: "p90", label: "90th percentile", color: "#a78bfa" }]} />
      </Panel>
      <Panel>
        <div style={panelTitleStyle}>Completed case volume by month</div>
        <div style={panelSubStyle}>Volume gives essential context for the duration trend: unusually high or low completion months can change the monthly percentiles.</div>
        <VolumeChart points={data.points} />
      </Panel>
    </>}
  </>;
}

const CLASS_LABELS = { "H-1B": "H-1B", "O": "O extraordinary ability", "L-1A": "L-1A manager/executive", "L-1B": "L-1B specialized knowledge", "P": "P athletes/entertainers", "R-1": "R-1 religious worker", "TN": "TN professional", "H-2A": "H-2A", "H-2B": "H-2B", "Blanket L": "Blanket L" };

function I129Detail() {
  const [classification, setClassification] = useState("H-1B");
  const [metric, setMetric] = useState("rfe_rate");
  const current = useJson(`${API}/processing-times/uscis/i129/current`);
  const history = useJson(`${API}/processing-times/uscis/i129/history`);
  const context = useJson(`${API}/processing-times/uscis/i129/context?classification=${encodeURIComponent(classification)}&metric=${metric}`);
  const selectedCurrent = current.data?.filter(item => classification === "H-1B" ? item.classification.startsWith("137-H1B") : item.classification === `137-${classification}`) || [];
  const latestContext = context.data?.points?.[context.data.points.length - 1];
  return <>
    <Panel style={{ borderColor: "#a78bfa55" }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#a78bfa", textTransform: "uppercase", letterSpacing: ".09em" }}>Choose petition type</div>
      <div style={{ ...panelSubStyle, marginBottom: 12 }}>Select the I-129 classification you want to examine. The processing snapshot and historical outcome chart below will update together.</div>
      <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
        {(context.data?.classifications || Object.keys(CLASS_LABELS)).map(item => <button key={item} onClick={() => setClassification(item)} style={{ padding: "8px 11px", borderRadius: 7, cursor: "pointer", border: `1px solid ${classification === item ? "#a78bfa" : "var(--border)"}`, background: classification === item ? "#a78bfa20" : "var(--bg3)", color: classification === item ? "#c4b5fd" : "var(--text2)", fontSize: 11, fontWeight: classification === item ? 650 : 450 }}>{CLASS_LABELS[item] || item}</button>)}
      </div>
    </Panel>
    {history.loading && <Loading />}{history.error && <ErrorText message={history.error} />}
    {!!history.data?.length && <Panel>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div><div style={panelTitleStyle}>Historical I-129 processing time</div><div style={panelSubStyle}>Quarterly median for all completed I-129 petitions. USCIS does not identify H-1B and O separately in this historical series, so the category-specific current snapshot remains above.</div></div>
        <div style={{ textAlign: "right" }}><div style={{ fontSize: 10, color: "var(--text3)" }}>Latest overall median</div><div style={{ fontSize: 20, fontWeight: 650, color: "var(--amber)", fontFamily: "'DM Mono',monospace" }}>{history.data[history.data.length - 1].value.toFixed(1)} months</div></div>
      </div>
      <LineChart points={history.data} unit="months" lines={[{ key: "value", label: "I-129 median", color: "var(--amber)" }]} />
    </Panel>}
    <Panel style={{ borderColor: "#a78bfa55", background: "linear-gradient(135deg,var(--bg2),#a78bfa08)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div><div style={panelTitleStyle}>I-129 is not one processing time</div><div style={panelSubStyle}>USCIS publishes current estimates by petition category. These are the time in which 80% of non-premium cases were completed over the prior six months.</div></div>
        <span style={{ fontSize: 10, padding: "5px 8px", borderRadius: 999, color: "#a78bfa", background: "#a78bfa16", border: "1px solid #a78bfa33" }}>Official USCIS snapshot · Jul. 16, 2026</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(190px,1fr))", gap: 10, marginTop: 16 }}>
        {current.loading && <Loading />}{current.error && <ErrorText message={current.error} />}
        {selectedCurrent.map(item => <div key={item.series_key} style={{ padding: 14, borderRadius: 8, border: "1px solid var(--border)", background: "var(--bg3)" }}>
          <div style={{ color: "var(--text3)", fontSize: 10, lineHeight: 1.4, minHeight: 28 }}>{item.series_label}</div>
          <div style={{ color: "var(--text)", fontSize: 24, fontWeight: 650, marginTop: 6, fontFamily: "'DM Mono',monospace" }}>{item.value}<span style={{ fontSize: 11, color: "var(--text3)", marginLeft: 5 }}>months</span></div>
        </div>)}
        {!current.loading && !current.error && !selectedCurrent.length && <div style={{ padding: 14, color: "var(--text3)", fontSize: 11, lineHeight: 1.55 }}>A current category-specific USCIS processing-time snapshot is not available in our dataset for this petition type. Historical outcome data is available below.</div>}
      </div>
    </Panel>
    <div><div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 7 }}>Choose historical measure</div>
      <Segmented value={metric} onChange={setMetric} options={[{ value: "rfe_rate", label: "RFE rate" }, { value: "approval_rate", label: "Approval rate" }, { value: "denial_rate", label: "Denial rate" }, { value: "received", label: "Petitions received" }, { value: "completed", label: "Completions" }]} />
    </div>
    {context.loading && <Loading />}{context.error && <ErrorText message={context.error} />}
    {!!context.data?.points?.length && <Panel>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div><div style={panelTitleStyle}>{CLASS_LABELS[classification] || classification} historical context</div><div style={panelSubStyle}>Classification-specific USCIS monthly data. This is workload and adjudication context—not a substitute for a historical processing-time series.</div></div>
        <div style={{ textAlign: "right" }}><div style={{ fontSize: 10, color: "var(--text3)" }}>Latest observation</div><div style={{ fontSize: 19, fontWeight: 650, color: "var(--blue)", fontFamily: "'DM Mono',monospace" }}>{fmtValue(latestContext.value, latestContext.unit)}{latestContext.unit === "cases" ? " cases" : ""}</div></div>
      </div>
      <LineChart points={context.data.points} unit={latestContext.unit} lines={[{ key: "value", label: metric.replaceAll("_", " "), color: "var(--blue)" }]} />
      {context.data.methodology && <div style={{ marginTop: 12, fontSize: 10, color: "var(--text3)" }}>{context.data.methodology}</div>}
      {!!selectedCurrent.length && <div style={{ marginTop: 15, paddingTop: 14, borderTop: "1px solid var(--border)", fontSize: 11, color: "var(--text2)" }}>Current category estimate: {selectedCurrent.map(item => `${item.series_label}: ${item.value} months`).join(" · ")}</div>}
    </Panel>}
  </>;
}

const I140_LABELS = {
  "EB-1 (all)": "EB-1 overall", "EB-1A": "EB-1A extraordinary ability",
  "EB-1B": "EB-1B professor/researcher", "EB-1C": "EB-1C multinational manager",
  "EB-2 (all)": "EB-2 overall", "EB-2 (non-NIW)": "EB-2 advanced degree",
  "EB-2 NIW": "EB-2 National Interest Waiver", "EB-3 (all)": "EB-3 overall",
  "EB-3 Skilled": "EB-3 skilled worker", "EB-3 Professional": "EB-3 professional",
  "EB-3 Other Workers": "EB-3 other workers",
};

function I140Detail() {
  const [classification, setClassification] = useState("EB-2 NIW");
  const context = useJson(`${API}/processing-times/uscis/i140/context?classification=${encodeURIComponent(classification)}`);
  const history = useJson(`${API}/processing-times/uscis/i140/history`);
  const points = context.data?.points || [];
  const latest = points[points.length - 1];
  const categories = context.data?.classifications || Object.keys(I140_LABELS);
  return <>
    <Panel style={{ borderColor: "#a78bfa55" }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#a78bfa", textTransform: "uppercase", letterSpacing: ".09em" }}>Choose employment-based category</div>
      <div style={{ ...panelSubStyle, marginBottom: 12 }}>The category selection controls every workload, inventory, and decision-outcome chart below.</div>
      <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
        {categories.map(item => <button key={item} onClick={() => setClassification(item)} style={{ padding: "8px 11px", borderRadius: 7, cursor: "pointer", border: `1px solid ${classification === item ? "#a78bfa" : "var(--border)"}`, background: classification === item ? "#a78bfa20" : "var(--bg3)", color: classification === item ? "#c4b5fd" : "var(--text2)", fontSize: 11, fontWeight: classification === item ? 650 : 450 }}>{I140_LABELS[item] || item}</button>)}
      </div>
    </Panel>

    {context.loading && <Loading />}{context.error && <ErrorText message={context.error} />}
    {latest && <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <div><div style={panelTitleStyle}>{I140_LABELS[classification] || classification}</div><div style={panelSubStyle}>Latest quarter: {fmtFiscalQuarter(latest.period_start)}</div></div>
        {context.data.premium_processing_business_days && <span style={{ fontSize: 10, color: "var(--text2)", border: "1px solid var(--border)", borderRadius: 999, padding: "5px 9px", background: "var(--bg3)" }}>Premium processing: USCIS action within {context.data.premium_processing_business_days} business days</span>}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 12 }}>
        <Stat label="Received" value={Number(latest.received).toLocaleString()} color="var(--blue)" />
        <Stat label="Approved" value={Number(latest.approved).toLocaleString()} color="var(--green)" />
        <Stat label="Denied" value={Number(latest.denied).toLocaleString()} color="var(--amber)" />
        <Stat label="Pending at quarter end" value={Number(latest.pending).toLocaleString()} color="#a78bfa" />
      </div>
      <Panel>
        <div style={panelTitleStyle}>Quarterly I-140 workload and decisions</div>
        <div style={panelSubStyle}>Petitions received and adjudicative actions taken during each quarter.</div>
        <LineChart points={points} unit="cases" lines={[{ key: "received", label: "Received", color: "var(--blue)" }, { key: "approved", label: "Approved", color: "var(--green)" }, { key: "denied", label: "Denied", color: "var(--amber)" }]} />
      </Panel>
      <Panel>
        <div style={panelTitleStyle}>Pending inventory</div>
        <div style={panelSubStyle}>Petitions awaiting a decision at the end of each quarter. Pending counts cannot be reconstructed by adding and subtracting quarterly actions because USCIS also transfers and administratively closes cases.</div>
        <LineChart points={points} unit="cases" lines={[{ key: "pending", label: "Pending", color: "#a78bfa" }]} />
      </Panel>
      <Panel>
        <div style={panelTitleStyle}>Share of quarterly decisions</div>
        <div style={panelSubStyle}>Approval and denial shares among cases decided during the quarter—not the eventual outcome rate of petitions filed in that quarter.</div>
        <LineChart points={points} unit="proportion" lines={[{ key: "decision_approval_rate", label: "Approval share", color: "var(--green)" }, { key: "decision_denial_rate", label: "Denial share", color: "var(--amber)" }]} />
        <div style={{ marginTop: 12, fontSize: 10, color: "var(--text3)" }}>{context.data.methodology}</div>
      </Panel>
    </>}

    {history.loading && <Loading />}{history.error && <ErrorText message={history.error} />}
    {!!history.data?.length && <Panel style={{ borderColor: "#a78bfa55", background: "linear-gradient(135deg,var(--bg2),#a78bfa08)" }}>
      <div style={panelTitleStyle}>Overall I-140 historical processing time</div>
      <div style={panelSubStyle}>USCIS publishes this quarterly median for all I-140 categories combined. It provides timing context, but it cannot be attributed to the selected EB category.</div>
      <LineChart points={history.data} unit="months" lines={[{ key: "value", label: "All I-140 median", color: "var(--amber)" }]} />
    </Panel>}
  </>;
}

function UscisOverview() {
  const overview = useJson(`${API}/processing-times/uscis/overview`);
  return <Panel>
    <div style={panelTitleStyle}>USCIS historical processing-time overview</div>
    <div style={panelSubStyle}>Monthly averages for four high-use case types on one scale. Use this overview to spot broad changes, then open “Other USCIS forms” for the complete series list.</div>
    {overview.loading && <Loading />}{overview.error && <ErrorText message={overview.error} />}
    {!!overview.data?.series?.length && <>
      <MultiSeriesChart series={overview.data.series} />
      <div style={{ marginTop: 12, fontSize: 10, color: "var(--text3)" }}>{overview.data.methodology}</div>
    </>}
  </Panel>;
}

function UscisHistory() {
  const options = useJson(`${API}/processing-times/uscis/options`);
  const [seriesKey, setSeriesKey] = useState("");
  const preferred = options.data?.find(item => item.form_type === "I-129") || options.data?.[0];
  const selectedSeriesKey = seriesKey || preferred?.series_key || "";
  const series = useJson(selectedSeriesKey ? `${API}/processing-times/uscis/series?series_key=${encodeURIComponent(selectedSeriesKey)}` : `${API}/processing-times/uscis/options`);
  const points = selectedSeriesKey ? series.data : null;
  const first = points?.[0], latest = points?.[points.length - 1];
  return <>
    {options.loading && <Loading />}{options.error && <ErrorText message={options.error} />}
    {!!options.data?.length && <div><div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 7 }}>Choose USCIS form and case type</div>
    {!!options.data?.length && <select value={selectedSeriesKey} onChange={event => setSeriesKey(event.target.value)} style={{ ...selectStyle, maxWidth: 620, width: "100%" }}>
      {options.data.map(item => <option key={`${item.series_key}:${item.statistic}`} value={item.series_key}>{item.series_label} · {item.statistic} · {item.point_count} points</option>)}
    </select>}</div>}
    {series.loading && <Loading />}{series.error && selectedSeriesKey && <ErrorText message={series.error} />}
    {!!points?.length && <Panel>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div><div style={panelTitleStyle}>{first.series_label}</div><div style={panelSubStyle}>{first.statistic === "median" ? "Median months for cases completed during each quarter." : "Average months for cases completed during each month."}</div></div>
        <div style={{ textAlign: "right" }}><div style={{ fontSize: 10, color: "var(--text3)" }}>Latest</div><div style={{ fontSize: 20, fontWeight: 650, color: "var(--amber)", fontFamily: "'DM Mono',monospace" }}>{latest.value} months</div></div>
      </div>
      <LineChart points={points} unit="months" lines={[{ key: "value", label: first.statistic, color: "var(--amber)" }]} />
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)", fontSize: 10, color: "var(--text3)" }}>Source: {latest.source_name}. Average and median series use different methodologies and are kept separate.</div>
    </Panel>}
  </>;
}

function Stat({ label, value, color }) {
  return <div style={{ padding: 15, background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius)" }}><div style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".06em" }}>{label}</div><div style={{ marginTop: 7, fontSize: 20, fontWeight: 650, color, fontFamily: "'DM Mono',monospace" }}>{value}</div></div>;
}
function Loading() { return <div style={{ padding: 30, color: "var(--text3)", fontSize: 12 }}>Loading processing data…</div>; }
function ErrorText({ message }) { return <div style={{ padding: 14, color: "var(--red,#ef4444)", fontSize: 12, border: "1px solid #ef444444", borderRadius: 8 }}>{message}</div>; }

const selectStyle = { padding: "8px 10px", borderRadius: 7, border: "1px solid var(--border)", background: "var(--bg2)", color: "var(--text)", fontSize: 11 };
const panelTitleStyle = { fontSize: 14, fontWeight: 650, color: "var(--text)" };
const panelSubStyle = { fontSize: 11, color: "var(--text3)", lineHeight: 1.55, marginTop: 5, maxWidth: 720 };

export function ProcessingTimesView({ onBack, backLabel = "DOL data home" }) {
  const [agency, setAgency] = useState("uscis");
  const [uscisTab, setUscisTab] = useState("i129");
  return <div style={{ height: "100%", overflowY: "auto", background: "var(--bg)", padding: "24px clamp(18px,4vw,48px) 48px" }}>
    <div style={{ maxWidth: 1120, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
      <BackButton onBack={onBack} label={backLabel} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 18, flexWrap: "wrap" }}>
        <div><div style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".12em", marginBottom: 8 }}>Agency performance</div><h1 style={{ fontSize: 24, color: "var(--text)", margin: 0 }}>Case processing times</h1><p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--text3)", maxWidth: 680, lineHeight: 1.6 }}>Historical completed-case durations with the methodology, volume, and petition category kept visible.</p></div>
        <Segmented value={agency} onChange={setAgency} options={[{ value: "uscis", label: "USCIS" }, { value: "dol", label: "Department of Labor" }]} />
      </div>
      {agency === "dol" ? <DolView /> : <>
        <UscisOverview />
        <Segmented value={uscisTab} onChange={setUscisTab} options={[{ value: "i129", label: "I-129 by petition type" }, { value: "i140", label: "I-140 by EB category" }, { value: "history", label: "Other USCIS forms" }]} />
        {uscisTab === "i129" ? <I129Detail /> : uscisTab === "i140" ? <I140Detail /> : <UscisHistory />}
      </>}
    </div>
  </div>;
}
