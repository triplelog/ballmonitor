from abc import ABC, abstractmethod
from typing import List
from ..models import Recruit


class BaseRecruitingScraper(ABC):
    """Abstract base class for recruiting data scrapers."""

    @abstractmethod
    def fetch_recruits_for_year(self, year: int) -> List[Recruit]:
        """Fetch all committed recruits and their offer lists for a given season."""
        pass
