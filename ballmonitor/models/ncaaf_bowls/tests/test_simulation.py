import random
import pytest
from ballmonitor.models.ncaaf_bowls.config import SimConfig
from ballmonitor.models.ncaaf_bowls.domain import Game, Team
from ballmonitor.models.ncaaf_bowls.simulator import SeasonSimulator, win_probability

def test_win_probability():
    # Equal ratings, neutral site -> 50%
    p_neutral = win_probability(10.0, 10.0, home_field_points=2.5, margin_sd=14.0, is_neutral=True)
    assert pytest.approx(p_neutral, 0.001) == 0.50

    # Equal ratings, home site -> >50%
    p_home = win_probability(10.0, 10.0, home_field_points=2.5, margin_sd=14.0, is_neutral=False)
    assert p_home > 0.50
    assert pytest.approx(p_home, 0.01) == 0.57

    # Large favorite
    p_heavy = win_probability(25.0, 0.0, home_field_points=2.5, margin_sd=14.0, is_neutral=False)
    assert p_heavy > 0.95

def test_season_simulation():
    teams = [
        Team("t1", "Team 1", "SEC", 20.0, 990, 8, "City1", "ST", 30.0, -85.0, 6, 1, 3, 1),
        Team("t2", "Team 2", "SEC", 18.0, 980, 8, "City2", "ST", 31.0, -86.0, 5, 2, 3, 1),
        Team("t3", "Team 3", "Big Ten", 22.0, 985, 9, "City3", "ST", 40.0, -83.0, 7, 0, 4, 0),
        Team("t4", "Team 4", "Big Ten", 16.0, 980, 7, "City4", "ST", 41.0, -84.0, 5, 2, 3, 1),
    ]
    schedule = [
        Game("t1", "t2", neutral=False, conf=True),
        Game("t3", "t4", neutral=False, conf=True),
    ]
    config = SimConfig(simulations=10, random_seed=123)
    sim = SeasonSimulator(teams, schedule, config)
    rng = random.Random(123)
    states = sim.simulate_season(rng)

    assert len(states) == 4
    for s in states.values():
        assert s.wins + s.losses > 0
        assert s.resume_score != 0.0

    # Conference champions should be crowned
    sec_champs = [s for s in states.values() if s.conf == "SEC" and s.is_conf_champ]
    b10_champs = [s for s in states.values() if s.conf == "Big Ten" and s.is_conf_champ]
    assert len(sec_champs) == 1
    assert len(b10_champs) == 1
