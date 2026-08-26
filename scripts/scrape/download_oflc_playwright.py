#!/usr/bin/env python3
"""
OFLC disclosure-file downloader (Playwright).

Replaces the hardcoded-manifest approach in download_oflc_data.py, which broke
for two independent reasons:

  1. DOL migrated new releases from
       https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/<name>.xlsx
     to
       https://www.dol.gov/media/<name>.xlsx
     Old files still resolve at the legacy path; new ones do not.

  2. Akamai bot-management blocks this host's direct HTTP requests (curl, httpx,
     wget) regardless of headers. Only a real browser session gets through, so
     downloads run inside the page context via fetch() with the page's cookies.

Rather than hardcoding filenames, this scrapes the performance page for every
*_Disclosure_Data_*.xlsx link, so new quarters are picked up with no code change.

Usage:
    python download_oflc_playwright.py                 # download anything missing
    python download_oflc_playwright.py --check-only    # report new files only
    python download_oflc_playwright.py --program PERM  # restrict to one program
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

PERF_URL = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data" / "raw" / "oflc"
PROFILE_DIR = Path.home() / ".casebase" / "playwright-profile"
STATE_FILE = Path.home() / ".casebase" / "oflc_download_state.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

PROGRAMS = ("PERM", "PW", "LCA")


def fy_dir_for(filename: str) -> str:
    """Derive the FY subdirectory name used by ingest_oflc.fy_from_path()."""
    if "FY2018_EOY" in filename:
        return "FY2018"
    m = re.search(r"FY(\d{4})(_Q\d)?", filename)
    if m:
        return f"FY{m.group(1)}{m.group(2) or ''}"
    m = re.search(r"FY(\d{2})(_Q\d)?", filename)      # legacy FY15/FY16/FY17
    if m:
        return f"FY20{m.group(1)}{m.group(2) or ''}"
    return "UNKNOWN"


def program_of(filename: str):
    head = filename.split("_", 1)[0].upper()
    return head if head in PROGRAMS else None


def local_path_for(filename: str):
    prog = program_of(filename)
    if not prog:
        return None
    return DATA_DIR / prog / fy_dir_for(filename) / filename


def existing_files() -> set:
    return {p.name for p in DATA_DIR.rglob("*.xlsx")}


def scrape_links(page) -> list:
    """Every OFLC disclosure .xlsx link on the performance page."""
    page.goto(PERF_URL, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(3_000)
    return page.evaluate("""() => {
        const ls = [...document.querySelectorAll('a[href$=".xlsx"]')]
            .map(a => a.href.replace('dol.gov//', 'dol.gov/'))
            .filter(h => /(PERM|LCA|PW)_Disclosure/i.test(h));
        return [...new Set(ls)].sort();
    }""")


def download_one(page, url: str, dest: Path):
    """Fetch inside the page context so Akamai sees a genuine browser session."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    try:
        res = page.evaluate("""async (u) => {
            const r = await fetch(u, {credentials: 'include'});
            if (!r.ok) return {ok: false, status: r.status};
            const bytes = new Uint8Array(await r.arrayBuffer());
            let bin = '';
            const CH = 0x8000;
            for (let i = 0; i < bytes.length; i += CH) {
                bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
            }
            return {ok: true, b64: btoa(bin), size: bytes.length};
        }""", url)
    except Exception as e:
        return False, f"fetch error: {e}"

    if not res.get("ok"):
        return False, f"HTTP {res.get('status')}"

    tmp.write_bytes(base64.b64decode(res["b64"]))
    try:
        if zipfile.ZipFile(tmp).testzip() is not None:
            tmp.unlink(missing_ok=True)
            return False, "corrupt zip"
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return False, f"not a valid xlsx: {e}"

    tmp.replace(dest)
    return True, f"{dest.stat().st_size / 1048576:.1f}MB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true",
                    help="report new files without downloading")
    ap.add_argument("--program", choices=PROGRAMS, help="restrict to one program")
    args = ap.parse_args()

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    have = existing_files()
    new_files, failures = [], []

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/Chicago",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")

        try:
            links = scrape_links(page)
        except Exception as e:
            print(f"FATAL: could not load performance page: {e}", file=sys.stderr)
            ctx.close()
            return 2

        print(f"found {len(links)} disclosure links on DOL page")

        wanted = []
        for url in links:
            name = url.rsplit("/", 1)[-1]
            prog = program_of(name)
            if not prog or (args.program and prog != args.program):
                continue
            if name in have:
                continue
            wanted.append((url, name))

        if not wanted:
            print("up to date - no new files")

        for url, name in wanted:
            dest = local_path_for(name)
            if dest is None:
                continue
            if args.check_only:
                print(f"  NEW: {name}")
                new_files.append(name)
                continue
            ok, msg = download_one(page, url, dest)
            print(f"  {'OK  ' if ok else 'FAIL'} {name}  {msg}")
            (new_files if ok else failures).append(name)
            page.wait_for_timeout(2_500)

        ctx.close()

    STATE_FILE.write_text(json.dumps({
        "last_run": datetime.now().isoformat(timespec="seconds"),
        "new_files": new_files,
        "failures": failures,
    }, indent=1))

    if failures:
        print(f"{len(failures)} download(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
