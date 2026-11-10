"""Big sports CSVs for the live data tables (web/tables.toml), ready for a tabdn table server.

    python -m ballmonitor.data_tables.build                 # every table below
    python -m ballmonitor.data_tables.build --only nfl_qb   # one table
    python -m ballmonitor.data_tables.build --offline       # from the download cache only

Downloads go to data_tables/raw/ (gzipped, gitignored); the CSVs to data_tables/csv/
(gitignored). Each CSV has short plain column names (documented in TABLES and in
web/tables.toml's column key) and only the columns worth filtering on. Turn a CSV into a
table server file with tabdn's builder page or `node tools/mkcom.mjs <csv> <name>.com` in
tabdn/tabc, then upload it next to batting.com and pitching.com.

Sources (attribution required, see README.md):
- nfl_qb: nflverse weekly player stats (github.com/nflverse/nflverse-data, CC BY 4.0), 1999-
- nba / wnba: ESPN box scores collected by the SportsDataverse
  (github.com/sportsdataverse/sportsdataverse-data, MIT), NBA 1994-, WNBA 2002-
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import shutil
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
RAW = HERE / "raw"
OUT = HERE / "csv"
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{year}.csv.gz"
SDV = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/{tag}/player_box_{year}.csv"


def fetch(url: str, dest: Path, offline: bool) -> Path | None:
    """Download `url` once into `dest` (stored gzipped); None when it doesn't exist."""
    if dest.exists():
        return dest
    if offline:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ballmonitor data tables (github.com/triplelog/ballmonitor)"})
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            body = res.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    tmp = dest.with_suffix(".part")
    if url.endswith(".gz"):
        tmp.write_bytes(body)
    else:
        with gzip.open(tmp, "wb", compresslevel=6) as f:
            f.write(body)
    tmp.replace(dest)
    return dest


def rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def num(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def passer_rating(cmp: float, att: float, yds: float, td: float, ints: float) -> float:
    """The NFL passer rating (0 to 158.3)."""
    if att <= 0:
        return 0.0
    clamp = lambda x: max(0.0, min(2.375, x))  # noqa: E731
    a = clamp((cmp / att - 0.3) * 5)
    b = clamp((yds / att - 3) * 0.25)
    c = clamp(td / att * 20)
    d = clamp(2.375 - ints / att * 25)
    return round((a + b + c + d) / 6 * 100, 1)


# ---- NFL quarterbacks ----------------------------------------------------------------------

NFL_QB_COLUMNS = ["season", "week", "type", "game", "player", "pos", "team", "opp",
                  "cmp", "att", "yds", "td", "int", "rating", "ypa", "sacks", "sack_yds",
                  "air_yds", "first_downs", "epa", "cpoe", "rush", "rush_yds", "rush_td",
                  "fumbles_lost", "fantasy"]


CHARTING_FROM = 2006   # nflverse has air yards and CPOE from this season on


def nfl_qb(offline: bool, log=print) -> Path:
    """One row per player per game with a pass thrown (any position), 1999 on."""
    out = OUT / "nfl_qb_games.csv"
    n = 0
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(NFL_QB_COLUMNS)
        for year in range(1999, dt.date.today().year + 1):
            src = fetch(NFLVERSE.format(year=year), RAW / "nfl" / f"stats_player_week_{year}.csv.gz", offline)
            if src is None:
                continue
            for r in rows(src):
                att = num(r["attempts"])
                if att < 1:
                    continue
                cmp, yds, td, ints = num(r["completions"]), num(r["passing_yards"]), num(r["passing_tds"]), num(r["passing_interceptions"])
                w.writerow([r["season"], r["week"], r["season_type"], r["game_id"], r["player_display_name"],
                            r["position"], r["team"], r["opponent_team"],
                            int(cmp), int(att), int(yds), int(td), int(ints), passer_rating(cmp, att, yds, td, ints),
                            round(yds / att, 2), int(num(r["sacks_suffered"])), int(abs(num(r["sack_yards_lost"]))),
                            # air yards and CPOE come from charting that starts in 2006: blank before
                            int(num(r["passing_air_yards"])) if year >= CHARTING_FROM else "",
                            int(num(r["passing_first_downs"])), round(num(r["passing_epa"]), 2),
                            round(num(r["passing_cpoe"]), 1) if r["passing_cpoe"] != "" and year >= CHARTING_FROM else "",
                            int(num(r["carries"])), int(num(r["rushing_yards"])), int(num(r["rushing_tds"])),
                            int(num(r["sack_fumbles_lost"]) + num(r["rushing_fumbles_lost"])),
                            round(num(r["fantasy_points"]), 2)])
                n += 1
    log(f"nfl_qb: {n:,} rows -> {out}")
    return out


# ---- NBA / WNBA ----------------------------------------------------------------------------

BASKETBALL_COLUMNS = ["date", "season", "type", "game", "player", "pos", "team", "opp", "home", "result",
                      "team_pts", "opp_pts", "start", "min", "pts", "reb", "ast", "stl", "blk", "tov", "pf",
                      "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "pm"]
SEASON_TYPE = {"2": "regular", "3": "playoffs", "5": "play-in"}   # 1 = preseason, 4 = all-star: left out


def _made_att(x: str) -> tuple[float, float]:
    """Old layout's "7-15" -> (7, 15); "--" or blank -> (0, 0)."""
    m, _, a = str(x).partition("-")
    return num(m), num(a)


def _normalise(r: dict, games: dict) -> dict:
    """Older ESPN seasons (e.g. WNBA 2002) have `min`, "made-att" shot columns and no opponent,
    home/away or score: map them to the newer names; `games` (game -> team -> points) supplies
    the opponent, both scores and the result. Home/away isn't in that data and stays blank."""
    if "minutes" in r:
        return r
    fg, fg3, ft = _made_att(r["fg"]), _made_att(r["fg3"]), _made_att(r["ft"])
    teams = games.get(r["game_id"], {})
    opp = next((k for k in teams if k != r["team_abbreviation"]), "")
    mine, theirs = teams.get(r["team_abbreviation"], 0), teams.get(opp, 0)
    return {**r, "minutes": r["min"], "points": r["pts"], "turnovers": r["to"], "fouls": r["pf"],
            "rebounds": r["reb"], "assists": r["ast"], "steals": r["stl"], "blocks": r["blk"],
            "offensive_rebounds": r["oreb"], "defensive_rebounds": r["dreb"],
            "field_goals_made": fg[0], "field_goals_attempted": fg[1],
            "three_point_field_goals_made": fg3[0], "three_point_field_goals_attempted": fg3[1],
            "free_throws_made": ft[0], "free_throws_attempted": ft[1],
            "opponent_team_abbreviation": opp, "home_away": "", "team_score": mine, "opponent_team_score": theirs,
            "team_winner": "true" if mine > theirs else "false",
            "starter": r["starter"].lower(), "did_not_play": r["did_not_play"].lower()}


def _game_points(path: Path) -> dict[str, dict[str, float]]:
    """For an old-layout season: game -> team -> points (sum of the players' points)."""
    out: dict[str, dict[str, float]] = {}
    for r in rows(path):
        if "minutes" in r:
            return {}
        g = out.setdefault(r["game_id"], {})
        g[r["team_abbreviation"]] = g.get(r["team_abbreviation"], 0) + num(r["pts"])
    return out


def basketball(league: str, first: int, offline: bool, log=print) -> Path:
    """One row per player per game played (did_not_play rows and preseason left out)."""
    tag = f"espn_{league}_player_boxscores"
    out = OUT / f"{league}_player_games.csv"
    n = 0
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(BASKETBALL_COLUMNS)
        for year in range(first, dt.date.today().year + 2):
            src = fetch(SDV.format(tag=tag, year=year), RAW / league / f"player_box_{year}.csv.gz", offline)
            if src is None:
                continue
            games = _game_points(src)
            for r in rows(src):
                r = _normalise(r, games)
                kind = SEASON_TYPE.get(r["season_type"])
                if not kind or r["did_not_play"] == "true" or num(r["minutes"]) <= 0:
                    continue
                w.writerow([r["game_date"], r["season"], kind, r["game_id"], r["athlete_display_name"],
                            r["athlete_position_abbreviation"], r["team_abbreviation"], r["opponent_team_abbreviation"],
                            # ESPN's team_winner flag is wrong for ~29% of NBA team-games; the scores agree
                            # with the players' points added up, so the result comes from them
                            r["home_away"], "W" if num(r["team_score"]) > num(r["opponent_team_score"]) else "L",
                            int(num(r["team_score"])), int(num(r["opponent_team_score"])),
                            1 if r["starter"] == "true" else 0, round(num(r["minutes"]), 1),
                            *[int(num(r[k])) for k in ("points", "rebounds", "assists", "steals", "blocks", "turnovers",
                                                       "fouls", "field_goals_made", "field_goals_attempted",
                                                       "three_point_field_goals_made", "three_point_field_goals_attempted",
                                                       "free_throws_made", "free_throws_attempted",
                                                       "offensive_rebounds", "defensive_rebounds", "plus_minus")]])
                n += 1
    log(f"{league}: {n:,} rows -> {out}")
    return out


TABLES = {
    "nfl_qb": lambda offline, log: nfl_qb(offline, log),
    "nba": lambda offline, log: basketball("nba", 1994, offline, log),
    "wnba": lambda offline, log: basketball("wnba", 2002, offline, log),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", choices=sorted(TABLES), action="append", help="build just these (repeatable)")
    ap.add_argument("--offline", action="store_true", help="use only what's already in raw/")
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    for name in args.only or TABLES:
        path = TABLES[name](args.offline, print)
        print(f"   {path.stat().st_size / 2**20:.1f} MB")
    free = shutil.disk_usage(OUT).free / 2**30
    print(f"done; {free:.1f} GB free on this disk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
