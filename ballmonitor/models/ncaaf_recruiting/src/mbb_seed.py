"""On-court seeds for the MBB offer model: a program's prior strength from barttorvik
adjusted efficiency margin in the two seasons that ended before a class's junior-year
offers (seasons y-2 and y-1 for class y). See RESEARCH_MBB_SEED.md."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from .mbb_names import to_bart


@lru_cache(maxsize=4)
def _team_seasons(path: str) -> dict[int, dict[str, float]]:
    em: dict[int, dict[str, float]] = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            em.setdefault(int(r["season"]), {})[r["team"]] = float(r["adj_em"])
    return em


def seed_prior(data_dir: Path, year: int, programs, beta: float) -> dict[str, float]:
    """{program: beta * mean adj. EM (seasons year-2, year-1) / 10}; programs without
    barttorvik data (non-D-I) get the D-I minimum."""
    path = data_dir / "outcomes" / "mbb_team_seasons.csv"
    if beta == 0.0 or not path.exists():
        return {}
    em = _team_seasons(str(path))
    names = set().union(*em.values())
    floor = min(v for s in em.values() for v in s.values())
    out = {}
    for t in programs:
        b = to_bart(t, names)
        vals = [em[s][b] for s in (year - 2, year - 1) if b and s in em and b in em[s]]
        out[t] = beta * (sum(vals) / len(vals) if vals else floor) / 10.0
    return out
