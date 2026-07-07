"""Citation resolver for PERM verification flags.

For each flag, retrieves supporting chunks from rag_chunks so the report
links every flag to actual regulation / instruction / BALCA / FAQ text.

Retrieval strategy per citation_type:
  regulation / completeness -> corpora: regulation, final_rules, form_instructions_dol
  form_instructions         -> corpora: form_instructions_dol
  balca                     -> corpora: balca, ina_cases
  faq                       -> corpora: dol_faqs
  typo / data_check         -> no retrieval (self-evident from the form)

Two-stage ranking: chunks whose cfr_citation matches a CFR section named in
the flag citation are boosted; otherwise pure cosine similarity via pgvector.
Query embedding uses app.embed.embed_query_sync (voyage-4-nano, local, $0).
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[1] / ".env")
load_dotenv(Path(__file__).parents[2] / ".env")

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")

CORPORA_BY_TYPE = {
    "regulation": ("regulation", "final_rules", "form_instructions_dol"),
    "completeness": ("regulation", "form_instructions_dol"),
    "form_instructions": ("form_instructions_dol",),
    "balca": ("balca", "ina_cases"),
    "faq": ("dol_faqs",),
}

CFR_RX = re.compile(r"656\.\d+[\w().]*")

# flag section_item -> balca_issue_tags.form_section values (rank boost)
def _form_sections_for(item):
    it = (item or "").split("/")[0]
    if it in ("A.16", "A.17"):
        return ["A.16-17.bona_fide"]
    if it.startswith("H.e"):
        return ["H.e.notice_and_general"]
    if it.startswith("H.c"):
        return ["H.recruitment", "H.advertising_content"]
    if it.startswith("H.d"):
        return ["H.recruitment", "H.recruitment_report"]
    if it.startswith(("H.a", "H.b")):
        return ["H.recruitment", "supervised_recruitment"]
    if it.startswith("G.2"):
        return ["G.2.live_in_domestic"]
    if it == "G.11":
        return ["G.11.payment"]
    if it == "G.12":
        return ["G.12.layoff"]
    if it.startswith("G.5"):
        return ["AppA.qualifications", "G.requirements"]
    if it.startswith("G."):
        return ["G.requirements", "G/H.general_17"]
    if it.startswith("AppA"):
        return ["AppA.qualifications"]
    if it.startswith("E."):
        return ["E.wage_pwd"]
    if it.startswith("F."):
        return ["H.e.notice_and_general", "H.recruitment"]
    return None


def _embed_query(text: str):
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from app.embed import embed_query_sync
    return embed_query_sync(text)


def _vec_literal(vec):
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def resolve_flag(conn, flag: dict, top_k: int = 3) -> list[dict]:
    corpora = CORPORA_BY_TYPE.get(flag.get("citation_type"))
    if not corpora:
        return []
    query = f"{flag['message']} {flag['citation']}"
    vec = _vec_literal(_embed_query(query))
    cfr = CFR_RX.search(flag.get("citation") or "")
    cfr_like = f"%{cfr.group(0).split('(')[0]}%" if cfr else None
    form_sections = _form_sections_for(flag.get("section_item"))

    # Rank: CFR-section match, then issue-tag form-section match (balca),
    # then cosine distance. One chunk per decision (DISTINCT ON source).
    # Disposition-only balca decisions (dismissals/withdrawals) excluded.
    sql = """
        SELECT id, corpus, source_label, cfr_citation, snippet, dist
        FROM (
            SELECT DISTINCT ON (corpus, source_id)
                   id, corpus, source_id, source_label, cfr_citation,
                   LEFT(chunk_text, 400) AS snippet,
                   (embedding <=> %(vec)s::vector) AS dist,
                   CASE WHEN %(cfr)s::text IS NOT NULL
                             AND cfr_citation LIKE %(cfr_like)s
                        THEN 0 ELSE 1 END AS cfr_rank,
                   CASE WHEN %(sections)s::text[] IS NOT NULL
                             AND corpus = 'balca'
                             AND EXISTS (SELECT 1 FROM balca_issue_tags t
                                         WHERE t.source_id = rag_chunks.source_id
                                           AND t.form_section = ANY(%(sections)s))
                        THEN 0 ELSE 1 END AS section_rank
            FROM rag_chunks
            WHERE corpus = ANY(%(corpora)s) AND embedding IS NOT NULL
              AND (corpus <> 'balca' OR NOT EXISTS (
                    SELECT 1 FROM balca_issue_tags t
                    WHERE t.source_id = rag_chunks.source_id
                      AND t.cfr_section = 'disposition'))
            ORDER BY corpus, source_id, dist
        ) best
        ORDER BY cfr_rank, section_rank, dist
        LIMIT %(k)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"vec": vec, "cfr": cfr_like, "cfr_like": cfr_like or "",
                          "sections": form_sections, "corpora": list(corpora),
                          "k": top_k})
        rows = cur.fetchall()
    return [{
        "chunk_id": r[0], "corpus": r[1], "source_label": r[2],
        "cfr_citation": r[3], "snippet": (r[4] or "").replace("\n", " "),
        "distance": round(float(r[5]), 4),
    } for r in rows]


def attach_citations(flags: list[dict], top_k: int = 3) -> list[dict]:
    """Mutates and returns flags with a 'support' key of retrieved chunks."""
    if not flags:
        return flags
    conn = psycopg2.connect(DB_URL)
    try:
        for f in flags:
            f["support"] = resolve_flag(conn, f, top_k)
    finally:
        conn.close()
    return flags
