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
from routers.ask_tools import build_tools_schema, execute_ask_tool

router = APIRouter()

# ── Multi-turn helpers ────────────────────────────────────────────────────────
import time as _time

MAX_HISTORY_TURNS = 6          # prior turns kept (3 exchanges)
MAX_HISTORY_CHARS = 24000      # ~6k tokens
ASSISTANT_TRUNC_CHARS = 1500

CONDENSE_SYSTEM = (
    "You rewrite the latest user message in an immigration-law research chat so it can be "
    "searched on its own, without the conversation.\n"
    "Rules:\n"
    "- If the message depends on earlier turns (pronouns, 'that', 'the same', 'what about', "
    "'and for'), rewrite it as one complete, specific question that includes the needed context "
    "(employer names, visa category, regulation, case).\n"
    "- If the message asks about something the assistant just said ('what do you mean by X', "
    "'explain that part'), rewrite it as a question about that specific content.\n"
    "- If the message starts a new topic or is already self-contained, return it exactly as written.\n"
    "- Keep terms of art (PERM, PWD, LCA, BALCA, AAO, RFE). Do not answer. No commentary.\n"
    "- Output only the rewritten question, one line."
)


def _trim_history(history: list) -> list:
    """Keep last N well-formed turns, truncate long assistant answers, enforce char ceiling."""
    out = []
    for m in (history or [])[-MAX_HISTORY_TURNS:]:
        role = m.get("role"); content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if role == "assistant" and len(content) > ASSISTANT_TRUNC_CHARS:
            content = content[:ASSISTANT_TRUNC_CHARS] + " …"
        out.append({"role": role, "content": content})
    # must alternate and start with user for the Anthropic API
    while out and out[0]["role"] != "user":
        out.pop(0)
    clean = []
    for m in out:
        if clean and clean[-1]["role"] == m["role"]:
            clean[-1]["content"] += "\n\n" + m["content"]
        else:
            clean.append(m)
    if clean and clean[-1]["role"] != "assistant":
        clean.pop()
    while clean and sum(len(m["content"]) for m in clean) > MAX_HISTORY_CHARS:
        clean = clean[2:]
    return clean


def _needs_condense(q: str, history: list) -> bool:
    if not history:
        return False
    low = f" {q.lower()} "
    cues = (" it ", " that", " this", " those", " them ", " same", "what about", "and for", "how about",
            "you said", "you mean", "explain", "more on", "what if", " his ", " her ", " their ", " they ")
    return len(q.split()) < 12 or any(c in low for c in cues)


async def _condense_question(q: str, history: list) -> str:
    if not ANTHROPIC_API_KEY or not _needs_condense(q, history):
        return q
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": ASK_AI_MODEL, "max_tokens": 200, "temperature": 0,
                      "system": CONDENSE_SYSTEM,
                      "messages": history + [{"role": "user", "content": f"Latest user message:\n{q}"}]},
            )
            r.raise_for_status()
            text_out = "".join(b.get("text", "") for b in r.json().get("content", [])).strip().strip('"')
    except Exception:
        return q
    bad = (not text_out or len(text_out) > 600 or "\n" in text_out
           or text_out.lower().startswith(("sure", "here", "the user", "i ")))
    return q if bad else text_out


_NAME_STOP = {
    "what", "who", "how", "when", "where", "why", "did", "does", "do", "is", "are", "was", "were", "can",
    "could", "should", "which", "in", "the", "a", "an", "of", "on", "and", "or", "to", "for", "about",
    "matter", "re", "decision", "decisions", "case", "cases", "ruling", "holding", "held", "decide",
    "decided", "explain", "tell", "me", "summarize", "summary", "board", "balca", "aao", "perm", "uscis",
    "dol", "oflc", "ina", "cfr", "usc", "i", "en", "banc", "please", "under", "with", "that", "this",
    "these", "those", "there", "here", "it", "its", "their", "his", "her", "if", "as", "at", "by", "from",
    "into", "vs", "v", "versus", "court", "judge", "panel", "labor", "certification", "application",
    "employer", "alien", "petition", "appeal", "denial", "certified", "denied", "reversed", "affirmed",
}
_NAME_RE = re.compile(r"[A-Z][\w&'.\-]*(?:\s+(?:[A-Z][\w&'.\-]*|&|of|de|la|and)\b)*")


def _extract_names(q: str) -> list:
    """Likely case/party names: quoted phrases, then runs of Capitalized words minus question words."""
    out = []
    for m in re.finditer(r'["\u201c]([^"\u201d]{3,60})["\u201d]', q):
        out.append(m.group(1).strip())
    for m in _NAME_RE.finditer(q):
        words = [w for w in m.group(0).split() if w.lower().strip(".,") not in _NAME_STOP]
        phrase = " ".join(words).strip(" .,")
        if len(phrase) >= 4 and len(words) <= 5 and phrase.lower() not in {o.lower() for o in out}:
            out.append(phrase)
    return out[:3]


_LEXICAL_CORPORA = ("balca", "aao", "ina_cases", "govinfo", "court_opinions")
_AUTHORITY_CORPORA = ("regulation", "policy", "ina", "govinfo", "dol_faqs", "final_rules",
                      "form_instructions", "form_instructions_dol", "uscis_checklists", "cbp_ifm")

# Classification / form codes -> the words the authorities actually use. Embeddings
# conflate "E-3" with "EB-3"; the regulation text says "E classification", "treaty alien".
_CODE_EXPANSIONS = {
    "e-3":   "E-3 Australian specialty occupation treaty alien 8 CFR 214.2(e) LCA 20 CFR 655",
    "e-1":   "E-1 treaty trader 8 CFR 214.2(e)",
    "e-2":   "E-2 treaty investor 8 CFR 214.2(e)",
    "h-1b":  "H-1B specialty occupation 8 CFR 214.2(h) labor condition application 20 CFR 655",
    "h-1b1": "H-1B1 free trade Chile Singapore specialty occupation 8 CFR 214.2(h)",
    "h-2a":  "H-2A temporary agricultural worker 8 CFR 214.2(h) 20 CFR 655",
    "h-2b":  "H-2B temporary nonagricultural worker 8 CFR 214.2(h) 20 CFR 655",
    "h-3":   "H-3 trainee 8 CFR 214.2(h)",
    "l-1":   "L-1 intracompany transferee 8 CFR 214.2(l)",
    "l-1a":  "L-1A intracompany transferee managerial executive 8 CFR 214.2(l)",
    "l-1b":  "L-1B intracompany transferee specialized knowledge 8 CFR 214.2(l)",
    "o-1":   "O-1 extraordinary ability 8 CFR 214.2(o)",
    "p-1":   "P-1 athlete entertainer 8 CFR 214.2(p)",
    "tn":    "TN USMCA NAFTA professional 8 CFR 214.6",
    "j-1":   "J-1 exchange visitor 8 CFR 214.2(j) 22 CFR 62",
    "f-1":   "F-1 student 8 CFR 214.2(f) optional practical training",
    "opt":   "optional practical training F-1 8 CFR 214.2(f)",
    "stem opt": "STEM optional practical training extension 8 CFR 214.2(f)(10)",
    "eb-1":  "EB-1 first preference priority worker extraordinary ability outstanding researcher multinational manager 8 CFR 204.5",
    "eb-1a": "EB-1A extraordinary ability 8 CFR 204.5(h)",
    "eb-1b": "EB-1B outstanding professor researcher 8 CFR 204.5(i)",
    "eb-1c": "EB-1C multinational executive manager 8 CFR 204.5(j)",
    "eb-2":  "EB-2 advanced degree exceptional ability 8 CFR 204.5(k)",
    "niw":   "national interest waiver EB-2 Dhanasar 8 CFR 204.5(k)(4)",
    "eb-3":  "EB-3 skilled worker professional other worker 8 CFR 204.5(l)",
    "eb-5":  "EB-5 immigrant investor 8 CFR 204.6",
    "i-140": "Form I-140 immigrant petition for alien worker 8 CFR 204.5",
    "i-129": "Form I-129 petition for nonimmigrant worker 8 CFR 214.2",
    "i-485": "Form I-485 adjustment of status 8 CFR 245",
    "i-765": "Form I-765 employment authorization 8 CFR 274a.12",
    "i-539": "Form I-539 extension change of nonimmigrant status 8 CFR 214.1 248",
    "i-9":   "Form I-9 employment eligibility verification 8 CFR 274a.2",
    "perm":  "PERM permanent labor certification ETA-9089 20 CFR 656",
    "lca":   "labor condition application ETA-9035 20 CFR 655",
    "pwd":   "prevailing wage determination ETA-9141 20 CFR 656.40",
    "ead":   "employment authorization document 8 CFR 274a.12",
    "ac21":  "AC21 American Competitiveness in the Twenty-first Century Act portability 8 CFR 245.25 214.2(h)(13)",
}
_CODE_RE = re.compile(r"\b(?:[A-Z]{1,2}-\d[A-Z0-9]*|EB-?\d[A-C]?|I-\d{3}|TN|NIW|PERM|LCA|PWD|EAD|OPT|AC21|STEM OPT)\b", re.I)
_CFR_RE = re.compile(r"\b(?:\d+\s*CFR\s*(?:§\s*)?)?(\d{3}\.\d+(?:\([a-z0-9]+\))*)(?![\w.])", re.I)


def _expand_codes(q: str) -> tuple:
    """Return (expanded_query_text, [codes found], [cfr cites found])."""
    codes, cites, extra = [], [], []
    for m in _CODE_RE.finditer(q):
        c = m.group(0).lower()
        if c not in codes:
            codes.append(c)
            if c in _CODE_EXPANSIONS:
                extra.append(_CODE_EXPANSIONS[c])
    for m in _CFR_RE.finditer(q):
        cites.append(m.group(1))
    expanded = q if not extra else f"{q}\n({' ; '.join(extra)})"
    return expanded, codes, cites


async def _general_lexical(question: str, corpus_filter: list, k: int = 24, timeout: float = 2.0) -> list:
    """Plain keyword pass over the whole question (hybrid search). Catches lowercase terms of
    art ("substantial merit", "business necessity") that neither the name pass nor the code
    pass sees. Capped by a timeout so a very common word set can never stall the answer."""
    import asyncio
    words = re.findall(r"[A-Za-z][A-Za-z0-9.\-]{2,}", question)
    if len(words) < 2:
        return []
    async def run():
        return await database.fetch_all(text("""
            SELECT id, corpus, source_id, source_label, source_date, source_outcome, chunk_index,
                   chunk_text, cfr_citation, form_type,
                   ts_rank_cd(to_tsvector('english', chunk_text), websearch_to_tsquery('english', :q)) AS rank,
                   false AS label_hit
            FROM rag_chunks
            WHERE to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
            ORDER BY rank DESC LIMIT :k
        """).bindparams(q=question, k=k * 2))
    try:
        rows = await asyncio.wait_for(run(), timeout)
    except asyncio.TimeoutError:
        print("general lexical pass timed out; skipped")
        return []
    except Exception as e:
        print(f"general lexical pass failed: {e}")
        return []
    allowed = set(corpus_filter) if corpus_filter else None
    out = [("keywords", r) for r in rows if not allowed or r["corpus"] in allowed]
    return out[:k]


async def _authority_chunks(question: str, codes: list, cites: list, corpus_filter: list, k: int = 24) -> list:
    """FTS over the authority corpora (regs, policy, FAM, INA, FAQs, forms) for code/cite questions.
    Uses the partial index (corpus predicate inside), so the corpus filter is cheap here."""
    if not codes and not cites:
        return []
    corpora = [c for c in (corpus_filter or _AUTHORITY_CORPORA) if c in _AUTHORITY_CORPORA]
    if not corpora:
        return []
    # tsquery: (code | expansion words) & (question content words OR'd) — ts_rank_cd rewards
    # chunks that hit more of the question words. Built by hand: websearch_to_tsquery has
    # no grouping, so "a OR b c" would parse as a | (b & c).
    def lex(w):  # sanitize into a tsquery-safe quoted lexeme
        w = re.sub(r"[^A-Za-z0-9.\-()]", "", w)
        return f"'{w.lower()}'" if w else ""
    # Index side must stay selective: only the exact code / cite tokens. Expansion words and
    # question words go on the ranking side, OR'd. (OR-ing "specialty|occupation|labor" on the
    # left matched 300K regulation chunks and took ~100 s to rank.)
    left = [lex(c) for c in codes] + [lex(cite) for cite in cites]
    left = [x for x in left if x]
    exp_words = []
    for c in codes:
        exp_words += re.findall(r"[A-Za-z]{4,}", _CODE_EXPANSIONS.get(c, ""))[:6]
    qwords = [w for w in re.findall(r"[A-Za-z]{3,}", question.lower())
              if w not in _NAME_STOP and w not in ("get", "many", "much", "long", "does", "one", "have", "has")]
    right = [lex(w) for w in dict.fromkeys([*qwords, *[e.lower() for e in exp_words]])][:16]
    if not left:
        return []
    ts = "(" + " | ".join(left) + ")"
    if right:
        ts += " & (" + " | ".join(right) + ")"
    cin = ", ".join(f":c{i}" for i in range(len(corpora)))
    bind = {"q": ts, "k": k, **{f"c{i}": c for i, c in enumerate(corpora)}}
    import asyncio
    try:
        rows = await asyncio.wait_for(database.fetch_all(text(f"""
            SELECT id, corpus, source_id, source_label, source_date, source_outcome, chunk_index,
                   chunk_text, cfr_citation, form_type,
                   ts_rank_cd(to_tsvector('english', chunk_text), to_tsquery('english', :q)) AS rank,
                   false AS label_hit
            FROM rag_chunks
            WHERE corpus IN ({cin})
              AND to_tsvector('english', chunk_text) @@ to_tsquery('english', :q)
            ORDER BY rank DESC LIMIT :k
        """).bindparams(**bind)), 3.0)
    except asyncio.TimeoutError:
        print("authority retrieval timed out; skipped")
        return []
    except Exception as e:
        print(f"authority retrieval failed: {e}")
        return []
    return [(", ".join(codes + cites), r) for r in rows]

# Chunks most likely to state the holding/disposition of a decision.
_HOLDING_TSQ = "hold | held | holding | conclude | concludes | reverse | reversed | affirm | affirmed | order | ordered"


def _norm_entity(s: str) -> str:
    s = re.sub(r"[^\w\s]", " ", s or "")
    s = re.sub(r"\b(inc|llc|corp|corporation|co|ltd|lp|llp|plc|the|matter of|in re)\b", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip().lower()


async def _resolve_case(name: str) -> list:
    """entity_index lookup: returns [{corpus, source_id, name, alias, edate, outcome}] for a case name
    or docket/citation. Exact alias first, then normalized substring, then fuzzy."""
    n = _norm_entity(name)
    if len(n) < 3:
        return []
    rows = await database.fetch_all(text("""
        SELECT etype, name, alias, corpus, source_id, edate, outcome,
               CASE WHEN lower(alias) = lower(:raw) THEN 3
                    WHEN norm = :n THEN 2
                    WHEN norm LIKE :like THEN 1 ELSE 0 END AS score
        FROM entity_index
        WHERE etype = 'case' AND (lower(alias) = lower(:raw) OR norm = :n OR norm LIKE :like)
        ORDER BY score DESC, edate DESC NULLS LAST LIMIT 6
    """).bindparams(raw=name.strip(), n=n, like=f"%{n}%"))
    if not rows:
        rows = await database.fetch_all(text("""
            SELECT etype, name, alias, corpus, source_id, edate, outcome, 0 AS score
            FROM entity_index WHERE etype = 'case' AND similarity(norm, :n) > 0.55
            ORDER BY similarity(norm, :n) DESC LIMIT 4
        """).bindparams(n=n))
    return [dict(r) for r in rows]


async def _cfr_section_chunks(cites: list, question: str, corpus_filter: list, per_section: int = 10) -> list:
    """A cited CFR section is pulled directly (all its chunks, current edition) and pinned —
    like a named decision. '656.10(c)' -> section '656.10'; the title (20 CFR) is taken from the
    question when present, else all titles matching the section number are allowed."""
    if not cites or (corpus_filter and "regulation" not in corpus_filter):
        return []
    out = []
    for cite in cites[:3]:
        m = re.match(r"(\d{3}\.\d+)", cite)
        if not m:
            continue
        sec = m.group(1)
        tm = re.search(r"(\d+)\s*CFR\s*(?:§\s*)?" + re.escape(sec), question, re.I)
        title = tm.group(1) if tm else None
        sub = re.findall(r"\(([a-z0-9]+)\)", cite)
        bind = {"pat": (f"{title} CFR {sec}" if title else f"% CFR {sec}"), "n": per_section,
                "sub": f"%({sub[0]})%" if sub else "%"}
        rows = await database.fetch_all(text("""
            SELECT id, corpus, source_id, source_label, source_date, source_outcome, chunk_index,
                   chunk_text, cfr_citation, form_type, 0.9::float AS rank
            FROM rag_chunks
            WHERE corpus = 'regulation' AND cfr_citation LIKE :pat
            ORDER BY source_date DESC, (chunk_text LIKE :sub) DESC, chunk_index
            LIMIT :n
        """).bindparams(**bind))
        out.extend((cite, r, True) for r in rows)
    return out


async def _named_decision_chunks(phrases: list, corpus_filter: list, per_decision: int = 4) -> list:
    """Resolve case names via entity_index (any corpus) and return the decisions' OWN chunks,
    holding-bearing ones first. Also records unresolved/unchunked names in _last_coverage."""
    out = []
    notes = []
    for ph in phrases:
        hits = await _resolve_case(ph)
        chunked = [h for h in hits if h["corpus"] != "precedent_decisions"]
        if corpus_filter:
            chunked = [h for h in chunked if h["corpus"] in corpus_filter]
        if not chunked:
            known = [h for h in hits if h["corpus"] == "precedent_decisions"]
            if known:
                notes.append(f"{ph}: known precedent ({known[0]['name']}, {known[0]['alias']}) but its text is not in the corpus; "
                             f"rely on decisions that cite it.")
            else:
                notes.append(f"{ph}: no decision by that name is in the corpus (checked the entity index); "
                             f"rely on decisions that cite it, and say so.")
            continue
        for h in chunked[:2]:
            rows = await database.fetch_all(text("""
                SELECT id, corpus, source_id, source_label, source_date, source_outcome, chunk_index,
                       chunk_text, cfr_citation, form_type,
                       ts_rank_cd(to_tsvector('english', chunk_text), to_tsquery('english', :hq)) AS rank
                FROM rag_chunks
                WHERE corpus = :corpus AND source_id = :sid
                ORDER BY (chunk_index = 1) DESC, rank DESC, chunk_index DESC
                LIMIT :n
            """).bindparams(hq=_HOLDING_TSQ, corpus=h["corpus"], sid=str(h["source_id"]), n=per_decision))
            out.extend((ph, r, True) for r in rows)
    return out, notes


async def _lexical_chunks(phrases: list, corpus_filter: list, k: int = 6) -> list:
    """Phrase search over decision corpora; label matches first, then ts_rank, then recency."""
    if not phrases:
        return []
    corpora = [c for c in (corpus_filter or _LEXICAL_CORPORA) if c in _LEXICAL_CORPORA]
    if not corpora:
        return []
    seen, out = set(), []
    allowed = set(corpora)
    for ph in phrases:
        # No corpus predicate in SQL: combining it with the FTS index makes the planner
        # BitmapAnd a million-row corpus scan (~3 s). Over-fetch and filter here instead.
        import asyncio
        try:
            rows = await asyncio.wait_for(database.fetch_all(text("""
                SELECT id, corpus, source_id, source_label, source_date, source_outcome, chunk_index,
                       chunk_text, cfr_citation, form_type,
                       0.5::float AS rank,
                       (lower(source_label) LIKE :lbl) AS label_hit
                FROM rag_chunks
                WHERE to_tsvector('english', chunk_text) @@ phraseto_tsquery('english', :ph)
                ORDER BY label_hit DESC, source_date DESC NULLS LAST
                LIMIT :k
            """).bindparams(ph=ph, lbl=f"%{ph.lower()}%", k=k * 5)), 3.0)
        except asyncio.TimeoutError:
            print(f"citing-decisions pass timed out for {ph!r}; skipped")
            continue
        except Exception as e:
            print(f"lexical retrieval failed for {ph!r}: {e}")
            continue
        n = 0
        for r in rows:
            if r["id"] in seen or r["corpus"] not in allowed:
                continue
            seen.add(r["id"])
            out.append((ph, r))
            n += 1
            if n >= k:
                break
    return out


# ── Ranking: over-fetch, priors, per-source cap, Voyage rerank ───────────────
ASK_RERANK = os.environ.get("ASK_RERANK", "1") != "0"
RERANK_MODEL = os.environ.get("ASK_RERANK_MODEL", "rerank-2.5")
OVERFETCH = 4          # vector candidates = top_k * OVERFETCH
MAX_PER_SOURCE = 3

_INTENT = [   # (regex on the question, {corpus: prior})
    (re.compile(r"\b(perm|labor certification|9089|balca|656\.|prevailing wage|recruitment|audit|"
                r"supervised recruitment|business necessity|actual minimum|certifying officer|\bco\b)", re.I),
     {"balca": 0.06, "regulation": 0.02}),
    (re.compile(r"\b(aao|i-140|i-129|eb-?[123]|niw|national interest|extraordinary ability|outstanding "
                r"(?:professor|researcher)|multinational|specialty occupation|l-1|o-1|adjustment|i-485|"
                r"dhanasar|kazarian|petitioner|beneficiary)", re.I),
     {"aao": 0.06}),
    (re.compile(r"\b(cfr|§|regulation|regulatory|rule|final rule|statute|ina §|8 u\.?s\.?c)", re.I),
     {"regulation": 0.05, "govinfo": 0.03, "ina": 0.03}),
    (re.compile(r"\b(policy manual|fam\b|foreign affairs manual|uscis policy|adjudicator)", re.I),
     {"policy": 0.06}),
    (re.compile(r"\b(?:[A-Z]{1,2}-\d[A-Z0-9]*|TN|EAD|OPT)\b", re.I),      # nonimmigrant/form codes
     {"regulation": 0.08, "policy": 0.06, "dol_faqs": 0.03, "form_instructions": 0.03}),
    (re.compile(r"\b(how (?:many|long)|years?|months?|period of (?:admission|stay)|validity|valid for|"
                r"duration|maximum (?:stay|period)|increments?|extension|renew)", re.I),
     {"regulation": 0.06, "policy": 0.05}),
]
_BOILERPLATE = re.compile(
    r"^\s*(u\.s\. (department of labor|citizenship and immigration services)|non-precedent decision|"
    r"administrative appeals office|board of alien labor certification appeals|in re:|matter of:|"
    r"cite as|notice:|issued:|date:|before:|appearances:|800 k street)", re.I)


def _corpus_priors(question: str) -> dict:
    pri = {"balca": 0.02}          # Casebase is PERM-first; mild default lean
    for rx, boosts in _INTENT:
        if rx.search(question):
            for c, b in boosts.items():
                pri[c] = max(pri.get(c, 0), b)
    return pri


def _chunk_prior(c: dict, pri: dict) -> float:
    p = pri.get(c["corpus"], 0.0)
    head = (c["chunk_text"] or "")[:200]
    if _BOILERPLATE.search(head) or c.get("chunk_index") == 0:
        p -= 0.12           # caption/header chunks: cite nothing useful
    return p


async def _voyage_rerank(question: str, cands: list) -> list:
    """Return relevance scores aligned to cands, or None if unavailable."""
    if not ASK_RERANK or not cands:
        return None
    try:
        import voyageai
        vo = voyageai.Client(api_key=os.environ.get("VOYAGE_API_KEY"))
        docs = [(c["chunk_text"] or "")[:2000] for c in cands]
        import asyncio
        res = await asyncio.to_thread(vo.rerank, question, docs, model=RERANK_MODEL, top_k=len(docs))
        scores = [0.0] * len(cands)
        for r in res.results:
            scores[r.index] = float(r.relevance_score)
        return scores
    except Exception as e:
        print(f"rerank unavailable: {e}")
        return None


async def _rank_chunks(question: str, vec: list, lexical: list, top_k: int, plan_corpora: list = None) -> list:
    """vec: vector candidates (dicts, have similarity). lexical: (phrase, row, is_own).
    Returns ordered list of dicts, 'decision' (own) chunks first, then reranked pool."""
    pri = _corpus_priors(question)
    for i, c in enumerate(plan_corpora or []):          # planner's ranked corpora outrank regex intents
        pri[c] = max(pri.get(c, 0), (0.07, 0.05, 0.03)[i] if i < 3 else 0.02)
    pinned, pool, seen = [], [], set()
    for ph, r, is_own in lexical:
        d = dict(r)
        rk = d.get("rank")
        d = d | {"match_type": "decision" if is_own else "keyword", "match_phrase": ph,
                 "similarity": min(1.0, float(rk) if rk else 0.0)}
        if d["id"] in seen:
            continue
        seen.add(d["id"])
        (pinned if is_own else pool).append(d)
    for c in vec:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        pool.append(dict(c) | {"match_type": "semantic"})

    scores = await _voyage_rerank(question, pool)
    for i, c in enumerate(pool):
        base = scores[i] if scores else float(c.get("similarity") or 0.0)
        c["rank_score"] = base + _chunk_prior(c, pri)
        c["rerank_score"] = scores[i] if scores else None
    pool.sort(key=lambda c: c["rank_score"], reverse=True)

    out, per_src = list(pinned), {}
    for c in pool:
        k = (c["corpus"], c["source_id"])
        if per_src.get(k, 0) >= MAX_PER_SOURCE:
            continue
        per_src[k] = per_src.get(k, 0) + 1
        out.append(c)
        if len(out) >= top_k + len(pinned):
            break
    return out


# ── Query understanding (planner) ─────────────────────────────────────────────
PLAN_SYSTEM = """You are the query-understanding step of an immigration-law research assistant whose
corpus holds: BALCA decisions (PERM era 2006-present as 'balca'; 1977-2009 INA-era as 'ina_cases'),
AAO non-precedent decisions ('aao'), 8/20/22 CFR ('regulation'), USCIS Policy Manual + FAM ('policy'),
the INA ('ina'), DOL FAQs ('dol_faqs'), Federal Register final rules ('final_rules'), form instructions
('form_instructions'), USCIS FOIA reading-room documents ('uscis_foia'); plus live DOL disclosure data
(PERM/LCA/PWD filings, who represents whom, processing times) and the visa bulletin via tools.

Given the conversation and the latest user message, return ONLY a JSON object:
{
 "standalone": "the latest message rewritten as one self-contained question (keep it unchanged if it already is; carry over employer names, visa categories, cases, sections from earlier turns; if the message asks about something the assistant just said, make that explicit)",
 "question_type": one of "case_holding" | "rule" | "procedure" | "statistic" | "representation" | "comparison" | "definition" | "other",
 "entities": [ {"text": "as written", "type": one of "case" | "employer" | "law_firm" | "attorney" | "classification" | "cfr" | "ina" | "form" | "term"} ],
 "corpora": ["ordered list of the 1-3 corpora most likely to hold the answer, from the names above"],
 "rewrites": ["2-4 alternative phrasings using the vocabulary the target authorities actually use (regulations say 'treaty alien', 'E classification', 'specialty occupation', 'period of admission'; BALCA says 'Certifying Officer', 'actual minimum requirements'; AAO says 'petitioner', 'beneficiary', 'preponderance'); include the governing section number when you know it, e.g. '8 CFR 214.2(e)(20)'"],
 "tools": ["any of get_employer_representation, get_firm_clients, query_oflc_data, get_dol_processing_times, get_visa_bulletin_current, search_decisions, search_regulations that MUST run for this question; empty if none"]
}
Rules: a question naming a law firm or attorney's clients/filings needs get_firm_clients; naming an
employer's counsel needs get_employer_representation; volumes/rates/wages need query_oflc_data;
'how long are X taking' needs get_dol_processing_times; priority dates need get_visa_bulletin_current.
A named decision is a "case" entity even if you know it well. Keep JSON compact. No commentary."""


async def _plan_question(q: str, history: list) -> dict:
    """One haiku call: standalone rewrite + entities + corpora + rewrites + required tools."""
    fallback = {"standalone": q, "question_type": "other", "entities": [], "corpora": [], "rewrites": [], "tools": []}
    if not ANTHROPIC_API_KEY:
        return fallback
    try:
        async with httpx.AsyncClient(timeout=25.0) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": ASK_AI_MODEL, "max_tokens": 600, "temperature": 0,
                      "system": PLAN_SYSTEM,
                      "messages": history + [{"role": "user", "content": f"Latest user message:\n{q}"}]},
            )
            r.raise_for_status()
            txt = "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
            txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
            plan = json.loads(txt)
    except Exception as e:
        print(f"planner failed: {e}")
        return fallback
    out = dict(fallback)
    sa = (plan.get("standalone") or "").strip()
    out["standalone"] = sa if sa and len(sa) < 600 and "\n" not in sa else q
    out["question_type"] = plan.get("question_type") or "other"
    out["entities"] = [e for e in (plan.get("entities") or []) if isinstance(e, dict) and e.get("text")][:8]
    out["corpora"] = [c for c in (plan.get("corpora") or []) if isinstance(c, str)][:3]
    out["rewrites"] = [w for w in (plan.get("rewrites") or []) if isinstance(w, str) and 8 < len(w) < 400][:4]
    out["tools"] = [t for t in (plan.get("tools") or []) if isinstance(t, str)][:4]
    return out


VERIFY_SYSTEM = """You check whether retrieved passages can answer a legal research question. Reply ONLY with JSON:
{"sufficient": true|false, "reason": "one sentence", "retry_query": "if insufficient: a better search phrased in the words the governing authority would use, naming the section or decision if you know it; else null"}
"sufficient" means at least one passage states the rule/holding/fact asked about (not merely the same topic).
Questions answered by tools (filing statistics, who represents whom, processing times, priority dates) count as sufficient."""


async def _verify_sources(question: str, chunks: list) -> dict:
    if not ANTHROPIC_API_KEY or not chunks:
        return {"sufficient": True}
    listing = "\n\n".join(
        f"[{i+1}] {c['corpus']}: {c['source_label']} {c.get('cfr_citation') or ''}\n{(c['chunk_text'] or '')[:350]}"
        for i, c in enumerate(chunks[:12]))
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": ASK_AI_MODEL, "max_tokens": 200, "temperature": 0, "system": VERIFY_SYSTEM,
                      "messages": [{"role": "user", "content": f"Question: {question}\n\nPassages:\n{listing}"}]},
            )
            r.raise_for_status()
            txt = "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
            txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
            v = json.loads(txt)
            return {"sufficient": bool(v.get("sufficient", True)), "reason": v.get("reason"),
                    "retry_query": v.get("retry_query")}
    except Exception as e:
        print(f"verify failed: {e}")
        return {"sufficient": True}


async def _vector_chunks(q_text: str, corpus_filter: list, k: int) -> list:
    """Embed (with code expansion) and fetch top-k by cosine."""
    embed_text, _, _ = _expand_codes(q_text)
    q_vec = await embed_query(embed_text)
    q_vec_str = "[" + ",".join(f"{v:.6f}" for v in q_vec) + "]"
    corpus_where, bind = "", {"k": k}
    if corpus_filter:
        placeholders = ", ".join(f":c{i}" for i in range(len(corpus_filter)))
        corpus_where = f"WHERE corpus IN ({placeholders})"
        for i, c in enumerate(corpus_filter):
            bind[f"c{i}"] = c
    rows = await database.fetch_all(text(f"""
        SELECT id, corpus, source_id, source_label, source_date,
               source_outcome, chunk_index, chunk_text, cfr_citation, form_type,
               1 - (embedding <=> '{q_vec_str}'::vector) AS similarity
        FROM rag_chunks
        {corpus_where}
        ORDER BY embedding <=> '{q_vec_str}'::vector
        LIMIT :k
    """).bindparams(**bind))
    return [dict(r) for r in rows]


async def _retrieve(search_q: str, plan: dict, corpus_filter: list, top_k: int) -> list:
    """Fan-out retrieval driven by the plan, then rerank. Regex passes remain as a floor."""
    import asyncio
    # a) vector: standalone + rewrites (multi-query), union keeping best similarity
    queries = [search_q] + [w for w in plan.get("rewrites", []) if w.lower() != search_q.lower()]
    vec, best = [], {}
    for i, qq in enumerate(queries[:4]):          # sequential: the local embedder is not re-entrant
        try:
            lst = await _vector_chunks(qq, corpus_filter, top_k * (OVERFETCH if i == 0 else 2))
        except Exception as e:
            print(f"vector query failed: {e}")
            continue
        for c in lst:
            if c["id"] not in best or c["similarity"] > best[c["id"]]["similarity"]:
                best[c["id"]] = c
    vec = sorted(best.values(), key=lambda c: c["similarity"], reverse=True)

    # b) entity paths
    ents = plan.get("entities", [])
    names = [e["text"] for e in ents if e.get("type") == "case"] or _extract_names(search_q)
    codes = [e["text"].lower() for e in ents if e.get("type") in ("classification", "form")]
    cites = [e["text"] for e in ents if e.get("type") in ("cfr", "ina")]
    terms = [e["text"] for e in ents if e.get("type") == "term"]
    _, rx_codes, rx_cites = _expand_codes(search_q)
    codes = list(dict.fromkeys(codes + rx_codes)); cites = list(dict.fromkeys(cites + rx_cites))

    own, coverage = await _named_decision_chunks(names, corpus_filter)
    plan["coverage"] = coverage
    own += await _cfr_section_chunks(cites, search_q, corpus_filter)
    cite_rows = await _lexical_chunks(names, corpus_filter)
    auth = await _authority_chunks(search_q, codes, cites, corpus_filter)
    kw = await _general_lexical(search_q, corpus_filter)
    term_rows = []
    for t in terms[:3]:
        term_rows += await _general_lexical(f'"{t}" {search_q}', corpus_filter, k=12)
    for w in plan.get("rewrites", [])[:2]:          # rewrites also get a keyword pass (cheap, capped)
        kw += await _general_lexical(w, corpus_filter, k=12, timeout=1.5)
    lexical = own + [(ph, r, False) for ph, r in cite_rows + auth + kw + term_rows]
    return await _rank_chunks(search_q, vec, lexical, top_k, plan_corpora=plan.get("corpora", []))


async def _log_turn(row: dict) -> None:
    try:
        await database.execute(text("""
            INSERT INTO ask_chat_log
              (conversation_id, turn_index, raw_question, condensed_question, condense_ms,
               corpus_filter, chunk_ids, retrieve_ms, tool_calls, answer, model, rounds, generate_ms, error,
               plan, verify)
            VALUES (CAST(:conversation_id AS uuid), :turn_index, :raw_question, :condensed_question, :condense_ms,
               :corpus_filter, :chunk_ids, :retrieve_ms, CAST(:tool_calls AS jsonb), :answer, :model,
               :rounds, :generate_ms, :error, CAST(:plan AS jsonb), CAST(:verify AS jsonb))
        """).bindparams(**row))
    except Exception as e:  # logging must never break the answer
        print(f"ask_chat_log insert failed: {e}")

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
        "corpus_filter": ["balca","aao","regulation","policy","govinfo"],  // optional
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
    history    = _trim_history(body.get("history") or [])   # prior turns, oldest first
    conversation_id = body.get("conversation_id") or None
    turn_index = sum(1 for m in (body.get("history") or []) if m.get("role") == "user") + 1

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    log = {"conversation_id": conversation_id, "turn_index": turn_index, "raw_question": question,
           "condensed_question": None, "condense_ms": None, "corpus_filter": corpus_filter or None,
           "chunk_ids": None, "retrieve_ms": None, "tool_calls": "[]", "answer": None,
           "model": ASK_AI_MODEL if ANTHROPIC_API_KEY else OLLAMA_CHAT_MODEL, "rounds": 0,
           "generate_ms": None, "error": None, "plan": None, "verify": None}

    # 0. Understand the question: standalone rewrite, entities, target corpora, rewrites, tools
    _t0 = _time.monotonic()
    plan = await _plan_question(question, history)
    search_q = plan["standalone"]
    log["condense_ms"] = int((_time.monotonic() - _t0) * 1000)
    log["condensed_question"] = search_q
    log["plan"] = json.dumps(plan)

    # 1-2. Retrieve: multi-query vector + entity paths + keyword passes, reranked
    _t0 = _time.monotonic()
    try:
        chunks = await _retrieve(search_q, plan, corpus_filter, top_k)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Retrieval failed: {e}")

    # 2c. Verify the sources can answer; one more targeted round if not.
    verify = {"sufficient": True}
    if plan.get("question_type") not in ("statistic", "representation") and not plan.get("tools"):
        verify = await _verify_sources(search_q, chunks)
        if not verify.get("sufficient") and verify.get("retry_query"):
            rq = verify["retry_query"]
            try:
                extra_vec = await _vector_chunks(rq, corpus_filter, top_k * 2)
                extra_kw = await _general_lexical(rq, corpus_filter, k=16)
                _, rc, rcite = _expand_codes(rq)
                extra_auth = await _authority_chunks(rq, rc, rcite, corpus_filter)
                have = {c["id"] for c in chunks}
                pool_vec = [dict(c) | {"match_type": c.get("match_type", "semantic")} for c in chunks if c.get("match_type") != "decision"] + \
                           [c for c in extra_vec if c["id"] not in have]
                pinned_own = [(c.get("match_phrase"), c, True) for c in chunks if c.get("match_type") == "decision"]
                merged = await _rank_chunks(search_q, pool_vec, pinned_own + [(ph, r, False) for ph, r in extra_kw + extra_auth],
                                            top_k, plan_corpora=plan.get("corpora", []))
                chunks = merged
            except Exception as e:
                print(f"retry retrieval failed: {e}")
    log["retrieve_ms"] = int((_time.monotonic() - _t0) * 1000)
    log["chunk_ids"] = [int(c["id"]) for c in chunks]
    log["model"] = f"{log['model']} | rerank={RERANK_MODEL if ASK_RERANK else 'off'}"
    log["verify"] = json.dumps(verify)

    if not chunks:
        async def no_results():
            yield json.dumps({"type": "condensed", "query": search_q}) + "\n"
            yield json.dumps({"type": "sources", "sources": []}) + "\n"
            await _log_turn({**log, "answer": "(no results)"})
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
            "match_type":   chunk.get("match_type", "semantic") if isinstance(chunk, dict) else "semantic",
            "is_new_source": is_new_source,
            "excerpt":      chunk["chunk_text"],
        }
        sources.append(source)

        # Build context snippet for the prompt
        meta_parts = [f"[{ref_num}] {label}: {chunk['source_label']}"]
        if isinstance(chunk, dict) and chunk.get("match_type") == "decision" and chunk["corpus"] == "regulation":
            meta_parts.append(f"(THIS IS the text of {chunk.get('match_phrase')} itself)")
        elif isinstance(chunk, dict) and chunk.get("match_type") == "decision":
            meta_parts.append(f"(THIS IS the {chunk.get('match_phrase')} decision itself)")
        elif isinstance(chunk, dict) and chunk.get("match_type") == "keyword" and chunk.get("match_phrase") not in ("keywords", None) \
                and chunk["corpus"] in _LEXICAL_CORPORA:
            meta_parts.append(f"(a later decision that cites/discusses {chunk.get('match_phrase')})")
        if chunk["source_date"]:
            meta_parts.append(f"Date: {chunk['source_date']}")
        if chunk["source_outcome"]:
            meta_parts.append(f"Outcome: {chunk['source_outcome']}")
        if chunk["cfr_citation"]:
            meta_parts.append(f"Citation: {chunk['cfr_citation']}")

        context_parts.append("\n".join(meta_parts) + "\n" + chunk["chunk_text"])

    context_block = "\n\n---\n\n".join(context_parts)

    # 4. Synthesize a cited answer — prefer Anthropic Claude, fall back to local Ollama
    system_prompt = f"""Today's date is {_date.today().strftime('%A, %B %d, %Y')}. Treat "now", "current", "recent", and "this year" relative to that date; disclosure data and decisions in the corpus run through mid-2026.

You are a legal AI assistant specializing in PERM labor certification and U.S. immigration law.
You are given retrieved excerpts from BALCA decisions, AAO decisions, federal regulations (CFR), GovInfo federal legal materials, and USCIS/FAM policy manuals.
Follow all formatting instructions exactly. Be concise and precise.
Answer the question accurately using ONLY the provided sources and your tool results.

Rules:
- Cite every factual claim with the source reference number in brackets, e.g. [3] or [1][4].
- When citing a regulation, include the CFR citation if available (e.g., 20 CFR § 656.17).
- When citing a case decision, include the case label and outcome where relevant.
- If sources conflict, note the conflict and explain which is more authoritative (statutes/public laws > regulations > policy > case decisions).
- If neither the sources nor your tools can answer, say so clearly — do not speculate. Never conclude information is unavailable until you have tried the relevant tool.
- Write in plain legal English. Be precise but readable.
- Corpus coverage: BALCA decisions from April 2006 forward (PERM era); AAO non-precedent
  decisions; pre-2006 BALCA precedents (e.g. the 1989 en banc decisions) are NOT in the
  corpus as source documents, but later decisions that cite them ARE. When asked about a
  decision you cannot find as a source, look for later decisions that discuss it (use the
  search_decisions tool), state what they say it held, and say plainly that the original
  is not in the corpus. Never answer "I don't know" about a well-known case without
  first calling search_decisions.
- For questions about a visa classification, form, period of stay, validity, filing
  procedure, or what a regulation says, if the retrieved sources do not contain the
  answer, call search_regulations (it covers 8 CFR, 20 CFR, 22 CFR, the INA, the USCIS
  Policy Manual, the FAM, DOL FAQs, and form instructions) BEFORE saying the answer is
  unavailable. Never answer "I don't have sources" for a basic immigration-rule question
  without having tried it.
- Structure longer answers with short paragraphs. Do not use bullet points unless listing distinct requirements.

You also have tools for live DOL performance data: employer representation
(which law firm/attorney is of record on an employer's PERM/LCA/PWD filings —
use get_employer_representation for any "who represents X" question, and
get_firm_clients for "who does firm Y represent"), OFLC disclosure aggregates
and individual filing records (PERM/LCA/PW, FY2020-FY2026), DOL
processing-time percentiles, and the visa bulletin currently in force.
When reporting representation, state the current counsel first (most recent
filings), then note prior firms and when the change happened, and give the
filing counts by program.
Use tools PROACTIVELY and WITHOUT asking permission — never ask "Would you
like me to query…"; just query. Do not narrate what you are about to do
("I'll query…", "Let me search…", "I'll look up…") — call the tool silently
and begin the answer with the substance. A conversation may change topic
between turns; answer the current question on its own terms and never
remark on the switch or on what the earlier turns were about. Any question about specific employers,
attorneys or law firms, filing volumes, approval/denial rates, wages,
occupations, worksites, processing times, or priority dates is a data
question: answer it from the tools, not the text sources. The retrieved
text excerpts are usually irrelevant to data questions — do not lead with
an explanation of why the sources don't answer; go straight to the tool.
When you state numbers from a tool result, attribute them in prose (e.g.
"per OFLC disclosure data, FY2020-FY2026") instead of [N] citations; reserve
[N] citations for the text sources. If a tool returns an error or empty
result after reasonable retries, say the data is unavailable rather than
guessing."""

    plan_hint = ""
    if plan.get("tools"):
        plan_hint += f"\nRequired tools for this question (call them before answering): {', '.join(plan['tools'])}."
    if plan.get("entities"):
        plan_hint += "\nEntities in the question: " + "; ".join(f"{e['text']} ({e.get('type')})" for e in plan["entities"]) + "."
    if plan.get("coverage"):
        plan_hint += "\nCoverage: " + " ".join(plan["coverage"])
    if not verify.get("sufficient"):
        plan_hint += f"\nNote: an automated check judged the sources thin ({verify.get('reason')}). Use search_regulations / search_decisions before concluding the answer is unavailable."
    user_prompt = f"""Sources:

{context_block}

---

Question: {question}""" + (f"""
(Standalone form of the question, for context: {search_q})""" if search_q != question else "") + plan_hint + """

Answer (cite sources with [N] notation):"""

    # 5. Stream the response — use Anthropic if key is set, otherwise local Ollama
    async def generate():
        answer_parts: list = []
        tool_log: list = []
        gen_t0 = _time.monotonic()
        yield json.dumps({"type": "condensed", "query": search_q}) + "\n"
        yield json.dumps({"type": "plan", "question_type": plan.get("question_type"), "entities": plan.get("entities"),
                          "corpora": plan.get("corpora"), "tools": plan.get("tools"),
                          "verified": verify.get("sufficient", True), "verify_reason": verify.get("reason")}) + "\n"
        # Emit the sources metadata
        yield json.dumps({"type": "sources", "sources": sources}) + "\n"

        try:
          if ANTHROPIC_API_KEY:
            # ── Anthropic Claude with tool use (agentic loop) ─────────────────
            tools = build_tools_schema()
            messages = history + [{"role": "user", "content": user_prompt}]
            tool_display = {
                "search_decisions": "Looking up the decision…",
                "search_regulations": "Searching the regulations and policy manuals…",
                "get_employer_representation": "Looking up employer representation…",
                "get_firm_clients": "Looking up the firm's clients…",
                "query_oflc_data": "Querying OFLC disclosure data…",
                "get_dol_processing_times": "Checking DOL processing times…",
                "get_visa_bulletin_current": "Checking the visa bulletin…",
            }

            async with httpx.AsyncClient(timeout=120.0) as http_client:
                for _round in range(5):
                    blocks = []          # finalized content blocks this round
                    cur = None           # block under construction
                    cur_json = ""        # accumulating tool_use input JSON
                    stop_reason = None

                    async with http_client.stream(
                        "POST",
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": ANTHROPIC_API_KEY,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": ASK_AI_MODEL,
                            "max_tokens": 2000,
                            "stream": True,
                            "system": system_prompt,
                            "tools": tools,
                            "messages": messages,
                        },
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data_str = line[5:].strip()
                            if not data_str or data_str == "[DONE]":
                                continue
                            try:
                                event = json.loads(data_str)
                            except Exception:
                                continue
                            etype = event.get("type")
                            if etype == "content_block_start":
                                cb = event.get("content_block", {})
                                if cb.get("type") == "tool_use":
                                    cur = {"type": "tool_use", "id": cb["id"], "name": cb["name"], "input": {}}
                                    cur_json = ""
                                else:
                                    cur = {"type": "text", "text": ""}
                            elif etype == "content_block_delta":
                                delta = event.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    if cur is not None and cur.get("type") == "text":
                                        cur["text"] += delta["text"]
                                    answer_parts.append(delta["text"])
                                    yield json.dumps({"type": "token", "text": delta["text"]}) + "\n"
                                elif delta.get("type") == "input_json_delta":
                                    cur_json += delta.get("partial_json", "")
                            elif etype == "content_block_stop":
                                if cur is not None:
                                    if cur.get("type") == "tool_use":
                                        try:
                                            cur["input"] = json.loads(cur_json) if cur_json.strip() else {}
                                        except Exception:
                                            cur["input"] = {}
                                    blocks.append(cur)
                                    cur = None
                            elif etype == "message_delta":
                                stop_reason = event.get("delta", {}).get("stop_reason") or stop_reason

                    log["rounds"] = _round + 1
                    if stop_reason != "tool_use":
                        break

                    # Execute requested tools, then continue the loop
                    messages.append({"role": "assistant", "content": blocks})
                    tool_results = []
                    for b in blocks:
                        if b.get("type") != "tool_use":
                            continue
                        yield json.dumps({
                            "type": "status",
                            "text": tool_display.get(b["name"], f"Running {b['name']}…"),
                        }) + "\n"
                        _tt = _time.monotonic()
                        result = await execute_ask_tool(b["name"], b.get("input") or {})
                        tool_log.append({"name": b["name"], "input": b.get("input") or {},
                                         "result_chars": len(result),
                                         "ms": int((_time.monotonic() - _tt) * 1000)})
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": b["id"],
                            "content": result,
                        })
                    messages.append({"role": "user", "content": tool_results})
          else:
            # ── Local Ollama mistral:7b-instruct (fallback) ───────────────────
            payload = _json.dumps({
                "model": OLLAMA_CHAT_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    *history,
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
                                answer_parts.append(token)
                                yield json.dumps({"type": "token", "text": token}) + "\n"
                            if event.get("done"):
                                break
                        except Exception:
                            continue

        except Exception as e:
            log["error"] = f"{type(e).__name__}: {e}"[:500]
            yield json.dumps({"type": "error", "message": "The answer could not be completed. Please try again."}) + "\n"

        log["answer"] = "".join(answer_parts) or None
        log["tool_calls"] = json.dumps(tool_log, default=str)
        log["generate_ms"] = int((_time.monotonic() - gen_t0) * 1000)
        await _log_turn(log)
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
