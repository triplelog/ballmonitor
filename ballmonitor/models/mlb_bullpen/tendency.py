"""Team and league bullpen-usage tendencies (pre-game, rolling).

`rolling_usage` walks team-games in date order and, for each one, reports how many pool
relievers the team used per game over its last `team_games` games and how many the whole
league used per team-game over the last `league_days` days -- using only games on EARLIER
dates (a doubleheader's game 2 does not see game 1). fetch.py writes these as the input
columns `team_recent_games`, `team_recent_relievers` and `league_recent_relievers`;
research.py recomputes them for its window grid.

`log_usage_ratio` turns them into the model's tendency term:

    shrunk = (n * team + k * league) / (n + k),   k = tendency_prior_games
    log_ratio = ln(shrunk / bullpen_baseline_relievers)

i.e. the team's recent relievers per game shrunk toward the recent league average
(empirical Bayes with k pseudo-games), relative to the 2025 level the simulator's hook
settings were tuned to. Stdlib only.
"""

from __future__ import annotations

import math
from collections import deque
from datetime import date, timedelta
from typing import Any, Iterable


def pool_used(row: dict) -> int:
    """Pool relievers who pitched in a team-game (outcome; only for later games' inputs)."""
    import json

    used = {x for x in row["actual_relievers_used"].split(";") if x}
    pool = {r["name"] for r in json.loads(row["relievers_json"])}
    return len(used & pool)


def rolling_usage(rows: Iterable[dict], team_games: int, league_days: int) -> dict[tuple[str, str], dict]:
    """{(game_pk, team): {"team_recent_games", "team_recent_relievers",
    "league_recent_relievers"}} from strictly earlier dates. Rows need `game_pk`, `team`,
    `game_date` and either `pool_used` or the outcome columns to compute it."""
    by_date: dict[str, list[tuple[str, str, str, int]]] = {}
    for r in rows:
        used = int(r["pool_used"]) if "pool_used" in r and r["pool_used"] != "" else pool_used(r)
        by_date.setdefault(r["game_date"], []).append((str(r["game_pk"]), r["team"], r["game_date"], used))
    team_hist: dict[str, deque] = {}
    league: deque = deque()  # (date, used) within league_days
    league_sum = 0
    out: dict[tuple[str, str], dict] = {}
    for d in sorted(by_date):
        cutoff = (date.fromisoformat(d) - timedelta(days=league_days)).isoformat()
        while league and league[0][0] < cutoff:
            league_sum -= league.popleft()[1]
        league_mean = league_sum / len(league) if league else None
        for pk, team, _, _ in by_date[d]:
            h = team_hist.get(team)
            n = len(h) if h else 0
            out[(pk, team)] = {
                "team_recent_games": n,
                "team_recent_relievers": round(sum(h) / n, 3) if n else None,
                "league_recent_relievers": round(league_mean, 3) if league_mean is not None else None,
            }
        for _, team, _, used in by_date[d]:
            team_hist.setdefault(team, deque(maxlen=team_games)).append(used)
            league.append((d, used))
            league_sum += used
    return out


def _num(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    v = float(value)
    return None if math.isnan(v) else v


def shrunk_relievers(team: Any, n_games: Any, league: Any, params: Any) -> float | None:
    """Team relievers per game shrunk toward the league mean (k = tendency_prior_games).
    Missing league mean -> bullpen_baseline_relievers; missing team -> league; nothing -> None."""
    team, league, n = _num(team), _num(league), _num(n_games) or 0.0
    if team is None and league is None:
        return None
    base = league if league is not None else float(params.bullpen_baseline_relievers)
    if team is None or n <= 0:
        return base
    k = float(params.tendency_prior_games)
    return (n * team + k * base) / (n + k)


def log_usage_ratio(team: Any, n_games: Any, league: Any, params: Any) -> tuple[float, float | None]:
    """(ln(shrunk / bullpen_baseline_relievers), shrunk); (0, None) without any tendency input."""
    s = shrunk_relievers(team, n_games, league, params)
    if s is None or s <= 0:
        return 0.0, None
    return math.log(s / float(params.bullpen_baseline_relievers)), s
