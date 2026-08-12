/**
 * WageDashboard.jsx
 * July 1 Wage Comparer — actual 2026-27 OFLC wages vs 2025-26
 *
 * Panels:
 *  1. Header summary cards (avg change, movers count, etc.)
 *  2. US heat map — H-1B filings by state, click to drill into MSA
 *  3. Area wage diff chart — top 10 SOCs for selected area, old vs new
 *  4. Top movers — biggest SOC-level risers and fallers (bar chart)
 *  5. Employer exposure — Level I concentration for top filers (bubble/bar)
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { API } from "./apiBase";
import { US_MAP_VIEWBOX, US_STATE_PATHS } from "./usStatePaths";
import TreemapPanel from "./TreemapPanel";

// ── Tiny helpers ──────────────────────────────────────────────────────────────
const fmt$ = (n) => n == null ? "—" : "$" + Math.round(n).toLocaleString();
const fmtPct = (n) => n == null ? "—" : (n >= 0 ? "+" : "") + n.toFixed(1) + "%";
const pctColor = (n, dark) => {
  if (n == null) return dark ? "#8795a1" : "#73808c";
  if (n > 5)  return dark ? "#55b989" : "#27815f";
  if (n < 0)  return dark ? "#e06b6b" : "#bf4b4b";
  return dark ? "#d89a35" : "#b47718";
};

function useTheme() {
  const [dark, setDark] = useState(
    () => document.documentElement.getAttribute("data-theme") === "dark"
  );
  useEffect(() => {
    const obs = new MutationObserver(() =>
      setDark(document.documentElement.getAttribute("data-theme") === "dark")
    );
    obs.observe(document.documentElement, { attributes: true });
    return () => obs.disconnect();
  }, []);
  return dark;
}

function useFetch(url) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!url) return;
    setLoading(true); setError(null); setData(null);
    fetch(url)
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [url]);
  return { data, loading, error };
}

// ── State abbreviation → name map ────────────────────────────────────────────
const STATE_NAMES = {
  AL:"Alabama",AK:"Alaska",AZ:"Arizona",AR:"Arkansas",CA:"California",
  CO:"Colorado",CT:"Connecticut",DC:"Dist. Columbia",DE:"Delaware",FL:"Florida",
  GA:"Georgia",HI:"Hawaii",ID:"Idaho",IL:"Illinois",IN:"Indiana",IA:"Iowa",
  KS:"Kansas",KY:"Kentucky",LA:"Louisiana",ME:"Maine",MD:"Maryland",
  MA:"Massachusetts",MI:"Michigan",MN:"Minnesota",MS:"Mississippi",MO:"Missouri",
  MT:"Montana",NE:"Nebraska",NV:"Nevada",NH:"New Hampshire",NJ:"New Jersey",
  NM:"New Mexico",NY:"New York",NC:"North Carolina",ND:"North Dakota",OH:"Ohio",
  OK:"Oklahoma",OR:"Oregon",PA:"Pennsylvania",RI:"Rhode Island",SC:"South Carolina",
  SD:"South Dakota",TN:"Tennessee",TX:"Texas",UT:"Utah",VT:"Vermont",
  VA:"Virginia",WA:"Washington",WV:"West Virginia",WI:"Wisconsin",WY:"Wyoming",
};

// ── Panel 1: Summary Cards ────────────────────────────────────────────────────
function SummaryCards({ dark }) {
  const { data, loading } = useFetch(`${API}/wages/summary`);
  const cards = data ? [
    { label: "Areas with wage decrease", value: data.decreased?.toLocaleString(), color: "var(--red)", dim: "var(--red-dim)" },
    { label: "Areas up >5%",             value: data.big_increase?.toLocaleString(), color: "var(--green)", dim: "var(--green-dim)" },
    { label: "Median Level I change",    value: fmtPct(data.median_change), color: data.median_change >= 0 ? "var(--green)" : "var(--red)", dim: data.median_change >= 0 ? "var(--green-dim)" : "var(--red-dim)" },
    { label: "Average Level I change",   value: fmtPct(data.avg_change), color: data.avg_change >= 0 ? "var(--green)" : "var(--red)", dim: data.avg_change >= 0 ? "var(--green-dim)" : "var(--red-dim)" },
  ] : [];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 24 }}>
      {loading ? [0,1,2,3].map(i => (
        <div key={i} style={{ height: 80, background: "var(--bg3)", borderRadius: "var(--radius-lg)", animation: "pulse 1.4s ease infinite" }} />
      )) : cards.map((c,i) => (
        <div key={i} style={{ background: c.dim, border: `1px solid ${c.color}30`, borderRadius: "var(--radius-lg)", padding: "16px 20px" }}>
          <div style={{ fontSize: 24, fontWeight: 600, color: c.color, lineHeight: 1.1, fontFamily: "'DM Serif Display',serif" }}>{c.value}</div>
          <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>{c.label}</div>
        </div>
      ))}
    </div>
  );
}

// ── Panel 2: US Heat Map ──────────────────────────────────────────────────────
function USHeatMap({ onStateSelect, selectedState, dark }) {
  const { data: heatData } = useFetch(`${API}/wages/heatmap/states`);
  const [hovered, setHovered] = useState(null);   // state code
  const [tooltip, setTooltip] = useState(null);   // {x, y}
  const wrapRef = useRef(null);

  const filingMap = {};
  let maxFilings = 1;
  if (heatData) {
    heatData.forEach(d => { filingMap[d.state] = d.filings; });
    maxFilings = Math.max(...heatData.map(d => d.filings));
  }

  // Sequential color scale — light-to-saturated, distinct in both themes.
  const getColor = (code) => {
    const count = filingMap[code] || 0;
    if (!count) return dark ? "#20262c" : "#eef1f4";
    const t = Math.pow(count / maxFilings, 0.4);   // perceptual boost for low values
    // Interpolate teal→deep blue (light) / dim teal→bright cyan (dark)
    const lerp = (a, b) => Math.round(a + (b - a) * t);
    return dark
      ? `rgb(${lerp(32, 96)}, ${lerp(52, 199)}, ${lerp(64, 235)})`
      : `rgb(${lerp(224, 13)}, ${lerp(237, 108)}, ${lerp(242, 165)})`;
  };

  const handleMove = (e, code) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    setHovered(code);
    setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  const fmtFilings = (n) => n >= 1000 ? `${(n/1000).toFixed(n >= 10000 ? 0 : 1)}K` : `${n}`;

  // Rank states for the side list
  const topStates = (heatData || []).slice(0, 8);

  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px 24px", marginBottom: 20 }}>
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>H-1B Filing Concentration</div>
          <div style={{ fontSize: 11, color: "var(--text3)" }}>Certified LCA worksites · click a state, then pick a metro below</div>
        </div>
        {selectedState && (
          <button onClick={() => onStateSelect(null)} style={{ fontSize: 11, padding: "4px 10px", background: "var(--bg3)", border: "1px solid var(--border)", color: "var(--text2)" }}>
            ✕ {STATE_NAMES[selectedState] || selectedState}
          </button>
        )}
      </div>

      <div className="m-stack" style={{ display: "grid", gridTemplateColumns: "1fr 168px", gap: 16 }}>
        {/* Map */}
        <div ref={wrapRef} style={{ position: "relative" }}>
          <svg viewBox={US_MAP_VIEWBOX} style={{ width: "100%", height: "auto", display: "block" }}>
            {Object.entries(US_STATE_PATHS).map(([code, d]) => {
              const isSel = selectedState === code;
              const isHov = hovered === code;
              return (
                <path
                  key={code}
                  d={d}
                  fill={getColor(code)}
                  stroke={isSel ? "var(--accent)" : (dark ? "#3a444d" : "#ffffff")}
                  strokeWidth={isSel ? 2.5 : 1}
                  strokeLinejoin="round"
                  style={{
                    cursor: "pointer",
                    transition: "filter 0.12s, opacity 0.12s",
                    filter: isHov ? "brightness(1.18)" : "none",
                    opacity: selectedState && !isSel && !isHov ? 0.55 : 1,
                  }}
                  onClick={() => onStateSelect(isSel ? null : code)}
                  onMouseMove={(e) => handleMove(e, code)}
                  onMouseLeave={() => { setHovered(null); setTooltip(null); }}
                >
                </path>
              );
            })}
          </svg>

          {/* Tooltip */}
          {tooltip && hovered && (
            <div style={{
              position: "absolute",
              left: Math.min(tooltip.x + 14, (wrapRef.current?.clientWidth || 600) - 170),
              top: tooltip.y - 54,
              background: dark ? "#242b31" : "#ffffff",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "8px 12px",
              pointerEvents: "none",
              boxShadow: "0 6px 20px rgba(0,0,0,0.18)",
              fontSize: 12, zIndex: 10, whiteSpace: "nowrap",
            }}>
              <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>
                {STATE_NAMES[hovered] || hovered}
              </div>
              <div style={{ color: "var(--text3)" }}>
                {(filingMap[hovered] || 0).toLocaleString()} certified filings
              </div>
            </div>
          )}

          {/* Gradient legend */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
            <span style={{ fontSize: 10, color: "var(--text3)" }}>0</span>
            <div style={{ flex: "0 0 120px", height: 8, borderRadius: 4, background: dark
              ? "linear-gradient(to right, #202c34, #60c7eb)"
              : "linear-gradient(to right, #e0edf2, #0d6ca5)" }} />
            <span style={{ fontSize: 10, color: "var(--text3)" }}>{fmtFilings(maxFilings)} filings</span>
          </div>
        </div>

        {/* Top-8 ranked list — quick-click alternative to hunting on the map */}
        <div style={{ borderLeft: "1px solid var(--border)", paddingLeft: 14 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            Top states
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {topStates.map((s, i) => {
              const isSel = selectedState === s.state;
              return (
                <button
                  key={s.state}
                  onClick={() => onStateSelect(isSel ? null : s.state)}
                  onMouseEnter={() => setHovered(s.state)}
                  onMouseLeave={() => setHovered(null)}
                  style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "5px 8px", fontSize: 11, textAlign: "left",
                    background: isSel ? "var(--accent-dim, var(--bg3))" : "transparent",
                    border: `1px solid ${isSel ? "var(--accent)" : "transparent"}`,
                    borderRadius: "var(--radius)",
                    color: "var(--text)", cursor: "pointer",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <span style={{ width: 9, height: 9, borderRadius: 2, background: getColor(s.state), border: `1px solid ${dark ? "#3a444d" : "#d7dde3"}`, flexShrink: 0 }} />
                    <span style={{ fontWeight: isSel ? 600 : 500 }}>{s.state}</span>
                  </span>
                  <span style={{ color: "var(--text3)", fontVariantNumeric: "tabular-nums" }}>{fmtFilings(s.filings)}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Panel 3: Area Wage Comparison ─────────────────────────────────────────────
function AreaWagePanel({ areaCode, areaName, dark }) {
  const { data, loading } = useFetch(areaCode ? `${API}/wages/compare/area/${areaCode}` : null);

  if (!areaCode) return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "32px 24px", marginBottom: 20, textAlign: "center" }}>
      <div style={{ fontSize: 32, marginBottom: 8 }}>🗺️</div>
      <div style={{ fontSize: 13, color: "var(--text3)" }}>Click a state on the map, then select an MSA below to compare wages</div>
    </div>
  );

  if (loading) return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: 24, marginBottom: 20 }}>
      <div style={{ height: 260, background: "var(--bg3)", borderRadius: "var(--radius)", animation: "pulse 1.4s ease infinite" }} />
    </div>
  );

  if (!data || data.length === 0) return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: 24, marginBottom: 20 }}>
      <div style={{ color: "var(--text3)", textAlign:"center", padding: "24px 0" }}>No wage data found for this area.</div>
    </div>
  );

  const maxWage = Math.max(...data.flatMap(d => [d.cur.I, d.cur.IV, d.prior.I, d.prior.IV].filter(Boolean)));

  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px 24px", marginBottom: 20 }}>
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>
          Top 10 H-1B Occupations — {areaName}
        </div>
        <div style={{ fontSize: 11, color: "var(--text3)" }}>
          2025-26 vs 2026-27 ALC wages · Level I (entry) bars shown · hover for all levels
        </div>
      </div>

      <div className="m-scroll-x" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {data.map((row, i) => {
          const chg = row.change_pct?.I;
          const barWidth = (v) => v ? `${(v / maxWage * 100).toFixed(1)}%` : "0%";
          const barH = 8;
          return (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "200px 1fr 80px 80px 72px", gap: 12, alignItems: "center", minWidth: 560 }}>
              {/* SOC label */}
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text)", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}
                  title={`${row.soc_code} — ${row.soc_title}`}>
                  {row.soc_title?.split(",")[0] || row.soc_code}
                </div>
                <div style={{ fontSize: 10, color: "var(--text3)" }}>{row.soc_code}</div>
              </div>
              {/* Dual bars */}
              <div>
                {/* Prior year */}
                <div style={{ marginBottom: 3, display:"flex", alignItems:"center", gap: 6 }}>
                  <div style={{ width: barWidth(row.prior?.I), height: barH, background: dark ? "#2b333a" : "#d7dde3", borderRadius: 2, transition:"width 0.4s", minWidth: 2 }} />
                </div>
                {/* Current year */}
                <div style={{ display:"flex", alignItems:"center", gap: 6 }}>
                  <div style={{ width: barWidth(row.cur?.I), height: barH, background: chg > 5 ? (dark?"#55b989":"#27815f") : chg < 0 ? (dark?"#e06b6b":"#bf4b4b") : "var(--accent)", borderRadius: 2, transition:"width 0.4s", minWidth: 2 }} />
                </div>
              </div>
              {/* Prior value */}
              <div style={{ textAlign:"right" }}>
                <div style={{ fontSize: 10, color: "var(--text3)", marginBottom: 2 }}>2025-26</div>
                <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text2)" }}>{fmt$(row.prior?.I ? row.prior.I * 2080 : null)}</div>
              </div>
              {/* Current value */}
              <div style={{ textAlign:"right" }}>
                <div style={{ fontSize: 10, color: "var(--text3)", marginBottom: 2 }}>2026-27</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>{fmt$(row.cur?.I ? row.cur.I * 2080 : null)}</div>
              </div>
              {/* Change badge */}
              <div style={{ textAlign:"right" }}>
                <span style={{
                  fontSize: 11, fontWeight: 600,
                  color: pctColor(chg, dark),
                  background: chg > 5 ? (dark?"#55b98920":"#27815f15") : chg < 0 ? (dark?"#e06b6b20":"#bf4b4b15") : "var(--bg3)",
                  borderRadius: 4, padding: "2px 6px",
                }}>
                  {fmtPct(chg)}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div style={{ display:"flex", gap: 16, marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
        {[
          { color: dark?"#2b333a":"#d7dde3", label: "2025-26 (prior year)" },
          { color: "var(--accent)", label: "2026-27 <5% change" },
          { color: dark?"#55b989":"#27815f", label: ">5% increase" },
          { color: dark?"#e06b6b":"#bf4b4b", label: "Decrease" },
        ].map((l,i) => (
          <div key={i} style={{ display:"flex", alignItems:"center", gap: 5 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: l.color }} />
            <span style={{ fontSize: 10, color: "var(--text3)" }}>{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Panel 4: Top Movers ───────────────────────────────────────────────────────
function TopMoversPanel({ dark }) {
  const [direction, setDirection] = useState("up");
  const { data, loading } = useFetch(`${API}/wages/movers?direction=${direction}&limit=12`);

  const maxAbs = data ? Math.max(...data.map(d => Math.abs(d.avg_change_pct))) : 1;

  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px 24px" }}>
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>Biggest Movers</div>
          <div style={{ fontSize: 11, color: "var(--text3)" }}>Average Level I wage change across ≥20 areas</div>
        </div>
        <div style={{ display:"flex", gap: 6 }}>
          {["up","down"].map(d => (
            <button key={d} onClick={() => setDirection(d)} style={{
              fontSize: 11, padding: "4px 10px",
              background: direction === d ? (d==="up" ? "var(--green-dim)" : "var(--red-dim)") : "var(--bg3)",
              border: `1px solid ${direction===d ? (d==="up" ? "var(--green)" : "var(--red)") : "var(--border)"}`,
              color: direction===d ? (d==="up" ? "var(--green)" : "var(--red)") : "var(--text2)",
            }}>
              {d === "up" ? "↑ Rising" : "↓ Falling"}
            </button>
          ))}
        </div>
      </div>

      {loading ? <div style={{ height: 200, background: "var(--bg3)", borderRadius: "var(--radius)", animation: "pulse 1.4s ease infinite" }} />
        : (
        <div style={{ display:"flex", flexDirection:"column", gap: 6 }}>
          {(data || []).map((row, i) => {
            const barW = Math.abs(row.avg_change_pct) / maxAbs * 100;
            const isUp = row.avg_change_pct > 0;
            return (
              <div key={i} style={{ display:"grid", gridTemplateColumns:"180px 1fr 56px", gap: 10, alignItems:"center" }}>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color:"var(--text)", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}
                    title={`${row.soc_code} — ${row.soc_title}`}>
                    {row.soc_title?.split(",")[0] || row.soc_code}
                  </div>
                  <div style={{ fontSize: 10, color:"var(--text3)" }}>{row.soc_code} · {row.areas} areas</div>
                </div>
                <div style={{ background:"var(--bg3)", borderRadius: 3, height: 10, overflow:"hidden" }}>
                  <div style={{
                    height:"100%", width:`${barW}%`,
                    background: isUp ? (dark?"#55b989":"#27815f") : (dark?"#e06b6b":"#bf4b4b"),
                    borderRadius: 3, transition: "width 0.5s",
                  }} />
                </div>
                <div style={{ textAlign:"right", fontSize: 12, fontWeight: 600, color: pctColor(row.avg_change_pct, dark) }}>
                  {fmtPct(row.avg_change_pct)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Shared matrix table: rows=SOCs, cols=areas, diverging change cells ───────
// Used by both the fixed Wage Change Matrix and the custom matrix builder.
function MatrixTable({ dark, data }) {
  const [hover, setHover] = useState(null); // {s, a, cell, x, y}
  const wrapRef = useRef(null);

  // Diverging color: red (down) -> neutral -> green (up), scaled to ±10%
  const cellColor = (chg) => {
    if (chg == null) return dark ? "#20262c" : "#f0f2f4";
    const t = Math.max(-1, Math.min(1, chg / 10));
    if (t >= 0) {
      const s = Math.pow(t, 0.7);
      return dark
        ? `rgb(${Math.round(38-8*s)}, ${Math.round(50+120*s)}, ${Math.round(52+60*s)})`
        : `rgb(${Math.round(240-190*s)}, ${Math.round(245-90*s)}, ${Math.round(240-150*s)})`;
    } else {
      const s = Math.pow(-t, 0.7);
      return dark
        ? `rgb(${Math.round(46+130*s)}, ${Math.round(48-10*s)}, ${Math.round(50-6*s)})`
        : `rgb(${Math.round(246)}, ${Math.round(240-120*s)}, ${Math.round(238-110*s)})`;
    }
  };

  const shortArea = (name) => (name || "").split(",")[0].split("-")[0].trim();
  const shortSoc  = (title, code) => (title || code).split(",")[0];

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "separate", borderSpacing: 2, width: "100%" }}>
            <thead>
              <tr>
                <th style={{ minWidth: 150 }}></th>
                {data.areas.map((a) => (
                  <th key={a.area_code} title={a.area_name}
                      style={{ fontSize: 9.5, fontWeight: 600, color: "var(--text3)", padding: "0 2px 6px", textTransform: "uppercase", letterSpacing: "0.03em", whiteSpace: "nowrap", maxWidth: 64, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {shortArea(a.area_name)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.socs.map((s, si) => (
                <tr key={s.soc_code}>
                  <td title={`${s.soc_code} — ${s.soc_title}${s.filings != null ? ` · ${s.filings.toLocaleString()} H-1B filings` : ""}`}
                      style={{ fontSize: 11, fontWeight: 500, color: "var(--text)", paddingRight: 10, whiteSpace: "nowrap", maxWidth: 170, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {shortSoc(s.soc_title, s.soc_code)}
                  </td>
                  {data.areas.map((a, ai) => {
                    const cell = data.cells[`${s.soc_code}|${a.area_code}`] || {};
                    const chg = cell.change_pct;
                    return (
                      <td key={a.area_code}
                          onMouseEnter={(e) => {
                            const rect = wrapRef.current?.getBoundingClientRect();
                            if (rect) setHover({ s, a, cell, x: e.clientX - rect.left, y: e.clientY - rect.top });
                          }}
                          onMouseLeave={() => setHover(null)}
                          style={{
                            background: cellColor(chg),
                            height: 26, minWidth: 46,
                            borderRadius: 3, textAlign: "center",
                            fontSize: 9.5, fontWeight: 600, cursor: "default",
                            fontVariantNumeric: "tabular-nums",
                            color: chg == null ? "var(--text3)"
                              : Math.abs(chg) > 5.5 ? "#fff"
                              : (dark ? "#c7d0d8" : "#374550"),
                            outline: hover?.s === s && hover?.a === a ? "2px solid var(--accent)" : "none",
                          }}>
                        {chg == null ? "·" : (chg > 0 ? "+" : "") + chg.toFixed(1)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

      {hover && (
        <div style={{
          position: "absolute",
          left: Math.min(hover.x + 14, (wrapRef.current?.clientWidth || 700) - 240),
          top: hover.y - 76,
          background: dark ? "#242b31" : "#fff",
          border: "1px solid var(--border)", borderRadius: "var(--radius)",
          padding: "9px 12px", pointerEvents: "none", zIndex: 10,
          boxShadow: "0 6px 20px rgba(0,0,0,0.18)", fontSize: 11.5, whiteSpace: "nowrap",
        }}>
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>{hover.s.soc_code} · {shortSoc(hover.s.soc_title, "")}</div>
          <div style={{ color: "var(--text3)", marginBottom: 4 }}>{hover.a.area_name}</div>
          {hover.cell.change_pct == null ? (
            <div style={{ color: "var(--text3)" }}>No comparable data (geo tier changed)</div>
          ) : (
            <div style={{ color: "var(--text2)" }}>
              {fmt$(hover.cell.prior_annual)} → <b style={{ color: "var(--text)" }}>{fmt$(hover.cell.cur_annual)}</b>
              <span style={{ marginLeft: 8, fontWeight: 700, color: pctColor(hover.cell.change_pct, dark) }}>{fmtPct(hover.cell.change_pct)}</span>
            </div>
          )}
        </div>
      )}

      {/* Diverging legend */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10 }}>
        <span style={{ fontSize: 10, color: "var(--text3)" }}>-10%</span>
        <div style={{ width: 140, height: 8, borderRadius: 4, background: dark
          ? "linear-gradient(to right, #b02e2c, #2e3234, #26aa70)"
          : "linear-gradient(to right, #f67872, #f0f2f4, #32977a)" }} />
        <span style={{ fontSize: 10, color: "var(--text3)" }}>+10%</span>
        <span style={{ fontSize: 10, color: "var(--text3)", marginLeft: 10 }}>· = geo tier changed, not comparable</span>
      </div>
    </div>
  );
}

// ── Panel 5: SOC x Metro Change Matrix ────────────────────────────────────────
function MatrixPanel({ dark }) {
  const { data, loading } = useFetch(`${API}/wages/matrix?n_socs=14&n_areas=12`);
  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px 24px", marginBottom: 20 }}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>Wage Change Matrix — Top Occupations × Top Metros</div>
        <div style={{ fontSize: 11, color: "var(--text3)" }}>Level I % change, 2025-26 → 2026-27 · rows ranked by H-1B volume · hover any cell for detail</div>
      </div>
      {loading || !data ? (
        <div style={{ height: 340, background: "var(--bg3)", borderRadius: "var(--radius)", animation: "pulse 1.4s ease infinite" }} />
      ) : (
        <MatrixTable dark={dark} data={data} />
      )}
    </div>
  );
}

// ── Panel 5b: Custom Wage Comparison builder ─────────────────────────────────
// Typeahead search input with removable chips; used for both SOCs and areas.
function ChipPicker({ dark, label, placeholder, endpoint, selected, setSelected,
                      itemKey, renderOption, renderChip, max = 20 }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);
  const boxRef = useRef(null);

  useEffect(() => {
    if (query.length < 2) { setResults([]); setOpen(false); return; }
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetch(`${API}${endpoint}?q=${encodeURIComponent(query)}`)
        .then(r => r.json())
        .then(d => { setResults(d); setOpen(true); })
        .catch(() => {});
    }, 250);
    return () => clearTimeout(debounceRef.current);
  }, [query, endpoint]);

  useEffect(() => {
    const onDoc = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const add = (item) => {
    if (selected.length < max && !selected.some(s => itemKey(s) === itemKey(item))) {
      setSelected([...selected, item]);
    }
    setQuery(""); setResults([]); setOpen(false);
  };
  const remove = (item) => setSelected(selected.filter(s => itemKey(s) !== itemKey(item)));

  return (
    <div ref={boxRef} style={{ flex: 1, minWidth: 260, position: "relative" }}>
      <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 6 }}>{label}</div>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => { if (results.length) setOpen(true); }}
        placeholder={placeholder}
        style={{
          width: "100%", boxSizing: "border-box", padding: "8px 11px",
          fontSize: 12.5, color: "var(--text)", background: "var(--bg)",
          border: "1px solid var(--border)", borderRadius: "var(--radius)",
          outline: "none",
        }}
      />
      {open && results.length > 0 && (
        <div style={{
          position: "absolute", top: "100%", left: 0, right: 0, marginTop: 4,
          background: dark ? "#242b31" : "#fff", border: "1px solid var(--border)",
          borderRadius: "var(--radius)", boxShadow: "0 6px 20px rgba(0,0,0,0.18)",
          zIndex: 20, maxHeight: 260, overflowY: "auto",
        }}>
          {results.map((r) => (
            <div key={itemKey(r)} onMouseDown={() => add(r)}
                 style={{ padding: "7px 11px", fontSize: 12, cursor: "pointer", color: "var(--text)", borderBottom: "1px solid var(--border)" }}
                 onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg3)"}
                 onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
              {renderOption(r)}
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8, minHeight: 24 }}>
        {selected.map((s) => (
          <span key={itemKey(s)} style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "3px 9px", fontSize: 11, fontWeight: 500,
            background: "var(--bg3)", border: "1px solid var(--border)",
            borderRadius: 999, color: "var(--text)", whiteSpace: "nowrap",
          }}>
            {renderChip(s)}
            <span onClick={() => remove(s)} style={{ cursor: "pointer", color: "var(--text3)", fontWeight: 700, fontSize: 12, lineHeight: 1 }}>×</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function CustomMatrixPanel({ dark }) {
  const [socs, setSocs] = useState([]);     // [{soc_code, soc_title}]
  const [areas, setAreas] = useState([]);   // [{area_code, area_name, state}]

  const url = socs.length && areas.length
    ? `${API}/wages/matrix/custom?socs=${encodeURIComponent(socs.map(s => s.soc_code).join(","))}&areas=${encodeURIComponent(areas.map(a => a.area_code).join(","))}`
    : null;
  const { data, loading } = useFetch(url);

  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px 24px", marginBottom: 20 }}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>Custom Wage Comparison</div>
        <div style={{ fontSize: 11, color: "var(--text3)" }}>Build your own matrix — pick occupations (rows) and locations (columns) · Level I % change, 2025-26 → 2026-27</div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 18, marginBottom: 16 }}>
        <ChipPicker
          dark={dark} label="Occupations (rows)" placeholder="Search SOC code or title…"
          endpoint="/wages/soc-search"
          selected={socs} setSelected={setSocs}
          itemKey={(s) => s.soc_code}
          renderOption={(s) => <><b>{s.soc_code}</b> · {s.soc_title}</>}
          renderChip={(s) => `${s.soc_code} ${(s.soc_title || "").split(",")[0]}`}
        />
        <ChipPicker
          dark={dark} label="Locations (columns)" placeholder="Search metro or area name…"
          endpoint="/wages/area-search"
          selected={areas} setSelected={setAreas}
          itemKey={(a) => a.area_code}
          renderOption={(a) => <>{a.area_name}</>}
          renderChip={(a) => (a.area_name || "").split(",")[0]}
        />
      </div>

      {!url ? (
        <div style={{ padding: "26px 0", textAlign: "center", fontSize: 12, color: "var(--text3)" }}>
          Select at least one occupation and one location to build the comparison.
        </div>
      ) : loading || !data ? (
        <div style={{ height: 120, background: "var(--bg3)", borderRadius: "var(--radius)", animation: "pulse 1.4s ease infinite" }} />
      ) : (
        <MatrixTable dark={dark} data={data} />
      )}
    </div>
  );
}

// ── Panel 6: SOC Explorer ─────────────────────────────────────────────────────
function SocExplorerPanel({ dark }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);   // {soc_code, soc_title}
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => {
    if (query.length < 2) { setResults([]); return; }
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetch(`${API}/wages/soc-search?q=${encodeURIComponent(query)}`)
        .then(r => r.json())
        .then(d => { setResults(d); setOpen(true); })
        .catch(() => {});
    }, 250);
    return () => clearTimeout(debounceRef.current);
  }, [query]);

  const { data: areas, loading } = useFetch(
    selected ? `${API}/wages/soc/${selected.soc_code}/areas?limit=20` : null
  );

  const maxAbs = areas?.length ? Math.max(...areas.map(a => Math.abs(a.change_pct))) : 1;

  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px 24px", marginBottom: 20 }}>
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>SOC Explorer</div>
        <div style={{ fontSize: 11, color: "var(--text3)" }}>Search any occupation to see its top 20 Level I wage gains and top 20 reductions by metro</div>
      </div>

      {/* Search box */}
      <div style={{ position: "relative", maxWidth: 460, marginBottom: 14 }}>
        <input
          value={selected ? `${selected.soc_code} — ${selected.soc_title}` : query}
          onChange={(e) => { setSelected(null); setQuery(e.target.value); }}
          onFocus={() => results.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 180)}
          placeholder="Try: software, 29-1141, accountant, mechanical engineer…"
          style={{ width: "100%" }}
        />
        {selected && (
          <button onClick={() => { setSelected(null); setQuery(""); }}
            style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", fontSize: 11, padding: "2px 8px", background: "var(--bg3)", border: "1px solid var(--border)", color: "var(--text3)" }}>
            ✕
          </button>
        )}
        {open && !selected && results.length > 0 && (
          <div style={{
            position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 20,
            background: dark ? "#242b31" : "#fff", border: "1px solid var(--border)",
            borderRadius: "var(--radius)", boxShadow: "0 8px 24px rgba(0,0,0,0.16)",
            maxHeight: 260, overflowY: "auto",
          }}>
            {results.map(r => (
              <div key={r.soc_code}
                onMouseDown={() => { setSelected(r); setOpen(false); }}
                style={{ padding: "8px 12px", fontSize: 12, cursor: "pointer", color: "var(--text)", borderBottom: "1px solid var(--border)" }}
                onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg3)"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                <b style={{ fontVariantNumeric: "tabular-nums" }}>{r.soc_code}</b>
                <span style={{ color: "var(--text2)", marginLeft: 8 }}>{r.soc_title}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      {!selected ? (
        <div style={{ padding: "26px 0", textAlign: "center", color: "var(--text3)", fontSize: 12 }}>
          Pick an occupation to see its biggest area-level wage moves
        </div>
      ) : loading ? (
        <div style={{ height: 220, background: "var(--bg3)", borderRadius: "var(--radius)", animation: "pulse 1.4s ease infinite" }} />
      ) : !areas?.length ? (
        <div style={{ padding: "26px 0", textAlign: "center", color: "var(--text3)", fontSize: 12 }}>
          No comparable year-over-year data for this SOC
        </div>
      ) : (
        <div className="m-stack" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 28px", alignItems: "start" }}>
          {[["gain", "Top 20 gains"], ["reduction", "Top 20 reductions"]].map(([dir, label]) => {
            const rows = areas.filter(a => a.direction === dir);
            return (
              <div key={dir}>
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em", color: dir === "gain" ? (dark ? "#55b989" : "#27815f") : (dark ? "#e06b6b" : "#bf4b4b"), marginBottom: 6 }}>
                  {label}
                </div>
                {!rows.length ? (
                  <div style={{ fontSize: 11, color: "var(--text3)", padding: "6px 0" }}>None</div>
                ) : rows.map((a, i) => {
                  const isUp = a.change_pct >= 0;
                  const barW = Math.abs(a.change_pct) / maxAbs * 100;
                  return (
                    <div key={i} style={{ display: "grid", gridTemplateColumns: "150px 1fr 96px", gap: 8, alignItems: "center", marginBottom: 4 }}>
                      <div title={a.area_name} style={{ fontSize: 11, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {a.area_name?.split(",")[0]}
                        <span style={{ color: "var(--text3)" }}> · {a.state}</span>
                      </div>
                      <div style={{ background: "var(--bg3)", borderRadius: 3, height: 9, overflow: "hidden" }}>
                        <div style={{ height: "100%", width: `${barW}%`, background: isUp ? (dark ? "#55b989" : "#27815f") : (dark ? "#e06b6b" : "#bf4b4b"), borderRadius: 3, transition: "width 0.4s" }} />
                      </div>
                      <div style={{ fontSize: 11, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                        <span style={{ fontWeight: 700, color: pctColor(a.change_pct, dark) }}>{fmtPct(a.change_pct)}</span>
                        <span style={{ color: "var(--text3)", marginLeft: 6 }}>{fmt$(a.cur_annual)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Panel 7: State Impact Scatter ─────────────────────────────────────────────
function StateImpactScatter({ onStateSelect, selectedState, dark }) {
  const { data, loading } = useFetch(`${API}/wages/state-impact`);
  const [hovered, setHovered] = useState(null);
  const wrapRef = useRef(null);

  const W = 520, H = 300, PAD = { l: 46, r: 16, t: 14, b: 34 };

  let content = null;
  if (data?.length) {
    const logMin = Math.log10(Math.max(100, Math.min(...data.map(d => d.filings))));
    const logMax = Math.log10(Math.max(...data.map(d => d.filings)));
    const chgs   = data.map(d => d.median_change);
    const yMin   = Math.min(...chgs), yMax = Math.max(...chgs);
    const yPad   = Math.max(0.4, (yMax - yMin) * 0.12);
    const y0 = yMin - yPad, y1 = yMax + yPad;

    const xOf = (f)   => PAD.l + (Math.log10(f) - logMin) / (logMax - logMin) * (W - PAD.l - PAD.r);
    const yOf = (chg) => PAD.t + (1 - (chg - y0) / (y1 - y0)) * (H - PAD.t - PAD.b);
    const rOf = (pct) => 4 + (pct / 100) * 14;   // radius by % of combos decreased

    // X ticks at 1K / 10K / 100K
    const xticks = [1000, 10000, 100000].filter(v => v >= 10**logMin/2 && v <= 10**logMax*2);
    const yticks = [];
    for (let v = Math.ceil(y0); v <= Math.floor(y1); v++) yticks.push(v);

    content = (
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {/* grid + axes */}
        {yticks.map(v => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={yOf(v)} y2={yOf(v)}
                  stroke={dark ? "#2b333a" : "#e8ecef"} strokeWidth={v === 0 ? 1.6 : 0.7}
                  strokeDasharray={v === 0 ? "" : "3,3"} />
            <text x={PAD.l - 7} y={yOf(v) + 3} textAnchor="end" fontSize="9" fill="var(--text3)">{v > 0 ? "+" + v : v}%</text>
          </g>
        ))}
        {xticks.map(v => (
          <g key={v}>
            <line x1={xOf(v)} x2={xOf(v)} y1={PAD.t} y2={H - PAD.b} stroke={dark ? "#2b333a" : "#e8ecef"} strokeWidth="0.7" strokeDasharray="3,3" />
            <text x={xOf(v)} y={H - PAD.b + 14} textAnchor="middle" fontSize="9" fill="var(--text3)">{v >= 1000 ? `${v/1000}K` : v}</text>
          </g>
        ))}
        <text x={(PAD.l + W - PAD.r) / 2} y={H - 4} textAnchor="middle" fontSize="9.5" fill="var(--text3)">Certified H-1B filings (log scale)</text>

        {/* dots */}
        {data.map(d => {
          const isSel = selectedState === d.state;
          const isHov = hovered?.state === d.state;
          const up = d.median_change >= 0;
          return (
            <g key={d.state}
               onClick={() => onStateSelect(isSel ? null : d.state)}
               onMouseEnter={() => setHovered(d)}
               onMouseLeave={() => setHovered(null)}
               style={{ cursor: "pointer" }}>
              <circle cx={xOf(d.filings)} cy={yOf(d.median_change)} r={rOf(d.pct_decreased)}
                      fill={up ? (dark ? "#55b98955" : "#27815f2e") : (dark ? "#e06b6b55" : "#bf4b4b2e")}
                      stroke={isSel ? "var(--accent)" : (up ? (dark ? "#55b989" : "#27815f") : (dark ? "#e06b6b" : "#bf4b4b"))}
                      strokeWidth={isSel || isHov ? 2.4 : 1.2} />
              <text x={xOf(d.filings)} y={yOf(d.median_change) + 3} textAnchor="middle"
                    fontSize={rOf(d.pct_decreased) > 8 ? 8.5 : 7.5} fontWeight="600"
                    fill="var(--text)" style={{ pointerEvents: "none", userSelect: "none" }}>
                {d.state}
              </text>
            </g>
          );
        })}
      </svg>
    );
  }

  return (
    <div style={{ position: "relative", background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px 24px" }}>
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>Where Volume Meets Volatility</div>
        <div style={{ fontSize: 11, color: "var(--text3)" }}>Filing volume vs median Level I change · bubble size = share of wages that decreased · click a state to drill in</div>
      </div>
      {loading || !data ? (
        <div style={{ height: 280, background: "var(--bg3)", borderRadius: "var(--radius)", animation: "pulse 1.4s ease infinite" }} />
      ) : content}
      {hovered && (
        <div style={{
          position: "absolute", right: 20, top: 16,
          background: dark ? "#242b31" : "#fff", border: "1px solid var(--border)",
          borderRadius: "var(--radius)", padding: "9px 12px", pointerEvents: "none",
          boxShadow: "0 6px 20px rgba(0,0,0,0.18)", fontSize: 11.5, zIndex: 10,
        }}>
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 3 }}>{STATE_NAMES[hovered.state] || hovered.state}</div>
          <div style={{ color: "var(--text2)" }}>{hovered.filings.toLocaleString()} filings</div>
          <div style={{ color: pctColor(hovered.median_change, dark), fontWeight: 600 }}>median {fmtPct(hovered.median_change)}</div>
          <div style={{ color: "var(--text3)" }}>{hovered.pct_decreased}% of wages decreased</div>
        </div>
      )}
    </div>
  );
}

// ── MSA Selector (for state-selected area drill-down) ─────────────────────────
function MSASelector({ state, onSelect, selectedArea, dark }) {
  const { data, loading } = useFetch(state ? `${API}/wages/areas?state=${state}` : null);

  if (!state) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", textTransform:"uppercase", letterSpacing:"0.05em", display:"block", marginBottom: 6 }}>
        Select metro area — {STATE_NAMES[state] || state}
      </label>
      <select
        value={selectedArea?.code || ""}
        onChange={e => {
          const area = data?.find(a => a.code === e.target.value);
          onSelect(area || null);
        }}
        style={{ maxWidth: 420 }}
        disabled={loading}
      >
        <option value="">— Choose a metro area —</option>
        {(data || []).map(a => (
          <option key={a.code} value={a.code}>{a.name}</option>
        ))}
      </select>
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export function WageDashboard() {
  const dark = useTheme();
  const [selectedState, setSelectedState] = useState(null);
  const [selectedArea, setSelectedArea] = useState(null);

  const handleStateSelect = (state) => {
    setSelectedState(state);
    setSelectedArea(null);
  };

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <style>{`
        @keyframes pulse {
          0%,100% { opacity: 1; }
          50%      { opacity: 0.5; }
        }
      `}</style>
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "32px 32px 64px" }}>

        {/* Header */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 22, color: "var(--text)", marginBottom: 4 }}>
            July 1 Wage Comparer
          </div>
          <div style={{ fontSize: 12, color: "var(--text3)", lineHeight: 1.6 }}>
            2026-27 OFLC ALC prevailing wages (effective July 1, 2026) vs 2025-26 actuals ·
            Based on BLS May 2025 OEWS · {new Intl.DateTimeFormat("en-US",{month:"long",day:"numeric",year:"numeric"}).format(new Date())}
          </div>
        </div>

        {/* Summary cards */}
        <SummaryCards dark={dark} />

        {/* Heat map */}
        <USHeatMap
          onStateSelect={handleStateSelect}
          selectedState={selectedState}
          dark={dark}
        />

        {/* MSA selector + area wage panel */}
        {selectedState && (
          <>
            <MSASelector
              state={selectedState}
              selectedArea={selectedArea}
              onSelect={setSelectedArea}
              dark={dark}
            />
            <AreaWagePanel
              areaCode={selectedArea?.code || null}
              areaName={selectedArea?.name || ""}
              dark={dark}
            />
          </>
        )}

        {/* SOC hierarchy treemap drilldown */}
        <TreemapPanel dark={dark} />

        {/* Full-width change matrix */}
        <MatrixPanel dark={dark} />

        {/* User-built comparison matrix */}
        <CustomMatrixPanel dark={dark} />

        {/* SOC search explorer */}
        <SocExplorerPanel dark={dark} />

        {/* Bottom row: movers + state impact scatter */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 16 }}>
          <TopMoversPanel dark={dark} />
          <StateImpactScatter onStateSelect={handleStateSelect} selectedState={selectedState} dark={dark} />
        </div>

      </div>
    </div>
  );
}
