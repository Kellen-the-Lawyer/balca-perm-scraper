#!/bin/bash
# DOL OFLC Data Download
# Downloads PERM, LCA, and PW disclosure files (FY2020–FY2026)
# Run from the perm-research directory: bash download_oflc_data.sh
# Safe to re-run — already-downloaded files are skipped.

set -e
cd "$(dirname "$0")"

# Activate the project venv (httpx is installed there)
source ../.venv/bin/activate

echo "======================================"
echo " DOL OFLC Data Download"
echo " Started: $(date)"
echo " Python:  $(python3 --version)"
echo "======================================"

echo ""
echo "--- Downloading OFLC Disclosure Files ---"
python3 download_oflc_data.py

echo ""
echo "======================================"
echo " Done: $(date)"
echo "======================================"
