#!/usr/bin/env bash
# Refresh every OFLC-derived materialized view, then entity_index (depends on mv_employer_representation
# and on decisions/rag_chunks — so also run after BALCA/AAO/regulation ingests), on both databases.
# Run after any OFLC disclosure-data load (download_oflc_data / manual COPY).
#   bash scripts/sql/refresh_oflc_matviews.sh            # both DBs
#   bash scripts/sql/refresh_oflc_matviews.sh homebrew   # one DB
set -euo pipefail
VIEWS=(mv_wage_yoy mv_lca_soc_filings mv_soc_titles mv_employer_representation)
SQL=""
for v in "${VIEWS[@]}"; do
  # CONCURRENTLY needs a unique index; mv_wage_yoy has none, so plain refresh there.
  if [[ "$v" == "mv_wage_yoy" ]]; then SQL+="REFRESH MATERIALIZED VIEW $v; "
  else SQL+="REFRESH MATERIALIZED VIEW CONCURRENTLY $v; "; fi
done
SQL+="REFRESH MATERIALIZED VIEW entity_index; ANALYZE mv_employer_representation; ANALYZE entity_index;"

target="${1:-both}"
if [[ "$target" == "both" || "$target" == "homebrew" ]]; then
  echo "== Homebrew :5433"
  psql postgresql://perm:perm_local_pw@localhost:5433/perm_decisions -c "$SQL"
fi
if [[ "$target" == "both" || "$target" == "docker" ]]; then
  echo "== Docker :5432"
  docker exec casebase-db psql -U perm -d perm_decisions -c "$SQL"
fi
