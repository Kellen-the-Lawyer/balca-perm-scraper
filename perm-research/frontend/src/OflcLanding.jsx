import { useState, useEffect } from "react";
import { API } from "./apiBase";

const CARDS = [
  {
    id: "dashboard",
    icon: "▨",
    label: "Dashboards",
    description: "Live KPI snapshots across PERM, LCA, and Prevailing Wage — cert rates, top firms, wage trends, SOC breakdowns.",
    color: "var(--amber)",
    cta: "Open Dashboard",
  },
  {
    id: "templates",
    icon: "⊟",
    label: "Template Reports",
    description: "21 pre-built reports covering outcomes, SOC drift, wage sourcing, firm performance, and cross-program trends.",
    color: "var(--blue)",
    cta: "Browse Templates",
  },
  {
    id: "pivot",
    icon: "⊞",
    label: "Pivot Builder",
    description: "Build any custom report from scratch. Drag fields, set filters, pivot by any dimension, export to CSV.",
    color: "var(--green)",
    cta: "Open Builder",
  },
];

function QuickStats() {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    fetch(`${API}/oflc/landing-stats`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setStats(d); })
      .catch(() => {});
  }, []);

  const items = [
    { label: "PERM Filings", value: stats?.perm_total?.toLocaleString() ?? "—", color: "var(--amber)" },
    { label: "PERM Cert Rate", value: stats?.perm_cert_rate ? `${stats.perm_cert_rate}%` : "—", color: "var(--amber)" },
    { label: "LCA Filings", value: stats?.lca_total?.toLocaleString() ?? "—", color: "var(--blue)" },
    { label: "PW Determinations", value: stats?.pw_total?.toLocaleString() ?? "—", color: "var(--green)" },
  ];

  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap", justifyContent: "center" }}>
      {items.map(item => (
        <div key={item.label} style={{ padding: "12px 24px", borderRadius: "var(--radius)", background: "var(--bg2)", border: "1px solid var(--border)", textAlign: "center", minWidth: 140 }}>
          <div style={{ fontSize: 20, fontWeight: 600, color: item.color, fontFamily: "'DM Mono', monospace" }}>{item.value}</div>
          <div style={{ fontSize: 10, color: "var(--text2)", textTransform: "uppercase", letterSpacing: "0.07em", marginTop: 4 }}>{item.label}</div>
        </div>
      ))}
    </div>
  );
}

export function OflcLanding({ onNavigate }) {
  const [hovered, setHovered] = useState(null);
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "48px 32px", gap: 40, background: "var(--bg)", overflowY: "auto" }}>
      <div style={{ textAlign: "center", maxWidth: 540 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 12 }}>DOL Performance Data</div>
        <div style={{ fontSize: 26, fontWeight: 600, color: "var(--text)", lineHeight: 1.3, marginBottom: 12 }}>What would you like to do?</div>
        <div style={{ fontSize: 13, color: "var(--text3)", lineHeight: 1.7 }}>
          Explore PERM, LCA, and Prevailing Wage disclosure data across 1.4M+ records from FY2020–FY2026.
        </div>
      </div>
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap", justifyContent: "center", maxWidth: 900, width: "100%" }}>
        {CARDS.map(card => (
          <div key={card.id} onClick={() => onNavigate(card.id)}
            onMouseEnter={() => setHovered(card.id)} onMouseLeave={() => setHovered(null)}
            style={{
              flex: "1 1 240px", maxWidth: 280, padding: "28px 24px", borderRadius: "var(--radius)",
              border: `1px solid ${hovered === card.id ? card.color + "88" : "var(--border2)"}`,
              background: hovered === card.id ? `${card.color}08` : "var(--bg2)",
              cursor: "pointer", transition: "all 0.15s", display: "flex", flexDirection: "column", gap: 14,
              boxShadow: hovered === card.id ? `0 0 0 1px ${card.color}44, 0 8px 32px #00000044` : "none",
            }}>
            <div style={{ width: 40, height: 40, borderRadius: 8, background: `${card.color}18`, border: `1px solid ${card.color}33`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, color: card.color }}>
              {card.icon}
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text)", marginBottom: 8 }}>{card.label}</div>
              <div style={{ fontSize: 12, color: "var(--text2)", lineHeight: 1.6 }}>{card.description}</div>
            </div>
            <div style={{ marginTop: "auto", fontSize: 12, fontWeight: 500, color: card.color }}>{card.cta} →</div>
          </div>
        ))}
      </div>
      <QuickStats />
    </div>
  );
}
