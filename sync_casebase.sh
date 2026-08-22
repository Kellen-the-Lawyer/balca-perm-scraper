#!/bin/bash
# =============================================================================
# Casebase — Scheduled Sync Script
# Scrapes new BALCA and AAO decisions and ingests them into the database.
#
# Runs via launchd. Logs to: ~/Library/Logs/casebase_sync.log
# Manual run: bash /Users/Dad/Documents/GitHub/Casebase/sync_casebase.sh
# =============================================================================

set -euo pipefail

REPO="/Users/Dad/Documents/GitHub/Casebase"
INGEST_DIR="$REPO/scripts/ingest"
VENV_PYTHON="$REPO/venv/bin/python"
SYSTEM_PYTHON="/opt/homebrew/bin/python3.14"
LOG="$HOME/Library/Logs/casebase_sync.log"
LOCK="/tmp/casebase_sync.lock"

# ── Environment ──────────────────────────────────────────────────────────────
# launchd gives jobs a bare environment, so nothing from the interactive shell
# is present. Without this, BALCA scrape fails (DOL_AZURE_QUERY_KEY missing) and
# AAO ingest fails (falls back to a wrong DATABASE_URL default).
if [ -f "$REPO/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$REPO/.env"
    set +a
fi
: "${DATABASE_URL:=postgresql://perm@127.0.0.1:5433/perm_decisions}"
export DATABASE_URL

# ── Logging helper ────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# ── Lock: prevent overlapping runs ───────────────────────────────────────────
if [ -f "$LOCK" ]; then
    OLD_PID=$(cat "$LOCK")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        log "SKIP — another sync is already running (PID $OLD_PID)"
        exit 0
    else
        log "Stale lock found (PID $OLD_PID), removing"
        rm -f "$LOCK"
    fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

log "======================================================"
log "Casebase sync started"
log "======================================================"

ERRORS=0

# ── 1. BALCA scraper: fetch latest decisions from DOL search ─────────────────
# Scrapes the current fiscal year to pick up anything new since last run.
# Uses --max-pages 999 so it pages through everything available.
CURRENT_YEAR=$(date +%Y)
log "--- BALCA scrape (fiscal year $CURRENT_YEAR) ---"
if cd "$REPO" && "$VENV_PYTHON" -m balca_perm_scraper.cli search \
    --max-pages 999 \
    >> "$LOG" 2>&1; then
    log "BALCA scrape: OK"
else
    log "BALCA scrape: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi

# ── 1b. BALCA load: download new/upgraded PDFs from SQLite listing -> decisions ─
# One row per docket; newest substantive document wins (see load_balca_decisions.py).
log "--- BALCA load (sqlite -> PDF -> decisions) ---"
if cd "$REPO" && "$VENV_PYTHON" -u scripts/ingest/load_balca_decisions.py \
    >> "$LOG" 2>&1; then
    log "BALCA load: OK"
else
    log "BALCA load: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi

# ── 2. BALCA RAG ingest: chunk + embed (Voyage) any decision not yet in rag_chunks
log "--- BALCA RAG ingest ---"
if cd "$INGEST_DIR" && "$VENV_PYTHON" -u ingest_rag.py --corpus balca \
    >> "$LOG" 2>&1; then
    log "BALCA ingest: OK"
else
    log "BALCA ingest: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi

# ── 3. Tag any new docketing notices ─────────────────────────────────────────
log "--- Tagging docketing notices ---"
if "$SYSTEM_PYTHON" - <<'PYSQL' >> "$LOG" 2>&1
import psycopg2, os
url = os.environ.get("DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")
conn = psycopg2.connect(url)
cur = conn.cursor()
cur.execute("""
    UPDATE decisions
    SET doc_type = 'docketing_notice'
    WHERE doc_type = 'decision'
      AND outcome IS NULL
      AND full_text ILIKE '%NOTICE OF DOCKETING, BRIEFING SCHEDULE%'
""")
print(f"Tagged {cur.rowcount} new docketing notices")
conn.commit()
cur.close()
conn.close()
PYSQL
then
    log "Docketing notice tagging: OK"
else
    log "Docketing notice tagging: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi

# ── 4. AAO ingest: re-index recent AAO decisions ─────────────────────────────
# ── 3b. AAO fetch: discover + download decisions posted since last run ────────
# Walks the USCIS non-precedent listing newest-first; appends to aao_index.csv.
log "--- AAO fetch (uscis.gov listing) ---"
if cd "$REPO" && "$VENV_PYTHON" -u scripts/scrape/fetch_aao_new.py --max-pages 20 --stop-after 2 \
    >> "$LOG" 2>&1; then
    log "AAO fetch: OK"
else
    log "AAO fetch: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi

# --new-only: only PDFs in aao_index.csv not yet text-extracted (seconds, not hours).
log "--- AAO ingest (--new-only) ---"
if cd "$INGEST_DIR" && "$VENV_PYTHON" -u ingest_aao.py --new-only \
    >> "$LOG" 2>&1; then
    log "AAO ingest: OK"
else
    log "AAO ingest: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi

# ── 4b. AAO RAG ingest: chunk + embed decisions not yet in rag_chunks ─────────
log "--- AAO RAG ingest ---"
if cd "$INGEST_DIR" && "$VENV_PYTHON" -u ingest_rag.py --corpus aao \
    >> "$LOG" 2>&1; then
    log "AAO RAG ingest: OK"
else
    log "AAO RAG ingest: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi

# ── 4c. USCIS Reading Room (FOIA): catalog -> download -> RAG ingest ─────────
# Incremental catalog walk (newest-first, stops after 2 quiet pages), download
# pending files except contracts/foia-logs, chunk+embed under corpus uscis_foia.
log "--- USCIS reading room catalog ---"
if cd "$REPO" && "$VENV_PYTHON" -u scripts/scrape/scrape_uscis_reading_room.py --stop-after 2 \
    >> "$LOG" 2>&1; then
    log "Reading room catalog: OK"
else
    log "Reading room catalog: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi
log "--- USCIS reading room download ---"
if cd "$REPO" && "$VENV_PYTHON" -u scripts/scrape/download_uscis_foia.py \
    --exclude-category contracts --exclude-category foia-logs --limit 200 \
    >> "$LOG" 2>&1; then
    log "Reading room download: OK"
else
    log "Reading room download: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi
log "--- USCIS reading room RAG ingest ---"
if cd "$INGEST_DIR" && "$VENV_PYTHON" -u ingest_foia.py >> "$LOG" 2>&1; then
    log "Reading room RAG ingest: OK"
else
    log "Reading room RAG ingest: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi

# ── 5. AAO citations: extract citations from newly ingested decisions ─────────
# --since uses a 8-day window (one day past the weekly schedule) to ensure
# nothing falls through the cracks if a run is delayed or missed.
SINCE=$(date -v-8d '+%Y-%m-%d' 2>/dev/null || date -d '8 days ago' '+%Y-%m-%d')
log "--- AAO citation extraction (since $SINCE) ---"
if cd "$INGEST_DIR" && "$VENV_PYTHON" -u build_aao_citations.py \
    --since "$SINCE" \
    >> "$LOG" 2>&1; then
    log "AAO citations: OK"
else
    log "AAO citations: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi

# ── Summary ───────────────────────────────────────────────────────────────────
log "======================================================"
if [ "$ERRORS" -eq 0 ]; then
    log "Sync completed successfully"
else
    log "Sync completed with $ERRORS error(s) — check log for details"
fi
log "======================================================"

exit $((ERRORS > 0 ? 1 : 0))
