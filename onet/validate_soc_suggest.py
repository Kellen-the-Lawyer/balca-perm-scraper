"""
validate_soc_suggest.py — AI SOC suggestions vs DOL-certified PERM data.

Ground truth: titles with >=20 certified PERM filings (FY2024-26) where a
single SOC accounts for >=80% of filings (modal SOC). Title-only input —
a handicap vs real usage (full JD + reqs), so treat results as a floor.

Pass 1: retrieval-only (rerank=false) on ALL clean titles.
Pass 2: full pipeline (rerank=true, haiku) on the RERANK_N highest-volume.

Output: /tmp/soc_validate_results.json + printed summary with the
confusion pairs (AI top-1 vs DOL modal) sorted by filing volume.
"""
import asyncio, json, sys
import httpx, psycopg2

API = "http://127.0.0.1:8001/api/soc-suggest"
DB = "postgresql://perm@127.0.0.1:5433/perm_decisions"
RERANK_N = 150
CONCURRENCY = 5

SQL = """
with cert as (
  select lower(trim(job_title)) t, substring(soc_code from 1 for 7) soc
  from oflc_perm
  where case_status ilike 'certified%%'
    and fiscal_year in ('FY2024','FY2025','FY2026')
    and job_title is not null and soc_code is not null
), agg as (
  select t, count(*) n, mode() within group (order by soc) modal
  from cert group by t having count(*) >= 20
)
select a.t, a.n, a.modal,
       (select count(*) from cert c where c.t=a.t and c.soc=a.modal)::float/a.n share
from agg a where
  (select count(*) from cert c where c.t=a.t and c.soc=a.modal)::float/a.n >= 0.8
order by a.n desc;
"""


async def suggest(client, sem, title, rerank):
    async with sem:
        for attempt in range(3):
            try:
                r = await client.post(API, json={
                    "job_title": title, "job_description": title,
                    "min_requirements": "", "rerank": rerank, "top_k": 5},
                    timeout=120.0)
                r.raise_for_status()
                d = r.json()
                return [s["soc_code"] for s in d["suggestions"]]
            except Exception as e:
                if attempt == 2:
                    return {"error": str(e)}
                await asyncio.sleep(3 * (attempt + 1))


async def run_pass(rows, rerank, tag):
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        tasks = [suggest(client, sem, t, rerank) for t, n, modal, share in rows]
        out = await asyncio.gather(*tasks)
    results = []
    for (t, n, modal, share), socs in zip(rows, out):
        rec = {"title": t, "n": n, "dol_soc": modal, "dol_share": round(share, 3)}
        if isinstance(socs, dict):
            rec["error"] = socs["error"]
        else:
            rec["ai_socs"] = socs
            rec["top1"] = bool(socs) and socs[0] == modal
            rec["top3"] = modal in socs[:3]
        results.append(rec)
        done = len(results)
        if done % 25 == 0:
            print(f"[{tag}] {done}/{len(rows)}", flush=True)
    return results


def summarize(results, tag):
    ok = [r for r in results if "top1" in r]
    if not ok:
        print(f"[{tag}] no results"); return
    tw = sum(r["n"] for r in ok)
    t1 = sum(r["top1"] for r in ok) / len(ok)
    t3 = sum(r["top3"] for r in ok) / len(ok)
    t1w = sum(r["n"] for r in ok if r["top1"]) / tw
    t3w = sum(r["n"] for r in ok if r["top3"]) / tw
    print(f"\n[{tag}] titles={len(ok)} errors={len(results)-len(ok)}")
    print(f"[{tag}] top-1: {t1:.1%} per-title / {t1w:.1%} filing-weighted")
    print(f"[{tag}] top-3: {t3:.1%} per-title / {t3w:.1%} filing-weighted")
    conf = {}
    for r in ok:
        if not r["top1"]:
            key = (r["ai_socs"][0] if r["ai_socs"] else "none", r["dol_soc"])
            conf.setdefault(key, [0, 0])
            conf[key][0] += 1; conf[key][1] += r["n"]
    print(f"[{tag}] top confusion pairs (AI -> DOL, titles, filings):")
    for (ai, dol), (c, n) in sorted(conf.items(), key=lambda x: -x[1][1])[:12]:
        print(f"    {ai} -> {dol}   {c:3d} titles, {n:6d} filings")


async def main():
    conn = psycopg2.connect(DB); cur = conn.cursor()
    cur.execute(SQL); rows = cur.fetchall(); conn.close()
    print(f"clean ground-truth titles: {len(rows)}", flush=True)

    retr = await run_pass(rows, False, "retrieval")
    summarize(retr, "retrieval")

    rer = await run_pass(rows[:RERANK_N], True, "rerank")
    summarize(rer, "rerank")

    json.dump({"retrieval": retr, "rerank": rer},
              open("/tmp/soc_validate_results.json", "w"), indent=1)
    print("\nsaved /tmp/soc_validate_results.json")

asyncio.run(main())
