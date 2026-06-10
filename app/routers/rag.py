"""RAG endpoints: /api/ask, /api/ask/stats, and the Claude proxy."""
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

@router.post("/api/claude")
async def claude_proxy(request: Request):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured on server")
    body = await request.json()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
    return resp.json()


# ── RAG / Ask endpoint ────────────────────────────────────────────────────────



@router.post("/api/ask")
async def ask(request: Request):
    """
    RAG Q&A endpoint. Streams a cited answer using top-k retrieved chunks.

    Request body:
      {
        "question": "...",
        "corpus_filter": ["balca","aao","regulation","policy"],  // optional
        "top_k": 12,   // optional, default 12
        "stream": true // optional, default true
      }

    Response (streaming): newline-delimited JSON tokens:
      {"type": "sources", "sources": [...]}   // first message: retrieved sources
      {"type": "token",   "text": "..."}      // streamed answer tokens
      {"type": "done"}                        // final message
    """
    body       = await request.json()
    question   = body.get("question", "").strip()
    corpus_filter = body.get("corpus_filter", [])  # empty = all corpora
    top_k      = min(int(body.get("top_k", 12)), 20)
    do_stream  = body.get("stream", True)

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    # 1. Embed the question via Ollama
    try:
        q_vec = await embed_query(question)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Embedding failed (is Ollama running?): {e}")
    q_vec_str = "[" + ",".join(f"{v:.6f}" for v in q_vec) + "]"

    # 2. Retrieve top-k chunks by cosine similarity
    corpus_where = ""
    bind = {"k": top_k}
    if corpus_filter:
        placeholders = ", ".join(f":c{i}" for i in range(len(corpus_filter)))
        corpus_where = f"WHERE corpus IN ({placeholders})"
        for i, c in enumerate(corpus_filter):
            bind[f"c{i}"] = c

    chunks = await database.fetch_all(
        text(f"""
            SELECT id, corpus, source_id, source_label, source_date,
                   source_outcome, chunk_index, chunk_text, cfr_citation, form_type,
                   1 - (embedding <=> '{q_vec_str}'::vector) AS similarity
            FROM rag_chunks
            {corpus_where}
            ORDER BY embedding <=> '{q_vec_str}'::vector
            LIMIT :k
        """).bindparams(**bind)
    )

    if not chunks:
        async def no_results():
            yield json.dumps({"type": "sources", "sources": []}) + "\n"
            yield json.dumps({"type": "token", "text": "I could not find relevant material in the database for that question."}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
        return StreamingResponse(no_results(), media_type="text/plain")

    # 3. Build context block for the LLM
    sources = []
    context_parts = []
    seen = set()

    for i, chunk in enumerate(chunks):
        src_key = (chunk["corpus"], chunk["source_id"])
        is_new_source = src_key not in seen
        seen.add(src_key)

        label = CORPUS_LABELS.get(chunk["corpus"], chunk["corpus"])
        ref_num = i + 1

        # Build source object for the frontend
        source = {
            "ref":          ref_num,
            "corpus":       chunk["corpus"],
            "source_id":    chunk["source_id"],
            "source_label": chunk["source_label"],
            "source_date":  chunk["source_date"],
            "outcome":      chunk["source_outcome"],
            "cfr_citation": chunk["cfr_citation"],
            "form_type":    chunk["form_type"],
            "similarity":   round(float(chunk["similarity"]), 3),
            "is_new_source": is_new_source,
        }
        sources.append(source)

        # Build context snippet for the prompt
        meta_parts = [f"[{ref_num}] {label}: {chunk['source_label']}"]
        if chunk["source_date"]:
            meta_parts.append(f"Date: {chunk['source_date']}")
        if chunk["source_outcome"]:
            meta_parts.append(f"Outcome: {chunk['source_outcome']}")
        if chunk["cfr_citation"]:
            meta_parts.append(f"Citation: {chunk['cfr_citation']}")

        context_parts.append("\n".join(meta_parts) + "\n" + chunk["chunk_text"])

    context_block = "\n\n---\n\n".join(context_parts)

    # 4. Synthesize a cited answer — prefer Anthropic Claude, fall back to local Ollama
    system_prompt = """You are a legal AI assistant specializing in PERM labor certification and U.S. immigration law.
You are given retrieved excerpts from BALCA decisions, AAO decisions, federal regulations (CFR), and USCIS/FAM policy manuals.
Follow all formatting instructions exactly. Be concise and precise.
Answer the question accurately using ONLY the provided sources.

Rules:
- Cite every factual claim with the source reference number in brackets, e.g. [3] or [1][4].
- When citing a regulation, include the CFR citation if available (e.g., 20 CFR § 656.17).
- When citing a case decision, include the case label and outcome where relevant.
- If sources conflict, note the conflict and explain which is more authoritative (regulations > policy > case decisions).
- If the sources do not contain enough information to answer, say so clearly — do not speculate.
- Write in plain legal English. Be precise but readable.
- Structure longer answers with short paragraphs. Do not use bullet points unless listing distinct requirements."""

    user_prompt = f"""Sources:

{context_block}

---

Question: {question}

Answer (cite sources with [N] notation):"""

    # 5. Stream the response — use Anthropic if key is set, otherwise local Ollama
    async def generate():
        # First, emit the sources metadata
        yield json.dumps({"type": "sources", "sources": sources}) + "\n"

        if ANTHROPIC_API_KEY:
            # ── Anthropic Claude (preferred) ──────────────────────────────────
            async with httpx.AsyncClient(timeout=120.0) as http_client:
                async with http_client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 1500,
                        "stream": True,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]" or not data_str:
                            continue
                        try:
                            event = json.loads(data_str)
                            if event.get("type") == "content_block_delta":
                                delta = event.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    yield json.dumps({"type": "token", "text": delta["text"]}) + "\n"
                        except Exception:
                            continue
        else:
            # ── Local Ollama mistral:7b-instruct (fallback) ───────────────────
            payload = _json.dumps({
                "model": OLLAMA_CHAT_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                "stream": True,
                "options": {"temperature": 0, "num_predict": 1500},
            }).encode()
            async with httpx.AsyncClient(timeout=120.0) as http_client:
                async with http_client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = _json.loads(line)
                            token = event.get("message", {}).get("content", "")
                            if token:
                                yield json.dumps({"type": "token", "text": token}) + "\n"
                            if event.get("done"):
                                break
                        except Exception:
                            continue

        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(generate(), media_type="text/plain")


@router.get("/api/ask/stats")
async def ask_stats():
    """Returns stats about the RAG corpus for the UI."""
    rows = await database.fetch_all(text("""
        SELECT corpus,
               COUNT(*) AS chunks,
               COUNT(DISTINCT source_id) AS sources,
               COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded
        FROM rag_chunks
        GROUP BY corpus ORDER BY corpus
    """))
    total_chunks   = sum(r["chunks"] for r in rows)
    total_embedded = sum(r["embedded"] for r in rows)
    return {
        "total_chunks":   total_chunks,
        "total_embedded": total_embedded,
        "ready":          total_embedded > 0,
        "by_corpus": [dict(r) for r in rows],
    }


# ══════════════════════════════════════════════════════════════════════════════
# OFLC Disclosure Data Endpoints
# PERM, LCA (H-1B/H-1B1/E-3), and Prevailing Wage — FY2020–FY2026
# ══════════════════════════════════════════════════════════════════════════════

