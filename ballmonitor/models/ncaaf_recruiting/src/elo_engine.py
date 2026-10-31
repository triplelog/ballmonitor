import math
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize

from .models import RankingMethod, Recruit, TeamRating, RankingResult
from .geocoding import get_campus_coords, haversine_miles


@lru_cache(maxsize=64)
def _solve_plackett_luce_cached(
    num_teams: int,
    c_ids_tuple: Tuple[int, ...],
    s_ids_tuple: Tuple[Tuple[int, ...], ...],
    lambda_reg: float,
    mu_tuple: Optional[Tuple[float, ...]] = None,
) -> np.ndarray:
    """MAP program strengths. The L2 penalty pulls each strength toward its prior mean
    ``mu`` (default 0: every program starts equal)."""
    c_ids = np.array(c_ids_tuple, dtype=np.int32)
    mu = np.zeros(num_teams) if mu_tuple is None else np.array(mu_tuple)
    s_ids = [list(s) for s in s_ids_tuple]
    actual_commits = np.bincount(c_ids, minlength=num_teams)

    def nll_and_grad(gamma: np.ndarray) -> Tuple[float, np.ndarray]:
        nll = 0.5 * lambda_reg * np.sum((gamma - mu) ** 2)
        grad = lambda_reg * (gamma - mu) - actual_commits
        for i, s in enumerate(s_ids):
            g_s = gamma[s]
            max_g = np.max(g_s)
            exp_g = np.exp(g_s - max_g)
            sum_exp = np.sum(exp_g)
            nll -= (gamma[c_ids[i]] - (max_g + np.log(sum_exp)))
            grad[s] += exp_g / sum_exp
        return nll, grad

    gamma_init = mu.copy()
    res = minimize(
        nll_and_grad,
        gamma_init,
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 200},
    )
    return res.x


class EloEngine:
    """College football & basketball offer-based recruiting ranking engine.
    
    Supports:
    1. Plackett-Luce (default): Global convex maximum-a-posteriori (MAP) estimation.
       Eliminates sequential order-dependence and heuristic ad-hoc thresholds.
    2. Sequential Elo: The historical online SGD update algorithm.
    """

    def __init__(
        self,
        method: RankingMethod = RankingMethod.PLACKETT_LUCE,
        # Plackett-Luce hyperparameters
        l2_reg: float = 0.5,
        quality_power: float = 0.5,
        rank_decay: float = 0.95,
        volume_discount: float = 0.0,
        cornerstone_weight: float = 0.0,
        # Sequential Elo hyperparameters
        k_factor: float = 10.0,
        iterations: int = 2,
        base_elo: float = 1500.0,
        benchmarks: Optional[List[int]] = None,
        min_commit_threshold: int = 20,
        points_fn=None,
        prior_gamma: Optional[Dict[str, float]] = None,
        commit_weight: float = 0.0,
        aggregate: str = "sum",
    ):
        self.method = method
        self.l2_reg = l2_reg
        self.quality_power = quality_power
        self.rank_decay = rank_decay
        self.volume_discount = volume_discount
        self.cornerstone_weight = cornerstone_weight

        self.k_factor = k_factor
        self.iterations = iterations
        self.base_elo = base_elo
        self.benchmarks = benchmarks or [2000, 1900, 1800, 1700, 1600, 1500]
        self.min_commit_threshold = min_commit_threshold
        # Optional f(rating, rank) -> class points for the recruit at within-class
        # rank (1 = best). Defaults to rating * rank_decay ** (rank - 1).
        self.points_fn = points_fn
        # Seed: prior mean of each program's strength (e.g. from on-court results);
        # programs not listed start at 0. The offer battles then move them from there.
        self.prior_gamma = prior_gamma or {}
        # Recruit score counts the committed school's strength times commit_weight too
        # (0 = only the schools he turned down, the original definition).
        self.commit_weight = commit_weight
        if aggregate not in ("sum", "max"):
            raise ValueError("aggregate must be 'sum' or 'max'")
        self.aggregate = aggregate

    # =========================================================================
    # PLACKETT-LUCE GLOBAL MAP ESTIMATION (DEFAULT)
    # =========================================================================

    def _run_plackett_luce(
        self, year: int, recruits: List[Recruit], fit_recruits: Optional[List[Recruit]] = None
    ) -> RankingResult:
        """Run global Plackett-Luce optimization and compute class rankings.

        ``fit_recruits`` (default: ``recruits``) are the offer battles the prestige fit
        uses -- e.g. this class plus earlier classes (``prestige_years``). Only
        ``recruits`` are scored and ranked.
        """
        def _valid(rs: List[Recruit]) -> List[Recruit]:
            return [r for r in rs if r.committed_team and r.committed_team != "0" and r.all_teams]

        valid_recruits = _valid(recruits)
        if not valid_recruits:
            return RankingResult(year=year, teams=[], recruits=recruits, method=RankingMethod.PLACKETT_LUCE)
        fit_valid = _valid(fit_recruits) if fit_recruits is not None else valid_recruits
        multi_recruits = [r for r in fit_valid if r.is_multi_offer]

        # Programs in this class's data are ranked; the fit may know more programs.
        team_set = sorted({t for r in valid_recruits for t in r.all_teams})
        fit_teams = sorted(set(team_set) | {t for r in fit_valid for t in r.all_teams})
        team_to_id = {t: i for i, t in enumerate(fit_teams)}
        num_teams = len(fit_teams)

        # Vectorize multi-offer recruits
        c_ids_tuple = tuple(team_to_id[r.committed_team] for r in multi_recruits)
        s_ids_tuple = tuple(tuple(team_to_id[t] for t in r.all_teams) for r in multi_recruits)

        # Count total offers per team (this class)
        offer_counts = np.zeros(num_teams)
        for r in valid_recruits:
            for t in r.all_teams:
                offer_counts[team_to_id[t]] += 1
        mean_offers = np.mean(offer_counts[offer_counts > 0]) if np.any(offer_counts > 0) else 1.0

        mu_tuple = (tuple(float(self.prior_gamma.get(t, 0.0)) for t in fit_teams)
                    if self.prior_gamma else None)
        gamma = _solve_plackett_luce_cached(
            num_teams, c_ids_tuple, s_ids_tuple, float(self.l2_reg), mu_tuple
        )
        exp_gamma = np.exp(gamma)
        if self.volume_discount > 0.0:
            exp_gamma = exp_gamma * (mean_offers / np.maximum(1.0, offer_counts)) ** self.volume_discount

        # Group recruits by committed team and score them
        team_recruits: Dict[str, List[Recruit]] = {t: [] for t in team_set}
        all_recruit_scores: List[float] = []
        for r in valid_recruits:
            losing = [team_to_id[t] for t in r.all_teams if t != r.committed_team]
            weights = list(exp_gamma[losing])
            if self.commit_weight > 0.0 and r.committed_team in team_to_id:
                weights.append(self.commit_weight * exp_gamma[team_to_id[r.committed_team]])
            if weights:
                agg = max(weights) if self.aggregate == "max" else sum(weights)
                score = float(agg ** self.quality_power)
            else:
                score = 1.0 if self.cornerstone_weight > 0.0 else 0.0

            r.score = score
            all_recruit_scores.append(score)

            # Compute recruit distance if geolocation coordinates are present
            if r.latitude != 0.0 or r.longitude != 0.0:
                campus = get_campus_coords(r.committed_team)
                if campus:
                    r.distance_miles = haversine_miles(campus, (r.latitude, r.longitude))

            team_recruits[r.committed_team].append(r)

        mu_benchmark = max(1.0, float(np.median(all_recruit_scores))) if all_recruit_scores else 3.0

        # Compute team class scores with rank decay
        team_ratings: List[TeamRating] = []
        for t in team_set:
            pts_list = team_recruits[t]
            commits = len(pts_list)
            if commits == 0 and self.cornerstone_weight > 0.0:
                continue

            pts_list.sort(key=lambda r: r.score, reverse=True)

            if self.points_fn is not None:
                rot_score = sum(self.points_fn(r.score, idx + 1) for idx, r in enumerate(pts_list))
            else:
                rot_score = sum(r.score * (self.rank_decay ** idx) for idx, r in enumerate(pts_list))
            if self.cornerstone_weight > 0.0 and commits > 0:
                cornerstone_k = min(commits, 2)
                cornerstone_avg = sum(pts_list[i].score for i in range(cornerstone_k)) / cornerstone_k
                quality_mult = (cornerstone_avg / mu_benchmark) ** self.cornerstone_weight
                score = rot_score * quality_mult
            else:
                score = rot_score

            elo = float(self.base_elo + (gamma[team_to_id[t]] * 400.0 / np.log(10.0)))

            # Geographic stats
            distances = [r.distance_miles for r in pts_list if r.distance_miles > 0.0]
            avg_dist = (sum(distances) / len(distances)) if distances else 0.0
            national_pct = (sum(1 for d in distances if d >= 500.0) / len(distances) * 100.0) if distances else 0.0
            avg_recruit_score = (sum(r.score for r in pts_list) / commits) if commits > 0 else 0.0

            team_ratings.append(
                TeamRating(
                    name=t,
                    elo=elo,
                    offers_count=int(offer_counts[team_to_id[t]]),
                    commits_count=commits,
                    total_score=score,
                    avg_recruit_score=avg_recruit_score,
                    avg_recruit_distance=avg_dist,
                    national_pct=national_pct,
                )
            )

        team_ratings.sort(key=lambda tr: tr.total_score, reverse=True)
        for idx, tr in enumerate(team_ratings, 1):
            tr.rank = idx

        return RankingResult(
            year=year,
            teams=team_ratings,
            recruits=recruits,
            method=RankingMethod.PLACKETT_LUCE,
        )

    # =========================================================================
    # LEGACY SEQUENTIAL ELO (PRESERVED FOR ABLATION STUDIES)
    # =========================================================================

    def _elo_multiplier(self, elo: float) -> float:
        chance = 1.0 / (1.0 + 10.0 ** ((self.base_elo - elo) / 400.0))
        chance = min(max(chance, 1e-6), 1.0 - 1e-6)
        return chance / (1.0 - chance)

    def _run_sequential_elo(self, year: int, recruits: List[Recruit]) -> RankingResult:
        team_map: Dict[str, TeamRating] = {}
        for r in recruits:
            for team in r.all_teams:
                if team not in team_map:
                    team_map[team] = TeamRating(name=team, elo=self.base_elo)

        for r in recruits:
            committed = r.committed_team
            if committed in team_map:
                team_map[committed].commits_count += 1
            for team in r.all_teams:
                if team in team_map:
                    team_map[team].offers_count += 1

        for t in team_map.values():
            if t.commits_count < self.min_commit_threshold:
                t.elo = 1000.0 + (t.commits_count * 25.0)

        sorted_recruits = sorted(recruits, key=lambda r: r.total_offers)
        for _ in range(self.iterations):
            for r in sorted_recruits:
                if not r.is_multi_offer:
                    continue
                all_teams = r.all_teams
                tmul = sum(self._elo_multiplier(team_map[team].elo) for team in all_teams)
                if tmul <= 0.0:
                    continue
                for team in all_teams:
                    mul = self._elo_multiplier(team_map[team].elo)
                    norm_prob = mul / tmul
                    oelo = team_map[team].elo
                    if team == r.committed_team:
                        team_map[team].elo = oelo + self.k_factor * (1.0 - norm_prob)
                    else:
                        team_map[team].elo = oelo - self.k_factor * norm_prob

        for t in team_map.values():
            t.points = {b: 0.0 for b in self.benchmarks}

        recruit_tmul = {
            idx: sum(self._elo_multiplier(team_map[t].elo) for t in r.all_teams)
            for idx, r in enumerate(recruits)
            if r.is_multi_offer
        }

        for b in self.benchmarks:
            chance_top = 1.0 / (1.0 + 10.0 ** ((self.base_elo - b) / 400.0))
            mul_top = chance_top / (1.0 - chance_top)
            for idx, r in enumerate(recruits):
                if not r.is_multi_offer or idx not in recruit_tmul:
                    continue
                tmul = recruit_tmul[idx]
                prob_top = mul_top / (tmul + mul_top)
                awarded = max(0.0, 0.5 - prob_top)
                r.points[b] = awarded
                team_map[r.committed_team].points[b] += awarded

        all_teams = list(team_map.values())
        tier_thresholds = [
            (1, 2000), (6, 1900), (11, 1800), (21, 1700), (41, 1600), (71, 1500)
        ]
        ranked_teams: List[TeamRating] = []
        ranked_names = set()
        ratio = 1.0
        current_benchmark = 2000

        for r in range(1, len(all_teams) + 1):
            for threshold, bench in tier_thresholds:
                if r == threshold:
                    current_benchmark = bench
                    break
            candidates = [t for t in all_teams if t.name not in ranked_names]
            if not candidates:
                break
            candidates.sort(key=lambda t: t.points.get(current_benchmark, 0.0), reverse=True)
            top_team = candidates[0]
            ranked_names.add(top_team.name)

            if r in [6, 11, 21, 41, 71]:
                prev_bench = current_benchmark + 100
                prev_pts = top_team.points.get(prev_bench, 0.0)
                curr_pts = top_team.points.get(current_benchmark, 0.0)
                if curr_pts > 0 and prev_pts > 0:
                    ratio *= (prev_pts / curr_pts)

            top_team.total_score = top_team.points.get(current_benchmark, 0.0) * ratio
            top_team.rank = r
            ranked_teams.append(top_team)

        return RankingResult(
            year=year,
            teams=ranked_teams,
            recruits=recruits,
            method=RankingMethod.SEQUENTIAL_ELO,
        )

    def run(
        self, year: int, recruits: List[Recruit], fit_recruits: Optional[List[Recruit]] = None
    ) -> RankingResult:
        """Run recruiting rankings using the configured method.

        ``fit_recruits`` (Plackett-Luce only) widens the prestige fit, e.g. to include
        earlier classes; only ``recruits`` are scored.
        """
        if self.method == RankingMethod.PLACKETT_LUCE:
            return self._run_plackett_luce(year, recruits, fit_recruits)
        elif self.method == RankingMethod.SEQUENTIAL_ELO:
            return self._run_sequential_elo(year, recruits)
        else:
            raise ValueError(f"Unknown ranking method: {self.method}")
