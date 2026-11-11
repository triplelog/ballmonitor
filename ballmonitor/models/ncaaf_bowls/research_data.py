"""Past seasons for the ncaaf_bowls accuracy study (research.py), from ESPN's public APIs.

    python -m ballmonitor.models.ncaaf_bowls.research_data [--offline] [--seasons 2016-2025]

The same APIs fetch.py uses for the current season. Raw responses are cached in
data/raw/espn_hist/<season>/ (gitignored); --offline rebuilds the CSVs from that cache.
About 35 requests per season, once. Stdlib only.

Writes (data/historical/):
  games.csv         every completed game with an FBS team: regular season, conference title
                    games and the postseason (ESPN scoreboard)
  fpi_weekly.csv    every ESPN FPI snapshot the API keeps (one per week), with the time ESPN
                    says it was computed (`last_updated`) and ESPN's own season projections
  cfp_rankings.csv  the selection committee's final top 25 (ESPN rankings, poll id 21)

**Hindsight guard.** The snapshot ESPN labels week N holds the ratings after week N's games
(the title-game week moves only the teams that played; the 2023-2025 timestamps agree). The
`last_updated` stamps of 2016-2022 are stale (several weeks share one) and some "week 1"
snapshots were recomputed in December, so research.py goes by the week label, predicts week N
from snapshot N-1, and drops week 1. Seasons before 2016 were back-filled and are not fetched.
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MODEL_DIR = Path(__file__).resolve().parent
RAW = MODEL_DIR / "data" / "raw" / "espn_hist"
OUT = MODEL_DIR / "data" / "historical"

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
FBS_GROUP = 80
CFP_POLL = 21
DEFAULT_SEASONS = range(2016, 2026)
PAUSE_SECONDS = 0.25

# ESPN conference group ids (2016-2025). The old Pac-12 and the 2026 Pac-12 share id 9.
CONFERENCES = {
    "151": "AAC", "1": "ACC", "4": "Big 12", "5": "Big Ten", "12": "CUSA", "18": "Independent",
    "15": "MAC", "17": "MWC", "9": "Pac-12", "8": "SEC", "37": "Sun Belt",
}
FPI_FIELDS = ("fpi", "projectedw", "projectedl", "probwinconf", "probmakeplayoffs", "prob6wins",
              "probwintitle")

GAME_COLS = ["season", "season_type", "week", "kickoff_utc", "espn_id", "home_id", "home", "away_id",
             "away", "home_fbs", "away_fbs", "home_conf", "away_conf", "neutral", "conf_game",
             "title_game", "note", "home_score", "away_score"]
FPI_COLS = ["season", "season_type", "week", "last_updated", "team_id", *FPI_FIELDS]
CFP_COLS = ["season", "poll_date", "rank", "team_id", "wins", "losses"]


class Cache:
    def __init__(self, offline: bool):
        self.offline = offline
        self.requests = 0

    def get(self, url: str, season: int, name: str, optional: bool = False) -> Any:
        path = RAW / str(season) / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text())
        if self.offline:
            if optional:
                return None
            raise FileNotFoundError(f"--offline but {path} is not cached")
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ballmonitor/ncaaf_bowls"})
                with urllib.request.urlopen(req, timeout=30) as res:
                    data = json.loads(res.read())
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and optional:
                    data = None
                    break
                if attempt == 3:
                    raise
            except Exception:
                if attempt == 3:
                    raise
            time.sleep(1.5 * (attempt + 1))
        self.requests += 1
        time.sleep(PAUSE_SECONDS)
        path.write_text(json.dumps(data))
        return data


def _team_id(ref: str) -> str:
    return ref.split("/teams/")[1].split("?")[0]


def _fpi_rows(c: Cache, season: int, stype: int, week: int) -> list[list]:
    rows, page = [], 1
    while True:
        res = c.get(f"{CORE}/seasons/{season}/types/{stype}/weeks/{week}/powerindex?limit=200&page={page}",
                    season, f"fpi_t{stype}_w{week}_p{page}", optional=True)
        if not res or not res.get("items"):
            break
        for item in res["items"]:
            vals = {p["name"]: p.get("value") for p in item.get("predictives", [])}
            if vals.get("fpi") is None:
                continue
            rows.append([season, stype, week, item.get("lastUpdated", ""), _team_id(item["team"]["$ref"]),
                         *("" if vals.get(k) is None else round(float(vals[k]), 3) for k in FPI_FIELDS)])
        if page >= res.get("pageCount", 1):
            break
        page += 1
    return rows


def build_season(c: Cache, season: int) -> tuple[list[list], list[list], list[list]]:
    first = c.get(f"{SITE}/scoreboard?dates={season}&seasontype=2&week=1&groups={FBS_GROUP}&limit=400",
                  season, "sb_t2_w1")
    weeks = [int(e["value"]) for s in first["leagues"][0]["calendar"] if s["value"] == "2" for e in s["entries"]]

    fpi: list[list] = []
    for wk in weeks:
        fpi += _fpi_rows(c, season, 2, wk)
    fpi += _fpi_rows(c, season, 3, 1)
    fbs = {r[4] for r in fpi}

    boards = [(2, wk, c.get(f"{SITE}/scoreboard?dates={season}&seasontype=2&week={wk}&groups={FBS_GROUP}&limit=400",
                            season, f"sb_t2_w{wk}")) for wk in weeks]
    boards.append((3, 1, c.get(f"{SITE}/scoreboard?dates={season}&seasontype=3&week=1&groups={FBS_GROUP}&limit=400",
                               season, "sb_t3_w1")))
    games: dict[str, list] = {}
    for stype, wk, board in boards:
        for ev in board.get("events", []):
            comp = ev["competitions"][0]
            if not comp["status"]["type"].get("completed"):
                continue
            # trust the event's own season and type, not the query that returned it
            if ev["season"]["year"] != season or ev["season"]["type"] != stype:
                continue
            sides = {x["homeAway"]: x for x in comp["competitors"]}
            h, a = sides["home"], sides["away"]
            if h["team"]["id"] not in fbs and a["team"]["id"] not in fbs:
                continue
            note = " ".join(n.get("headline", "") for n in comp.get("notes", []))
            conf = lambda s: CONFERENCES.get(str(s["team"].get("conferenceId", "")), "") if s["team"]["id"] in fbs else ""  # noqa: E731
            games[ev["id"]] = [
                season, stype, wk, ev["date"], ev["id"],
                h["team"]["id"], h["team"].get("location", ""), a["team"]["id"], a["team"].get("location", ""),
                int(h["team"]["id"] in fbs), int(a["team"]["id"] in fbs), conf(h), conf(a),
                int(bool(comp.get("neutralSite"))), int(bool(comp.get("conferenceCompetition"))),
                int(stype == 2 and "Championship" in note), note,
                int(h["score"]), int(a["score"]),
            ]

    # The committee's final ranking: the last regular-season week that has poll 21.
    cfp: list[list] = []
    for wk in sorted(weeks, reverse=True):
        poll = c.get(f"{CORE}/seasons/{season}/types/2/weeks/{wk}/rankings/{CFP_POLL}", season,
                     f"cfp_w{wk}", optional=True)
        if poll and poll.get("ranks"):
            for r in poll["ranks"]:
                w, _, lo = (r.get("record", {}).get("summary") or "-").partition("-")
                cfp.append([season, poll.get("date", "")[:10], r["current"], _team_id(r["team"]["$ref"]), w, lo])
            break
    return sorted(games.values(), key=lambda g: (g[3], g[4])), fpi, cfp


def _write(path: Path, cols: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def main(argv: list[str]) -> None:
    seasons = list(DEFAULT_SEASONS)
    if "--seasons" in argv:
        lo, _, hi = argv[argv.index("--seasons") + 1].partition("-")
        seasons = list(range(int(lo), int(hi or lo) + 1))
    c = Cache(offline="--offline" in argv)
    games, fpi, cfp = [], [], []
    for season in seasons:
        g, f, r = build_season(c, season)
        print(f"{season}: {len(g)} games, {len({(x[1], x[2]) for x in f})} FPI snapshots "
              f"({len({x[4] for x in f})} teams), CFP top {len(r)}  [{c.requests} requests so far]")
        games += g
        fpi += f
        cfp += r
    OUT.mkdir(parents=True, exist_ok=True)
    _write(OUT / "games.csv", GAME_COLS, games)
    _write(OUT / "fpi_weekly.csv", FPI_COLS, fpi)
    _write(OUT / "cfp_rankings.csv", CFP_COLS, cfp)
    print(f"wrote games.csv ({len(games)}), fpi_weekly.csv ({len(fpi)}), cfp_rankings.csv ({len(cfp)})")


if __name__ == "__main__":
    main(sys.argv[1:])
