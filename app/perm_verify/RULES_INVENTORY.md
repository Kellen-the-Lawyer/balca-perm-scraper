# PERM Verification System — Rule Inventory (Phase 1 spec)

Flag levels:
- **RED** — will (or is highly likely to) result in denial as filed.
- **YELLOW** — grey area, audit trigger, or documentation risk; certifiable but flagged.

Every flag emits: `{level, rule_id, section_item, message, citation_type, citation}`.
citation_type ∈ {typo, completeness, regulation, form_instructions, balca, faq, data_check}.

## Tier 1 — Completeness & internal consistency (deterministic)

| ID | Level | Check | Citation |
|----|-------|-------|----------|
| T1-001 | RED | Any required (*) field blank/N/A where an answer is required | 20 CFR 656.17(a)(1) (incomplete apps denied); Instructions p.1 |
| T1-002 | RED | D.1 Appendix A attached = No | Instructions §D.1 ("application will be denied") |
| T1-003 | RED | I.1 certification = No | 20 CFR 656.10(c) |
| T1-004 | RED | H.e.1f (did NOT post notice) marked | 20 CFR 656.10(d) |
| T1-005 | RED | E.1 PWD number malformed (not P-100-xxxxx-xxxxxx) | typo; Instructions §E.1 |
| T1-006 | RED | A.3 / B.5 / F.a.2 address is a PO Box | Instructions §A.3, §B.5, §F.a.2 |
| T1-007 | RED | A.12 FEIN not 9 digits (or looks like SSN pattern) | Instructions §A.12 |
| T1-008 | YELLOW | A.13 NAICS code invalid/retired against NAICS reference table | Instructions §A.13; data_check |
| T1-009 | RED | B (POC) name+phone+email identical to C (attorney) and attorney not employer employee | Instructions §B note, §C note |
| T1-010 | RED | Conditional (§) field blank where trigger condition met (full dependency map: G.2→2a/2b/2c; G.4→4a; G.4+G.4a→4b; G.5→5a/5b; F.b.1→F.b.2; H.b.1a/1b→H.c; H.b.1a→H.d; H.b.1c→App D; G.6–G.12 Yes→App C entry) | 656.17(a)(1); Instructions per-item |
| T1-011 | RED | G.6–G.12 marked Yes but no matching Appendix C section (match on section_item value) | Instructions Appendix C note |
| T1-012 | YELLOW | Appendix C entry present but its G-item is No (orphan explanation) | typo/consistency |
| T1-013 | RED | F.b.1 Yes but Appendix B attached = No | Instructions §F.b.2 |
| T1-014 | RED | H.b = 1c (college/univ teacher) but no Appendix D | Instructions §H.b.1c |
| T1-015 | YELLOW | H.b = 1d (Schedule A/sheepherder) — case must go to USCIS, not DOL | Instructions §H.b.1d |
| T1-016 | RED | Date fields malformed (MM/DD/YYYY vs MM/YYYY per field spec) | typo |
| T1-017 | YELLOW | A.14 employees-in-area = 0 or implausibly low vs. recruitment claims | data_check; audit risk |
| T1-018 | RED | Appendix A worker info identical to Section B/C contact (unless live-in domestic) | Instructions Appendix A note |
| T1-019 | YELLOW | Appendix A education year attained after any experience start that presupposes the degree | consistency |
| T1-020 | RED | E.3 wage range: To < From | typo |
| T1-021 | RED | Multi-file upload names different foreign workers (documents mixed across cases) | data_check; cross-file consistency |

## Tier 2 — Regulatory timing & recruitment rules (deterministic, needs filing_date)

| ID | Level | Check | Citation |
|----|-------|-------|----------|
| T2-001 | RED | SWA job order duration < 30 days (end − start) | 20 CFR 656.17(e)(1)(i)(A) |
| T2-002 | RED | SWA job order end > 180 days before filing, or job order ends < 30 days before filing | 656.17(e)(1)(i); Instructions §H.c note |
| T2-003 | RED | Sunday ads: either ad date not ≥30 and ≤180 days before filing | 656.17(e)(1)(i)(B); 656.17(e)(1)(i) |
| T2-004 | YELLOW | Ad dates not Sundays (calendar check) when ad2_type = newspaper and H.c.2 Sunday edition = Yes | 656.17(e)(1)(i)(B)(1) |
| T2-005 | RED | H.c.2 Sunday edition = No but worksite in major metro MSA (Sunday edition exists) | 656.17(e)(1)(i)(B)(2); BALCA on rural exception |
| T2-006 | RED | Professional occupation (H.b=1a): fewer than 3 additional recruitment steps completed | 656.17(e)(1)(ii) |
| T2-007 | RED | More than one additional step conducted solely within 30 days of filing | 656.17(e)(1)(ii) |
| T2-008 | RED | Any additional step > 180 days before filing | 656.17(e)(1)(ii) |
| T2-009 | RED | Notice of posting window violated (<30 or >180 days before filing) where dates known | 656.10(d)(3)(i)–(iv) |
| T2-010 | YELLOW | Physical posting: 10 consecutive business days cannot be verified from form (attest-only) | 656.10(d)(1)(ii); doc-request risk |
| T2-011 | RED | H.e combination invalid: 1c or 1d without 1b; 1a+1b both marked; 1e or 1f with others | Instructions §H.e note |
| T2-012 | YELLOW | Employee referral program used as a step (needs proof of incentives + duration) | 656.17(e)(1)(ii)(G); BALCA (e.g., *Clearstream Banking*) |
| T2-013 | YELLOW | Additional step end date after filing date (step not complete at filing) | 656.17(e)(1)(ii) |
| T2-014 | RED | Occupation is professional per O*NET (bachelor's usual) but H.b=1b non-professional recruitment used | 656.17(e); 656.20; BALCA line on professional misclassification |
| T2-015 | YELLOW | Occupation borderline professional/non-professional (O*NET education distribution ambiguous) | 656.20 grey area |

## Tier 3 — Wage rules (needs PWD data + OEWS tables)

| ID | Level | Check | Citation |
|----|-------|-------|----------|
| T3-001 | RED | Offered wage (E.3 From) < prevailing wage on PWD | 656.10(c)(1); Instructions §E note (higher of two wages if dual-requirement PWD) |
| T3-002 | RED | Wage expressed as range and bottom of range < PWD wage | 656.17(e); Labor Condition Stmt (1) |
| T3-003 | YELLOW | Offered wage within 2% of PW floor (no cushion; renewal-year PW increase risk) | practice heuristic; data_check vs mv_wage_yoy |
| T3-004 | YELLOW | E.5 wage conditions mention commissions/bonuses without guaranteed-basis language | 656.10(c)(2); Labor Condition Stmt (2) |
| T3-005 | RED | PWD expired at filing (validity window vs filing date, if PWD dates provided) | 656.40(c) |
| T3-006 | YELLOW | Offered wage anomalous vs OEWS distribution for SOC×area (e.g., < p10) | data_check; audit signal |

## Tier 4 — Audit-risk & substantive (scored YELLOW; BALCA/RAG-backed)

| ID | Level | Check | Citation |
|----|-------|-------|----------|
| T4-001 | YELLOW | A.16 Yes (ownership interest) | 656.17(l); *Modular Container Systems* factors |
| T4-002 | YELLOW | A.17 Yes (familial relationship) | 656.17(l); audit near-certain |
| T4-003 | YELLOW | G.5 Yes + G.5a Yes (experience with employer, substantially comparable) | 656.17(i)(3); *Delitizer Corp.* line |
| T4-004 | YELLOW | G.7 Yes combination of occupations | 656.17(h)(3); *Kellogg* context |
| T4-005 | YELLOW | G.8 Yes foreign language | 656.17(h)(2); business necessity per *Lucky Horse Fashion* |
| T4-006 | YELLOW | G.9 Yes exceeds SVP | 656.17(h)(1); business necessity (*Information Industries* test) |
| T4-007 | RED | G.9 answered No but requirements (from PWD/9141 data) exceed O*NET Job Zone SVP for SOC | data_check vs O*NET; misrepresentation/denial risk; 656.17(h)(1) |
| T4-008 | YELLOW | G.11 Yes payment received | 656.12(b) |
| T4-009 | YELLOW | G.12 Yes layoff within 6 months | 656.17(k); notify-and-consider duty |
| T4-010 | YELLOW | G.4a Yes + 4b "I DO NOT ACCEPT" | *Francis Kellogg*, 1994-INA-465 (en banc); denial line where alt reqs not substantially equivalent |
| T4-011 | YELLOW | F.c travel/roving language ("Various Worksites", % travel) without matching PWD coverage | 656.10; BALCA roving-employee line |
| T4-012 | YELLOW | Appendix C explanation < ~200 chars for business-necessity items (thin justification) | heuristic; *Information Industries* standard |
| T4-013 | YELLOW | Appendix A duties text near-identical across employers (copy-paste tailoring signal) | audit heuristic; fuzzy-match |
| T4-014 | YELLOW | Worker experience gap: qualifying experience months < requirement months (when 9141 reqs available) | 656.17(i); *substantially comparable* analysis |
| T4-015 | YELLOW | G.3 = No (no foreign degree equivalent) but Appendix A shows only foreign degree | consistency; I-140 downstream risk |
| T4-016 | YELLOW | Employer denial-rate percentile high for this SOC (OFLC disclosure data) | data_check; base-rate signal |

## Out of scope for the form-only checker (needs documents)
Recruitment tear sheets, notice content sufficiency (656.10(d)(4) wage/contact content), recruitment report, applicant rejection reasons. These become Phase 5 (document-level audit-file checker).

## Engine notes
- Tier 1–2 = pure functions over the schema JSON + filing_date. No DB.
- Tier 3 needs: PWD record (user-supplied or 9141 extract via existing extract_pwd.py), OEWS wage tables (already in DB).
- T2-014/T4-007 need O*NET Job Zone/SVP by SOC → load onet/ flat files into Postgres (pending task).
- Tier 4 citations resolve to rag_chunks retrieval (corpus IN ('balca','regulation','dol_faqs')) scoped by cfr_citation; each flag links supporting chunks.
- Ingest task: ETA-9089 General Instructions + Appendices (uploaded PDFs) into a 'form_instructions_dol' label so instruction-based flags can cite chunks.
