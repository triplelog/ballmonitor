import pytest

from ballmonitor.core import registry
from ballmonitor.models.open_war import engine as E

pytestmark = pytest.mark.skipif(not (E.LAHMAN / "People.csv").exists(),
                                reason="needs the Lahman CSVs (Triple Play's local raw folder)")


def run(player="ruthba01", **overrides):
    return registry.load_model("open_war", None, overrides).predict({"player": player})


def test_ruth_is_an_inner_circle_player():
    pred = run()
    assert 120 < pred.extras["career"] < 190            # Baseball-Reference: 182.6 (with pitching batting)
    assert pred.outcome("Pitching").estimate > 10       # his Red Sox pitching years count


def test_known_seasons_rank_high():
    assert run("bondsba01").extras["seasons"][2001] > 9   # Baseball-Reference 11.9
    assert run("gibsobo01").extras["seasons"][1968] > 9   # 11.2


def test_replacement_level_moves_war_up():
    base = run("jeterde01").extras["career"]
    lower_bar = run("jeterde01", batting_replacement_runs=25.0).extras["career"]
    assert lower_bar > base


def test_position_adjustment_matters_for_a_catcher():
    base = run("benchjo01").extras["career"]
    no_catcher_bonus = run("benchjo01", pos_c=0.0).extras["career"]
    assert no_catcher_bonus < base - 5


def test_linear_weights_formula_is_used():
    base = run("aaronha01").extras["career"]
    cheap_homers = run("aaronha01", **{"formulas.linear_weights": "w_single * singles + w_double * doubles + w_triple * triples + 0.5 * HR + w_bb * (BB + HBP)"}).extras["career"]
    assert cheap_homers < base - 20
