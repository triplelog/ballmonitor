"""Reproducible studies for college_diamond -> RESEARCH.md (generated; never edit by hand).

    python -m ballmonitor.models.college_diamond.research            # all parts + RESEARCH.md
    python -m ballmonitor.models.college_diamond.research strength   # one part (+ RESEARCH.md)
    python -m ballmonitor.models.college_diamond.research report     # RESEARCH.md from saved JSON

Parts (each saves data/research/<part>.json; RESEARCH.md is rebuilt from whatever exists):
  coverage   data coverage vs. Warren Nolan final records/RPI (fetch.py's checks)
  strength   team-strength study (research_strength.py): weekend/midweek split, margin
             compression, preseason prior, recency; walk-forward weekly predictions
  selection  committee proxy (research_selection.py): P(at-large), P(host) from RPI and
             rating at Selection Monday/Sunday; fitted on development seasons
  backtest   full-model snapshots (research_backtest.py) at ~Apr 1, ~May 1 and selection
             eve vs. benchmarks; writes data/backtest.csv

Needs `pip install -e '.[data]'` (numpy) and `ballmonitor fetch college_diamond`.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent
OUT = MODEL_DIR / "data" / "research"


def save(part: str, obj: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{part}.json").write_text(json.dumps(obj, indent=1, default=str))


def load(part: str) -> dict | None:
    path = OUT / f"{part}.json"
    return json.loads(path.read_text()) if path.exists() else None


def run_part(part: str) -> None:
    t = time.time()
    print(f"[{part}]")
    if part == "coverage":
        from ballmonitor.models.college_diamond.research_report import coverage_part
        save(part, coverage_part())
    elif part == "strength":
        from ballmonitor.models.college_diamond import research_strength
        save(part, research_strength.run())
    elif part == "selection":
        from ballmonitor.models.college_diamond import research_selection
        save(part, research_selection.run())
    elif part == "backtest":
        from ballmonitor.models.college_diamond import research_backtest
        save(part, research_backtest.run())
    else:
        raise SystemExit(f"unknown part {part!r}")
    print(f"[{part}] done in {time.time() - t:.0f}s")


def main(argv: list[str]) -> None:
    parts = argv or ["coverage", "strength", "selection", "backtest"]
    for part in parts:
        if part != "report":
            run_part(part)
    from ballmonitor.models.college_diamond.research_report import write_report
    write_report(MODEL_DIR / "RESEARCH.md", {p: load(p) for p in ("coverage", "strength", "selection", "backtest")})
    print("wrote RESEARCH.md")


if __name__ == "__main__":
    main(sys.argv[1:])
