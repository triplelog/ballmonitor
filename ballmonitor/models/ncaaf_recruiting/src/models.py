from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class RankingMethod(str, Enum):
    PLACKETT_LUCE = "plackett_luce"
    SEQUENTIAL_ELO = "sequential_elo"


@dataclass
class Recruit:
    """Represents an individual recruit, their commitment, and scholarship offers."""
    url: str
    year: int
    name: str
    position: str
    hometown: str
    stars: int
    committed_team: str
    offers: List[str] = field(default_factory=list)
    latitude: float = 0.0
    longitude: float = 0.0
    score: float = 0.0
    distance_miles: float = 0.0
    points: Dict[int, float] = field(default_factory=dict)
    
    @property
    def all_teams(self) -> List[str]:
        """All schools involved: committed school first, then remaining offering schools."""
        teams = [self.committed_team]
        for t in self.offers:
            if t != self.committed_team and t not in teams:
                teams.append(t)
        return teams

    @property
    def total_offers(self) -> int:
        return len(self.all_teams)

    @property
    def is_multi_offer(self) -> bool:
        return self.total_offers > 1


@dataclass
class TeamRating:
    """Represents a team's evaluated recruiting strength, Elo prestige, and geography."""
    name: str
    elo: float = 1500.0
    offers_count: int = 0
    commits_count: int = 0
    points: Dict[int, float] = field(default_factory=dict)
    total_score: float = 0.0
    rank: int = 0
    avg_recruit_score: float = 0.0
    avg_recruit_distance: float = 0.0
    national_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "name": self.name,
            "elo": round(self.elo, 1),
            "commits": self.commits_count,
            "offers": self.offers_count,
            "total_score": round(self.total_score, 2),
            "avg_recruit_score": round(self.avg_recruit_score, 2),
            "avg_distance_mi": round(self.avg_recruit_distance, 1),
            "national_pct": round(self.national_pct, 1),
            "points_2000": round(self.points.get(2000, 0.0), 2),
            "points_1800": round(self.points.get(1800, 0.0), 2),
            "points_1500": round(self.points.get(1500, 0.0), 2),
        }


@dataclass
class RankingResult:
    """Complete output for a season's recruiting class rankings."""
    year: int
    teams: List[TeamRating]
    recruits: List[Recruit]
    method: RankingMethod = RankingMethod.PLACKETT_LUCE

    @property
    def by_name(self) -> Dict[str, TeamRating]:
        return {t.name.lower(): t for t in self.teams}
