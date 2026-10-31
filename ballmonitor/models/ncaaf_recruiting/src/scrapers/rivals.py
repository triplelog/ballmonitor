"""
Rivals Scraper Module

NOTE: Do not run active scraping until requested by the user.
This module documents the scraping contract and modernization requirements:
1. Selenium 4+ syntax (find_element(By.CLASS_NAME, ...) instead of deprecated find_element_by_*).
2. Explicit waits via WebDriverWait instead of fragile time.sleep().
3. Safe JSON parsing of embedded data attributes rather than dangerous Python eval().
4. Thread pool joining or async HTTP (aiohttp / httpx) to avoid hanging worker threads.
"""

from typing import List, Optional
from .base import BaseRecruitingScraper
from ..models import Recruit


class RivalsScraper(BaseRecruitingScraper):
    """Modernized scraper interface for Rivals.com recruit offer data."""

    def __init__(self, headless: bool = True):
        self.headless = headless

    def fetch_recruits_for_year(self, year: int) -> List[Recruit]:
        """Placeholder for active Rivals scraper execution.
        
        Will be implemented when active scraping is requested.
        """
        raise NotImplementedError(
            f"Active scraping for year {year} is disabled per user request. "
            "Use DataLoader to load existing historical CSV datasets."
        )
