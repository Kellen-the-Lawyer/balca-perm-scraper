#!/usr/bin/env python3
"""
load_balca_decisions.py — the missing link between the BALCA scraper and Postgres.

    balca_perm.sqlite (scraper output)  ->  download PDF  ->  pdfplumber  ->  decisions

Model (Kellen ruling 2026-08-21): ONE ROW PER DOCKET. When a docket has several
documents, the highest-ranked document type wins (Case Decision > Motion Recon >
Order); within a rank, the newest wins. An existing row is overwritten only when
the candidate outranks it or is newer at the same rank. On overwrite, the stale
rag_chunks / balca_issue_tags for that decision id are deleted so that
ingest_rag.py re-chunks it on the next run.

Usage:
    venv/bin/python scripts/ingest/load_balca_decisions.py [--dry-run] [--limit N] [--since YYYY-MM-DD]
Env:  DATABASE_URL (defaults to Homebrew 5433)
"""
import argparse, os, re, sqlite3, sys, time, random, shutil, signal
from datetime import date, datetime
from pathlib import Path

import pdfplumber, psycopg2, psycopg2.extras
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
load_dotenv(REPO / ".env")
sys.path.insert(0, str(REPO / "scripts" / "ingest"))
from backfill_balca_outcomes import detect_outcome  # noqa: E402
from balca_perm_scraper.client import ScraperClient  # noqa: E402
from balca_perm_scraper.config import SETTINGS  # noqa: E402

DB_URL   = os.environ.get("DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")
SQLITE   = SETTINGS.database_path
PDF_DIR  = SETTINGS.raw_dir / "pdfs"
PREV_DIR = SETTINGS.raw_dir / "pdfs_superseded"

RANK = {"Case Decision": 3, "Motion Recon/Modification Disp": 2, "Order": 1, "": 1, None: 1}
PG_RANK = {"decision": 3, "docketing_notice": 1}
DOCKETING_RE = re.compile(r"NOTICE\s+OF\s+DOCKETING", re.IGNORECASE)
DOWNLOAD_DEADLINE_S = 90  # hard wall-clock cap per PDF; httpx timeout only resets between bytes


class _Deadline(Exception):
    pass


def _alarm(signum, frame):
    raise _Deadline(f"download exceeded {DOWNLOAD_DEADLINE_S}s")


def pick_candidates(since=None):
    """Best document per docket from sqlite (PER cases only)."""
    con = sqlite3.connect(SQLITE)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT stable_id, case_name, docket_number, decision_date, document_type, pdf_url "
        "FROM decisions WHERE case_type='PER' AND docket_number IS NOT NULL AND pdf_url IS NOT NULL"
    ).fetchall()
    best = {}
    for r in rows:
        key = (RANK.get(r["document_type"], 1), r["decision_date"] or "")
        if r["docket_number"] not in best or key > best[r["docket_number"]][0]:
            best[r["docket_number"]] = (key, dict(r))
    cands = [v[1] for v in best.values()]
    if since:
        cands = [c for c in cands if (c["decision_date"] or "") >= since]
    return cands


def load_existing(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, case_number, decision_date, doc_type, source_url FROM decisions")
        return {r["case_number"]: r for r in cur.fetchall()}


def needs_load(cand, existing):
    if existing is None:
        return "insert"
    if existing["source_url"] == cand["pdf_url"]:
        return None
    c_rank = RANK.get(cand["document_type"], 1)
    e_rank = PG_RANK.get(existing["doc_type"], 3)
    c_date = cand["decision_date"] or ""
    e_date = existing["decision_date"].isoformat() if existing["decision_date"] else ""
    if c_rank > e_rank or (c_rank == e_rank and c_date > e_date):
        return "replace"
    return None


def extract_text(path):
    parts, errs = [], []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            try:
                parts.append(page.extract_text() or "")
            except Exception as e:  # noqa: BLE001
                errs.append(f"p{i+1}: {e}")
    return "\n\n".join(parts).strip(), len(parts), ("; ".join(errs) or None)


def employer_from_case_name(name):
    if not name:
        return None
    name = re.sub(r"^\s*In\s+re:?\s+", "", name, flags=re.IGNORECASE)
    m = re.search(r"\s+v\.?\s+(.+)$", name)  # "Worker v. Employer" -> Employer
    return (m.group(1) if m else name).strip() or None


def upsert(conn, cand, action, existing, pdf_path, text, pages, errs):
    is_notice = bool(DOCKETING_RE.search(text[:3000])) and cand["document_type"] != "Case Decision"
    doc_type = "docketing_notice" if is_notice else "decision"
    outcome = None if is_notice else detect_outcome(text)
    quality = "ok" if len(text) > 500 else ("empty" if not text else "short")
    vals = dict(
        case_number=cand["docket_number"], filename=pdf_path.name, pdf_path=str(pdf_path),
        decision_date=cand["decision_date"] or None, employer_name=employer_from_case_name(cand["case_name"]),
        outcome=outcome, full_text=text, text_extracted=bool(text), parse_errors=errs, doc_type=doc_type,
        extraction_status="ok" if text else "failed", extraction_error=errs, extracted_at=datetime.now(),
        extraction_page_count=pages, extraction_char_count=len(text), extraction_quality=quality,
        source_url=cand["pdf_url"],
    )
    with conn.cursor() as cur:
        if action == "replace":
            sid = str(existing["id"])
            cur.execute("DELETE FROM rag_chunks WHERE corpus='balca' AND source_id=%s", (sid,))
            cur.execute("DELETE FROM balca_issue_tags WHERE source_id=%s", (sid,))
            sets = ", ".join(f"{k}=%({k})s" for k in vals if k != "case_number")
            vals["id"] = existing["id"]
            cur.execute(f"UPDATE decisions SET {sets}, extraction_attempts=extraction_attempts+1, "
                        f"ingested_at=NOW() WHERE id=%(id)s", vals)
        else:
            cols = ", ".join(vals)
            cur.execute(f"INSERT INTO decisions ({cols}, extraction_attempts) "
                        f"VALUES ({', '.join(f'%({k})s' for k in vals)}, 1)", vals)
    conn.commit()
    return doc_type, outcome


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--since", help="only consider sqlite docs dated >= YYYY-MM-DD")
    a = ap.parse_args()

    conn = psycopg2.connect(DB_URL)
    existing = load_existing(conn)
    work = []
    for c in pick_candidates(a.since):
        act = needs_load(c, existing.get(c["docket_number"]))
        if act:
            work.append((act, c))
    work.sort(key=lambda w: w[1]["decision_date"] or "")
    if a.limit:
        work = work[: a.limit]
    print(f"sqlite dockets considered; {len(work)} to load "
          f"({sum(1 for w in work if w[0]=='insert')} insert, {sum(1 for w in work if w[0]=='replace')} replace)")
    if a.dry_run:
        for act, c in work:
            print(f"  {act:7} {c['docket_number']} {c['decision_date']} {c['document_type']}")
        return

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    with ScraperClient() as client:
        for act, c in work:
            dest = PDF_DIR / f"{c['docket_number']}.pdf"
            if act == "replace" and dest.exists():
                PREV_DIR.mkdir(parents=True, exist_ok=True)
                stamp = existing[c["docket_number"]]["decision_date"] or "undated"
                shutil.move(dest, PREV_DIR / f"{c['docket_number']}__{stamp}.pdf")
            tmp = dest.with_suffix(".part")
            try:
                signal.signal(signal.SIGALRM, _alarm); signal.alarm(DOWNLOAD_DEADLINE_S)
                try:
                    got = client.stream_to_file(c["pdf_url"], tmp)
                finally:
                    signal.alarm(0)
                if not got:
                    print(f"  FAIL {c['docket_number']}: 403/404 {c['pdf_url']}"); fail += 1; continue
                tmp.rename(dest)
                text, pages, errs = extract_text(dest)
                doc_type, outcome = upsert(conn, c, act, existing.get(c["docket_number"]), dest, text, pages, errs)
                print(f"  {act:7} {c['docket_number']} {c['decision_date']} -> {doc_type}/{outcome} ({len(text)} chars)")
                ok += 1
            except Exception as e:  # noqa: BLE001
                conn.rollback(); tmp.unlink(missing_ok=True)
                print(f"  FAIL {c['docket_number']}: {e}"); fail += 1
                if isinstance(e, _Deadline):
                    # stale socket inside the client; start a fresh one
                    client.client.close(); client.client = ScraperClient().client
            time.sleep(SETTINGS.pdf_sleep_seconds + random.uniform(0, SETTINGS.pdf_sleep_jitter))
    print(f"Done. loaded={ok} failed={fail}")
    sys.exit(1 if fail and not ok else 0)


if __name__ == "__main__":
    main()
