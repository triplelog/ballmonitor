"""
On3 Ingestion Client using SportsDataVerse

Fetches consensus player rankings and scholarship offer lists directly from On3 RDB endpoints:
- Primary class rankings: on3_industry_player_rankings / on3_players_industry_comparision
- Granular team target and offer histories: on3_player_team_targets
"""

from typing import Dict, List, Optional
import sportsdataverse.cfb as cfb

from .base import BaseRecruitingScraper
from ..data_loader import standardize_team_name  # noqa: F401  (re-exported)
from ..models import Recruit
from ..geocoding import CityLocator, get_campus_coords, haversine_miles


class On3Scraper(BaseRecruitingScraper):
    """Client for On3 player rankings and offer lists via sportsdataverse."""

    def __init__(self, city_locator: Optional[CityLocator] = None):
        self.locator = city_locator

    def fetch_recruits_for_year(self, year: int) -> List[Recruit]:
        """Fetch all recruits for a given year."""
        return self.fetch_recruits(year=year)

    def fetch_recruits(
        self, year: int, limit: Optional[int] = None
    ) -> List[Recruit]:
        """
        Fetch recruit profiles and their complete scholarship offers.

        Args:
            year: Recruiting class year (e.g., 2023, 2024).
            limit: Maximum number of recruits to retrieve (None for all available in page 1).
        """
        rankings_df = cfb.on3_industry_player_rankings(year=year, return_as_pandas=True)
        if rankings_df is None or rankings_df.empty:
            return []

        if limit is not None:
            rankings_df = rankings_df.head(limit)

        recruits: List[Recruit] = []
        for _, row in rankings_df.iterrows():
            recruit = self._parse_recruit_row(year=year, row=row)
            if recruit:
                recruits.append(recruit)

        return recruits

    def _parse_recruit_row(self, year: int, row) -> Optional[Recruit]:
        """Fetch target offers and build a Recruit object from a rankings row."""
        person_key = row.get("person_key")
        if not person_key:
            return None

        name = str(row.get("person_name", "")).strip()
        pos = str(row.get("person_position_abbreviation", "")).strip()
        hometown = str(row.get("person_home_town_name", "")).strip()
        slug = str(row.get("person_slug", "")).strip()
        url = f"https://www.on3.com/db/{slug}/" if slug else ""

        # Consensus stars
        stars = 3
        try:
            val = row.get("person_rating_consensus_stars")
            if val is not None and not (isinstance(val, float) and str(val) == "nan"):
                stars = int(val)
        except (ValueError, TypeError):
            stars = 3

        # Coordinates
        lat, lon = 0.0, 0.0
        if self.locator and hometown:
            lat, lon = self.locator.locate(hometown)

        # Retrieve granular offers and commit status from team targets
        try:
            targets_df = cfb.on3_player_team_targets(
                player_key=int(person_key), return_as_pandas=True
            )
        except Exception:
            targets_df = None

        committed_school = ""
        offers: List[str] = []
        distance_miles = 0.0

        if targets_df is not None and not targets_df.empty:
            # Committed / Enrolled school
            committed_mask = targets_df["status"].isin(["Enrolled", "Signed", "Committed"])
            if committed_mask.any():
                commit_row = targets_df[committed_mask].iloc[0]
                committed_school = standardize_team_name(
                    commit_row.get("team_name", ""),
                    commit_row.get("team_slug", "")
                )
                try:
                    distance_miles = float(commit_row.get("distance", 0.0) or 0.0)
                except (ValueError, TypeError):
                    distance_miles = 0.0

            # Offering schools
            for _, t_row in targets_df.iterrows():
                t_name = standardize_team_name(
                    t_row.get("team_name", ""),
                    t_row.get("team_slug", "")
                )
                if t_name and t_name != committed_school and t_name not in offers:
                    offers.append(t_name)

        # Fallback for committed school if not found in targets
        if not committed_school:
            raw_team = str(row.get("college_team_name", "")).strip()
            # Clean common mascot suffix if needed
            for suffix in [" Buckeyes", " Bulldogs", " Gators", " Tigers", " Longhorns", " Crimson Tide"]:
                if raw_team.endswith(suffix):
                    raw_team = raw_team[:-len(suffix)].strip()
            committed_school = raw_team

        # If campus distance wasn't pre-computed, calculate it if coordinates exist
        if distance_miles == 0.0 and lat != 0.0 and lon != 0.0 and committed_school:
            campus_coords = get_campus_coords(committed_school)
            if campus_coords:
                distance_miles = haversine_miles(lat, lon, campus_coords[0], campus_coords[1])

        return Recruit(
            url=url,
            year=year,
            name=name,
            position=pos,
            hometown=hometown,
            stars=stars,
            committed_team=committed_school,
            offers=offers,
            latitude=lat,
            longitude=lon,
            distance_miles=distance_miles,
        )
