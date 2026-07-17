"""
SOC Code & Wage Level Suggester — /api/soc-suggest

Workflow:
  1. Accepts job title + job description + minimum requirements.
  2. Hybrid retrieval against onet_occupations:
       a. semantic — cosine similarity on voyage composite embeddings
       b. lexical  — exact title hits on title / alternate_titles /
                     reported_titles (a JD titled "Software Engineer"
                     must surface 15-1252 regardless of cosine score)
  3. LLM re-rank (ASK_AI_MODEL) over the merged candidates, returning a
     per-candidate verdict + rationale (duties matched / not covered),
     plus a structured parse of the minimum requirements.
  4. Runs the NPWHC 5-step wage-level worksheet (wage_level router) on
     the top pick using the parsed requirements, returning the full
     auditable worksheet + prevailing wage dollars when geography given.
  5. Flags job-zone mismatches (requirements far above the occupation's
     typical preparation — PWD redetermination / audit exposure).

Graphite integration: LCA details tab and PERM details tab call this
endpoint via casebase_client; response is self-contained JSON.
"""
import json
import re
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from core import *  # noqa: F401,F403 -- database, ANTHROPIC_API_KEY, ASK_AI_MODEL, embed_query
from routers import wage_level as wl

router = APIRouter()

SEMANTIC_K = 10       # candidates from cosine retrieval
MAX_CANDIDATES = 8    # cap sent to the LLM


class SocSuggestRequest(BaseModel):
    job_title: str = ""
    job_description: str
    min_requirements: str = ""
    top_k: int = Field(5, ge=1, le=8)
    # optional geography for prevailing wage dollars
    area_code: Optional[str] = None
    state_ab: Optional[str] = None
    county_name: Optional[str] = None
    collection_type: str = "alc"
    # skip the LLM re-rank (retrieval-only mode)
    rerank: bool = True

# ── Retrieval ────────────────────────────────────────────────────────────────

async def _semantic_candidates(query_text: str, k: int):
    vec = await embed_query(query_text)
    vec_str = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
    rows = await database.fetch_all(text(f"""
        SELECT o.onetsoc_code, o.soc_code, o.title, o.description,
               o.composite_text, z.job_zone,
               1 - (o.embedding <=> '{vec_str}'::vector) AS similarity
        FROM onet_occupations o
        LEFT JOIN onet_job_zones z ON z.onetsoc_code = o.onetsoc_code
        ORDER BY o.embedding <=> '{vec_str}'::vector
        LIMIT :k""").bindparams(k=k))
    return [dict(r) for r in rows]


async def _lexical_candidates(job_title: str):
    t = (job_title or "").strip()
    if len(t) < 3:
        return []
    rows = await database.fetch_all(text(r"""
        SELECT o.onetsoc_code, o.soc_code, o.title, o.description,
               o.composite_text, z.job_zone,
               NULL::float AS similarity
        FROM onet_occupations o
        LEFT JOIN onet_job_zones z ON z.onetsoc_code = o.onetsoc_code
        WHERE lower(o.title) = lower(:t)
           OR EXISTS (SELECT 1 FROM unnest(o.alternate_titles) a
                      WHERE lower(regexp_replace(a, '\s*\(.*\)\s*$', '')) = lower(:t)
                         OR lower(a) = lower(:t))
           OR EXISTS (SELECT 1 FROM unnest(o.reported_titles) r
                      WHERE lower(regexp_replace(r, '\s*\(.*\)\s*$', '')) = lower(:t)
                         OR lower(r) = lower(:t))
        LIMIT 5""").bindparams(t=t))
    if not rows:
        # retry with seniority prefix stripped (Senior/Lead/Principal/…)
        stripped = re.sub(r"^(senior|sr\.?|lead|principal|staff|junior|jr\.?)\s+",
                          "", t, flags=re.I)
        if stripped != t:
            return await _lexical_candidates(stripped)
    return [dict(r) for r in rows]


async def _gather_candidates(req: SocSuggestRequest):
    query_text = "\n".join(p for p in [
        f"Job title: {req.job_title}" if req.job_title else "",
        req.job_description,
        f"Minimum requirements: {req.min_requirements}" if req.min_requirements else "",
    ] if p)
    semantic = await _semantic_candidates(query_text, SEMANTIC_K)
    lexical = await _lexical_candidates(req.job_title)
    merged, seen = [], set()
    for c in lexical:
        c["lexical_match"] = True
        merged.append(c); seen.add(c["onetsoc_code"])
    for c in semantic:
        if c["onetsoc_code"] in seen:
            for m in merged:
                if m["onetsoc_code"] == c["onetsoc_code"]:
                    m["similarity"] = c["similarity"]
            continue
        c["lexical_match"] = False
        merged.append(c); seen.add(c["onetsoc_code"])
    return merged[:MAX_CANDIDATES]

# ── LLM re-rank + requirements parse ─────────────────────────────────────────

_SYSTEM = """You are an expert on the U.S. SOC occupational classification \
system as applied to DOL prevailing wage determinations, LCAs, and PERM \
labor certification. You compare a job description and its stated minimum \
requirements against candidate O*NET-SOC occupations and rank the matches. \
Base every judgment ONLY on the provided candidate occupation texts. \
Respond with ONLY a valid JSON object — no markdown fences, no preamble."""

_USER_TMPL = """Job title: {title}

Job description:
{jd}

Stated minimum requirements:
{reqs}

Candidate occupations:
{cands}

Return JSON exactly in this shape:
{{
  "requirements": {{
    "degree_required": one of ["none","high_school","associates","bachelors","masters","doctorate","professional"],
    "months_experience": integer months of experience required (0 if none stated),
    "special_skills": [short strings — specific skills/tools/certifications beyond an entry-level worker in the matched occupation],
    "special_skills_points": 0, 1, or 2 — suggested Step-4 points per the NPWHC worksheet,
    "foreign_language_required": bool,
    "supervisory_duties": bool
  }},
  "ranking": [
    {{
      "onetsoc_code": "...",
      "verdict": one of ["strong","moderate","weak"],
      "rationale": 2-3 sentences: why this occupation does or does not fit,
      "duties_matched": [short phrases from the JD that map to this occupation's tasks],
      "duties_not_covered": [JD duties that fall OUTSIDE this occupation, if any]
    }}
  ]
}}
Rank ALL candidates, best match first. Judge by duties performed, not by \
job title prestige or wage. If duties span two occupations, say so in the \
rationale of both. Follow OFLC practice: always prefer the most SPECIFIC \
occupation that covers the core duties; select a residual "All Other" \
category (title containing "All Other", codes typically ending in 99) ONLY \
when no specific occupation fits — a specialization or newer job title \
(e.g. DevOps, SRE, full-stack) still belongs under its parent specific \
occupation, not the residual. A "lead", "senior", or "principal" prefix \
does not make a role managerial unless the duties are primarily managing \
people rather than performing the occupation's work. When an occupation \
carries a NOTE that it officially lists the given job title among its \
known O*NET titles, that occupation is presumptively the correct match — \
rank it first unless the described duties clearly contradict it."""


def _cand_block(cands, job_title=""):
    parts = []
    for c in cands:
        note = ""
        if c.get("lexical_match") and job_title:
            note = (f"\n*** NOTE: This occupation officially lists "
                    f"\"{job_title}\" among its known alternate/reported job "
                    f"titles in O*NET. ***")
        parts.append(f"### {c['onetsoc_code']}{note}\n{c['composite_text'][:2400]}")
    return "\n\n".join(parts)


async def _llm_rerank(req: SocSuggestRequest, cands):
    body = {
        "model": ASK_AI_MODEL,
        "max_tokens": 3000,
        "temperature": 0,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": _USER_TMPL.format(
            title=req.job_title or "(not given)",
            jd=req.job_description[:8000],
            reqs=req.min_requirements[:3000] or "(not given)",
            cands=_cand_block(cands, req.job_title))}],
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json=body)
    data = resp.json()
    if "content" not in data:
        raise RuntimeError(f"Anthropic error: {data.get('error', data)}")
    raw = "".join(b.get("text", "") for b in data["content"])
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
    return json.loads(raw)

# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/api/soc-suggest")
async def soc_suggest(req: SocSuggestRequest):
    if not req.job_description.strip():
        raise HTTPException(400, "job_description is required")

    try:
        cands = await _gather_candidates(req)
    except Exception as e:
        raise HTTPException(503, f"Retrieval failed: {e}")
    if not cands:
        raise HTTPException(404, "No candidate occupations found")
    by_code = {c["onetsoc_code"]: c for c in cands}

    parsed_reqs, llm_ranking, llm_error = None, None, None
    if req.rerank and ANTHROPIC_API_KEY:
        try:
            out = await _llm_rerank(req, cands)
            parsed_reqs = out.get("requirements")
            llm_ranking = out.get("ranking")
        except Exception as e:
            llm_error = str(e)

    # Assemble suggestions in LLM order, falling back to retrieval order
    suggestions, used = [], set()
    order = []
    if llm_ranking:
        for r in llm_ranking:
            code = r.get("onetsoc_code")
            if code in by_code and code not in used:
                order.append((by_code[code], r)); used.add(code)
    for c in cands:
        if c["onetsoc_code"] not in used:
            order.append((c, None)); used.add(c["onetsoc_code"])

    for c, r in order[:req.top_k]:
        suggestions.append({
            "onetsoc_code": c["onetsoc_code"],
            "soc_code": c["soc_code"],
            "title": c["title"],
            "description": c["description"],
            "job_zone": c["job_zone"],
            "similarity": round(float(c["similarity"]), 4)
                          if c["similarity"] is not None else None,
            "lexical_title_match": c["lexical_match"],
            "verdict": (r or {}).get("verdict"),
            "rationale": (r or {}).get("rationale"),
            "duties_matched": (r or {}).get("duties_matched", []),
            "duties_not_covered": (r or {}).get("duties_not_covered", []),
        })

    # Wage-level worksheet for the top suggestion
    wage_result, wage_error = None, None
    top = suggestions[0]
    if parsed_reqs:
        try:
            det = wl.DetermineRequest(
                soc_code=top["soc_code"],
                degree_required=parsed_reqs.get("degree_required", "bachelors"),
                months_experience_required=int(parsed_reqs.get("months_experience") or 0),
                special_skills_points=min(2, max(0, int(parsed_reqs.get("special_skills_points") or 0))),
                foreign_language_required=bool(parsed_reqs.get("foreign_language_required")),
                supervisory_duties=bool(parsed_reqs.get("supervisory_duties")),
                area_code=req.area_code, state_ab=req.state_ab,
                county_name=req.county_name, collection_type=req.collection_type)
            wage_result = await wl.wage_level_determine(det)
        except Exception as e:
            wage_error = str(e)

    # Job-zone mismatch flag (PWD redetermination / audit exposure)
    flags = []
    if len(req.job_description.strip()) < 100:
        flags.append(
            "The job description provided is very short — suggestions are "
            "driven mostly by the job title, which is unreliable for generic "
            "titles. Paste the full duties section for a dependable ranking.")
    if wage_result and top.get("job_zone") and top["job_zone"] <= 2 \
            and wage_result.get("total_points", 0) >= 4:
        flags.append(
            f"Requirements score {wage_result['total_points']} worksheet "
            f"points but {top['soc_code']} is Job Zone {top['job_zone']} "
            f"(little preparation typical). Requirements this far above "
            f"normal invite a 656.17(h) business-necessity challenge or a "
            f"higher-zone SOC reassignment by the NPWC.")

    return {
        "suggestions": suggestions,
        "parsed_requirements": parsed_reqs,
        "wage_determination": wage_result,
        "wage_determination_error": wage_error,
        "flags": flags,
        "llm_rerank_used": llm_ranking is not None,
        "llm_error": llm_error,
        "model": ASK_AI_MODEL if llm_ranking is not None else None,
    }
