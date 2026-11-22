"""
Positional Recruiting Model: Offense vs. Defense & Run vs. Pass

Breaks down offer-based class rankings across positions:
- Offense vs. Defense allocation
- Run vs. Pass contribution weighting for each position
- Unit-level and phase-level sums and rankings
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from .models import Recruit, TeamRating, RankingResult


@dataclass(frozen=True)
class PositionWeight:
    """Configures a position's unit assignment and run/pass balance."""
    position: str
    unit: str  # "OFFENSE", "DEFENSE", "SPECIAL_TEAMS", "ATHLETE"
    offense_share: float
    defense_share: float
    run_pct: float  # Share of unit contribution assigned to run
    pass_pct: float  # Share of unit contribution assigned to pass


# Domain-informed football position allocations
DEFAULT_POSITION_WEIGHTS: Dict[str, PositionWeight] = {
    # Offense
    "QB": PositionWeight("QB", "OFFENSE", 1.0, 0.0, 0.15, 0.85),
    "RB": PositionWeight("RB", "OFFENSE", 1.0, 0.0, 0.80, 0.20),
    "WR": PositionWeight("WR", "OFFENSE", 1.0, 0.0, 0.10, 0.90),
    "TE": PositionWeight("TE", "OFFENSE", 1.0, 0.0, 0.50, 0.50),
    "OT": PositionWeight("OT", "OFFENSE", 1.0, 0.0, 0.40, 0.60),
    "IOL": PositionWeight("IOL", "OFFENSE", 1.0, 0.0, 0.60, 0.40),
    "OL": PositionWeight("OL", "OFFENSE", 1.0, 0.0, 0.50, 0.50),
    # Defense
    "DT": PositionWeight("DT", "DEFENSE", 0.0, 1.0, 0.75, 0.25),
    "DE": PositionWeight("DE", "DEFENSE", 0.0, 1.0, 0.50, 0.50),
    "DL": PositionWeight("DL", "DEFENSE", 0.0, 1.0, 0.50, 0.50),
    "EDGE": PositionWeight("EDGE", "DEFENSE", 0.0, 1.0, 0.30, 0.70),
    "LB": PositionWeight("LB", "DEFENSE", 0.0, 1.0, 0.60, 0.40),
    "CB": PositionWeight("CB", "DEFENSE", 0.0, 1.0, 0.15, 0.85),
    "S": PositionWeight("S", "DEFENSE", 0.0, 1.0, 0.35, 0.65),
    "DB": PositionWeight("DB", "DEFENSE", 0.0, 1.0, 0.30, 0.70),
    # Athlete / Two-Way
    "ATH": PositionWeight("ATH", "ATHLETE", 0.5, 0.5, 0.50, 0.50),
    # Special Teams
    "K": PositionWeight("K", "SPECIAL_TEAMS", 0.0, 0.0, 0.0, 0.0),
    "P": PositionWeight("P", "SPECIAL_TEAMS", 0.0, 0.0, 0.0, 0.0),
    "LS": PositionWeight("LS", "SPECIAL_TEAMS", 0.0, 0.0, 0.0, 0.0),
}


@dataclass
class TeamPositionalRating:
    """Positional, unit-level, and run/pass recruiting ratings for a team."""
    name: str
    overall_score: float = 0.0
    overall_rank: int = 0
    commits_count: int = 0

    # Offense vs. Defense
    offense_score: float = 0.0
    offense_rank: int = 0
    defense_score: float = 0.0
    defense_rank: int = 0

    # Run vs. Pass Sub-phases
    run_offense_score: float = 0.0
    run_offense_rank: int = 0
    pass_offense_score: float = 0.0
    pass_offense_rank: int = 0

    run_defense_score: float = 0.0
    run_defense_rank: int = 0
    pass_defense_score: float = 0.0
    pass_defense_rank: int = 0

    # Commits breakdown
    offense_commits: float = 0.0
    defense_commits: float = 0.0
    position_counts: Dict[str, int] = field(default_factory=dict)
    position_scores: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "overall_rank": self.overall_rank,
            "overall_score": round(self.overall_score, 2),
            "commits": self.commits_count,
            "offense_score": round(self.offense_score, 2),
            "offense_rank": self.offense_rank,
            "defense_score": round(self.defense_score, 2),
            "defense_rank": self.defense_rank,
            "run_offense_score": round(self.run_offense_score, 2),
            "run_offense_rank": self.run_offense_rank,
            "pass_offense_score": round(self.pass_offense_score, 2),
            "pass_offense_rank": self.pass_offense_rank,
            "run_defense_score": round(self.run_defense_score, 2),
            "run_defense_rank": self.run_defense_rank,
            "pass_defense_score": round(self.pass_defense_score, 2),
            "pass_defense_rank": self.pass_defense_rank,
            "offense_commits": round(self.offense_commits, 1),
            "defense_commits": round(self.defense_commits, 1),
        }


@dataclass
class PositionalRankingResult:
    """Complete positional recruiting rankings for a given season."""
    year: int
    teams: List[TeamPositionalRating]
    weights: Dict[str, PositionWeight]

    @property
    def by_name(self) -> Dict[str, TeamPositionalRating]:
        return {t.name.lower(): t for t in self.teams}

    def rank_by(self, criterion: str) -> List[TeamPositionalRating]:
        """
        Sort and return teams ranked by a specific unit or phase criterion:
        'overall', 'offense', 'defense', 'run_offense', 'pass_offense',
        'run_defense', or 'pass_defense'.
        """
        key_map = {
            "overall": lambda t: t.overall_score,
            "offense": lambda t: t.offense_score,
            "defense": lambda t: t.defense_score,
            "run_offense": lambda t: t.run_offense_score,
            "pass_offense": lambda t: t.pass_offense_score,
            "run_defense": lambda t: t.run_defense_score,
            "pass_defense": lambda t: t.pass_defense_score,
        }
        if criterion not in key_map:
            raise ValueError(f"Unknown ranking criterion: '{criterion}'. Choose from {list(key_map.keys())}")
        return sorted(self.teams, key=key_map[criterion], reverse=True)


class PositionalRankingEngine:
    """Evaluates and ranks recruiting classes by position, unit, and run/pass phase."""

    def __init__(self, weights: Optional[Dict[str, PositionWeight]] = None, rank_decay: Optional[float] = None):
        """Each side of the ball is summed like the class score: a team's offense (defense)
        contributions are sorted best first and the k-th counts `rank_decay`^(k-1); its run/pass
        parts share that weight. `rank_decay` None = use the ranking result's `unit_points`
        (the model's unit_rank_decay through recruit_points), or undiscounted sums without it."""
        self.weights = dict(weights) if weights else dict(DEFAULT_POSITION_WEIGHTS)
        self.rank_decay = rank_decay

    def evaluate(self, ranking_result: RankingResult) -> PositionalRankingResult:
        """
        Compute positional, unit, and run/pass sums for each team from an evaluated RankingResult.
        """
        team_ratings_map = {t.name: t for t in ranking_result.teams}
        team_pos_map: Dict[str, TeamPositionalRating] = {}

        for t_name, tr in team_ratings_map.items():
            team_pos_map[t_name] = TeamPositionalRating(
                name=t_name,
                overall_score=tr.total_score,
                overall_rank=tr.rank,
                commits_count=tr.commits_count,
            )

        # Collect each committed recruit's contributions per side of the ball
        sides: Dict[str, Dict[str, list]] = {}
        for r in ranking_result.recruits:
            if not r.committed_team or r.committed_team == "0":
                continue
            t_name = r.committed_team
            if t_name not in team_pos_map:
                team_pos_map[t_name] = TeamPositionalRating(name=t_name)

            t_stat = team_pos_map[t_name]
            pos = r.position.upper().strip()
            score = r.score

            # Lookup allocation
            weight = self.weights.get(pos)
            if weight is None:
                # Default fallback: 50/50 athlete
                weight = PositionWeight(pos, "ATHLETE", 0.5, 0.5, 0.50, 0.50)

            # Record position-level stats
            t_stat.position_counts[pos] = t_stat.position_counts.get(pos, 0) + 1
            t_stat.position_scores[pos] = t_stat.position_scores.get(pos, 0.0) + score

            team_sides = sides.setdefault(t_name, {"off": [], "def": []})
            if weight.offense_share > 0.0:
                t_stat.offense_commits += weight.offense_share
                team_sides["off"].append((score * weight.offense_share, weight.run_pct, weight.pass_pct))
            if weight.defense_share > 0.0:
                t_stat.defense_commits += weight.defense_share
                team_sides["def"].append((score * weight.defense_share, weight.run_pct, weight.pass_pct))

        # Sum each side best first, the k-th contribution discounted by its rank
        if self.rank_decay is not None:
            decay = float(self.rank_decay)

            def points(contrib: float, rank: int) -> float:
                return contrib * decay ** (rank - 1)
        else:
            points = ranking_result.unit_points or (lambda contrib, rank: contrib)
        for t_name, team_sides in sides.items():
            t_stat = team_pos_map[t_name]
            for side, items in team_sides.items():
                items.sort(key=lambda c: c[0], reverse=True)
                total = run = pas = 0.0
                for k, (contrib, run_pct, pass_pct) in enumerate(items, 1):
                    w = points(contrib, k)
                    total += w
                    run += w * run_pct
                    pas += w * pass_pct
                if side == "off":
                    t_stat.offense_score, t_stat.run_offense_score, t_stat.pass_offense_score = total, run, pas
                else:
                    t_stat.defense_score, t_stat.run_defense_score, t_stat.pass_defense_score = total, run, pas

        teams_list = list(team_pos_map.values())

        # Compute ordinal ranks across each phase
        def _assign_ranks(field_name: str, rank_attr: str):
            teams_list.sort(key=lambda t: getattr(t, field_name), reverse=True)
            for idx, item in enumerate(teams_list, 1):
                setattr(item, rank_attr, idx)

        _assign_ranks("offense_score", "offense_rank")
        _assign_ranks("defense_score", "defense_rank")
        _assign_ranks("run_offense_score", "run_offense_rank")
        _assign_ranks("pass_offense_score", "pass_offense_rank")
        _assign_ranks("run_defense_score", "run_defense_rank")
        _assign_ranks("pass_defense_score", "pass_defense_rank")

        # Sort by overall score by default
        teams_list.sort(key=lambda t: t.overall_score, reverse=True)
        for idx, item in enumerate(teams_list, 1):
            item.overall_rank = idx

        return PositionalRankingResult(
            year=ranking_result.year,
            teams=teams_list,
            weights=self.weights,
        )
