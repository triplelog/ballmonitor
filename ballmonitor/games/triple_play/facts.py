"""Lahman database -> one facts record per player (everything the categories need).

Reads the Lahman CSVs from data/raw/lahman_csv/ (built by `python -m
ballmonitor.games.triple_play.build --lahman <SABR zip or CRAN tarball>`). Column names
differ slightly between releases (CRAN: X2B; SABR CSV: 2B); only columns common to both are used.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

RAW = Path(__file__).parent / "data" / "raw" / "lahman_csv"

# current franchise id -> short name used in the categories
FRANCHISES = {
    "ANA": "Angels", "ARI": "Diamondbacks", "ATL": "Braves", "BAL": "Orioles", "BOS": "Red Sox",
    "CHC": "Cubs", "CHW": "White Sox", "CIN": "Reds", "CLE": "Guardians", "COL": "Rockies",
    "DET": "Tigers", "FLA": "Marlins", "HOU": "Astros", "KCR": "Royals", "LAD": "Dodgers",
    "MIL": "Brewers", "MIN": "Twins", "NYM": "Mets", "NYY": "Yankees", "OAK": "Athletics",
    "PHI": "Phillies", "PIT": "Pirates", "SDP": "Padres", "SEA": "Mariners", "SFG": "Giants",
    "STL": "Cardinals", "TBD": "Rays", "TEX": "Rangers", "TOR": "Blue Jays", "WSN": "Nationals",
}
POSITIONS = {"c": "G_c", "1b": "G_1b", "2b": "G_2b", "3b": "G_3b", "ss": "G_ss", "of": "G_of", "p": "G_p"}


def _rows(name: str):
    with open(RAW / f"{name}.csv", newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def _i(x) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def load() -> dict[str, dict]:
    team_franch, team_games = {}, {}
    for r in _rows("Teams"):
        team_franch[(r["yearID"], r["teamID"])] = r["franchID"]
        team_games[(r["yearID"], r["teamID"])] = _i(r["G"])
    ws_winner = {r["yearID"]: r["teamIDwinner"] for r in _rows("SeriesPost")
                 if r["round"] == "WS" and _i(r["yearID"]) >= 1903}

    P: dict[str, dict] = {}
    for r in _rows("People"):
        if not r.get("nameLast"):
            continue
        P[r["playerID"]] = {
            "id": r["playerID"], "name": f"{r['nameFirst']} {r['nameLast']}".strip(),
            "birth_country": r["birthCountry"], "birth_state": r["birthState"],
            "bats": r["bats"], "throws": r["throws"],
            "franch": defaultdict(int), "pos": defaultdict(int), "g": 0, "years": set(),
            "ws_titles": [], "bat": defaultdict(int), "pit": defaultdict(int),
            "season_max": defaultdict(float), "awards": defaultdict(int), "allstar": set(),
            "hof": False, "hof_ballot": False,
        }

    team_year_games = defaultdict(int)          # (player, year, team) -> games
    for r in _rows("Appearances"):
        p = P.get(r["playerID"])
        if not p:
            continue
        g = _i(r["G_all"])
        p["g"] += g
        p["years"].add(_i(r["yearID"]))
        fr = team_franch.get((r["yearID"], r["teamID"]))
        if fr:
            p["franch"][fr] += g
        for key, col in POSITIONS.items():
            p["pos"][key] += _i(r.get(col))
        team_year_games[(r["playerID"], r["yearID"], r["teamID"])] += g
    for (pid, year, team), g in team_year_games.items():
        if ws_winner.get(year) == team and g > 0:
            P[pid]["ws_titles"].append((int(year), g))

    # batting: careers + single-season bests (stints combined)
    season = defaultdict(lambda: defaultdict(int))
    season_teams = defaultdict(set)
    for r in _rows("Batting"):
        p = P.get(r["playerID"])
        if not p:
            continue
        key = (r["playerID"], r["yearID"])
        for col in ("AB", "H", "HR", "RBI", "SB", "BB", "HBP", "SH", "SF"):
            v = _i(r.get(col))
            p["bat"][col] += v
            season[key][col] += v
        season_teams[key].add(r["teamID"])
    for (pid, year), s in season.items():
        p = P[pid]
        m = p["season_max"]
        m["hr"] = max(m["hr"], s["HR"])
        m["h"] = max(m["h"], s["H"])
        m["sb"] = max(m["sb"], s["SB"])
        m["rbi"] = max(m["rbi"], s["RBI"])
        if s["HR"] >= 30 and s["SB"] >= 30:
            m["thirty_thirty"] = 1
        pa = s["AB"] + s["BB"] + s["HBP"] + s["SH"] + s["SF"]
        team_g = max(team_games.get((year, t), 0) for t in season_teams[(pid, year)])
        if team_g and pa >= 3.1 * team_g and s["AB"]:
            m["ba_q"] = max(m["ba_q"], s["H"] / s["AB"])

    pseason = defaultdict(lambda: defaultdict(int))
    pteams = defaultdict(set)
    for r in _rows("Pitching"):
        p = P.get(r["playerID"])
        if not p:
            continue
        key = (r["playerID"], r["yearID"])
        for col in ("W", "SO", "SV", "IPouts", "ER", "G", "GS"):
            v = _i(r.get(col))
            p["pit"][col] += v
            pseason[key][col] += v
        pteams[key].add(r["teamID"])
    for (pid, year), s in pseason.items():
        m = P[pid]["season_max"]
        m["w"] = max(m["w"], s["W"])
        m["so"] = max(m["so"], s["SO"])
        m["sv"] = max(m["sv"], s["SV"])
        team_g = max(team_games.get((year, t), 0) for t in pteams[(pid, year)])
        if team_g and s["IPouts"] >= 3 * team_g:
            era = 27 * s["ER"] / s["IPouts"]
            m["era_q"] = era if not m.get("era_q") else min(m["era_q"], era)

    award_map = {"Most Valuable Player": "mvp", "Cy Young Award": "cy", "Rookie of the Year": "roy",
                 "Gold Glove": "gg", "Silver Slugger": "ss", "World Series MVP": "wsmvp"}
    for r in _rows("AwardsPlayers"):
        p, a = P.get(r["playerID"]), award_map.get(r["awardID"])
        if p and a:
            p["awards"][a] += 1
    for r in _rows("AllstarFull"):   # MLB All-Star Games only (not the Negro Leagues East-West games)
        if r["playerID"] in P and r["lgID"] in ("AL", "NL"):
            P[r["playerID"]]["allstar"].add(r["yearID"])
    for r in _rows("HallOfFame"):
        p = P.get(r["playerID"])
        if p and r["category"] == "Player":
            p["hof_ballot"] = True
            if r["inducted"] == "Y":
                p["hof"] = True

    for p in P.values():
        b, pt = p["bat"], p["pit"]
        p["ba"] = b["H"] / b["AB"] if b["AB"] else 0.0
        p["era"] = 27 * pt["ER"] / pt["IPouts"] if pt["IPouts"] else 99.0
        p["first"] = min(p["years"]) if p["years"] else 0
        p["last"] = max(p["years"]) if p["years"] else 0
        p["seasons"] = len(p["years"])
        p["n_franch"] = sum(1 for g in p["franch"].values() if g > 0)
        p["n_allstar"] = len(p["allstar"])
        p["fame"] = fame(p)
    return {k: v for k, v in P.items() if v["g"] > 0}


def fame(p: dict) -> float:
    """How recognisable a player is (for choosing puzzle players; not shown).

    All-Star selections, the Hall of Fame and major awards dominate; long careers and big
    counting stats add; careers that ended before 1946 are discounted and those since 1980
    nudged up, because that is what today's fans know."""
    a, b, pt = p["awards"], p["bat"], p["pit"]
    score = (4 * len(p["allstar"]) + 25 * p["hof"] + 8 * a["mvp"] + 6 * a["cy"] + 3 * a["roy"]
             + 0.7 * a["gg"] + 0.7 * a["ss"] + 2 * a["wsmvp"]
             + p["g"] / 200 + b["HR"] / 40 + b["H"] / 300 + pt["W"] / 15 + pt["SV"] / 40)
    if p.get("last", 0) < 1946:
        score *= 0.65
    if p.get("last", 0) >= 1980:
        score *= 1.25
    if p.get("last", 0) >= 2005:
        score *= 1.15
    return round(score, 2)
