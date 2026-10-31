"""
Power Rankings Provider & Management:
Allows seamless loading, switching, and blending of different power rating sets
(e.g., SP+, ESPN FPI, Elo, Sagarin, or custom CSV/JSON files).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

try:
    from .config import DATA_DIR
except (ImportError, ValueError):
    from config import DATA_DIR
try:
    from .domain import Team
except (ImportError, ValueError):
    from domain import Team

class RatingManager:
    """Manages loading, validating, and applying power ratings to teams."""

    @staticmethod
    def load_ratings(
        source: str | Path | dict[str, float] | None,
        teams: list[Team]
    ) -> dict[str, float]:
        """
        Loads power ratings from a source and returns a map of team_id -> rating.

        Sources can be:
        - None / "default": Uses the ratings stored in teams.json (ESPN FPI)
        - "fpi": ESPN Football Power Index (data/ratings_fpi.csv, built by fetch.py)
        - "results": results-only ridge rating from this season's scores (data/ratings_results.csv)
        - Path / string ending in .csv: Loads CSV with columns (team_id, rating) or (team, rating)
        - Path / string ending in .json: Loads JSON mapping team_id -> rating
        - dict: Direct mapping of team_id -> rating
        """
        team_id_lookup = {t.id: t.id for t in teams}
        # Also index by lowercase name for fuzzy CSV matching
        name_lookup = {t.name.lower(): t.id for t in teams}
        for t in teams:
            name_lookup[t.id.lower().replace("_", " ")] = t.id
            name_lookup[t.id.lower()] = t.id

        if source is None or source == "default":
            return {t.id: t.rating for t in teams}

        if isinstance(source, dict):
            ratings = {}
            for k, v in source.items():
                t_id = team_id_lookup.get(k) or name_lookup.get(k.lower())
                if t_id:
                    ratings[t_id] = float(v)
            return RatingManager._fill_missing(ratings, teams)

        # String or Path
        source_str = str(source).strip().lower()

        # Check built-in rating files
        builtin_map = {
            "fpi": DATA_DIR / "ratings_fpi.csv",
            "results": DATA_DIR / "ratings_results.csv",
        }

        path: Path | None = None
        if source_str in builtin_map:
            path = builtin_map[source_str]
        else:
            p = Path(source)
            if p.exists():
                path = p

        if path and path.exists():
            if path.suffix.lower() == ".csv":
                return RatingManager._load_from_csv(path, teams, name_lookup)
            elif path.suffix.lower() == ".json":
                with open(path, "r") as f:
                    data = json.load(f)
                return RatingManager.load_ratings(data, teams)

        raise FileNotFoundError(
            f"Ratings source '{source}' not recognized. "
            f"Use 'default', 'fpi', 'results', or provide a path to a .csv/.json file."
        )

    @staticmethod
    def _load_from_csv(path: Path, teams: list[Team], name_lookup: dict[str, str]) -> dict[str, float]:
        ratings: dict[str, float] = {}
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return RatingManager._fill_missing(ratings, teams)

            # Determine column indices
            header_lower = [c.strip().lower() for c in header]
            team_col = 0
            rating_col = 1
            for i, col in enumerate(header_lower):
                if col in ("team", "team_id", "school", "name", "id"):
                    team_col = i
                elif col in ("rating", "rating_margin", "fpi", "results_rating", "pts"):
                    rating_col = i

            for row in reader:
                if not row or len(row) <= max(team_col, rating_col):
                    continue
                team_raw = row[team_col].strip()
                try:
                    val = float(row[rating_col].strip())
                except ValueError:
                    continue

                t_id = name_lookup.get(team_raw.lower())
                if t_id:
                    ratings[t_id] = val

        return RatingManager._fill_missing(ratings, teams)

    @staticmethod
    def _fill_missing(ratings: dict[str, float], teams: list[Team]) -> dict[str, float]:
        """Fills in missing teams using their baseline rating from teams.json."""
        complete = {}
        for t in teams:
            if t.id in ratings:
                complete[t.id] = ratings[t.id]
            else:
                complete[t.id] = t.rating
        return complete

    @staticmethod
    def blend_ratings(
        rating_sets: list[tuple[dict[str, float], float]],
        teams: list[Team]
    ) -> dict[str, float]:
        """
        Blends multiple rating sets according to assigned weights:
        rating_sets = [(ratings_dict_1, 0.5), (ratings_dict_2, 0.5)]
        """
        total_weight = sum(w for _, w in rating_sets)
        blended = {}
        for t in teams:
            t_id = t.id
            weighted_sum = sum(rset.get(t_id, t.rating) * w for rset, w in rating_sets)
            blended[t_id] = weighted_sum / total_weight if total_weight > 0 else t.rating
        return blended
