#!/usr/bin/env python3
"""Ask AI regression eval. Runs each case through /api/ask and checks sources, tools, and text.
    python3 scripts/eval/ask_eval.py [--base http://localhost:8011] [--only id,id] [--top-k 12]
Writes results to scripts/eval/last_run.json. Exit code = number of failures."""
import argparse, json, sys, time, urllib.request, uuid, pathlib
HERE = pathlib.Path(__file__).parent
ap = argparse.ArgumentParser(); ap.add_argument("--base", default="http://localhost:8011")
ap.add_argument("--only", default=""); ap.add_argument("--top-k", type=int, default=12); a = ap.parse_args()
cases = json.load(open(HERE / "ask_eval_cases.json"))
if a.only: cases = [c for c in cases if c["id"] in a.only.split(",")]

def ask(q, history):
    hist = [m for pair in history for m in ({"role": "user", "content": pair[0]}, {"role": "assistant", "content": pair[1]})]
    req = urllib.request.Request(f"{a.base}/api/ask", data=json.dumps({"question": q, "top_k": a.top_k, "history": hist,
                                 "conversation_id": str(uuid.uuid4())}).encode(), headers={"Content-Type": "application/json"})
    ans, sources, tools, condensed = "", [], [], None
    t = time.time()
    with urllib.request.urlopen(req, timeout=240) as r:
        for line in r:
            d = json.loads(line); ty = d.get("type")
            if ty == "token": ans += d["text"]
            elif ty == "sources": sources = d["sources"]
            elif ty == "status": tools.append(d["text"])
            elif ty == "condensed": condensed = d["query"]
            elif ty == "error": ans += f"\n[error] {d.get('message')}"
    return ans, sources, tools, condensed, time.time() - t

STATUS_TOOL = {"Looking up employer representation…": "get_employer_representation", "Looking up the firm's clients…": "get_firm_clients",
               "Querying OFLC disclosure data…": "query_oflc_data", "Checking DOL processing times…": "get_dol_processing_times",
               "Checking the visa bulletin…": "get_visa_bulletin_current", "Looking up the decision…": "search_decisions",
               "Searching the regulations and policy manuals…": "search_regulations"}
results, fails = [], 0
for c in cases:
    ans, sources, statuses, condensed, secs = ask(c["q"], c.get("history", []))
    tools = {STATUS_TOOL.get(s, s) for s in statuses}
    cited = {int(m) for m in __import__("re").findall(r"\[(\d+)\]", ans)}
    cited_srcs = [s for s in sources if s["ref"] in cited]
    labels = " | ".join(f"{s['corpus']}:{s['source_label']} {s.get('cfr_citation') or ''}" for s in cited_srcs).lower()
    problems = []
    for ms in c.get("must_source", []):
        if ms.lower() not in labels: problems.append(f"source missing: {ms}")
    if c.get("must_source_corpus") and not any(s["corpus"] == c["must_source_corpus"] for s in cited_srcs):
        problems.append(f"no cited source from corpus {c['must_source_corpus']}")
    if c.get("must_source_corpus_any") and not any(s["corpus"] in c["must_source_corpus_any"] for s in cited_srcs):
        problems.append(f"no cited source from corpora {c['must_source_corpus_any']}")
    if c.get("must_source_any") and not any(ms.lower() in labels for ms in c["must_source_any"]):
        problems.append(f"no cited source matching any of {c['must_source_any']}")
    mt = c.get("must_text", []); low = ans.lower()
    if mt:
        hits = [t for t in mt if t.lower() in low]
        if c.get("any_text") and not hits: problems.append(f"text missing (any of): {mt}")
        if not c.get("any_text") and len(hits) < len(mt): problems.append(f"text missing: {[t for t in mt if t.lower() not in low]}")
    for ft in c.get("forbid_text", []):
        if ft.lower() in low: problems.append(f"forbidden text present: {ft}")
    if c.get("must_tool"):
        if c.get("any_tool"):
            if not tools & set(c["must_tool"]): problems.append(f"tool not used (any of): {c['must_tool']}")
        else:
            for t in c["must_tool"]:
                if t not in tools: problems.append(f"tool not used: {t}")
    ok = not problems; fails += (not ok)
    print(f"{'PASS' if ok else 'FAIL'}  {c['id']:<22} {secs:5.1f}s  {'; '.join(problems)}")
    results.append({"id": c["id"], "ok": ok, "problems": problems, "secs": round(secs, 1), "tools": sorted(tools),
                    "condensed": condensed, "cited": [f"{s['corpus']}:{s['source_label']}" for s in cited_srcs], "answer": ans[:1500]})
json.dump(results, open(HERE / "last_run.json", "w"), indent=1)
print(f"\n{len(cases) - fails}/{len(cases)} passed")
sys.exit(fails)
