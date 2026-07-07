#!/usr/bin/env python3
"""
BALCA CFR-citation heuristic tagger — Phase 4, step 1.

For every BALCA decision in rag_chunks (corpus='balca'):
  1. Regex-extract all 20 CFR 656.x cites (normalized) and key en banc
     precedent names from the decision's chunks.
  2. Pick the PRIMARY issue: most-mentioned substantive cite, excluding
     procedural boilerplate (656.26/656.27 BALCA review, 656.1/656.2 scope,
     bare 656.3 definitions) which appears in nearly every decision.
  3. Map CFR section -> ETA-9089 form section (crosswalk below).
  4. Write per-decision tags to balca_issue_tags and backfill each CHUNK's
     rag_chunks.cfr_citation with that chunk's own dominant substantive cite
     (powers the citation resolver's cfr LIKE boost).

Pure regex, no LLM, no API. ~52K chunks, runs in about a minute.

Usage:
    venv/bin/python3 perm-research/tag_balca_cfr.py [--dry-run] [--report-only]
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[1] / ".env")
DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")

# 20 C.F.R. § 656.17(e)(1)(ii)(B) — capture section + up to 3 paren levels.
CFR_RX = re.compile(
    r"(?:20\s*C\.?\s*F\.?\s*R\.?\s*)?(?:§+|[Ss]ections?\s+)?\s*"
    r"\b656\.(\d{1,2})"
    r"((?:\s*\(\s*[A-Za-z0-9]{1,3}\s*\)){0,3})")

PROCEDURAL = {"656.26", "656.27", "656.1", "656.2", "656.5"}
DEFINITIONS = {"656.3"}

PRECEDENT_RX = {
    "Kellogg": re.compile(r"\bKellogg\b"),
    "Information Industries": re.compile(r"Information\s+Industries", re.I),
    "Modular Container": re.compile(r"Modular\s+Container", re.I),
    "Delitizer": re.compile(r"\bDelitizer\b", re.I),
    "HealthAmerica": re.compile(r"Health\s*America", re.I),
    "Lucky Horse": re.compile(r"Lucky\s+Horse", re.I),
    "Il Cortile": re.compile(r"Il\s+Cortile", re.I),
}

# CFR section/subsection -> 9089 form-section crosswalk
def form_section_for(section, sub):
    if section == "656.17":
        return {"e": "H.recruitment", "f": "H.advertising_content",
                "g": "H.recruitment_report", "h": "G.requirements",
                "i": "AppA.qualifications", "j": "G.requirements",
                "k": "G.12.layoff", "l": "A.16-17.bona_fide"}.get(sub, "G/H.general_17")
    return {
        "656.10": "H.e.notice_and_general",
        "656.11": "post-filing.modifications",
        "656.12": "G.11.payment",
        "656.15": "schedule_A",
        "656.18": "appD.college_teacher",
        "656.19": "G.2.live_in_domestic",
        "656.20": "audit",
        "656.21": "supervised_recruitment",
        "656.24": "CO.determination",
        "656.30": "validity_scope",
        "656.31": "fraud_revocation",
        "656.32": "revocation",
        "656.40": "E.wage_pwd",
        "656.41": "pwd.review",
    }.get(section, "other")


def norm_cites(text):
    """Return Counter of normalized cites like '656.17(e)' / '656.24'."""
    c = Counter()
    for m in CFR_RX.finditer(text):
        section = f"656.{m.group(1)}"
        subs = re.findall(r"\(\s*([A-Za-z0-9]{1,3})\s*\)", m.group(2) or "")
        sub1 = subs[0].lower() if subs else None
        key = f"{section}({sub1})" if sub1 else section
        c[key] += 1
    return c


def split_key(key):
    m = re.match(r"(656\.\d{1,2})(?:\((\w{1,3})\))?$", key)
    return (m.group(1), m.group(2)) if m else (key, None)


def substantive(key):
    sec, _ = split_key(key)
    return sec not in PROCEDURAL and sec not in DEFINITIONS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(DB_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT id, source_id, chunk_text FROM rag_chunks "
                    "WHERE corpus='balca' ORDER BY source_id, chunk_index")
        rows = cur.fetchall()

    per_decision = defaultdict(Counter)
    per_decision_prec = defaultdict(set)
    decision_text = defaultdict(str)
    chunk_updates = []  # (chunk_id, dominant cite)
    for cid, sid, text in rows:
        if len(decision_text[sid]) < 3000:
            decision_text[sid] += (text or "")[:3000]
        cites = norm_cites(text or "")
        per_decision[sid].update(cites)
        for name, rx in PRECEDENT_RX.items():
            if rx.search(text or ""):
                per_decision_prec[sid].add(name)
        subst = Counter({k: v for k, v in cites.items() if substantive(k)})
        if subst:
            chunk_updates.append((cid, subst.most_common(1)[0][0]))

    tag_rows, primary_dist = [], Counter()
    tagged, untagged = 0, 0
    for sid, cites in per_decision.items():
        subst = Counter({k: v for k, v in cites.items() if substantive(k)})
        pool = subst or cites
        if not pool:
            untagged += 1
            txt = decision_text.get(sid, "").lower()[:3000]
            kind = ("withdrawal" if "withdraw" in txt else
                    "dismissal" if "dismiss" in txt else
                    "remand" if "remand" in txt else "short_order")
            tag_rows.append((sid, "disposition", kind, 1, True,
                             "none", None))
            primary_dist[f"disposition({kind}) -> none"] += 1
            continue
        tagged += 1
        primary_key = pool.most_common(1)[0][0]
        for key, n in pool.most_common(12):
            sec, sub = split_key(key)
            tag_rows.append((sid, sec, sub, n, key == primary_key,
                             form_section_for(sec, sub),
                             sorted(per_decision_prec.get(sid, [])) or None))
        psec, psub = split_key(primary_key)
        primary_dist[f"{primary_key} -> {form_section_for(psec, psub)}"] += 1

    total = tagged + untagged
    print(f"Decisions: {total}  tagged: {tagged} ({tagged/total*100:.1f}%)  "
          f"no-cite: {untagged} ({untagged/total*100:.1f}%)")
    print(f"Tag rows: {len(tag_rows)}   chunk cfr backfills: {len(chunk_updates)}")
    print("\nPrimary-issue distribution (top 25):")
    for k, n in primary_dist.most_common(25):
        print(f"  {k:<45} {n:>6}  ({n/tagged*100:4.1f}%)")

    if args.dry_run or args.report_only:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM balca_issue_tags")
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO balca_issue_tags
              (source_id, cfr_section, subsection, mentions, is_primary,
               form_section, precedents)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, tag_rows, page_size=500)
        psycopg2.extras.execute_batch(cur, """
            UPDATE rag_chunks SET cfr_citation=%s WHERE id=%s
        """, [(cite, cid) for cid, cite in chunk_updates], page_size=500)
    conn.commit()
    conn.close()
    print("\nWritten: balca_issue_tags + rag_chunks.cfr_citation backfill.")


if __name__ == "__main__":
    main()
