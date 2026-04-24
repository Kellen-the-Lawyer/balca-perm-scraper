#!/usr/bin/env python3
"""
DOL OFLC Performance Data Downloader
Downloads PERM, LCA, and PW Disclosure Data (FY2020–FY2026)
from https://www.dol.gov/agencies/eta/foreign-labor/performance

Run from the perm-research directory:
    python3 download_oflc_data.py
    python3 download_oflc_data.py --dry-run
"""

import os
import sys
import time
import httpx
from pathlib import Path
from urllib.parse import urlparse

# ── Output directory (relative to this script) ───────────────────────────────
BASE_DIR = Path(__file__).parent / "oflc_data"

BASE = "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs"

# ── File manifest ─────────────────────────────────────────────────────────────
# (program, fiscal_year, label, url)
FILES = [
    # ── PERM Disclosure Data / PERM_FY (FY2020–FY2026 Q1) ────────────────────
    ("PERM", "FY2026_Q1", "PERM_Disclosure_Data_FY2026_Q1",
     f"{BASE}/PERM_Disclosure_Data_FY2026_Q1.xlsx"),
    ("PERM", "FY2025", "PERM_Disclosure_Data_FY2025",
     f"{BASE}/PERM_Disclosure_Data_FY2025_Q4.xlsx"),
    ("PERM", "FY2024", "PERM_Disclosure_Data_FY2024",
     f"{BASE}/PERM_Disclosure_Data_FY2024_Q4.xlsx"),
    ("PERM", "FY2024", "PERM_Disclosure_Data_New_Form_FY2024",
     f"{BASE}/PERM_Disclosure_Data_New_Form_FY2024_Q4.xlsx"),
    ("PERM", "FY2023", "PERM_FY2023",
     f"{BASE}/PERM_Disclosure_Data_FY2023_Q4.xlsx"),
    ("PERM", "FY2022", "PERM_FY2022",
     f"{BASE}/PERM_Disclosure_Data_FY2022_Q4.xlsx"),
    ("PERM", "FY2021", "PERM_FY2021",
     f"{BASE}/PERM_Disclosure_Data_FY2021.xlsx"),
    ("PERM", "FY2020", "PERM_FY2020",
     f"{BASE}/PERM_Disclosure_Data_FY2020.xlsx"),

    # ── LCA Disclosure Data (FY2020–FY2025, all quarters) ────────────────────
    ("LCA", "FY2025_Q1", "LCA_Disclosure_Data_FY2025_Q1",
     f"{BASE}/LCA_Disclosure_Data_FY2025_Q1.xlsx"),
    ("LCA", "FY2025_Q2", "LCA_Disclosure_Data_FY2025_Q2",
     f"{BASE}/LCA_Disclosure_Data_FY2025_Q2.xlsx"),
    ("LCA", "FY2025_Q3", "LCA_Disclosure_Data_FY2025_Q3",
     f"{BASE}/LCA_Disclosure_Data_FY2025_Q3.xlsx"),
    ("LCA", "FY2025_Q4", "LCA_Disclosure_Data_FY2025_Q4",
     f"{BASE}/LCA_Disclosure_Data_FY2025_Q4.xlsx"),
    ("LCA", "FY2024_Q1", "LCA_Disclosure_Data_FY2024_Q1",
     f"{BASE}/LCA_Disclosure_Data_FY2024_Q1.xlsx"),
    ("LCA", "FY2024_Q2", "LCA_Disclosure_Data_FY2024_Q2",
     f"{BASE}/LCA_Disclosure_Data_FY2024_Q2.xlsx"),
    ("LCA", "FY2024_Q3", "LCA_Disclosure_Data_FY2024_Q3",
     f"{BASE}/LCA_Disclosure_Data_FY2024_Q3.xlsx"),
    ("LCA", "FY2024_Q4", "LCA_Disclosure_Data_FY2024_Q4",
     f"{BASE}/LCA_Disclosure_Data_FY2024_Q4.xlsx"),
    ("LCA", "FY2023_Q1", "LCA_Disclosure_Data_FY2023_Q1",
     f"{BASE}/LCA_Disclosure_Data_FY2023_Q1.xlsx"),
    ("LCA", "FY2023_Q2", "LCA_Disclosure_Data_FY2023_Q2",
     f"{BASE}/LCA_Disclosure_Data_FY2023_Q2.xlsx"),
    ("LCA", "FY2023_Q3", "LCA_Disclosure_Data_FY2023_Q3",
     f"{BASE}/LCA_Disclosure_Data_FY2023_Q3.xlsx"),
    ("LCA", "FY2023_Q4", "LCA_Disclosure_Data_FY2023_Q4",
     f"{BASE}/LCA_Disclosure_Data_FY2023_Q4.xlsx"),
    ("LCA", "FY2022_Q1", "LCA_Disclosure_Data_FY2022_Q1",
     f"{BASE}/LCA_Disclosure_Data_FY2022_Q1.xlsx"),
    ("LCA", "FY2022_Q2", "LCA_Disclosure_Data_FY2022_Q2",
     f"{BASE}/LCA_Disclosure_Data_FY2022_Q2.xlsx"),
    ("LCA", "FY2022_Q3", "LCA_Disclosure_Data_FY2022_Q3",
     f"{BASE}/LCA_Disclosure_Data_FY2022_Q3.xlsx"),
    ("LCA", "FY2022_Q4", "LCA_Disclosure_Data_FY2022_Q4",
     f"{BASE}/LCA_Disclosure_Data_FY2022_Q4.xlsx"),
    ("LCA", "FY2021_Q1", "LCA_Disclosure_Data_FY2021_Q1",
     f"{BASE}/LCA_Disclosure_Data_FY2021_Q1.xlsx"),
    ("LCA", "FY2021_Q2", "LCA_Disclosure_Data_FY2021_Q2",
     f"{BASE}/LCA_Disclosure_Data_FY2021_Q2.xlsx"),
    ("LCA", "FY2021_Q3", "LCA_Disclosure_Data_FY2021_Q3",
     f"{BASE}/LCA_Disclosure_Data_FY2021_Q3.xlsx"),
    ("LCA", "FY2021_Q4", "LCA_Disclosure_Data_FY2021_Q4",
     f"{BASE}/LCA_Disclosure_Data_FY2021_Q4.xlsx"),
    ("LCA", "FY2020_Q1", "LCA_Disclosure_Data_FY2020_Q1",
     f"{BASE}/LCA_Disclosure_Data_FY2020_Q1.xlsx"),
    ("LCA", "FY2020_Q2", "LCA_Disclosure_Data_FY2020_Q2",
     f"{BASE}/LCA_Disclosure_Data_FY2020_Q2.xlsx"),
    ("LCA", "FY2020_Q3", "LCA_Disclosure_Data_FY2020_Q3",
     f"{BASE}/LCA_Disclosure_Data_FY2020_Q3.xlsx"),
    ("LCA", "FY2020_Q4", "LCA_Disclosure_Data_FY2020_Q4",
     f"{BASE}/LCA_Disclosure_Data_FY2020_Q4.xlsx"),

    # ── PW Disclosure Data (FY2020–FY2025) ───────────────────────────────────
    ("PW", "FY2025", "PW_Disclosure_Data_FY2025",
     f"{BASE}/PW_Disclosure_Data_FY2025_Q4.xlsx"),
    ("PW", "FY2024", "PW_Disclosure_Data_FY2024",
     f"{BASE}/PW_Disclosure_Data_FY2024_Q4.xlsx"),
    ("PW", "FY2023", "PW_Disclosure_Data_FY2023_old_form",
     f"{BASE}/PW_Disclosure_Data_FY2023_Q4_old_form.xlsx"),
    ("PW", "FY2023", "PW_Disclosure_Data_FY2023_revised_form",
     f"{BASE}/PW_Disclosure_Data_FY2023_Q4_revised_form.xlsx"),
    ("PW", "FY2022", "PW_Disclosure_Data_FY2022_old_form",
     f"{BASE}/PW_Disclosure_Data_FY2022_Q4_old_form.xlsx"),
    ("PW", "FY2022", "PW_Disclosure_Data_FY2022_revised_form",
     f"{BASE}/PW_Disclosure_Data_FY2022_Q4_revised_form.xlsx"),
    ("PW", "FY2021", "PW_Disclosure_Data_FY2021_old_form",
     f"{BASE}/PW_Disclosure_Data_FY2021_old_form.xlsx"),
    ("PW", "FY2021", "PW_Disclosure_Data_FY2021_revised_form",
     f"{BASE}/PW_Disclosure_Data_FY2021_revised_form.xlsx"),
    ("PW", "FY2020", "PW_Disclosure_Data_FY2020",
     f"{BASE}/PW_Disclosure_Data_FY2020.xlsx"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
    "Referer": "https://www.dol.gov/agencies/eta/foreign-labor/performance",
}

RETRY_LIMIT = 3
RETRY_DELAY = 5
INTER_FILE_DELAY = 1


def download_file(client: httpx.Client, url: str, dest: Path, label: str) -> bool:
    if dest.exists():
        print(f"  [SKIP]  {label}  ({dest.name} already exists)")
        return True
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            print(f"  [GET ]  {label}  (attempt {attempt})")
            with client.stream("GET", url, timeout=120) as r:
                if r.status_code == 200:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with open(dest, "wb") as fh:
                        for chunk in r.iter_bytes(chunk_size=256 * 1024):
                            fh.write(chunk)
                    print(f"  [OK  ]  {dest.name}  ({dest.stat().st_size / 1024:,.0f} KB)")
                    return True
                print(f"  [WARN]  HTTP {r.status_code} — {url}")
        except httpx.RequestError as exc:
            print(f"  [ERR ]  {exc}")
        if attempt < RETRY_LIMIT:
            print(f"         Retrying in {RETRY_DELAY}s …")
            time.sleep(RETRY_DELAY)
    print(f"  [FAIL]  {label}")
    return False


def main():
    dry_run = "--dry-run" in sys.argv
    print("=" * 70)
    print("DOL OFLC Performance Data Downloader")
    print(f"Output : {BASE_DIR.resolve()}")
    print(f"Mode   : {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Files  : {len(FILES)} total")
    print("=" * 70)

    if dry_run:
        for program, fy, label, _ in FILES:
            print(f"  [{program:<4}] {fy:<12}  {label}")
        print("=" * 70)
        print("Re-run without --dry-run to download.")
        return

    ok, skipped, failed = [], [], []

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
        for program, fy, label, url in FILES:
            out_dir = BASE_DIR / program / fy
            out_dir.mkdir(parents=True, exist_ok=True)
            filename = os.path.basename(urlparse(url).path)
            dest = out_dir / filename
            already = dest.exists()
            success = download_file(client, url, dest, label)
            if success and already:
                skipped.append(label)
            elif success:
                ok.append(label)
                time.sleep(INTER_FILE_DELAY)
            else:
                failed.append(label)

    manifest = BASE_DIR / "manifest.csv"
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with open(manifest, "w") as mf:
        mf.write("program,fiscal_year,label,url\n")
        for program, fy, label, url in FILES:
            mf.write(f"{program},{fy},{label},{url}\n")

    print()
    print("=" * 70)
    print(f"Downloaded : {len(ok)}")
    print(f"Skipped    : {len(skipped)}  (already on disk)")
    print(f"Failed     : {len(failed)}")
    if failed:
        print("\nFailed files:")
        for f in failed:
            print(f"  • {f}")
    print(f"\nManifest   : {manifest}")
    print("=" * 70)


if __name__ == "__main__":
    main()
