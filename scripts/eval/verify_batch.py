#!/usr/bin/env python3
"""Batch-run the PERM verifier over the synthetic 9089/9141 pair corpus.

Uses pair.json form_data directly (the 9089 AcroForm templates are not
readable by the certified-print extractor) and an adapter that turns the
9141 form_data into the extract_9141 dict shape.  No AI calls: cite=False,
no Tier 5, no skill model.  O*NET checks hit local Postgres only.

Usage:
  python3 scripts/eval/verify_batch.py [--corpus DIR] [--limit N]
                                       [--sample N --seed S] [--out DIR]
Writes:
  <out>/flags.jsonl      one line per case: {case, filing_date, summary, flags[]}
  <out>/rule_rates.csv   rule_id, level, cases_fired, total, pct, example
  <out>/errors.jsonl     cases that raised
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.perm_verify.engine import verify_data  # noqa: E402
from app.perm_verify.rules import _d  # noqa: E402

DEFAULT_CORPUS = ROOT / "output/json/eta_pair_full_5000_unwatermarked"

_DEG = {"Master's": "Master's", "Bachelor's": "Bachelor's",
        "Doctorate": "Doctorate", "Associate's": "Associate's",
        "High School/GED": "High school/GED", "None": "None", "Other": "Other"}


def _deg(v):
    if not v:
        return None
    return _DEG.get(v, v)


def _int(v):
    try:
        return int(str(v).strip()) if v not in (None, "", "N/A") else None
    except ValueError:
        return None


def _yn(v):
    return v if v in ("Yes", "No") else None


def _clean_text(v):
    if not v:
        return None
    s = str(v).strip()
    if s.startswith('="') and s.endswith('"'):
        s = s[2:-1]
    return s or None


def adapt_pwd(fd):
    """pair.json pwd.form_data -> extract_9141-shaped dict."""
    m, r, a, det, jo = (fd.get("meta", {}), fd.get("requirements", {}),
                        fd.get("alternate_requirements", {}),
                        fd.get("determination", {}), fd.get("job_offer", {}))
    ws = jo.get("worksite", {}) or {}
    lvl = (det.get("wage_level") or "").replace("Level", "").strip() or None
    alt = _yn(a.get("accepted"))
    out = {
        "pwd_case_number": m.get("pwd_case_number"),
        "case_status": m.get("case_status"),
        "determination_date": m.get("determination_date"),
        "validity_from": m.get("determination_date"),
        "validity_to": m.get("expiration_date"),
        "expiration_date": m.get("expiration_date"),
        "employer_name": (fd.get("employer") or {}).get("legal_business_name"),
        "employer_fein": (fd.get("employer") or {}).get("fein"),
        "job_title": jo.get("job_title"),
        "travel_details": jo.get("travel_details") if jo.get("travel_required") == "Yes" else None,
        "worksite_address1": ws.get("address1"), "worksite_city": ws.get("city"),
        "worksite_state": ws.get("state"), "worksite_county": ws.get("county"),
        "worksite_postal": ws.get("postal_code"),
        # F.b
        "education_primary": _deg(r.get("education_level")),
        "other_degree_text_primary": _clean_text(r.get("other_degree")),
        "majors_primary": _clean_text(r.get("majors")),
        "second_degree_required": _yn(r.get("second_degree_required")),
        "training_required": _yn(r.get("training_required")),
        "training_months_primary": _int(r.get("training_months")),
        "experience_required": _yn(r.get("experience_required")),
        "experience_months_primary": _int(r.get("experience_months")),
        "experience_occupation": _clean_text(r.get("experience_occupation")),
        "special_reqs_primary": _yn(r.get("special_required")),
        "foreign_language_primary": bool(r.get("foreign_language")),
        "special_skills_text": _clean_text(r.get("other_special")),
        # F.c
        "alternate_reqs_accepted": alt,
        "education_alternate": _deg(a.get("education_level")) if alt == "Yes" else None,
        "other_degree_text_alternate": _clean_text(a.get("other_degree")) if alt == "Yes" else None,
        "majors_alternate": _clean_text(a.get("majors")) if alt == "Yes" else None,
        "training_alternate_accepted": _yn(a.get("training_accepted")),
        "training_months_alternate": _int(a.get("training_months")) if alt == "Yes" else None,
        "experience_alternate_accepted": _yn(a.get("experience_accepted")),
        "experience_months_alternate": _int(a.get("experience_months")) if alt == "Yes" else None,
        "special_reqs_alternate": _yn(a.get("special_required")),
        "foreign_language_alternate": bool(a.get("foreign_language")) if alt == "Yes" else False,
        "special_skills_text_alternate": _clean_text(a.get("other_special")) if alt == "Yes" else None,
        # G determination
        "soc_code": det.get("soc_code"), "soc_title": det.get("soc_title"),
        "onet_code": None if det.get("onet_code") in (None, "N/A") else det.get("onet_code"),
        "onet_title": None if det.get("onet_title") in (None, "N/A") else det.get("onet_title"),
        "combination_code": det.get("combination_soc_code"),
        "combination_title": det.get("combination_soc_title"),
        "combination_of_occupations": bool(det.get("combination_soc_code") or det.get("combination_soc_title")),
        "pw_minimum": det.get("prevailing_wage"),
        "pw_alternative": det.get("alternate_prevailing_wage"),
        "pw_per": det.get("wage_unit"),
        "pw_oews_level": lvl,
        "pw_source": det.get("wage_source"),
        "pw_survey_name": det.get("survey_name"),
        "bls_area": det.get("bls_area"),
    }
    out["education_required"] = out["education_primary"]
    out["experience_months_required"] = out["experience_months_primary"]
    return out


def run_case(case_dir):
    pj = json.load(open(case_dir / "pair.json"))
    form = pj["perm"]["form_data"]
    fd = (form.get("meta") or {}).get("received_date")
    fdate = _d(fd) if fd else None
    pwd = adapt_pwd(pj["pwd"]["form_data"])
    r = verify_data(form, fdate, cite=False, pwd=pwd)
    return {"case": case_dir.name, "filing_date": fd,
            "status": (form.get("meta") or {}).get("case_status"),
            "summary": r["summary"],
            "flags": [{k: f[k] for k in ("level", "rule_id", "section_item", "message")}
                      for f in r["flags"]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "output/eval/verify_batch"))
    args = ap.parse_args()

    cases = sorted(p for p in Path(args.corpus).iterdir() if (p / "pair.json").exists())
    if args.sample:
        random.Random(args.seed).shuffle(cases)
        cases = sorted(cases[:args.sample])
    if args.limit:
        cases = cases[:args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    fired = defaultdict(set)          # rule_id -> {case}
    levels = defaultdict(Counter)     # rule_id -> Counter(level)
    example = {}
    n_err, t0 = 0, time.time()
    with open(out / "flags.jsonl", "w") as fo, open(out / "errors.jsonl", "w") as fe:
        for i, cd in enumerate(cases, 1):
            try:
                res = run_case(cd)
            except Exception as e:
                n_err += 1
                fe.write(json.dumps({"case": cd.name, "error": repr(e),
                                     "trace": traceback.format_exc()[-1500:]}) + "\n")
                continue
            fo.write(json.dumps(res) + "\n")
            for f in res["flags"]:
                fired[f["rule_id"]].add(res["case"])
                levels[f["rule_id"]][f["level"]] += 1
                example.setdefault(f["rule_id"], f["message"][:160])
            if i % 250 == 0:
                print(f"  {i}/{len(cases)}  {time.time()-t0:.0f}s", flush=True)

    total = len(cases) - n_err
    rows = []
    for rid in sorted(fired, key=lambda r: (r.split("-")[0], r)):
        n = len(fired[rid])
        lv = "/".join(f"{k}:{v}" for k, v in sorted(levels[rid].items()))
        rows.append((rid, lv, n, total, round(100 * n / total, 1) if total else 0, example[rid]))
    with open(out / "rule_rates.csv", "w", newline="") as fc:
        w = csv.writer(fc)
        w.writerow(["rule_id", "levels", "cases_fired", "total_cases", "pct", "example"])
        w.writerows(rows)

    print(f"\n{total} cases verified, {n_err} errors, {time.time()-t0:.0f}s -> {out}")
    print(f"{'rule':9} {'levels':22} {'fired':>6} {'pct':>6}  example")
    for rid, lv, n, tot, pct, ex in rows:
        print(f"{rid:9} {lv:22} {n:6} {pct:5.1f}%  {ex[:90]}")


if __name__ == "__main__":
    main()
