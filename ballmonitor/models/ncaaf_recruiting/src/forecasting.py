"""
Signing Day Forecaster & Commitment Probability Engine

Predicts final recruiting class rankings and team scores before National Signing Day:
- Models recruit commitment probability using Plackett-Luce prestige and geographic gravity
- Evaluates expected class trajectories via Monte Carlo simulation
- Supports interactive 'what-if' scenario overrides to test hypothetical commitments
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from .models import Recruit, TeamRating, RankingResult, RankingMethod
from .elo_engine import EloEngine
from .geocoding import get_campus_coords, haversine_miles


@dataclass
class ForecastedTeamRating:
    """Projected final team ranking and probabilistic finish distribution."""
    name: str
    current_rank: int = 0
    current_score: float = 0.0
    current_commits: int = 0

    projected_score_mean: float = 0.0
    projected_score_std: float = 0.0
    projected_rank_median: int = 0
    projected_rank_mean: float = 0.0
    projected_rank_p10: int = 0
    projected_rank_p90: int = 0

    prob_top1: float = 0.0
    prob_top5: float = 0.0
    prob_top10: float = 0.0
    expected_new_commits: float = 0.0

    @property
    def rank_delta(self) -> int:
        """Improvement in rank (+ is improvement, - is drop)."""
        return self.current_rank - self.projected_rank_median

    @property
    def score_delta(self) -> float:
        """Projected score increase over current score."""
        return self.projected_score_mean - self.current_score


@dataclass
class ForecastResult:
    """Complete forecast output across all teams."""
    year: int
    teams: List[ForecastedTeamRating]
    unsigned_count: int
    n_simulations: int
    overrides: Dict[str, str] = field(default_factory=dict)

    @property
    def by_name(self) -> Dict[str, ForecastedTeamRating]:
        return {t.name.lower(): t for t in self.teams}


@dataclass
class ScenarioDelta:
    """Delta impact of a scenario override on a single school."""
    team: str
    baseline_rank: int
    scenario_rank: int
    rank_delta: int
    baseline_score: float
    scenario_score: float
    score_delta: float


@dataclass
class ScenarioComparison:
    """Comparison between baseline forecast and an overridden scenario."""
    year: int
    overrides: Dict[str, str]
    deltas: List[ScenarioDelta]
    notable_movers: List[ScenarioDelta]


class CommitmentPredictor:
    """
    Computes school choice probabilities for unsigned recruits based on
    latent program prestige (Plackett-Luce Elo) and geographic distance decay.
    """

    def __init__(
        self,
        team_ratings: Dict[str, TeamRating],
        distance_decay: float = 0.85,
        reference_distance: float = 100.0,
        base_elo: float = 1500.0,
    ):
        self.team_ratings = team_ratings
        self.distance_decay = distance_decay
        self.d0 = reference_distance
        self.base_elo = base_elo

    def predict_probabilities(
        self, recruit: Recruit, candidate_teams: Optional[List[str]] = None
    ) -> Dict[str, float]:
        """
        Calculate softmax commitment probabilities for an unsigned recruit across offering schools.
        """
        candidates = candidate_teams or [t for t in recruit.all_teams if t and t != "0"]
        if not candidates:
            return {}
        if len(candidates) == 1:
            return {candidates[0]: 1.0}

        rec_coords = (recruit.latitude, recruit.longitude) if (recruit.latitude != 0.0 or recruit.longitude != 0.0) else None

        utilities: Dict[str, float] = {}
        for school in candidates:
            tr = self.team_ratings.get(school)
            elo = tr.elo if tr else self.base_elo
            gamma = (elo - self.base_elo) * (math.log(10.0) / 400.0)

            # Geographic proximity decay
            campus = get_campus_coords(school)
            if campus and rec_coords:
                dist = haversine_miles(rec_coords, campus)
                dist_penalty = self.distance_decay * math.log(1.0 + (dist / self.d0))
            else:
                # Default average campus distance penalty if unlocated
                dist_penalty = self.distance_decay * math.log(1.0 + (450.0 / self.d0))

            utilities[school] = gamma - dist_penalty

        # Numerical softmax
        max_u = max(utilities.values())
        exp_u = {s: math.exp(u - max_u) for s, u in utilities.items()}
        sum_exp = sum(exp_u.values())
        if sum_exp <= 0.0:
            uniform = 1.0 / len(candidates)
            return {s: uniform for s in candidates}

        return {s: exp_u[s] / sum_exp for s in candidates}


class SigningDayForecaster:
    """
    Simulates signing day outcomes and predicts final class rankings.
    """

    def __init__(
        self,
        elo_engine: Optional[EloEngine] = None,
        distance_decay: float = 0.85,
        rank_decay: float = 0.95,
    ):
        self.engine = elo_engine or EloEngine(method=RankingMethod.PLACKETT_LUCE)
        self.distance_decay = distance_decay
        self.rank_decay = rank_decay

    def forecast(
        self,
        year: int,
        recruits: List[Recruit],
        overrides: Optional[Dict[str, str]] = None,
        n_simulations: int = 500,
        seed: Optional[int] = 42,
    ) -> ForecastResult:
        """
        Run Monte Carlo simulations to forecast final class rankings.

        Args:
            year: Recruiting season year.
            recruits: Complete list of recruits (both committed and unsigned).
            overrides: Dict mapping recruit name -> overridden school commitment.
            n_simulations: Number of Monte Carlo draws (default: 500).
            seed: Random seed for deterministic reproducibility.
        """
        # Local generator: reproducible without touching numpy's global RNG state.
        rng = np.random.default_rng(seed)

        active_overrides = {k.strip().upper(): v.strip() for k, v in (overrides or {}).items()}

        # 1. Partition into committed vs. unsigned
        committed_recruits: List[Recruit] = []
        unsigned_recruits: List[Recruit] = []

        for r in recruits:
            r_name = r.name.strip().upper()
            if r_name in active_overrides:
                # User overridden to a specific team
                overridden_team = active_overrides[r_name]
                r_copy = Recruit(
                    url=r.url,
                    year=r.year,
                    name=r.name,
                    position=r.position,
                    hometown=r.hometown,
                    stars=r.stars,
                    committed_team=overridden_team,
                    offers=[t for t in r.all_teams if t != overridden_team],
                    latitude=r.latitude,
                    longitude=r.longitude,
                )
                committed_recruits.append(r_copy)
            elif r.committed_team and r.committed_team != "0":
                committed_recruits.append(r)
            else:
                if r.all_teams and any(t for t in r.all_teams if t != "0"):
                    unsigned_recruits.append(r)

        # 2. Run baseline Plackett-Luce on current commits to establish current ratings and prestige
        base_result = self.engine.run(year, committed_recruits)
        team_ratings_map = {t.name: t for t in base_result.teams}

        # Calculate scores for unsigned recruits using base model parameters
        predictor = CommitmentPredictor(
            team_ratings=team_ratings_map,
            distance_decay=self.distance_decay,
        )

        # 3. Pre-compute probability distributions and quality scores for unsigned recruits
        unsigned_candidates: List[Tuple[Recruit, List[str], np.ndarray, float]] = []
        for r in unsigned_recruits:
            prob_dict = predictor.predict_probabilities(r)
            if not prob_dict:
                continue
            schools = list(prob_dict.keys())
            probs = np.array(list(prob_dict.values()), dtype=float)
            probs /= probs.sum()  # ensure exact sum = 1.0

            # Estimate recruit score from defeated offers
            # In Plackett-Luce, q_i = (sum exp(gamma_s))^0.5
            gamma_terms = []
            for s in schools:
                tr = team_ratings_map.get(s)
                elo = tr.elo if tr else 1500.0
                gamma_terms.append(math.exp((elo - 1500.0) * (math.log(10.0) / 400.0)))
            rec_score = (sum(gamma_terms)) ** 0.5 if gamma_terms else 2.0

            unsigned_candidates.append((r, schools, probs, rec_score))

        # Base recruit scores grouped by team
        base_team_scores: Dict[str, List[float]] = {}
        for r in committed_recruits:
            if r.committed_team not in base_team_scores:
                base_team_scores[r.committed_team] = []
            base_team_scores[r.committed_team].append(r.score)

        all_teams_set = set(team_ratings_map.keys())
        for _, schools, _, _ in unsigned_candidates:
            all_teams_set.update(schools)

        # 4. Monte Carlo Simulation
        team_sim_scores: Dict[str, List[float]] = {t: [] for t in all_teams_set}
        team_sim_ranks: Dict[str, List[int]] = {t: [] for t in all_teams_set}
        team_sim_new_commits: Dict[str, List[int]] = {t: [] for t in all_teams_set}

        for _ in range(n_simulations):
            # Sample commits for this realization
            realized_team_scores: Dict[str, List[float]] = {
                t: list(base_team_scores.get(t, [])) for t in all_teams_set
            }
            realized_new_counts: Dict[str, int] = {t: 0 for t in all_teams_set}

            for _, schools, probs, rec_score in unsigned_candidates:
                chosen_school = rng.choice(schools, p=probs)
                realized_team_scores[chosen_school].append(rec_score)
                realized_new_counts[chosen_school] += 1

            # Compute class scores with rank decay
            realized_totals: List[Tuple[str, float]] = []
            for t in all_teams_set:
                scores = realized_team_scores[t]
                scores.sort(reverse=True)
                total = sum(s * (self.rank_decay ** idx) for idx, s in enumerate(scores))
                realized_totals.append((t, total))

            # Rank realization
            realized_totals.sort(key=lambda x: x[1], reverse=True)
            for rank_idx, (t, tot) in enumerate(realized_totals, 1):
                team_sim_scores[t].append(tot)
                team_sim_ranks[t].append(rank_idx)
                team_sim_new_commits[t].append(realized_new_counts[t])

        # 5. Compile aggregate forecast metrics
        forecasted_teams: List[ForecastedTeamRating] = []
        for t in all_teams_set:
            tr = team_ratings_map.get(t)
            curr_rank = tr.rank if tr else len(all_teams_set)
            curr_score = tr.total_score if tr else 0.0
            curr_commits = tr.commits_count if tr else 0

            scores_arr = np.array(team_sim_scores[t])
            ranks_arr = np.array(team_sim_ranks[t])
            new_comm_arr = np.array(team_sim_new_commits[t])

            p_top1 = float(np.mean(ranks_arr == 1))
            p_top5 = float(np.mean(ranks_arr <= 5))
            p_top10 = float(np.mean(ranks_arr <= 10))

            forecasted_teams.append(
                ForecastedTeamRating(
                    name=t,
                    current_rank=curr_rank,
                    current_score=curr_score,
                    current_commits=curr_commits,
                    projected_score_mean=float(np.mean(scores_arr)),
                    projected_score_std=float(np.std(scores_arr)),
                    projected_rank_median=int(np.median(ranks_arr)),
                    projected_rank_mean=float(np.mean(ranks_arr)),
                    projected_rank_p10=int(np.percentile(ranks_arr, 10)),
                    projected_rank_p90=int(np.percentile(ranks_arr, 90)),
                    prob_top1=p_top1,
                    prob_top5=p_top5,
                    prob_top10=p_top10,
                    expected_new_commits=float(np.mean(new_comm_arr)),
                )
            )

        # Sort forecasted teams by median projected rank, then mean projected score
        forecasted_teams.sort(key=lambda x: (x.projected_rank_median, -x.projected_score_mean))

        return ForecastResult(
            year=year,
            teams=forecasted_teams,
            unsigned_count=len(unsigned_candidates),
            n_simulations=n_simulations,
            overrides=active_overrides,
        )

    def compare_scenarios(
        self,
        year: int,
        recruits: List[Recruit],
        scenario_overrides: Dict[str, str],
        baseline_overrides: Optional[Dict[str, str]] = None,
        n_simulations: int = 500,
    ) -> ScenarioComparison:
        """
        Compare a baseline forecast against a what-if scenario with recruit overrides.
        """
        base_fc = self.forecast(
            year=year,
            recruits=recruits,
            overrides=baseline_overrides,
            n_simulations=n_simulations,
        )
        scen_fc = self.forecast(
            year=year,
            recruits=recruits,
            overrides=scenario_overrides,
            n_simulations=n_simulations,
        )

        base_map = {t.name.lower(): t for t in base_fc.teams}
        scen_map = {t.name.lower(): t for t in scen_fc.teams}

        all_names = sorted(list(set(base_map.keys()) | set(scen_map.keys())))
        deltas: List[ScenarioDelta] = []
        for name in all_names:
            bt = base_map.get(name)
            st = scen_map.get(name)
            if not bt or not st:
                continue

            b_rank = bt.projected_rank_median
            s_rank = st.projected_rank_median
            b_score = bt.projected_score_mean
            s_score = st.projected_score_mean

            deltas.append(
                ScenarioDelta(
                    team=st.name,
                    baseline_rank=b_rank,
                    scenario_rank=s_rank,
                    rank_delta=b_rank - s_rank,
                    baseline_score=b_score,
                    scenario_score=s_score,
                    score_delta=s_score - b_score,
                )
            )

        # Filter notable movers (rank changed or score shifted by >= 0.5)
        notable = [d for d in deltas if d.rank_delta != 0 or abs(d.score_delta) >= 0.25]
        notable.sort(key=lambda d: (-abs(d.score_delta), d.scenario_rank))

        return ScenarioComparison(
            year=year,
            overrides=scenario_overrides,
            deltas=deltas,
            notable_movers=notable,
        )
