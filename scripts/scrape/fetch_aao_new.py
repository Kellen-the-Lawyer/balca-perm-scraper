#!/usr/bin/env python3
"""
fetch_aao_new.py — discover and download NEW AAO non-precedent decisions.

Walks https://www.uscis.gov/administrative-appeals/aao-decisions/aao-non-precedent-decisions
(newest first, 100/page), downloads any PDF whose filename is not yet in
~/aao_decisions/aao_index.csv, saves it under ~/aao_decisions/<regulation>/, and
appends the row to aao_index.csv in the exact column layout ingest_aao.py reads
(pdf_filename,pdf_url,title,date,form,regulation,pdf_path).

Stops after `--stop-after` consecutive listing pages containing nothing new
(default 2 — the listing is date-sorted but late postings can land behind newer
ones). Then run: ingest_aao.py --new-only.

Usage:
    venv/bin/python scripts/scrape/fetch_aao_new.py [--dry-run] [--max-pages N] [--stop-after N]
Backfill of a large gap: --max-pages 400 --stop-after 400  (~400 * 11s listing + PDFs)
"""
import argparse, csv, os, random, re, shutil, sys, time
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx
from bs4 import BeautifulSoup

AAO_BASE = Path("/Users/Dad/aao_decisions")
INDEX_CSV = AAO_BASE / "aao_index.csv"
COLS = ["pdf_filename", "pdf_url", "title", "date", "form", "regulation", "pdf_path"]
LISTING = "https://www.uscis.gov/administrative-appeals/aao-decisions/aao-non-precedent-decisions"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
LISTING_DELAY = 10.0   # robots.txt Crawl-delay
PDF_DELAY = 2.0


def known_filenames():
    if not INDEX_CSV.exists():
        return set()
    with open(INDEX_CSV, newline="", encoding="utf-8") as f:
        return {r["pdf_filename"].strip() for r in csv.DictReader(f)}


def parse_listing(html):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for div in soup.select("div.views-row"):
        a = div.select_one("div.views-item-title a[href]")
        if not a or not a["href"].lower().endswith(".pdf"):
            continue
        href = a["href"]
        for span in a.select("span.extra-info"):
            span.decompose()
        title = a.get_text(" ", strip=True)
        date_div = div.select_one("div.views-field-field-display-date .field-content")
        date_str = date_div.get_text(strip=True) if date_div else ""
        meta = ""
        for fc in div.select("div.views-field .field-content"):
            t = fc.get_text(" ", strip=True)
            if t and t != title and t != date_str and "," in t:
                meta = t
        form, regulation = "", ""
        if meta:
            form, _, regulation = meta.partition(",")
            form = form.strip()
            regulation = regulation.strip().strip('"').replace("&quot;", "").strip()
        rows.append({
            "pdf_filename": unquote(href.rsplit("/", 1)[-1]),
            "pdf_url": urljoin("https://www.uscis.gov", href),
            "title": title, "date": date_str, "form": form,
            "regulation": regulation, "pdf_path": href,
        })
    return rows


def safe_folder(regulation):
    return re.sub(r"[/\\:]", " ", regulation).strip() or "Uncategorized"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--stop-after", type=int, default=2,
                    help="stop after N consecutive pages with nothing new")
    a = ap.parse_args()

    known = known_filenames()
    print(f"index has {len(known)} filenames")
    new_rows, quiet_pages = [], 0
    with httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True) as c:
        for page in range(a.max_pages):
            r = c.get(LISTING, params={"uri_1": "All", "m": "All", "y": "All",
                                       "items_per_page": 100, "page": page})
            r.raise_for_status()
            rows = parse_listing(r.text)
            fresh = [x for x in rows if x["pdf_filename"] not in known]
            print(f"page {page}: {len(rows)} rows, {len(fresh)} new")
            if not rows:
                break
            new_rows.extend(fresh)
            for x in fresh:
                known.add(x["pdf_filename"])
            quiet_pages = quiet_pages + 1 if not fresh else 0
            if quiet_pages >= a.stop_after:
                break
            time.sleep(LISTING_DELAY + random.uniform(0, 2))

        if a.dry_run:
            for x in new_rows[:25]:
                print(f"  {x['date']:<18} {x['form']:<6} {x['pdf_filename']}  [{x['regulation']}]")
            print(f"dry-run: {len(new_rows)} new decisions would be downloaded")
            return

        ok, fail = 0, 0
        for x in new_rows:
            folder = AAO_BASE / safe_folder(x["regulation"])
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / x["pdf_filename"]
            tmp = dest.with_suffix(".part")
            try:
                with c.stream("GET", x["pdf_url"]) as resp:
                    resp.raise_for_status()
                    with open(tmp, "wb") as fh:
                        for chunk in resp.iter_bytes():
                            fh.write(chunk)
                with open(tmp, "rb") as fh:
                    if fh.read(5) != b"%PDF-":
                        raise ValueError("not a PDF")
                tmp.rename(dest)
                with open(INDEX_CSV, "a", newline="", encoding="utf-8") as f:
                    csv.DictWriter(f, fieldnames=COLS).writerow({k: x[k] for k in COLS})
                ok += 1
                print(f"  saved {dest.relative_to(AAO_BASE)}")
            except Exception as e:  # noqa: BLE001
                tmp.unlink(missing_ok=True); fail += 1
                print(f"  FAIL {x['pdf_filename']}: {e}")
            time.sleep(PDF_DELAY + random.uniform(0, 1))
    print(f"Done. new={len(new_rows)} saved={ok} failed={fail}")
    sys.exit(1 if fail and not ok else 0)


if __name__ == "__main__":
    main()
