"""
onet_ingest.py
--------------
Parses O*NET MySQL dump files, builds composite occupation text,
generates sentence-transformer embeddings, and loads everything
into PostgreSQL with pgvector.

Usage:
    python3 onet_ingest.py

Requirements:
    pip3 install sentence-transformers psycopg2-binary pgvector
"""

import re
import sys
from collections import defaultdict

import psycopg2
from psycopg2.extras import execute_batch
from sentence_transformers import SentenceTransformer

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

ONET_DIR = "/Users/Dad/Documents/GitHub/balca-perm-scraper/perm-research/onet/db_30_2_mysql"

DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "casebase",
    "user":     "Dad",
    "password": "",
}

MODEL_NAME = "all-MiniLM-L6-v2"
MAX_TASKS  = 10


# ─────────────────────────────────────────────
# PARSERS
# ─────────────────────────────────────────────

def unescape_sql_string(s):
    return s.replace("''", "'")


def parse_occupation_data(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = r"INSERT INTO occupation_data.*?VALUES \('([^']+)',\s*'((?:[^']|'')*)',\s*'((?:[^']|'')*)'\);"
    occupations = {}
    for m in re.finditer(pattern, content):
        code = m.group(1).strip()
        occupations[code] = {
            "title":       unescape_sql_string(m.group(2).strip()),
            "description": unescape_sql_string(m.group(3).strip()),
        }
    return occupations


def parse_task_statements(path, max_tasks=10):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = (
        r"INSERT INTO task_statements.*?VALUES "
        r"\('([^']+)',\s*[\d.]+,\s*'((?:[^']|'')*)',\s*'([^']*)'"
    )
    tasks = defaultdict(list)
    for m in re.finditer(pattern, content):
        code      = m.group(1).strip()
        task_text = unescape_sql_string(m.group(2).strip())
        task_type = m.group(3).strip()
        if task_type == "Core" and len(tasks[code]) < max_tasks:
            tasks[code].append(task_text)
    return dict(tasks)


def parse_alternate_titles(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = r"INSERT INTO alternate_titles.*?VALUES \('([^']+)',\s*'((?:[^']|'')*)'"
    alt_titles = defaultdict(list)
    for m in re.finditer(pattern, content):
        alt_titles[m.group(1).strip()].append(
            unescape_sql_string(m.group(2).strip())
        )
    return dict(alt_titles)


# ─────────────────────────────────────────────
# COMPOSITE TEXT BUILDER
# ─────────────────────────────────────────────

def build_composite_text(code, occupations, tasks, alt_titles):
    occ   = occupations[code]
    parts = [f"Title: {occ['title']}"]
    alts  = list(dict.fromkeys(alt_titles.get(code, [])))[:20]
    if alts:
        parts.append(f"Also known as: {', '.join(alts)}")
    parts.append(f"Description: {occ['description']}")
    job_tasks = tasks.get(code, [])
    if job_tasks:
        parts.append(f"Key Tasks: {' '.join(job_tasks)}")
    return "\n".join(parts)


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS onet_occupations (
    onetsoc_code   VARCHAR(10) PRIMARY KEY,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    composite_text TEXT NOT NULL,
    embedding      vector(384)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS onet_embedding_idx
    ON onet_occupations
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);
"""


def setup_database(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print("  Database table ready")


def insert_occupations(conn, rows):
    sql = """
        INSERT INTO onet_occupations
            (onetsoc_code, title, description, composite_text, embedding)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (onetsoc_code) DO UPDATE SET
            title          = EXCLUDED.title,
            description    = EXCLUDED.description,
            composite_text = EXCLUDED.composite_text,
            embedding      = EXCLUDED.embedding;
    """
    with conn.cursor() as cur:
        execute_batch(cur, sql, rows, page_size=100)
    conn.commit()
    print(f"  Inserted/updated {len(rows)} rows")


def build_index(conn):
    with conn.cursor() as cur:
        cur.execute(CREATE_INDEX_SQL)
    conn.commit()
    print("  Vector index created")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("\n=== O*NET Ingestion Pipeline ===\n")

    print("Step 1: Parsing SQL files...")
    occupations = parse_occupation_data(f"{ONET_DIR}/03_occupation_data.sql")
    print(f"  occupation_data:  {len(occupations):,} rows")
    tasks = parse_task_statements(f"{ONET_DIR}/17_task_statements.sql", MAX_TASKS)
    print(f"  task_statements:  {sum(len(v) for v in tasks.values()):,} core tasks")
    alt_titles = parse_alternate_titles(f"{ONET_DIR}/29_alternate_titles.sql")
    print(f"  alternate_titles: {sum(len(v) for v in alt_titles.values()):,} titles")


    print("\nStep 2: Building composite texts...")
    codes = list(occupations.keys())
    composite_texts = [
        build_composite_text(code, occupations, tasks, alt_titles)
        for code in codes
    ]
    print(f"  Built {len(composite_texts):,} composite texts")

    print(f"\nStep 3: Generating embeddings with {MODEL_NAME}...")
    print("  (First run downloads ~80MB model — subsequent runs are instant)")
    model = SentenceTransformer(MODEL_NAME)
    embeddings = model.encode(
        composite_texts,
        batch_size=64,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    print(f"  Generated {len(embeddings):,} embeddings, shape: {embeddings.shape}")

    print(f"\nStep 4: Loading into PostgreSQL...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except psycopg2.OperationalError as e:
        print(f"\n  ERROR: Could not connect to database.\n  {e}")
        sys.exit(1)

    setup_database(conn)

    rows = [
        (
            codes[i],
            occupations[codes[i]]["title"],
            occupations[codes[i]]["description"],
            composite_texts[i],
            embeddings[i].tolist(),
        )
        for i in range(len(codes))
    ]

    insert_occupations(conn, rows)
    build_index(conn)
    conn.close()

    print(f"\n=== Done! {len(rows):,} occupations loaded into onet_occupations. ===\n")


if __name__ == "__main__":
    main()
