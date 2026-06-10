// ─────────────────────────────────────────────────────────────────────────────
// PERM Recruitment ↔ PWD Compliance Engine
//
// Deterministic checks that test whether a piece of PERM recruitment is
// consistent with the prevailing wage determination (ETA-9141) and with the
// content rules of 20 CFR 656, as construed by BALCA. Pure functions — no React,
// no network — so they can be unit-tested in isolation.
//
// Grounding (verified against the casebase knowledge base, see
// docs/perm-recruitment-comparer-analysis.json):
//   • Scope of the §656.17(f) advertising-content rules — Symantec Corp.,
//     2011-PER-01856 (BALCA en banc): (f)(1)-(7) apply only to newspaper/journal
//     ads and the Notice of Filing, NOT to the "additional" recruitment steps
//     (employer website, job-search sites, job fairs, etc.) or SWA job orders.
//   • Wage floor / range bottom == PWD is permissible — Credit Suisse, 2010-PER-00103.
//   • Requirements may be abbreviated but must not EXCEED the 9089 — East
//     Tennessee State Univ., 2010-PER-00038; 2024-PER-00128.
//   • NOF must state a rate of pay and the (d)(3) content — 656.10(d)(3)-(4);
//     posting ≥ 10 consecutive business days — 2011-PER-02628.
//
// Each check returns: { reqId, title, status, detail, citation }
//   status ∈ 'pass' | 'flag' | 'fail' | 'na' | 'review'
//     pass   — satisfied
//     fail   — affirmative violation
//     flag   — cannot confirm from the inputs (missing date/wage/etc.); never
//              silently pass when a required input is absent
//     na     — not applicable to this recruitment medium (e.g. (f) rules on an
//              additional step, per Symantec)
//     review — requires human/legal judgment (routed to LLM in a later phase)
// ─────────────────────────────────────────────────────────────────────────────

// ── Recruitment-type taxonomy (names tracking 20 CFR 656) ────────────────────
// appliesF: whether the §656.17(f)(1)-(7) advertising-content rules govern this
//   medium. Per Symantec Corp., 2011-PER-01856 (en banc), (f) governs only the
//   newspaper-of-general-circulation ad, the professional-journal ad, and the
//   Notice of Filing. Every "additional" step under §656.17(e)(1)(ii) — and the
//   SWA job order — need only advertise the occupation, so appliesF = false.
// group: used to organize the dropdown into <optgroup>s.
export const RECRUITMENT_TYPES = {
  // ── Mandatory recruitment steps — §656.17(e)(1)(i) ──────────────────────────
  newspaper_general:   { label: 'Newspaper of general circulation — Sunday advertisement (§656.17(e)(1)(i)(B))', group: 'Mandatory steps — §656.17(e)(1)(i)', appliesF: true,  isNof: false },
  professional_journal:{ label: 'Professional journal advertisement (§656.17(e)(1)(i)(B)(4))',                   group: 'Mandatory steps — §656.17(e)(1)(i)', appliesF: true,  isNof: false },
  swa_job_order:       { label: 'State Workforce Agency job order (§656.17(e)(1)(i)(A))',                        group: 'Mandatory steps — §656.17(e)(1)(i)', appliesF: false, isNof: false },
  // ── Additional recruitment steps — §656.17(e)(1)(ii)(A)-(J) ─────────────────
  job_fair:                { label: 'Job fair (§656.17(e)(1)(ii)(A))',                                  group: 'Additional steps — §656.17(e)(1)(ii)', appliesF: false, isNof: false },
  employer_website:        { label: "Employer's website (§656.17(e)(1)(ii)(B))",                        group: 'Additional steps — §656.17(e)(1)(ii)', appliesF: false, isNof: false },
  job_search_website:      { label: "Job search website other than the employer's (§656.17(e)(1)(ii)(C))", group: 'Additional steps — §656.17(e)(1)(ii)', appliesF: false, isNof: false },
  on_campus_recruiting:    { label: 'On-campus recruiting (§656.17(e)(1)(ii)(D))',                      group: 'Additional steps — §656.17(e)(1)(ii)', appliesF: false, isNof: false },
  trade_professional_org:  { label: 'Trade or professional organization (§656.17(e)(1)(ii)(E))',        group: 'Additional steps — §656.17(e)(1)(ii)', appliesF: false, isNof: false },
  private_employment_firm: { label: 'Private employment firm (§656.17(e)(1)(ii)(F))',                   group: 'Additional steps — §656.17(e)(1)(ii)', appliesF: false, isNof: false },
  employee_referral:       { label: 'Employee referral program with incentives (§656.17(e)(1)(ii)(G))', group: 'Additional steps — §656.17(e)(1)(ii)', appliesF: false, isNof: false },
  campus_placement_office: { label: 'Campus placement office (§656.17(e)(1)(ii)(H))',                   group: 'Additional steps — §656.17(e)(1)(ii)', appliesF: false, isNof: false },
  local_ethnic_newspaper:  { label: 'Local or ethnic newspaper (§656.17(e)(1)(ii)(I))',                 group: 'Additional steps — §656.17(e)(1)(ii)', appliesF: false, isNof: false },
  radio_tv:                { label: 'Radio or television advertisement (§656.17(e)(1)(ii)(J))',         group: 'Additional steps — §656.17(e)(1)(ii)', appliesF: false, isNof: false },
  // ── Notice of Filing — §656.10(d) ───────────────────────────────────────────
  notice_of_filing:    { label: 'Notice of Filing — posted notice (§656.10(d)(1)(ii))',          group: 'Notice of Filing — §656.10(d)', appliesF: true, isNof: true },
  notice_in_house:     { label: 'Notice of Filing — in-house / electronic media (§656.10(d)(1)(ii))', group: 'Notice of Filing — §656.10(d)', appliesF: true, isNof: true },
};

// ── Checklist metadata (titles + authority) keyed to requirement ids ─────────
export const CHECKLIST = {
  'ADV-F-SCOPE':          { title: 'Advertising-content rules scope',           citation: '20 CFR 656.17(f); Symantec Corp., 2011-PER-01856 (en banc)' },
  'ADV-NAME-EMPLOYER':    { title: 'Names the employer & directs applicants',   citation: '20 CFR 656.17(f)(1)-(2)' },
  'ADV-GEOGRAPHIC-AREA':  { title: 'States the geographic area of employment',  citation: '20 CFR 656.17(f)(4); Cognizant, 2013-PER-01448' },
  'ADV-WAGE-FLOOR':       { title: 'Wage / range bottom ≥ prevailing wage',     citation: '20 CFR 656.17(f)(5); Credit Suisse, 2010-PER-00103' },
  'ADV-NOT-EXCEED-9089':  { title: 'Requirements do not exceed the 9089/PWD',   citation: '20 CFR 656.17(f)(6); East Tennessee State Univ., 2010-PER-00038' },
  'ADV-NOT-LESS-FAVORABLE': { title: 'No terms less favorable than offered',    citation: '20 CFR 656.17(f)(7); Thomas L. Brown Assocs., 2009-PER-00347' },
  'ADV-CLEARLY-OPEN':     { title: 'Job clearly open to U.S. workers',          citation: '20 CFR 656.10(c)(8); AMR Capital Trading, 2012-PER-00609' },
  'ADV-VACANCY-DESC':     { title: 'Vacancy described specifically (nexus)',    citation: '20 CFR 656.17(f)(3); Choate Rosemary Hall, 2012-PER-03326' },
  'NOF-CONTENT-D3':       { title: 'Notice of Filing statutory content',        citation: '20 CFR 656.10(d)(3)(i)-(iv)' },
  'NOF-RATE-OF-PAY':      { title: 'NOF states a rate of pay ≥ PWD',            citation: '20 CFR 656.10(d)(4)' },
  'NOF-POSTING-10-DAYS':  { title: 'Posted ≥ 10 consecutive business days',     citation: '20 CFR 656.10(d)(1)(ii); 2011-PER-02628' },
  'PWD-VALIDITY-WINDOW':  { title: 'Recruitment within PWD validity window',    citation: '20 CFR 656.40(c)' },
  'WAGE-OFFER-GE-PWD':    { title: 'Offered wage ≥ prevailing wage',            citation: '20 CFR 656.10(c)(1)' },
};

// ── Numeric / date helpers ───────────────────────────────────────────────────

const ANNUAL_MULT = { hour: 2080, week: 52, 'bi-weekly': 26, biweekly: 26, month: 12, year: 1 };

export function parseMoney(v) {
  if (v == null) return null;
  const m = String(v).replace(/,/g, '').match(/-?\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : null;
}

// Annualize a wage given its unit ('Year','Hour', etc.). Defaults to annual.
export function normWage(value, unit) {
  const n = typeof value === 'number' ? value : parseMoney(value);
  if (n == null) return null;
  const key = String(unit || 'year').trim().toLowerCase().replace(/s$/, '');
  const mult = ANNUAL_MULT[key] != null ? ANNUAL_MULT[key] : 1;
  return n * mult;
}

const DEG_RANK = {
  '': 0, none: 0, 'high school/ged': 1, "associate's": 2, 'associates': 2,
  "bachelor's": 3, bachelors: 3, "master's": 4, masters: 4,
  'doctorate (ph.d.)': 5, doctorate: 5, phd: 5,
};
export function degRank(label) {
  return DEG_RANK[String(label || '').trim().toLowerCase()] ?? 0;
}

const US_HOLIDAYS_MMDD = new Set([
  '01-01', '06-19', '07-04', '11-11', '12-25', // fixed federal holidays
]);
// Count business days inclusive of both endpoints, excluding weekends + the
// fixed-date federal holidays above (floating holidays are not modeled — a
// conservative simplification noted to the user).
export function businessDaysBetween(startISO, endISO) {
  const s = new Date(startISO + 'T00:00:00');
  const e = new Date(endISO + 'T00:00:00');
  if (isNaN(s) || isNaN(e) || e < s) return null;
  let count = 0;
  for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
    const dow = d.getDay();
    if (dow === 0 || dow === 6) continue;
    const mmdd = String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    if (US_HOLIDAYS_MMDD.has(mmdd)) continue;
    count++;
  }
  return count;
}

export function daysBetween(startISO, endISO) {
  const s = new Date(startISO + 'T00:00:00');
  const e = new Date(endISO + 'T00:00:00');
  if (isNaN(s) || isNaN(e)) return null;
  return Math.round((e - s) / 86400000);
}

// ── Parse a free-text recruitment piece into structured fields ───────────────
export function parseRecruitment(text) {
  const t = text || '';
  const out = { wageLow: null, wageHigh: null, wageUnit: 'Year', degLevel: '', expMonths: null };

  // Wage: prefer an explicit range, else a single figure.
  let wageEnd = -1;
  const range = t.match(/\$\s*([\d,]+(?:\.\d+)?)\s*(?:-|–|—|to)\s*\$?\s*([\d,]+(?:\.\d+)?)/);
  if (range) {
    out.wageLow = parseMoney(range[1]);
    out.wageHigh = parseMoney(range[2]);
    wageEnd = range.index + range[0].length;
  } else {
    const single = t.match(/\$\s*([\d,]+(?:\.\d+)?)/);
    if (single) { out.wageLow = parseMoney(single[1]); wageEnd = single.index + single[0].length; }
  }
  // Detect the pay unit only in the window right after the wage figure, so an
  // unrelated phrase elsewhere (e.g. "telecommuting up to 2 days per week")
  // cannot hijack the unit.
  const win = wageEnd >= 0 ? t.slice(wageEnd, wageEnd + 24) : '';
  if (/\/\s*hr\b|per\s+hour|hourly|an?\s+hour/i.test(win)) out.wageUnit = 'Hour';
  else if (/\/\s*wk\b|per\s+week|weekly/i.test(win)) out.wageUnit = 'Week';
  else if (/\/\s*mo\b|per\s+month|monthly/i.test(win)) out.wageUnit = 'Month';
  else out.wageUnit = 'Year';

  // Minimum degree: the lowest-ranked degree word present (the stated minimum).
  const degs = [];
  if (/bachelor/i.test(t)) degs.push("Bachelor's");
  if (/master/i.test(t)) degs.push("Master's");
  if (/associate/i.test(t)) degs.push("Associate's");
  if (/doctorate|ph\.?d/i.test(t)) degs.push('Doctorate (Ph.D.)');
  if (degs.length) out.degLevel = degs.sort((a, b) => degRank(a) - degRank(b))[0];

  // Minimum experience: the smallest "N years/months" figure (the stated minimum).
  const exps = [...t.matchAll(/(\d{1,3})\s*(years?|yrs?|months?|mos?)\s+(?:of\s+)?experience/gi)]
    .map(m => (/year|yr/i.test(m[2]) ? +m[1] * 12 : +m[1]));
  if (exps.length) out.expMonths = Math.min(...exps);

  return out;
}

// ── Individual checks ─────────────────────────────────────────────────────────
const mk = (reqId, status, detail) => ({
  reqId, status, detail,
  title: (CHECKLIST[reqId] || {}).title || reqId,
  citation: (CHECKLIST[reqId] || {}).citation || '',
});

function checkScope(meta) {
  return meta.appliesF
    ? mk('ADV-F-SCOPE', 'pass', 'Governed by the §656.17(f) advertising-content rules (newspaper/journal ad or Notice of Filing).')
    : mk('ADV-F-SCOPE', 'na', "An 'additional' recruitment step — §656.17(f) content rules do not apply (Symantec); it need only advertise the occupation. Checked for consistency only.");
}

function checkEmployerName(pwd, item) {
  const t = item.rawText || '';
  const name = (pwd.employerName || '').trim();
  // Match on the core name token (drop trailing Inc./LLC/Corp punctuation noise).
  const core = name.replace(/[.,]/g, '').replace(/\b(inc|llc|corp|co|ltd)\b/gi, '').trim();
  const named = core ? new RegExp(core.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i').test(t) : false;
  const directs = /apply|send\s+resume|report\s+to|https?:\/\/|www\.|@\w/i.test(t);
  if (!name) return mk('ADV-NAME-EMPLOYER', 'review', 'Employer name not available from the PWD — verify the ad names the employer and directs applicants to it.');
  if (named && directs) return mk('ADV-NAME-EMPLOYER', 'pass', `Names "${name}" and provides an application method.`);
  if (!named) return mk('ADV-NAME-EMPLOYER', 'fail', `Does not appear to name the employer "${name}".`);
  return mk('ADV-NAME-EMPLOYER', 'flag', 'Names the employer but no clear application method detected — verify.');
}

function checkGeographic(pwd, item) {
  const t = (item.rawText || '').toLowerCase();
  const city = (pwd.city || '').toLowerCase();
  const st = (pwd.stateVal || '').toLowerCase();
  const hasCity = city && t.includes(city);
  const hasState = st && (new RegExp(`\\b${st}\\b`, 'i').test(item.rawText || ''));
  if (!city && !st) return mk('ADV-GEOGRAPHIC-AREA', 'review', 'No PWD worksite to compare against.');
  if (hasCity || hasState) {
    if (pwd.travel === 'yes' && !/travel|telecommut|remote/i.test(item.rawText || '')) {
      return mk('ADV-GEOGRAPHIC-AREA', 'flag', `States the area (${pwd.city}, ${pwd.stateVal}) but the PWD requires travel that is not disclosed.`);
    }
    return mk('ADV-GEOGRAPHIC-AREA', 'pass', `States the area of employment (${pwd.city}, ${pwd.stateVal}).`);
  }
  return mk('ADV-GEOGRAPHIC-AREA', 'flag', `Could not find the worksite area (${pwd.city}, ${pwd.stateVal}) in the text — verify the geographic area is stated.`);
}

function checkWageFloor(pwd, item, parsed, meta) {
  const reqId = meta.isNof ? 'NOF-RATE-OF-PAY' : 'ADV-WAGE-FLOOR';
  const pwdNorm = normWage(pwd.pwdWageNum != null ? pwd.pwdWageNum : pwd.pwdWage, pwd.wageUnit);
  if (pwdNorm == null) return mk(reqId, 'flag', 'PWD wage not available to compare against.');
  if (parsed.wageLow == null) {
    if (meta.isNof) return mk(reqId, 'fail', 'A Notice of Filing must state a rate of pay (§656.10(d)(4)); none found.');
    return mk(reqId, 'na', 'No wage stated. Post-2004, a §656.17(f) advertisement need not state a wage, so there is no (f)(5) violation.');
  }
  const lowNorm = normWage(parsed.wageLow, parsed.wageUnit);
  if (lowNorm >= pwdNorm) {
    const desc = parsed.wageHigh != null
      ? `Range $${parsed.wageLow.toLocaleString()}–$${parsed.wageHigh.toLocaleString()} starts at or above the PWD ($${(pwd.pwdWageNum || parseMoney(pwd.pwdWage)).toLocaleString()}).`
      : `Stated wage $${parsed.wageLow.toLocaleString()} is at or above the PWD.`;
    return mk(reqId, 'pass', desc + ' A range floor no less than the PWD is permissible (Credit Suisse).');
  }
  return mk(reqId, 'fail', `Stated wage floor $${parsed.wageLow.toLocaleString()} is below the prevailing wage — must be at or above it.`);
}

function checkNotExceed(pwd, item, parsed) {
  const issues = [];
  if (parsed.degLevel && pwd.primDegLevel && degRank(parsed.degLevel) > degRank(pwd.primDegLevel)) {
    issues.push(`requires a ${parsed.degLevel} where the PWD minimum is a ${pwd.primDegLevel}`);
  }
  if (parsed.expMonths != null && pwd.primExpMonths != null && parsed.expMonths > pwd.primExpMonths) {
    issues.push(`requires ${parsed.expMonths} months experience where the PWD minimum is ${pwd.primExpMonths}`);
  }
  if (issues.length) return mk('ADV-NOT-EXCEED-9089', 'fail', `Recruitment ${issues.join('; ')}. A requirement that exceeds the 9089/PWD is a basis for denial.`);
  // No deterministic exceedance. If the piece lists no requirements, that is the
  // permitted one-directional abbreviation; flag the skill/field semantics for review.
  if (!parsed.degLevel && parsed.expMonths == null) {
    return mk('ADV-NOT-EXCEED-9089', 'pass', 'No requirements stated — lawful abbreviation; the one-directional rule permits omitting (not exceeding) requirements.');
  }
  return mk('ADV-NOT-EXCEED-9089', 'pass', `Stated minimum (${parsed.degLevel || 'degree n/a'}${parsed.expMonths != null ? `, ${parsed.expMonths} mo` : ''}) does not exceed the PWD minimum. Note: added skills/fields and wording nuances need human review.`);
}

function checkNofContent(item) {
  const t = item.rawText || '';
  const purpose = /permanent\s+(?:alien\s+)?labor\s+certification/i.test(t);
  const evidence = /any\s+person\s+may\s+provide\s+documentary\s+evidence/i.test(t);
  // The standard ETA Notice-of-Filing template gives the Office of Foreign
  // Labor Certification DC address (200 Constitution Ave NW, Room N-5311) as the
  // Certifying Officer address — accept that block as well as the literal words.
  const coAddr = /N-?5311/i.test(t) || /200\s+constitution/i.test(t)
    || (/certifying\s+officer/i.test(t) && /\b\d{5}\b/.test(t))
    || (/office of foreign labor certification/i.test(t) && /\b\d{5}\b/.test(t));
  const missing = [];
  if (!purpose) missing.push('labor-certification purpose statement');
  if (!evidence) missing.push("'any person may provide documentary evidence' statement");
  if (!coAddr) missing.push('Certifying Officer address');
  if (missing.length === 0) return mk('NOF-CONTENT-D3', 'pass', 'Contains the labor-cert purpose, the documentary-evidence statement, and the Certifying Officer address (§656.10(d)(3)(i)-(iii)).');
  return mk('NOF-CONTENT-D3', 'fail', 'Missing required (d)(3) content: ' + missing.join('; ') + '.');
}

function checkNofPosting(item) {
  if (!item.postedDate || !item.removedDate) {
    return mk('NOF-POSTING-10-DAYS', 'flag', 'Posting "date posted / date removed" not supplied — cannot confirm the 10-consecutive-business-day posting.');
  }
  const bd = businessDaysBetween(item.postedDate, item.removedDate);
  if (bd == null) return mk('NOF-POSTING-10-DAYS', 'flag', 'Could not parse the posting dates.');
  if (bd >= 10) return mk('NOF-POSTING-10-DAYS', 'pass', `Posted ${bd} business days (≥ 10 required).`);
  return mk('NOF-POSTING-10-DAYS', 'fail', `Posted only ${bd} business days — at least 10 consecutive business days are required.`);
}

function checkNofWindow(item) {
  if (!item.postedDate || !item.filingDate) {
    return mk('NOF-CONTENT-D3', 'flag', 'Posting date and/or 9089 filing date not supplied — cannot confirm the 30–180 day window (§656.10(d)(3)(iv)).');
  }
  const d = daysBetween(item.postedDate, item.filingDate);
  if (d == null) return mk('NOF-CONTENT-D3', 'flag', 'Could not parse the dates for the 30–180 day window.');
  if (d >= 30 && d <= 180) return mk('NOF-CONTENT-D3', 'pass', `Provided ${d} days before filing (within the 30–180 day window).`);
  return mk('NOF-CONTENT-D3', 'fail', `Provided ${d} days before filing — must be between 30 and 180 days (§656.10(d)(3)(iv)).`);
}

function checkValidityWindow(pwd, item) {
  const recDate = item.pubDate || item.postedDate;
  if (!recDate) return mk('PWD-VALIDITY-WINDOW', 'flag', 'Recruitment/posting date not supplied — cannot confirm it falls within the PWD validity window.');
  if (!pwd.pwdDeterminationDate || !pwd.pwdExpirationDate) return mk('PWD-VALIDITY-WINDOW', 'flag', 'PWD validity dates not available.');
  if (recDate >= pwd.pwdDeterminationDate && recDate <= pwd.pwdExpirationDate) {
    return mk('PWD-VALIDITY-WINDOW', 'pass', `Recruitment dated ${recDate} is within the PWD validity window (${pwd.pwdDeterminationDate} to ${pwd.pwdExpirationDate}).`);
  }
  return mk('PWD-VALIDITY-WINDOW', 'fail', `Recruitment dated ${recDate} falls outside the PWD validity window (${pwd.pwdDeterminationDate} to ${pwd.pwdExpirationDate}).`);
}

function checkOfferedWage(pwd, item) {
  if (item.offeredWage == null || item.offeredWage === '') return null; // optional input
  const pwdNorm = normWage(pwd.pwdWageNum != null ? pwd.pwdWageNum : pwd.pwdWage, pwd.wageUnit);
  const offNorm = normWage(item.offeredWage, item.offeredWageUnit || pwd.wageUnit);
  if (pwdNorm == null || offNorm == null) return mk('WAGE-OFFER-GE-PWD', 'flag', 'Could not compare offered wage to the PWD.');
  return offNorm >= pwdNorm
    ? mk('WAGE-OFFER-GE-PWD', 'pass', 'Offered wage equals or exceeds the prevailing wage.')
    : mk('WAGE-OFFER-GE-PWD', 'fail', 'Offered wage is below the prevailing wage (§656.10(c)(1)).');
}

// Judgment checks surfaced (not decided) for human/LLM review in a later phase.
function reviewChecks(meta) {
  const out = [
    mk('ADV-NOT-LESS-FAVORABLE', 'review', 'Confirm no stated wage/term is less favorable than what is offered to the foreign worker (e.g. bare PWD when the actual offer is higher; undisclosed atypical benefits).'),
    mk('ADV-CLEARLY-OPEN', 'review', 'Confirm the recruitment does not affirmatively mischaracterize the position or overstate the minimum requirements (§656.10(c)(8)).'),
  ];
  if (meta.appliesF) {
    out.push(mk('ADV-VACANCY-DESC', 'review', 'Confirm the vacancy description is specific enough to apprise applicants (logical-nexus standard, §656.17(f)(3)).'));
  }
  return out;
}

// ── Public API: audit one recruitment piece against the PWD ──────────────────
export function auditRecruitmentPiece(pwd, item) {
  const meta = RECRUITMENT_TYPES[item.type] || RECRUITMENT_TYPES.newspaper_general;
  const parsed = parseRecruitment(item.rawText);
  const findings = [];

  findings.push(checkScope(meta));
  findings.push(checkEmployerName(pwd, item));
  findings.push(checkGeographic(pwd, item));
  findings.push(checkWageFloor(pwd, item, parsed, meta));
  findings.push(checkNotExceed(pwd, item, parsed));
  findings.push(checkValidityWindow(pwd, item));

  if (meta.isNof) {
    findings.push(checkNofContent(item));
    findings.push(checkNofWindow(item));
    findings.push(checkNofPosting(item));
  }
  const off = checkOfferedWage(pwd, item);
  if (off) findings.push(off);

  findings.push(...reviewChecks(meta));

  // Verdict rolls up affirmative problems only. 'review' items (human-judgment
  // checks) and 'na' items do not by themselves downgrade the verdict — they are
  // surfaced separately as items needing review.
  const has = (s) => findings.some(f => f.status === s);
  const overallVerdict = has('fail') ? 'defective' : has('flag') ? 'compliant_with_flags' : 'compliant';
  const reviewCount = findings.filter(f => f.status === 'review').length;

  return { type: item.type, typeLabel: meta.label, parsed, findings, overallVerdict, reviewCount };
}

export const STATUS_ORDER = ['fail', 'flag', 'review', 'pass', 'na'];
