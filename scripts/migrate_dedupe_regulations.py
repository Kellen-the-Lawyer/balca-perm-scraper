"""
One-time migration: fix cfr_part misparses, dedupe regulations_docs on
(cfr_title, cfr_part), carry PDF paths onto kept rows, purge orphaned
regulation rag_chunks, and re-parse section indexes with the fixed regex.

Usage:
  python scripts/migrate_dedupe_regulations.py --dry-run
  python scripts/migrate_dedupe_regulations.py --apply
"""
import argparse, asyncio, json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "ingest"))
from ingest_regulations import FILENAME_RE, extract_sections  # noqa: E402

import asyncpg  # noqa: E402

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")


async def fix_parts(conn, apply):
    """Re-derive cfr_part from filename (fixes 41 CFR '101' vs '101-10')."""
    rows = await conn.fetch(
        "SELECT id, filename, cfr_title, cfr_part FROM regulations_docs")
    fixes = []
    for r in rows:
        m = FILENAME_RE.match(r["filename"])
        if not m:
            continue
        part = m.group(2).lower().strip()
        if part != (r["cfr_part"] or ""):
            fixes.append((r["id"], r["cfr_part"], part))
    print(f"[parts] {len(fixes)} rows need cfr_part corrections")
    for id_, old, new in fixes[:15]:
        print(f"   id {id_}: {old!r} -> {new!r}")
    if len(fixes) > 15:
        print(f"   ... and {len(fixes)-15} more")
    if apply:
        for id_, _, new in fixes:
            await conn.execute(
                "UPDATE regulations_docs SET cfr_part=$1 WHERE id=$2", new, id_)
    return len(fixes)


async def dedupe(conn, apply):
    """Per (cfr_title, cfr_part): keep freshest as_of_date (tie: ingested_at).
    Carry a .pdf pdf_path from a deleted twin onto a .txt keeper. Delete the
    losers and their regulation rag_chunks."""
    groups = await conn.fetch("""
        SELECT cfr_title, lower(cfr_part) AS part,
               array_agg(id ORDER BY as_of_date DESC NULLS LAST,
                         ingested_at DESC) AS ids
        FROM regulations_docs
        WHERE cfr_title IS NOT NULL AND cfr_part IS NOT NULL
        GROUP BY cfr_title, lower(cfr_part)
        HAVING count(*) > 1
        ORDER BY cfr_title, part""")
    total_lost = chunks_purged = 0
    for g in groups:
        keeper, losers = g["ids"][0], g["ids"][1:]
        krow = await conn.fetchrow(
            "SELECT pdf_path FROM regulations_docs WHERE id=$1", keeper)
        pdf_carry = None
        if (krow["pdf_path"] or "").lower().endswith(".txt"):
            for lid in losers:
                lrow = await conn.fetchrow(
                    "SELECT pdf_path FROM regulations_docs WHERE id=$1", lid)
                if (lrow["pdf_path"] or "").lower().endswith(".pdf"):
                    pdf_carry = lrow["pdf_path"]
                    break
        n_chunks = await conn.fetchval(
            "SELECT count(*) FROM rag_chunks WHERE corpus='regulation' "
            "AND source_id = ANY($1)", [str(i) for i in losers])
        print(f"[dedupe] {g['cfr_title']} CFR {g['part']}: keep {keeper}, "
              f"drop {list(losers)} ({n_chunks} chunks)"
              + (f", carry pdf" if pdf_carry else ""))
        total_lost += len(losers)
        chunks_purged += n_chunks
        if apply:
            if pdf_carry:
                await conn.execute(
                    "UPDATE regulations_docs SET pdf_path=$1 WHERE id=$2",
                    pdf_carry, keeper)
            await conn.execute(
                "DELETE FROM rag_chunks WHERE corpus='regulation' "
                "AND source_id = ANY($1)", [str(i) for i in losers])
            await conn.execute(
                "DELETE FROM regulations_docs WHERE id = ANY($1)", losers)
    print(f"[dedupe] groups={len(groups)} rows_to_delete={total_lost} "
          f"chunks_to_purge={chunks_purged}")
    return len(groups)


async def reparse_sections(conn, apply):
    """Rebuild the sections index for every doc with the fixed regex."""
    ids = [r["id"] for r in await conn.fetch(
        "SELECT id FROM regulations_docs ORDER BY id")]
    changed = 0
    for id_ in ids:
        row = await conn.fetchrow(
            "SELECT cfr_part, full_text, sections FROM regulations_docs "
            "WHERE id=$1", id_)
        secs = extract_sections(row["full_text"] or "", row["cfr_part"])
        old = row["sections"]
        old_n = len(json.loads(old)) if isinstance(old, str) else len(old or [])
        if old_n != len(secs):
            changed += 1
        if apply:
            await conn.execute(
                "UPDATE regulations_docs SET sections=$1 WHERE id=$2",
                json.dumps(secs), id_)
    print(f"[sections] {len(ids)} docs scanned, {changed} section counts changed")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run
    print(f"MODE: {'APPLY' if apply else 'DRY-RUN'}  DB: {DB_URL}")
    conn = await asyncpg.connect(DB_URL)
    try:
        await fix_parts(conn, apply)
        await dedupe(conn, apply)
        await reparse_sections(conn, apply)
        n = await conn.fetchval("SELECT count(*) FROM regulations_docs")
        c = await conn.fetchval(
            "SELECT count(*) FROM rag_chunks WHERE corpus='regulation'")
        print(f"[final] regulations_docs={n} regulation_chunks={c}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
