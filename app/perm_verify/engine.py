"""PERM verification engine — orchestrates extraction and rule tiers.

Usage:
    python -m app.perm_verify.engine <9089.pdf> [--filing-date YYYY-MM-DD] [--json]

Filing date defaults to the day of review (pre-filing mode); the report
always includes the computed first-day-to-file / last-day-to-file window.
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date, datetime

from .extract_9089 import extract
from .rules import tier1, tier2, tier4_form_only, filing_window, RED, YELLOW


def verify(pdf_path, filing_date=None, cite=False, cite_top_k=3, pwd_pdf=None,
           appendix_pdfs=None):
    """Verify an ETA-9089 from PDF(s).

    pdf_path may be a single path or a list of paths — FLAG Print Summary
    drafts often arrive as several documents (main print, appendices,
    per-section exports). If ANY supplied document is a draft print, the
    whole set is parsed with the draft extractor. Otherwise the first
    path is treated as the final certified form (a single PDF) and the
    geometry extractor is used.
    """
    from .extract_9089_draft import looks_like_draft, extract as extract_draft
    if isinstance(pdf_path, (list, tuple)):
        paths = list(pdf_path)
    else:
        paths = [pdf_path]
    paths += list(appendix_pdfs or [])
    if any(looks_like_draft(p) for p in paths):
        form = extract_draft(paths)
    else:
        form = extract(paths[0])
        if len(paths) > 1:
            form.setdefault("meta", {})["ignored_extra_files"] = len(paths) - 1
    pwd = None
    if pwd_pdf:
        from .extract_9141 import extract as extract_pwd
        pwd = extract_pwd(pwd_pdf)
    return verify_data(form, filing_date, cite=cite,
                       cite_top_k=cite_top_k, pwd=pwd)


def verify_data(form, filing_date=None, cite=False, cite_top_k=3, pwd=None):
    """Run all rule tiers over an already-structured ETA-9089 dict.

    `form` follows the extract_9089 section layout (A_employer, B_poc, ...,
    H_recruitment, appendix_A); `pwd` optionally follows the extract_9141
    flat layout (pwd_case_number, pw_minimum, soc_code, ...). No PDFs are
    touched — this is the entry point for structured callers (Graphite).
    """
    fd = filing_date or date.today()
    flags = tier1(form) + tier2(form, fd) + tier4_form_only(form)
    if pwd:
        from .rules_tier3 import tier3, derived_checks
        flags += tier3(form, pwd, fd)
        flags += derived_checks(form, pwd, fd)
        from .rules_onet import onet_checks
        flags += onet_checks(form, pwd)
    first, last = filing_window(form)
    window = {
        "review_date_presumed_filing": fd.isoformat(),
        "first_day_to_file": first.isoformat() if first else None,
        "last_day_to_file": last.isoformat() if last else None,
        "in_window": bool(first and last and first <= fd <= last),
    }
    flag_dicts = [f.to_dict() for f in flags]
    if cite and flag_dicts:
        from .citations import attach_citations
        attach_citations(flag_dicts, top_k=cite_top_k)
    return {
        "form": form,
        "pwd": pwd,
        "filing_window": window,
        "flags": flag_dicts,
        "summary": {
            "red": sum(1 for f in flags if f.level == RED),
            "yellow": sum(1 for f in flags if f.level == YELLOW),
        },
    }


def _print_report(result):
    w = result["filing_window"]
    s = result["summary"]
    meta = result["form"].get("meta", {})
    print(f"ETA-9089 Verification — {meta.get('perm_case_number', 'uncaptioned')}")
    print(f"Presumed filing date (review date): {w['review_date_presumed_filing']}")
    print(f"Filing window: first day {w['first_day_to_file']}, "
          f"last day {w['last_day_to_file']}"
          f" — {'IN WINDOW' if w['in_window'] else 'OUT OF WINDOW'}")
    print(f"Flags: {s['red']} RED, {s['yellow']} YELLOW\n")
    for f in result["flags"]:
        print(f"[{f['level']}] {f['rule_id']} ({f['section_item']}) "
              f"— {f['message']}")
        print(f"        cite [{f['citation_type']}]: {f['citation']}")
        for s in f.get("support", []):
            print(f"        ↳ [{s['corpus']}] {s['source_label']} "
                  f"(chunk {s['chunk_id']}, d={s['distance']})")
            print(f"          {s['snippet'][:180]}...")
    if not result["flags"]:
        print("No flags. Form is facially certifiable as of the review date.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--filing-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date())
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cite", action="store_true",
                    help="Attach supporting rag_chunks to each flag")
    ap.add_argument("--pwd", help="ETA-9141 determination PDF for Tier 3 checks")
    args = ap.parse_args()
    result = verify(args.pdf, args.filing_date, cite=args.cite, pwd_pdf=args.pwd)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
    else:
        _print_report(result)


if __name__ == "__main__":
    main()
