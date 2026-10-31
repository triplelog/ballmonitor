"""Opponent ratings for DAD, built from game results (stdlib only).

DAD needs every opponent's rating on the same scale as the baseline: net points (goals,
runs) per game against an average team on a neutral field. `fit_ratings` computes the
classic least-squares margin rating (SRS / Massey 1997) with one shared home advantage:

    margin(home - away) = r_home - r_away + h * (not neutral) + noise

solved by simple fixed-point iteration (no numpy needed). Ratings are centred so the
mean team is 0. `ridge` adds `ridge` phantom 0-margin games against an average team,
which keeps early-season ratings finite and shrinks them toward 0.

Used by fetch.py (reference ratings and examples) and research.py (first-half ratings
that are known at the split date). The model itself never reads data.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Game:
    league: str
    season: int
    date: str          # YYYY-MM-DD
    season_type: int   # 2 = regular season, 3 = postseason (ESPN convention)
    home: str
    away: str
    home_score: float
    away_score: float
    neutral: bool

    @property
    def margin(self) -> float:
        return self.home_score - self.away_score


@dataclass
class Fit:
    ratings: dict[str, float]
    home_advantage: float
    residual_sd: float   # sqrt(SSR / (games - teams - 1)), i.e. per-game noise
    games: int


GAME_FIELDS = ["league", "season", "date", "season_type", "home", "away",
               "home_score", "away_score", "neutral"]


def read_games(path: Path) -> list[Game]:
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.append(Game(r["league"], int(r["season"]), r["date"], int(r["season_type"]),
                            r["home"], r["away"], float(r["home_score"]), float(r["away_score"]),
                            r["neutral"] in ("1", "True", "true")))
    return out


def write_games(path: Path, games: Iterable[Game]) -> int:
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(GAME_FIELDS)
        for g in games:
            w.writerow([g.league, g.season, g.date, g.season_type, g.home, g.away,
                        f"{g.home_score:g}", f"{g.away_score:g}", int(g.neutral)])
            n += 1
    return n


def fit_ratings(games: list[Game], ridge: float = 0.0, iterations: int = 300,
                fixed_home_advantage: float | None = None) -> Fit:
    """Least-squares margin ratings + home advantage (see module docstring)."""
    teams = sorted({g.home for g in games} | {g.away for g in games})
    r = {t: 0.0 for t in teams}
    played: dict[str, list[tuple[str, float, float]]] = {t: [] for t in teams}
    for g in games:
        loc = 0.0 if g.neutral else 1.0
        played[g.home].append((g.away, g.margin, loc))
        played[g.away].append((g.home, -g.margin, -loc))
    h = fixed_home_advantage or 0.0
    venue = [g for g in games if not g.neutral]
    for _ in range(iterations):
        if fixed_home_advantage is None and venue:
            h = sum(g.margin - (r[g.home] - r[g.away]) for g in venue) / len(venue)
        new = {}
        for t, lst in played.items():
            new[t] = sum(m - h * loc + r[o] for o, m, loc in lst) / (len(lst) + ridge)
        mean = sum(new.values()) / len(new) if new else 0.0
        delta = max((abs(new[t] - mean - r[t]) for t in teams), default=0.0)
        r = {t: v - mean for t, v in new.items()}
        if delta < 1e-7:
            break
    ssr = sum((g.margin - (r[g.home] - r[g.away] + (0.0 if g.neutral else h))) ** 2 for g in games)
    dof = max(len(games) - len(teams) - 1, 1)
    return Fit(r, h, math.sqrt(ssr / dof), len(games))


def team_games(games: list[Game], team: str) -> list[tuple[Game, str, float, str]]:
    """(game, opponent, margin from `team`'s side, location) for every game `team` played."""
    out = []
    for g in games:
        if g.home == team:
            out.append((g, g.away, g.margin, "neutral" if g.neutral else "home"))
        elif g.away == team:
            out.append((g, g.home, -g.margin, "neutral" if g.neutral else "away"))
    return out
