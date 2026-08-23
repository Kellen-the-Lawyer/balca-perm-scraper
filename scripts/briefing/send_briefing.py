#!/usr/bin/env python3
"""
Weekly BALCA / AAO briefing emails.

Runs after the Sunday sync. For each corpus:
  1. Find decisions whose ingested_at is newer than the last sent briefing
     (state table briefing_runs). First run seeds the watermark silently.
  2. Score novelty for each: 1 - max cosine vs prior chunks of the same
     corpus (rag_chunks, voyage-4-large), plus boosts for overrule/reverse/
     first-impression language, unseen CFR-subsection combos (BALCA), and an
     outcome that diverges from the corpus' modal outcome.
  3. Decisions at/above NOVELTY_THRESHOLD get a <=4-sentence Haiku summary
     and a link; the rest collapse to one aggregate line per decision month.
  4. Render HTML, archive to ~/Library/Logs/casebase_briefings/, send via
     Outlook (AppleScript) from the corpus alias to Kellen. Watermark is
     advanced only after a successful send.

Usage:
  send_briefing.py --corpus balca|aao [--dry-run] [--force-since YYYY-MM-DD]
                   [--threshold 0.35] [--no-send]
  --dry-run   : score + render + write HTML, no Outlook, no watermark.
  --no-send   : write HTML and advance watermark (manual send later).
  --force-since: ignore watermark, use ingested_at > date (testing/backfill).
"""
import argparse, datetime as dt, html, json, os, re, subprocess, sys
from pathlib import Path
import httpx, psycopg2, psycopg2.extras

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
for line in (REPO / ".env").read_text().splitlines():   # same pattern as sync
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"'))

DB = os.environ.get("DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SUMMARY_MODEL = os.environ.get("BRIEFING_MODEL", "claude-haiku-4-5-20251001")
TO_ADDR = os.environ.get("BRIEFING_TO", "Kellen@kellenpowell.com")
ARCHIVE_DIR = Path.home() / "Library/Logs/casebase_briefings"
NOVELTY_THRESHOLD = {"balca": 0.30, "aao": 0.32}   # ~p98 of chunk-mean base; calibrated 2026-08-22 on 200/corpus (balca p50 .117 p90 .207; aao p50 .160 p90 .249)
AAO_EMPLOYMENT_FORMS = {"I-140", "I-129", "I-129CW", "I-526", "I-829", "I-924", "I-956"}  # no I-485: EB adjustments are not AAO-appealable; what reaches AAO is T/U/SI
AAO_I360_EMPLOYMENT_RE = re.compile(r"religious worker|special immigrant (?!juvenile)|EB-4", re.I)

CORPUS = {
    "balca": dict(table="decisions", label="BALCA", sender="balcabriefings@kellenpowell.com",
                  title_sql="case_number || coalesce(' — ' || employer_name, '')", modal="Affirmed"),
    "aao":   dict(table="aao_decisions", label="AAO", sender="aaobriefings@kellenpowell.com",
                  title_sql="coalesce(title, filename)", modal="Dismissed"),
}
RECENT_DAYS = 120  # only decisions DECIDED this recently can feature; older backfill is aggregate-only
MIN_CHARS = 4000   # shorter = procedural; never featured on base novelty
BOOST_RE = re.compile(r"\b((we|hereby|is|are) (hereby )?overrul\w+|first impression|we reverse|is reversed|hereby reversed|"
                      r"we depart from|abrogat\w+|matter of first|we decline to follow)\b", re.I)
WIN_OUTCOME = {"balca": "Reversed", "aao": "Sustained"}   # appellant prevails = notable

# ── state ─────────────────────────────────────────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS briefing_runs (
  id serial PRIMARY KEY, corpus text NOT NULL, watermark timestamptz NOT NULL,
  sent_at timestamptz DEFAULT now(), n_new int, n_featured int,
  archive_path text, status text NOT NULL DEFAULT 'sent');
"""

def get_watermark(cur, corpus):
    cur.execute("SELECT max(watermark) FROM briefing_runs WHERE corpus=%s AND status IN ('sent','seeded','nosend')", (corpus,))
    return cur.fetchone()["max"]

# ── candidates ────────────────────────────────────────────────────────────────
def fetch_new(cur, corpus, since, sample=0):
    c = CORPUS[corpus]
    where = "ingested_at > %s"
    if sample:   # testing: N random decisions from 2026 stand in for "new"
        where = "decision_date >= '2026-01-01' AND %s::text IS NOT NULL AND random() < 1"
    if corpus == "balca":
        cur.execute(f"""
          SELECT id, {c['title_sql']} AS title, decision_date, outcome, source_url, ingested_at,
                 full_text, job_title, panel, NULL AS form_type
          FROM decisions WHERE {where} AND doc_type='decision'
          ORDER BY {'random() LIMIT ' + str(sample) if sample else 'decision_date DESC NULLS LAST'}""", (since,))
    else:
        cur.execute(f"""
          SELECT id, {c['title_sql']} AS title, decision_date, outcome, source_url, ingested_at,
                 full_text, regulation AS job_title, decision_type AS panel, form_type
          FROM aao_decisions WHERE {where} AND NOT is_precedent
          ORDER BY {'random() LIMIT ' + str(sample) if sample else 'decision_date DESC NULLS LAST'}""", (since,))
    rows = [dict(r) for r in cur.fetchall()]
    excluded = {}
    if corpus == "aao":
        keep = []
        for r in rows:
            ft = (r["form_type"] or "?").strip()
            ok = ft in AAO_EMPLOYMENT_FORMS or (ft == "I-360" and AAO_I360_EMPLOYMENT_RE.search(r["full_text"][:20000] or ""))
            if ok: keep.append(r)
            else:  excluded.setdefault(ft, []).append(r)
        rows = keep
    return rows, {k: len(v) for k, v in excluded.items()}

# ── novelty ───────────────────────────────────────────────────────────────────
def chunk_novelty(cur, corpus, sid, new_ids, k=25):
    """Mean over the decision's chunks of (cosine distance to nearest chunk of any
    *prior* decision in the corpus). HNSW per chunk; own/new decisions filtered
    post-hoc in Python, so k must exceed the chunk count of the largest new doc."""
    cur.execute("SET hnsw.ef_search = 80")
    cur.execute("SELECT embedding FROM rag_chunks WHERE corpus=%s AND source_id=%s ORDER BY chunk_index", (corpus, sid))
    embs = [r["embedding"] for r in cur.fetchall()]
    if not embs:
        return None
    skip, dists = set(new_ids) | {sid}, []
    for e in embs:
        cur.execute("""SELECT source_id, embedding <=> %s::vector AS d FROM rag_chunks
                       WHERE corpus=%s ORDER BY embedding <=> %s::vector LIMIT %s""", (e, corpus, e, k))
        nn = [r["d"] for r in cur.fetchall() if r["source_id"] not in skip]
        dists.append(float(nn[0]) if nn else 1.0)
    return sum(dists) / len(dists)

def novelty(cur, corpus, row, new_ids):
    sid = str(row["id"])
    if row["outcome"] in (None, "Unknown", "Withdrawn") or re.search(r"_ORDER_|_NOTICE_", row.get("source_url") or ""):
        return 0.0, ["procedural/no outcome"]
    if not row["decision_date"] or (dt.date.today() - row["decision_date"]).days > RECENT_DAYS:
        return 0.0, ["backfill (older than %d days)" % RECENT_DAYS]
    if len(row["full_text"] or "") < MIN_CHARS:
        return 0.0, [f"short ({len(row['full_text'] or '')} chars)"]
    base = chunk_novelty(cur, corpus, sid, new_ids)
    if base is None:
        return None, ["no-embedding"]
    reasons, boost = [], 0.0
    txt = row["full_text"] or ""
    m = BOOST_RE.search(txt)
    if m:
        boost += 0.15; reasons.append(f"language: '{m.group(0)}'")
    if row["outcome"] == WIN_OUTCOME[corpus]:
        boost += 0.10; reasons.append(f"outcome {row['outcome']}")
    if corpus == "balca":
        cur.execute("""
          SELECT cfr_section, subsection FROM balca_issue_tags t
          WHERE source_id=%s AND subsection IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM balca_issue_tags p WHERE p.cfr_section=t.cfr_section
              AND p.subsection=t.subsection AND NOT (p.source_id = ANY(%s)))""", (sid, new_ids))
        fresh = cur.fetchall()
        if fresh:
            boost += 0.15; reasons.append("unseen CFR subsection: " + ", ".join(f"{r[0]}{r[1]}" for r in fresh[:3]))
    return round(min(1.0, base + boost), 3), reasons + [f"base {base:.2f}"]

# ── summaries ─────────────────────────────────────────────────────────────────
def summarize(corpus, row):
    if not ANTHROPIC_API_KEY:
        return "(no ANTHROPIC_API_KEY — summary skipped)", "NOTABLE"
    label = CORPUS[corpus]["label"]
    prompt = (f"You are briefing an immigration attorney on a new {label} decision. In at most four sentences, "
              f"state (1) the issue and the regulation or statute at stake, (2) the holding and outcome, "
              f"(3) why this matters for practitioners — what is new, or whether it is routine. "
              f"Plain prose, no headings, no preamble, no bullet points. Then on a final separate line write "
              f"exactly VERDICT: NOTABLE or VERDICT: ROUTINE — NOTABLE only if the decision announces, extends, "
              f"or departs from a rule, resolves an open question, or would change how a PERM/I-140 practitioner "
              f"prepares a case; procedural dispositions and straightforward applications of settled law are ROUTINE.\n\nDECISION TEXT:\n{(row['full_text'] or '')[:60000]}")
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=90,
                       headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                                "content-type": "application/json"},
                       json={"model": SUMMARY_MODEL, "max_tokens": 400,
                             "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        txt = "".join(b.get("text", "") for b in r.json()["content"]).strip()
        txt = re.sub(r"^(#.*\n+|\*\*.*\*\*\n+)", "", txt).strip()
        m = re.search(r"VERDICT:\s*(NOTABLE|ROUTINE)", txt, re.I)
        verdict = m.group(1).upper() if m else "NOTABLE"
        return re.sub(r"\n*\s*VERDICT:.*$", "", txt, flags=re.I|re.S).strip(), verdict
    except Exception as ex:
        return f"(summary failed: {ex})", "NOTABLE"

# ── render ────────────────────────────────────────────────────────────────────
def month_key(d):
    return d.strftime("%B %Y") if d else "Undated"

def render(corpus, featured, routine, excluded, since, now, demoted=()):
    c = CORPUS[corpus]; H = html.escape
    out = [f"<html><body style='font-family:-apple-system,Helvetica,Arial;font-size:14px;color:#222;max-width:760px'>",
           f"<h2 style='margin-bottom:2px'>{c['label']} Briefing — week ending {now:%B %d, %Y}</h2>",
           f"<p style='color:#666;margin-top:0'>{len(featured)+len(routine)} new decision(s) ingested since {since:%b %d}; "
           f"{len(featured)} flagged for review.</p>"]
    if not featured:
        out.append("<p><i>No decisions cleared the novelty threshold this week.</i></p>")
    months = {}
    for r in featured: months.setdefault(month_key(r["decision_date"]), []).append(r)
    for mk, rows in months.items():
        out.append(f"<h3 style='border-bottom:1px solid #ddd'>{H(mk)}</h3>")
        for r in rows:
            link = f"<a href='{H(r['source_url'])}'>{H(r['title'])}</a>" if r["source_url"] else H(r["title"])
            meta = " · ".join(x for x in [r["decision_date"].isoformat() if r["decision_date"] else "",
                                          r.get("form_type") or "", r["outcome"] or "",
                                          f"novelty {r['novelty']}"] if x)
            out.append(f"<p><b>{link}</b><br><span style='color:#666;font-size:12px'>{H(meta)}</span><br>"
                       f"{H(r['summary'])}<br><span style='color:#999;font-size:11px'>why flagged: {H('; '.join(r['reasons']))}</span></p>")
    if demoted:
        out.append("<h3 style='border-bottom:1px solid #ddd'>Reviewed, judged routine</h3><p style='font-size:13px'>")
        for r in demoted:
            link = f"<a href='{H(r['source_url'])}'>{H(r['title'])}</a>" if r["source_url"] else H(r["title"])
            out.append(f"{link} — {H(r['outcome'] or '')}, {H(r['summary'].split('. ')[0])}.<br>")
        out.append("</p>")
    if routine:
        cutoff = (now - dt.timedelta(days=730)).date()
        recent = [r for r in routine if r["decision_date"] and r["decision_date"] >= cutoff]
        old = [r for r in routine if r not in recent]
        if recent:
            out.append("<h3 style='border-bottom:1px solid #ddd'>Other decisions</h3>"
                       "<table style='font-size:13px;border-collapse:collapse'>"
                       "<tr style='color:#666;text-align:left'><th style='padding:2px 10px 2px 0'>Date</th><th style='padding:2px 10px 2px 0'>Decision</th><th>Disposition</th></tr>")
            for r in sorted(recent, key=lambda r: r["decision_date"], reverse=True):
                link = f"<a href='{H(r['source_url'])}'>{H(r['title'])}</a>" if r["source_url"] else H(r["title"])
                form = f" <span style='color:#888'>{H(r['form_type'])}</span>" if r.get("form_type") else ""
                out.append(f"<tr><td style='padding:2px 10px 2px 0;white-space:nowrap'>{r['decision_date']:%Y-%m-%d}</td>"
                           f"<td style='padding:2px 10px 2px 0'>{link}{form}</td><td>{H(r['outcome'] or 'Unknown')}</td></tr>")
            out.append("</table>")
        if old:
            oc = {}
            for r in old: oc[r["outcome"] or "Unknown"] = oc.get(r["outcome"] or "Unknown", 0) + 1
            out.append(f"<p style='color:#888;font-size:12px'>Backfill (decided before {cutoff:%b %Y}, now searchable in Casebase): {len(old)} decision(s) — "
                       + ", ".join(f"{n} {H(o.lower())}" for o, n in sorted(oc.items(), key=lambda x: -x[1])) + ".</p>")
    if excluded:
        out.append("<p style='color:#888;font-size:12px'>Not employment-based, omitted: "
                   + ", ".join(f"{H(k)} ({v})" for k, v in sorted(excluded.items(), key=lambda x: -x[1])) + "</p>")
    out.append(f"<p style='color:#aaa;font-size:11px'>Generated by Casebase from {c['table']}; summaries by {H(SUMMARY_MODEL)}. Review before forwarding.</p></body></html>")
    return "\n".join(out)

# ── outlook ───────────────────────────────────────────────────────────────────
def send_outlook(subject, body_html, sender, to):
    def q(s): return s.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "Microsoft Outlook"
      set msg to make new outgoing message with properties {{subject:"{q(subject)}", content:"{q(body_html)}"}}
      try
        set sender of msg to {{name:"Casebase Briefings", address:"{sender}"}}
      end try
      make new recipient at msg with properties {{email address:{{address:"{to}"}}}}
      send msg
    end tell'''
    r = subprocess.run(["osascript", "-"], input=script, text=True, capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, choices=list(CORPUS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--force-since")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--max-summaries", type=int, default=0, help="cap Haiku calls (0 = no cap)")
    ap.add_argument("--sample", type=int, default=0, help="testing: N random 2026 decisions as the new set (implies --dry-run)")
    a = ap.parse_args()
    corpus, now = a.corpus, dt.datetime.now()
    if a.threshold is None: a.threshold = NOVELTY_THRESHOLD[corpus]
    if a.sample: a.dry_run = True
    conn = psycopg2.connect(DB); conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(DDL)

    since = dt.datetime.fromisoformat(a.force_since) if a.force_since else get_watermark(cur, corpus)
    if a.sample: since = since or now
    if since is None:
        cur.execute("INSERT INTO briefing_runs (corpus, watermark, status) VALUES (%s, now(), 'seeded')", (corpus,))
        print(f"[{corpus}] first run: watermark seeded at now(); nothing sent."); return

    rows, excluded = fetch_new(cur, corpus, since, a.sample)
    print(f"[{corpus}] {len(rows)} new since {since:%Y-%m-%d %H:%M} (excluded {sum(excluded.values())})")
    new_ids = [str(r["id"]) for r in rows]
    for r in rows:
        r["novelty"], r["reasons"] = novelty(cur, corpus, r, new_ids)
    featured = sorted([r for r in rows if r["novelty"] is not None and r["novelty"] >= a.threshold],
                      key=lambda r: -r["novelty"])
    routine = [r for r in rows if r not in featured]
    demoted = []
    for i, r in enumerate(list(featured)):
        if a.max_summaries and i >= a.max_summaries:
            r["summary"], r["verdict"] = "(summary cap reached)", "NOTABLE"; continue
        r["summary"], r["verdict"] = summarize(corpus, r)
        print(f"  {r['verdict']:8} novelty {r['novelty']}  {r['title'][:60]}  [{'; '.join(r['reasons'])}]")
        if r["verdict"] == "ROUTINE":
            featured.remove(r); demoted.append(r)
    for r in routine[:5]:
        print(f"  routine {r['novelty']}  {r['title'][:70]}")

    body = render(corpus, featured, routine, excluded, since, now, demoted)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE_DIR / f"{now:%Y-%m-%d}-{corpus}{'-dryrun' if a.dry_run else ''}.html"
    path.write_text(body)
    print(f"[{corpus}] wrote {path}")
    if a.dry_run:
        return
    subject = f"{CORPUS[corpus]['label']} Briefing — {now:%b %d, %Y} ({len(featured)} flagged, {len(rows)} new)"
    status = "nosend"
    if not a.no_send:
        send_outlook(subject, body, CORPUS[corpus]["sender"], TO_ADDR)
        status = "sent"; print(f"[{corpus}] sent to {TO_ADDR}")
    wm = max(r["ingested_at"] for r in rows) if rows else since
    cur.execute("INSERT INTO briefing_runs (corpus, watermark, n_new, n_featured, archive_path, status) VALUES (%s,%s,%s,%s,%s,%s)",
                (corpus, wm, len(rows), len(featured), str(path), status))

if __name__ == "__main__":
    main()
