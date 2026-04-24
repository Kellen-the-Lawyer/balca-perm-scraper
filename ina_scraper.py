#!/usr/bin/env python3
"""
INA Scraper — Immigration and Nationality Act
Source: https://www.law.cornell.edu/uscode/text/8/chapter-12

Scrapes the full INA (8 U.S.C. Chapter 12) from LII/Cornell, walking the
hierarchy:  Chapter → Subchapters → Sections → full statutory text.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SETUP (run once):
    pip install requests beautifulsoup4
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

USAGE:
    python ina_scraper.py                       # scrape everything (~200 sections)
    python ina_scraper.py --subchapter I        # only Subchapter I
    python ina_scraper.py --subchapter I II     # multiple subchapters
    python ina_scraper.py --section 1101        # single section
    python ina_scraper.py --output ./ina_data/  # custom output directory
    python ina_scraper.py --resume              # skip already-fetched sections
    python ina_scraper.py --json-only           # skip .txt output

OUTPUT:
    ina_full.json   — structured (subchapter → sections → text + notes + URL)
    ina_full.txt    — flat readable text, easy to grep
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL    = "https://www.law.cornell.edu"
CHAPTER_URL = f"{BASE_URL}/uscode/text/8/chapter-12"

SUBCHAPTERS = {
    "I":   ("GENERAL PROVISIONS",                f"{BASE_URL}/uscode/text/8/chapter-12/subchapter-I"),
    "II":  ("IMMIGRATION",                        f"{BASE_URL}/uscode/text/8/chapter-12/subchapter-II"),
    "III": ("NATIONALITY AND NATURALIZATION",     f"{BASE_URL}/uscode/text/8/chapter-12/subchapter-III"),
    "IV":  ("REFUGEE ASSISTANCE",                 f"{BASE_URL}/uscode/text/8/chapter-12/subchapter-IV"),
    "V":   ("ALIEN TERRORIST REMOVAL PROCEDURES", f"{BASE_URL}/uscode/text/8/chapter-12/subchapter-V"),
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "Referer":         CHAPTER_URL,
}

DELAY = 1.5   # seconds between requests — polite to LII's servers

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def fetch(url: str) -> BeautifulSoup:
    """GET a URL and return a BeautifulSoup object. Raises on HTTP error."""
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    time.sleep(DELAY)
    return BeautifulSoup(resp.text, "html.parser")


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    """Collapse whitespace and strip."""
    return re.sub(r"\s+", " ", text).strip()


def parse_subchapter_index(subchapter_roman: str) -> list[dict]:
    """
    Fetch a subchapter index page and return a list of
    {'section': '1101', 'title': 'Definitions', 'url': '...'} dicts.
    """
    url = SUBCHAPTERS[subchapter_roman][1]
    soup = fetch(url)

    sections = []
    content = soup.find("div", id="content") or soup.find("main") or soup
    for li in content.find_all("li"):
        a = li.find("a", href=re.compile(r"/uscode/text/8/\d"))
        if not a:
            continue
        href = a["href"]
        section_num = href.rstrip("/").split("/")[-1]
        title = _clean(a.get_text())
        title = re.sub(r"^§\s*[\w.]+\.\s*", "", title)  # strip leading § NNNN.
        sections.append({
            "section": section_num,
            "title":   title,
            "url":     BASE_URL + href if href.startswith("/") else href,
        })
    return sections


def parse_section(url: str) -> dict:
    """
    Fetch a section page and return
    {'text': '...', 'notes': '...', 'source_url': url}.
    """
    soup = fetch(url)

    # Strip navigation chrome
    for tag in soup.find_all(["nav", "footer", "header"]):
        tag.decompose()
    for tag in soup.find_all(class_=re.compile(r"toolbox|sidebar|breadcrumb|tabs")):
        tag.decompose()

    content_div = (
        soup.find("div", id="content")
        or soup.find("div", class_=re.compile(r"field-item"))
        or soup.find("main")
        or soup
    )

    paragraphs = []
    for elem in content_div.descendants:
        if elem.name in ("p", "li", "h2", "h3", "h4"):
            t = _clean(elem.get_text(" ", strip=True))
            if t and len(t) > 2:
                paragraphs.append(t)

    # Deduplicate adjacent identical lines (nested tags can repeat text)
    seen: list[str] = []
    for p in paragraphs:
        if not seen or p != seen[-1]:
            seen.append(p)

    notes_div = soup.find("div", id=re.compile(r"notes|tab_default_2"))
    notes_text = _clean(notes_div.get_text(" ", strip=True)) if notes_div else ""

    return {
        "text":       "\n\n".join(seen),
        "notes":      notes_text,
        "source_url": url,
    }


# ── Main scraping logic ───────────────────────────────────────────────────────

def scrape_section_list(
    section_entries: list[dict],
    already_fetched: set[str],
    verbose: bool = True,
) -> list[dict]:
    """Fetch each section. Skips sections whose IDs are in already_fetched."""
    results = []
    total = len(section_entries)
    for i, entry in enumerate(section_entries, 1):
        sec_id = entry["section"]
        if sec_id in already_fetched:
            if verbose:
                print(f"  [{i}/{total}] § {sec_id} — skipped (already fetched)")
            results.append(entry)
            continue
        if verbose:
            print(f"  [{i}/{total}] § {sec_id} — {entry['title']}")
        try:
            data = parse_section(entry["url"])
        except Exception as exc:
            print(f"    ⚠  Error fetching {entry['url']}: {exc}", file=sys.stderr)
            data = {"text": "", "notes": "", "source_url": entry["url"]}
        results.append({**entry, **data})
    return results


def scrape_subchapter(
    roman: str,
    already_fetched: set[str],
    verbose: bool = True,
) -> dict:
    title, url = SUBCHAPTERS[roman]
    if verbose:
        print(f"\n── Subchapter {roman}: {title}")
    section_entries = parse_subchapter_index(roman)
    if verbose:
        print(f"   {len(section_entries)} sections found")
    sections = scrape_section_list(section_entries, already_fetched, verbose=verbose)
    return {
        "subchapter": roman,
        "title":      title,
        "url":        url,
        "sections":   sections,
    }


def scrape_ina(
    subchapters: list[str] | None = None,
    single_section: str | None = None,
    resume_from: Path | None = None,
    verbose: bool = True,
) -> dict:
    """Top-level scrape."""
    if single_section:
        url = f"{BASE_URL}/uscode/text/8/{single_section}"
        if verbose:
            print(f"Scraping single section § {single_section}")
        data = parse_section(url)
        return {"mode": "single_section", "section": single_section, "url": url, **data}

    # Load prior run for --resume
    already_fetched: set[str] = set()
    prior_data: dict = {}
    if resume_from and resume_from.exists():
        prior_data = json.loads(resume_from.read_text(encoding="utf-8"))
        for sub in prior_data.get("subchapters", []):
            for sec in sub.get("sections", []):
                if sec.get("text"):
                    already_fetched.add(sec["section"])
        if verbose:
            print(f"Resuming — {len(already_fetched)} sections already in cache")

    targets = subchapters or list(SUBCHAPTERS.keys())
    result: dict = {
        "title":       "Immigration and Nationality Act",
        "usc":         "8 U.S.C. Chapter 12",
        "source":      CHAPTER_URL,
        "subchapters": [],
    }

    # Preserve prior subchapters not being re-scraped
    if prior_data:
        prior_subs = {s["subchapter"]: s for s in prior_data.get("subchapters", [])}
        for roman, sub_data in prior_subs.items():
            if roman not in targets:
                result["subchapters"].append(sub_data)

    for roman in targets:
        if roman not in SUBCHAPTERS:
            print(f"Unknown subchapter '{roman}' — valid: {list(SUBCHAPTERS)}", file=sys.stderr)
            continue
        result["subchapters"].append(
            scrape_subchapter(roman, already_fetched, verbose=verbose)
        )

    # Sort subchapters by canonical order
    order = list(SUBCHAPTERS.keys())
    result["subchapters"].sort(
        key=lambda s: order.index(s["subchapter"]) if s["subchapter"] in order else 99
    )
    return result


# ── Output writers ────────────────────────────────────────────────────────────

def write_json(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ JSON → {path}")


def write_text(data: dict, path: Path) -> None:
    lines = []
    if data.get("mode") == "single_section":
        lines.append(f"§ {data['section']}\n{'=' * 60}")
        lines.append(data["text"])
        if data.get("notes"):
            lines.append(f"\nNotes:\n{data['notes']}")
    else:
        lines.append(f"{data['title']}  |  {data['usc']}")
        lines.append("=" * 70)
        for sub in data.get("subchapters", []):
            lines.append(f"\n\nSUBCHAPTER {sub['subchapter']} — {sub['title']}")
            lines.append("-" * 70)
            for sec in sub["sections"]:
                lines.append(f"\n§ {sec['section']}. {sec['title']}")
                lines.append(sec.get("text", ""))
                if sec.get("notes"):
                    lines.append(f"\n  [Historical Notes]\n  {sec['notes'][:600]}...")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ Text → {path}")


# ── Stats ─────────────────────────────────────────────────────────────────────

def print_stats(data: dict) -> None:
    if data.get("mode") == "single_section":
        words = len(data.get("text", "").split())
        print(f"\nSection § {data['section']}: {words:,} words")
        return
    total_sections = sum(len(s["sections"]) for s in data.get("subchapters", []))
    total_words    = sum(
        len(sec.get("text", "").split())
        for sub in data.get("subchapters", [])
        for sec in sub["sections"]
    )
    print(f"\n{'─'*40}")
    print(f"Subchapters : {len(data['subchapters'])}")
    print(f"Sections    : {total_sections}")
    print(f"Words       : {total_words:,}")
    print(f"{'─'*40}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scrape the INA (8 U.S.C. Chapter 12) from law.cornell.edu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--subchapter", nargs="+", metavar="ROMAN",
                   help="Subchapter(s) to scrape, e.g. --subchapter I II")
    p.add_argument("--section",    metavar="NUM",
                   help="Single section number, e.g. --section 1101")
    p.add_argument("--output",     metavar="DIR", default=".",
                   help="Output directory (default: current directory)")
    p.add_argument("--resume",     action="store_true",
                   help="Skip sections already present in a prior ina_full.json")
    p.add_argument("--json-only",  action="store_true",
                   help="Skip writing the .txt file")
    p.add_argument("--quiet",      action="store_true",
                   help="Suppress progress output")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem        = f"ina_section_{args.section}" if args.section else "ina_full"
    json_path   = out_dir / f"{stem}.json"
    resume_path = json_path if args.resume else None

    data = scrape_ina(
        subchapters=args.subchapter,
        single_section=args.section,
        resume_from=resume_path,
        verbose=not args.quiet,
    )

    write_json(data, json_path)
    if not args.json_only:
        write_text(data, out_dir / f"{stem}.txt")

    print_stats(data)


if __name__ == "__main__":
    main()
