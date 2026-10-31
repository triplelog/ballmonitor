"""
Simulation Engine & Aggregator:
Orchestrates Monte Carlo season simulations, aggregates CFP and bowl probabilities,
computes opponent distributions (overall & per bowl), and calculates bowl win probabilities.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from .cfp import CFPGameResult, CFPResult, CFPSelector
except (ImportError, ValueError):
    from cfp import CFPGameResult, CFPResult, CFPSelector
try:
    from .config import DATA_DIR, SimConfig
except (ImportError, ValueError):
    from config import DATA_DIR, SimConfig
try:
    from .domain import Bowl, Game, Team
except (ImportError, ValueError):
    from domain import Bowl, Game, Team
try:
    from .ratings import RatingManager
except (ImportError, ValueError):
    from ratings import RatingManager
try:
    from .scenarios import Scenario
except (ImportError, ValueError):
    from scenarios import Scenario
try:
    from .selection import BowlMatchup, BowlSelector
except (ImportError, ValueError):
    from selection import BowlMatchup, BowlSelector
try:
    from .simulator import SeasonSimulator
except (ImportError, ValueError):
    from simulator import SeasonSimulator

@dataclass
class BowlAppearanceDetail:
    bowl_id: str
    bowl_name: str
    p_appear: float
    p_win_conditional: float
    p_win_unconditional: float
    opponents: list[tuple[str, float, float]] # [(opp_name, cond_prob, win_rate_vs_opp)]

@dataclass
class TeamSummary:
    team_id: str
    team_name: str
    conf: str
    rating: float
    record_mean_wins: float
    record_mean_losses: float
    p_eligible: float
    p_conf_champ: float
    p_cfp: float
    p_cfp_bye: float
    p_play_postseason: float
    p_win_any_bowl: float
    national_champ_prob: float
    top_seeds: dict[int, float]
    overall_opponents: list[tuple[str, float, float]] # [(opp_name, prob, win_rate)]
    top_bowls: list[tuple[str, str, float]]           # [(bowl_id, bowl_name, prob)]
    bowls_detail: dict[str, BowlAppearanceDetail]
    all_bowls: dict[str, float]
    conf_rank_probs: dict[int, float] = field(default_factory=dict)
    expected_non_playoff_rank: float | None = None

@dataclass
class BowlSummary:
    bowl_id: str
    bowl_name: str
    city: str
    state: str
    is_cfp: bool
    top_teams: list[tuple[str, float]]                # [(team_name, prob)]
    top_matchups: list[tuple[str, str, float]]        # [(team1, team2, prob)]

@dataclass
class SimulationResults:
    total_simulations: int
    team_summaries: dict[str, TeamSummary]
    bowl_summaries: dict[str, BowlSummary]
    conf_cfp_bids_mean: dict[str, float]
    conference_pecking_orders: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    active_ratings_source: str = "default"
    active_scenario: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_simulations": self.total_simulations,
            "ratings_source": self.active_ratings_source,
            "scenario": self.active_scenario,
            "conf_cfp_bids_mean": self.conf_cfp_bids_mean,
            "conference_pecking_orders": self.conference_pecking_orders,
            "teams": {
                t_id: {
                    "name": s.team_name,
                    "conf": s.conf,
                    "rating": s.rating,
                    "projected_record": f"{s.record_mean_wins:.1f}-{s.record_mean_losses:.1f}",
                    "p_eligible": round(s.p_eligible, 4),
                    "p_conf_champ": round(s.p_conf_champ, 4),
                    "p_cfp": round(s.p_cfp, 4),
                    "p_cfp_bye": round(s.p_cfp_bye, 4),
                    "p_play_postseason": round(s.p_play_postseason, 4),
                    "p_win_any_bowl": round(s.p_win_any_bowl, 4),
                    "national_champ_prob": round(s.national_champ_prob, 4),
                    "top_bowls": [
                        {
                            "bowl_id": bid,
                            "bowl_name": bname,
                            "probability": round(prob, 4),
                            "win_prob_given_bowl": round(s.bowls_detail[bid].p_win_conditional, 4) if bid in s.bowls_detail else 0.0,
                            "win_prob_unconditional": round(s.bowls_detail[bid].p_win_unconditional, 4) if bid in s.bowls_detail else 0.0,
                        }
                        for bid, bname, prob in s.top_bowls
                    ],
                    "top_opponents_overall": [
                        {"opponent": opp, "probability": round(p, 4), "win_rate": round(wr, 4)}
                        for opp, p, wr in s.overall_opponents[:6]
                    ]
                }
                for t_id, s in self.team_summaries.items()
            },
            "bowls": {
                b_id: {
                    "name": b.bowl_name,
                    "city": b.city,
                    "state": b.state,
                    "is_cfp": b.is_cfp,
                    "top_teams": [
                        {"team": t, "probability": round(p, 4)}
                        for t, p in b.top_teams[:8]
                    ],
                    "top_matchups": [
                        {"team_1": t1, "team_2": t2, "probability": round(p, 4)}
                        for t1, t2, p in b.top_matchups[:5]
                    ]
                }
                for b_id, b in self.bowl_summaries.items()
            }
        }

@lru_cache(maxsize=16)
def _load_json_cached(path_str: str) -> list[dict[str, Any]]:
    with open(path_str, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=8)
def _load_teams_raw_cached(data_dir_str: str) -> list[dict[str, Any]]:
    data_dir = Path(data_dir_str)
    data = [dict(d) for d in _load_json_cached(str((data_dir / "teams.json").resolve()))]
    hist_path = data_dir / "historical" / "historical_bowls_2014_2023.json"
    if hist_path.exists():
        try:
            hist_data = _load_json_cached(str(hist_path.resolve()))
            latest_year = max(h.get("year", 0) for h in hist_data)
            last_year_matchups = [h for h in hist_data if h.get("year") == latest_year]
            bowl_map = {}
            for m in last_year_matchups:
                bid = m.get("bowl_id")
                if bid:
                    bowl_map[m.get("team_1")] = bid
                    bowl_map[m.get("team_2")] = bid
            for d in data:
                if not d.get("last_bowl") and d.get("id") in bowl_map:
                    d["last_bowl"] = bowl_map[d["id"]]
        except Exception:
            pass
    return data


class BowlEngine:
    def __init__(
        self,
        config: SimConfig | None = None,
        data_dir: Path | None = None,
        ratings_source: str | Path | dict[str, float] | None = None
    ):
        self.config = config or SimConfig()
        self.data_dir = data_dir or DATA_DIR

        self.teams = self._load_teams()
        self.bowls = self._load_bowls()
        self.schedule = self._load_schedule()

        self.team_dict = {t.id: t for t in self.teams}
        self.bowl_dict = {b.id: b for b in self.bowls}

        # Load ratings
        self.ratings_source = ratings_source or "default"
        self.active_ratings = RatingManager.load_ratings(self.ratings_source, self.teams)

        self.simulator = SeasonSimulator(self.teams, self.schedule, self.config, self.active_ratings)
        self.cfp_selector = CFPSelector({b.id: b for b in self.bowls if b.is_cfp})
        self.bowl_selector = BowlSelector(self.bowls, self.teams, self.config, schedule=self.schedule)

    def set_ratings(self, source: str | Path | dict[str, float]) -> None:
        """Switch active power ratings."""
        self.ratings_source = str(source)
        self.active_ratings = RatingManager.load_ratings(source, self.teams)
        self.simulator.custom_ratings = self.active_ratings

    def _load_teams(self) -> list[Team]:
        return [Team.from_dict(d) for d in _load_teams_raw_cached(str(self.data_dir.resolve()))]

    def _load_bowls(self) -> list[Bowl]:
        return [Bowl.from_dict(d) for d in _load_json_cached(str((self.data_dir / "bowls.json").resolve()))]

    def _load_schedule(self) -> list[Game]:
        return [Game.from_dict(d) for d in _load_json_cached(str((self.data_dir / "schedule.json").resolve()))]

    def run(
        self,
        num_sims: int | None = None,
        scenario: Scenario | None = None
    ) -> SimulationResults:
        """Runs N Monte Carlo season simulations and aggregates results."""
        n_sims = num_sims or self.config.simulations
        rng = random.Random(self.config.random_seed)

        # Basic Tracking accumulators
        team_wins = defaultdict(int)
        team_losses = defaultdict(int)
        team_eligible_count = defaultdict(int)
        team_conf_champ_count = defaultdict(int)
        team_cfp_count = defaultdict(int)
        team_bye_count = defaultdict(int)
        team_national_champ_count = defaultdict(int)
        team_seed_counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        team_bowl_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Bowl specific & win tracking
        # team_id -> bowl_id -> count of wins
        team_bowl_wins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # team_id -> bowl_id -> opponent_id -> count of times played
        team_bowl_opp_counts: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        # team_id -> bowl_id -> opponent_id -> count of times won
        team_bowl_opp_wins: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        # Overall postseason & opponent tracking
        team_postseason_played_count = defaultdict(int)
        team_won_any_bowl_count = defaultdict(int)
        team_overall_opp_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        team_overall_opp_wins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Conference pecking order tracking (ranks among non-playoff bowl-eligible teams)
        team_conf_rank_counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        team_conf_rank_total_sum = defaultdict(int)
        team_conf_non_cfp_eligible_count = defaultdict(int)

        # Bowl level summaries
        bowl_team_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        bowl_matchup_counts: dict[str, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
        conf_cfp_bids_total: dict[str, int] = defaultdict(int)

        for _ in range(n_sims):
            # Track postseason participation & wins in this specific simulation run
            teams_played_postseason_this_sim: set[str] = set()
            teams_won_postseason_this_sim: set[str] = set()

            # 1. Simulate Season (respecting What-If scenario)
            states = self.simulator.simulate_season(rng, scenario=scenario)

            # 2. Select, Seed & Simulate CFP
            cfp_res = self.cfp_selector.select_and_seed(
                states,
                simulate_games=True,
                rng=rng,
                margin_sd=self.config.margin_sd,
                home_field_points=self.config.home_field_points,
                win_prob_fn=self.config.win_prob_fn,
            )

            if cfp_res.national_champion:
                team_national_champ_count[cfp_res.national_champion.id] += 1

            # Record CFP bids by conference & seeds
            for seed in cfp_res.seeds:
                conf_cfp_bids_total[seed.conf] += 1
                team_cfp_count[seed.id] += 1
                team_seed_counts[seed.id][seed.cfp_seed] += 1
                if seed.cfp_bye:
                    team_bye_count[seed.id] += 1
                teams_played_postseason_this_sim.add(seed.id)

            # Record Quarterfinal & Semifinal bowl appearances
            for b_id, team_ids in cfp_res.bowl_assignments.items():
                for t_id in team_ids:
                    team_bowl_counts[t_id][b_id] += 1
                    bowl_team_counts[b_id][t_id] += 1

            # Record CFP Games, Opponents & Wins
            for game in cfp_res.played_games:
                w_id = game.winner.id
                l_id = game.loser.id
                teams_won_postseason_this_sim.add(w_id)

                # Overall opponent tracking
                team_overall_opp_counts[w_id][l_id] += 1
                team_overall_opp_counts[l_id][w_id] += 1
                team_overall_opp_wins[w_id][l_id] += 1

                # If this game took place in a NY6 bowl
                if game.bowl_id:
                    b_id = game.bowl_id
                    team_bowl_wins[w_id][b_id] += 1
                    team_bowl_opp_counts[w_id][b_id][l_id] += 1
                    team_bowl_opp_counts[l_id][b_id][w_id] += 1
                    team_bowl_opp_wins[w_id][b_id][l_id] += 1

                    pair = tuple(sorted([game.home_team.name, game.away_team.name]))
                    bowl_matchup_counts[b_id][pair] += 1

            # 3. Select & Simulate Non-CFP Bowls
            bowl_matchups = self.bowl_selector.select_bowls(states, cfp_res.cfp_team_ids, rng)

            for m in bowl_matchups:
                t1 = m.team_1
                t2 = m.team_2
                w = m.winner
                l = m.loser

                if t1:
                    team_bowl_counts[t1.id][m.bowl_id] += 1
                    bowl_team_counts[m.bowl_id][t1.id] += 1
                    teams_played_postseason_this_sim.add(t1.id)
                if t2:
                    team_bowl_counts[t2.id][m.bowl_id] += 1
                    bowl_team_counts[m.bowl_id][t2.id] += 1
                    teams_played_postseason_this_sim.add(t2.id)

                if t1 and t2 and w and l:
                    teams_won_postseason_this_sim.add(w.id)

                    # Track Bowl Wins
                    team_bowl_wins[w.id][m.bowl_id] += 1

                    # Track Opponents in this bowl
                    team_bowl_opp_counts[t1.id][m.bowl_id][t2.id] += 1
                    team_bowl_opp_counts[t2.id][m.bowl_id][t1.id] += 1
                    team_bowl_opp_wins[w.id][m.bowl_id][l.id] += 1

                    # Track Overall Opponents
                    team_overall_opp_counts[t1.id][t2.id] += 1
                    team_overall_opp_counts[t2.id][t1.id] += 1
                    team_overall_opp_wins[w.id][l.id] += 1

                    # Normalized matchup pair for bowl summary
                    pair = tuple(sorted([t1.name, t2.name]))
                    bowl_matchup_counts[m.bowl_id][pair] += 1

            # Update sim-level tallies
            for t_id in teams_played_postseason_this_sim:
                team_postseason_played_count[t_id] += 1
            for t_id in teams_won_postseason_this_sim:
                team_won_any_bowl_count[t_id] += 1

            # Record general season stats
            for t_id, s in states.items():
                team_wins[t_id] += s.wins
                team_losses[t_id] += s.losses
                if s.wins >= self.config.bowl_eligible_wins:
                    team_eligible_count[t_id] += 1
                if s.is_conf_champ:
                    team_conf_champ_count[t_id] += 1

            # 4. Record conference pecking order of non-playoff bowl-eligible teams
            conf_to_states = defaultdict(list)
            for s in states.values():
                conf_to_states[s.conf].append(s)

            for conf_name, c_states in conf_to_states.items():
                eligible_non_cfp = [
                    s for s in c_states
                    if s.id not in cfp_res.cfp_team_ids and s.wins >= self.config.bowl_eligible_wins
                ]
                # Sort by conference bowl selection priority:
                # 1. conf_win_pct
                # 2. conf_wins
                # 3. total wins
                # 4. resume_score
                sorted_picks = sorted(
                    eligible_non_cfp,
                    key=lambda s: (s.conf_win_pct, s.conf_wins, s.wins, s.resume_score),
                    reverse=True
                )
                for rank_idx, s in enumerate(sorted_picks, start=1):
                    team_conf_rank_counts[s.id][rank_idx] += 1
                    team_conf_rank_total_sum[s.id] += rank_idx
                    team_conf_non_cfp_eligible_count[s.id] += 1

        # Aggregate Team Summaries
        team_summaries: dict[str, TeamSummary] = {}
        for t in self.teams:
            t_id = t.id
            mean_wins = team_wins[t_id] / n_sims
            mean_losses = team_losses[t_id] / n_sims
            p_elig = team_eligible_count[t_id] / n_sims
            p_champ = team_conf_champ_count[t_id] / n_sims
            p_cfp = team_cfp_count[t_id] / n_sims
            p_bye = team_bye_count[t_id] / n_sims
            p_play_post = team_postseason_played_count[t_id] / n_sims
            p_win_any = team_won_any_bowl_count[t_id] / n_sims
            p_natty = team_national_champ_count[t_id] / n_sims

            # Seeds
            seeds_dist = {
                seed: count / n_sims
                for seed, count in sorted(team_seed_counts[t_id].items())
            }

            # Bowls probabilities & detailed opponent breakdowns
            all_b_probs = {
                b_id: count / n_sims
                for b_id, count in team_bowl_counts[t_id].items()
            }

            bowls_detail: dict[str, BowlAppearanceDetail] = {}
            for b_id, p_appear in all_b_probs.items():
                b_obj = self.bowl_dict.get(b_id)
                b_name = b_obj.name if b_obj else b_id
                appear_cnt = team_bowl_counts[t_id][b_id]
                win_cnt = team_bowl_wins[t_id][b_id]

                p_win_cond = (win_cnt / appear_cnt) if appear_cnt > 0 else 0.0
                p_win_uncond = win_cnt / n_sims

                # Opponent breakdown for this specific bowl
                opp_counts = team_bowl_opp_counts[t_id][b_id]
                sorted_opps = sorted(opp_counts.items(), key=lambda x: x[1], reverse=True)
                opp_list = []
                for opp_id, cnt in sorted_opps:
                    opp_team = self.team_dict.get(opp_id)
                    opp_name = opp_team.name if opp_team else opp_id
                    opp_cond_prob = cnt / appear_cnt if appear_cnt > 0 else 0.0
                    opp_wins = team_bowl_opp_wins[t_id][b_id][opp_id]
                    opp_wr = opp_wins / cnt if cnt > 0 else 0.0
                    opp_list.append((opp_name, opp_cond_prob, opp_wr))

                bowls_detail[b_id] = BowlAppearanceDetail(
                    bowl_id=b_id,
                    bowl_name=b_name,
                    p_appear=p_appear,
                    p_win_conditional=p_win_cond,
                    p_win_unconditional=p_win_uncond,
                    opponents=opp_list
                )

            # Top 4 bowls
            top_bowls_list = []
            sorted_b = sorted(all_b_probs.items(), key=lambda x: x[1], reverse=True)
            for b_id, prob in sorted_b[:4]:
                b_obj = self.bowl_dict.get(b_id)
                b_name = b_obj.name if b_obj else b_id
                top_bowls_list.append((b_id, b_name, prob))

            # Overall Opponent Breakdown across all postseason games
            overall_opp_counts = team_overall_opp_counts[t_id]
            sorted_overall_opps = sorted(overall_opp_counts.items(), key=lambda x: x[1], reverse=True)
            overall_opponents_list = []
            for opp_id, cnt in sorted_overall_opps:
                opp_team = self.team_dict.get(opp_id)
                opp_name = opp_team.name if opp_team else opp_id
                p_facing = cnt / n_sims
                w_cnt = team_overall_opp_wins[t_id][opp_id]
                wr = w_cnt / cnt if cnt > 0 else 0.0
                overall_opponents_list.append((opp_name, p_facing, wr))

            active_r = self.active_ratings.get(t_id, t.rating)

            # Conference pecking order probabilities
            conf_rank_probs = {
                r: count / n_sims
                for r, count in sorted(team_conf_rank_counts[t_id].items())
            }
            exp_rank = (team_conf_rank_total_sum[t_id] / team_conf_non_cfp_eligible_count[t_id]) if team_conf_non_cfp_eligible_count[t_id] > 0 else None

            team_summaries[t_id] = TeamSummary(
                team_id=t_id,
                team_name=t.name,
                conf=t.conf,
                rating=active_r,
                record_mean_wins=mean_wins,
                record_mean_losses=mean_losses,
                p_eligible=p_elig,
                p_conf_champ=p_champ,
                p_cfp=p_cfp,
                p_cfp_bye=p_bye,
                p_play_postseason=p_play_post,
                p_win_any_bowl=p_win_any,
                national_champ_prob=p_natty,
                top_seeds=seeds_dist,
                overall_opponents=overall_opponents_list,
                top_bowls=top_bowls_list,
                bowls_detail=bowls_detail,
                all_bowls=all_b_probs,
                conf_rank_probs=conf_rank_probs,
                expected_non_playoff_rank=exp_rank
            )

        # Aggregate Bowl Summaries
        bowl_summaries: dict[str, BowlSummary] = {}
        for b in self.bowls:
            b_id = b.id
            t_counts = bowl_team_counts[b_id]
            sorted_teams = sorted(t_counts.items(), key=lambda x: x[1], reverse=True)
            top_teams = [
                (self.team_dict[t_id].name if t_id in self.team_dict else t_id, cnt / n_sims)
                for t_id, cnt in sorted_teams
            ]

            m_counts = bowl_matchup_counts[b_id]
            sorted_matchups = sorted(m_counts.items(), key=lambda x: x[1], reverse=True)
            top_matchups = [
                (pair[0], pair[1], cnt / n_sims)
                for pair, cnt in sorted_matchups
            ]

            bowl_summaries[b_id] = BowlSummary(
                bowl_id=b_id,
                bowl_name=b.name,
                city=b.city,
                state=b.state,
                is_cfp=b.is_cfp,
                top_teams=top_teams,
                top_matchups=top_matchups
            )

        conf_cfp_bids_mean = {
            conf: total / n_sims
            for conf, total in sorted(conf_cfp_bids_total.items(), key=lambda x: x[1], reverse=True)
        }

        # Aggregate Conference Pecking Orders for non-playoff bowl-eligible teams
        conference_pecking_orders: dict[str, list[dict[str, Any]]] = {}
        conf_teams_map = defaultdict(list)
        for t in self.teams:
            conf_teams_map[t.conf].append(t)

        for conf_name, c_teams in conf_teams_map.items():
            if conf_name in ("Independent",):
                continue
            rows = []
            for t in c_teams:
                t_id = t.id
                tsum = team_summaries[t_id]
                r_probs = tsum.conf_rank_probs
                p_cfp = tsum.p_cfp
                p_inelig = max(0.0, 1.0 - tsum.p_eligible)
                p1 = r_probs.get(1, 0.0)
                p2 = r_probs.get(2, 0.0)
                p3 = r_probs.get(3, 0.0)
                p4 = r_probs.get(4, 0.0)
                p5 = r_probs.get(5, 0.0)
                p6_plus = sum(p for r, p in r_probs.items() if r >= 6)
                rows.append({
                    "team_id": t_id,
                    "team_name": t.name,
                    "conf": conf_name,
                    "rating": tsum.rating,
                    "proj_record": f"{tsum.record_mean_wins:.1f}-{tsum.record_mean_losses:.1f}",
                    "p_cfp": p_cfp,
                    "p_ineligible": p_inelig,
                    "p_rank_1": p1,
                    "p_rank_2": p2,
                    "p_rank_3": p3,
                    "p_rank_4": p4,
                    "p_rank_5": p5,
                    "p_rank_6_plus": p6_plus,
                    "expected_rank": tsum.expected_non_playoff_rank,
                })
            rows.sort(
                key=lambda x: (
                    x["p_rank_1"],
                    x["p_rank_2"],
                    x["p_rank_3"],
                    -(x["expected_rank"] or 99.0)
                ),
                reverse=True
            )
            conference_pecking_orders[conf_name] = rows

        return SimulationResults(
            total_simulations=n_sims,
            team_summaries=team_summaries,
            bowl_summaries=bowl_summaries,
            conf_cfp_bids_mean=conf_cfp_bids_mean,
            conference_pecking_orders=conference_pecking_orders,
            active_ratings_source=str(self.ratings_source),
            active_scenario=str(scenario) if scenario else None
        )
