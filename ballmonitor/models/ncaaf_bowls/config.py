"""
Configuration and tunable parameters for the College Football Bowl Simulator.
All key constants, weights, and model parameters are defined here.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

DATA_DIR = Path(__file__).parent / "data"

@dataclass
class SimConfig:
    # --- Season Simulation Parameters ---
    simulations: int = 2500
    random_seed: int | None = 42
    home_field_points: float = 2.5
    margin_sd: float = 14.0
    bowl_eligible_wins: int = 6
    # Rating of every FCS opponent (schedule.json ids starting with "fcs_").
    fcs_opponent_rating: float = -21.7
    # Optional P(team A wins) given (rating_diff = A - B, home = +1/0/-1).
    # When None the built-in normal-CDF margin model is used. model.py passes
    # the config.toml `win_probability` formula here so it drives every game.
    win_prob_fn: Callable[[float, int], float] | None = None

    # --- CFP Selection Committee Proxy Weights ---
    # Committee ranks teams based on resume: record, power rating, conf championship, SOS
    resume_win_pct_weight: float = 65.0      # Primary driver: 12-0 vs 11-1 vs 10-2
    resume_power_weight: float = 1.0         # Team strength (SP+/FPI margin)
    resume_conf_champ_bonus: float = 8.0     # Bonus for winning a conference championship
    resume_power4_bonus: float = 4.0         # Schedule strength advantage for P4 teams
    resume_loss_penalty_exponent: float = 1.5 # Progressive penalty for 3+ losses
    resume_loss_penalty_scale: float = 3.5   # Points per (losses ** exponent)
    resume_p4_champ_bonus: float = 3.0       # Extra bonus for a power-conference title

    # --- Bowl Utility & Selection Preferences ---
    # Bowls pick available teams to maximize game attractiveness
    bowl_win_weight: float = 3.5             # Bowls strongly prefer more wins (e.g. 9-3 over 7-5)
    bowl_rating_weight: float = 0.4          # Team quality/competitiveness
    bowl_brand_weight: float = 1.4           # TV ratings & ticket sales appeal (calibrated to +1.6 win premium)
    bowl_geo_weight: float = 1.8             # Proximity to bowl site (fan travel)
    bowl_max_distance_miles: float = 2500.0  # Normalization distance
    bowl_drive_in_radius_miles: float = 400.0# Empirical drive-in window (<400 mi, 29.7% overall)
    bowl_drive_in_bonus: float = 3.5         # Additional utility boost for drive-in proximity
    bowl_regional_proximity_mult: float = 1.6# Proximity boost multiplier for regional drive-in bowls
    bowl_repeat_penalty: float = 14.0        # Calibrated to 85.2% empirical repeat suppression
    bowl_rematch_penalty: float = 25.0       # Strongly avoid regular season rematch in non-CFP bowls
    bowl_temperature: float = 0.35           # Softmax temperature (0 = strictly deterministic, higher = stochastic)

    # --- Big Ten Specific Rules ---
    # A Big Ten bowl cannot bypass a team with 2+ more conference wins
    big_ten_max_conf_win_skip: int = 1

    # --- Notre Dame ACC Clause ---
    # Notre Dame can take an ACC bowl slot if within 1 win of the best available ACC team
    notre_dame_acc_win_tolerance: int = 1

DEFAULT_CONFIG = SimConfig()
