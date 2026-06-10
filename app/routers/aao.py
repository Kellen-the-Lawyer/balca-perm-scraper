"""AAO decisions and I&N Dec. precedents: search, detail, citations, PDFs."""
import os
import re
import json
import io
from datetime import date as _date
from typing import Any, Optional

import httpx
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import text

from core import *  # noqa: F401,F403 -- shared db, config, helpers

router = APIRouter()

@router.get("/api/aao/search")
async def aao_search(
    request: Request,
    query: str = Query(default="", alias="q"),
    outcome: Optional[str] = Query(default=None),
    form_type: Optional[str] = Query(default=None),
    regulation: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    sort_by: str = Query(default="relevance"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q_text = _clean_query(query)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    bind = {}
    is_form_query = bool(
        q_text and re.fullmatch(r"[A-Z]{1,3}-\d{2,5}[A-Z]?", q_text, flags=re.IGNORECASE)
    )

    if q_text:
        if is_form_query:
            conditions.append("""(
                d.form_type = :q_form
                OR d.filename ILIKE :q_prefix
                OR d.title ILIKE :q_prefix
                OR d.regulation ILIKE :q_prefix
            )""")
            bind["q_form"] = q_text.upper()
            bind["q_prefix"] = f"{q_text}%"
        else:
            bind["qtext"] = q_text
            bind["q_like"] = _like(q_text)
            conditions.append("d.search_vector @@ websearch_to_tsquery('english', :qtext)")
    if outcome:
        conditions.append("d.outcome = :outcome")
        bind["outcome"] = outcome
    if form_type:
        conditions.append("d.form_type = :form_type")
        bind["form_type"] = form_type
    if regulation:
        conditions.append("d.regulation ILIKE :regulation")
        bind["regulation"] = f"%{regulation}%"
    if date_from:
        conditions.append("d.decision_date >= :date_from")
        bind["date_from"] = _date.fromisoformat(date_from)
    if date_to:
        conditions.append("d.decision_date <= :date_to")
        bind["date_to"] = _date.fromisoformat(date_to)

    where = " AND ".join(conditions)

    if sort_by == "date_asc":
        order = "d.decision_date ASC NULLS LAST"
    elif sort_by == "date_desc":
        order = "d.decision_date DESC NULLS LAST"
    elif is_form_query:
        order = (
            "(CASE WHEN d.form_type = :q_form THEN 2.0 ELSE 0 END "
            "+ CASE WHEN d.filename ILIKE :q_prefix THEN 1.0 ELSE 0 END "
            "+ CASE WHEN d.title ILIKE :q_prefix THEN 0.5 ELSE 0 END) "
            "DESC, d.decision_date DESC NULLS LAST"
        )
    elif q_text:
        order = (
            "(ts_rank(d.search_vector, websearch_to_tsquery('english', :qtext)) * 0.60 "
            "+ CASE WHEN d.title ILIKE :q_like THEN 1.5 ELSE 0 END "
            "+ CASE WHEN d.filename ILIKE :q_like THEN 1.0 ELSE 0 END "
            "+ CASE WHEN d.form_type ILIKE :q_like THEN 0.8 ELSE 0 END "
            "+ CASE WHEN d.regulation ILIKE :q_like THEN 0.7 ELSE 0 END "
            "+ log(1 + COALESCE((SELECT COUNT(*) FROM aao_citations ac WHERE ac.cited_aao_id = d.id), 0)) * 0.30) "
            "DESC, d.decision_date DESC NULLS LAST"
        )
    else:
        order = "d.decision_date DESC NULLS LAST"

    snippet = ""
    if q_text and not is_form_query:
        snippet = (", ts_headline('english', d.full_text, websearch_to_tsquery('english', :qtext),"
                   " 'MaxWords=30, MinWords=15, StartSel=<mark>, StopSel=</mark>') AS headline")

    count_bind = {key: value for key, value in bind.items() if f":{key}" in where}
    total = await database.fetch_val(
        text(f"SELECT COUNT(*) FROM aao_decisions d WHERE {where}").bindparams(**count_bind))

    bind["limit"] = page_size
    bind["offset"] = offset
    rows = await database.fetch_all(
        text(f"""SELECT d.id, d.filename, d.title, d.decision_date::text,
               d.form_type, d.regulation, d.outcome, d.extraction_status,
               d.citation_quality_status, d.regulation_quality_status {snippet}
        FROM aao_decisions d WHERE {where}
        ORDER BY {order} LIMIT :limit OFFSET :offset""").bindparams(**bind))

    await log_search_event(
        request,
        corpus="aao",
        query=q_text,
        filters=_search_filters(
            outcome=outcome,
            form_type=form_type,
            regulation=regulation,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
        ),
        result_count=total,
    )
    return {"total": total, "page": page, "page_size": page_size,
            "results": [dict(r) for r in rows]}


@router.get("/api/aao/decisions/{decision_id}")
async def get_aao_decision(decision_id: int):
    row = await database.fetch_one(
        q("SELECT * FROM aao_decisions WHERE id = :id", id=decision_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    d = dict(row)
    d["decision_date"] = str(d["decision_date"]) if d["decision_date"] else None
    d["ingested_at"] = str(d["ingested_at"]) if d.get("ingested_at") else None
    d["search_vector"] = None
    return d


@router.get("/api/aao/decisions/{decision_id}/citation-map")
async def get_aao_citation_map(decision_id: int):
    """
    Returns all outbound citations from this AAO decision, keyed by cited_raw.
    Each entry includes the citation type and resolved IDs for link targets.
    Used by the frontend to hyperlink Matter of / I&N Dec. citations inline.

    Shape: { "Matter of Chawathe": { type, cited_aao_id, cited_balca_id, cited_precedent_id },
             "25 I&N Dec. 369":    { type, cited_aao_id, cited_balca_id, cited_precedent_id }, ... }
    """
    rows = await database.fetch_all(q("""
        SELECT cited_raw, citation_type, cited_aao_id, cited_balca_id, cited_precedent_id
        FROM aao_citations
        WHERE citing_id = :id
    """, id=decision_id))
    return {
        row["cited_raw"]: {
            "type":               row["citation_type"],
            "cited_aao_id":       row["cited_aao_id"],
            "cited_balca_id":     row["cited_balca_id"],
            "cited_precedent_id": row["cited_precedent_id"],
        }
        for row in rows
    }


@router.get("/api/aao/decisions/{decision_id}/citations")
async def get_aao_citations(decision_id: int):
    """
    Full citation detail for a single AAO decision — both outbound and inbound.
    Used by the detail sidebar to show what this decision cites and what cites it.
    """
    citations_made = await database.fetch_all(q("""
        SELECT ac.id, ac.cited_raw, ac.citation_type, ac.context_snippet,
               ac.cited_aao_id, ac.cited_balca_id, ac.cited_precedent_id,
               a2.title          AS cited_aao_title,
               a2.filename       AS cited_aao_filename,
               d2.case_number    AS cited_balca_case_number,
               pd.citation       AS cited_precedent_citation,
               pd.party_name     AS cited_precedent_party
        FROM aao_citations ac
        LEFT JOIN aao_decisions      a2 ON a2.id = ac.cited_aao_id
        LEFT JOIN decisions          d2 ON d2.id = ac.cited_balca_id
        LEFT JOIN precedent_decisions pd ON pd.id = ac.cited_precedent_id
        WHERE ac.citing_id = :id
        ORDER BY ac.citation_type, ac.cited_raw
    """, id=decision_id))

    cited_by = await database.fetch_all(q("""
        SELECT ac.id, ac.citing_id, ac.cited_raw, ac.citation_type, ac.context_snippet,
               a2.title    AS citing_aao_title,
               a2.filename AS citing_aao_filename,
               a2.decision_date::text AS citing_aao_date,
               a2.outcome  AS citing_aao_outcome
        FROM aao_citations ac
        JOIN aao_decisions a2 ON a2.id = ac.citing_id
        WHERE ac.cited_aao_id = :id
        ORDER BY a2.decision_date DESC NULLS LAST
    """, id=decision_id))

    return {
        "citations_made": [dict(r) for r in citations_made],
        "cited_by":       [dict(r) for r in cited_by],
    }



@router.get("/api/precedents/map")
async def get_precedent_map():
    """
    Returns the full lookup map used for inline citation linking.
    Now sourced from aao_decisions WHERE is_precedent = TRUE.
    Two keys per entry:
      - "25 I&N Dec. 369"  -> {id, citation, party_name, type}
      - "Adopted 2017-02"  -> {id, citation, party_name, type}
    """
    rows = await database.fetch_all("""
        SELECT id, citation, party_name, decision_type, adopted_num
        FROM aao_decisions
        WHERE is_precedent = TRUE
    """)
    result = {}
    for row in rows:
        if not row["citation"]:
            continue
        entry = {
            "id":         row["id"],
            "citation":   row["citation"],
            "party_name": row["party_name"],
            "type":       row["decision_type"],
        }
        m = re.search(r'(\d+ I&N Dec\. \d+)', row["citation"])
        if m:
            result[m.group(1)] = entry
            result[m.group(1).replace("I&N", "l&N")] = entry
        if row["decision_type"] == "adopted" and row["adopted_num"]:
            result[f"Adopted Decision {row['adopted_num']}"] = entry
            result[f"Adopted Decision {row['adopted_num']}".replace(" ", "\xa0")] = entry
    return result


@router.get("/api/precedents/search")
async def search_precedents(
    query: str = Query(alias="q", default=""),
    limit: int = Query(default=5, ge=1, le=20),
):
    """
    Search I&N Dec. precedent decisions (now in aao_decisions with is_precedent=TRUE).
    Ranked by text relevance + citation authority (how many AAO decisions cite them).
    """
    q_text = _clean_query(query)
    if not q_text:
        return []

    rows = await database.fetch_all(text("""
        SELECT id, citation, party_name, volume, decision_type, adopted_num,
               EXTRACT(YEAR FROM decision_date)::int AS year,
               length(full_text) AS has_text,
               COALESCE((SELECT COUNT(*) FROM aao_citations ac
                          WHERE ac.cited_aao_id = aao_decisions.id), 0) AS cited_by_count,
               (ts_rank(search_vector, websearch_to_tsquery('english', :q)) * 0.60
                + log(1 + COALESCE((SELECT COUNT(*) FROM aao_citations ac
                                     WHERE ac.cited_aao_id = aao_decisions.id), 0)) * 0.40) AS rank
        FROM aao_decisions
        WHERE is_precedent = TRUE
          AND (search_vector @@ websearch_to_tsquery('english', :q)
               OR party_name ILIKE :like
               OR citation ILIKE :like)
        ORDER BY rank DESC
        LIMIT :lim
    """).bindparams(q=q_text, like=f"%{q_text}%", lim=limit))

    return [dict(r) for r in rows]


@router.get("/api/precedents/{precedent_id}")
async def get_precedent(precedent_id: int):
    """Fetch a single precedent decision — now from aao_decisions."""
    row = await database.fetch_one(q("""
        SELECT id, citation, party_name, decision_type, adopted_num,
               EXTRACT(YEAR FROM decision_date)::int AS year,
               pdf_path, full_text, title
        FROM aao_decisions WHERE id = :id AND is_precedent = TRUE
    """, id=precedent_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return dict(row)


@router.get("/api/precedents/{precedent_id}/pdf")
async def serve_precedent_pdf(precedent_id: int):
    row = await database.fetch_one(q(
        "SELECT pdf_path FROM aao_decisions WHERE id = :id AND is_precedent = TRUE",
        id=precedent_id))
    if not row or not row["pdf_path"]:
        raise HTTPException(status_code=404, detail="PDF not available")
    path = row["pdf_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="PDF file not found on disk")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{os.path.basename(path)}"'})


@router.get("/api/aao/decisions/{decision_id}/pdf")
async def serve_aao_pdf(decision_id: int):
    row = await database.fetch_one(
        q("SELECT filename, pdf_path FROM aao_decisions WHERE id = :id", id=decision_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return _serve_pdf_source(
        local_path=row["pdf_path"],
        gcs_object=_aao_gcs_object(row["pdf_path"]),
        filename=row["filename"] or os.path.basename(row["pdf_path"]),
    )


@router.get("/api/aao/stats")
async def aao_stats():
    total = await database.fetch_val(q("SELECT COUNT(*) FROM aao_decisions"))
    indexed = await database.fetch_val(
        q("SELECT COUNT(*) FROM aao_decisions WHERE text_extracted = TRUE"))
    outcomes = await database.fetch_all(q(
        "SELECT outcome, COUNT(*) AS cnt FROM aao_decisions GROUP BY outcome ORDER BY cnt DESC"))
    top_forms = await database.fetch_all(q("""
        SELECT form_type, COUNT(*) AS cnt FROM aao_decisions
        WHERE form_type IS NOT NULL
        GROUP BY form_type ORDER BY cnt DESC LIMIT 10"""))
    return {
        "total_decisions": total,
        "indexed_decisions": indexed,
        "outcomes": [dict(r) for r in outcomes],
        "top_forms": [dict(r) for r in top_forms],
    }


# ── Regulations ───────────────────────────────────────────────────────────────



@router.get("/api/aao/search/citation-graph")
async def aao_citation_graph(
    query: str = Query(alias="q"),
    limit: int = Query(default=40, ge=5, le=80),
):
    """
    Citation network for an AAO search query.
    Precedent decisions (Chawathe, Dhanasar, etc.) are now regular aao_decisions
    rows with is_precedent=TRUE, so all edges use cited_aao_id uniformly.
    Precedent nodes are tagged node_type='precedent' for gold styling in the UI.
    """
    if not query.strip():
        return {"nodes": [], "edges": []}

    q_text = query.strip()
    is_form_query = bool(re.fullmatch(r"[A-Z]{1,3}-\d{2,5}[A-Z]?", q_text, re.IGNORECASE))

    # ── Precedent-seed mode ────────────────────────────────────────────────
    # When the query exactly matches a precedent's party_name (e.g. "Chawathe",
    # "Dhanasar"), build the graph centred on decisions that CITE that precedent
    # rather than doing a full-text search. The precedent becomes a forced hub.
    prec_seed = await database.fetch_one(text("""
        SELECT id, party_name, citation, decision_type
        FROM aao_decisions
        WHERE is_precedent = TRUE
          AND (party_name ILIKE :q OR citation ILIKE :q)
        ORDER BY CASE WHEN party_name ILIKE :q THEN 0 ELSE 1 END
        LIMIT 1
    """).bindparams(q=q_text))

    if prec_seed:
        prec_id   = prec_seed["id"]
        prec_dict = dict(prec_seed)

        # Top citing decisions, ranked by how many OTHER precedents they also cite
        citing_rows = await database.fetch_all(text("""
            SELECT d.id, d.filename, d.title, d.form_type,
                   d.decision_date::text AS date, d.outcome,
                   d.is_precedent, d.party_name, d.citation,
                   (SELECT COUNT(*) FROM aao_citations ac2
                    WHERE ac2.citing_id = d.id
                      AND ac2.cited_aao_id IN (SELECT id FROM aao_decisions WHERE is_precedent = TRUE)
                   ) AS prec_cite_count,
                   (SELECT COUNT(*) FROM aao_citations ac3
                    WHERE ac3.cited_aao_id = d.id
                   ) AS cited_by_count
            FROM aao_citations ac
            JOIN aao_decisions d ON d.id = ac.citing_id
            WHERE ac.cited_aao_id = :pid
              AND d.is_precedent = FALSE
            ORDER BY prec_cite_count DESC, cited_by_count DESC, d.decision_date DESC NULLS LAST
            LIMIT :lim
        """).bindparams(pid=prec_id, lim=limit))

        if not citing_rows:
            return {"nodes": [], "edges": []}

        citing_ids = [r["id"] for r in citing_rows]

        # Edges between the citing decisions themselves
        inter_edges = await database.fetch_all(text("""
            SELECT citing_id AS source, cited_aao_id AS target
            FROM aao_citations
            WHERE citing_id = ANY(:ids) AND cited_aao_id = ANY(:ids)
        """).bindparams(ids=citing_ids))

        # Other precedents these decisions also cite (sibling precedents)
        sibling_rows = await database.fetch_all(text("""
            SELECT ac.citing_id, ac.cited_aao_id,
                   d.id, d.party_name, d.citation, d.decision_type,
                   d.decision_date::text AS date
            FROM aao_citations ac
            JOIN aao_decisions d ON d.id = ac.cited_aao_id
            WHERE ac.citing_id = ANY(:ids)
              AND d.is_precedent = TRUE
              AND d.id != :pid
        """).bindparams(ids=citing_ids, pid=prec_id))

        sib_map = {}
        sib_edges = []
        for row in sibling_rows:
            sid = row["cited_aao_id"]
            if sid not in sib_map:
                sib_map[sid] = {
                    "id": sid, "node_type": "precedent", "tier": "secondary",
                    "label": row["party_name"] or row["citation"],
                    "party_name": row["party_name"], "citation": row["citation"],
                    "date": row["date"], "is_precedent": True,
                    "outcome": None, "form_type": None, "filename": None,
                    "cited_by_count": 0, "rank": 0.0,
                }
            sib_map[sid]["cited_by_count"] += 1
            sib_edges.append({"source": row["citing_id"], "target": sid})

        # Keep top sibling precedents
        siblings = sorted(sib_map.values(), key=lambda x: -x["cited_by_count"])[:15]
        kept_sib = {s["id"] for s in siblings}
        sib_edges = [e for e in sib_edges if e["target"] in kept_sib]

        # Build node list — hub precedent first (primary tier), then citing decisions
        nodes = [{
            "id": prec_id, "node_type": "precedent", "tier": "primary",
            "label": prec_dict["party_name"],
            "party_name": prec_dict["party_name"], "citation": prec_dict["citation"],
            "is_precedent": True, "filename": None, "form_type": None,
            "date": None, "outcome": None,
            "cited_by_count": len(citing_ids), "rank": float(len(citing_ids)),
        }]
        for r in citing_rows:
            nodes.append({
                "id": r["id"], "node_type": "aao", "tier": "secondary",
                "label": r["title"] or r["form_type"] or r["filename"] or "",
                "filename": r["filename"], "form_type": r["form_type"],
                "date": r["date"], "outcome": r["outcome"],
                "is_precedent": False, "party_name": None, "citation": None,
                "cited_by_count": int(r["cited_by_count"]), "rank": 0.0,
            })
        for s in siblings:
            nodes.append(s)

        edges = (
            [{"source": row["id"], "target": prec_id} for row in citing_rows]
            + [{"source": e["source"], "target": e["target"]} for e in inter_edges]
            + sib_edges
        )

        return {
            "query": q_text,
            "nodes": nodes,
            "edges": edges,
            "primary_count": 1,
            "secondary_count": len(citing_rows) + len(siblings),
            "precedent_count": 1 + len(siblings),
        }

    # ── Step 1: primary nodes (exclude is_precedent rows from primary set) ─
    if is_form_query:
        primary_rows = await database.fetch_all(text("""
            SELECT id, filename, title, form_type, decision_date::text AS date, outcome,
                   is_precedent, party_name, citation,
                   COALESCE((SELECT COUNT(*) FROM aao_citations ac
                             WHERE ac.cited_aao_id = aao_decisions.id), 0)::float AS rank
            FROM aao_decisions
            WHERE is_precedent = FALSE
              AND (form_type = :form OR filename ILIKE :prefix OR title ILIKE :prefix)
            ORDER BY rank DESC, decision_date DESC NULLS LAST
            LIMIT :lim
        """).bindparams(form=q_text.upper(), prefix=f"{q_text}%", lim=limit))
    else:
        primary_rows = await database.fetch_all(text("""
            SELECT id, filename, title, form_type, decision_date::text AS date, outcome,
                   is_precedent, party_name, citation,
                   (ts_rank(search_vector, websearch_to_tsquery('english', :q)) * 0.70
                    + log(1 + COALESCE((SELECT COUNT(*) FROM aao_citations ac
                                        WHERE ac.cited_aao_id = aao_decisions.id), 0)) * 0.30) AS rank
            FROM aao_decisions
            WHERE is_precedent = FALSE
              AND search_vector @@ websearch_to_tsquery('english', :q)
            ORDER BY rank DESC
            LIMIT :lim
        """).bindparams(q=q_text, lim=limit))

    if not primary_rows:
        return {"nodes": [], "edges": []}

    primary_ids = [r["id"] for r in primary_rows]
    primary_rows = [dict(r) for r in primary_rows]  # convert Records to dicts

    # ── Step 2: edges between primaries ────────────────────────────────────
    aao_edge_rows = await database.fetch_all(text("""
        SELECT citing_id AS source, cited_aao_id AS target
        FROM aao_citations
        WHERE citing_id = ANY(:ids) AND cited_aao_id = ANY(:ids)
          AND cited_aao_id IS NOT NULL
    """).bindparams(ids=primary_ids))

    # ── Step 3: secondary nodes — cited by primaries, not in primaries ─────
    # This now naturally includes precedent decisions since they're in aao_decisions
    secondary_rows = await database.fetch_all(text("""
        SELECT ac.citing_id, ac.cited_aao_id,
               d.id, d.filename, d.title, d.form_type,
               d.decision_date::text AS date, d.outcome,
               d.is_precedent, d.party_name, d.citation
        FROM aao_citations ac
        JOIN aao_decisions d ON d.id = ac.cited_aao_id
        WHERE ac.citing_id = ANY(:ids)
          AND ac.cited_aao_id IS NOT NULL
          AND ac.cited_aao_id != ALL(:ids)
    """).bindparams(ids=primary_ids))

    sec_map = {}
    sec_edges = []
    for row in secondary_rows:
        sid = row["cited_aao_id"]
        if sid not in sec_map:
            sec_map[sid] = {
                "id": sid,
                "filename": row["filename"], "title": row["title"],
                "form_type": row["form_type"], "date": row["date"],
                "outcome": row["outcome"], "cited_by_count": 0,
                "is_precedent": row["is_precedent"],
                "party_name": row["party_name"],
                "citation": row["citation"],
                "node_type": "precedent" if row["is_precedent"] else "aao",
            }
        sec_map[sid]["cited_by_count"] += 1
        sec_edges.append({"source": row["citing_id"], "target": sid})

    secondaries = sorted(sec_map.values(), key=lambda x: -x["cited_by_count"])
    # Precedents are always kept (they're the landmark cases); apply min_cites only to non-precedents
    prec_secondaries = [s for s in secondaries if s["is_precedent"]]
    aao_secondaries  = [s for s in secondaries if not s["is_precedent"]]
    min2 = 2 if len([s for s in aao_secondaries if s["cited_by_count"] >= 2]) >= 3 else 1
    aao_secondaries  = [s for s in aao_secondaries if s["cited_by_count"] >= min2][:15]
    prec_secondaries = prec_secondaries[:20]
    kept_sec_ids = {s["id"] for s in aao_secondaries} | {s["id"] for s in prec_secondaries}
    sec_edges = [e for e in sec_edges if e["target"] in kept_sec_ids]

    # ── Assemble ────────────────────────────────────────────────────────────
    def node_label(r):
        if r.get("is_precedent") and r.get("party_name"):
            return r["party_name"]
        return r.get("title") or r.get("form_type") or r.get("filename") or ""

    nodes = []
    for r in primary_rows:
        nodes.append({
            "id": r["id"], "node_type": "precedent" if r["is_precedent"] else "aao",
            "tier": "primary",
            "label": node_label(r), "filename": r["filename"],
            "form_type": r["form_type"], "date": r["date"], "outcome": r["outcome"],
            "is_precedent": r["is_precedent"], "party_name": r["party_name"],
            "citation": r["citation"], "rank": float(r["rank"] or 0),
        })
    for s in aao_secondaries + prec_secondaries:
        nodes.append({**s, "label": node_label(s), "tier": "secondary", "rank": 0.0})

    return {
        "query": q_text,
        "nodes": nodes,
        "edges": [{"source": e["source"], "target": e["target"]} for e in aao_edge_rows]
               + sec_edges,
        "primary_count": len(primary_rows),
        "secondary_count": len(aao_secondaries) + len(prec_secondaries),
        "precedent_count": len(prec_secondaries),
    }


# ── ETA-9141 PWD extraction ───────────────────────────────────────────────────

