import { useState, useEffect, useCallback } from "react";
import { API } from "./apiBase";
import { useFetch } from "./common";

// ─── constants ────────────────────────────────────────────────────────────────

const COUNTRIES = ["India","China","Mexico","Philippines","Rest of the World"];
const CATEGORIES = ["EB1","EB2","EB3","EB4","EB5","EW3","CRW"];
const MONTHS = ["January","February","March","April","May","June",
                "July","August","September","October","November","December"];

const TIER1 = new Set([
  "Philippines|EB3","Philippines|EB2","Mexico|EB2","Mexico|EB3","Rest of the World|EB3"
]);

const REGIME_META = {
  eb2_ahead:   { color: "var(--green, #27815f)", label: "EB2 Ahead", desc: "EB2 cutoff leads EB3 — forecasts reliable" },
  eb3_ahead:   { color: "var(--amber, #b47718)", label: "EB3 Ahead", desc: "EB3 leads EB2 — downgrade incentive active, queue inflated" },
  near_parity: { color: "var(--text3, #888)",    label: "Near Parity", desc: "Cutoffs close — transitional, monitor weekly" },
  "n/a":       { color: "var(--text3, #888)",    label: "N/A",        desc: "Spread regime doesn't apply to this category" },
  unknown:     { color: "var(--text3, #888)",    label: "Unknown",    desc: "Insufficient data" },
};

const CONFIDENCE_META = {
  high:               { color: "#27815f", label: "High" },
  medium:             { color: "#b47718", label: "Medium" },
  low:                { color: "#bf4b4b", label: "Low" },
  cleared:            { color: "#27815f", label: "Cleared" },
  insufficient_data:  { color: "#888",    label: "Insufficient data" },
  queue_growing:      { color: "#bf4b4b", label: "Queue growing" },
};

// ─── helpers ─────────────────────────────────────────────────────────────────

function fmt(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString();
}

function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(s);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function tier(country, category) {
  if (TIER1.has(`${country}|${category}`)) return 1;
  if (category === "EB2" || category === "EB3") return 2;
  return 3;
}

// ─── sub-components ──────────────────────────────────────────────────────────

function RegimeBadge({ regime }) {
  const m = REGIME_META[regime] || REGIME_META.unknown;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontSize: 11, fontWeight: 600, letterSpacing: "0.04em",
      color: m.color, border: `1px solid ${m.color}44`,
      borderRadius: 4, padding: "2px 8px", textTransform: "uppercase",
    }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: m.color, flexShrink: 0 }} />
      {m.label}
    </span>
  );
}

function ConfidenceDot({ confidence }) {
  const m = CONFIDENCE_META[confidence] || CONFIDENCE_META.low;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: m.color }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: m.color }} />
      {m.label}
    </span>
  );
}

function StatCard({ label, value, sub, accent }) {
  return (
    <div style={{
      background: "var(--bg2)", border: "1px solid var(--border)",
      borderRadius: "var(--radius)", padding: "14px 16px", minWidth: 0,
    }}>
      <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 500, color: accent || "var(--text)", lineHeight: 1.1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

function SectionHeader({ children, accent }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
      textTransform: "uppercase", color: accent || "var(--text3)",
      borderBottom: "1px solid var(--border)", paddingBottom: 8, marginBottom: 16,
    }}>
      {children}
    </div>
  );
}

// ─── Tier 1: Forecast Panel ───────────────────────────────────────────────────

function ForecastPanel({ country, category }) {
  const { data, loading, error } = useFetch(
    `${API}/eb-inventory/forecast?country=${encodeURIComponent(country)}&category=${category}`
  );

  if (loading) return <div style={{ color: "var(--text3)", fontSize: 13, padding: 24 }}>Loading forecast…</div>;
  if (error || !data) return (
    <div style={{ color: "var(--text3)", fontSize: 13, padding: 24 }}>
      {error?.detail?.message || "Forecast unavailable."}
    </div>
  );

  const active = (data.forecasts || []).filter(f => f.pending > 0);

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 24 }}>
        <StatCard label="Snapshot" value={fmtDate(data.snapshot_date)} />
        <StatCard label="Regime" value={<RegimeBadge regime={data.regime} />} />
        <StatCard label="EB2 Cutoff" value={fmtDate(data.eb2_cutoff)} />
        <StatCard label="EB3 Cutoff" value={fmtDate(data.eb3_cutoff)} />
        <StatCard
          label="Backtest MAE"
          value={`${data.backtest_accuracy?.mae_months ?? "—"} mo`}
          sub="mean absolute error"
          accent="#27815f"
        />
      </div>

      <SectionHeader accent="#27815f">Priority date forecasts — {country} {category}</SectionHeader>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ color: "var(--text3)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              <th style={{ textAlign: "left", padding: "6px 10px", borderBottom: "1px solid var(--border)" }}>Priority year</th>
              <th style={{ textAlign: "right", padding: "6px 10px", borderBottom: "1px solid var(--border)" }}>Pending</th>
              <th style={{ textAlign: "right", padding: "6px 10px", borderBottom: "1px solid var(--border)" }}>Months to clear</th>
              <th style={{ textAlign: "left", padding: "6px 10px", borderBottom: "1px solid var(--border)" }}>Projected cutoff date</th>
              <th style={{ textAlign: "left", padding: "6px 10px", borderBottom: "1px solid var(--border)" }}>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {active.map(f => (
              <tr key={f.priority_year} style={{ borderBottom: "1px solid var(--border)22" }}>
                <td style={{ padding: "8px 10px", fontWeight: 500 }}>PY {f.priority_year}</td>
                <td style={{ padding: "8px 10px", textAlign: "right", fontFamily: "monospace" }}>{fmt(f.pending)}</td>
                <td style={{ padding: "8px 10px", textAlign: "right", fontFamily: "monospace" }}>
                  {f.months_to_clear != null ? `${f.months_to_clear}` : "—"}
                </td>
                <td style={{ padding: "8px 10px" }}>{fmtDate(f.projected_clear_date)}</td>
                <td style={{ padding: "8px 10px" }}><ConfidenceDot confidence={f.confidence} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.regime !== "eb2_ahead" && (
        <div style={{ marginTop: 16, fontSize: 12, color: "var(--text3)", padding: "10px 14px", background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius)" }}>
          Note: Current regime is <strong>{data.regime}</strong> — {REGIME_META[data.regime]?.desc}. Forecast accuracy is lower than the {data.backtest_accuracy?.mae_months}mo MAE benchmark, which was measured in the eb2_ahead regime.
        </div>
      )}
    </div>
  );
}

// ─── Tier 2: Regime Panel ────────────────────────────────────────────────────

function RegimePanel({ country, category }) {
  const { data: regime, loading } = useFetch(
    `${API}/eb-inventory/regime?country=${encodeURIComponent(country)}&category=${category}`
  );
  const { data: spread, loading: sloading } = useFetch(
    `${API}/eb-inventory/spread-history?country=${encodeURIComponent(country)}`
  );

  const isEB23 = category === "EB2" || category === "EB3";

  return (
    <div>
      {isEB23 ? (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 24 }}>
            <StatCard label="Current Regime" value={loading ? "…" : <RegimeBadge regime={regime?.regime} />} />
            <StatCard label="Spread" value={loading ? "…" : (regime?.spread_days != null ? `${regime.spread_days > 0 ? "+" : ""}${regime.spread_days}d` : "—")} sub="EB2 minus EB3 cutoff" accent={regime?.spread_days > 0 ? "#27815f" : regime?.spread_days < 0 ? "#b47718" : "var(--text)"} />
            <StatCard label="EB2 Cutoff" value={loading ? "…" : fmtDate(regime?.eb2_cutoff)} />
            <StatCard label="EB3 Cutoff" value={loading ? "…" : fmtDate(regime?.eb3_cutoff)} />
            <StatCard label="Forecast accuracy (eb2_ahead)" value="2.4 mo MAE" sub="91% within 6 months" accent="#27815f" />
          </div>

          {!loading && regime && (
            <div style={{
              padding: "12px 16px", marginBottom: 20,
              background: regime.regime === "eb2_ahead" ? "#27815f10" : regime.regime === "eb3_ahead" ? "#b4771810" : "var(--bg2)",
              border: `1px solid ${REGIME_META[regime.regime]?.color || "var(--border)"}44`,
              borderRadius: "var(--radius)", fontSize: 13
            }}>
              <strong>{REGIME_META[regime.regime]?.desc}</strong>
              {regime.regime === "eb2_ahead" && (
                <div style={{ marginTop: 6, color: "var(--text3)", fontSize: 12 }}>
                  When EB2 leads EB3, beneficiaries port back from EB3 to EB2 — the combined queue deflates quickly. Use the Tier 1 forecaster if this is Mexico or Philippines, or the queue position tool for other countries.
                </div>
              )}
              {regime.regime === "eb3_ahead" && (
                <div style={{ marginTop: 6, color: "var(--text3)", fontSize: 12 }}>
                  New filers are entering the EB2 queue via EB3 downgrade strategy, inflating inventory numbers. Individual priority year counts are unreliable. Use queue position (cases ahead) rather than a clearance date.
                </div>
              )}
            </div>
          )}

          <SectionHeader>Spread history — {country} (EB2 cutoff minus EB3 cutoff)</SectionHeader>
          {sloading ? (
            <div style={{ color: "var(--text3)", fontSize: 13 }}>Loading…</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: "var(--text3)", fontSize: 11 }}>
                    <th style={{ textAlign: "left", padding: "5px 8px", borderBottom: "1px solid var(--border)" }}>Bulletin</th>
                    <th style={{ textAlign: "left", padding: "5px 8px", borderBottom: "1px solid var(--border)" }}>EB2 cutoff</th>
                    <th style={{ textAlign: "left", padding: "5px 8px", borderBottom: "1px solid var(--border)" }}>EB3 cutoff</th>
                    <th style={{ textAlign: "right", padding: "5px 8px", borderBottom: "1px solid var(--border)" }}>Spread (days)</th>
                    <th style={{ textAlign: "left", padding: "5px 8px", borderBottom: "1px solid var(--border)" }}>Regime</th>
                  </tr>
                </thead>
                <tbody>
                  {(spread?.history || []).slice(-24).reverse().map((r, i) => {
                    const sd = r.spread_days;
                    const reg = sd == null ? "unknown" : sd < -60 ? "eb3_ahead" : sd > 60 ? "eb2_ahead" : "near_parity";
                    return (
                      <tr key={i} style={{ borderBottom: "1px solid var(--border)22" }}>
                        <td style={{ padding: "5px 8px", fontFamily: "monospace" }}>{fmtDate(r.bulletin_date)}</td>
                        <td style={{ padding: "5px 8px", fontFamily: "monospace" }}>{fmtDate(r.eb2_cutoff)}</td>
                        <td style={{ padding: "5px 8px", fontFamily: "monospace" }}>{fmtDate(r.eb3_cutoff)}</td>
                        <td style={{ padding: "5px 8px", textAlign: "right", fontFamily: "monospace", color: sd > 0 ? "#27815f" : sd < 0 ? "#b47718" : "var(--text)" }}>
                          {sd != null ? (sd > 0 ? `+${sd}` : sd) : "—"}
                        </td>
                        <td style={{ padding: "5px 8px" }}><RegimeBadge regime={reg} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : (
        <div style={{ color: "var(--text3)", fontSize: 13, padding: "20px 0" }}>
          The EB2/EB3 spread regime analysis applies only to EB2 and EB3 categories. Select EB2 or EB3 to see regime data for {country}.
        </div>
      )}
    </div>
  );
}

// ─── Tier 3: Queue Position Panel ────────────────────────────────────────────

function QueuePositionPanel({ country, category }) {
  const [priorityYear, setPriorityYear] = useState(2013);
  const [priorityMonth, setPriorityMonth] = useState("");
  const [queried, setQueried] = useState(null);

  const { data, loading, error } = useFetch(
    queried
      ? `${API}/eb-inventory/queue-position?country=${encodeURIComponent(queried.country)}&category=${queried.category}&priority_year=${queried.year}${queried.month ? `&priority_month=${queried.month}` : ""}`
      : null
  );

  const run = () => setQueried({ country, category, year: priorityYear, month: priorityMonth });

  return (
    <div>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", marginBottom: 24, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.05em" }}>Priority year</div>
          <input
            type="number" value={priorityYear}
            onChange={e => setPriorityYear(parseInt(e.target.value))}
            min={1990} max={2026}
            style={{ width: 90, padding: "7px 10px", background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius)", color: "var(--text)", fontSize: 14 }}
          />
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.05em" }}>Priority month (optional)</div>
          <select value={priorityMonth} onChange={e => setPriorityMonth(e.target.value)}
            style={{ padding: "7px 10px", background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius)", color: "var(--text)", fontSize: 14 }}>
            <option value="">Any</option>
            {MONTHS.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <button onClick={run}
          style={{ padding: "8px 20px", background: "var(--amber, #b47718)", border: "none", borderRadius: "var(--radius)", color: "#000", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
          Check queue
        </button>
      </div>

      {loading && <div style={{ color: "var(--text3)", fontSize: 13 }}>Loading…</div>}
      {error && <div style={{ color: "#bf4b4b", fontSize: 13 }}>Error: {JSON.stringify(error)}</div>}

      {data && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 24 }}>
            <StatCard label="Cases ahead" value={fmt(data.cases_ahead)} sub="approx pending I-485s" accent="#315f7c" />
            <StatCard label="Cases in PY" value={fmt(data.cases_in_priority_year)} sub={`${data.priority_year} total`} />
            <StatCard label="Current cutoff" value={data.cutoff_unavailable ? "Unavailable" : fmtDate(data.current_cutoff)} sub={`as of ${fmtDate(data.latest_bulletin)}`} />
            <StatCard label="Avg monthly advance" value={data.avg_monthly_advance_days != null ? `${data.avg_monthly_advance_days}d` : "—"} sub="days/month (12mo avg)" />
          </div>

          <div style={{
            padding: "14px 16px", marginBottom: 20,
            background: "var(--bg2)", border: "1px solid var(--border)",
            borderRadius: "var(--radius)", fontSize: 13
          }}>
            <div style={{ fontWeight: 500, marginBottom: 6 }}>
              {country} {category} — PY {data.priority_year}{data.priority_month ? ` (${data.priority_month})` : ""}
            </div>
            <div style={{ color: "var(--text3)", fontSize: 12, lineHeight: 1.6 }}>
              {fmt(data.cases_ahead)} pending I-485 applications are currently ahead of this priority date in USCIS inventory. This count covers only cases already filed — it does not include the{" "}
              {country === "India" ? "~486,000" : "many"} approved I-140 petitioners who have not yet filed I-485. Priority date advancement is controlled by DOS visa number management, not USCIS inventory levels.
            </div>
            {data.clearance_date_note && (
              <div style={{ marginTop: 8, color: "#bf4b4b", fontSize: 12 }}>{data.clearance_date_note}</div>
            )}
          </div>

          <SectionHeader>Recent cutoff advancement — {country} {category}</SectionHeader>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ color: "var(--text3)", fontSize: 11 }}>
                  <th style={{ textAlign: "left", padding: "5px 8px", borderBottom: "1px solid var(--border)" }}>Bulletin</th>
                  <th style={{ textAlign: "left", padding: "5px 8px", borderBottom: "1px solid var(--border)" }}>Cutoff date</th>
                  <th style={{ textAlign: "right", padding: "5px 8px", borderBottom: "1px solid var(--border)" }}>Advance (days)</th>
                </tr>
              </thead>
              <tbody>
                {(data.advance_history || []).map((r, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--border)22" }}>
                    <td style={{ padding: "5px 8px", fontFamily: "monospace" }}>{fmtDate(r.bulletin_date)}</td>
                    <td style={{ padding: "5px 8px", fontFamily: "monospace" }}>{fmtDate(r.priority_date)}</td>
                    <td style={{ padding: "5px 8px", textAlign: "right", fontFamily: "monospace", color: r.advance_days > 0 ? "#27815f" : "#bf4b4b" }}>
                      {r.advance_days > 0 ? `+${r.advance_days}` : r.advance_days}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ─── Main view ───────────────────────────────────────────────────────────────

export function EbInventoryView() {
  const [country,  setCountry]  = useState("India");
  const [category, setCategory] = useState("EB2");
  const [activeTab, setActiveTab] = useState(null); // auto-set on country/cat change

  const t = tier(country, category);

  // Auto-select the best tab for this combination
  useEffect(() => {
    if (t === 1) setActiveTab("forecast");
    else if (category === "EB2" || category === "EB3") setActiveTab("regime");
    else setActiveTab("queue");
  }, [country, category, t]);

  const tabs = [
    ...(t === 1 ? [{ id: "forecast", label: "Forecast", accent: "#27815f",
      desc: `Tier 1 — backtest MAE ~${{"Philippines|EB3":0.8,"Mexico|EB2":1.3,"Mexico|EB3":1.7,"Philippines|EB2":2.1,"Rest of the World|EB3":3.3}[`${country}|${category}`] ?? "—"} months` }] : []),
    ...((category === "EB2" || category === "EB3") ? [{ id: "regime", label: "Regime monitor", accent: "#b47718", desc: "Tier 2 — EB2/EB3 spread and regime history" }] : []),
    { id: "queue", label: "Queue position", accent: "#315f7c", desc: "Tier 3 — cases ahead of a priority date" },
  ];

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "28px 32px 48px", maxWidth: 1100, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 22, fontWeight: 500, color: "var(--text)", marginBottom: 6 }}>
          EB Inventory &amp; Priority Date Analysis
        </div>
        <div style={{ fontSize: 13, color: "var(--text3)" }}>
          Based on 25 monthly USCIS snapshots (Feb 2024 – Apr 2026) × 5 countries × 7 categories — 74,052 observations.
        </div>
      </div>

      {/* Country + Category selectors */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.05em" }}>Country of chargeability</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {COUNTRIES.map(c => (
              <button key={c} onClick={() => setCountry(c)}
                style={{ padding: "5px 12px", fontSize: 12, fontWeight: 500, cursor: "pointer",
                  background: country === c ? "var(--amber, #b47718)" : "var(--bg2)",
                  color: country === c ? "#000" : "var(--text3)",
                  border: "1px solid var(--border)", borderRadius: "var(--radius)",
                  transition: "all 0.15s" }}>
                {c}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.05em" }}>Category</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {CATEGORIES.map(c => (
              <button key={c} onClick={() => setCategory(c)}
                style={{ padding: "5px 12px", fontSize: 12, fontWeight: 500, cursor: "pointer",
                  background: category === c ? "var(--amber, #b47718)" : "var(--bg2)",
                  color: category === c ? "#000" : "var(--text3)",
                  border: "1px solid var(--border)", borderRadius: "var(--radius)",
                  transition: "all 0.15s" }}>
                {c}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Tier badge */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 20 }}>
        <span style={{
          fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase",
          padding: "3px 10px", borderRadius: 4,
          background: t === 1 ? "#27815f20" : t === 2 ? "#b4771820" : "#315f7c20",
          color:      t === 1 ? "#27815f"   : t === 2 ? "#b47718"   : "#315f7c",
          border:     `1px solid ${t === 1 ? "#27815f40" : t === 2 ? "#b4771840" : "#315f7c40"}`,
        }}>
          Tier {t}
        </span>
        <span style={{ fontSize: 12, color: "var(--text3)" }}>
          {t === 1 && "High-accuracy forecaster — backtest MAE 0.8–3.3 months"}
          {t === 2 && "Regime monitor — reliable only when EB2 is ahead of EB3"}
          {t === 3 && "Queue position only — no clearance date available"}
        </span>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 0, marginBottom: 24, borderBottom: "1px solid var(--border)" }}>
        {tabs.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            style={{
              padding: "9px 18px", fontSize: 13, fontWeight: 500, cursor: "pointer",
              background: "none", border: "none",
              borderBottom: activeTab === tab.id ? `2px solid ${tab.accent}` : "2px solid transparent",
              color: activeTab === tab.id ? tab.accent : "var(--text3)",
              marginBottom: -1, transition: "color 0.15s",
            }}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab description */}
      {tabs.find(t => t.id === activeTab) && (
        <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 20 }}>
          {tabs.find(t => t.id === activeTab).desc}
        </div>
      )}

      {/* Tab content */}
      {activeTab === "forecast" && t === 1 && <ForecastPanel country={country} category={category} />}
      {activeTab === "regime"   && <RegimePanel country={country} category={category} />}
      {activeTab === "queue"    && <QueuePositionPanel country={country} category={category} />}
    </div>
  );
}
