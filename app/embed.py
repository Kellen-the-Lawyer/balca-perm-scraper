"""
app/embed.py — Unified embedding module for Casebase
=====================================================

Two embedding paths, both via Voyage API:

  embed_documents(texts)  — voyage-4-large, for ingestion.
                            One-time cost per document. Batched.

  embed_query(text)       — voyage-4-lite, for query-time embedding.
                            $0.02/MTok — effectively free at search volume.

Both use the Voyage 4 shared embedding space, so document vectors and query
vectors are directly comparable in pgvector. Both output 1024-dim floats.

Environment variables:
    VOYAGE_API_KEY       Required for both functions
    VOYAGE_DOC_MODEL     Default: voyage-4-large
    VOYAGE_QUERY_MODEL   Default: voyage-4-lite
    EMBED_DIM            Output dimensions (default: 1024)
    VOYAGE_BATCH_SIZE    Batch size for embed_documents (default: 128)

Usage (ingest scripts):
    from app.embed import embed_documents
    vecs = embed_documents(chunk_texts)   # list of 1024-dim lists

Usage (query path / core.py):
    from app.embed import embed_query
    vec = await embed_query(query_text)   # 1024-dim list
"""

import os
import time
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_env_path = Path(__file__).parents[1] / ".env"
load_dotenv(_env_path)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VOYAGE_API_KEY    = os.environ.get("VOYAGE_API_KEY", "")
VOYAGE_DOC_MODEL  = os.environ.get("VOYAGE_DOC_MODEL", "voyage-4-large")
VOYAGE_QUERY_MODEL = os.environ.get("VOYAGE_QUERY_MODEL", "voyage-4-lite")  # API fallback only
VOYAGE_NANO_HF_ID  = os.environ.get("VOYAGE_NANO_MODEL_ID", "voyageai/voyage-4-nano")
EMBED_DIM         = int(os.environ.get("EMBED_DIM", "1024"))
_MAX_RETRIES      = 5
_RETRY_DELAYS     = [1, 2, 5, 10, 30]
# Voyage hard limit: 120K tokens/batch, 1000 texts/batch.
# AAO chunks can be ~10K tokens each so we cap at 10 chunks/batch to stay safe.
# Shorter-chunk corpora will naturally batch faster since the re-embed script
# feeds 128 chunks at a time and _voyage_embed splits them here.
_MAX_CHARS_BATCH  = 160_000   # ~40K tokens at chars/4 — safe ceiling for dense legal text
_MAX_CHUNKS_BATCH = 25        # Hard count cap


def _char_safe_batches(texts: list[str]) -> list[list[str]]:
    """
    Split texts into batches capped by character count and chunk count.
    chars/4 underestimates Voyage tokens by ~30% on legal text, so we
    target 280K chars (~70K tokens) to stay well under the 120K limit.
    """
    batches, current, current_chars = [], [], 0
    for t in texts:
        chars = len(t)
        if current and (current_chars + chars > _MAX_CHARS_BATCH or len(current) >= _MAX_CHUNKS_BATCH):
            batches.append(current)
            current, current_chars = [], 0
        current.append(t)
        current_chars += chars
    if current:
        batches.append(current)
    return batches


# ---------------------------------------------------------------------------
# Internal: shared Voyage API call with retry/backoff
# ---------------------------------------------------------------------------

def _voyage_embed(texts: list[str], model: str, input_type: str) -> list[list[float]]:
    """Call Voyage embed endpoint with token-aware batching and retry."""
    if not VOYAGE_API_KEY:
        raise RuntimeError("VOYAGE_API_KEY is not set. Add it to .env.")
    if not texts:
        return []

    try:
        import voyageai
    except ImportError as exc:
        raise ImportError(
            "voyageai package is required. Install: pip install voyageai"
        ) from exc

    client = voyageai.Client(api_key=VOYAGE_API_KEY)
    all_vectors = []

    for batch in _char_safe_batches(texts):
        for attempt in range(_MAX_RETRIES):
            try:
                result = client.embed(
                    batch,
                    model=model,
                    input_type=input_type,
                    output_dimension=EMBED_DIM,
                )
                all_vectors.extend(result.embeddings)
                break
            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = "429" in err_str or "rate" in err_str
                is_last = attempt == _MAX_RETRIES - 1
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                if is_last:
                    raise RuntimeError(
                        f"Voyage API failed after {_MAX_RETRIES} attempts: {e}"
                    ) from e
                wait = delay * 2 if is_rate_limit else delay
                log.warning(f"Voyage API error (attempt {attempt+1}), retrying in {wait}s: {e}")
                time.sleep(wait)

    return [v[:EMBED_DIM] for v in all_vectors]


# ---------------------------------------------------------------------------
# embed_documents() — voyage-4-large, for ingestion
# ---------------------------------------------------------------------------

def embed_documents(texts: list[str], model: Optional[str] = None) -> list[list[float]]:
    """
    Embed document chunks for ingestion using voyage-4-large.
    Called once per document at ingest time.
    """
    return _voyage_embed(texts, model or VOYAGE_DOC_MODEL, "document")


# ---------------------------------------------------------------------------
# embed_query() — voyage-4-lite, for search
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Auto-patch for voyage-4-nano HuggingFace modeling file
# create_causal_mask() in current transformers doesn't accept cache_position.
# This patch is applied on import so it survives cache clears.
# ---------------------------------------------------------------------------

def _patch_nano_modeling():
    import glob
    pattern = (
        str(Path.home() /
        ".cache/huggingface/modules/transformers_modules/voyageai"
        "/voyage_hyphen_4_hyphen_nano/*/modeling_qwen3_bidirectional.py")
    )
    for fpath in glob.glob(pattern):
        txt = open(fpath).read()
        changed = False
        # Patch 1: create_causal_mask() no longer accepts cache_position
        if "cache_position=dummy_cache_position," in txt:
            needle = '                cache_position=dummy_cache_position,\n'
            txt = txt.replace(needle, '')
            changed = True
        # Patch 2 (transformers 5.x): AutoModel.register() reads
        # model_class.config_class.__name__ unguarded; remote code never
        # sets config_class, so the inherited None raises AttributeError.
        if "config_class = Qwen3Config" not in txt:
            txt = txt.replace(
                "from transformers import PreTrainedModel, Qwen3Model",
                "from transformers import PreTrainedModel, Qwen3Model, Qwen3Config")
            txt = txt.replace(
                "class Qwen3BidirectionalModel(PreTrainedModel):\n",
                "class Qwen3BidirectionalModel(PreTrainedModel):\n"
                "    config_class = Qwen3Config\n")
            changed = True
        if changed:
            open(fpath, "w").write(txt)
            log.info(f"Auto-patched {fpath}")

_patch_nano_modeling()

# Lazy singleton for local nano model
import threading
_nano_model = None
_nano_lock = threading.Lock()

def _load_nano():
    global _nano_model
    if _nano_model is not None:
        return _nano_model
    with _nano_lock:
        if _nano_model is not None:   # another thread won the race
            return _nano_model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError("sentence-transformers required: pip install sentence-transformers") from exc
        log.info(f"Loading local {VOYAGE_NANO_HF_ID} (first call only)...")
        _nano_model = SentenceTransformer(VOYAGE_NANO_HF_ID, trust_remote_code=True, truncate_dim=EMBED_DIM)
        log.info("Local nano model loaded.")
    return _nano_model


def embed_query_sync(text: str) -> list[float]:
    """
    Embed a single search query using local voyage-4-nano (no API call).
    Falls back to voyage-4-lite API if sentence-transformers unavailable.
    """
    try:
        model = _load_nano()
        vec = model.encode(
            text.strip(),
            prompt_name="query",
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vec[:EMBED_DIM].tolist()
    except Exception as e:
        log.warning(f"Local nano failed ({e}), falling back to API")
        vecs = _voyage_embed([text.strip()], VOYAGE_QUERY_MODEL, "query")
        return vecs[0]


async def embed_query(text: str) -> list[float]:
    """
    Async wrapper around embed_query_sync.
    Drop-in replacement for the old Ollama embed_query() in core.py.
    """
    import asyncio
    return await asyncio.to_thread(embed_query_sync, text.strip())


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def voyage_api_available() -> bool:
    if not VOYAGE_API_KEY:
        return False
    try:
        import voyageai  # noqa: F401
        return True
    except ImportError:
        return False
