"""
Season Simulation Engine:
Simulates remaining regular-season games and conference championship games
using team power ratings, home-field advantage, normal CDF win probabilities,
and optional What-If scenario forcing (e.g., winning out).
"""

from __future__ import annotations

import math
import random
from typing import Sequence

try:
    from .config import SimConfig
except (ImportError, ValueError):
    from config import SimConfig
try:
    from .domain import Game, Team, TeamSimState
except (ImportError, ValueError):
    from domain import Game, Team, TeamSimState
try:
    from .scenarios import Scenario
except (ImportError, ValueError):
    from scenarios import Scenario

# Every FBS conference holds a title game in 2026 (ESPN lists all ten for Dec 4-6).
CONFERENCES_WITH_TITLE_GAME = [
    "SEC", "Big Ten", "Big 12", "ACC", "Pac-12", "MWC", "AAC", "Sun Belt", "MAC", "CUSA"
]

POWER_CONFERENCES = {"SEC", "Big Ten", "Big 12", "ACC"}

def win_probability(
    rating_home: float,
    rating_away: float,
    home_field_points: float,
    margin_sd: float,
    is_neutral: bool = False
) -> float:
    """Calculates home team win probability using normal CDF on projected point margin."""
    h = 0.0 if is_neutral else home_field_points
    projected_margin = (rating_home - rating_away) + h
    z = projected_margin / margin_sd
    return 0.5 * (1.0 + math.erf(z / 1.4142135623730951))

class SeasonSimulator:
    def __init__(
        self,
        teams: list[Team],
        schedule: list[Game],
        config: SimConfig,
        custom_ratings: dict[str, float] | None = None
    ):
        self.teams = teams
        self.team_dict = {t.id: t for t in teams}
        self.schedule = schedule
        self.config = config
        self.custom_ratings = custom_ratings or {t.id: t.rating for t in teams}

    def simulate_season(
        self,
        rng: random.Random,
        scenario: Scenario | None = None
    ) -> dict[str, TeamSimState]:
        """Simulates all remaining schedule games and conference championships for one season."""
        # Initialize simulated states from baseline records and applied ratings
        states: dict[str, TeamSimState] = {}
        for t in self.teams:
            rating = self.custom_ratings.get(t.id, t.rating)
            if scenario and t.id in scenario.rating_overrides:
                rating = scenario.rating_overrides[t.id]

            # Create team copy with active rating
            team_with_rating = Team(
                id=t.id,
                name=t.name,
                conf=t.conf,
                rating=rating,
                apr=t.apr,
                brand=t.brand,
                city=t.city,
                state=t.state,
                lat=t.lat,
                lon=t.lon,
                wins=t.wins,
                losses=t.losses,
                conf_wins=t.conf_wins,
                conf_losses=t.conf_losses,
                legacy_pac12=t.legacy_pac12,
                acc_bowl_eligible=t.acc_bowl_eligible,
                last_bowl=t.last_bowl
            )
            states[t.id] = TeamSimState(
                team=team_with_rating,
                wins=t.wins,
                losses=t.losses,
                conf_wins=t.conf_wins,
                conf_losses=t.conf_losses
            )

        # Track head-to-head outcomes for tiebreakers
        h2h: dict[tuple[str, str], str] = {}

        # 1. Simulate remaining regular season games
        for game in self.schedule:
            home_state = states.get(game.home)
            away_state = states.get(game.away)
            if not game.opponents_are_fbs:
                self._simulate_fcs_game(home_state or away_state, home_state is not None, game, rng, scenario)
                continue
            if not home_state or not away_state:
                raise ValueError(f"schedule.json game {game.away} at {game.home}: unknown FBS team")

            # Check if game outcome is forced by scenario (e.g. wins_out or specific game pick)
            forced_winner_id = scenario.is_forced(home_state.id, away_state.id) if scenario else None

            if forced_winner_id == home_state.id:
                home_won = True
            elif forced_winner_id == away_state.id:
                home_won = False
            else:
                p_home = self._win_prob(
                    home_state.rating, away_state.rating, 0 if game.neutral else 1
                )
                home_won = rng.random() < p_home

            winner = home_state if home_won else away_state
            loser = away_state if home_won else home_state

            winner.wins += 1
            loser.losses += 1

            if game.conf and home_state.conf == away_state.conf:
                winner.conf_wins += 1
                loser.conf_losses += 1

            # Save H2H
            h2h[(winner.id, loser.id)] = winner.id
            h2h[(loser.id, winner.id)] = winner.id

        # 2. Simulate Conference Championship Games
        self._simulate_conference_championships(states, h2h, rng, scenario)

        # 3. Calculate Resume Scores for CFP ranking
        self._calculate_resume_scores(states)

        return states

    def _win_prob(self, rating_a: float, rating_b: float, home: int) -> float:
        """P(A beats B); home = +1 (A at home), 0 (neutral), -1 (A away)."""
        if self.config.win_prob_fn is not None:
            return self.config.win_prob_fn(rating_a - rating_b, home)
        return win_probability(
            rating_a, rating_b, self.config.home_field_points * home,
            self.config.margin_sd, is_neutral=False,
        )

    def _simulate_fcs_game(self, s: TeamSimState | None, fbs_home: bool, game: Game,
                           rng: random.Random, scenario: Scenario | None) -> None:
        """FBS team vs an FCS opponent rated fcs_opponent_rating (never a conference game)."""
        if s is None:
            raise ValueError(f"schedule.json game {game.away} at {game.home}: no FBS team")
        if scenario and s.id in scenario.wins_out:
            won = True
        elif scenario and s.id in scenario.loses_out:
            won = False
        else:
            home = 0 if game.neutral else (1 if fbs_home else -1)
            won = rng.random() < self._win_prob(s.rating, self.config.fcs_opponent_rating, home)
        if won:
            s.wins += 1
        else:
            s.losses += 1

    def _simulate_conference_championships(
        self,
        states: dict[str, TeamSimState],
        h2h: dict[tuple[str, str], str],
        rng: random.Random,
        scenario: Scenario | None = None
    ) -> None:
        """Determines top 2 teams in each conference and simulates the championship game."""
        for conf_name in CONFERENCES_WITH_TITLE_GAME:
            conf_teams = [s for s in states.values() if s.conf == conf_name]
            if len(conf_teams) < 2:
                continue

            # Sort teams within conference for championship game berths:
            # 1. Conference win percentage
            # 2. Total wins
            # 3. Power rating + random tiebreaker jitter
            def conf_sort_key(s: TeamSimState):
                return (
                    s.conf_win_pct,
                    s.conf_wins,
                    s.win_pct,
                    s.rating + rng.uniform(-0.01, 0.01)
                )

            ranked = sorted(conf_teams, key=conf_sort_key, reverse=True)

            team1 = ranked[0]
            team2 = ranked[1]

            # 2-way H2H tiebreak check if records identical
            if len(ranked) >= 2:
                if (ranked[0].conf_win_pct == ranked[1].conf_win_pct and
                    (ranked[0].id, ranked[1].id) in h2h):
                    if h2h[(ranked[0].id, ranked[1].id)] == ranked[1].id:
                        team1, team2 = ranked[1], ranked[0]

            # Check if conference champion is forced by scenario
            if scenario and conf_name in scenario.forced_conf_champs:
                forced_champ_id = scenario.forced_conf_champs[conf_name]
                if team1.id == forced_champ_id:
                    champ, runner_up = team1, team2
                elif team2.id == forced_champ_id:
                    champ, runner_up = team2, team1
                else:
                    # Replace runner up with forced champ
                    forced_team = states.get(forced_champ_id)
                    if forced_team:
                        champ, runner_up = forced_team, team1
                    else:
                        champ, runner_up = team1, team2
            else:
                # If one team is on a forced "win out" run
                if scenario and team1.id in scenario.wins_out and team2.id not in scenario.wins_out:
                    champ, runner_up = team1, team2
                elif scenario and team2.id in scenario.wins_out and team1.id not in scenario.wins_out:
                    champ, runner_up = team2, team1
                else:
                    # Simulate neutral-site conference championship game
                    p_t1 = self._win_prob(team1.rating, team2.rating, 0)
                    if rng.random() < p_t1:
                        champ, runner_up = team1, team2
                    else:
                        champ, runner_up = team2, team1

            champ.wins += 1
            champ.is_conf_champ = True
            runner_up.losses += 1
            runner_up.conf_runner_up = True

    def _calculate_resume_scores(self, states: dict[str, TeamSimState]) -> None:
        """Calculates CFP committee resume scores for all teams."""
        for s in states.values():
            cfg = self.config
            score = 0.0

            # Win percentage (base driver)
            score += s.win_pct * cfg.resume_win_pct_weight

            # Loss penalty: 1 loss is okay, 2 losses hurts, 3+ losses heavily penalised
            if s.losses > 0:
                score -= (s.losses ** cfg.resume_loss_penalty_exponent) * cfg.resume_loss_penalty_scale

            # Power rating (underlying strength)
            score += s.rating * cfg.resume_power_weight

            # Conference Champion bonus
            if s.is_conf_champ:
                score += cfg.resume_conf_champ_bonus
                if s.conf in POWER_CONFERENCES:
                    score += cfg.resume_p4_champ_bonus  # Extra prestige for winning SEC/Big Ten/Big 12/ACC

            # Power conference / Notre Dame schedule strength bonus
            if s.conf in POWER_CONFERENCES or s.id == "notre_dame":
                score += cfg.resume_power4_bonus

            s.resume_score = score
