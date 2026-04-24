#!/bin/bash
# Casebase RAG — full corpus ingestion
# Run from the perm-research directory: bash ingest_all.sh
# Safe to restart — upsert on conflict means it skips already-embedded chunks.

set -e
cd "$(dirname "$0")"

echo "======================================"
echo " Casebase RAG Ingestion"
echo " Started: $(date)"
echo "======================================"

echo ""
echo "--- Policy Manuals ---"
python3 ingest_rag.py --corpus policy

echo ""
echo "--- BALCA Decisions ---"
python3 ingest_rag.py --corpus balca

echo ""
echo "--- AAO: 2022-present ---"
python3 ingest_rag.py --corpus aao --date-from 2022-01-01

echo ""
echo "--- AAO: 2019-2021 ---"
python3 ingest_rag.py --corpus aao --date-from 2019-01-01 --date-to 2021-12-31

echo ""
echo "--- AAO: 2016-2018 ---"
python3 ingest_rag.py --corpus aao --date-from 2016-01-01 --date-to 2018-12-31

echo ""
echo "--- AAO: 2013-2015 ---"
python3 ingest_rag.py --corpus aao --date-from 2013-01-01 --date-to 2015-12-31

echo ""
echo "--- AAO: 2010-2012 ---"
python3 ingest_rag.py --corpus aao --date-from 2010-01-01 --date-to 2012-12-31

echo ""
echo "--- AAO: pre-2010 ---"
python3 ingest_rag.py --corpus aao --date-to 2009-12-31

echo ""
echo "======================================"
echo " All done: $(date)"
echo "======================================"
