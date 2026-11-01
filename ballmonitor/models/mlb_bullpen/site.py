"""Public page: each MLB bullpen's pecking order going into its last 2026 game, plus the
season's relief workload by team.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views mlb_bullpen`) from the
committed data/games.csv.gz and data/pitcher_lines.csv.gz; the page only displays the numbers.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
from collections import defaultdict

from ballmonitor.core import views as V

SEASON = "2026"
TEAMS = {
    "ATH": "Athletics", "ATL": "Atlanta Braves", "AZ": "Arizona Diamondbacks", "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox", "CHC": "Chicago Cubs", "CIN": "Cincinnati Reds", "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies", "CWS": "Chicago White Sox", "DET": "Detroit Tigers", "HOU": "Houston Astros",
    "KC": "Kansas City Royals", "LAA": "Los Angeles Angels", "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins", "MIL": "Milwaukee Brewers", "MIN": "Minnesota Twins", "NYM": "New York Mets",
    "NYY": "New York Yankees", "PHI": "Philadelphia Phillies", "PIT": "Pittsburgh Pirates",
    "SD": "San Diego Padres", "SEA": "Seattle Mariners", "SF": "San Francisco Giants",
    "STL": "St. Louis Cardinals", "TB": "Tampa Bay Rays", "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays", "WSH": "Washington Nationals",
}


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _read(path) -> list[dict]:
    with gzip.open(path, "rt", newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r["season"] == SEASON]


def page(model) -> dict:
    data = model.dir / "data"
    games = _read(data / "games.csv.gz")
    lines = _read(data / "pitcher_lines.csv.gz")

    last: dict[str, dict] = {}
    for g in games:  # last regular-season game per team (doubleheaders: later game_pk)
        k = (g["game_date"], int(g["game_pk"]))
        if g["team"] not in last or k > (last[g["team"]]["game_date"], int(last[g["team"]]["game_pk"])):
            last[g["team"]] = g

    relief_outs: dict[tuple[str, str], int] = defaultdict(int)  # (team, pitcher) -> 2026 relief outs
    team = defaultdict(lambda: {"outs": 0, "runs": 0, "arms": set(), "all_outs": 0, "games": set()})
    for ln in lines:
        t = team[ln["team"]]
        t["all_outs"] += int(ln["outs"])
        t["games"].add(ln["game_pk"])
        if ln["started"] == "0":
            relief_outs[(ln["team"], ln["name"])] += int(ln["outs"])
            t["outs"] += int(ln["outs"])
            t["runs"] += int(ln["runs"])
            t["arms"].add(ln["pitcher_id"])

    options = []
    for abbr in sorted(last, key=lambda a: TEAMS.get(a, a)):
        g = last[abbr]
        inputs, actual = model.backtest_case(g)
        ex = model.predict(inputs).extras
        used = set(actual["used"])
        saves = {r["name"]: int(r.get("saves", 0)) for r in inputs["relievers"]}
        rows = [{
            "name": name,
            "appear": ex["p_appear"][name],
            "first": ex["p_first"][name],
            "save": ex["stats"][name]["saves"] / ex["n_simulations"],
            "saves": saves.get(name, 0),
            "ip": relief_outs.get((abbr, name), 0) / 3,
            "pitched": "Yes" if name in used else "No",
        } for name in ex["p_appear"]]
        rows.sort(key=lambda r: (-r["appear"], r["name"]))
        where = "vs" if g["is_home"] in ("1", "true", "True") else "at"
        opp = TEAMS.get(g["opponent"], g["opponent"])
        options.append(V.option(TEAMS.get(abbr, abbr), [V.table(
            f"pen_{abbr.lower()}", f"{TEAMS.get(abbr, abbr)} bullpen",
            [V.col("name", "Reliever"), V.col("appear", "Chance he pitches", "pct", bar=True),
             V.col("first", "First out of the pen", "pct"), V.col("save", "Chance of a save", "pct"),
             V.col("saves", "Saves (last 30 games)", "int"), V.col("ip", "Relief innings 2026", "number", decimals=0),
             V.col("pitched", "Did he pitch?")],
            rows,
            subtitle=(f"Before the last game of the season, {_day(g['game_date'])} {where} {opp} "
                      f"(starter: {g['starter_name']}). Score: {g['runs_for']}-{g['runs_against']}."),
            note="\"Did he pitch?\" is what actually happened in that game. Saves count the team's last 30 games.")]))

    pens = V.picker(
        "pens", "Who comes out of the bullpen?", "Team", options,
        subtitle=("Each team's relievers ranked by their chance to pitch in the final regular-season game, "
                  "based on who was rested, who had been closing and how deep the starter usually goes."))

    team_rows = []
    for abbr, t in team.items():
        team_rows.append({
            "team": TEAMS.get(abbr, abbr),
            "ip": t["outs"] / 3,
            "share": t["outs"] / t["all_outs"] if t["all_outs"] else 0.0,
            "per_game": t["outs"] / 3 / len(t["games"]) if t["games"] else 0.0,
            "ra9": 27 * t["runs"] / t["outs"] if t["outs"] else 0.0,
            "arms": len(t["arms"]),
        })
    workload = V.table(
        "workload", "2026 bullpen workload by team",
        [V.col("team", "Team"), V.col("ip", "Relief innings", "number", decimals=0, bar=True),
         V.col("per_game", "Relief innings per game", "number", decimals=1),
         V.col("share", "Share of all innings", "pct"),
         V.col("ra9", "Runs allowed per 9 innings", "number", decimals=2),
         V.col("arms", "Relievers used", "int")],
        team_rows, sort="ip", search=True,
        subtitle="Regular season. Click a column to sort.",
        note=("Runs allowed count every run scored while a reliever was on the mound, earned or not "
              "(including runners left on base by the pitcher before him)."))

    last_day = max(g["game_date"] for g in games)
    return V.page(
        title="MLB bullpens: who pitches in relief",
        summary="Every team's relievers ranked by their chance to pitch, and how hard each bullpen worked in 2026.",
        sport="Baseball",
        updated=f"2026 regular season, final (games through {_day(last_day)})",
        how=("For each game we look at every reliever on the active roster: how often he has pitched lately, "
             "whether he has been closing or setting up, and whether he is tired from the last few days. "
             f"We then play the game out {int(model.params.num_simulations):,} times, letting the manager "
             "make the calls real managers made in 2025, and count how often each reliever got in."),
        views=[pens, workload],
    )
