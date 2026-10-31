"""MLB Game and Bullpen Monte Carlo Simulator.

Simulates plate appearances, base-out transitions, game score evolution,
starter endurance, the 3-batter minimum rule, leverage situations, and
managerial bullpen call decisions.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from ballmonitor.models.mlb_bullpen.ledger import BullpenLedger, RelieverWorkload


@dataclass
class PitchingAppearance:
    """Record of a pitcher's appearance in a single game simulation."""

    name: str
    is_starter: bool
    role: str
    hand: str
    outs_recorded: int = 0
    batters_faced: int = 0
    pitches: int = 0
    runs_allowed: int = 0
    earned_save: bool = False
    order_entered: int = 0  # 0 = starter, 1 = 1st reliever, 2 = 2nd, etc.
    entry_lead: int = 0  # our lead (runs) when the pitcher entered
    entry_runners: int = 0  # runners on base when the pitcher entered
    lead_lost: bool = False  # lead became a tie/deficit while he pitched

    @property
    def innings_pitched(self) -> float:
        """Innings pitched in standard baseball notation (e.g., 1.1 = 1 inn + 1 out)."""
        full_innings = self.outs_recorded // 3
        partial_outs = self.outs_recorded % 3
        return full_innings + (partial_outs * 0.1)

    @property
    def decimal_ip(self) -> float:
        """Exact innings pitched as a float (e.g., 1.333 for 4 outs)."""
        return self.outs_recorded / 3.0


@dataclass
class GameSimulationResult:
    """Outcome of one simulated baseball game."""

    team_score: int
    opp_score: int
    innings_played: int
    won: bool
    pitchers_used: list[PitchingAppearance]
    lead_after_7: bool


@dataclass
class RelieverStats:
    """Aggregated simulation metrics for one reliever."""

    name: str
    role: str
    hand: str
    appearances: int = 0
    first_in_count: int = 0
    saves: int = 0
    appear_when_leading_7: int = 0
    appear_when_trailing_7: int = 0
    total_outs: int = 0
    total_pitches: int = 0
    outs_list: list[int] = field(default_factory=list)
    pitches_list: list[int] = field(default_factory=list)


def compute_leverage_index(
    inning: int,
    score_diff: int,
    outs: int = 0,
    on_1b: bool = False,
    on_2b: bool = False,
    on_3b: bool = False,
) -> float:
    """Analytical approximation of Tom Tango's empirical Leverage Index (LI).

    LI = 1.0 represents league average leverage across all plate appearances.
    LI < 0.85 = Low Leverage (early innings, comfortable leads/deficits).
    LI 1.5 - 2.8 = High Leverage (tight game in 7th+ inning).
    LI >= 2.8 = Extreme Leverage / Fireman jam (runners in scoring position in late tight game).
    """
    base_state = (bool(on_1b), bool(on_2b), bool(on_3b))
    if base_state == (False, False, False):
        b_mult = 0.85 if outs == 0 else 0.65 if outs == 1 else 0.45
    elif base_state == (True, False, False):
        b_mult = 1.4 if outs == 0 else 1.2 if outs == 1 else 0.9
    elif base_state == (False, True, False):
        b_mult = 1.8 if outs == 0 else 1.6 if outs == 1 else 1.3
    elif base_state == (False, False, True):
        b_mult = 2.0 if outs == 0 else 1.8 if outs == 1 else 1.3
    elif base_state == (True, True, False):
        b_mult = 2.3 if outs == 0 else 2.1 if outs == 1 else 1.7
    elif base_state == (True, False, True):
        b_mult = 2.4 if outs == 0 else 2.2 if outs == 1 else 1.8
    elif base_state == (False, True, True):
        b_mult = 2.8 if outs == 0 else 2.6 if outs == 1 else 2.1
    else:  # Bases loaded
        b_mult = 3.4 if outs == 0 else 3.2 if outs == 1 else 2.6

    if inning <= 3:
        i_mult = 0.6
    elif inning <= 5:
        i_mult = 0.8
    elif inning == 6:
        i_mult = 1.0
    elif inning == 7:
        i_mult = 1.3
    elif inning == 8:
        i_mult = 1.7
    else:  # 9+
        i_mult = 2.3

    abs_margin = abs(score_diff)
    if abs_margin == 0:
        m_mult = 1.6
    elif abs_margin == 1:
        m_mult = 1.5
    elif abs_margin == 2:
        m_mult = 1.05
    elif abs_margin == 3:
        m_mult = 0.65
    elif abs_margin == 4:
        m_mult = 0.35
    else:
        m_mult = 0.12

    return round((b_mult * i_mult * m_mult) / 1.15, 2)


def is_save(last: PitchingAppearance) -> bool:
    """MLB Rule 9.19 save test for the pitcher who finished a win."""
    lead = last.entry_lead
    if last.is_starter or lead < 1 or last.lead_lost or last.outs_recorded < 1:
        return False
    return (
        (lead <= 3 and last.outs_recorded >= 3)  # lead of 3 or fewer, 1+ inning
        or lead <= last.entry_runners + 2  # tying run on base, at bat or on deck
        or last.outs_recorded >= 9  # 3+ innings
    )


SITUATIONS = ("early", "middle", "late_other", "late_close", "fireman", "save", "late_tie", "blowout")
SITUATION_ROLES = ("closer", "setup", "long")  # middle relievers are the reference (bonus 0)


def classify_situation(inning: int, lead: int, li: float, params: Any) -> str:
    """Game situation when a reliever is called (first match wins):

    save       inning >= 9, lead 1..save_lead_max
    late_tie   inning >= 9, tied or trailing by <= close_deficit_max
    blowout    |lead| >= blowout_margin
    fireman    inning >= close_game_inning, close game, LI >= li_extreme_threshold
    late_close inning >= close_game_inning, -close_deficit_max <= lead <= close_lead_max
    late_other inning >= close_game_inning, anything else
    early      inning <= early_exit_inning
    middle     everything else (the reference situation: no bonuses)
    """
    p = params
    if inning >= 9 and 1 <= lead <= p.save_lead_max:
        return "save"
    if inning >= 9 and -p.close_deficit_max <= lead <= 0:
        return "late_tie"
    if abs(lead) >= p.blowout_margin:
        return "blowout"
    if inning >= p.close_game_inning:
        if -p.close_deficit_max <= lead <= p.close_lead_max:
            return "fireman" if li >= p.li_extreme_threshold else "late_close"
        return "late_other"
    if inning <= p.early_exit_inning:
        return "early"
    return "middle"


def role_base(params: Any, role: str) -> float:
    """Base score by role (middle relievers = 0, the reference)."""
    return 0.0 if role == "middle" else float(getattr(params, f"role_{role}"))


def situation_bonus(params: Any, situation: str, role: str) -> float:
    """Param sit_<situation>_<role>; 0 for middle relievers and the middle situation."""
    if situation == "middle" or role not in SITUATION_ROLES:
        return 0.0
    return float(getattr(params, f"sit_{situation}_{role}"))


def platoon_match(hand: str, upcoming: list[str], params: Any) -> int:
    """1 if at least platoon_min_batters of the next batters bat from the pitcher's side
    (switch hitters never count)."""
    return int(upcoming.count(hand) >= params.platoon_min_batters)


def static_score(rel: RelieverWorkload, ledger: BullpenLedger, params: Any, off_day_tomorrow: bool) -> float:
    """Situation-independent part of a reliever's score: role base + usage - fatigue."""
    return (
        role_base(params, rel.role)
        + rel.usage_score(params)
        - ledger.compute_fatigue_penalty(rel, params, off_day_tomorrow=off_day_tomorrow)
    )


class GameSimulator:
    """Simulates games and models managerial pitching changes."""

    def __init__(
        self,
        *,
        starter_name: str,
        starter_hand: str,
        starter_stamina: int,
        ledger: BullpenLedger,
        lineup: list[str],
        params: Any,
        is_home: bool = True,
        off_day_tomorrow: bool = False,
    ):
        self.starter_name = starter_name
        self.starter_hand = starter_hand.upper()
        self.starter_stamina = starter_stamina
        self.ledger = ledger
        self.lineup = [h.upper() for h in lineup] if lineup else ["R"] * 9
        self.params = params
        self.is_home = is_home
        self.off_day_tomorrow = off_day_tomorrow
        self._avail_cache = {
            rel.name: self.ledger.is_available(rel, self.params)
            for rel in self.ledger.relievers.values()
        }
        self._static_score = {
            rel.name: static_score(rel, self.ledger, self.params, self.off_day_tomorrow)
            for rel in self.ledger.relievers.values()
        }

    def simulate_game(self, rng: random.Random | None = None) -> GameSimulationResult:
        """Simulate one full MLB game from start to finish."""
        r = rng or random

        team_score = 0
        opp_score = 0
        lead_after_7 = False

        pitchers_used: list[PitchingAppearance] = []
        used_names: set[str] = set()

        # Start with starting pitcher
        current_pitcher = PitchingAppearance(
            name=self.starter_name,
            is_starter=True,
            role="starter",
            hand=self.starter_hand,
            order_entered=0,
        )
        pitchers_used.append(current_pitcher)
        used_names.add(self.starter_name)

        lineup_idx = 0
        inning = 1

        while inning <= 12:  # Cap extra innings at 12
            # Half 1: Away team batting, Home team defending
            # Half 2: Home team batting, Away team defending

            # Check lead after 7 innings
            if inning == 8 and not lead_after_7:
                lead_after_7 = team_score > opp_score

            # --- HALF INNING WHERE OUR TEAM DEFENDS ---
            # If our team is home, we defend Top of inning.
            # If our team is away, we defend Bottom of inning.
            if self.is_home:
                # Top half: opp bat, we defend
                runs, lineup_idx = self._simulate_defensive_half(
                    inning=inning,
                    team_score=team_score,
                    opp_score=opp_score,
                    lineup_idx=lineup_idx,
                    current_pitcher=current_pitcher,
                    pitchers_used=pitchers_used,
                    used_names=used_names,
                    r=r,
                )
                opp_score += runs
                current_pitcher = pitchers_used[-1]

                # Bottom half: we bat, opp defends
                if inning >= 9 and team_score > opp_score:
                    # Home team already leading in 9th+; game ends (no bottom 9 needed)
                    break

                runs_scored = self._simulate_offensive_half(r)
                team_score += runs_scored

                # Walk-off check in bottom 9th+
                if inning >= 9 and team_score > opp_score:
                    break
            else:
                # Away team: we bat Top, we defend Bottom
                runs_scored = self._simulate_offensive_half(r)
                team_score += runs_scored

                # Bottom half: opp bat, we defend
                if inning >= 9 and opp_score > team_score:
                    # Home team leading going into bottom 9+; game over
                    break

                runs, lineup_idx = self._simulate_defensive_half(
                    inning=inning,
                    team_score=team_score,
                    opp_score=opp_score,
                    lineup_idx=lineup_idx,
                    current_pitcher=current_pitcher,
                    pitchers_used=pitchers_used,
                    used_names=used_names,
                    r=r,
                )
                opp_score += runs
                current_pitcher = pitchers_used[-1]

                # Walk-off check
                if inning >= 9 and opp_score > team_score:
                    break

            # Check if game decided after 9 full innings
            if inning >= 9 and team_score != opp_score:
                break

            inning += 1

        won = team_score > opp_score

        # Saves (MLB Rule 9.19): the reliever who finished a win, entered with a
        # lead he never relinquished, and either (a) entered with a lead of 3 or
        # fewer and pitched 1+ inning, (b) entered with the tying run on base, at
        # bat or on deck, or (c) pitched 3+ innings. A walk-off win is never a save
        # (the lead was not held while he pitched).
        if won and len(pitchers_used) > 1:
            pitchers_used[-1].earned_save = is_save(pitchers_used[-1])

        return GameSimulationResult(
            team_score=team_score,
            opp_score=opp_score,
            innings_played=min(inning, 12),
            won=won,
            pitchers_used=pitchers_used,
            lead_after_7=lead_after_7,
        )

    def _simulate_offensive_half(self, r: random.Random) -> int:
        """Runs scored by our team in a half-inning, drawn from the config list
        `offense_runs_cdf` = [P(0), P(<=1), P(<=2), P(<=3)]; 4+ runs = 4..6 uniformly."""
        u = r.random()
        for runs, cum in enumerate(self.params.offense_runs_cdf):
            if u < cum:
                return runs
        return 4 + r.randint(0, 2)

    def _simulate_defensive_half(
        self,
        *,
        inning: int,
        team_score: int,
        opp_score: int,
        lineup_idx: int,
        current_pitcher: PitchingAppearance,
        pitchers_used: list[PitchingAppearance],
        used_names: set[str],
        r: random.Random,
    ) -> tuple[int, int]:
        """Simulate the half-inning where our team pitches and defends."""
        outs = 0
        runs_in_half = 0
        on_1b = False
        on_2b = False
        on_3b = False

        # Extra innings (10+) start with runner on 2nd (Ghost Runner Rule)
        if inning >= 10:
            on_2b = True

        # Check between-innings hook before the half-inning starts
        if self._should_hook_between_innings(current_pitcher, inning, team_score, opp_score, r):
            new_pitcher = self._call_reliever(
                inning=inning,
                team_score=team_score,
                opp_score=opp_score,
                lineup_idx=lineup_idx,
                used_names=used_names,
                pitchers_used=pitchers_used,
                outs=0,
                on_1b=False,
                on_2b=(inning >= 10),
                on_3b=False,
                r=r,
            )
            pitchers_used.append(new_pitcher)
            used_names.add(new_pitcher.name)
            current_pitcher = new_pitcher

        # Simulate batter by batter until 3 outs
        while outs < 3:
            batter_hand = self.lineup[lineup_idx]

            # Mid-inning hook check (must respect 3-batter minimum for relievers)
            if self._should_hook_mid_inning(
                current_pitcher, inning, team_score, opp_score, runs_in_half, outs, on_1b, on_2b, on_3b, r
            ):
                new_pitcher = self._call_reliever(
                    inning=inning,
                    team_score=team_score,
                    opp_score=opp_score + runs_in_half,  # include runs already in this half
                    lineup_idx=lineup_idx,
                    used_names=used_names,
                    pitchers_used=pitchers_used,
                    outs=outs,
                    on_1b=on_1b,
                    on_2b=on_2b,
                    on_3b=on_3b,
                    r=r,
                )
                pitchers_used.append(new_pitcher)
                used_names.add(new_pitcher.name)
                current_pitcher = new_pitcher

            # Simulate Plate Appearance
            pa_outs, pa_runs, on_1b, on_2b, on_3b, pitches_thrown = self._simulate_plate_appearance(
                current_pitcher.hand, batter_hand, outs, on_1b, on_2b, on_3b, r
            )

            current_pitcher.batters_faced += 1
            current_pitcher.pitches += pitches_thrown
            current_pitcher.outs_recorded += pa_outs
            current_pitcher.runs_allowed += pa_runs
            outs += pa_outs
            runs_in_half += pa_runs
            if team_score - (opp_score + runs_in_half) <= 0:
                current_pitcher.lead_lost = True

            lineup_idx = (lineup_idx + 1) % len(self.lineup)

        return runs_in_half, lineup_idx

    def _simulate_plate_appearance(
        self,
        p_hand: str,
        b_hand: str,
        outs: int,
        on_1b: bool,
        on_2b: bool,
        on_3b: bool,
        r: random.Random,
    ) -> tuple[int, int, bool, bool, bool, int]:
        """Simulate a single plate appearance with platoon splits and base-out updates."""
        # Platoon advantage: same hand favors pitcher, opposite hand favors batter.
        # Switch hitters ("S") bat from the opposite side, so they always have it.
        platoon_advantage_batter = (b_hand == "S") or (p_hand != b_hand)

        # Event probabilities [K, BB/HBP, 1B, 2B, HR] (config); the rest is an out in play
        rates = self.params.pa_rates_batter_edge if platoon_advantage_batter else self.params.pa_rates_pitcher_edge
        p_k, p_bb, p_1b, p_2b, p_hr = (float(x) for x in rates)

        u = r.random()
        runs = 0
        pa_outs = 0

        # Pitches in the PA: rounded normal (params pitches_per_pa, pitches_per_pa_sd), 1..12
        pitches = min(12, max(1, round(r.gauss(self.params.pitches_per_pa, self.params.pitches_per_pa_sd))))

        if u < p_k:
            # Strikeout
            pa_outs = 1
        elif u < p_k + p_bb:
            # Walk / Hit By Pitch
            if on_1b and on_2b and on_3b:
                runs += 1
            elif on_1b and on_2b:
                on_3b = True
            elif on_1b:
                on_2b = True
            on_1b = True
        elif u < p_k + p_bb + p_1b:
            # Single
            if on_3b:
                runs += 1
                on_3b = False
            if on_2b:
                if r.random() < 0.65:
                    runs += 1
                else:
                    on_3b = True
                on_2b = False
            if on_1b:
                if r.random() < 0.30:
                    on_3b = True
                else:
                    on_2b = True
            on_1b = True
        elif u < p_k + p_bb + p_1b + p_2b:
            # Double
            if on_3b:
                runs += 1
                on_3b = False
            if on_2b:
                runs += 1
                on_2b = False
            if on_1b:
                if r.random() < 0.45:
                    runs += 1
                else:
                    on_3b = True
                on_1b = False
            on_2b = True
        elif u < p_k + p_bb + p_1b + p_2b + p_hr:
            # Home run
            runs = 1 + int(on_1b) + int(on_2b) + int(on_3b)
            on_1b = False
            on_2b = False
            on_3b = False
        else:
            # Out in play (Groundout, flyout, lineout, double play)
            if on_1b and outs < 2 and r.random() < 0.12:
                # Ground into Double Play (GIDP)
                pa_outs = 2
                on_1b = False
                if on_3b and outs == 0:
                    runs += 1
                    on_3b = False
            else:
                pa_outs = 1
                # Sacrifice fly / productive out
                if on_3b and outs < 2 and r.random() < 0.35:
                    runs += 1
                    on_3b = False
                elif on_2b and outs < 2 and r.random() < 0.25:
                    on_3b = True
                    on_2b = False

        return pa_outs, runs, on_1b, on_2b, on_3b, pitches

    def _should_hook_between_innings(
        self,
        pitcher: PitchingAppearance,
        inning: int,
        team_score: int,
        opp_score: int,
        r: random.Random,
    ) -> bool:
        """Decide if pitcher is replaced between innings."""
        p = self.params
        if pitcher.is_starter:
            # Starter: check pitch count, times through the order and inning
            pitch_ratio = pitcher.pitches / max(1, self.starter_stamina)
            if pitch_ratio >= p.hook_force_ratio:
                return True
            if pitch_ratio >= p.hook_soft_ratio and r.random() < p.hook_soft_prob:
                return True
            if pitcher.batters_faced >= p.tto_batters and r.random() < p.tto_hook_prob:
                # 3rd time through order (TTO) hook
                return True
            if inning >= p.late_hook_inning and r.random() < p.late_hook_prob:
                return True
            return False

        # Relievers:
        if pitcher.role == "long":
            # Long relievers pitch multiple innings unless high pitch count
            if pitcher.outs_recorded >= p.long_max_outs or pitcher.pitches >= p.long_max_pitches:
                return True
            return r.random() < p.long_hook_prob

        # Closer, setup, middle: usually one inning; sometimes (reliever_extend_prob) a
        # second one, never more than 2 x reliever_max_outs.
        if pitcher.pitches >= p.reliever_max_pitches:
            return True
        if pitcher.outs_recorded >= p.reliever_max_outs:
            if pitcher.outs_recorded < 2 * p.reliever_max_outs and r.random() < p.reliever_extend_prob:
                return False
            return True
        return False

    def _should_hook_mid_inning(
        self,
        pitcher: PitchingAppearance,
        inning: int,
        team_score: int,
        opp_score: int,
        runs_in_half: int,
        outs: int,
        on_1b: bool,
        on_2b: bool,
        on_3b: bool,
        r: random.Random,
    ) -> bool:
        """Decide if pitcher is hooked mid-inning (with runners on base or jam)."""
        p = self.params
        if not pitcher.is_starter:
            # MLB 3-Batter Minimum Rule:
            # Reliever CANNOT be pulled mid-inning unless they have faced at least 3 batters!
            if pitcher.batters_faced < 3:
                return False

            # After 3 batters: hook if struggling or high pitch count
            if pitcher.pitches >= p.reliever_mid_max_pitches or runs_in_half >= p.reliever_mid_max_runs:
                return True
            if (
                (on_1b or on_2b or on_3b)
                and pitcher.pitches >= p.reliever_traffic_pitches
                and r.random() < p.reliever_traffic_hook_prob
            ):
                return True
            return False

        # Starter mid-inning hook:
        # Extreme pitch count
        if pitcher.pitches >= self.starter_stamina + p.starter_max_over:
            return True

        # Jam situation (runner in scoring position or 2+ runs in) with high pitch count
        is_jam = (on_2b or on_3b) or (runs_in_half >= 2)
        pitch_ratio = pitcher.pitches / max(1, self.starter_stamina)

        if pitch_ratio >= p.jam_hook_ratio and is_jam:
            # 3rd time through order jam is the primary trigger for modern quick hooks
            if pitcher.batters_faced >= p.jam_tto_batters:
                return r.random() < p.jam_hook_prob_tto
            return r.random() < p.jam_hook_prob

        if runs_in_half >= p.blowup_runs:
            # Early blowup
            return True

        return False

    def _call_reliever(
        self,
        *,
        inning: int,
        team_score: int,
        opp_score: int,
        lineup_idx: int,
        used_names: set[str],
        pitchers_used: list[PitchingAppearance],
        outs: int = 0,
        on_1b: bool = False,
        on_2b: bool = False,
        on_3b: bool = False,
        r: random.Random,
    ) -> PitchingAppearance:
        """Classify the game situation, score every available reliever and pick one
        with a softmax (see `candidate_score`)."""
        score_diff = team_score - opp_score
        li = compute_leverage_index(inning, score_diff, outs, on_1b, on_2b, on_3b)
        situation = classify_situation(inning, score_diff, li, self.params)

        # Candidates: available relievers who have not pitched yet; then emergency arms
        # (tired but on the active roster); arms off the active roster never pitch.
        candidates = [
            rel for rel in self.ledger.relievers.values()
            if rel.name not in used_names and self._avail_cache.get(rel.name, True)
        ]
        if not candidates:
            candidates = [rel for rel in self.ledger.relievers.values()
                          if rel.name not in used_names and rel.active]
        if not candidates:
            candidates = [rel for rel in self.ledger.relievers.values() if rel.active] or list(
                self.ledger.relievers.values())

        upcoming = [self.lineup[(lineup_idx + i) % len(self.lineup)] for i in range(3)]
        scores = [
            self._static_score[rel.name]
            + situation_bonus(self.params, situation, rel.role)
            + self.params.platoon_bonus * platoon_match(rel.hand, upcoming, self.params)
            for rel in candidates
        ]

        temperature = self.params.temperature
        max_s = max(scores)
        weights = [math.exp((s - max_s) / temperature) for s in scores]
        chosen_rel = r.choices(candidates, weights=weights, k=1)[0]

        return PitchingAppearance(
            name=chosen_rel.name,
            is_starter=False,
            role=chosen_rel.role,
            hand=chosen_rel.hand,
            order_entered=len(pitchers_used),
            entry_lead=score_diff,
            entry_runners=int(on_1b) + int(on_2b) + int(on_3b),
            lead_lost=score_diff <= 0,
        )


class MonteCarloSimulator:
    """Runs N simulations and aggregates probabilities for each reliever."""

    def __init__(self, simulator: GameSimulator):
        self.simulator = simulator

    def run(self, num_simulations: int = 500, seed: int = 42) -> dict[str, RelieverStats]:
        """Execute Monte Carlo simulation and aggregate statistics."""
        rng = random.Random(seed)
        stats: dict[str, RelieverStats] = {
            rel.name: RelieverStats(name=rel.name, role=rel.role, hand=rel.hand)
            for rel in self.simulator.ledger.relievers.values()
        }

        for _ in range(num_simulations):
            result = self.simulator.simulate_game(rng)

            # Check relievers used
            relievers_in_game = [p for p in result.pitchers_used if not p.is_starter]
            appeared_in_sim: set[str] = set()
            for idx, p in enumerate(relievers_in_game):
                if p.name in stats:
                    s = stats[p.name]
                    if p.name not in appeared_in_sim:
                        s.appearances += 1
                        appeared_in_sim.add(p.name)
                        if result.lead_after_7:
                            s.appear_when_leading_7 += 1
                        else:
                            s.appear_when_trailing_7 += 1
                    if idx == 0:
                        s.first_in_count += 1
                    if p.earned_save:
                        s.saves += 1
                    s.total_outs += p.outs_recorded
                    s.total_pitches += p.pitches
                    s.outs_list.append(p.outs_recorded)
                    s.pitches_list.append(p.pitches)

        return stats
