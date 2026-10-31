"""Game records and loaders for college_diamond (stdlib only).

The built files in data/ (see fetch.py and MODEL.md "Data") are read here; the model,
the simulation and research.py all go through these helpers.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

GAME_FIELDS = ["season", "date", "game_type", "home", "away", "home_score", "away_score",
               "neutral", "innings", "conf_game", "round"]


@dataclass(frozen=True)
class Game:
    season: int
    date: str            # YYYY-MM-DD
    game_type: str       # R regular season, C conference tournament, N NCAA tournament
    home: str            # team id (NCAA seo name); listed home team when neutral
    away: str
    home_score: int
    away_score: int
    neutral: bool        # known neutral site (baseball: from boydsworld locations)
    innings: int         # 0 = regulation/unknown, else the extra-inning count
    conf_game: bool      # both teams in the same conference (and a regular-season game)
    round: str           # NCAA round description ("Regionals", ...) or ""

    @property
    def margin(self) -> int:
        return self.home_score - self.away_score

    @property
    def day(self) -> dt.date:
        return dt.date.fromisoformat(self.date)

    @property
    def weekday(self) -> int:
        """Monday = 0 ... Sunday = 6."""
        return self.day.weekday()


def write_games(path: Path, games) -> int:
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(GAME_FIELDS)
        for g in games:
            w.writerow([g.season, g.date, g.game_type, g.home, g.away, g.home_score, g.away_score,
                        int(g.neutral), g.innings, int(g.conf_game), g.round])
            n += 1
    return n


@lru_cache(maxsize=4)
def load_games(sport: str) -> tuple[Game, ...]:
    out = []
    with open(DATA_DIR / f"games_{sport}.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.append(Game(int(r["season"]), r["date"], r["game_type"], r["home"], r["away"],
                            int(r["home_score"]), int(r["away_score"]), r["neutral"] == "1",
                            int(r["innings"] or 0), r["conf_game"] == "1", r["round"]))
    return tuple(out)


@lru_cache(maxsize=4)
def load_teams(sport: str) -> dict[int, dict[str, dict]]:
    """season -> team id -> {name, conference, source}."""
    out: dict[int, dict[str, dict]] = {}
    with open(DATA_DIR / f"teams_{sport}.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(int(r["season"]), {})[r["team"]] = {
                "name": r["name"], "conference": r["conference"], "source": r["source"]}
    return out


@lru_cache(maxsize=2)
def load_formats() -> dict:
    return json.loads((DATA_DIR / "conference_formats.json").read_text())


@lru_cache(maxsize=2)
def load_tournaments() -> dict:
    return json.loads((DATA_DIR / "ncaa_tournaments.json").read_text())


def season_games(sport: str, season: int) -> list[Game]:
    return [g for g in load_games(sport) if g.season == season]
