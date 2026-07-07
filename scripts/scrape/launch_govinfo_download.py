#!/usr/bin/env python3
"""
Launch the GovInfo bulk downloader as a background job.

This keeps a long "download everything" run alive outside the Codex tool
session, with progress in logs/govinfo_download.log and the child PID in
logs/govinfo_download.pid.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = ROOT / "logs" / "govinfo_download.log"
DEFAULT_PID = ROOT / "logs" / "govinfo_download.pid"


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch GovInfo bulk download in the background")
    parser.add_argument("--date-from", default="1900-01-01")
    parser.add_argument("--collections", default=None)
    parser.add_argument("--page-size", default="1000")
    parser.add_argument("--delay", default="0.2")
    parser.add_argument("--out-dir", default=os.environ.get("GOVINFO_OUT_DIR", str(Path.home() / "casebase_govinfo")))
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--pid-file", type=Path, default=DEFAULT_PID)
    args = parser.parse_args()

    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    args.pid_file.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(ROOT / ".venv" / "bin" / "python"),
        "-u",
        str(ROOT / "scripts" / "scrape" / "download_govinfo_bulk.py"),
        "--date-from", args.date_from,
        "--page-size", str(args.page_size),
        "--delay", str(args.delay),
        "--out-dir", args.out_dir,
    ]
    if args.collections:
        cmd.extend(["--collections", args.collections])

    log_handle = args.log_file.open("ab", buffering=0)
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    args.pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
    print(proc.pid)


if __name__ == "__main__":
    main()
