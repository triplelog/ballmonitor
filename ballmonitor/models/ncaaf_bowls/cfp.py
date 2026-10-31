"""
12-Team College Football Playoff (CFP) selection, seeding and playoff simulation,
2026-27 protocol (collegefootballplayoff.com):
- Automatic bids: the ACC, Big Ten, Big 12 and SEC champions, plus the highest-ranked
  champion of the American, CUSA, MAC, Mountain West, Pac-12 and Sun Belt.
- Seven at-large bids: the next highest-ranked teams.
- Straight seeding by ranking; seeds 1-4 get first-round byes (champions or not).
- Seeds 5-12 play on campus in the first round (5v12, 6v11, 7v10, 8v9).
- Quarterfinal and semifinal bowls come from data/bowls.json (cfp_round); the top four
  seeds are placed in quarterfinal bowls in seed order, each taking the nearest one left.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence

try:
    from .domain import Bowl, TeamSimState
except (ImportError, ValueError):
    from domain import Bowl, TeamSimState

AUTO_BID_CONFERENCES = ("ACC", "Big Ten", "Big 12", "SEC")
GROUP_OF_SIX = ("AAC", "CUSA", "MAC", "MWC", "Pac-12", "Sun Belt")

@dataclass
class CFPGameResult:
    round_name: str
    bowl_id: str | None
    home_team: TeamSimState
    away_team: TeamSimState
    winner: TeamSimState
    loser: TeamSimState

@dataclass
class CFPResult:
    # Seeds 1 to 12
    seeds: list[TeamSimState]
    byes: list[TeamSimState]
    first_round: list[tuple[TeamSimState, TeamSimState]] # (host, visitor)
    bowl_assignments: dict[str, list[str]] # bowl_id -> list of team_ids
    cfp_team_ids: set[str]
    played_games: list[CFPGameResult] = field(default_factory=list)
    national_champion: TeamSimState | None = None

def _sim_game(
    team_a: TeamSimState,
    team_b: TeamSimState,
    home_team: TeamSimState | None,
    home_field_points: float,
    margin_sd: float,
    rng: random.Random,
    win_prob_fn=None,
) -> tuple[TeamSimState, TeamSimState]:
    """Returns (winner, loser)"""
    if win_prob_fn is not None:
        home = 1 if home_team is team_a else (-1 if home_team is team_b else 0)
        p_a = win_prob_fn(team_a.rating - team_b.rating, home)
        if rng.random() < p_a:
            return team_a, team_b
        return team_b, team_a
    is_neutral = home_team is None
    h = 0.0 if is_neutral else home_field_points
    if home_team == team_a:
        margin = (team_a.rating - team_b.rating) + h
    elif home_team == team_b:
        margin = (team_a.rating - team_b.rating) - h
    else:
        margin = (team_a.rating - team_b.rating)

    z = margin / margin_sd
    p_a = 0.5 * (1.0 + math.erf(z / 1.4142135623730951))
    if rng.random() < p_a:
        return team_a, team_b
    return team_b, team_a

class CFPSelector:
    def __init__(self, ny6_bowls: dict[str, Bowl] | None = None):
        self.ny6_bowls = ny6_bowls or {}
        self.quarterfinals = [b for b in self.ny6_bowls.values() if b.cfp_round == "quarterfinal"]
        self.semifinals = [b.id for b in self.ny6_bowls.values() if b.cfp_round == "semifinal"]
        if len(self.quarterfinals) != 4 or len(self.semifinals) != 2:
            raise ValueError("bowls.json needs 4 CFP quarterfinal and 2 semifinal bowls (cfp_round)")

    def select_and_seed(
        self,
        states: dict[str, TeamSimState],
        simulate_games: bool = True,
        rng: random.Random | None = None,
        margin_sd: float = 14.0,
        home_field_points: float = 2.5,
        win_prob_fn=None,
    ) -> CFPResult:
        """Selects, seeds, and optionally simulates the full 12-team CFP bracket."""
        # 1. Rank all teams by resume score (Committee ranking proxy)
        ranked_all = sorted(states.values(), key=lambda s: s.resume_score, reverse=True)

        # 2. Automatic bids: power-four champions + best Group-of-Six champion
        auto = [s for s in ranked_all if s.is_conf_champ and s.conf in AUTO_BID_CONFERENCES]
        g6 = next((s for s in ranked_all if s.is_conf_champ and s.conf in GROUP_OF_SIX), None)
        if g6:
            auto.append(g6)
        field_ids = {s.id for s in auto}

        # 3. At-large bids: next highest-ranked teams until the field has 12
        for s in ranked_all:
            if len(field_ids) >= 12:
                break
            field_ids.add(s.id)

        # 4. Straight seeding by ranking
        full_seeds = [s for s in ranked_all if s.id in field_ids]
        for i, team in enumerate(full_seeds):
            team.cfp_seed = i + 1
            team.cfp_bye = i < 4
        seeds_1_to_4 = full_seeds[:4]

        # 5. First round matchups on campus:
        # Seed 5 hosts 12, 6 hosts 11, 7 hosts 10, 8 hosts 9
        first_round = [
            (full_seeds[4], full_seeds[11]),
            (full_seeds[5], full_seeds[10]),
            (full_seeds[6], full_seeds[9]),
            (full_seeds[7], full_seeds[8]),
        ]

        # 6. Quarterfinal bowls: seeds 1-4 in order, each to the nearest remaining bowl
        open_qf = list(self.quarterfinals)
        seed_qf_bowl: dict[str, str] = {}
        for top in seeds_1_to_4:
            bowl = min(open_qf, key=lambda b: b.distance_to(top.team))
            seed_qf_bowl[top.id] = bowl.id
            open_qf.remove(bowl)
            top.assigned_bowl = bowl.id
        # Semifinals: the 1/8/9 vs 4/5/12 side plays in the first semifinal bowl listed
        semi_a, semi_b = self.semifinals

        bowl_assignments: dict[str, list[str]] = {b.id: [] for b in self.quarterfinals}
        bowl_assignments.update({semi_a: [], semi_b: []})

        cfp_team_ids = {s.id for s in full_seeds}

        # 7. Simulate CFP Tournament if requested
        played_games: list[CFPGameResult] = []
        national_champion: TeamSimState | None = None

        if simulate_games and rng is not None:
            # First Round (on campus, higher seed gets home field)
            w_5_12, l_5_12 = _sim_game(full_seeds[4], full_seeds[11], home_team=full_seeds[4], home_field_points=home_field_points, margin_sd=margin_sd, rng=rng, win_prob_fn=win_prob_fn)
            played_games.append(CFPGameResult("First Round", None, full_seeds[4], full_seeds[11], w_5_12, l_5_12))

            w_6_11, l_6_11 = _sim_game(full_seeds[5], full_seeds[10], home_team=full_seeds[5], home_field_points=home_field_points, margin_sd=margin_sd, rng=rng, win_prob_fn=win_prob_fn)
            played_games.append(CFPGameResult("First Round", None, full_seeds[5], full_seeds[10], w_6_11, l_6_11))

            w_7_10, l_7_10 = _sim_game(full_seeds[6], full_seeds[9], home_team=full_seeds[6], home_field_points=home_field_points, margin_sd=margin_sd, rng=rng, win_prob_fn=win_prob_fn)
            played_games.append(CFPGameResult("First Round", None, full_seeds[6], full_seeds[9], w_7_10, l_7_10))

            w_8_9, l_8_9 = _sim_game(full_seeds[7], full_seeds[8], home_team=full_seeds[7], home_field_points=home_field_points, margin_sd=margin_sd, rng=rng, win_prob_fn=win_prob_fn)
            played_games.append(CFPGameResult("First Round", None, full_seeds[7], full_seeds[8], w_8_9, l_8_9))

            # Quarterfinals (Seeds 1-4 face first round winners in their assigned QF bowls)
            qf_matchup_defs = [
                (full_seeds[0], w_8_9),
                (full_seeds[1], w_7_10),
                (full_seeds[2], w_6_11),
                (full_seeds[3], w_5_12),
            ]

            qf_winners = []
            for top_seed, r1_winner in qf_matchup_defs:
                qf_bowl = seed_qf_bowl[top_seed.id]
                bowl_assignments[qf_bowl] = [top_seed.id, r1_winner.id]
                w, l = _sim_game(top_seed, r1_winner, home_team=None, home_field_points=0.0, margin_sd=margin_sd, rng=rng, win_prob_fn=win_prob_fn)
                played_games.append(CFPGameResult("Quarterfinal", qf_bowl, top_seed, r1_winner, w, l))
                qf_winners.append(w)

            # Semifinals
            semi_1_w, semi_1_l = _sim_game(qf_winners[0], qf_winners[3], home_team=None, home_field_points=0.0, margin_sd=margin_sd, rng=rng, win_prob_fn=win_prob_fn)
            bowl_assignments[semi_a] = [qf_winners[0].id, qf_winners[3].id]
            played_games.append(CFPGameResult("Semifinal", semi_a, qf_winners[0], qf_winners[3], semi_1_w, semi_1_l))

            semi_2_w, semi_2_l = _sim_game(qf_winners[1], qf_winners[2], home_team=None, home_field_points=0.0, margin_sd=margin_sd, rng=rng, win_prob_fn=win_prob_fn)
            bowl_assignments[semi_b] = [qf_winners[1].id, qf_winners[2].id]
            played_games.append(CFPGameResult("Semifinal", semi_b, qf_winners[1], qf_winners[2], semi_2_w, semi_2_l))

            # National Championship Game
            natty_w, natty_l = _sim_game(semi_1_w, semi_2_w, home_team=None, home_field_points=0.0, margin_sd=margin_sd, rng=rng, win_prob_fn=win_prob_fn)
            played_games.append(CFPGameResult("National Championship", None, semi_1_w, semi_2_w, natty_w, natty_l))
            national_champion = natty_w
        else:
            for champ in seeds_1_to_4:
                bowl_assignments[seed_qf_bowl[champ.id]].append(champ.id)

        return CFPResult(
            seeds=full_seeds,
            byes=seeds_1_to_4,
            first_round=first_round,
            bowl_assignments=bowl_assignments,
            cfp_team_ids=cfp_team_ids,
            played_games=played_games,
            national_champion=national_champion
        )
