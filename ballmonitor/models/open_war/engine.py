"""Open WAR's arithmetic: season wins above replacement from the Lahman database. See MODEL.md.

Per player-season (stints combined; a player's park is his teams' park factors weighted by
plate appearances or innings):
  batting runs  = linear-weight runs - league linear-weight runs per PA x PA (league = same
                  league and year), park-adjusted
  position runs = sum over positions of the position's runs per 162 games x games there
  replacement   = batting_replacement_runs x PA / 600
  pitching runs = (league RA9 x park - RA9) x IP / 9 + pitching_replacement_runs_per_9 x IP / 9
  WAR           = (batting + position + replacement) / runs per win  [+ the same for pitching]
Every weight is a config param or formula (see config.toml).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

LAHMAN = Path(__file__).resolve().parents[2] / "games" / "triple_play" / "data" / "raw" / "lahman_csv"
POSITIONS = ("c", "1b", "2b", "3b", "ss", "lf", "cf", "rf", "dh")
SEASON_COLS = ["playerID", "yearID", "teams", "PA", "IP", "bat_runs", "pos_runs", "bat_rep", "pitch_runs",
               "pitch_rep", "rpw", "bWAR", "pWAR", "WAR"]


def _i(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _rows(name: str, lahman: Path = LAHMAN):
    with (lahman / f"{name}.csv").open(newline="", encoding="utf-8-sig") as fh:
        yield from csv.DictReader(fh)


def batting_lw(p, b: dict) -> float:
    """Linear-weight runs of a batting line (formula `linear_weights`)."""
    singles = b["H"] - b["X2B"] - b["X3B"] - b["HR"]
    return p.formula("linear_weights", singles=singles, doubles=b["X2B"], triples=b["X3B"], HR=b["HR"],
                     BB=b["BB"], HBP=b["HBP"], SB=b["SB"], CS=b["CS"])


def compute(p, lahman: Path = LAHMAN) -> list[dict]:
    """Every player-season's Open WAR."""
    # teams: park factors and league runs per game
    park, team_league = {}, {}
    lg_runs, lg_games = defaultdict(float), defaultdict(float)
    for t in _rows("Teams", lahman):
        key = (t["yearID"], t["teamID"])
        park[key] = (_i(t["BPF"]) or 100.0, _i(t["PPF"]) or 100.0)
        team_league[key] = t["lgID"]
        lg_runs[(t["yearID"], t["lgID"])] += _i(t["R"])
        lg_games[(t["yearID"], t["lgID"])] += _i(t["G"])

    # batting lines per player-season (stints combined) and league totals
    bat: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
    lg_bat: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
    for r in _rows("Batting", lahman):
        key = (r["playerID"], r["yearID"])
        line = {k: _i(r.get(k)) for k in ("AB", "H", "X2B", "X3B", "HR", "BB", "HBP", "SB", "CS", "SH", "SF")}
        line["PA"] = line["AB"] + line["BB"] + line["HBP"] + line["SH"] + line["SF"]
        line["outs"] = line["AB"] - line["H"] + line["SH"] + line["SF"] + line["CS"]
        lg = (r["yearID"], r["lgID"])
        for k, v in line.items():
            bat[key][k] += v
            lg_bat[lg][k] += v
        bat[key].setdefault("_parts", [])
        bat[key]["_parts"].append((lg, r["teamID"], line["PA"]))
    # The run environment: each league-year's out value makes its linear-weight runs add up to the
    # runs the league scored (formula `out_value`); with it off, outs count zero.
    out_w, lg_rate = {}, {}
    for lg, v in lg_bat.items():
        if v["PA"] <= 0:
            continue
        lw = batting_lw(p, v)
        out_w[lg] = p.formula("out_value", league_runs=lg_runs.get(lg, 0.0), league_lw=lw, league_outs=max(v["outs"], 1.0)) \
            if p.use_run_environment and lg_runs.get(lg) else 0.0
        lg_rate[lg] = (lw + out_w[lg] * v["outs"]) / v["PA"]

    # positions
    games_at: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
    for r in _rows("Appearances", lahman):
        key = (r["playerID"], r["yearID"])
        for pos in POSITIONS:
            games_at[key][pos] += _i(r.get(f"G_{pos}"))
        games_at[key]["p"] += _i(r.get("G_p"))
        games_at[key]["all"] += _i(r.get("G_all"))

    # pitching
    pit: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
    lg_pit: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
    for r in _rows("Pitching", lahman):
        key = (r["playerID"], r["yearID"])
        outs, runs = _i(r["IPouts"]), _i(r.get("R")) or _i(r.get("ER"))
        lg = (r["yearID"], r["lgID"])
        pit[key]["outs"] += outs
        pit[key]["R"] += runs
        lg_pit[lg]["outs"] += outs
        lg_pit[lg]["R"] += runs
        pit[key].setdefault("_parts", [])
        pit[key]["_parts"].append((lg, r["teamID"], outs))
    lg_ra9 = {lg: 27 * v["R"] / v["outs"] for lg, v in lg_pit.items() if v["outs"] > 0}

    use_park = bool(p.use_park_factors)
    out = []
    for key in sorted(set(bat) | set(pit), key=lambda k: (k[1], k[0])):
        pid, year = key
        b, q, g = bat.get(key), pit.get(key), games_at.get(key, {})
        teams = sorted({t for _, t, _ in (b or {}).get("_parts", [])} | {t for _, t, _ in (q or {}).get("_parts", [])})
        # runs per win from the league's scoring that year (formula `runs_per_win`)
        parts = (b or {}).get("_parts") or (q or {}).get("_parts")
        lg = parts[0][0]
        rpg = lg_runs[lg] / lg_games[lg] if lg_games.get(lg) else 4.5
        rpw = p.formula("runs_per_win", runs_per_game=rpg)
        pa = b["PA"] if b else 0.0
        ip = q["outs"] / 3 if q else 0.0
        mostly_pitcher = g.get("p", 0) > 0.5 * max(g.get("all", 0), 1)
        bat_runs = pos_runs = bat_rep = 0.0
        if b and pa > 0 and not (mostly_pitcher and not p.pitcher_batting):
            expected = sum(lg_rate.get(l, 0.0) * n for l, _, n in b["_parts"])
            pf = sum((park.get((year, t), (100, 100))[0] / 100) * n for _, t, n in b["_parts"]) / pa if use_park else 1.0
            outs_value = sum(out_w.get(l, 0.0) * n for l, _, n in b["_parts"]) / pa * b["outs"]
            raw = batting_lw(p, b) + outs_value
            bat_runs = raw - expected * pf
            pos_runs = sum(getattr(p, f"pos_{pos}") * g.get(pos, 0) / 162 for pos in POSITIONS)
            bat_rep = p.batting_replacement_runs * pa / 600
        pitch_runs = pitch_rep = 0.0
        if q and q["outs"] > 0:
            ra9 = 27 * q["R"] / q["outs"]
            lg_ra = sum(lg_ra9.get(l, ra9) * n for l, _, n in q["_parts"]) / q["outs"]
            pf = sum((park.get((year, t), (100, 100))[1] / 100) * n for _, t, n in q["_parts"]) / q["outs"] if use_park else 1.0
            pitch_runs = (lg_ra * pf - ra9) * ip / 9
            pitch_rep = p.pitching_replacement_runs_per_9 * ip / 9
        bwar = (bat_runs + pos_runs + bat_rep) / rpw
        pwar = (pitch_runs + pitch_rep) / rpw
        out.append({"playerID": pid, "yearID": int(year), "teams": "/".join(teams), "PA": int(pa), "IP": round(ip, 1),
                    "bat_runs": round(bat_runs, 2), "pos_runs": round(pos_runs, 2), "bat_rep": round(bat_rep, 2),
                    "pitch_runs": round(pitch_runs, 2), "pitch_rep": round(pitch_rep, 2), "rpw": round(rpw, 3),
                    "bWAR": round(bwar, 2), "pWAR": round(pwar, 2), "WAR": round(bwar + pwar, 2)})
    return out


def load(data_dir: Path) -> list[dict]:
    with (data_dir / "seasons.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["yearID"] = int(r["yearID"])
        for k in SEASON_COLS[3:]:
            r[k] = float(r[k])
    return rows
