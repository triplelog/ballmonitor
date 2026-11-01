"""Public page: a strength leaderboard for the latest finished season of each league.

Runs the model's multi-team mode (predict() with `teams`) on the committed game files
(data/games_<league>.csv) and power ratings (data/team_ratings.csv), the same way fetch.py
builds the leaderboard examples: regular season only, opponent rating = the opponent's
end-of-regular-season rating. Built at site-build time; the page only displays the numbers.
"""

from __future__ import annotations

import csv

from ballmonitor.core import views as V

from .fetch import LEAGUE_SPORT
from .ratings import read_games

# league, page label, how its seasons are named, default team to compare with (model preset),
# plain name of that team, unit word.
LEAGUES = [
    ("cfb", "College football", "single", "bubble", "a playoff bubble team", "points"),
    ("nfl", "NFL", "single", "average", "an average team", "points"),
    ("mbb", "Men's college basketball", "split", "bubble", "an NCAA tournament bubble team", "points"),
    ("wbb", "Women's college basketball", "split", "bubble", "an NCAA tournament bubble team", "points"),
    ("nba", "NBA", "split", "average", "an average team", "points"),
    ("mlb", "MLB", "single", "bubble", "a wild-card bubble team", "runs"),
    ("epl", "Premier League", "split", "average", "an average team", "goals"),
    ("laliga", "La Liga", "split", "average", "an average team", "goals"),
    ("bundesliga", "Bundesliga", "split", "average", "an average team", "goals"),
    ("seriea", "Serie A", "split", "average", "an average team", "goals"),
    ("ligue1", "Ligue 1", "split", "average", "an average team", "goals"),
]
COLLEGE = {"cfb", "mbb", "wbb"}


def _season_name(season: int, style: str) -> str:
    return f"{season - 1}-{str(season)[-2:]}" if style == "split" else str(season)


def _ratings(path) -> dict[tuple[str, int], dict[str, float]]:
    out: dict[tuple[str, int], dict[str, float]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.setdefault((r["league"], int(r["season"])), {})[r["team"]] = float(r["rating"])
    return out


def _team_games(games, team: str, ratings: dict[str, float]) -> list[dict]:
    rows = []
    for g in games:
        if team not in (g.home, g.away):
            continue
        home = g.home == team
        opp = g.away if home else g.home
        if opp not in ratings:
            continue  # e.g. a non-Division I opponent with no rating
        ts, os_ = (g.home_score, g.away_score) if home else (g.away_score, g.home_score)
        rows.append({"date": g.date, "opponent": opp, "opponent_rating": ratings[opp],
                     "team_score": ts, "opponent_score": os_,
                     "location": "neutral" if g.neutral else ("home" if home else "away")})
    return rows


def _league(model, league: str, label: str, style: str, baseline: str, vs: str, unit: str,
            all_ratings) -> tuple[str, list[dict], str] | None:
    path = model.dir / "data" / f"games_{league}.csv"
    if not path.exists():
        return None
    games = read_games(path)
    season = max(s for (lg, s) in all_ratings if lg == league)
    ratings = all_ratings[(league, season)]
    games = [g for g in games if g.season == season and g.season_type == 2]
    teams = [{"name": t, "games": tg} for t in sorted(ratings) if (tg := _team_games(games, t, ratings))]
    # All-Star / exhibition sides (NBA "Team Stars", MLB "American All-Stars") play a game or
    # three: keep only teams with at least half the league's typical schedule.
    typical = sorted(len(t["games"]) for t in teams)[len(teams) // 2]
    teams = [t for t in teams if len(t["games"]) >= typical / 2]
    board = model.predict({"sport": LEAGUE_SPORT[league], "baseline": baseline,
                           "teams": teams}).extras["leaderboard"]
    soccer = LEAGUE_SPORT[league] == "soccer"
    rows = [{
        "rank": i,
        "team": r["team"],
        "record": (f"{r['wins']}-{r['draws']}-{r['losses']}" if soccer else f"{r['wins']}-{r['losses']}"),
        "strength": r["strength_rating"],
        "beat": r["win_prob_vs_default"],
        "wins_above": r["total_wad"],
    } for i, r in enumerate(board, 1)]
    season_name = _season_name(season, style)
    short = vs.replace("an NCAA tournament ", "a ").replace("a playoff ", "a ").replace("a wild-card ", "a ")
    table = V.table(
        f"board_{league}", f"{label}, {season_name} regular season",
        [V.col("rank", "Rank", "int"), V.col("team", "Team"),
         V.col("record", "Record (W-D-L)" if soccer else "Record"),
         V.col("strength", f"Strength ({unit}/game)", "signed", decimals=2 if unit != "points" else 1),
         V.col("beat", f"Chance to beat {short}", "pct", bar=True),
         V.col("wins_above", f"Wins above {short}", "signed", decimals=1)],
        rows,
        subtitle=(f"Strength: how many {unit} per game better than an average team, after allowing for "
                  f"opponents and home field. Chance to beat {vs} on a neutral field, and how many more "
                  f"games the team won than {vs} would have against the same schedule."),
        note=("Records count regular-season games against Division I opponents only. " if league in COLLEGE else
              "Regular season only, from ESPN's scoreboards (a few games may be missing). ")
             + ("A draw counts as half a win." if soccer else ""),
        search=True, page_size=25 if len(rows) > 40 else 0)
    return f"{label} ({season_name})", [table], season_name


def page(model) -> dict:
    all_ratings = _ratings(model.dir / "data" / "team_ratings.csv")
    options, seasons = [], {}
    for spec in LEAGUES:
        out = _league(model, *spec, all_ratings)
        if out:
            options.append(V.option(out[0], out[1]))
            seasons.setdefault(out[2], []).append(spec[1])
    by_league = V.picker(
        "by_league", "Team strength by league", "League", options,
        subtitle="Pick a league to see every team ranked by how good it really was, not just its record.")
    return V.page(
        title="How good was every team, really?",
        summary="Every team in eleven leagues ranked by schedule-adjusted strength for the latest finished season.",
        sport="More sports",
        order=50,
        updated="Latest finished regular seasons (" + ", ".join(seasons) + ")",
        how=("We start from each game's final margin, then adjust for how strong the opponent was and where "
             "the game was played, and pull small samples a little toward average. Comparing that with a "
             "benchmark team (a tournament bubble team in college, an average team in most pro leagues) "
             "gives the chance to beat it and the wins above it. Results come from ESPN and football-data.co.uk."),
        views=[by_league],
    )
