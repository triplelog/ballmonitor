"""
CollegeFootballData (CFBD) API Ingestion Client

The modern alternative to raw HTML scraping:
- REST API providing structured recruit rankings and school commitment data.
- Documentation: https://collegefootballdata.com
"""

from typing import List, Optional
from .base import BaseRecruitingScraper
from ..models import Recruit


class CFBDScraper(BaseRecruitingScraper):
    """Client for CollegeFootballData API recruiting endpoints."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def fetch_recruits_for_year(self, year: int) -> List[Recruit]:
        """Placeholder for CFBD API recruit ingestion."""
        raise NotImplementedError(
            f"CFBD API ingestion for year {year} is disabled per user request. "
            "Use DataLoader to load existing historical CSV datasets."
        )
