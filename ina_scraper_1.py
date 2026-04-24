#!/usr/bin/env python3
"""
INA Scraper — Immigration and Nationality Act
Source: https://www.law.cornell.edu/uscode/text/8/chapter-12

Scrapes the full INA (8 U.S.C. Chapter 12) from LII/Cornell, walking the
hierarchy:  Chapter → Subchapters → (Parts →) Sections → full statutory text.

Subchapters I, IV, V list sections directly.
Subchapters II and III have an intermediate Part level — handled automatically.

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
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    time.sleep(DELAY)
    return BeautifulSoup(resp.text, "html.parser")


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_links(soup: BeautifulSoup, pattern: str) -> list[tuple[str, str]]:
    """Return (href, link_text) for all <a> tags whose href matches pattern."""
    content = soup.find("div", id="content") or soup.find("main") or soup
    results = []
    for li in content.find_all("li"):
        a = li.find("a", href=re.compile(pattern))
        if a:
            href = a["href"]
            if href.startswith("/"):
                href = BASE_URL + href
            results.append((href, _clean(a.get_text())))
    return results


def get_section_links(index_url: str) -> list[dict]:
    """
    Fetch an index page (subchapter or part) and return section dicts.
    If the page lists Parts instead of sections, recurse into each Part.
    """
    soup = fetch(index_url)

    # Check for Part links (subchapter-II style)
    part_links = _extract_links(soup, r"/uscode/text/8/chapter-12/subchapter-[^/]+/part-")
    if part_links:
        sections = []
        for part_url, part_title in part_links:
            print(f"    → Part: {part_title}")
            sections.extend(get_section_links(part_url))
        return sections

    # Otherwise collect direct section links
    raw = _extract_links(soup, r"/uscode/text/8/\d")
    sections = []
    for href, link_text in raw:
        section_num = href.rstrip("/").split("/")[-1]
        title = re.sub(r"^§\s*[\w.]+\.\s*", "", link_text)
        sections.append({
            "section": section_num,
            "title":   title,
            "url":     href,
        })
    return sections


def parse_section(url: str) -> dict:
    soup = fetch(url)

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
    results = []
    total = len(section_entries)
    for i, entry in enumerate(section_entries, 1):
        sec_id = entry["section"]
        if sec_id in already_fetched:
            if verbose:
                print(f"  [{i}/{total}] § {sec_id} — skipped (resume)")
            results.append(entry)
            continue
        if verbose:
            print(f"  [{i}/{total}] § {sec_id} — {entry['title']}")
        try:
            data = parse_section(entry["url"])
        except Exception as exc:
            print(f"    ⚠  Error: {exc}", file=sys.stderr)
            data = {"text": "", "notes": "", "source_url": entry["url"]}
        results.append({**entry, **data})
    return results


def scrape_subchapter(roman: str, already_fetched: set[str], verbose: bool = True) -> dict:
    title, url = SUBCHAPTERS[roman]
    if verbose:
        print(f"\n── Subchapter {roman}: {title}")
    section_entries = get_section_links(url)
    if verbose:
        print(f"   {len(section_entries)} sections found")
    sections = scrape_section_list(section_entries, already_fetched, verbose=verbose)
    return {"subchapter": roman, "title": title, "url": url, "sections": sections}


def scrape_ina(
    subchapters: list[str] | None = None,
    single_section: str | None = None,
    resume_from: Path | None = None,
    verbose: bool = True,
) -> dict:
    if single_section:
        url = f"{BASE_URL}/uscode/text/8/{single_section}"
        if verbose:
            print(f"Scraping single section § {single_section}")
        data = parse_section(url)
        return {"mode": "single_section", "section": single_section, "url": url, **data}

    already_fetched: set[str] = set()
    prior_data: dict = {}
    if resume_from and resume_from.exists():
        prior_data = json.loads(resume_from.read_text(encoding="utf-8"))
        for sub in prior_data.get("subchapters", []):
            for sec in sub.get("sections", []):
                if sec.get("text"):
                    already_fetched.add(sec["section"])
        if verbose:
            print(f"Resuming — {len(already_fetched)} sections already cached")

    targets = subchapters or list(SUBCHAPTERS.keys())
    result: dict = {
        "title":       "Immigration and Nationality Act",
        "usc":         "8 U.S.C. Chapter 12",
        "source":      CHAPTER_URL,
        "subchapters": [],
    }

    if prior_data:
        prior_subs = {s["subchapter"]: s for s in prior_data.get("subchapters", [])}
        for roman, sub_data in prior_subs.items():
            if roman not in targets:
                result["subchapters"].append(sub_data)

    for roman in targets:
        if roman not in SUBCHAPTERS:
            print(f"Unknown subchapter '{roman}' — valid: {list(SUBCHAPTERS)}", file=sys.stderr)
            continue
        result["subchapters"].append(scrape_subchapter(roman, already_fetched, verbose=verbose))

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


def print_stats(data: dict) -> None:
    if data.get("mode") == "single_section":
        print(f"\nSection § {data['section']}: {len(data.get('text','').split()):,} words")
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
    p = argparse.ArgumentParser(description="Scrape the INA from law.cornell.edu")
    p.add_argument("--subchapter", nargs="+", metavar="ROMAN")
    p.add_argument("--section",    metavar="NUM")
    p.add_argument("--output",     metavar="DIR", default=".")
    p.add_argument("--resume",     action="store_true")
    p.add_argument("--json-only",  action="store_true")
    p.add_argument("--quiet",      action="store_true")
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
