#!/usr/bin/env python3
"""
CourtListener API Explorer
==========================
Run this before building the full scraper to understand
the data model and calibrate query strategy.

Usage:
    cd /Users/Dad/Documents/GitHub/Casebase
    source venv/bin/activate
    python scripts/scrape/explore_courtlistener.py

Requires: pip install requests python-dotenv
"""

import json, os, time
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

TOKEN = os.environ.get("COURTLISTENER_TOKEN", "177d15d21ae11462542b0029637d457c9cb229eb")
BASE  = "https://www.courtlistener.com/api/rest/v4"
HDR   = {
    "Authorization": f"Token {TOKEN}",
    "User-Agent": "Casebase/1.0 (immigration research tool; kellen@example.com)",
}

def get(path, params=None):
    url = path if path.startswith("http") else f"{BASE}/{path.lstrip('/')}/"
    r = requests.get(url, headers=HDR, params=params, timeout=30)
    r.raise_for_status()
    time.sleep(0.4)
    return r.json()

def search(params):
    r = requests.get(f"{BASE}/search/", headers=HDR, params=params, timeout=30)
    r.raise_for_status()
    time.sleep(0.4)
    return r.json()

def section(title):
    print(f"\n{'='*70}\n{title}\n{'='*70}")

# ── 1. Auth check ─────────────────────────────────────────────────────────────
section("1. AUTH CHECK")
r = requests.get(f"{BASE}/courts/?page_size=1", headers=HDR, timeout=10)
print(f"Status: {r.status_code}  ({'OK' if r.ok else r.text[:80]})")


# ── 2. Federal appellate courts ──────────────────────────────────────────────
section("2. FEDERAL APPELLATE COURTS")
data = get("courts", {"jurisdiction": "F", "page_size": 50})
print(f"Total federal appellate courts: {data['count']}")
for c in data["results"]:
    print(f"  {c['id']:10}  {c['full_name']}")

# ── 3. Immigration opinion volume per circuit ─────────────────────────────────
section("3. IMMIGRATION OPINION COUNTS BY CIRCUIT")
CIRCUITS = [
    ("scotus", "Supreme Court"),
    ("ca1",    "1st Circuit"),
    ("ca2",    "2nd Circuit"),
    ("ca3",    "3rd Circuit"),
    ("ca4",    "4th Circuit"),
    ("ca5",    "5th Circuit"),
    ("ca6",    "6th Circuit"),
    ("ca7",    "7th Circuit"),
    ("ca8",    "8th Circuit"),
    ("ca9",    "9th Circuit"),
    ("ca10",   "10th Circuit"),
    ("ca11",   "11th Circuit"),
    ("cadc",   "D.C. Circuit"),
]
for court_id, name in CIRCUITS:
    d = search({"type": "o", "q": "immigration",
                "court": court_id, "page_size": 1})
    print(f"  {court_id:8}  {name:22}  {d.get('count', '?'):>8,} hits")
    time.sleep(0.3)

# ── 4. Sample search: PERM / labor certification ──────────────────────────────
section("4. SAMPLE SEARCH: PERM labor certification (9th Cir, 2015+)")
d = search({
    "type": "o",
    "q": "PERM \"labor certification\" immigration",
    "court": "ca9",
    "filed_after": "2015-01-01",
    "order_by": "score desc",
    "page_size": 5,
})
print(f"Total: {d.get('count', 0):,}")
for op in d.get("results", []):
    print(f"\n  {op.get('caseName')}")
    print(f"    Filed: {op.get('dateFiled')}  |  Citations: {op.get('citation', [])}")
    print(f"    cluster_id={op.get('cluster_id')}  "
          f"URL: https://www.courtlistener.com{op.get('absolute_url','')}")


# ── 5. Inspect a single cluster + opinion object ─────────────────────────────
section("5. OPINION CLUSTER + TEXT FIELDS")
# Use a known immigration case: Kazarian v. USCIS (9th Cir. 2010)
# Search for it
d = search({"type": "o", "q": "Kazarian USCIS extraordinary ability",
            "court": "ca9", "page_size": 3})
if d.get("results"):
    sample = d["results"][0]
    cluster_id = sample["cluster_id"]
    print(f"Case: {sample.get('caseName')}  (cluster {cluster_id})")
    cluster = get(f"clusters/{cluster_id}")
    print(f"  date_filed:         {cluster.get('date_filed')}")
    print(f"  precedential_status:{cluster.get('precedential_status')}")
    print(f"  citations:          {cluster.get('citations')}")
    print(f"  syllabus length:    {len(cluster.get('syllabus') or ''):,}")
    opinion_urls = cluster.get("sub_opinions", [])
    print(f"  sub_opinions:       {len(opinion_urls)}")
    if opinion_urls:
        op_id = opinion_urls[0].rstrip("/").split("/")[-1]
        op = get(f"opinions/{op_id}")
        for field in ["type", "author_str", "joined_by_str"]:
            print(f"  {field:22}: {op.get(field)}")
        for tf in ["plain_text", "html_with_citations", "html", "xml_harvard"]:
            val = op.get(tf) or ""
            print(f"  {tf:22}: {len(val):,} chars")
        # Show first 500 chars of best text
        best = op.get("plain_text") or op.get("html_with_citations") or ""
        print(f"\n  --- First 500 chars of plain_text ---")
        print("  " + best[:500].replace("\n", "\n  "))

# ── 6. Opinions endpoint filters ─────────────────────────────────────────────
section("6. OPINIONS ENDPOINT FILTERS (published, ca9, 2020+)")
d = get("opinions", {
    "cluster__docket__court": "ca9",
    "cluster__date_filed__gte": "2020-01-01",
    "cluster__precedential_status": "Published",
    "page_size": 3,
    "fields": "id,cluster,type,plain_text,html_with_citations",
})
cnt = d.get('count', '?')
print(f"Total published ca9 opinions since 2020: {cnt}")
print("Pagination cursor key present:", "next" in d)
print("Sample records:")
for op in d.get("results", []):
    txt = op.get("plain_text") or op.get("html_with_citations") or ""
    print(f"  id={op['id']}  cluster={op.get('cluster','')}  "
          f"type={op.get('type')}  text={len(txt):,}c")


# ── 7. Rate limit headers ─────────────────────────────────────────────────────
section("7. RATE LIMIT HEADERS")
r = requests.get(f"{BASE}/opinions/?page_size=1", headers=HDR, timeout=10)
print("Relevant response headers:")
for k, v in sorted(r.headers.items()):
    if any(x in k.lower() for x in ["rate","limit","remain","throttle","retry","allow","burst"]):
        print(f"  {k}: {v}")
if not any(x in k.lower() for k in r.headers
           for x in ["rate","limit","remain","throttle"]):
    print("  (none found — throttle likely enforced silently via 429)")

# ── 8. Citation graph sanity check ───────────────────────────────────────────
section("8. CITATION GRAPH (opinions-cited endpoint)")
# How many times is Chevron cited in immigration opinions?
d = search({"type": "o", "q": "Chevron deference immigration", "page_size": 1})
print(f"'Chevron deference immigration' hits: {d.get('count',0):,}")
# Check opinions-cited endpoint
r2 = requests.get(f"{BASE}/opinions-cited/", headers=HDR,
                  params={"page_size": 1}, timeout=10)
if r2.ok:
    print(f"opinions-cited total records: {r2.json().get('count',0):,}")

# ── 9. Strategy summary ───────────────────────────────────────────────────────
section("9. RECOMMENDED SCRAPE STRATEGY (based on above)")
print("""
Based on the API exploration:

OPTION A — Search-based (keyword filter):
  Query: q="immigration" for each circuit court
  Pros:  Smaller, targeted result set (~focused on immigration)
  Cons:  May miss relevant cases that don't use the word "immigration"
         Hit counts subject to ±6% cardinality error at scale

OPTION B — Opinions endpoint (filter by court + date):
  Query: cluster__docket__court=ca9, cluster__precedential_status=Published
  Pros:  Complete, reproducible; no missed cases; cursor pagination is reliable
  Cons:  Larger volume — need to filter post-ingest or add more query filters

RECOMMENDED: Option B with court filter + published status only.
  - Keeps us to published (precedential) opinions only
  - Covers all 13 circuits + SCOTUS
  - Cursor-based pagination (no page-100 limit issue)
  - Text field: prefer plain_text, fall back to html_with_citations

ESTIMATED VOLUME (published immigration circuit opinions):
  See section 3 above for per-circuit counts.
  Total across all circuits likely 50,000–200,000 published opinions.
  Recommend starting with 2000-present to keep scope manageable.
""")

print("✅ Exploration complete.")
