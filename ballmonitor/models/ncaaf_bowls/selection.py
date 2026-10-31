"""
College Football Bowl Selection Engine:
Fills the non-CFP bowls from the tie-in slots in data/bowls.json:
  1. contracted single-conference slots, each conference in its pick order,
  2. pooled slots shared by several conferences, in bowl-prestige order,
  3. any slot still open, from all remaining eligible teams.
Rules: the Notre Dame / ACC clause, the Big Ten conference-win and anti-repeat rules,
SEC anti-repeat, the Pac-12 legacy agreement (the 12 pre-2024 Pac-12 schools fill the
"Pac-12 legacy" slots and not their current conference's), and the APR fallback for
5-win teams when there are too few eligible teams.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Sequence

try:
    from .config import SimConfig
except (ImportError, ValueError):
    from config import SimConfig
try:
    from .domain import Bowl, Game, Team, TeamSimState
except (ImportError, ValueError):
    from domain import Bowl, Game, Team, TeamSimState

LEGACY_TOKEN = "Pac-12 legacy"

# Order in which conferences make their contracted picks (power conferences first).
CONFERENCE_PICK_ORDER = [
    "SEC", "Big Ten", "Big 12", "ACC", LEGACY_TOKEN, "Pac-12",
    "AAC", "MWC", "Sun Belt", "MAC", "CUSA",
]

REGIONAL_DRIVE_IN_BOWLS = {
    "dukes_mayo_bowl", "music_city_bowl", "gasparilla_bowl",
    "texas_bowl", "birmingham_bowl", "liberty_bowl"
}

@dataclass
class BowlMatchup:
    bowl_id: str
    bowl_name: str
    team_1: TeamSimState | None
    team_2: TeamSimState | None
    is_cfp: bool = False
    winner: TeamSimState | None = None
    loser: TeamSimState | None = None

class BowlSelector:
    def __init__(
        self,
        bowls: list[Bowl],
        all_teams: list[Team],
        config: SimConfig,
        schedule: list[Game] | None = None
    ):
        self.bowls = bowls
        self.non_cfp_bowls = [b for b in bowls if not b.is_cfp]
        self.bowl_dict = {b.id: b for b in bowls}
        self.all_teams = all_teams
        self.team_dict = {t.id: t for t in all_teams}
        self.config = config
        self.schedule = schedule or []
        self.regular_season_matchups: set[tuple[str, str]] = set()
        for g in self.schedule:
            self.regular_season_matchups.add((g.home, g.away))
            self.regular_season_matchups.add((g.away, g.home))

    def select_bowls(
        self,
        states: dict[str, TeamSimState],
        cfp_team_ids: set[str],
        rng: random.Random
    ) -> list[BowlMatchup]:
        """Runs the entire bowl selection process for all non-CFP bowl games."""
        cfg = self.config

        # 1. Determine Bowl Eligibility
        # A team is bowl eligible with >= 6 wins.
        # If too few eligible teams, fill open spots with teams one win short, sorted by APR.
        eligible_pool = {
            t_id: s for t_id, s in states.items()
            if t_id not in cfp_team_ids and s.wins >= cfg.bowl_eligible_wins
        }

        needed_slots = sum(len(b.slots) or 2 for b in self.non_cfp_bowls)

        if len(eligible_pool) < needed_slots:
            # APR fallback for 5-7 teams
            five_win_teams = [
                s for t_id, s in states.items()
                if t_id not in cfp_team_ids and s.wins == cfg.bowl_eligible_wins - 1 and t_id not in eligible_pool
            ]
            five_win_teams_sorted = sorted(five_win_teams, key=lambda s: s.team.apr, reverse=True)
            for team in five_win_teams_sorted:
                eligible_pool[team.id] = team
                if len(eligible_pool) >= needed_slots:
                    break

        available_teams = dict(eligible_pool)
        assignments: dict[str, list[TeamSimState]] = {b.id: [] for b in self.non_cfp_bowls}

        # Helper to compute preference/attractiveness score of a team for a specific bowl
        def team_bowl_utility(
            bowl: Bowl,
            candidate: TeamSimState,
            opponent: TeamSimState | None = None
        ) -> float:
            u = 0.0
            # Wins bonus
            u += candidate.wins * cfg.bowl_win_weight
            # Power rating bonus
            u += candidate.rating * cfg.bowl_rating_weight

            # Brand appeal calibrated to empirical +1.6 win premium
            # Prestige-scaled: Top-tier bowls (Citrus, Alamo, Pop-Tarts, ReliaQuest) place higher premium on national brands
            brand_prestige_factor = 0.8 + (bowl.prestige / 10.0) * 0.4
            u += candidate.team.brand * cfg.bowl_brand_weight * brand_prestige_factor

            # Geographic proximity bonus (baseline)
            dist = bowl.distance_to(candidate.team)
            geo_factor = max(0.0, 1.0 - (dist / cfg.bowl_max_distance_miles))
            u += geo_factor * cfg.bowl_geo_weight * 10.0

            # 400-mile Drive-in bonus (from historical analysis where 29.7% of teams are within drive-in radius)
            # Regional bowls (Duke's Mayo 75%, Music City 67%, Gasparilla 50%, Texas Bowl 44%) have heavy drive-in bias
            if dist <= cfg.bowl_drive_in_radius_miles:
                drive_factor = 1.0 - (dist / cfg.bowl_drive_in_radius_miles)
                drive_bonus = cfg.bowl_drive_in_bonus * drive_factor
                if bowl.id in REGIONAL_DRIVE_IN_BOWLS:
                    drive_bonus *= cfg.bowl_regional_proximity_mult
                u += drive_bonus

            # Repeat bowl penalty (calibrated to 85.2% empirical repeat suppression)
            if candidate.team.last_bowl == bowl.id:
                u -= cfg.bowl_repeat_penalty

            # Regular season rematch avoidance: bowls avoid pairing teams that already met this season
            if opponent is not None and (candidate.id, opponent.id) in self.regular_season_matchups:
                u -= cfg.bowl_rematch_penalty

            # Specific regional affinity bonuses
            t_id = candidate.id
            b_id = bowl.id
            if b_id == "texas_bowl" and candidate.team.state in ("TX", "LA", "OK"):
                u += 5.0
            elif b_id == "music_city_bowl" and candidate.team.state in ("TN", "KY", "AL"):
                u += 5.0
            elif b_id == "dukes_mayo_bowl" and candidate.team.state in ("NC", "SC", "VA"):
                u += 5.0
            elif b_id == "pinstripe_bowl" and candidate.team.state in ("NY", "NJ", "PA", "MA", "MD"):
                u += 5.0
            elif b_id == "reliaquest_bowl" and candidate.team.state in ("FL", "GA"):
                u += 4.0
            elif b_id == "gator_bowl" and candidate.team.state in ("FL", "GA", "SC"):
                u += 4.0
            elif b_id == "alamo_bowl" and candidate.team.state in ("TX", "OK"):
                u += 4.0

            # Stochastic jitter based on temperature
            if cfg.bowl_temperature > 0.0:
                # Gumbel noise for multinomial choice behavior: -scale * ln(-ln(U))
                u_rand = max(1e-9, min(1.0 - 1e-9, rng.random()))
                gumbel_noise = -math.log(-math.log(u_rand))
                u += gumbel_noise * cfg.bowl_temperature * 2.0

            return u

        def pick_best_team(
            candidates: list[TeamSimState],
            bowl: Bowl,
            max_conf_win_skip: int | None = None,
            enforce_anti_repeat: bool = False,
            opponent: TeamSimState | None = None
        ) -> TeamSimState | None:
            if not candidates:
                return None

            # Filter candidates if conference win constraint applies (e.g. Big Ten rule)
            valid_candidates = list(candidates)
            if max_conf_win_skip is not None and len(valid_candidates) > 1:
                max_conf_wins = max(c.conf_wins for c in valid_candidates)
                valid_candidates = [
                    c for c in valid_candidates
                    if c.conf_wins >= max_conf_wins - max_conf_win_skip
                ]

            # Contractual anti-repeat filter (e.g. Big Ten explicit contract rule):
            # A bowl cannot pick the same team in consecutive years if another eligible candidate exists
            if enforce_anti_repeat and len(valid_candidates) > 1:
                non_repeat_candidates = [
                    c for c in valid_candidates
                    if c.team.last_bowl != bowl.id
                ]
                if non_repeat_candidates:
                    valid_candidates = non_repeat_candidates

            # Avoid regular-season rematch if opponent is already slotted and alternatives exist
            if opponent is not None and len(valid_candidates) > 1:
                non_rematch_candidates = [
                    c for c in valid_candidates
                    if (c.id, opponent.id) not in self.regular_season_matchups
                ]
                if non_rematch_candidates:
                    valid_candidates = non_rematch_candidates

            scored = [(team_bowl_utility(bowl, c, opponent=opponent), c) for c in valid_candidates]
            scored.sort(key=lambda x: x[0], reverse=True)
            chosen = scored[0][1]
            return chosen

        def token(s: TeamSimState) -> str:
            return LEGACY_TOKEN if s.team.legacy_pac12 else s.conf

        def candidates(confs: list[str]) -> list[TeamSimState]:
            cands = [s for s in available_teams.values() if token(s) in confs]
            # Notre Dame may take an ACC slot if within tolerance of the best ACC team left
            nd = available_teams.get("notre_dame")
            if "ACC" in confs and nd and nd not in cands:
                acc = [s for s in cands if s.conf == "ACC"]
                if acc and nd.wins >= max(c.wins for c in acc) - cfg.notre_dame_acc_win_tolerance:
                    cands.append(nd)
            return cands

        def fill(bowl: Bowl, confs: list[str] | None) -> None:
            cands = list(available_teams.values()) if confs is None else candidates(confs)
            if not cands:
                return
            only = confs[0] if confs and len(confs) == 1 else None
            chosen = pick_best_team(
                cands, bowl,
                max_conf_win_skip=cfg.big_ten_max_conf_win_skip if only == "Big Ten" else None,
                enforce_anti_repeat=only in ("Big Ten", "SEC"),
                opponent=assignments[bowl.id][0] if assignments[bowl.id] else None,
            )
            if chosen:
                assignments[bowl.id].append(chosen)
                del available_teams[chosen.id]

        by_prestige = sorted(self.non_cfp_bowls, key=lambda b: (b.prestige, b.payout), reverse=True)

        # 1. Contracted single-conference slots, conference by conference in pick order
        single: dict[str, list[tuple[int, Bowl]]] = {}
        for rank, bowl in enumerate(by_prestige):
            for slot in bowl.slots:
                if len(slot["confs"]) == 1:
                    single.setdefault(slot["confs"][0], []).append((slot.get("order", 99) * 100 + rank, bowl))
        conf_order = CONFERENCE_PICK_ORDER + sorted(set(single) - set(CONFERENCE_PICK_ORDER))
        for conf in conf_order:
            for _, bowl in sorted(single.get(conf, []), key=lambda x: x[0]):
                fill(bowl, [conf])

        # 2. Pooled slots shared by several conferences
        for bowl in by_prestige:
            for slot in bowl.slots:
                if len(slot["confs"]) > 1 and len(assignments[bowl.id]) < 2:
                    fill(bowl, slot["confs"])

        # 3. Anything still open: all remaining eligible teams
        for bowl in by_prestige:
            while len(assignments[bowl.id]) < 2 and available_teams:
                before = len(assignments[bowl.id])
                fill(bowl, None)
                if len(assignments[bowl.id]) == before:
                    break

        # Build list of final BowlMatchup objects
        results: list[BowlMatchup] = []
        for bowl in self.non_cfp_bowls:
            teams_in_bowl = assignments[bowl.id]
            t1 = teams_in_bowl[0] if len(teams_in_bowl) > 0 else None
            t2 = teams_in_bowl[1] if len(teams_in_bowl) > 1 else None

            if t1:
                t1.assigned_bowl = bowl.id
            if t2:
                t2.assigned_bowl = bowl.id

            winner: TeamSimState | None = None
            loser: TeamSimState | None = None
            if t1 and t2:
                # Simulate non-CFP neutral bowl game
                if cfg.win_prob_fn is not None:
                    p_t1 = cfg.win_prob_fn(t1.rating - t2.rating, 0)
                else:
                    z = (t1.rating - t2.rating) / cfg.margin_sd
                    p_t1 = 0.5 * (1.0 + math.erf(z / 1.4142135623730951))
                if rng.random() < p_t1:
                    winner, loser = t1, t2
                else:
                    winner, loser = t2, t1

            results.append(BowlMatchup(
                bowl_id=bowl.id,
                bowl_name=bowl.name,
                team_1=t1,
                team_2=t2,
                is_cfp=False,
                winner=winner,
                loser=loser
            ))

        return results
