"""
ingest_onet_occupations.py
--------------------------
Parses O*NET 30.2 MySQL dump files, builds composite occupation text,
embeds with voyage-4-large (app/embed.py), and loads into the
perm_decisions database (onet_occupations table, pgvector 1024-dim).

Run from repo root:
    PYTHONPATH=/Users/Dad/Documents/GitHub/Casebase \
      nohup venv/bin/python onet/ingest_onet_occupations.py \
      > /tmp/onet_ingest.log 2>&1 &

Composite text per occupation:
    Title, alternate titles (top 20), reported titles (top 10),
    description, core tasks (top 10), hot technology skills (top 15).

Alternate + reported titles are ALSO stored as text[] columns for
lexical title matching in the SOC suggester (a JD titled "Software
Engineer" should hard-hit 15-1252 regardless of cosine score).
"""

import re
import sys
from collections import defaultdict

import psycopg2
from psycopg2.extras import execute_batch

sys.path.insert(0, "/Users/Dad/Documents/GitHub/Casebase")
from app.embed import embed_documents  # voyage-4-large, 1024-dim

ONET_DIR = "/Users/Dad/Documents/GitHub/Casebase/onet/db_30_2_mysql"
DB_DSN = "postgresql://perm@127.0.0.1:5433/perm_decisions"

MAX_TASKS = 10
MAX_ALT_TITLES = 20
MAX_REPORTED = 10
MAX_TECH = 15


def unesc(s):
    return s.replace("''", "'")


def _rows(path, table):
    """Yield tuples of quoted-string/numeric fields from INSERT statements."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = rf"INSERT INTO {table} [^)]*\) VALUES \((.*?)\);\n"
    for m in re.finditer(pattern, content, re.DOTALL):
        yield m.group(1)


_FIELD = re.compile(r"'((?:[^']|'')*)'|(NULL)|(-?[\d.]+)")


def _split_fields(raw):
    out = []
    for m in _FIELD.finditer(raw):
        if m.group(1) is not None:
            out.append(unesc(m.group(1)))
        elif m.group(2):
            out.append(None)
        else:
            out.append(m.group(3))
    return out


def parse_occupation_data():
    occ = {}
    for raw in _rows(f"{ONET_DIR}/03_occupation_data.sql", "occupation_data"):
        f = _split_fields(raw)
        occ[f[0].strip()] = {"title": f[1].strip(), "description": f[2].strip()}
    return occ


def parse_task_statements():
    tasks = defaultdict(list)
    for raw in _rows(f"{ONET_DIR}/17_task_statements.sql", "task_statements"):
        f = _split_fields(raw)
        code, task_text, task_type = f[0].strip(), f[2].strip(), (f[3] or "").strip()
        if task_type == "Core" and len(tasks[code]) < MAX_TASKS:
            tasks[code].append(task_text)
    return dict(tasks)


def parse_alternate_titles():
    alts = defaultdict(list)
    for raw in _rows(f"{ONET_DIR}/29_alternate_titles.sql", "alternate_titles"):
        f = _split_fields(raw)
        alts[f[0].strip()].append(f[1].strip())
    return dict(alts)


def parse_reported_titles():
    rep = defaultdict(list)
    for raw in _rows(f"{ONET_DIR}/30_sample_of_reported_titles.sql",
                     "sample_of_reported_titles"):
        f = _split_fields(raw)
        rep[f[0].strip()].append(f[1].strip())
    return dict(rep)


def parse_technology_skills():
    """Hot technologies first, then others, capped at MAX_TECH per code."""
    hot, other = defaultdict(list), defaultdict(list)
    for raw in _rows(f"{ONET_DIR}/31_technology_skills.sql", "technology_skills"):
        f = _split_fields(raw)
        code, example, is_hot = f[0].strip(), f[1].strip(), (f[3] or "N")
        (hot if is_hot == "Y" else other)[code].append(example)
    tech = {}
    for code in set(hot) | set(other):
        seen = list(dict.fromkeys(hot.get(code, []) + other.get(code, [])))
        tech[code] = seen[:MAX_TECH]
    return tech


def build_composite(code, occ, tasks, alts, reps, tech):
    o = occ[code]
    parts = [f"Occupation: {o['title']} (O*NET-SOC {code})"]
    a = list(dict.fromkeys(alts.get(code, [])))[:MAX_ALT_TITLES]
    if a:
        parts.append(f"Also known as: {', '.join(a)}")
    r = list(dict.fromkeys(reps.get(code, [])))[:MAX_REPORTED]
    if r:
        parts.append(f"Reported job titles: {', '.join(r)}")
    parts.append(f"Description: {o['description']}")
    t = tasks.get(code, [])
    if t:
        parts.append("Core tasks: " + " ".join(t))
    tk = tech.get(code, [])
    if tk:
        parts.append(f"Technology and tools: {', '.join(tk)}")
    return "\n".join(parts)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS onet_occupations (
    onetsoc_code     VARCHAR(12) PRIMARY KEY,
    soc_code         VARCHAR(7) NOT NULL,          -- 6-digit base, e.g. 15-1252
    title            TEXT NOT NULL,
    description      TEXT NOT NULL,
    alternate_titles TEXT[] NOT NULL DEFAULT '{}',
    reported_titles  TEXT[] NOT NULL DEFAULT '{}',
    composite_text   TEXT NOT NULL,
    embedding        vector(1024)
);
"""

INDEX_SQL = [
    """CREATE INDEX IF NOT EXISTS onet_occ_embedding_idx
       ON onet_occupations USING hnsw (embedding vector_cosine_ops);""",
    """CREATE INDEX IF NOT EXISTS onet_occ_soc_idx
       ON onet_occupations (soc_code);""",
]


def main():
    print("=== O*NET occupation ingest (perm_decisions, voyage-4-large) ===")
    occ = parse_occupation_data()
    tasks = parse_task_statements()
    alts = parse_alternate_titles()
    reps = parse_reported_titles()
    tech = parse_technology_skills()
    print(f"occupations={len(occ)} task_codes={len(tasks)} "
          f"alt_codes={len(alts)} rep_codes={len(reps)} tech_codes={len(tech)}")
    if len(occ) < 900:
        print("ERROR: occupation_data parse looks short — aborting.")
        sys.exit(1)

    codes = sorted(occ.keys())
    texts = [build_composite(c, occ, tasks, alts, reps, tech) for c in codes]
    print(f"composite texts built: {len(texts)}; "
          f"avg chars={sum(len(t) for t in texts)//len(texts)}")

    print("embedding with voyage-4-large ...")
    vecs = embed_documents(texts)
    assert len(vecs) == len(codes) and len(vecs[0]) == 1024

    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()

    rows = []
    for i, c in enumerate(codes):
        base = c.split(".")[0]
        rows.append((
            c, base, occ[c]["title"], occ[c]["description"],
            list(dict.fromkeys(alts.get(c, []))),
            list(dict.fromkeys(reps.get(c, []))),
            texts[i], str(vecs[i]),
        ))
    sql = """
        INSERT INTO onet_occupations
          (onetsoc_code, soc_code, title, description,
           alternate_titles, reported_titles, composite_text, embedding)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (onetsoc_code) DO UPDATE SET
          soc_code=EXCLUDED.soc_code, title=EXCLUDED.title,
          description=EXCLUDED.description,
          alternate_titles=EXCLUDED.alternate_titles,
          reported_titles=EXCLUDED.reported_titles,
          composite_text=EXCLUDED.composite_text,
          embedding=EXCLUDED.embedding;
    """
    with conn.cursor() as cur:
        execute_batch(cur, sql, rows, page_size=100)
    conn.commit()
    with conn.cursor() as cur:
        for s in INDEX_SQL:
            cur.execute(s)
    conn.commit()
    conn.close()
    print(f"=== Done: {len(rows)} occupations loaded. ===")


if __name__ == "__main__":
    main()
