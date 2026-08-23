#!/usr/bin/env python3
"""
backfill_balca_outcomes.py
==========================
Re-detects and fills NULL outcomes for BALCA decisions using the ORDER
section of each decision's full_text.

Outcome mapping:
  Affirmed   -- CO denial affirmed; employer loses
  Dismissed  -- appeal procedurally dismissed or withdrawn; also admin closings
  Remanded   -- sent back to CO for further proceedings
  Reversed   -- CO denial explicitly reversed; employer wins
  Unknown    -- has text but no detectable outcome language

Vacated notes:
  Vacated+Remanded (the most common combined order) -> Remanded
  Pure Vacated (no remand) -> Reversed

Usage:
    python backfill_balca_outcomes.py [--dry-run] [--limit N] [--reprocess-all]
"""

import argparse
import os
import re

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "app", ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions"
)

TAIL_CHARS = 2500

_P_VACATED_REMANDED = re.compile(
    r'(?:VACAT|vacating).{0,200}?REMAND|REMAND.{0,200}?VACAT',
    re.IGNORECASE | re.DOTALL,
)
_P_GRANTED = re.compile(
    r'(?:certif\w*\s+(?:is\s+)?GRANTED|HEREBY\s+GRANT|GRANT\w*\s+(?:labor\s+)?certif'
    r'|IT\s+IS\s+(?:HEREBY\s+)?ORDERED\s+that\s+(?:labor\s+)?certif\w+\s+(?:is\s+)?GRANT)',
    re.IGNORECASE,
)
_P_VACATED   = re.compile(r'\b(?:VACAT\w+|vacating\s+the\s+denial)\b', re.IGNORECASE)
_P_REMANDED  = re.compile(r'\bREMAND\w*\b', re.IGNORECASE)
_P_REVERSED  = re.compile(r'\bREVERS\w*\b', re.IGNORECASE)
_P_AFFIRMED  = re.compile(r'\bAFFIRM\w*\b', re.IGNORECASE)
_P_DISMISSED = re.compile(
    r'\b(?:DISMISS\w*|HEREBY\s*DISMISS\w*|ADMINISTRATIVELY\s+CLOS\w*|WITHDRAWN)\b',
    re.IGNORECASE,
)


_P_ORDER_CLAUSE = re.compile(r'IT\s+IS\s+(?:HEREBY\s+)?ORDERED', re.IGNORECASE)
_P_CAPTION = re.compile(
    r'DECISION\s+AND\s+ORDER\s+(?:[A-Z ,]{0,40}?)\b(AFFIRM|REVERS|REMAND|VACAT|DISMISS|GRANT)\w*',
    re.IGNORECASE,
)


_P_FOR_CERT = re.compile(r'REMAND\w*.{0,80}?(?:for\s+(?:the\s+)?(?:purpose\s+of\s+)?(?:grant\w*|certification|issuance)|to\s+grant)', re.IGNORECASE | re.DOTALL)


def _classify(zone):
    """Classify a short zone that is KNOWN to be dispositive (an order clause or caption).
    Convention (Kellen, 2026-08-22): a remand that merely directs the CO to grant/certify is a
    REVERSAL; only a remand for further proceedings (submit evidence, reconsider) is Remanded."""
    if _P_REVERSED.search(zone):
        return "Reversed"
    if _P_AFFIRMED.search(zone):          # before grant/remand: "AFFIRMED ... CO's request for remand to grant"
        return "Affirmed"
    if _P_GRANTED.search(zone) or _P_FOR_CERT.search(zone):
        return "Reversed"
    if _P_VACATED_REMANDED.search(zone) or _P_REMANDED.search(zone):
        return "Remanded"
    if _P_VACATED.search(zone):
        return "Reversed"
    if _P_DISMISSED.search(zone):
        return "Dismissed"
    return None


_P_ORDER_END = re.compile(r'Entered at the direction|For the (?:panel|Board)|NOTICE OF OPPORTUNITY|SO ORDERED', re.IGNORECASE)


def detect_outcome(full_text):
    return detect_outcome_ex(full_text)[0]


def detect_outcome_ex(full_text):
    """Outcome from the dispositive text ONLY, in priority order:
      1. the LAST "IT IS ORDERED" clause (the ORDER paragraph) - ~94% of decisions
      2. the caption "DECISION AND ORDER AFFIRMING/REVERSING/... "
      3. the final TAIL_CHARS
    Never the whole document: discussion of precedent ("the Board has vacated
    denials...") must not outrank the order (2026-08-22, Idiada 2025-PER-00072)."""
    """Returns (outcome, source) where source is 'order' | 'caption' | 'tail' | None."""
    if not full_text or not full_text.strip():
        return None, None
    orders = list(_P_ORDER_CLAUSE.finditer(full_text))
    if orders:
        zone = full_text[orders[-1].start(): orders[-1].start() + 700]
        e = _P_ORDER_END.search(zone, 20)
        if e:
            zone = zone[:e.start()]
        r = _classify(zone)
        if r:
            return r, "order"
    m = _P_CAPTION.search(full_text[:3000])
    if m:
        r = _classify(m.group(0))
        if r:
            return r, "caption"
    tail = full_text[-TAIL_CHARS:] if len(full_text) > TAIL_CHARS else full_text
    return (_classify(tail) or "Unknown"), "tail"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=DB_URL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reprocess-all", action="store_true",
                        help="Re-detect on ALL decisions, not just NULLs")
    args = parser.parse_args()

    conn = psycopg2.connect(args.db_url)
    print(f"Connected: {args.db_url.split('@')[-1]}")

    where = "doc_type != 'docketing_notice' AND full_text != ''"
    if not args.reprocess_all:
        where += " AND outcome IS NULL"
    limit_clause = f"LIMIT {args.limit}" if args.limit else ""

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT id, case_number, full_text FROM decisions "
            f"WHERE {where} ORDER BY id {limit_clause}"
        )
        rows = cur.fetchall()

    print(f"Processing {len(rows):,} decisions...")

    counts = {}
    updates = []
    for row in rows:
        outcome = detect_outcome(row["full_text"])
        if outcome is None:
            counts["no_text"] = counts.get("no_text", 0) + 1
            continue
        counts[outcome] = counts.get(outcome, 0) + 1
        updates.append({"id": row["id"], "outcome": outcome})

    print("\nDetected outcomes:")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:12} : {v:,}")

    if args.dry_run:
        print("\nDRY RUN -- no changes written")
        # Sample reversed for spot-check
        sample = [u for u in updates if u["outcome"] == "Reversed"][:5]
        if sample:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, case_number, employer_name FROM decisions WHERE id = ANY(%s)",
                    ([s["id"] for s in sample],)
                )
                print("Sample Reversed cases:")
                for r in cur.fetchall():
                    print(f"  {r['case_number']} -- {r['employer_name']}")
        conn.close()
        return

    if updates:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                "UPDATE decisions SET outcome = %(outcome)s WHERE id = %(id)s",
                updates,
                page_size=500,
            )
        conn.commit()
        print(f"\nWritten: {len(updates):,} outcomes updated")
    else:
        print("\nNo updates needed")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
