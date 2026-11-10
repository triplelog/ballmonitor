"""`ballmonitor fetch ranked_choice [--offline]`: download/refresh every ballot source.

Each source module in sources/ caches raw pages in data/raw/<source>/ and rebuilds
data/ballots/<source>.csv.gz (+ _contests) from the cache (format: sources/CONTRACT.md).
With a full cache a run only asks for what can be new (the current AP poll weeks), so it is
cheap to run daily. On a machine without the raw cache (the daily CI build) the AP source
treats the weeks already in its built CSV as downloaded and fetches only new weeks; the
award sources (MLB, NBA, NHL change once a year) are skipped there so their built CSVs are
never overwritten from an empty cache. A failing source is reported and the others still run.
Each source's top-level log lines (downloads, weeks not posted yet, polite stops, totals) are
passed on; its indented per-page detail is dropped.
"""

from __future__ import annotations

import importlib
from pathlib import Path

SOURCES = ["ap_polls", "mlb", "nba", "nhl"]
RAW = {"ap_polls": "ap", "mlb": "mlb", "nba": "nba", "nhl": "nhl"}
INCREMENTAL = {"ap_polls"}  # can update from the built CSVs alone


def fetch(model_dir: Path, offline: bool = False):
    for name in SOURCES:
        raw = Path(model_dir) / "data" / "raw" / RAW[name]
        if name not in INCREMENTAL and not (raw.is_dir() and any(raw.iterdir())):
            yield f"{name}: no raw cache on this machine - skipped (built CSVs kept)"
            continue
        try:
            module = importlib.import_module(f"ballmonitor.models.ranked_choice.sources.{name}")
        except ImportError as exc:
            yield f"{name}: not available ({exc})"
            continue
        notes: list[str] = []
        try:
            written = module.fetch(Path(model_dir), offline=offline, log=_quiet(name, notes)) or []
        except Exception as exc:  # keep going: one broken source must not block the rest
            yield from notes
            yield f"{name}: FAILED ({type(exc).__name__}: {exc})"
            continue
        yield from notes
        for line in written:
            yield f"{name}: {line}"


def _quiet(name: str, notes: list[str]):
    """Logger keeping a source's top-level lines (what it downloaded, what is not posted yet,
    a polite stop, its totals) and dropping the indented per-page detail, so a run's log
    (e.g. the daily CI build) shows why nothing new arrived without hundreds of lines."""
    def log(*args):
        line = " ".join(str(a) for a in args)
        if line and not line[0].isspace():
            notes.append(line if line.startswith(f"{name}:") else f"{name}: {line}")
    return log
