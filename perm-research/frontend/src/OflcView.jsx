import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { OflcLanding } from "./OflcLanding";
import { OflcTemplates } from "./OflcTemplates";
import { OflcDashboard } from "./OflcDashboard";
import { API } from "./apiBase";

// ── Field catalogs per dataset ────────────────────────────────────────────────

const PERM_FIELDS = {
  "Case": [
    { key: "case_status",        label: "Case Status",          type: "text",    agg: false },
    { key: "fiscal_year",        label: "Fiscal Year",          type: "text",    agg: false },
    { key: "occupation_type",    label: "Occupation Type",      type: "text",    agg: false },
    { key: "received_date",      label: "Received Date",        type: "date",    agg: false },
    { key: "decision_date",      label: "Decision Date",        type: "date",    agg: false },
    { key: "case_number",        label: "Case Number",          type: "text",    agg: false },
    { key: "pwd_number",         label: "PWD Number",           type: "text",    agg: false },
  ],
  "Employer": [
    { key: "employer_name",      label: "Employer Name",        type: "text",    agg: false },
    { key: "employer_state",     label: "Employer State",       type: "text",    agg: false },
    { key: "employer_city",      label: "Employer City",        type: "text",    agg: false },
    { key: "employer_fein",      label: "Employer FEIN",        type: "text",    agg: false },
    { key: "employer_naics",     label: "NAICS Code",           type: "text",    agg: false },
    { key: "employer_num_payroll",    label: "# Employees (Payroll)", type: "numeric", agg: true },
    { key: "employer_year_commenced", label: "Year Commenced",  type: "numeric", agg: true },
  ],
  "Attorney / Agent": [
    { key: "atty_law_firm",      label: "Law Firm",             type: "text",    agg: false },
    { key: "atty_last_name",     label: "Attorney Last Name",   type: "text",    agg: false },
    { key: "atty_first_name",    label: "Attorney First Name",  type: "text",    agg: false },
    { key: "atty_state",         label: "Attorney State",       type: "text",    agg: false },
  ],
  "Job / SOC": [
    { key: "job_title",          label: "Job Title",            type: "text",    agg: false },
    { key: "soc_code",           label: "SOC Code",             type: "text",    agg: false },
    { key: "soc_title",          label: "SOC Title",            type: "text",    agg: false },
    { key: "wage_from",          label: "Wage (From)",          type: "numeric", agg: true },
    { key: "wage_to",            label: "Wage (To)",            type: "numeric", agg: true },
    { key: "wage_per",           label: "Wage Per",             type: "text",    agg: false },
  ],
  "Worksite": [
    { key: "worksite_city",      label: "Worksite City",        type: "text",    agg: false },
    { key: "worksite_state",     label: "Worksite State",       type: "text",    agg: false },
    { key: "worksite_postal_code", label: "Worksite ZIP",       type: "text",    agg: false },
    { key: "worksite_bls_area",  label: "BLS Area",             type: "text",    agg: false },
  ],
  "Flags": [
    { key: "fw_currently_employed", label: "FW Currently Employed", type: "text", agg: false },
    { key: "is_multiple_locations", label: "Multiple Locations",    type: "text", agg: false },
    { key: "employer_layoff",       label: "Employer Layoff",       type: "text", agg: false },
  ],
};

const LCA_FIELDS = {
  "Case": [
    { key: "case_status",        label: "Case Status",          type: "text",    agg: false },
    { key: "visa_class",         label: "Visa Class",           type: "text",    agg: false },
    { key: "fiscal_year",        label: "Fiscal Year",          type: "text",    agg: false },
    { key: "received_date",      label: "Received Date",        type: "date",    agg: false },
    { key: "decision_date",      label: "Decision Date",        type: "date",    agg: false },
    { key: "begin_date",         label: "Begin Date",           type: "date",    agg: false },
    { key: "end_date",           label: "End Date",             type: "date",    agg: false },
    { key: "full_time_position", label: "Full Time",            type: "text",    agg: false },
    { key: "total_worker_positions", label: "# Worker Positions", type: "numeric", agg: true },
    { key: "h1b_dependent",      label: "H-1B Dependent",       type: "text",    agg: false },
    { key: "willful_violator",   label: "Willful Violator",     type: "text",    agg: false },
  ],
  "Employer": [
    { key: "employer_name",      label: "Employer Name",        type: "text",    agg: false },
    { key: "employer_state",     label: "Employer State",       type: "text",    agg: false },
    { key: "employer_city",      label: "Employer City",        type: "text",    agg: false },
    { key: "employer_fein",      label: "Employer FEIN",        type: "text",    agg: false },
    { key: "naics_code",         label: "NAICS Code",           type: "text",    agg: false },
  ],
  "Attorney / Agent": [
    { key: "law_firm_name",      label: "Law Firm",             type: "text",    agg: false },
    { key: "agent_last_name",    label: "Agent Last Name",      type: "text",    agg: false },
    { key: "agent_first_name",   label: "Agent First Name",     type: "text",    agg: false },
    { key: "agent_state",        label: "Agent State",          type: "text",    agg: false },
  ],
  "Job / SOC": [
    { key: "job_title",          label: "Job Title",            type: "text",    agg: false },
    { key: "soc_code",           label: "SOC Code",             type: "text",    agg: false },
    { key: "soc_title",          label: "SOC Title",            type: "text",    agg: false },
    { key: "wage_from",          label: "Wage (From)",          type: "numeric", agg: true },
    { key: "wage_to",            label: "Wage (To)",            type: "numeric", agg: true },
    { key: "wage_unit",          label: "Wage Unit",            type: "text",    agg: false },
    { key: "prevailing_wage",    label: "Prevailing Wage",      type: "numeric", agg: true },
    { key: "pw_unit",            label: "PW Unit",              type: "text",    agg: false },
    { key: "pw_wage_level",      label: "PW Wage Level",        type: "text",    agg: false },
    { key: "pw_oes_year",        label: "PW OES Year",          type: "text",    agg: false },
  ],
  "Worksite": [
    { key: "worksite_city",      label: "Worksite City",        type: "text",    agg: false },
    { key: "worksite_state",     label: "Worksite State",       type: "text",    agg: false },
    { key: "worksite_postal_code", label: "Worksite ZIP",       type: "text",    agg: false },
  ],
};

const PW_FIELDS = {
  "Case": [
    { key: "case_status",        label: "Case Status",          type: "text",    agg: false },
    { key: "visa_class",         label: "Visa Class",           type: "text",    agg: false },
    { key: "fiscal_year",        label: "Fiscal Year",          type: "text",    agg: false },
    { key: "received_date",      label: "Received Date",        type: "date",    agg: false },
    { key: "determination_date", label: "Determination Date",   type: "date",    agg: false },
  ],
  "Employer": [
    { key: "employer_name",      label: "Employer Name",        type: "text",    agg: false },
    { key: "employer_state",     label: "Employer State",       type: "text",    agg: false },
    { key: "employer_city",      label: "Employer City",        type: "text",    agg: false },
    { key: "employer_fein",      label: "Employer FEIN",        type: "text",    agg: false },
    { key: "naics_code",         label: "NAICS Code",           type: "text",    agg: false },
  ],
  "Attorney / Agent": [
    { key: "law_firm_name",      label: "Law Firm",             type: "text",    agg: false },
    { key: "agent_last_name",    label: "Agent Last Name",      type: "text",    agg: false },
    { key: "agent_first_name",   label: "Agent First Name",     type: "text",    agg: false },
  ],
  "Job / SOC": [
    { key: "job_title",                label: "Job Title",                type: "text",    agg: false },
    { key: "soc_code",                 label: "SOC Code (PWD)",           type: "text",    agg: false },
    { key: "soc_title",                label: "SOC Title (PWD)",          type: "text",    agg: false },
    { key: "suggested_soc_code",       label: "Suggested SOC Code",       type: "text",    agg: false },
    { key: "suggested_soc_title",      label: "Suggested SOC Title",      type: "text",    agg: false },
    { key: "pwd_soc_code",             label: "PWD SOC Code",             type: "text",    agg: false },
    { key: "pwd_soc_title",            label: "PWD SOC Title",            type: "text",    agg: false },
    { key: "emp_soc_codes",            label: "Employer SOC Codes",       type: "text",    agg: false },
    { key: "emp_soc_titles",           label: "Employer SOC Titles",      type: "text",    agg: false },
    { key: "o_net_code",               label: "O*NET Code",               type: "text",    agg: false },
    { key: "o_net_title",              label: "O*NET Title",              type: "text",    agg: false },
    { key: "pw_wage_level",            label: "PW Wage Level",            type: "text",    agg: false },
    { key: "pwd_wage_rate",            label: "PWD Wage Rate",            type: "numeric", agg: true },
    { key: "pwd_unit",                 label: "PWD Unit",                 type: "text",    agg: false },
    { key: "wage_source",              label: "Wage Source",              type: "text",    agg: false },
    { key: "wage_source_requested",    label: "Wage Source Requested",    type: "text",    agg: false },
    { key: "survey_name",              label: "Survey Name",              type: "text",    agg: false },
    { key: "bls_area",                 label: "BLS Area",                 type: "text",    agg: false },
    { key: "pwd_wage_expiration_date", label: "PWD Expiration",           type: "date",    agg: false },
    { key: "alt_pwd_wage_rate",        label: "Alt PWD Wage Rate",        type: "numeric", agg: true },
    { key: "alt_pwd_unit",             label: "Alt PWD Unit",             type: "text",    agg: false },
    { key: "alt_pwd_wage_level",       label: "Alt PWD Wage Level",       type: "text",    agg: false },
    { key: "alt_pwd_wage_source",      label: "Alt PWD Wage Source",      type: "text",    agg: false },
  ],
  "Worksite": [
    { key: "worksite_city",      label: "Worksite City",        type: "text",    agg: false },
    { key: "worksite_state",     label: "Worksite State",       type: "text",    agg: false },
    { key: "worksite_postal_code", label: "Worksite ZIP",       type: "text",    agg: false },
  ],
};

const DATASET_CONFIG = {
  perm: { label: "PERM",           table: "oflc_perm", fields: PERM_FIELDS, color: "var(--amber)",  dateField: "decision_date" },
  lca:  { label: "LCA (H-1B)",     table: "oflc_lca",  fields: LCA_FIELDS,  color: "var(--blue)",   dateField: "decision_date" },
  pw:   { label: "Prevailing Wage", table: "oflc_pw",   fields: PW_FIELDS,   color: "var(--green)",  dateField: "determination_date" },
};

const AGGREGATIONS = [
  { key: "count",          label: "Count",          numeric: false },
  { key: "count_distinct", label: "Count Distinct", numeric: false },
  { key: "sum",            label: "Sum",            numeric: true  },
  { key: "avg",            label: "Average",        numeric: true  },
  { key: "min",            label: "Min",            numeric: true  },
  { key: "max",            label: "Max",            numeric: true  },
  { key: "pct_of_total",   label: "% of Total",     numeric: false },
];

const SOC_FIELDS = new Set(["soc_code","suggested_soc_code","pwd_soc_code","emp_soc_codes","o_net_code"]);
const DEFAULT_OP = (fieldKey) => SOC_FIELDS.has(fieldKey) ? "=" : "ILIKE";

function flatFields(fields) {
  return Object.values(fields).flat();
}
function fieldByKey(fields, key) {
  return flatFields(fields).find(f => f.key === key);
}

// ── Spinner ───────────────────────────────────────────────────────────────────
function Spinner({ small }) {
  return (
    <div style={{ padding: small ? "8px" : "40px 20px", display: "flex", justifyContent: "center", alignItems: "center" }}>
      <div style={{
        width: small ? 14 : 20, height: small ? 14 : 20,
        border: "2px solid var(--border2)", borderTopColor: "var(--amber)",
        borderRadius: "50%", animation: "spin 0.7s linear infinite",
      }} />
    </div>
  );
}

// ── Chip ──────────────────────────────────────────────────────────────────────
function Chip({ label, onRemove, color = "var(--amber)", badge }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      background: `${color}18`, border: `1px solid ${color}44`,
      color, fontSize: 11, fontWeight: 500,
      padding: "3px 8px", borderRadius: 4,
      fontFamily: "'DM Mono', monospace",
    }}>
      {label}
      {badge && <span style={{ fontSize: 9, background: `${color}33`, padding: "1px 4px", borderRadius: 3 }}>{badge}</span>}
      {onRemove && <span onClick={onRemove} style={{ cursor: "pointer", opacity: 0.7, fontSize: 12, lineHeight: 1 }}>×</span>}
    </span>
  );
}

// ── Zone Chip (with inline value filter) ──────────────────────────────────────
function ZoneChip({ fieldKey, label, color, filterValue, onFilterChange, onRemove, fields, table }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(filterValue || "");
  const [suggestions, setSuggestions] = useState([]);
  const inputRef = useRef(null);

  useEffect(() => { if (editing) setTimeout(() => inputRef.current?.focus(), 40); }, [editing]);

  const fetchSug = useCallback(async (val) => {
    if (!val || val.length < 1) { setSuggestions([]); return; }
    try {
      const r = await fetch(`${API}/oflc/field-values/${table}?field=${fieldKey}&q=${encodeURIComponent(val)}&limit=8`);
      if (r.ok) { const d = await r.json(); setSuggestions(d.values || []); }
    } catch { setSuggestions([]); }
  }, [fieldKey, table]);

  const commit = (val) => {
    onFilterChange(fieldKey, val);
    setEditing(false);
    setSuggestions([]);
  };

  const active = !!filterValue;

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 0, position: "relative" }}>
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 5,
        background: `${color}18`, border: `1px solid ${active ? color : color + "44"}`,
        color, fontSize: 11, fontWeight: 500,
        padding: "3px 8px", borderRadius: editing ? "4px 0 0 4px" : 4,
        fontFamily: "'DM Mono', monospace", cursor: "default",
      }}>
        {label}
        {active && (
          <span style={{ fontSize: 9, background: `${color}33`, padding: "1px 5px", borderRadius: 3, maxWidth: 80, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            = {filterValue}
          </span>
        )}
        {/* Filter icon */}
        <span
          onClick={() => { setDraft(filterValue || ""); setEditing(e => !e); }}
          title="Filter this field"
          style={{ cursor: "pointer", opacity: active ? 1 : 0.5, fontSize: 10, lineHeight: 1, padding: "0 1px" }}
        >⊟</span>
        <span onClick={onRemove} style={{ cursor: "pointer", opacity: 0.6, fontSize: 12, lineHeight: 1 }}>×</span>
      </span>
      {editing && (
        <span style={{ display: "inline-flex", flexDirection: "column", position: "absolute", top: "100%", left: 0, zIndex: 100, minWidth: 180 }}>
          <span style={{ display: "flex" }}>
            <input
              ref={inputRef}
              value={draft}
              onChange={e => { setDraft(e.target.value); fetchSug(e.target.value); }}
              onKeyDown={e => {
                if (e.key === "Enter") commit(draft);
                if (e.key === "Escape") { setEditing(false); setSuggestions([]); }
              }}
              placeholder={`filter ${label}…`}
              style={{ fontSize: 11, padding: "4px 7px", borderRadius: "0 0 0 4px", border: `1px solid ${color}`, borderRight: "none", flex: 1, background: "var(--bg2)", color: "var(--text)" }}
            />
            <span
              onClick={() => commit(draft)}
              style={{ padding: "4px 8px", background: color, color: "var(--bg)", fontSize: 11, cursor: "pointer", borderRadius: "0 0 4px 0", fontWeight: 600 }}
            >✓</span>
            {filterValue && (
              <span
                onClick={() => commit("")}
                style={{ padding: "4px 7px", background: "var(--bg4)", color: "var(--text3)", fontSize: 11, cursor: "pointer", border: `1px solid ${color}`, borderLeft: "none", borderRadius: "0 0 4px 0" }}
                title="Clear filter"
              >✕</span>
            )}
          </span>
          {suggestions.length > 0 && (
            <span style={{ background: "var(--bg2)", border: `1px solid ${color}44`, borderTop: "none", borderRadius: "0 0 4px 4px", overflow: "hidden" }}>
              {suggestions.map(v => (
                <span key={v} onMouseDown={() => commit(v)}
                  style={{ display: "block", padding: "5px 8px", fontSize: 11, cursor: "pointer", color: "var(--text2)", fontFamily: "'DM Mono', monospace" }}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                  onMouseLeave={e => e.currentTarget.style.background = ""}>
                  {v}
                </span>
              ))}
            </span>
          )}
        </span>
      )}
    </span>
  );
}

// ── Drop Zone ─────────────────────────────────────────────────────────────────
function DropZone({ label, items, onDrop, onRemove, color, zoneFilters, onFilterChange, fields, table }) {
  const [over, setOver] = useState(false);
  return (
    <div
      onDragOver={e => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={e => { e.preventDefault(); setOver(false); const data = e.dataTransfer.getData("fieldKey"); if (data) onDrop(data); }}
      style={{
        minHeight: 44, padding: "6px 8px",
        border: `1px dashed ${over ? color : "var(--border2)"}`,
        borderRadius: "var(--radius)", background: over ? `${color}08` : "var(--bg3)",
        transition: "all 0.12s", display: "flex", flexWrap: "wrap", gap: 5, alignItems: "flex-start",
      }}
    >
      <span style={{ fontSize: 10, color: "var(--text3)", fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", alignSelf: "center", marginRight: 4 }}>{label}</span>
      {items.map((item, i) => (
        onFilterChange
          ? <ZoneChip key={item.key + i} fieldKey={item.key} label={item.label} color={color}
              filterValue={zoneFilters?.[item.key] || ""}
              onFilterChange={onFilterChange} onRemove={() => onRemove(i)}
              fields={fields} table={table} />
          : <Chip key={item.key + i} label={item.label} color={color} onRemove={() => onRemove(i)} />
      ))}
      {items.length === 0 && <span style={{ fontSize: 11, color: "var(--text3)", alignSelf: "center", fontStyle: "italic" }}>drag fields here</span>}
    </div>
  );
}

// ── Field List Sidebar ────────────────────────────────────────────────────────
function FieldList({ fields, search, usedKeys }) {
  const [collapsed, setCollapsed] = useState({});
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    const result = {};
    for (const [cat, flds] of Object.entries(fields)) {
      const matching = flds.filter(f => !q || f.label.toLowerCase().includes(q) || f.key.toLowerCase().includes(q));
      if (matching.length) result[cat] = matching;
    }
    return result;
  }, [fields, search]);

  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      {Object.entries(filtered).map(([cat, flds]) => (
        <div key={cat}>
          <div onClick={() => setCollapsed(c => ({ ...c, [cat]: !c[cat] }))}
            style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "5px 12px", cursor: "pointer", borderBottom: "1px solid var(--border)", background: "var(--bg)" }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.07em", textTransform: "uppercase" }}>{cat}</span>
            <span style={{ fontSize: 10, color: "var(--text3)" }}>{collapsed[cat] ? "▶" : "▼"}</span>
          </div>
          {!collapsed[cat] && flds.map(f => (
            <div key={f.key} draggable onDragStart={e => e.dataTransfer.setData("fieldKey", f.key)}
              style={{
                padding: "7px 12px", cursor: "grab", display: "flex", alignItems: "center", gap: 7,
                borderBottom: "1px solid var(--border)",
                background: usedKeys.has(f.key) ? "var(--bg3)" : "transparent",
                opacity: usedKeys.has(f.key) ? 0.45 : 1, transition: "background 0.1s",
              }}
              onMouseEnter={e => { if (!usedKeys.has(f.key)) e.currentTarget.style.background = "var(--bg2)"; }}
              onMouseLeave={e => { e.currentTarget.style.background = usedKeys.has(f.key) ? "var(--bg3)" : "transparent"; }}
            >
              <span style={{ width: 5, height: 5, borderRadius: "50%", flexShrink: 0, background: f.type === "numeric" ? "var(--green)" : f.type === "date" ? "var(--blue)" : "var(--text3)" }} />
              <span style={{ fontSize: 12, color: "var(--text2)", flex: 1 }}>{f.label}</span>
              {f.agg && <span style={{ fontSize: 9, color: "var(--green)", fontFamily: "'DM Mono', monospace" }}>∑</span>}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// ── Filter Row ────────────────────────────────────────────────────────────────
function FilterRow({ filter, fields, onUpdate, onRemove, table }) {
  const field = fieldByKey(fields, filter.field);
  const [suggestions, setSuggestions] = useState([]);
  const [showSug, setShowSug] = useState(false);

  const fetchSuggestions = useCallback(async (val) => {
    if (!filter.field || val.length < 1) { setSuggestions([]); return; }
    try {
      const r = await fetch(`${API}/oflc/field-values/${table}?field=${filter.field}&q=${encodeURIComponent(val)}&limit=12`);
      if (r.ok) { const data = await r.json(); setSuggestions(data.values || []); setShowSug(true); }
    } catch { setSuggestions([]); }
  }, [filter.field, table]);

  const opOptions = field?.type === "numeric"
    ? [["=","="],["!=","≠"],[">",">"],[">="," ≥"],["<","<"],["<=","≤"],["IS NULL","null"],["IS NOT NULL","not null"]]
    : field?.type === "date"
    ? [["=","="],["!=","≠"],[">","after"],[">=","from"],["<","before"],["<=","until"],["IS NULL","null"],["IS NOT NULL","not null"]]
    : [["ILIKE","contains"],["NOT ILIKE","excludes"],["=","="],["!=","≠"],["IS NULL","null"],["IS NOT NULL","not null"]];

  const noValue = filter.op === "IS NULL" || filter.op === "IS NOT NULL";

  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 5 }}>
      <select value={filter.field} onChange={e => onUpdate({ ...filter, field: e.target.value, op: DEFAULT_OP(e.target.value), value: "" })}
        style={{ fontSize: 12, flex: "0 0 160px", padding: "5px 8px" }}>
        <option value="">— pick field —</option>
        {Object.entries(fields).map(([cat, flds]) => (
          <optgroup key={cat} label={cat}>{flds.map(f => <option key={f.key} value={f.key}>{f.label}</option>)}</optgroup>
        ))}
      </select>
      <select value={filter.op} onChange={e => onUpdate({ ...filter, op: e.target.value })}
        style={{ fontSize: 12, flex: "0 0 90px", padding: "5px 8px" }}>
        {opOptions.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      {!noValue && (
        <div style={{ position: "relative", flex: 1 }}>
          <input value={filter.value}
            onChange={e => { onUpdate({ ...filter, value: e.target.value }); fetchSuggestions(e.target.value); }}
            onFocus={() => filter.value && fetchSuggestions(filter.value)}
            onBlur={() => setTimeout(() => setShowSug(false), 150)}
            placeholder={field?.type === "date" ? "YYYY-MM-DD" : "value…"}
            style={{ fontSize: 12, padding: "5px 8px" }} />
          {showSug && suggestions.length > 0 && (
            <div style={{ position: "absolute", top: "calc(100% + 2px)", left: 0, right: 0, zIndex: 50,
              background: "var(--bg2)", border: "1px solid var(--border2)", borderRadius: "var(--radius)",
              maxHeight: 180, overflowY: "auto", boxShadow: "0 6px 20px #00000066" }}>
              {suggestions.map(v => (
                <div key={v} onMouseDown={() => { onUpdate({ ...filter, value: v }); setShowSug(false); }}
                  style={{ padding: "6px 10px", fontSize: 12, cursor: "pointer", color: "var(--text2)" }}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                  onMouseLeave={e => e.currentTarget.style.background = ""}>{v}</div>
              ))}
            </div>
          )}
        </div>
      )}
      <button onClick={onRemove} style={{ width: 24, height: 28, padding: 0, fontSize: 14, background: "none", border: "1px solid var(--border)", color: "var(--text3)", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>×</button>
    </div>
  );
}

// ── Value Metric Picker ───────────────────────────────────────────────────────
function ValuePicker({ value, fields, onUpdate, onRemove }) {
  const field = fieldByKey(fields, value.field);
  const validAggs = AGGREGATIONS.filter(a => !a.numeric || field?.agg);
  return (
    <div style={{ display: "flex", gap: 5, alignItems: "center", marginBottom: 4 }}>
      <select value={value.agg} onChange={e => onUpdate({ ...value, agg: e.target.value })}
        style={{ fontSize: 11, flex: "0 0 110px", padding: "4px 6px" }}>
        {validAggs.map(a => <option key={a.key} value={a.key}>{a.label}</option>)}
      </select>
      {value.agg !== "count" && value.agg !== "pct_of_total" && (
        <select value={value.field} onChange={e => onUpdate({ ...value, field: e.target.value })}
          style={{ fontSize: 11, flex: 1, padding: "4px 6px" }}>
          {Object.entries(fields).map(([cat, flds]) => (
            <optgroup key={cat} label={cat}>{flds.filter(f => f.agg).map(f => <option key={f.key} value={f.key}>{f.label}</option>)}</optgroup>
          ))}
        </select>
      )}
      <input value={value.label} onChange={e => onUpdate({ ...value, label: e.target.value })}
        placeholder="label…" style={{ fontSize: 11, flex: "0 0 90px", padding: "4px 6px" }} />
      <button onClick={onRemove} style={{ width: 22, height: 24, padding: 0, background: "none", border: "1px solid var(--border)", color: "var(--text3)", fontSize: 12 }}>×</button>
    </div>
  );
}

// ── Pivot Table ───────────────────────────────────────────────────────────────
function formatVal(v) {
  if (v === null || v === undefined) return <span style={{ color: "var(--text3)" }}>—</span>;
  const n = parseFloat(v);
  if (!isNaN(n)) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return String(v);
}

function PivotTable({ data, rowFields, colField, valueMetrics, fields, color, rawMode }) {
  if (!data || !data.rows) return null;

  if (rawMode) {
    const cols = data.columns || [];
    return (
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              {cols.map(c => (
                <th key={c} style={{ padding: "8px 12px", textAlign: "left", fontWeight: 600, fontSize: 10,
                  letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--text3)",
                  background: "var(--bg3)", borderBottom: "1px solid var(--border2)",
                  position: "sticky", top: 0, whiteSpace: "nowrap" }}>
                  {fieldByKey(fields, c)?.label || c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, i) => (
              <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}
                onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                onMouseLeave={e => e.currentTarget.style.background = ""}>
                {cols.map((c, j) => (
                  <td key={j} style={{ padding: "7px 12px", color: "var(--text2)", fontFamily: j === 0 ? "'DM Mono', monospace" : "inherit" }}>
                    {row[c] ?? <span style={{ color: "var(--text3)", fontStyle: "italic" }}>—</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ padding: "8px 12px", fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
          {data.total_rows?.toLocaleString()} rows {data.limited ? `(showing first ${data.rows.length})` : ""}
        </div>
      </div>
    );
  }

  // Pivot mode
  const colValues = data.col_values || [];
  const hasColField = !!colField;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr>
            {rowFields.map(rf => (
              <th key={rf} style={{ padding: "8px 12px", textAlign: "left", fontWeight: 600, fontSize: 10,
                letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--text3)",
                background: "var(--bg3)", borderBottom: "1px solid var(--border2)",
                position: "sticky", top: 0, whiteSpace: "nowrap", minWidth: 140 }}>
                {fieldByKey(fields, rf)?.label || rf}
              </th>
            ))}
            {hasColField
              ? colValues.map(cv => valueMetrics.map(vm => (
                  <th key={`${cv}-${vm.label}`} style={{ padding: "8px 12px", textAlign: "right", fontSize: 10,
                    fontWeight: 600, color, background: "var(--bg3)", borderBottom: "1px solid var(--border2)",
                    position: "sticky", top: 0, whiteSpace: "nowrap" }}>
                    <div style={{ fontSize: 9, color: "var(--text3)", marginBottom: 1 }}>{cv ?? "—"}</div>{vm.label}
                  </th>
                )))
              : valueMetrics.map(vm => (
                  <th key={vm.label} style={{ padding: "8px 12px", textAlign: "right", fontSize: 10,
                    fontWeight: 600, color, background: "var(--bg3)", borderBottom: "1px solid var(--border2)",
                    position: "sticky", top: 0, whiteSpace: "nowrap" }}>{vm.label}</th>
                ))
            }
            {hasColField && valueMetrics.map(vm => (
              <th key={`total-${vm.label}`} style={{ padding: "8px 12px", textAlign: "right", fontSize: 10,
                fontWeight: 600, color: "var(--text3)", background: "var(--bg3)",
                borderBottom: "1px solid var(--border2)", position: "sticky", top: 0, whiteSpace: "nowrap" }}>
                Total · {vm.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}
              onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
              onMouseLeave={e => e.currentTarget.style.background = ""}>
              {rowFields.map((rf, j) => (
                <td key={rf} style={{ padding: "7px 12px", color: j === 0 ? color : "var(--text2)",
                  fontFamily: j === 0 ? "'DM Mono', monospace" : "inherit", fontWeight: j === 0 ? 500 : 400 }}>
                  {row[rf] ?? <span style={{ color: "var(--text3)", fontStyle: "italic" }}>—</span>}
                </td>
              ))}
              {hasColField
                ? colValues.map(cv => valueMetrics.map(vm => (
                    <td key={`${cv}-${vm.label}`} style={{ padding: "7px 12px", textAlign: "right", fontFamily: "'DM Mono', monospace", color: "var(--text)" }}>
                      {formatVal(row[`${cv}__${vm.label}`])}
                    </td>
                  )))
                : valueMetrics.map(vm => (
                    <td key={vm.label} style={{ padding: "7px 12px", textAlign: "right", fontFamily: "'DM Mono', monospace", color: "var(--text)" }}>
                      {formatVal(row[vm.label])}
                    </td>
                  ))
              }
              {hasColField && valueMetrics.map(vm => (
                <td key={`rt-${vm.label}`} style={{ padding: "7px 12px", textAlign: "right", fontFamily: "'DM Mono', monospace", color: "var(--text3)", fontWeight: 600 }}>
                  {formatVal(row[`__row_total__${vm.label}`])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {data.grand_total && (
          <tfoot>
            <tr style={{ borderTop: "2px solid var(--border2)", background: "var(--bg3)" }}>
              {rowFields.map((rf, j) => (
                <td key={rf} style={{ padding: "8px 12px", fontSize: 11, color: "var(--text3)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {j === 0 ? "Grand Total" : ""}
                </td>
              ))}
              {hasColField
                ? colValues.map(cv => valueMetrics.map(vm => (
                    <td key={`gt-${cv}-${vm.label}`} style={{ padding: "8px 12px", textAlign: "right", fontFamily: "'DM Mono', monospace", color, fontWeight: 700 }}>
                      {formatVal(data.grand_total[`${cv}__${vm.label}`])}
                    </td>
                  )))
                : valueMetrics.map(vm => (
                    <td key={`gt-${vm.label}`} style={{ padding: "8px 12px", textAlign: "right", fontFamily: "'DM Mono', monospace", color, fontWeight: 700 }}>
                      {formatVal(data.grand_total[vm.label])}
                    </td>
                  ))
              }
              {hasColField && valueMetrics.map(vm => (
                <td key={`grt-${vm.label}`} style={{ padding: "8px 12px", textAlign: "right", fontFamily: "'DM Mono', monospace", color, fontWeight: 700 }}>
                  {formatVal(data.grand_total[`__row_total__${vm.label}`])}
                </td>
              ))}
            </tr>
          </tfoot>
        )}
      </table>
      <div style={{ padding: "8px 12px", fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
        {data.total_rows?.toLocaleString()} rows{data.limited ? ` · showing top ${data.rows.length}` : ""}
      </div>
    </div>
  );
}

// ── Chart View ────────────────────────────────────────────────────────────────
function ChartView({ data, valueMetrics, rowFields, color }) {
  const [chartMetric, setChartMetric] = useState(0);
  const [chartType, setChartType] = useState("horizontal");
  if (!data?.rows?.length) return <div style={{ padding: "40px", textAlign: "center", color: "var(--text3)" }}>Run a query first to see charts.</div>;
  const vm = valueMetrics[chartMetric] || valueMetrics[0];
  if (!vm) return null;
  const labelKey = rowFields[0];
  const chartData = data.rows.slice(0, 30).map(r => ({
    label: String(r[labelKey] ?? "—").slice(0, 40),
    value: parseFloat(r[vm.label]) || 0,
  }));
  const maxVal = Math.max(...chartData.map(d => d.value), 1);

  return (
    <div style={{ padding: "20px 24px" }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 20, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--text3)" }}>Metric:</span>
        {valueMetrics.map((vm2, i) => (
          <button key={i} onClick={() => setChartMetric(i)} style={{ fontSize: 11, padding: "3px 10px", height: "auto",
            background: chartMetric === i ? `${color}22` : "var(--bg3)", color: chartMetric === i ? color : "var(--text3)",
            border: `1px solid ${chartMetric === i ? color : "var(--border)"}`, borderRadius: 4 }}>{vm2.label}</button>
        ))}
        <div style={{ flex: 1 }} />
        {["bar", "horizontal"].map(t => (
          <button key={t} onClick={() => setChartType(t)} style={{ fontSize: 11, padding: "3px 10px", height: "auto",
            background: chartType === t ? `${color}22` : "var(--bg3)", color: chartType === t ? color : "var(--text3)",
            border: `1px solid ${chartType === t ? color : "var(--border)"}`, borderRadius: 4 }}>
            {t === "bar" ? "▨ Bar" : "⬛ Horizontal"}
          </button>
        ))}
      </div>
      <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text2)", marginBottom: 16 }}>
        {vm.label} · <span style={{ fontSize: 11, color: "var(--text3)" }}>top {chartData.length}</span>
      </div>
      {chartType === "bar" ? (
        <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 240, overflowX: "auto", paddingBottom: 60 }}>
          {chartData.map((d, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, flex: "0 0 auto", minWidth: 36 }}>
              <span style={{ fontSize: 9, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
                {d.value > 999 ? (d.value / 1000).toFixed(1) + "k" : d.value}
              </span>
              <div title={`${d.label}: ${d.value.toLocaleString()}`} style={{ width: 32, background: color, borderRadius: "3px 3px 0 0", height: `${Math.max(2, (d.value / maxVal) * 180)}px`, opacity: 0.85 }} />
              <span style={{ fontSize: 9, color: "var(--text3)", writingMode: "vertical-lr", transform: "rotate(180deg)", maxHeight: 55, overflow: "hidden" }}>{d.label}</span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {chartData.map((d, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 11, color: "var(--text2)", flex: "0 0 200px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "right" }}>{d.label}</span>
              <div style={{ flex: 1, height: 20, background: "var(--bg4)", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${(d.value / maxVal) * 100}%`, background: color, borderRadius: 3 }} />
              </div>
              <span style={{ fontSize: 11, color, fontFamily: "'DM Mono', monospace", flex: "0 0 70px", textAlign: "right" }}>{d.value.toLocaleString()}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── CSV Export ────────────────────────────────────────────────────────────────
function exportCSV(data, rawMode, rowFields, valueMetrics, colValues) {
  if (!data?.rows?.length) return;
  const escape = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
  let headers, rows;
  if (rawMode) {
    headers = data.columns || [];
    rows = data.rows.map(r => headers.map(h => r[h] ?? ""));
  } else {
    headers = [...rowFields];
    if (colValues?.length) {
      colValues.forEach(cv => valueMetrics.forEach(vm => headers.push(`${cv} - ${vm.label}`)));
      valueMetrics.forEach(vm => headers.push(`Total - ${vm.label}`));
    } else {
      valueMetrics.forEach(vm => headers.push(vm.label));
    }
    rows = data.rows.map(r => {
      const vals = rowFields.map(f => r[f] ?? "");
      if (colValues?.length) {
        colValues.forEach(cv => valueMetrics.forEach(vm => vals.push(r[`${cv}__${vm.label}`] ?? "")));
        valueMetrics.forEach(vm => vals.push(r[`__row_total__${vm.label}`] ?? ""));
      } else {
        valueMetrics.forEach(vm => vals.push(r[vm.label] ?? ""));
      }
      return vals;
    });
    if (data.grand_total) {
      const gt = rowFields.map((_, i) => i === 0 ? "Grand Total" : "");
      if (colValues?.length) {
        colValues.forEach(cv => valueMetrics.forEach(vm => gt.push(data.grand_total[`${cv}__${vm.label}`] ?? "")));
        valueMetrics.forEach(vm => gt.push(data.grand_total[`__row_total__${vm.label}`] ?? ""));
      } else {
        valueMetrics.forEach(vm => gt.push(data.grand_total[vm.label] ?? ""));
      }
      rows.push(gt);
    }
  }
  const csv = [headers.map(escape).join(","), ...rows.map(r => r.map(escape).join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = "oflc_export.csv"; a.click();
  URL.revokeObjectURL(url);
}

// ── Empty State ───────────────────────────────────────────────────────────────
function EmptyState({ rawMode, color }) {
  const examples = rawMode
    ? [
        { label: "All cases for a specific employer", hint: "Filter employer_name contains 'Google'" },
        { label: "Cases by attorney/firm", hint: "Filter atty_law_firm contains 'Fragomen'" },
        { label: "Recent decisions", hint: "Filter decision_date after 2025-01-01" },
      ]
    : [
        { label: "Certification rate by state", hint: "Rows: worksite_state · Values: Count, % of Total" },
        { label: "Top employers by filing volume", hint: "Rows: employer_name · Values: Count" },
        { label: "SOC codes used for a suggested SOC", hint: "Filter soc_code = 15-1299.09 · Rows: soc_title · Values: Count" },
        { label: "Wage distribution by wage level", hint: "Rows: pw_wage_level · Values: Avg wage_from, Count" },
        { label: "Law firm volume by fiscal year", hint: "Rows: atty_law_firm · Columns: fiscal_year · Values: Count" },
      ];
  return (
    <div style={{ padding: "32px 28px", maxWidth: 600 }}>
      <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 16 }}>
        {rawMode ? "Add filters and click Run to retrieve records." : "Drag fields to Rows, optionally Columns, configure Values, then click Run."}
      </div>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10 }}>Example queries</div>
      {examples.map((ex, i) => (
        <div key={i} style={{ padding: "10px 13px", marginBottom: 6, background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--radius)", borderLeft: `2px solid ${color}` }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", marginBottom: 3 }}>{ex.label}</div>
          <div style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{ex.hint}</div>
        </div>
      ))}
    </div>
  );
}

// ── Router ────────────────────────────────────────────────────────────────────
export function OflcView() {
  const [screen, setScreen] = useState("landing"); // landing | dashboard | templates | pivot
  const [templateOverride, setTemplateOverride] = useState(null);

  const openInBuilder = (template) => {
    setTemplateOverride(template);
    setScreen("pivot");
  };

  if (screen === "landing")   return <OflcLanding onNavigate={setScreen} />;
  if (screen === "dashboard") return <OflcDashboard onBack={() => setScreen("landing")} />;
  if (screen === "templates") return <OflcTemplates onBack={() => setScreen("landing")} onOpenInBuilder={openInBuilder} />;
  return <OflcPivot onBack={() => setScreen("landing")} templateOverride={templateOverride} onTemplateClear={() => setTemplateOverride(null)} />;
}

// ── Main Pivot (renamed from OflcView) ───────────────────────────────────────
function OflcPivot({ onBack, templateOverride, onTemplateClear }) {
  const [dataset, setDataset] = useState("perm");
  const [outputTab, setOutputTab] = useState("pivot");
  const [fieldSearch, setFieldSearch] = useState("");
  const [rowFields, setRowFields] = useState([]);
  const [colField, setColField] = useState(null);
  const [zoneFilters, setZoneFilters] = useState({}); // { fieldKey: value }
  const [valueMetrics, setValueMetrics] = useState([{ agg: "count", field: null, label: "Count" }]);
  const [filters, setFilters] = useState([]);
  const [limit, setLimit] = useState(500);
  const [rawMode, setRawMode] = useState(false);
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hasRun, setHasRun] = useState(false);

  const cfg = DATASET_CONFIG[dataset];
  const fields = cfg.fields;
  const color = cfg.color;

  // Load template override into builder state
  useEffect(() => {
    if (!templateOverride) return;
    const t = templateOverride;
    setDataset(t.dataset);
    setRowFields(t.rows || []);
    setColField(t.cols || null);
    setValueMetrics(t.metrics || [{ agg: "count", field: null, label: "Count" }]);
    setFilters(t.filters?.map((f, i) => ({ ...f, id: Date.now() + i })) || []);
    setZoneFilters({});
    setResults(null); setHasRun(false); setError(null);
    onTemplateClear();
  }, [templateOverride]);

  const usedKeys = useMemo(() => {
    const keys = new Set();
    rowFields.forEach(k => keys.add(k));
    if (colField) keys.add(colField);
    valueMetrics.forEach(v => { if (v.field) keys.add(v.field); });
    return keys;
  }, [rowFields, colField, valueMetrics]);

  const handleDatasetChange = (ds) => {
    setDataset(ds); setRowFields([]); setColField(null); setZoneFilters({});
    setValueMetrics([{ agg: "count", field: null, label: "Count" }]);
    setFilters([]); setResults(null); setHasRun(false); setError(null);
  };

  const handleFieldDrop = (zone, key) => {
    if (zone === "rows") { if (!rowFields.includes(key)) setRowFields(r => [...r, key]); }
    else if (zone === "cols") { setColField(key); }
  };

  const addFilter = () => setFilters(f => [...f, { id: Date.now(), field: "", op: "ILIKE", value: "" }]);
  const addValueMetric = () => setValueMetrics(v => [...v, { agg: "count", field: null, label: "Metric " + (v.length + 1) }]);

  const runQuery = async () => {
    setLoading(true); setError(null); setHasRun(true);
    const params = new URLSearchParams();
    params.set("table", cfg.table);
    params.set("mode", rawMode ? "raw" : "pivot");
    params.set("limit", limit);
    filters.forEach((f, i) => {
      if (f.field) { params.set(`f_field_${i}`, f.field); params.set(`f_op_${i}`, f.op); params.set(`f_val_${i}`, f.value || ""); }
    });
    // Zone filters (from row/col chips) — append after explicit filters
    let zfi = filters.filter(f => f.field).length;
    Object.entries(zoneFilters).forEach(([fieldKey, val]) => {
      if (val) { params.set(`f_field_${zfi}`, fieldKey); params.set(`f_op_${zfi}`, "="); params.set(`f_val_${zfi}`, val); zfi++; }
    });
    if (!rawMode) {
      rowFields.forEach(f => params.append("rows", f));
      if (colField) params.set("cols", colField);
      valueMetrics.forEach((vm, i) => {
        params.set(`vm_agg_${i}`, vm.agg);
        params.set(`vm_field_${i}`, vm.field || "");
        params.set(`vm_label_${i}`, vm.label || "Metric");
      });
    }
    try {
      const url = `${API}/oflc/query?${params}`;
      console.log("[OflcView] query URL:", url);
      const r = await fetch(url);
      if (!r.ok) { const err = await r.json().catch(() => ({ detail: "Unknown error" })); throw new Error(err.detail || `Server error ${r.status}`); }
      const d = await r.json(); d._fields = fields; setResults(d);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* ── Header ── */}
      <div style={{ padding: "10px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0, display: "flex", alignItems: "center", gap: 12 }}>
        <button onClick={onBack} style={{ background: "none", border: "1px solid var(--border)", fontSize: 11, padding: "3px 10px", height: "auto", color: "var(--text3)" }}>← Back</button>
        <div style={{ width: 1, height: 16, background: "var(--border)" }} />
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase" }}>DOL Performance Data</span>
        <div style={{ display: "flex", gap: 3, marginLeft: 8 }}>
          {Object.entries(DATASET_CONFIG).map(([key, ds]) => (
            <button key={key} onClick={() => handleDatasetChange(key)} style={{ padding: "4px 12px", height: "auto", fontSize: 12,
              background: dataset === key ? `${ds.color}18` : "var(--bg3)", color: dataset === key ? ds.color : "var(--text3)",
              border: `1px solid ${dataset === key ? ds.color + "44" : "var(--border)"}`, borderRadius: 4, fontWeight: dataset === key ? 600 : 400 }}>
              {ds.label}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text3)", cursor: "pointer", userSelect: "none" }}>
          <div onClick={() => setRawMode(m => !m)} style={{ width: 32, height: 16, borderRadius: 8, background: rawMode ? color : "var(--bg4)", border: `1px solid ${rawMode ? color : "var(--border2)"}`, position: "relative", cursor: "pointer", transition: "background 0.2s" }}>
            <div style={{ position: "absolute", top: 2, left: rawMode ? 16 : 2, width: 10, height: 10, borderRadius: "50%", background: rawMode ? "var(--bg)" : "var(--text3)", transition: "left 0.2s" }} />
          </div>
          Raw records
        </label>
        <button onClick={runQuery} disabled={loading || (!rawMode && rowFields.length === 0)} className="primary"
          style={{ fontSize: 12, padding: "5px 16px", height: "auto", opacity: (!rawMode && rowFields.length === 0) || loading ? 0.5 : 1, background: color, borderColor: color }}>
          {loading ? "Running…" : "▶ Run"}
        </button>
        {results && (
          <button onClick={() => exportCSV(results, rawMode, rowFields, valueMetrics, results.col_values)}
            style={{ fontSize: 12, padding: "5px 12px", height: "auto", display: "flex", alignItems: "center", gap: 5 }}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            CSV
          </button>
        )}
      </div>

      {/* ── Body ── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* ── Field Sidebar ── */}
        <div style={{ width: 220, flexShrink: 0, borderRight: "1px solid var(--border)", background: "var(--bg2)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)" }}>
            <div style={{ position: "relative" }}>
              <svg style={{ position: "absolute", left: 7, top: "50%", transform: "translateY(-50%)", color: "var(--text3)", pointerEvents: "none" }} width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
              <input value={fieldSearch} onChange={e => setFieldSearch(e.target.value)} placeholder="Search fields…" style={{ fontSize: 12, paddingLeft: 24, height: 30 }} />
            </div>
          </div>
          <div style={{ padding: "5px 10px", borderBottom: "1px solid var(--border)", display: "flex", gap: 10 }}>
            {[["var(--text3)", "text"], ["var(--green)", "numeric ∑"], ["var(--blue)", "date"]].map(([c, l]) => (
              <span key={l} style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 9, color: "var(--text3)" }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: c, flexShrink: 0 }} />{l}
              </span>
            ))}
          </div>
          <FieldList fields={fields} search={fieldSearch} usedKeys={usedKeys} />
          <div style={{ padding: "8px 10px", borderTop: "1px solid var(--border)", fontSize: 10, color: "var(--text3)", lineHeight: 1.5 }}>
            Drag fields to Rows, Columns, or use as filters.
          </div>
        </div>

        {/* ── Center ── */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Builder panel */}
          <div style={{ borderBottom: "1px solid var(--border)", background: "var(--bg2)", padding: "12px 16px", flexShrink: 0 }}>
            {!rawMode ? (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
                  <DropZone label="Rows" color={color}
                    items={rowFields.map(k => ({ key: k, label: fieldByKey(fields, k)?.label || k }))}
                    onDrop={key => handleFieldDrop("rows", key)}
                    onRemove={i => setRowFields(r => r.filter((_, j) => j !== i))}
                    zoneFilters={zoneFilters} fields={fields} table={cfg.table.replace("oflc_", "")}
                    onFilterChange={(fk, val) => setZoneFilters(z => ({ ...z, [fk]: val }))} />
                  <DropZone label="Columns (split by)" color="var(--blue)"
                    items={colField ? [{ key: colField, label: fieldByKey(fields, colField)?.label || colField }] : []}
                    onDrop={key => handleFieldDrop("cols", key)}
                    onRemove={() => setColField(null)}
                    zoneFilters={zoneFilters} fields={fields} table={cfg.table.replace("oflc_", "")}
                    onFilterChange={(fk, val) => setZoneFilters(z => ({ ...z, [fk]: val }))} />
                </div>
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 5 }}>Values</div>
                  {valueMetrics.map((vm, i) => (
                    <ValuePicker key={i} value={vm} fields={fields}
                      onUpdate={updated => setValueMetrics(v => v.map((x, j) => j === i ? updated : x))}
                      onRemove={() => setValueMetrics(v => v.filter((_, j) => j !== i))} />
                  ))}
                  <button onClick={addValueMetric} style={{ fontSize: 11, padding: "3px 10px", height: "auto", color, background: `${color}11`, border: `1px solid ${color}33` }}>+ Add metric</button>
                </div>
              </>
            ) : (
              <div style={{ padding: "8px 0", fontSize: 12, color: "var(--text2)" }}>
                <span style={{ color: "var(--text3)" }}>Raw mode:</span> Returns individual records matching your filters. Limit:&nbsp;
                <input value={limit} onChange={e => setLimit(Number(e.target.value))} type="number" style={{ width: 70, fontSize: 12, display: "inline-block", padding: "2px 6px" }} /> rows.
              </div>
            )}
            {/* Filters */}
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10, marginTop: rawMode ? 0 : 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.07em", textTransform: "uppercase" }}>Filters</span>
                <button onClick={addFilter} style={{ fontSize: 11, padding: "2px 8px", height: "auto", color: "var(--text3)", background: "none", border: "1px solid var(--border)" }}>+ Add</button>
                {!rawMode && (
                  <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text3)" }}>
                    Limit&nbsp;<input value={limit} onChange={e => setLimit(Number(e.target.value))} type="number" style={{ width: 65, fontSize: 11, display: "inline-block", padding: "2px 6px" }} />&nbsp;rows
                  </span>
                )}
              </div>
              {filters.map((f, i) => (
                <FilterRow key={f.id} filter={f} fields={fields} table={cfg.table.replace("oflc_", "")}
                  onUpdate={updated => setFilters(v => v.map((x, j) => j === i ? updated : x))}
                  onRemove={() => setFilters(v => v.filter((_, j) => j !== i))} />
              ))}
              {filters.length === 0 && <div style={{ fontSize: 11, color: "var(--text3)", fontStyle: "italic" }}>No filters — querying all rows.</div>}
            </div>
          </div>

          {/* Results */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {results && (
              <div style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
                {[{ id: "pivot", label: rawMode ? "Records" : "Pivot Table" }, { id: "chart", label: "Chart" }].map(t => (
                  <button key={t.id} onClick={() => setOutputTab(t.id)} style={{ padding: "8px 14px", fontSize: 12, background: "none", border: "none", borderRadius: 0,
                    borderBottom: outputTab === t.id ? `2px solid ${color}` : "2px solid transparent",
                    color: outputTab === t.id ? color : "var(--text3)", fontWeight: outputTab === t.id ? 500 : 400 }}>{t.label}</button>
                ))}
              </div>
            )}
            <div style={{ flex: 1, overflowY: "auto" }}>
              {loading && <Spinner />}
              {error && <div style={{ margin: "16px", padding: "10px 14px", background: "var(--red-dim)", border: "1px solid var(--red)", borderRadius: "var(--radius)", fontSize: 12, color: "var(--red)", fontFamily: "'DM Mono', monospace" }}>{error}</div>}
              {!loading && !error && !hasRun && <EmptyState rawMode={rawMode} color={color} />}
              {!loading && !error && hasRun && !results && <div style={{ padding: "40px", textAlign: "center", color: "var(--text3)" }}>No results.</div>}
              {!loading && results && outputTab === "pivot" && (
                <PivotTable data={results} rowFields={rowFields} colField={colField} valueMetrics={valueMetrics} fields={fields} color={color} rawMode={rawMode} />
              )}
              {!loading && results && outputTab === "chart" && (
                <ChartView data={results} valueMetrics={valueMetrics} rowFields={rowFields} color={color} />
              )}
            </div>
          </div>
        </div>
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
