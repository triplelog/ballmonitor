"""Lahman database -> player-seasons with per-plate-appearance rates and a main position.

Uses the Lahman CSVs Triple Play already unpacks (games/triple_play/data/raw/lahman_csv/,
gitignored). Seasons from MIN_YEAR on, where sacrifice flies and hit-by-pitch are recorded.
Plate appearances here = AB + BB + HBP + SF (sacrifice bunts are left out: the chain has no
bunts). Rates, in chain.OUTCOMES order: strikeouts, walks + hit by pitch, singles, doubles,
triples, home runs, other outs (AB - H - SO + SF).
"""

from __future__ import annotations

import csv
from collections import defaultdict

from ballmonitor.games.triple_play.facts import RAW

MIN_YEAR = 1955
MIN_PA = 450
POSITIONS = {"C": "G_c", "1B": "G_1b", "2B": "G_2b", "3B": "G_3b", "SS": "G_ss",
             "LF": "G_lf", "CF": "G_cf", "RF": "G_rf", "DH": "G_dh"}
MAIN_SHARE = 0.6   # a season counts at a position when at least 60% of its games were there


def _rows(name: str):
    with open(RAW / f"{name}.csv", newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def _i(x) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _col(r: dict, *names: str) -> int:
    """CRAN Lahman names doubles X2B, the SABR CSV 2B."""
    return next((_i(r[n]) for n in names if n in r), 0)


def team_names() -> dict[tuple[str, str], str]:
    """The team's name that season ("Montreal Expos", "Cleveland Indians"), not today's franchise name."""
    return {(r["yearID"], r["teamID"]): r["name"] for r in _rows("Teams")}


def load() -> list[dict]:
    names = {r["playerID"]: f"{r['nameFirst']} {r['nameLast']}".strip() for r in _rows("People") if r.get("nameLast")}
    teams = team_names()
    bat: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(int))
    team_pa: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in _rows("Batting"):
        if _i(r["yearID"]) < MIN_YEAR:
            continue
        key = (r["playerID"], r["yearID"])
        b = bat[key]
        for k, cols in (("AB", ("AB",)), ("H", ("H",)), ("2B", ("X2B", "2B")), ("3B", ("X3B", "3B")),
                        ("HR", ("HR",)), ("BB", ("BB",)), ("SO", ("SO",)), ("HBP", ("HBP",)), ("SF", ("SF",))):
            b[k] += _col(r, *cols)
        team_pa[key][r["teamID"]] += _i(r["AB"]) + _i(r["BB"])
    games: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(int))
    for r in _rows("Appearances"):
        if _i(r["yearID"]) < MIN_YEAR:
            continue
        g = games[(r["playerID"], r["yearID"])]
        g["all"] += _i(r["G_all"])
        for pos, col in POSITIONS.items():
            g[pos] += _i(r.get(col))

    out = []
    for (pid, year), b in bat.items():
        pa = b["AB"] + b["BB"] + b["HBP"] + b["SF"]
        if pa < MIN_PA or pid not in names:
            continue
        g = games.get((pid, year), {})
        pos = max(POSITIONS, key=lambda p: g.get(p, 0)) if g else None
        if not pos or g.get(pos, 0) < MAIN_SHARE * max(g.get("all", 0), 1):
            continue
        singles = b["H"] - b["2B"] - b["3B"] - b["HR"]
        counts = [b["SO"], b["BB"] + b["HBP"], singles, b["2B"], b["3B"], b["HR"],
                  b["AB"] - b["H"] - b["SO"] + b["SF"]]
        if min(counts) < 0:
            continue
        team_id = max(team_pa[(pid, year)], key=team_pa[(pid, year)].get)
        ab = max(b["AB"], 1)
        out.append({
            "id": pid, "name": names[pid], "year": int(year), "pos": pos,
            "team": teams.get((year, team_id), team_id) + (" (+1)" if len(team_pa[(pid, year)]) > 1 else ""),
            "pa": pa, "rates": [c / pa for c in counts],
            "avg": b["H"] / ab, "obp": (b["H"] + b["BB"] + b["HBP"]) / pa,
            "slg": (singles + 2 * b["2B"] + 3 * b["3B"] + 4 * b["HR"]) / ab,
            "hr": b["HR"], "bb": b["BB"] + b["HBP"], "so": b["SO"],
        })
    return out


def team_seasons() -> list[dict]:
    """Every team-season from MIN_YEAR on as one 'hitter' (for the calibration check): rates and real runs per game."""
    out = []
    for r in _rows("Teams"):
        if _i(r["yearID"]) < MIN_YEAR or _i(r["G"]) == 0:
            continue
        ab, h, d, t, hr = _i(r["AB"]), _i(r["H"]), _col(r, "X2B", "2B"), _col(r, "X3B", "3B"), _i(r["HR"])
        bb, so, hbp, sf = _i(r["BB"]), _i(r["SO"]), _i(r["HBP"]), _i(r["SF"])
        pa = ab + bb + hbp + sf
        counts = [so, bb + hbp, h - d - t - hr, d, t, hr, ab - h - so + sf]
        out.append({"year": _i(r["yearID"]), "team": r["teamID"], "rates": [c / pa for c in counts],
                    "runs_per_game": _i(r["R"]) / _i(r["G"])})
    return out
