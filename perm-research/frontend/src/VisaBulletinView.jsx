// ══════════════════════════════════════════════════════════════════════════════
// VisaBulletinView — imported into App.jsx
// ══════════════════════════════════════════════════════════════════════════════

import { useState, useEffect } from "react";

const VB_API = "/api/visa-bulletin";

function Spinner() {
  return (
    <div style={{ padding: "40px 20px", display: "flex", justifyContent: "center" }}>
      <div style={{ width: 20, height: 20, border: "2px solid var(--border2)", borderTopColor: "var(--amber)", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

const COUNTRIES = ["ALL", "CHINA", "INDIA", "MEXICO", "PHILIPPINES"];
const COUNTRY_LABELS = { ALL: "All Chargeability", CHINA: "China", INDIA: "India", MEXICO: "Mexico", PHILIPPINES: "Philippines" };
const EB_PREFS   = ["EB1","EB2","EB3","EB3W","EB4","EB5"];
const FAM_PREFS  = ["F1","F2A","F2B","F3","F4"];
const PREF_LABELS = {
  EB1:"Priority Workers", EB2:"Adv. Degree / Exc. Ability", EB3:"Skilled Workers",
  EB3W:"Other Workers", EB4:"Special Immigrants", EB5:"Investors",
  F1:"Unmarried Sons/Daughters of USC", F2A:"Spouses & Children of LPR",
  F2B:"Unmarried Sons/Daughters of LPR", F3:"Married Sons/Daughters of USC",
  F4:"Siblings of Adult USC",
};

function fmtDate(d) {
  if (!d) return null;
  // Parse YYYY-MM-DD directly to avoid timezone shifts
  const [year, month, day] = d.split("-").map(Number);
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${months[month-1]} ${String(day).padStart(2,"0")}, ${year}`;
}
function fmtMonthYear(d) {
  if (!d) return "";
  const [year, month] = d.split("-").map(Number);
  const months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  return `${months[month-1]} ${year}`;
}

function DateCell({ row, country, selected }) {
  if (!row) return <td style={{ padding: "9px 12px", color: "var(--text3)" }}>—</td>;
  const isSelected = country === selected;
  let val, color;
  if (row.is_current)     { val = "Current";     color = "var(--green)"; }
  else if (row.is_unavailable) { val = "Unavail."; color = "var(--red)"; }
  else if (row.priority_date)  { val = fmtDate(row.priority_date); color = isSelected ? "var(--amber)" : "var(--text2)"; }
  else                         { val = row.raw_value || "—"; color = "var(--text3)"; }
  return (
    <td style={{
      padding: "9px 12px", fontFamily: "'DM Mono', monospace", fontSize: 12,
      color, fontWeight: isSelected ? 500 : 400,
      background: isSelected ? "var(--amber-dim)" : "transparent",
    }}>
      {val}
    </td>
  );
}

function dateToMs(d) {
  if (!d) return null;
  const [y, m, day] = d.split("-").map(Number);
  return Date.UTC(y, m - 1, day);
}
function todayMs() {
  const n = new Date();
  return Date.UTC(n.getFullYear(), n.getMonth(), n.getDate());
}
function daysBetween(d1, d2) {
  return Math.floor((dateToMs(d2) - dateToMs(d1)) / 86400000);
}

function SparkLine({ history }) {
  if (!history || history.length < 2) return null;
  const dated = history.filter(h => h.priority_date && !h.is_current && !h.is_unavailable);
  if (dated.length < 2) return <div style={{ padding: "8px 0", color: "var(--text3)", fontSize: 11 }}>Not enough data to chart</div>;
  const vals = dated.map(h => dateToMs(h.priority_date));
  const min = Math.min(...vals), max = Math.max(...vals);
  const range = max - min || 1;
  const W = 260, H = 72;
  const pts = dated.map((h, i) => {
    const x = (i / (dated.length - 1)) * W;
    const y = H - ((dateToMs(h.priority_date) - min) / range) * (H - 8);
    return `${x},${y}`;
  }).join(" ");
  const lastX = W, lastY = H - ((vals[vals.length - 1] - min) / range) * (H - 8);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 72, display: "block" }} preserveAspectRatio="none">
      <polyline fill="none" stroke="var(--amber)" strokeWidth="1.5" points={pts} />
      <circle cx={lastX} cy={lastY} r="3" fill="var(--amber)" />
      <line x1="0" y1={H} x2={W} y2={H} stroke="var(--border)" strokeWidth="0.5" />
    </svg>
  );
}

function VisaBulletinView() {
  const [category, setCategory]     = useState("employment");
  const [dateType, setDateType]     = useState("final_action");
  const [selCountry, setSelCountry] = useState("ALL");
  const [selPref, setSelPref]       = useState("EB2");
  const [sideTab, setSideTab]       = useState("table");   // table | backlog
  const [centerTab, setCenterTab]   = useState("dates");   // dates | chart | compare

  // Bulletin index + current month navigation
  const [index, setIndex]       = useState(null);
  const [bulletinIdx, setBulletinIdx] = useState(0); // 0 = latest
  const [bulletin, setBulletin] = useState(null);
  const [loadingB, setLoadingB] = useState(false);

  // History / backlog for selected pref+country
  const [history, setHistory]   = useState(null);
  const [backlog, setBacklog]   = useState(null);
  const [loadingH, setLoadingH] = useState(false);

  // Load bulletin index once — default to currently active bulletin (latest where date <= today)
  useEffect(() => {
    fetch(`${VB_API}/index`).then(r => r.json()).then(data => {
      setIndex(data);
      // Find the most recent bulletin that is already in effect (bulletin_date <= today)
      const today = new Date().toISOString().slice(0, 10);
      const activeIdx = data.findIndex(b => b.bulletin_date <= today);
      setBulletinIdx(activeIdx >= 0 ? activeIdx : 0);
    });
  }, []);

  // Load bulletin when index or navigation changes
  useEffect(() => {
    if (!index || !index.length) return;
    const entry = index[bulletinIdx];
    if (!entry) return;
    const d = new Date(entry.bulletin_date + "T12:00:00Z");
    setLoadingB(true); setBulletin(null);
    fetch(`${VB_API}/${d.getFullYear()}/${d.getMonth() + 1}`)
      .then(r => r.json())
      .then(data => { setBulletin(data); setLoadingB(false); })
      .catch(() => setLoadingB(false));
  }, [index, bulletinIdx]);

  // Load history + backlog when selection changes
  useEffect(() => {
    if (!selPref || !selCountry) return;
    setLoadingH(true); setHistory(null); setBacklog(null);
    const cat = selPref.startsWith("F") ? "family" : "employment";
    Promise.all([
      fetch(`${VB_API}/history?preference=${selPref}&chargeability=${selCountry}&date_type=${dateType}`).then(r => r.json()),
      fetch(`${VB_API}/backlog?preference=${selPref}&chargeability=${selCountry}&date_type=${dateType}`).then(r => r.json()),
    ]).then(([h, b]) => { setHistory(h); setBacklog(b); setLoadingH(false); })
      .catch(() => setLoadingH(false));
  }, [selPref, selCountry, dateType]);

  // Switch pref list when category changes
  useEffect(() => {
    if (category === "employment") { if (!selPref.startsWith("E")) setSelPref("EB2"); }
    else { if (selPref.startsWith("E")) setSelPref("F1"); }
  }, [category]);

  const prefs = category === "employment" ? EB_PREFS : FAM_PREFS;

  // Build lookup: pref -> country -> row
  const lookup = {};
  if (bulletin) {
    bulletin
      .filter(r => r.category_type === category && r.date_type === dateType)
      .forEach(r => {
        if (!lookup[r.preference]) lookup[r.preference] = {};
        lookup[r.preference][r.chargeability] = r;
      });
  }

  const currentEntry = index?.[bulletinIdx];
  const bulletinTitle = currentEntry ? fmtMonthYear(currentEntry.bulletin_date) : "Loading…";

  const recentHistory = (history || []).slice(-24).reverse();

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>

      {/* ── Top bar ── */}
      <div style={{ padding: "11px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
        <div>
          <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 16, color: "var(--text)" }}>
            Visa Bulletin — {bulletinTitle}
          </div>
          <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 2 }}>
            {index ? `${index.length} bulletins loaded · FY2016–FY2026 · showing currently active bulletin` : "Loading…"}
          </div>
        </div>

        {/* Month navigation */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 12 }}>
          <button onClick={() => setBulletinIdx(i => Math.min(i + 1, (index?.length || 1) - 1))}
            disabled={bulletinIdx >= (index?.length || 1) - 1}
            style={{ width: 28, height: 28, padding: 0, fontSize: 13, opacity: bulletinIdx >= (index?.length || 1) - 1 ? 0.3 : 1, display: "flex", alignItems: "center", justifyContent: "center" }}>←</button>
          <button onClick={() => {
              const today = new Date().toISOString().slice(0, 10);
              const activeIdx = index?.findIndex(b => b.bulletin_date <= today) ?? 0;
              setBulletinIdx(activeIdx >= 0 ? activeIdx : 0);
            }}
            style={{ fontSize: 11, padding: "4px 10px", height: 28, background: "var(--bg3)", color: "var(--text3)", border: `1px solid var(--border)` }}>
            Current
          </button>
          <button onClick={() => setBulletinIdx(i => Math.max(i - 1, 0))}
            disabled={bulletinIdx <= 0}
            style={{ width: 28, height: 28, padding: 0, fontSize: 13, opacity: bulletinIdx <= 0 ? 0.3 : 1, display: "flex", alignItems: "center", justifyContent: "center" }}>→</button>
        </div>

        {/* Category toggle */}
        <div style={{ marginLeft: "auto", display: "flex", background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
          {[["employment","Employment-Based"],["family","Family-Sponsored"]].map(([v, l]) => (
            <button key={v} onClick={() => setCategory(v)} style={{ padding: "5px 14px", fontSize: 11, background: category === v ? "var(--amber-dim)" : "none", color: category === v ? "var(--amber)" : "var(--text3)", border: "none", borderRadius: 0, fontWeight: category === v ? 500 : 400 }}>{l}</button>
          ))}
        </div>

        {/* Final action / Dates for filing */}
        <div style={{ display: "flex", background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
          {[["final_action","Final Action"],["dates_for_filing","Dates for Filing"]].map(([v, l]) => (
            <button key={v} onClick={() => setDateType(v)} style={{ padding: "5px 12px", fontSize: 11, background: dateType === v ? "var(--amber-dim)" : "none", color: dateType === v ? "var(--amber)" : "var(--text3)", border: "none", borderRadius: 0, fontWeight: dateType === v ? 500 : 400 }}>{l}</button>
          ))}
        </div>
      </div>

      {/* ── Body: sidebar + center + right panel ── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

        {/* ── Left sidebar ── */}
        <div style={{ width: 220, borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", flexShrink: 0, background: "var(--bg2)" }}>

          {/* Side tabs */}
          <div style={{ display: "flex", borderBottom: "1px solid var(--border)" }}>
            {[["table","Bulletin"],["backlog","Backlog"]].map(([v, l]) => (
              <button key={v} onClick={() => setSideTab(v)} style={{ flex: 1, padding: "9px 6px", fontSize: 12, background: "none", border: "none", borderRadius: 0, borderBottom: sideTab === v ? "2px solid var(--amber)" : "2px solid transparent", color: sideTab === v ? "var(--amber)" : "var(--text3)", fontWeight: sideTab === v ? 500 : 400 }}>{l}</button>
            ))}
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "12px 10px" }}>

            {sideTab === "table" && (
              <>
                {/* Country selector */}
                <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>Country / Chargeability</div>
                {COUNTRIES.map(c => (
                  <button key={c} onClick={() => setSelCountry(c)} style={{ width: "100%", textAlign: "left", marginBottom: 4, padding: "7px 10px", fontSize: 11, background: selCountry === c ? "var(--amber-dim)" : "var(--bg3)", color: selCountry === c ? "var(--amber)" : "var(--text2)", border: `1px solid ${selCountry === c ? "var(--amber)" : "var(--border)"}`, borderRadius: "var(--radius)", fontWeight: selCountry === c ? 500 : 400 }}>
                    {COUNTRY_LABELS[c]}
                    {lookup[selPref]?.[c] && (
                      <span style={{ float: "right", fontFamily: "'DM Mono', monospace", fontSize: 10, color: selCountry === c ? "var(--amber)" : "var(--text3)" }}>
                        {lookup[selPref][c].is_current ? "C" : lookup[selPref][c].is_unavailable ? "U" : (lookup[selPref][c].priority_date ? lookup[selPref][c].priority_date.slice(0,4) : "—")}
                      </span>
                    )}
                  </button>
                ))}

                {/* Preference selector */}
                <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginTop: 16, marginBottom: 8 }}>Preference</div>
                {prefs.map(p => (
                  <button key={p} onClick={() => setSelPref(p)} style={{ width: "100%", textAlign: "left", marginBottom: 4, padding: "7px 10px", fontSize: 11, background: selPref === p ? "var(--amber-dim)" : "var(--bg3)", color: selPref === p ? "var(--amber)" : "var(--text2)", border: `1px solid ${selPref === p ? "var(--amber)" : "var(--border)"}`, borderRadius: "var(--radius)" }}>
                    <span style={{ fontFamily: "'DM Mono', monospace", fontWeight: 600, marginRight: 6 }}>{p}</span>
                    <span style={{ color: selPref === p ? "var(--amber)" : "var(--text3)", fontSize: 10 }}>{PREF_LABELS[p]?.split(" ").slice(0, 2).join(" ")}</span>
                  </button>
                ))}
              </>
            )}

            {sideTab === "backlog" && (
              <>
                <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10 }}>Backlog by Preference</div>
                {prefs.map(p => {
                  const row = lookup[p]?.[selCountry];
                  const isC = row?.is_current, isU = row?.is_unavailable;
                  const pd = row?.priority_date;
                  const yrs = pd ? Math.floor(daysBetween(pd, new Date().toISOString().slice(0,10)) / 365.25) : null;
                  return (
                    <button key={p} onClick={() => { setSelPref(p); setSideTab("table"); }} style={{ width: "100%", textAlign: "left", marginBottom: 6, padding: "9px 10px", fontSize: 11, background: selPref === p ? "var(--amber-dim)" : "var(--bg3)", border: `1px solid ${selPref === p ? "var(--amber)" : "var(--border)"}`, borderRadius: "var(--radius)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3 }}>
                        <span style={{ fontFamily: "'DM Mono', monospace", fontWeight: 600, color: selPref === p ? "var(--amber)" : "var(--text)" }}>{p}</span>
                        {isC && <span style={{ fontSize: 10, color: "var(--green)", background: "var(--green-dim)", padding: "1px 6px", borderRadius: 3 }}>Current</span>}
                        {isU && <span style={{ fontSize: 10, color: "var(--red)", background: "var(--red-dim)", padding: "1px 6px", borderRadius: 3 }}>Unavail.</span>}
                        {yrs !== null && !isC && !isU && <span style={{ fontSize: 11, fontFamily: "'DM Mono', monospace", color: yrs > 5 ? "var(--red)" : yrs > 2 ? "var(--amber)" : "var(--green)" }}>{yrs}yr</span>}
                      </div>
                      {pd && !isC && !isU && <div style={{ fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{fmtDate(pd)}</div>}
                    </button>
                  );
                })}
              </>
            )}
          </div>
        </div>

        {/* ── Center ── */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

          {/* Center tabs */}
          <div style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
            {[["dates","Priority Dates"],["chart","Movement Chart"],["compare","Compare Countries"]].map(([v, l]) => (
              <button key={v} onClick={() => setCenterTab(v)} style={{ padding: "9px 16px", fontSize: 12, background: "none", border: "none", borderRadius: 0, borderBottom: centerTab === v ? "2px solid var(--amber)" : "2px solid transparent", color: centerTab === v ? "var(--amber)" : "var(--text3)", fontWeight: centerTab === v ? 500 : 400 }}>{l}</button>
            ))}
          </div>

          <div style={{ flex: 1, overflowY: "auto" }}>
            {loadingB && <Spinner />}

            {/* ── Priority dates table ── */}
            {!loadingB && centerTab === "dates" && (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ position: "sticky", top: 0, background: "var(--bg)", zIndex: 2 }}>
                    <th style={{ padding: "9px 14px", fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text3)", textAlign: "left", borderBottom: "1px solid var(--border)", width: 110 }}>Preference</th>
                    {COUNTRIES.map(c => (
                      <th key={c} onClick={() => setSelCountry(c)} style={{ padding: "9px 12px", fontSize: 10, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: selCountry === c ? "var(--amber)" : "var(--text3)", textAlign: "left", borderBottom: "1px solid var(--border)", cursor: "pointer", background: selCountry === c ? "var(--amber-dim)" : "transparent", whiteSpace: "nowrap" }}>
                        {c === "ALL" ? "All Areas" : COUNTRY_LABELS[c]} {selCountry === c && "★"}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {prefs.map((p, i) => (
                    <tr key={p}
                      onClick={() => setSelPref(p)}
                      style={{ cursor: "pointer", background: selPref === p ? "var(--amber-dim)" : i % 2 === 0 ? "var(--bg)" : "var(--bg2)", borderLeft: selPref === p ? "2px solid var(--amber)" : "2px solid transparent" }}>
                      <td style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)" }}>
                        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, fontWeight: 600, color: selPref === p ? "var(--amber)" : "var(--text)" }}>{p}</div>
                        <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 1 }}>{PREF_LABELS[p]?.split(" ").slice(0, 3).join(" ")}</div>
                      </td>
                      {COUNTRIES.map(c => (
                        <td key={c} style={{ padding: "10px 12px", borderBottom: "1px solid var(--border)", background: selCountry === c ? (selPref === p ? "#f59e0b22" : "var(--amber-dim)") : "transparent" }}>
                          {(() => {
                            const row = lookup[p]?.[c];
                            if (!row) return <span style={{ color: "var(--text3)" }}>—</span>;
                            if (row.is_current) return <span style={{ color: "var(--green)", fontFamily: "'DM Mono', monospace", fontSize: 12, fontWeight: 500 }}>Current</span>;
                            if (row.is_unavailable) return <span style={{ color: "var(--red)", fontFamily: "'DM Mono', monospace", fontSize: 12 }}>Unavail.</span>;
                            if (row.priority_date) return <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: selPref === p && selCountry === c ? "var(--amber)" : selCountry === c || selPref === p ? "var(--text)" : "var(--text2)" }}>{fmtDate(row.priority_date)}</span>;
                            return <span style={{ color: "var(--text3)", fontSize: 11 }}>{row.raw_value}</span>;
                          })()}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {/* ── Movement chart ── */}
            {!loadingB && centerTab === "chart" && (
              <div style={{ padding: "20px 24px" }}>
                <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 16 }}>
                  Priority date movement — <span style={{ color: "var(--amber)" }}>{selPref} · {COUNTRY_LABELS[selCountry]}</span> — {dateType === "final_action" ? "Final Action" : "Dates for Filing"}
                </div>
                {loadingH && <Spinner />}
                {!loadingH && history && history.length > 1 && (
                  <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "16px" }}>
                    <SparkLine history={history} />
                    <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
                      <span>{history[0]?.bulletin_date?.slice(0, 7)}</span>
                      <span>{history[history.length - 1]?.bulletin_date?.slice(0, 7)}</span>
                    </div>
                  </div>
                )}
                {!loadingH && (!history || history.length < 2) && (
                  <div style={{ color: "var(--text3)", fontSize: 13, padding: "40px 0", textAlign: "center" }}>Not enough data for chart.</div>
                )}
              </div>
            )}

            {/* ── Compare all countries ── */}
            {!loadingB && centerTab === "compare" && (
              <div style={{ padding: "20px 24px" }}>
                <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 16 }}>
                  All chargeability for <span style={{ color: "var(--amber)" }}>{selPref}</span> — {bulletinTitle}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
                  {COUNTRIES.map(c => {
                    const row = lookup[selPref]?.[c];
                    const pd = row?.priority_date;
                    const yrs = pd ? Math.floor(daysBetween(pd, new Date().toISOString().slice(0,10)) / 365.25) : null;
                    return (
                      <div key={c} onClick={() => setSelCountry(c)} style={{ background: selCountry === c ? "var(--amber-dim)" : "var(--bg2)", border: `1px solid ${selCountry === c ? "var(--amber)" : "var(--border)"}`, borderRadius: "var(--radius-lg)", padding: "14px 16px", cursor: "pointer" }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: selCountry === c ? "var(--amber)" : "var(--text3)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>{COUNTRY_LABELS[c]}</div>
                        {!row && <div style={{ color: "var(--text3)" }}>—</div>}
                        {row?.is_current && <div style={{ color: "var(--green)", fontFamily: "'DM Mono', monospace", fontSize: 14, fontWeight: 500 }}>Current</div>}
                        {row?.is_unavailable && <div style={{ color: "var(--red)", fontFamily: "'DM Mono', monospace", fontSize: 14 }}>Unavailable</div>}
                        {pd && !row?.is_current && !row?.is_unavailable && (
                          <>
                            <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 13, color: selCountry === c ? "var(--amber)" : "var(--text)", marginBottom: 4 }}>{fmtDate(pd)}</div>
                            {yrs !== null && <div style={{ fontSize: 11, color: yrs > 5 ? "var(--red)" : yrs > 2 ? "var(--amber)" : "var(--green)" }}>{yrs} yr backlog</div>}
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── Right panel: backlog + history ── */}
        <div style={{ width: 280, borderLeft: "1px solid var(--border)", display: "flex", flexDirection: "column", background: "var(--bg2)", flexShrink: 0 }}>
          <div style={{ padding: "11px 14px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", marginBottom: 2 }}>
              <span style={{ fontFamily: "'DM Mono', monospace", color: "var(--amber)" }}>{selPref}</span>
              {" · "}{COUNTRY_LABELS[selCountry]}
            </div>
            <div style={{ fontSize: 11, color: "var(--text3)" }}>{dateType === "final_action" ? "Final Action Dates" : "Dates for Filing"}</div>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "14px" }}>
            {loadingH && <Spinner />}
            {!loadingH && backlog && (
              <>
                {/* Stats */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 16 }}>
                  {[
                    ["Cut-off", backlog.is_current ? "Current" : backlog.is_unavailable ? "Unavail." : fmtDate(backlog.current_cut_off), backlog.is_current ? "var(--green)" : backlog.is_unavailable ? "var(--red)" : "var(--amber)"],
                    ["Backlog", backlog.backlog_years ? `${backlog.backlog_years} yrs` : "—", backlog.backlog_years > 5 ? "var(--red)" : "var(--amber)"],
                    ["Avg Advance", backlog.avg_monthly_advance_days ? `+${Math.round(backlog.avg_monthly_advance_days)}d/mo` : "—", "var(--green)"],
                    ["Est. Wait", backlog.est_years_to_current ? `${backlog.est_years_to_current} yrs` : backlog.is_current ? "Now" : "—", backlog.est_years_to_current > 10 ? "var(--red)" : backlog.est_years_to_current > 3 ? "var(--amber)" : "var(--green)"],
                  ].map(([label, val, color]) => (
                    <div key={label} style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "10px 11px" }}>
                      <div style={{ fontSize: 10, color: "var(--text3)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                      <div style={{ fontSize: 14, fontWeight: 300, color, fontFamily: "'DM Mono', monospace" }}>{val}</div>
                    </div>
                  ))}
                </div>

                {/* Sparkline */}
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>24-Month Movement</div>
                  <div style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "10px 10px 6px" }}>
                    <SparkLine history={recentHistory.slice().reverse()} />
                  </div>
                </div>

                {/* History */}
                <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>Monthly History</div>
                {recentHistory.map((h, i) => {
                  const delta = h.movement_days;
                  const sign = delta === null ? null : delta > 0 ? "+" : delta < 0 ? "" : "=";
                  const dcolor = delta === null ? "var(--text3)" : delta > 0 ? "var(--green)" : delta < 0 ? "var(--red)" : "var(--text3)";
                  const dbg = delta === null ? "var(--bg4)" : delta > 0 ? "var(--green-dim)" : delta < 0 ? "var(--red-dim)" : "var(--bg4)";
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: "var(--text3)", minWidth: 56 }}>{h.bulletin_date?.slice(0, 7)}</span>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: h.is_current ? "var(--green)" : h.is_unavailable ? "var(--red)" : "var(--text2)", flex: 1 }}>
                        {h.is_current ? "Current" : h.is_unavailable ? "Unavail." : fmtDate(h.priority_date)}
                      </span>
                      {sign !== null && (
                        <span style={{ fontSize: 10, padding: "1px 5px", borderRadius: 3, background: dbg, color: dcolor, fontFamily: "'DM Mono', monospace" }}>
                          {sign}{Math.abs(delta)}d
                        </span>
                      )}
                    </div>
                  );
                })}
              </>
            )}
            {!loadingH && !backlog && (
              <div style={{ color: "var(--text3)", fontSize: 12, textAlign: "center", paddingTop: 40 }}>Select a preference to see backlog data.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export { VisaBulletinView };
