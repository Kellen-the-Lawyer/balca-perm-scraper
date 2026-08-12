// ── Module registry ───────────────────────────────────────────────────────────
// Single source of truth for every routed view. Routes (VIEW_PATHS), landing
// cards, the desktop nav dropdowns, and the mobile drawer are ALL derived from
// MODULES + the group definitions below. To add a tool: add one MODULES entry,
// reference its id in a dropdown group (and it appears in the drawer
// automatically). A dev-time guard warns if a routed module is unreachable.

// 13px nav / drawer icons
export const icon = {
  file:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>,
  globe:  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>,
  book:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>,
  books:  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>,
  link:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>,
  tool:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 1 1 0 10h-2"/><line x1="8" y1="12" x2="16" y2="12"/></svg>,
  letter: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>,
  table:  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>,
  cal:    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>,
  folder: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>,
  chat:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
  home:   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>,
  search: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>,
};

// The registry. `label` is the nav/drawer label; `card` (when present) puts a
// tile on the landing page, in registry order. `countKey` is resolved by
// LandingPage against live stats endpoints.
export const MODULES = [
  { id: "landing", path: "/" },

  { id: "balca", path: "/balca", label: "BALCA Decisions", navIcon: "file",
    card: { label: "BALCA / PERM Decisions", description: "Board of Alien Labor Certification Appeals — employer-sponsored green card appeals", countKey: "balca", countLabel: "decisions", accent: "var(--accent)", accentDim: "var(--accent-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg> } },

  { id: "aao", path: "/aao", label: "AAO Decisions", navIcon: "globe",
    card: { description: "Administrative Appeals Office — USCIS benefit petition appeals across all visa categories", countKey: "aao", countLabel: "decisions", accent: "var(--blue)", accentDim: "var(--blue-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg> } },

  { id: "regulations", path: "/regulations", label: "Regulations (CFR)", navIcon: "book",
    card: { label: "Regulations & Statutes", description: "8 CFR, 20 CFR, 22 CFR, and 29 CFR — full text search across 120 parts, 2,301 pages", accent: "var(--green)", accentDim: "var(--green-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg> } },

  { id: "policy", path: "/policy", label: "Policy Manuals", navIcon: "books",
    card: { description: "USCIS Policy Manual, Foreign Affairs Manual — agency guidance and adjudication policies", accent: "#a78bfa", accentDim: "#a78bfa22",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg> } },

  { id: "search-all", path: "/search-all", label: "Search All", navIcon: "search" },

  { id: "aao-citation-graph", path: "/aao-citation-graph", label: "AAO Citation Graph", navIcon: "link",
    card: { description: "Map how AAO decisions cite each other — surface the most-referenced precedents and form-type patterns visually", accent: "var(--blue)", accentDim: "var(--blue-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg> } },

  { id: "citation-graph", path: "/citation-graph", label: "Citation Graph", navIcon: "link",
    card: { description: "Map how search results cite each other — see the most-cited cases and citation branches emerge visually", accent: "var(--accent)", accentDim: "var(--accent-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg> } },

  { id: "perm-comparer", path: "/perm-comparer", label: "PERM Comparer", navIcon: "tool",
    card: { description: "Compare job description and requirements language, validate PWD wage positioning, and export reports.", accent: "var(--accent)", accentDim: "var(--accent-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 1 1 0 10h-2"/><line x1="8" y1="12" x2="16" y2="12"/></svg> } },

  { id: "perm-verify", path: "/perm-verify", label: "PERM Verify", navIcon: "tool",
    card: { description: "Upload a completed ETA-9089 (and its PWD) to flag denial risks, timing violations, and audit exposure — with citations.", accent: "var(--accent)", accentDim: "var(--accent-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M9 12l2 2 4-5"/><path d="M12 3l7 4v5c0 4.5-3 8-7 9-4-1-7-4.5-7-9V7z"/></svg> } },

  { id: "evl-compare", path: "/evl-compare", label: "PWD / EVL Review", navIcon: "letter",
    card: { description: "Compare every current PWD requirement against experience verification letters and report what is covered, unclear, or missing.", accent: "var(--blue)", accentDim: "var(--blue-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 4h6v16H4zM14 4h6v16h-6z"/><path d="m6 10 1.5 1.5L9 9M16 10h2M16 14h2"/></svg> } },

  { id: "applicant-eval", path: "/applicant-eval", label: "Applicant Evaluation", navIcon: "tool",
    card: { description: "Generate the recruiter applicant-review spreadsheet from a PWD or pasted requirements — YES/NO evaluation columns, auto-recommendation formula, and row highlighting.", accent: "var(--amber)", accentDim: "var(--amber-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/><path d="m5.5 13.5 1 1 2-2"/></svg> } },

  { id: "visa-bulletin", path: "/visa-bulletin", label: "Visa Bulletin", navIcon: "cal",
    card: { description: "Monthly DOS priority dates — track cutoffs, retrogression, and backlog estimates for EB and family categories", accent: "var(--green)", accentDim: "var(--green-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg> } },

  { id: "wage-dashboard", path: "/wage-dashboard", label: "July 1 Wage Comparer", navIcon: "cal",
    card: { description: "2026-27 vs 2025-26 prevailing wage changes — US heat map, metro-level SOC comparisons, top movers, and employer exposure analysis", accent: "var(--green)", accentDim: "var(--green-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg> } },

  { id: "soc-wage", path: "/soc-wage", label: "SOC & Wage Level", navIcon: "tool",
    card: { description: "The SOC Suggester and Wage Level Tool, combined. Type a SOC code or job title — or paste the job description for ranked matches — then the NPWHC worksheet recomputes live as you edit the requirements, with the wage at every level one click away.", accent: "var(--amber)", accentDim: "var(--amber-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><path d="M8 11h6M11 8v6"/><path d="M2 21l3-3"/></svg> } },

  { id: "oflc", path: "/oflc", label: "DOL Data", navIcon: "table",
    card: { label: "DOL Performance Data", description: "PERM, LCA, and Prevailing Wage disclosure data — 1.4M+ records across FY2020–FY2026. Dashboards, templates, and pivot builder.", accent: "var(--accent)", accentDim: "var(--accent-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg> } },

  { id: "processing-times", path: "/processing-times", label: "Case Processing Times", navIcon: "table",
    card: { description: "Historical USCIS and DOL timelines — compare H-1B, O, PERM, prevailing wage, and other case types with methodology and volume context.", accent: "#a78bfa", accentDim: "#a78bfa22",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 3v18h18"/><path d="m7 16 4-5 3 3 5-7"/><circle cx="7" cy="16" r="1"/><circle cx="11" cy="11" r="1"/><circle cx="14" cy="14" r="1"/><circle cx="19" cy="7" r="1"/></svg> } },

  { id: "eb-inventory", path: "/eb-inventory", label: "EB Inventory", navIcon: "table",
    card: { description: "Priority date queue analysis — 74K observations across 5 countries and 7 categories. Tier 1 forecaster for Philippines/Mexico, regime monitor for India/China, queue position for all.", accent: "var(--blue)", accentDim: "var(--blue-dim)",
      icon: <svg width='28' height='28' viewBox='0 0 24 24' fill='none' stroke='currentColor' strokeWidth='1.5'><rect x='3' y='4' width='18' height='18' rx='2' ry='2'/><line x1='16' y1='2' x2='16' y2='6'/><line x1='8' y1='2' x2='8' y2='6'/><line x1='3' y1='10' x2='21' y2='10'/></svg> } },

  { id: "ask", path: "/ask", label: "Ask AI", navIcon: "chat",
    card: { description: "Ask a research question — get a cited answer synthesized across cases, regulations, and policy", accent: "#f472b6", accentDim: "#f472b622",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> } },

  { id: "letter-assist", path: null, label: "Letter Assist", navIcon: "letter", comingSoon: true,
    card: { label: "Letter Assistant", description: "AI-powered drafting and review for NIW and EB-1A support letters — powered by AAO precedent", accent: "var(--accent)", accentDim: "var(--accent-dim)",
      icon: <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> } },

  { id: "projects", path: "/projects", label: "Projects", navIcon: "folder" },
  { id: "kanban",   path: "/kanban",   label: "Kanban",   navIcon: "table"  },
];

export const MODULES_BY_ID = Object.fromEntries(MODULES.map(m => [m.id, m]));
export const VIEW_PATHS = Object.fromEntries(MODULES.filter(m => m.path).map(m => [m.id, m.path]));
export const PATH_VIEWS = Object.fromEntries(Object.entries(VIEW_PATHS).map(([k, v]) => [v, k]));

// Old paths for retired tools -> their replacement (bookmarks keep working).
export const LEGACY_PATHS = {
  "/wage-level":  "/soc-wage",
  "/soc-suggest": "/soc-wage",
};

// Landing-page grouping: sections render in this order, cards in listed order.
// A card-bearing module missing from every section will trigger the dev warn.
export const CARD_SECTIONS = [
  { label: "PERM Tools", accent: "var(--accent)",
    ids: ["perm-verify", "perm-comparer", "evl-compare", "applicant-eval"] },
  { label: "SOC Codes & Wages", accent: "var(--amber)",
    ids: ["soc-wage", "wage-dashboard"] },
  { label: "Research", accent: "var(--blue)",
    ids: ["ask", "balca", "aao", "regulations", "policy", "citation-graph", "aao-citation-graph"] },
  { label: "More Tools & Data", accent: "var(--green)",
    ids: ["visa-bulletin", "oflc", "processing-times", "eb-inventory", "letter-assist"] },
];

const nav = (id, extra = {}) => {
  const m = MODULES_BY_ID[id];
  return { type: "item", id, label: m.label, icon: icon[m.navIcon], ...extra };
};

// Desktop grouped nav — order and grouping defined here, labels/icons from the
// registry. The mobile drawer derives from this (seps and disabled dropped).
export const dropdownGroups = [
  { label: "Case Law", items: [
    nav("balca"), nav("aao"),
    { type: "sep" },
    nav("citation-graph"), nav("aao-citation-graph"),
  ]},
  { label: "Statutes & Regs", items: [ nav("regulations"), nav("policy") ]},
  { label: "Tools", items: [
    nav("perm-comparer"), nav("perm-verify"), nav("evl-compare"), nav("applicant-eval"),
    nav("wage-dashboard"), nav("soc-wage"),
    nav("ask"),
    { type: "sep" },
    nav("letter-assist", { disabled: true }),
  ]},
  { label: "Data", items: [ nav("oflc"), { type: "sep" }, nav("eb-inventory") ]},
];

export const drawerGroups = [
  { section: null, items: [{ id: "landing", label: "Home", icon: icon.home }] },
  ...dropdownGroups.map(g => ({
    section: g.label,
    items: g.items.filter(it => it.type === "item" && !it.disabled)
                  .map(({ id, label, icon }) => ({ id, label, icon })),
  })),
  { section: "Other", items: [ nav("visa-bulletin"), nav("projects") ] },
];

// Dev-time drift guard: every routed module must be reachable from the landing
// page (card), the desktop nav, the drawer, or a known header control.
if (import.meta.env.DEV) {
  const HEADER_IDS = new Set(["landing", "projects", "kanban", "ask", "search-all"]);
  const reachable = new Set(HEADER_IDS);
  drawerGroups.forEach(g => g.items.forEach(it => reachable.add(it.id)));
  MODULES.forEach(m => {
    if (m.path && !m.card && !reachable.has(m.id)) {
      console.warn(`[modules] "${m.id}" is routed but has no landing card and is not in the nav/drawer/header — users can't reach it.`);
    }
  });
  const sectioned = new Set(CARD_SECTIONS.flatMap(s => s.ids));
  MODULES.forEach(m => {
    if (m.card && !sectioned.has(m.id)) {
      console.warn(`[modules] "${m.id}" has a landing card but is not in any CARD_SECTIONS group — its card won't render.`);
    }
  });
  CARD_SECTIONS.flatMap(s => s.ids).forEach(id => {
    if (!MODULES_BY_ID[id]?.card) {
      console.warn(`[modules] CARD_SECTIONS references "${id}" which has no card.`);
    }
  });
}
