/**
 * TreemapPanel.jsx — SOC Hierarchy Drilldown
 * Major group → detailed SOC → metro. Tiles sized by certified H-1B
 * filing volume (metros: annual wage), colored by median Level I change
 * on a vivid diverging scale. Click to drill, breadcrumbs to climb back.
 */
import { useState, useEffect } from "react";
import { API } from "./apiBase";

const fmt$ = (n) => n == null ? "—" : "$" + Math.round(n).toLocaleString();
const fmtPct = (n) => n == null ? "—" : (n >= 0 ? "+" : "") + n.toFixed(1) + "%";

function useFetch(url) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (!url) return;
    setLoading(true); setData(null);
    fetch(url).then(r => r.json()).then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [url]);
  return { data, loading };
}

// ── Vivid diverging color scale: coral → orange → gold → green → teal ───────
const STOPS_LIGHT = [
  [-8, [190,  54,  60]], [-3, [230, 126,  34]], [0, [240, 195,  60]],
  [ 3, [ 62, 168,  96]], [ 8, [ 22, 133, 148]],
];
const STOPS_DARK = [
  [-8, [225,  82,  88]], [-3, [240, 148,  64]], [0, [235, 200,  90]],
  [ 3, [ 82, 190, 118]], [ 8, [ 52, 168, 184]],
];
function tileColor(chg, dark) {
  if (chg == null) return dark ? "#3a434c" : "#d8d4ca";
  const stops = dark ? STOPS_DARK : STOPS_LIGHT;
  const v = Math.max(stops[0][0], Math.min(stops[stops.length - 1][0], chg));
  for (let i = 0; i < stops.length - 1; i++) {
    const [v0, c0] = stops[i], [v1, c1] = stops[i + 1];
    if (v >= v0 && v <= v1) {
      const t = v1 === v0 ? 0 : (v - v0) / (v1 - v0);
      const c = c0.map((x, k) => Math.round(x + (c1[k] - x) * t));
      return `rgb(${c[0]},${c[1]},${c[2]})`;
    }
  }
  return "#888";
}

// ── Squarified treemap layout ────────────────────────────────────────────────
function squarify(items, x, y, w, h) {
  const total = items.reduce((s, d) => s + d.weight, 0);
  if (!total) return [];
  const scaled = items.map(d => ({ ...d, area: d.weight / total * w * h }));
  const rects = [];
  let row = [], rowArea = 0;

  const worst = (row, side) => {
    const sum = row.reduce((s, d) => s + d.area, 0);
    const mx = Math.max(...row.map(d => d.area));
    const mn = Math.min(...row.map(d => d.area));
    return Math.max((side * side * mx) / (sum * sum), (sum * sum) / (side * side * mn));
  };
  const layoutRow = () => {
    const sum = row.reduce((s, d) => s + d.area, 0);
    const horiz = w >= h;
    const side = horiz ? h : w;
    const thick = sum / side;
    let off = 0;
    for (const d of row) {
      const len = d.area / thick;
      rects.push(horiz
        ? { ...d, x, y: y + off, w: thick, h: len }
        : { ...d, x: x + off, y, w: len, h: thick });
      off += len;
    }
    if (horiz) { x += thick; w -= thick; } else { y += thick; h -= thick; }
  };

  for (const item of scaled) {
    const side = Math.min(w, h);
    if (!row.length || worst([...row, item], side) <= worst(row, side)) {
      row.push(item); rowArea += item.area;
    } else {
      layoutRow(); row = [item]; rowArea = item.area;
    }
  }
  if (row.length) layoutRow();
  return rects;
}

// ── Panel ────────────────────────────────────────────────────────────────────
export default function TreemapPanel({ dark }) {
  const [path, setPath] = useState([]);          // [{id,label}], depth 0–2
  const [hover, setHover] = useState(null);
  const depth = path.length;

  const url = depth === 0 ? `${API}/wages/treemap`
    : depth === 1 ? `${API}/wages/treemap?group=${path[0].id}`
    : `${API}/wages/treemap?soc=${encodeURIComponent(path[1].id)}`;
  const { data, loading } = useFetch(url);

  const W = 1000, H = 430;
  const tiles = data?.tiles?.length
    ? squarify([...data.tiles].sort((a, b) => b.weight - a.weight), 0, 0, W, H)
    : [];

  const crumb = (label, i, active) => (
    <span key={i}>
      {i > 0 && <span style={{ color: "var(--text3)", margin: "0 7px" }}>›</span>}
      <button onClick={() => !active && setPath(path.slice(0, i))}
        style={{
          background: active ? (dark ? "#2c3540" : "#eee8db") : "transparent",
          border: "1px solid " + (active ? "var(--border)" : "transparent"),
          borderRadius: 999, padding: "3px 12px", fontSize: 12,
          fontWeight: active ? 700 : 500,
          color: active ? "var(--text)" : (dark ? "#7fb3e8" : "#2563a8"),
          cursor: active ? "default" : "pointer",
        }}>
        {label}
      </button>
    </span>
  );

  const hintText = depth === 0 ? "Click a group to see its occupations"
    : depth === 1 ? "Click an occupation to see its metros"
    : "Metro level — sized by 2026-27 annual wage";

  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "20px 24px", marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10, gap: 16, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>
            Wage Change by Occupation Group
          </div>
          <div style={{ fontSize: 11, color: "var(--text3)" }}>
            Tile size = certified H-1B filings · color = median Level I change · {hintText}
          </div>
        </div>
        {/* Legend */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 10, color: "var(--text3)" }}>−8%</span>
          <div style={{
            width: 130, height: 10, borderRadius: 5,
            background: `linear-gradient(90deg, ${[-8,-3,0,3,8].map(v => tileColor(v, dark)).join(",")})`,
          }} />
          <span style={{ fontSize: 10, color: "var(--text3)" }}>+8%</span>
        </div>
      </div>

      {/* Breadcrumbs */}
      <div style={{ marginBottom: 10, display: "flex", alignItems: "center", flexWrap: "wrap" }}>
        {crumb("All Groups", 0, depth === 0)}
        {path.map((p, i) => crumb(p.label, i + 1, i === path.length - 1))}
      </div>

      {loading ? (
        <div style={{ height: 340, background: "var(--bg3)", borderRadius: "var(--radius)", animation: "pulse 1.4s ease infinite" }} />
      ) : !tiles.length ? (
        <div style={{ padding: "40px 0", textAlign: "center", color: "var(--text3)", fontSize: 12 }}>
          No year-over-year data at this level
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", display: "block", borderRadius: "var(--radius)" }}>
          {tiles.map((t) => {
            const canDrill = depth < 2;
            const hovered = hover?.id === t.id;
            const showName = t.w > 88 && t.h > 40;
            const showPct = t.w > 52 && t.h > 22;
            return (
              <g key={t.id}
                 onClick={() => canDrill && setPath([...path, { id: t.id, label: t.label }])}
                 onMouseEnter={() => setHover(t)}
                 onMouseLeave={() => setHover(null)}
                 style={{ cursor: canDrill ? "pointer" : "default" }}>
                <rect x={t.x + 1.5} y={t.y + 1.5} width={Math.max(0, t.w - 3)} height={Math.max(0, t.h - 3)}
                      rx={5} fill={tileColor(t.chg, dark)}
                      stroke={hovered ? (dark ? "#fff" : "#1c242c") : "transparent"}
                      strokeWidth={hovered ? 2 : 0}
                      opacity={hover && !hovered ? 0.55 : 0.94} />
                {showName && (
                  <text x={t.x + 10} y={t.y + 20} fontSize={12} fontWeight={700}
                        fill="rgba(255,255,255,0.96)" style={{ pointerEvents: "none" }}>
                    {t.label.length > t.w / 7 ? t.label.slice(0, Math.floor(t.w / 7)) + "…" : t.label}
                  </text>
                )}
                {showPct && (
                  <text x={t.x + 10} y={t.y + (showName ? 38 : 19)} fontSize={12} fontWeight={600}
                        fill="rgba(255,255,255,0.85)" style={{ pointerEvents: "none", fontVariantNumeric: "tabular-nums" }}>
                    {fmtPct(t.chg)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}

      {/* Hover detail bar */}
      <div style={{ marginTop: 10, minHeight: 20, fontSize: 12, color: "var(--text2)", fontVariantNumeric: "tabular-nums" }}>
        {hover ? (
          <>
            <b style={{ color: "var(--text)" }}>{hover.full || hover.label}</b>
            <span style={{ marginLeft: 10 }}>median Δ <b>{fmtPct(hover.chg)}</b></span>
            {hover.filings != null && <span style={{ marginLeft: 10 }}>{hover.filings.toLocaleString()} H-1B filings</span>}
            {hover.socs != null && <span style={{ marginLeft: 10 }}>{hover.socs} occupations</span>}
            {hover.metros != null && <span style={{ marginLeft: 10 }}>{hover.metros} metros</span>}
            {hover.cur_annual != null && <span style={{ marginLeft: 10 }}>Level I {fmt$(hover.prior_annual)} → <b>{fmt$(hover.cur_annual)}</b></span>}
          </>
        ) : (
          <span style={{ color: "var(--text3)" }}>Hover a tile for details</span>
        )}
      </div>
    </div>
  );
}
