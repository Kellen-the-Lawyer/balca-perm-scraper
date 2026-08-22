#!/bin/zsh
# Sync tables Homebrew(5433) -> Docker(casebase-db), preserving ids.
# Usage: scripts/sync_docker_tables.sh decisions balca_issue_tags 'rag_chunks:corpus=balca'
#   table            -> UPSERT every HB row by id (never truncates: decisions has FK children
#                       like citations/project_notes that would cascade). Reports, but does not
#                       delete, ids that exist only in Docker.
#   table:col=value  -> same, but only the slice WHERE col=value; Docker-only ids in that
#                       slice ARE deleted (rag_chunks/balca_issue_tags have no FK children).
#   REPLACE=1 env     -> full mode DELETEs all Docker rows first (for tables whose ids are
#                       regenerated on rebuild, e.g. balca_issue_tags; never for decisions).
# Aborts if the column sets differ. oflc_* stays on /tmp/sync_docker.sh (TRUNCATE+COPY).
set -e
HB="postgresql://perm@127.0.0.1:5433/perm_decisions"
DK() { docker exec -i casebase-db psql -U perm -d perm_decisions "$@"; }
[ $# -eq 0 ] && { echo "usage: $0 table[:col=value] ..."; exit 1; }
for SPEC in "$@"; do
  T="${SPEC%%:*}"; FILTER=""; [ "$SPEC" != "$T" ] && FILTER="${SPEC#*:}"
  COLS=$(psql "$HB" -tAc "select string_agg(quote_ident(column_name), ',' order by ordinal_position) from information_schema.columns where table_name='$T';")
  DCOLS=$(DK -tAc "select string_agg(quote_ident(column_name), ',' order by ordinal_position) from information_schema.columns where table_name='$T';")
  [ "$(echo $COLS | tr ',' '\n' | sort | md5)" != "$(echo $DCOLS | tr ',' '\n' | sort | md5)" ] && { echo "ABORT $T: column sets differ"; echo "HB: $COLS"; echo "DK: $DCOLS"; exit 1; }
  WHERE=""; if [ -n "$FILTER" ]; then COL="${FILTER%%=*}"; VAL="${FILTER#*=}"; WHERE="WHERE $COL = '$VAL'"; fi
  echo "=== $T ${WHERE:-(full)} $(date +%T)"
  SETS=$(echo "$COLS" | tr ',' '\n' | grep -v '^id$' | sed 's/.*/&=EXCLUDED.&/' | paste -sd, -)
  TMP="/tmp/sync_${T}.tsv"
  psql "$HB" -c "\copy (SELECT $COLS FROM $T $WHERE) TO '$TMP'"
  docker cp "$TMP" casebase-db:"$TMP" >/dev/null
  DK <<SQL
BEGIN;
CREATE TEMP TABLE stage (LIKE $T INCLUDING DEFAULTS);
\\copy stage ($COLS) FROM '$TMP'
$( [ -n "$WHERE" ] && echo "DELETE FROM $T $WHERE AND id NOT IN (SELECT id FROM stage);" )
$( [ "$REPLACE" = 1 ] && [ -z "$WHERE" ] && echo "DELETE FROM $T;" )
INSERT INTO $T ($COLS) SELECT $COLS FROM stage
  ON CONFLICT (id) DO UPDATE SET $SETS;
SELECT setval(pg_get_serial_sequence('$T','id'), (SELECT max(id) FROM $T));
COMMIT;
SQL
  docker exec casebase-db rm -f "$TMP"; rm -f "$TMP"
  HBN=$(psql "$HB" -tAc "select count(*) from $T $WHERE"); DKN=$(DK -tAc "select count(*) from $T $WHERE")
  echo "  HB=$HBN Docker=$DKN $([ "$HBN" = "$DKN" ] && echo OK || echo "MISMATCH (Docker-only ids retained; investigate)")"
done
