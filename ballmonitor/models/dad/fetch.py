"""Download real game results for DAD and build data/games_<league>.csv + team ratings.

    ballmonitor fetch dad            # download what is missing, then rebuild
    ballmonitor fetch dad --offline  # rebuild from data/raw/ only (or verify built CSVs)

Sources (public, no key):
- ESPN site API scoreboards, one request per day:
  https://site.api.espn.com/apis/site/v2/sports/<path>/scoreboard?dates=YYYYMMDD
  Leagues: NCAA men's and women's D-I basketball (groups=50), FBS college football
  (groups=80), NFL, NBA, MLB. Only completed regular-season (type 2) and postseason
  (type 3) games are kept. Days are cached in data/raw/espn/<league>/<date>.json as the
  trimmed game rows (not the full API response, which is ~100x larger).
- football-data.co.uk season CSVs (Premier League, La Liga, Bundesliga, Serie A,
  Ligue 1): https://www.football-data.co.uk/mmz4281/<yyyy>/<code>.csv, cached in
  data/raw/football_data/.

College baseball and softball are not fetched: ESPN's scoreboards for them carry only a
fraction of D-I games, too few for ratings.

Built files (documented in MODEL.md):
- data/games_<league>.csv   league,season,date,season_type,home,away,home_score,
                            away_score,neutral. College leagues keep only games where
                            both teams played >= MIN_TEAM_GAMES games in the file
                            (drops non-D-I / FCS opponents).
- data/team_ratings.csv     end-of-regular-season least-squares margin ratings per
                            league-season (ratings.py) — hindsight values, fine for
                            describing a finished season, NOT for forecasting.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Generator

from ballmonitor.models.dad.ratings import Game, fit_ratings, read_games, write_games

ESPN = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={day}&limit=500{extra}"
FOOTBALL_DATA = "https://www.football-data.co.uk/mmz4281/{code}/{div}.csv"
UA = {"User-Agent": "Mozilla/5.0"}

# league -> (ESPN path, extra query, sport alias for the model, (start, end) of season Y,
#            seasons). Season Y = the year the season ends (basketball) or starts (football).
ESPN_LEAGUES = {
    "mbb": ("basketball/mens-college-basketball", "&groups=50", "basketball",
            lambda y: (dt.date(y - 1, 11, 1), dt.date(y, 4, 10)), list(range(2016, 2027))),
    "wbb": ("basketball/womens-college-basketball", "&groups=50", "wbb",
            lambda y: (dt.date(y - 1, 11, 1), dt.date(y, 4, 10)), list(range(2016, 2027))),
    # NBA 2020 and 2021 (COVID bubble / shortened) are skipped.
    "nba": ("basketball/nba", "", "basketball",
            lambda y: (dt.date(y - 1, 10, 1), dt.date(y, 4, 20)),
            [2016, 2017, 2018, 2019, 2022, 2023, 2024, 2025, 2026]),
    # 2020 college football (COVID: cancelled/conference-only schedules) is skipped.
    "cfb": ("football/college-football", "&groups=80", "football",
            lambda y: (dt.date(y, 8, 20), dt.date(y + 1, 1, 22)),
            [2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025]),
    "nfl": ("football/nfl", "", "football",
            lambda y: (dt.date(y, 9, 1), dt.date(y + 1, 2, 15)), list(range(2015, 2026))),
    # 2020 MLB (60-game season) is skipped.
    "mlb": ("baseball/mlb", "", "mlb",
            lambda y: (dt.date(y, 3, 15), dt.date(y, 11, 5)),
            [2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]),
}
SOCCER_LEAGUES = {"epl": "E0", "laliga": "SP1", "bundesliga": "D1", "seriea": "I1", "ligue1": "F1"}
SOCCER_SEASONS = list(range(2016, 2027))  # season Y = Y-1/Y, e.g. 2024 = 2023-24
MIN_TEAM_GAMES = {"mbb": 15, "wbb": 15, "cfb": 8}
LEAGUE_SPORT = {k: v[2] for k, v in ESPN_LEAGUES.items()} | {k: "soccer" for k in SOCCER_LEAGUES}


def _get(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("unreachable")


def _espn_day(path: str, extra: str, day: dt.date) -> list[dict]:
    data = json.loads(_get(ESPN.format(path=path, day=day.strftime("%Y%m%d"), extra=extra)))
    rows = []
    for ev in data.get("events", []):
        comp = ev["competitions"][0]
        if not comp["status"]["type"].get("completed"):
            continue
        stype = int(ev.get("season", {}).get("type", 0))
        if stype not in (2, 3):
            continue
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        if "home" not in sides or "away" not in sides:
            continue
        try:
            hs, as_ = float(sides["home"]["score"]), float(sides["away"]["score"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({
            "season_year": int(ev.get("season", {}).get("year", 0)),
            "season_type": stype,
            "date": ev["date"][:10],
            "home": sides["home"]["team"]["displayName"],
            "away": sides["away"]["team"]["displayName"],
            "home_score": hs, "away_score": as_,
            "neutral": bool(comp.get("neutralSite")),
        })
    return rows


def _espn_league(raw: Path, league: str, offline: bool) -> tuple[list[Game], int]:
    path, extra, _, window, seasons = ESPN_LEAGUES[league]
    cache = raw / "espn" / league
    cache.mkdir(parents=True, exist_ok=True)
    jobs = []
    for y in seasons:
        start, end = window(y)
        end = min(end, dt.date.today() - dt.timedelta(days=1))
        d = start
        while d <= end:
            jobs.append((y, d))
            d += dt.timedelta(days=1)

    def load(job):
        y, d = job
        f = cache / f"{d:%Y%m%d}.json"
        if f.exists():
            return y, json.loads(f.read_text()), False
        if offline:
            return y, None, False
        rows = _espn_day(path, extra, d)
        f.write_text(json.dumps(rows))
        return y, rows, True

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(load, jobs))
    downloaded = sum(1 for *_, new in results if new)
    games, seen = [], set()
    for y, rows, _ in results:
        for r in rows or []:
            # The scoreboard for day D can include games stamped D+1 (UTC); de-duplicate.
            key = (r["date"], r["home"], r["away"], r["home_score"], r["away_score"])
            if key in seen:
                continue
            seen.add(key)
            # Basketball: ESPN season year = end year. Football/MLB: year = start year.
            if r["season_year"] and r["season_year"] != y:
                continue
            games.append(Game(league, y, r["date"], r["season_type"], r["home"], r["away"],
                              r["home_score"], r["away_score"], r["neutral"]))
    return games, downloaded


def _parse_fd_date(s: str) -> str:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"bad date {s!r}")


def _soccer_league(raw: Path, league: str, offline: bool) -> tuple[list[Game], int]:
    div = SOCCER_LEAGUES[league]
    cache = raw / "football_data"
    cache.mkdir(parents=True, exist_ok=True)
    games, downloaded = [], 0
    for y in SOCCER_SEASONS:
        code = f"{(y - 1) % 100:02d}{y % 100:02d}"
        f = cache / f"{div}_{code}.csv"
        if not f.exists():
            if offline:
                continue
            try:
                f.write_bytes(_get(FOOTBALL_DATA.format(code=code, div=div)))
                downloaded += 1
            except Exception:
                continue
        text = f.read_bytes().decode("utf-8-sig", errors="replace")
        for r in csv.DictReader(text.splitlines()):
            if not r.get("HomeTeam") or not (r.get("FTHG") or "").strip():
                continue
            games.append(Game(league, y, _parse_fd_date(r["Date"]), 2, r["HomeTeam"].strip(),
                              r["AwayTeam"].strip(), float(r["FTHG"]), float(r["FTAG"]), False))
    return games, downloaded


def _filter_teams(games: list[Game], league: str) -> list[Game]:
    need = MIN_TEAM_GAMES.get(league)
    if not need:
        return games
    out = []
    for season in sorted({g.season for g in games}):
        sg = [g for g in games if g.season == season]
        n = Counter([g.home for g in sg] + [g.away for g in sg])
        keep = {t for t, c in n.items() if c >= need}
        out += [g for g in sg if g.home in keep and g.away in keep]
    return out


def build_ratings(data_dir: Path, leagues: list[str]) -> int:
    rows = []
    for league in leagues:
        f = data_dir / f"games_{league}.csv"
        if not f.exists():
            continue
        games = read_games(f)
        for season in sorted({g.season for g in games}):
            reg = [g for g in games if g.season == season and g.season_type == 2]
            if not reg:
                continue
            fit = fit_ratings(reg)
            rec = Counter()
            for g in reg:
                for team, m in ((g.home, g.margin), (g.away, -g.margin)):
                    rec[(team, "w" if m > 0 else "l" if m < 0 else "d")] += 1
                    rec[(team, "m")] += m
            for team, r in sorted(fit.ratings.items(), key=lambda kv: -kv[1]):
                n = rec[(team, "w")] + rec[(team, "l")] + rec[(team, "d")]
                rows.append([league, LEAGUE_SPORT[league], season, team, n, rec[(team, "w")],
                             rec[(team, "l")], rec[(team, "d")], round(rec[(team, "m")] / n, 3),
                             round(r, 3), round(fit.home_advantage, 3)])
    with open(data_dir / "team_ratings.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["league", "sport", "season", "team", "games", "wins", "losses", "draws",
                    "margin_per_game", "rating", "league_home_advantage"])
        w.writerows(rows)
    return len(rows)


def fetch(model_dir: Path, offline: bool = False) -> Generator[str, None, None]:
    data_dir = model_dir / "data"
    raw = data_dir / "raw"
    data_dir.mkdir(exist_ok=True)
    leagues = list(ESPN_LEAGUES) + list(SOCCER_LEAGUES)

    if offline and not raw.exists():
        missing = [lg for lg in leagues if not (data_dir / f"games_{lg}.csv").exists()]
        if missing:
            raise FileNotFoundError(f"offline: no data/raw/ cache and missing built CSVs: {missing}")
        yield f"Offline and no raw cache: verified {len(leagues)} built game CSVs."
        return

    for league in leagues:
        yield f"{league}: {'reading cache' if offline else 'downloading missing days'}..."
        if league in ESPN_LEAGUES:
            games, new = _espn_league(raw, league, offline)
        else:
            games, new = _soccer_league(raw, league, offline)
        games = _filter_teams(games, league)
        games.sort(key=lambda g: (g.season, g.date, g.home))
        if not games:
            yield f"{league}: no games (kept any existing CSV)."
            continue
        n = write_games(data_dir / f"games_{league}.csv", games)
        yield f"{league}: {new} new downloads; wrote {n} games to data/games_{league}.csv."
    n = build_ratings(data_dir, leagues)
    yield f"Wrote {n} team-season ratings to data/team_ratings.csv."
    yield from build_examples(model_dir)


# ── real examples built from the data ────────────────────────────────────────

# (example file, league, season, teams, baseline, description)
EXAMPLES = [
    ("default", "mbb", 2025, ["Florida Gators"], "bubble",
     "2024-25 Florida Gators men's basketball (national champions), full season"),
    ("multi_team", "mbb", 2025,
     ["Florida Gators", "Houston Cougars", "Duke Blue Devils", "Auburn Tigers"], "bubble",
     "2024-25 men's Final Four teams, full seasons, ranked by DAD"),
    ("wbb_south_carolina_2024", "wbb", 2024, ["South Carolina Gamecocks"], "top4_seed",
     "2023-24 South Carolina Gamecocks women's basketball (38-0 champions)"),
    ("cfb_season", "cfb", 2024, ["Ohio State Buckeyes"], "bubble",
     "2024 Ohio State Buckeyes football (CFP champions), FBS games only"),
    ("mlb_dodgers_2024", "mlb", 2024, ["Los Angeles Dodgers"], "bubble",
     "2024 Los Angeles Dodgers (World Series champions), regular season + postseason"),
    ("mlb_al_east_race", "mlb", 2024,
     ["New York Yankees", "Baltimore Orioles", "Boston Red Sox", "Tampa Bay Rays",
      "Toronto Blue Jays"], "bubble", "2024 AL East, regular season"),
    ("soccer_arsenal_2024", "epl", 2024, ["Arsenal"], "top4",
     "2023-24 Arsenal, Premier League (89 pts, 2nd)"),
    ("soccer_everton_relegation_2024", "epl", 2024, ["Everton"], "relegation_bubble",
     "2023-24 Everton, Premier League (survived in 15th despite an 8-point deduction)"),
]


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def build_examples(model_dir: Path) -> Generator[str, None, None]:
    data_dir = model_dir / "data"
    ratings: dict[tuple[str, int, str], float] = {}
    with open(data_dir / "team_ratings.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ratings[(r["league"], int(r["season"]), r["team"])] = float(r["rating"])
    cache: dict[str, list[Game]] = {}
    for name, league, season, teams, baseline, desc in EXAMPLES:
        f = data_dir / f"games_{league}.csv"
        if not f.exists():
            yield f"example {name}: skipped (no {f.name})"
            continue
        games = cache.setdefault(league, read_games(f))
        games = [g for g in games if g.season == season]
        if len(teams) > 1:  # leaderboard examples: regular season only, keeps them short
            games = [g for g in games if g.season_type == 2]
        out = [
            f"# {desc}.",
            f"# REAL DATA, generated by fetch.py (`ballmonitor fetch dad`) from data/games_{league}.csv",
            "# (ESPN scoreboards / football-data.co.uk). opponent_rating = the opponent's",
            "# end-of-regular-season least-squares margin rating from data/team_ratings.csv",
            "# (hindsight: fine for describing a finished season, not for forecasting).",
            f"sport = {_toml_str(LEAGUE_SPORT[league])}",
            f"baseline = {_toml_str(baseline)}",
        ]
        for team in teams:
            rows = []
            for g in games:
                if team not in (g.home, g.away):
                    continue
                home = g.home == team
                opp = g.away if home else g.home
                if (league, season, opp) not in ratings:
                    continue
                loc = "neutral" if g.neutral else ("home" if home else "away")
                ts, os_ = (g.home_score, g.away_score) if home else (g.away_score, g.home_score)
                rows.append((g.date, opp, ratings[(league, season, opp)], ts, os_, loc,
                             "postseason" if g.season_type == 3 else ""))
            if not rows:
                raise ValueError(f"example {name}: no games for {team} in {league} {season}")
            if len(teams) == 1:
                out.insert(5, f"team = {_toml_str(team)}")
                prefix = "[[games]]"
            else:
                out += ["", "[[teams]]", f"name = {_toml_str(team)}"]
                prefix = "[[teams.games]]"
            for date, opp, rt, ts, os_, loc, note in rows:
                out += ["", prefix, f"date = {_toml_str(date)}", f"opponent = {_toml_str(opp)}",
                        f"opponent_rating = {rt:.2f}", f"team_score = {ts:g}",
                        f"opponent_score = {os_:g}", f"location = {_toml_str(loc)}"]
                if note:
                    out.append(f"notes = {_toml_str(note)}")
        (model_dir / "examples" / f"{name}.toml").write_text("\n".join(out) + "\n", encoding="utf-8")
        yield f"example {name}: {league} {season}, {len(teams)} team(s)"
