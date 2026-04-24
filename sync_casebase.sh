#!/bin/bash
# =============================================================================
# Casebase — Scheduled Sync Script
# Scrapes new BALCA and AAO decisions and ingests them into the database.
#
# Runs via launchd. Logs to: ~/Library/Logs/casebase_sync.log
# Manual run: bash /Users/Dad/Documents/GitHub/balca-perm-scraper/sync_casebase.sh
# =============================================================================

set -euo pipefail

REPO="/Users/Dad/Documents/GitHub/balca-perm-scraper"
PERM_RESEARCH="$REPO/perm-research"
VENV_PYTHON="$REPO/venv/bin/python"
SYSTEM_PYTHON="/opt/homebrew/bin/python3.14"
LOG="$HOME/Library/Logs/casebase_sync.log"
LOCK="/tmp/casebase_sync.lock"

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

# ── 2. BALCA ingest: push scraped SQLite records into Postgres ────────────────
log "--- BALCA ingest into Postgres ---"
if cd "$PERM_RESEARCH" && "$SYSTEM_PYTHON" ingest_rag.py --corpus balca \
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
url = os.environ.get("DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
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
    log "Docketing notice tagging: OK"
else
    log "Docketing notice tagging: FAILED (exit $?)"
    ERRORS=$((ERRORS + 1))
fi

# ── 4. AAO ingest: re-index recent AAO decisions ─────────────────────────────
# Only re-ingests the last 90 days to keep the run fast.
DATE_FROM=$(date -v-90d '+%Y-%m-%d' 2>/dev/null || date -d '90 days ago' '+%Y-%m-%d')
log "--- AAO ingest (from $DATE_FROM) ---"
if cd "$PERM_RESEARCH" && "$SYSTEM_PYTHON" ingest_aao.py \
    >> "$LOG" 2>&1; then
    log "AAO ingest: OK"
else
    log "AAO ingest: FAILED (exit $?)"
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
