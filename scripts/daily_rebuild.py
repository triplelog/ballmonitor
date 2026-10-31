#!/usr/bin/env python3
"""Daily data refresh and static site build script.

Can be run directly or scheduled via cron (e.g. `0 6 * * * /path/to/.venv/bin/python scripts/daily_rebuild.py`).

Usage:
    python scripts/daily_rebuild.py [--out dist] [--offline]
"""

import argparse
import sys
from pathlib import Path

# Ensure ballmonitor is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ballmonitor.cli import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh model data and rebuild the static site.")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "dist", help="Output distribution folder")
    parser.add_argument("--offline", action="store_true", help="Rebuild using cached data without network calls")
    parser.add_argument("--models", help="Comma-separated models to fetch instead of the scheduled ones (the site is always fully built)")
    args = parser.parse_args()

    cmd = ["update-and-build", "--out", str(args.out)]
    if args.offline:
        cmd.append("--offline")
    if args.models:
        cmd.extend(["--models", args.models])

    sys.exit(main(cmd))
