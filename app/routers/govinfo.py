"""GovInfo bulk/package documents."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text

from core import *  # noqa: F401,F403 -- shared db, config, helpers

router = APIRouter()


@router.get("/api/govinfo-docs")
async def list_govinfo_docs(
    collection: Optional[str] = Query(default=None),
    congress: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    bind = {"limit": page_size, "offset": offset}
    if collection:
        conditions.append("collection = :collection")
        bind["collection"] = collection.upper()
    if congress:
        conditions.append("congress = :congress")
        bind["congress"] = congress
    where = " AND ".join(conditions)

    total = await database.fetch_val(
        text(f"SELECT COUNT(*) FROM govinfo_docs WHERE {where}").bindparams(**bind)
    )
    rows = await database.fetch_all(text(f"""
        SELECT id, package_id, collection, collection_label, title,
               date_issued::text, congress, doc_class, doc_number,
               doc_version, publisher, page_count,
               jsonb_array_length(sections) AS section_count
        FROM govinfo_docs
        WHERE {where}
        ORDER BY date_issued DESC NULLS LAST, package_id
        LIMIT :limit OFFSET :offset
    """).bindparams(**bind))
    return {"total": total, "page": page, "page_size": page_size,
            "results": [dict(row) for row in rows]}


@router.get("/api/govinfo-docs/search")
async def search_govinfo_docs(
    request: Request,
    query: str = Query(default="", alias="q"),
    collection: Optional[str] = Query(default=None),
    congress: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q_text = _clean_query(query)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    bind = {"limit": page_size, "offset": offset}

    if q_text:
        conditions.append("d.search_vector @@ websearch_to_tsquery('english', :qtext)")
        bind["qtext"] = q_text
    if collection:
        conditions.append("d.collection = :collection")
        bind["collection"] = collection.upper()
    if congress:
        conditions.append("d.congress = :congress")
        bind["congress"] = congress

    where = " AND ".join(conditions)
    order = (
        "ts_rank(d.search_vector, websearch_to_tsquery('english', :qtext)) DESC, d.date_issued DESC NULLS LAST"
        if q_text else
        "d.date_issued DESC NULLS LAST, d.package_id"
    )
    snippet = ""
    if q_text:
        snippet = """,
            ts_headline('english', d.full_text, websearch_to_tsquery('english', :qtext),
                'MaxWords=40, MinWords=18, StartSel=<mark>, StopSel=</mark>') AS headline
        """

    total = await database.fetch_val(
        text(f"SELECT COUNT(*) FROM govinfo_docs d WHERE {where}").bindparams(**bind)
    )
    rows = await database.fetch_all(text(f"""
        SELECT d.id, d.package_id, d.collection, d.collection_label, d.title,
               d.date_issued::text, d.congress, d.doc_class, d.doc_number,
               d.doc_version, d.publisher, d.page_count {snippet}
        FROM govinfo_docs d
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
    """).bindparams(**bind))

    await log_search_event(
        request,
        corpus="govinfo",
        query=q_text,
        filters=_search_filters(collection=collection, congress=congress),
        result_count=int(total or 0),
    )
    return {"total": total, "page": page, "page_size": page_size,
            "results": [dict(row) for row in rows]}


@router.get("/api/govinfo-docs/{doc_id}")
async def get_govinfo_doc(doc_id: int):
    row = await database.fetch_one(
        q("SELECT * FROM govinfo_docs WHERE id = :id", id=doc_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    doc = dict(row)
    doc["date_issued"] = str(doc["date_issued"]) if doc["date_issued"] else None
    doc["ingested_at"] = str(doc["ingested_at"]) if doc["ingested_at"] else None
    doc["search_vector"] = None
    return doc


@router.get("/api/govinfo-docs/stats/summary")
async def govinfo_stats():
    total = await database.fetch_val(q("SELECT COUNT(*) FROM govinfo_docs"))
    pages = await database.fetch_val(q("SELECT COALESCE(SUM(page_count), 0) FROM govinfo_docs"))
    by_collection = await database.fetch_all(q("""
        SELECT collection, collection_label, COUNT(*) AS docs, SUM(page_count) AS pages
        FROM govinfo_docs
        GROUP BY collection, collection_label
        ORDER BY docs DESC
    """))
    return {
        "total_docs": total,
        "total_pages": pages,
        "by_collection": [dict(row) for row in by_collection],
    }
