"""Build Open WAR's season table from the Lahman CSVs (Triple Play's raw copy).

    ballmonitor fetch open_war

Writes data/seasons.csv: one row per player-season (engine.SEASON_COLS). By hand: the Lahman CSVs
live in ballmonitor/games/triple_play/data/raw/lahman_csv/ (gitignored).
"""

from __future__ import annotations

import csv
from pathlib import Path

from ballmonitor.core import registry

from . import engine as E


def fetch(model_dir: Path, offline: bool = False) -> list[str]:
    model_dir = Path(model_dir)
    p = registry.load_model(model_dir.name).params
    rows = E.compute(p)
    (model_dir / "data").mkdir(exist_ok=True)
    with (model_dir / "data" / "seasons.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=E.SEASON_COLS)
        w.writeheader()
        w.writerows(rows)
    return [f"open_war: {len(rows)} player-seasons, {min(r['yearID'] for r in rows)}-{max(r['yearID'] for r in rows)}"]
