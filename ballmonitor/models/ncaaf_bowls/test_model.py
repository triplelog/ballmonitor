"""Model-level tests for ncaaf_bowls (the ballmonitor predict() contract)."""

import random

import pytest

from ballmonitor.core import registry
from ballmonitor.models.ncaaf_bowls.config import SimConfig
from ballmonitor.models.ncaaf_bowls.domain import Game, Team
from ballmonitor.models.ncaaf_bowls.simulator import SeasonSimulator


def _model(**overrides):
    return registry.load_model("ncaaf_bowls", overrides={"simulations": 60, **overrides})


def test_win_probability_formula_hand_check():
    p = _model().params
    # +7 at home with HFA 2.5 and SD 14: Phi(9.5 / 14) = Phi(0.6786) = 0.7513
    assert p.formula("win_probability", rating_diff=7.0, home=1) == pytest.approx(0.7513, abs=1e-3)
    assert p.formula("win_probability", rating_diff=0.0, home=0) == pytest.approx(0.5)


def test_probabilities_valid_and_ordered():
    pred = _model().predict({"team": "Ohio State"})
    for o in pred.outcomes:
        if o.probability is not None:
            assert 0.0 <= o.probability <= 1.0
    e = pred.extras
    # Winning the title requires making the CFP; a bye requires making the CFP
    # (2026 straight seeding: byes go to the top 4 ranked teams, champions or not).
    assert e["national_champ_prob"] <= e["p_cfp"]
    assert e["p_cfp_bye"] <= e["p_cfp"]


def test_unknown_team_raises():
    with pytest.raises(ValueError, match="unknown team"):
        _model().predict({"team": "Hogwarts"})


def test_team_lookup_by_id_and_case():
    assert _model().predict({"team": "ohio_state"}).extras["team"] == "Ohio State"
    assert _model().predict({"team": "BOISE STATE"}).extras["team"] == "Boise State"


def test_full_season_is_simulated():
    # Real schedule: every team plays 12 regular-season games (13 with a Hawaii trip),
    # plus a conference title game when it qualifies.
    pred = _model().predict({"team": "Auburn"})
    w, l = (float(x) for x in pred.extras["projected_record"].split("-"))
    assert 11.99 <= w + l <= 13.01


def test_schedule_data_is_complete_and_consistent():
    import json
    from ballmonitor.models.ncaaf_bowls.config import DATA_DIR
    teams = {t["id"]: t for t in json.loads((DATA_DIR / "teams.json").read_text())}
    games = json.loads((DATA_DIR / "schedule.json").read_text()) + json.loads((DATA_DIR / "results.json").read_text())
    count = {t: 0 for t in teams}
    seen = set()
    for g in games:
        assert g["espn_id"] not in seen, "duplicate game"
        seen.add(g["espn_id"])
        for side in ("home", "away"):
            assert g[side] in teams or g[side].startswith("fcs_"), g
            if g[side] in teams:
                count[g[side]] += 1
    assert all(12 <= n <= 13 for n in count.values()), {t: n for t, n in count.items() if not 12 <= n <= 13}
    # Records in teams.json are exactly the completed results
    for t in teams.values():
        played = [g for g in json.loads((DATA_DIR / "results.json").read_text()) if t["id"] in (g["home"], g["away"])]
        assert t["wins"] + t["losses"] == len(played)


def test_formula_override_moves_result():
    # A flatter win-probability curve (bigger SD) should hurt a heavy favourite.
    base = _model().predict({"team": "Oregon"}).extras["projected_record"]
    flat = _model(margin_sd=25.0).predict({"team": "Oregon"}).extras["projected_record"]
    assert float(flat.split("-")[0]) < float(base.split("-")[0])


def test_simulation_is_reproducible():
    a = _model().predict({"team": "Georgia"}).extras
    b = _model().predict({"team": "Georgia"}).extras
    assert a == b


def test_fcs_games_count_and_respect_scenarios():
    teams = [Team("a", "A", "SEC", 10.0, 990, 8, "X", "ST", 30.0, -85.0, 4, 4, 2, 2)]
    sched = [Game(home="a", away="fcs_x", conf=False)] * 3
    sim = SeasonSimulator(teams, sched, SimConfig())
    s = sim.simulate_season(random.Random(1))["a"]
    assert s.wins + s.losses == 11
    from ballmonitor.models.ncaaf_bowls.scenarios import Scenario
    s = sim.simulate_season(random.Random(1), scenario=Scenario(loses_out={"a"}))["a"]
    assert (s.wins, s.losses) == (4, 7)

