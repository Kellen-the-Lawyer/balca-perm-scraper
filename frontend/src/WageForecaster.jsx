import { useState, useEffect, useRef, useCallback } from "react";

const SOC_GROUPS = {
  "11":"Management","13":"Business & Financial Operations","15":"Computer & Mathematical",
  "17":"Architecture & Engineering","19":"Life, Physical & Social Science",
  "21":"Community & Social Service","23":"Legal","25":"Educational Instruction",
  "27":"Arts, Design, Entertainment & Media","29":"Healthcare Practitioners",
  "31":"Healthcare Support","33":"Protective Service","35":"Food Preparation & Serving",
  "37":"Building & Grounds Cleaning","39":"Personal Care & Service","41":"Sales & Related",
  "43":"Office & Administrative Support","45":"Farming, Fishing & Forestry",
  "47":"Construction & Extraction","49":"Installation, Maintenance & Repair",
  "51":"Production","53":"Transportation & Material Moving",
};

const STATE_NAMES = {
  AK:"Alaska",AL:"Alabama",AR:"Arkansas",AZ:"Arizona",CA:"California",CO:"Colorado",
  CT:"Connecticut",DC:"District of Columbia",DE:"Delaware",FL:"Florida",GA:"Georgia",
  HI:"Hawaii",IA:"Iowa",ID:"Idaho",IL:"Illinois",IN:"Indiana",KS:"Kansas",KY:"Kentucky",
  LA:"Louisiana",MA:"Massachusetts",MD:"Maryland",ME:"Maine",MI:"Michigan",MN:"Minnesota",
  MO:"Missouri",MS:"Mississippi",MT:"Montana",NC:"North Carolina",ND:"North Dakota",
  NE:"Nebraska",NH:"New Hampshire",NJ:"New Jersey",NM:"New Mexico",NV:"Nevada",
  NY:"New York",OH:"Ohio",OK:"Oklahoma",OR:"Oregon",PA:"Pennsylvania",PR:"Puerto Rico",
  RI:"Rhode Island",SC:"South Carolina",SD:"South Dakota",TN:"Tennessee",TX:"Texas",
  UT:"Utah",VA:"Virginia",VT:"Vermont",WA:"Washington",WI:"Wisconsin",WV:"West Virginia",
  WY:"Wyoming",
};

const LEVELS = ["Level I", "Level II", "Level III", "Level IV"];

const CARD_STYLES = [
  { bg: "#E6F1FB", border: "#B5D4F4", badge: { bg: "#B5D4F4", color: "#0C447C" }, val: "#0C447C", est: "#185FA5" },
  { bg: "#EAF3DE", border: "#C0DD97", badge: { bg: "#C0DD97", color: "#27500A" }, val: "#27500A", est: "#3B6D11" },
  { bg: "#FAEEDA", border: "#FAC775", badge: { bg: "#FAC775", color: "#633806" }, val: "#633806", est: "#854F0B" },
  { bg: "#FCEBEB", border: "#F7C1C1", badge: { bg: "#F7C1C1", color: "#791F1F" }, val: "#791F1F", est: "#A32D2D" },
];

const fmt = n => "$" + Math.round(n).toLocaleString();
const pct = (a, b) => ((a - b) / b * 100).toFixed(1);
const BASE = import.meta.env.BASE_URL || "/";

function Spinner() {
  return (
    <div style={{
      width: 14, height: 14,
      border: "2px solid var(--border2)",
      borderTopColor: "var(--amber)",
      borderRadius: "50%",
      animation: "wf-spin 0.7s linear infinite",
      display: "inline-block",
      verticalAlign: "middle",
    }} />
  );
}

// ── SOC Dropdown ─────────────────────────────────────────────────────────────

function SocDropdown({ meta, socFlat, curSoc, onChange }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapRef = useRef(null);
  const searchRef = useRef(null);
  const listRef = useRef(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Focus search input when opened
  useEffect(() => {
    if (open && searchRef.current) {
      setTimeout(() => searchRef.current?.focus(), 40);
    }
  }, [open]);

  const q = search.toLowerCase().trim();
  const filtered = q
    ? socFlat.filter(s => s.code.toLowerCase().includes(q) || s.title.toLowerCase().includes(q))
    : socFlat;

  // Group filtered results
  const groups = {};
  filtered.forEach(s => {
    if (!groups[s.group]) groups[s.group] = [];
    groups[s.group].push(s);
  });

  const selectedLabel = curSoc && meta?.[curSoc]
    ? `${curSoc} — ${meta[curSoc].title}`
    : null;

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      {/* Trigger button */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          padding: "7px 10px",
          fontSize: 13,
          fontFamily: "inherit",
          background: "var(--bg)",
          border: `1px solid ${open ? "var(--amber)" : "var(--border2)"}`,
          borderRadius: "var(--radius)",
          color: curSoc ? "var(--text)" : "var(--text3)",
          cursor: "pointer",
          textAlign: "left",
          transition: "border-color 0.1s",
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 }}>
          {selectedLabel || "— Search occupation —"}
        </span>
        <svg
          width="10" height="10" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2.5"
          style={{ flexShrink: 0, transform: open ? "rotate(180deg)" : "", transition: "transform 0.15s", color: "var(--text3)" }}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {/* Dropdown panel */}
      {open && (
        <div style={{
          position: "absolute",
          top: "calc(100% + 4px)",
          left: 0, right: 0,
          zIndex: 200,
          background: "var(--bg2)",
          border: "1px solid var(--border2)",
          borderRadius: "var(--radius-lg)",
          boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
          overflow: "hidden",
        }}>
          {/* Search input */}
          <div style={{ padding: 8, borderBottom: "1px solid var(--border)" }}>
            <input
              ref={searchRef}
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search by title or SOC code…"
              onClick={e => e.stopPropagation()}
              spellCheck={false}
              autoComplete="off"
              style={{ width: "100%", fontSize: 13 }}
            />
          </div>

          {/* Scrollable list */}
          <div ref={listRef} style={{ maxHeight: 280, overflowY: "auto" }}>
            {Object.keys(groups).sort().map(grp => (
              <div key={grp}>
                <div style={{
                  padding: "4px 12px 3px",
                  fontSize: 10, fontWeight: 700,
                  color: "var(--text3)",
                  background: "var(--bg3)",
                  position: "sticky", top: 0, zIndex: 1,
                  letterSpacing: "0.05em",
                  textTransform: "uppercase",
                }}>
                  {SOC_GROUPS[grp] || `Group ${grp}`}
                </div>
                {groups[grp].map(s => (
                  <button
                    key={s.code}
                    onClick={() => {
                      onChange(s.code);
                      setOpen(false);
                      setSearch("");
                    }}
                    style={{
                      width: "100%",
                      display: "flex",
                      alignItems: "baseline",
                      gap: 8,
                      padding: "6px 12px",
                      fontSize: 13,
                      fontFamily: "inherit",
                      background: s.code === curSoc ? "var(--amber-dim)" : "transparent",
                      color: s.code === curSoc ? "var(--amber)" : "var(--text)",
                      border: "none",
                      borderRadius: 0,
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                    onMouseEnter={e => { if (s.code !== curSoc) e.currentTarget.style.background = "var(--bg3)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = s.code === curSoc ? "var(--amber-dim)" : "transparent"; }}
                  >
                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: s.code === curSoc ? "var(--amber)" : "var(--text3)", flexShrink: 0 }}>
                      {s.code}
                    </span>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {s.title}
                    </span>
                  </button>
                ))}
              </div>
            ))}
            {filtered.length === 0 && (
              <div style={{ padding: "20px 12px", textAlign: "center", fontSize: 13, color: "var(--text3)" }}>
                No results for "{search}"
              </div>
            )}
          </div>

          {/* Clear selection */}
          {curSoc && (
            <div style={{ padding: "6px 8px", borderTop: "1px solid var(--border)" }}>
              <button
                onClick={() => { onChange(""); setOpen(false); setSearch(""); }}
                style={{
                  width: "100%", fontSize: 11, color: "var(--text3)",
                  background: "none", border: "none", cursor: "pointer",
                  padding: "3px", fontFamily: "inherit",
                }}
              >
                Clear selection
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

function WageForecaster() {
  const [meta, setMeta] = useState(null);
  const [geo, setGeo] = useState(null);
  const [loadErr, setLoadErr] = useState(null);

  const [stateVal, setStateVal] = useState("");
  const [county, setCounty] = useState("");
  const [curSoc, setCurSoc] = useState("");
  const [curArea, setCurArea] = useState(null);
  const [wageData, setWageData] = useState(null);
  const [wageLoading, setWageLoading] = useState(false);
  const wageCache = useRef({});
  const socFlat = useRef([]);

  useEffect(() => {
    Promise.all([
      fetch(`${BASE}oews/meta.json`).then(r => r.json()),
      fetch(`${BASE}oews/geo.json`).then(r => r.json()),
    ]).then(([m, g]) => {
      setMeta(m);
      setGeo(g);
      // Build sorted flat list
      const byGroup = {};
      Object.keys(m).sort().forEach(code => {
        const grp = code.split("-")[0];
        if (!byGroup[grp]) byGroup[grp] = [];
        byGroup[grp].push({ code, title: m[code].title, group: grp });
      });
      const flat = [];
      Object.keys(byGroup).sort().forEach(grp => {
        byGroup[grp].sort((a, b) => a.code.localeCompare(b.code)).forEach(item => flat.push(item));
      });
      socFlat.current = flat;
    }).catch(e => setLoadErr(e.message));
  }, []);

  const loadWages = useCallback(async (soc) => {
    if (!soc) { setWageData(null); return; }
    if (wageCache.current[soc]) { setWageData(wageCache.current[soc]); return; }
    setWageLoading(true);
    setWageData(null);
    try {
      const safe = soc.replace("-", "");
      const r = await fetch(`${BASE}oews/wages/${safe}.json`);
      if (r.ok) {
        const d = await r.json();
        wageCache.current[soc] = d;
        setWageData(d);
      }
    } catch { /* network error */ }
    setWageLoading(false);
  }, []);

  useEffect(() => { loadWages(curSoc); }, [curSoc, loadWages]);

  useEffect(() => {
    setCounty(""); setCurArea(null); setWageData(null);
  }, [stateVal]);

  useEffect(() => {
    if (!county || !stateVal || !geo) { setCurArea(null); return; }
    const entry = geo[stateVal]?.[county];
    setCurArea(entry ? { code: entry[0], name: entry[1] } : null);
  }, [county, stateVal, geo]);

  const dl = new Date("2026-06-30");
  const daysLeft = Math.ceil((dl - new Date()) / 86400000);

  const curEntry = curArea && wageData ? wageData[curArea.code] : null;
  const cur = curEntry?.slice(0, 4);
  const est = curEntry?.slice(4, 8);
  const socMeta = curSoc && meta ? meta[curSoc] : null;

  if (loadErr) return (
    <div style={{ padding: "40px 32px", color: "var(--red)" }}>
      Failed to load wage data: {loadErr}. Ensure /public/oews/ files are deployed.
    </div>
  );

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <style>{`@keyframes wf-spin { to { transform: rotate(360deg); } }`}</style>
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "32px 32px 64px" }}>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 12 }}>
          <div>
            <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 20, color: "var(--text)", marginBottom: 4 }}>
              Upcoming wage estimator
            </div>
            <div style={{ fontSize: 12, color: "var(--text3)" }}>
              {meta ? `${Object.keys(meta).length} occupation codes` : "Loading…"} · 530 metro areas · OFLC 2025-26 floors + ECI-calibrated July 2026 estimates
            </div>
          </div>
          {daysLeft > 0 && (
            <div style={{ textAlign: "right", flexShrink: 0 }}>
              <div style={{ fontSize: 26, fontWeight: 500, color: "var(--amber)", lineHeight: 1 }}>{daysLeft}</div>
              <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 2 }}>days to June 30</div>
            </div>
          )}
        </div>

        {/* NPRM warning */}
        <div style={{ padding: "8px 12px", background: "var(--amber-dim)", borderLeft: "3px solid var(--amber)", borderRadius: "0 var(--radius) var(--radius) 0", fontSize: 12, color: "var(--text2)", lineHeight: 1.55, marginBottom: "1.25rem" }}>
          <strong style={{ fontWeight: 500 }}>NPRM ETA-2026-0001 pending</strong> — DOL proposed raising wage percentile methodology (comment period closed May 26). If finalized before July 1, these estimates will not apply. File before June 30 to lock in current rates regardless.
        </div>

        {/* Selectors */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: "1rem" }}>

          {/* State */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 5 }}>State</div>
            <select value={stateVal} onChange={e => setStateVal(e.target.value)} style={{ width: "100%" }}>
              <option value="">— Select state —</option>
              {geo && Object.keys(geo).sort().map(ab => (
                <option key={ab} value={ab}>{STATE_NAMES[ab] || ab} ({ab})</option>
              ))}
            </select>
          </div>

          {/* County */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 5 }}>County / parish</div>
            <select value={county} onChange={e => setCounty(e.target.value)} disabled={!stateVal} style={{ width: "100%" }}>
              <option value="">— Select county —</option>
              {stateVal && geo?.[stateVal] && Object.keys(geo[stateVal]).map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          {/* SOC custom dropdown */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 5 }}>Occupation (SOC code)</div>
            <SocDropdown
              meta={meta}
              socFlat={socFlat.current}
              curSoc={curSoc}
              onChange={(code) => { setCurSoc(code); setWageData(null); }}
            />
          </div>
        </div>

        {/* MSA tag */}
        {curArea && (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 12px", border: "1px solid var(--border)", borderRadius: "var(--radius)", fontSize: 12, color: "var(--text2)", marginBottom: "0.85rem" }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>
            </svg>
            {curArea.name}
            <span style={{ color: "var(--text4)", fontSize: 10, fontFamily: "'DM Mono', monospace" }}>CBSA {curArea.code}</span>
          </div>
        )}

        {/* Loading */}
        {wageLoading && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text3)", padding: "8px 0" }}>
            <Spinner /> Loading {curSoc} wage data…
          </div>
        )}

        {/* No data for area/SOC combo */}
        {!wageLoading && curSoc && curArea && wageData && !curEntry && (
          <div style={{ padding: "12px 16px", background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--radius)", fontSize: 13, color: "var(--text2)", marginBottom: "1rem" }}>
            No OFLC prevailing wage data for <strong>{meta?.[curSoc]?.title || curSoc}</strong> in {curArea.name}. This occupation may not be surveyed in this metro area. Try a nearby larger metro.
          </div>
        )}

        {/* Results */}
        {cur && est && socMeta && !wageLoading && (
          <>
            {/* Four level cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10, marginBottom: "1rem" }}>
              {LEVELS.map((lv, i) => {
                const cs = CARD_STYLES[i];
                return (
                  <div key={lv} style={{ background: cs.bg, border: `1px solid ${cs.border}`, borderRadius: "var(--radius-lg)", padding: "14px 14px 12px" }}>
                    <div style={{ display: "inline-block", fontSize: 10, fontWeight: 700, padding: "1px 9px", borderRadius: 99, background: cs.badge.bg, color: cs.badge.color, marginBottom: 8, letterSpacing: "0.02em" }}>{lv}</div>
                    <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 1 }}>Current (2025-26)</div>
                    <div style={{ fontSize: 18, fontWeight: 500, color: cs.val, fontVariantNumeric: "tabular-nums", marginBottom: 8, lineHeight: 1.1 }}>{fmt(cur[i])}</div>
                    <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 1 }}>Estimated July 2026</div>
                    <div style={{ fontSize: 15, fontWeight: 500, color: cs.est, fontVariantNumeric: "tabular-nums", marginBottom: 4, lineHeight: 1.1 }}>{fmt(est[i])}</div>
                    <div style={{ fontSize: 11, color: "var(--text3)" }}>
                      +{pct(est[i], cur[i])}% · +${Math.round(est[i] - cur[i]).toLocaleString()}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Filing decision callout */}
            <div style={{ padding: "12px 16px", background: "var(--blue-dim, #dbeafe)", borderLeft: "3px solid var(--blue, #3b82f6)", borderRadius: "0 var(--radius) var(--radius) 0", fontSize: 13, color: "var(--blue-text, #1e40af)", lineHeight: 1.65, marginBottom: "1rem" }}>
              <strong style={{ fontWeight: 500 }}>Filing before June 30</strong> locks the Level II floor at <strong>{fmt(cur[1])}</strong> for the LCA validity period.
              {" "}Filing on or after July 1 raises it to an estimated <strong>{fmt(est[1])}</strong> — <strong>${Math.round(est[1] - cur[1]).toLocaleString()} more per year (+{pct(est[1], cur[1])}%)</strong>.
              {" "}Extensions and amendments are also subject to the rate in effect on the LCA filing date.
            </div>

            {/* Methodology strip */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
              {[
                ["Data source", "OFLC ALC_Export 2025-26 (flag.dol.gov, July 2025). Actual published prevailing wage floors — not estimates."],
                ["Growth model", `ECI ${socMeta.series === "priv_mgmt" ? "management/professional" : "all-occupations"} (+${socMeta.series === "priv_mgmt" ? "3.9" : "3.6"}%) · panel rotation (+2.1%) · calibration (+0.7%) = ${(socMeta.growth * 100).toFixed(2)}%. Validated against 19,948 BLS MSA × OFLC pairs.`],
                ["Uncertainty", `±1.5% on growth rate → ±$${Math.round(cur[1] * 0.015).toLocaleString()} on this Level II floor. NPRM ETA-2026-0001 pending finalization before July 1.`],
              ].map(([title, body]) => (
                <div key={title} style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "10px 12px", fontSize: 11, color: "var(--text3)", lineHeight: 1.55 }}>
                  <div style={{ fontWeight: 600, color: "var(--text2)", marginBottom: 3 }}>{title}</div>
                  {body}
                </div>
              ))}
            </div>
          </>
        )}

        {/* Empty state */}
        {!curSoc && !curArea && !wageLoading && (
          <div style={{ textAlign: "center", padding: "48px 0", fontSize: 13, color: "var(--text3)" }}>
            Select a state, county, and occupation to see prevailing wage floors.
          </div>
        )}

      </div>
    </div>
  );
}

export { WageForecaster };
