#!/usr/bin/env python3
"""
check_visa_bulletin.py — scheduled watcher for the next month's Visa Bulletin.

Run every 4 hours by launchd (com.casebase.visabulletin). Each run:
  1. If today < the 12th                       -> exit 0 silently
  2. If next month's bulletin is already loaded -> exit 0 silently
  3. Otherwise fetch travel.state.gov through the real Chrome (the only path that
     clears Cloudflare from this machine; see journal 2026-08-22), look for the
     next-month link on the index page (fall back to the predictable URL), parse
     with scrape_visa_bulletins.parse_bulletin_tables, upsert into Homebrew, then
     mirror those rows to Docker.
Once next month's bulletin is in visa_bulletin, step 2 makes every later run that
month a no-op — no state file needed.

Requires (one-time): Chrome > View > Developer > Allow JavaScript from Apple Events.

Usage: venv/bin/python scripts/scrape/check_visa_bulletin.py [--force] [--dry-run] [--target YYYY-MM]
"""
import argparse, asyncio, logging, os, subprocess, sys, tempfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "scrape"))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")
import asyncpg
from scrape_visa_bulletins import (BASE_URL, INDEX_URL, MONTH_NUM, parse_bulletin_links,
                                   parse_bulletin_tables)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")
MONTH_NAME = {v: k for k, v in MONTH_NUM.items()}
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("vb")

APPLESCRIPT = '''
on run argv
  set theURL to item 1 of argv
  tell application "Google Chrome"
    set w to make new window with properties {mode:"normal"}
    set t to active tab of w
    set URL of t to theURL
    set waited to 0
    repeat until (loading of t is false) or waited > 60
      delay 1
      set waited to waited + 1
    end repeat
    delay 6
    set h to execute t javascript "document.documentElement.outerHTML"
    close w
  end tell
  return h
end run
'''


def chrome_fetch(url: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as f:
        f.write(APPLESCRIPT); script = f.name
    try:
        r = subprocess.run(["osascript", script, url], capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(script)
    if r.returncode != 0:
        raise RuntimeError(f"osascript failed: {r.stderr.strip()[:300]}")
    html = r.stdout
    if "Just a moment" in html[:3000] or len(html) < 5000:
        raise RuntimeError("Chrome returned a Cloudflare challenge page / empty document")
    return html


def next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


async def already_loaded(conn, target: date) -> bool:
    n = await conn.fetchval("SELECT count(*) FROM visa_bulletin WHERE bulletin_date=$1", target)
    return n >= 100


def mirror_to_docker(target: date):
    """Copy the target month's rows Homebrew -> Docker (idempotent upsert)."""
    tsv = f"/tmp/vb_{target:%Y%m}.tsv"
    cols = ("bulletin_date,bulletin_title,source_url,category_type,date_type,preference,"
            "chargeability,priority_date,is_current,is_unavailable,raw_value")
    subprocess.run(["psql", DB_URL, "-c",
                    f"\\copy (SELECT {cols} FROM visa_bulletin WHERE bulletin_date='{target}') TO '{tsv}'"],
                   check=True, capture_output=True)
    subprocess.run(["docker", "cp", tsv, f"casebase-db:{tsv}"], check=True, capture_output=True)
    sql = f"""
    CREATE TEMP TABLE vb_stage (LIKE visa_bulletin INCLUDING DEFAULTS);
    \\copy vb_stage ({cols}) FROM '{tsv}'
    INSERT INTO visa_bulletin ({cols}) SELECT {cols} FROM vb_stage
      ON CONFLICT (bulletin_date, category_type, date_type, preference, chargeability)
      DO UPDATE SET priority_date=EXCLUDED.priority_date, is_current=EXCLUDED.is_current,
                    is_unavailable=EXCLUDED.is_unavailable, raw_value=EXCLUDED.raw_value;
    SELECT count(*) FROM visa_bulletin WHERE bulletin_date='{target}';
    """
    r = subprocess.run(["docker", "exec", "-i", "casebase-db", "psql", "-U", "perm", "-d",
                        "perm_decisions"], input=sql, capture_output=True, text=True, check=True)
    log.info(f"Docker now has {r.stdout.strip().splitlines()[-3].strip()} rows for {target:%B %Y}")
    os.unlink(tsv)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="ignore the day-of-month gate")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--target", help="YYYY-MM to fetch instead of next month")
    a = ap.parse_args()

    today = date.today()
    if a.target:
        y, m = a.target.split("-"); target = date(int(y), int(m), 1)
    else:
        target = next_month(today)
    if today.day < 12 and not a.force and not a.target:
        return  # silent: not in the watch window yet

    conn = await asyncpg.connect(DB_URL)
    try:
        if await already_loaded(conn, target) and not a.force:
            return  # silent: already have it
        log.info(f"Watching for {target:%B %Y} bulletin")

        html_index = chrome_fetch(INDEX_URL)
        links = [b for b in parse_bulletin_links(html_index) if b["bulletin_date"] == target]
        if links:
            url, title = links[0]["url"], links[0]["title"]
        else:
            # Index is often updated after the bulletin page itself goes live.
            url = (f"{BASE_URL}/content/travel/en/legal/visa-law0/visa-bulletin/"
                   f"{target.year}/visa-bulletin-for-{MONTH_NAME[target.month]}-{target.year}.html")
            title = f"Visa Bulletin For {MONTH_NAME[target.month].title()} {target.year}"
            log.info(f"Not on index yet; trying direct URL {url}")
        try:
            html = chrome_fetch(url)
        except RuntimeError as e:
            log.info(f"Not published yet ({e}); will retry next run")
            return
        rows = parse_bulletin_tables(html, target, title, url)
        if len(rows) < 100:
            log.warning(f"Parsed only {len(rows)} rows — page may be a 404/placeholder; retry next run")
            return
        log.info(f"Parsed {len(rows)} rows from {url}")
        if a.dry_run:
            for r in rows[:5]:
                log.info(f"  {r['category_type']} {r['date_type']} {r['preference']} "
                         f"{r['chargeability']} {r['raw_value']}")
            return
        await conn.executemany("""
            INSERT INTO visa_bulletin (bulletin_date, bulletin_title, source_url, category_type,
                date_type, preference, chargeability, priority_date, is_current, is_unavailable, raw_value)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (bulletin_date, category_type, date_type, preference, chargeability)
            DO UPDATE SET priority_date=EXCLUDED.priority_date, is_current=EXCLUDED.is_current,
                          is_unavailable=EXCLUDED.is_unavailable, raw_value=EXCLUDED.raw_value
        """, [(r["bulletin_date"], r["bulletin_title"], r["source_url"], r["category_type"],
               r["date_type"], r["preference"], r["chargeability"], r["priority_date"],
               r["is_current"], r["is_unavailable"], r["raw_value"]) for r in rows])
        log.info(f"Loaded {target:%B %Y} into Homebrew")
        mirror_to_docker(target)
        log.info("DONE — watcher will stay quiet until the 12th of next month")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
