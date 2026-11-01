"""Tests for Batter vs. Pitcher Similarity Matchup model."""

import math

import pandas as pd
import pytest

from ballmonitor.core import registry
from ballmonitor.core.stats import z_for_level
from ballmonitor.models.bvp_similarity import features as F


def run(inputs, variant=None, **overrides):
    return registry.load_model("bvp_similarity", variant, overrides).predict(inputs)


def test_default_prediction():
    pred = run({"pitcher": "Tarik Skubal", "batter": "Aaron Judge"})
    assert pred.primary.label == "Expected xwOBA"
    assert 0.200 <= pred.primary.estimate <= 0.550
    assert pred.primary.interval is not None
    lo, hi = pred.primary.interval
    assert lo < pred.primary.estimate < hi
    assert len(pred.steps) >= 5

    # Check secondary outcomes
    outcomes = {o.label: o for o in pred.outcomes}
    assert "Strikeout probability" in outcomes
    assert "Walk probability" in outcomes
    assert 0.05 <= outcomes["Strikeout probability"].probability <= 0.60
    assert 0.01 <= outcomes["Walk probability"].probability <= 0.35


def test_same_handedness_prediction():
    pred = run({"pitcher": "Dylan Cease", "batter": "Aaron Judge"})
    assert pred.inputs["pitcher_hand"] == "R"
    assert pred.inputs["batter_bats"] == "R"
    assert 0.200 <= pred.primary.estimate <= 0.550


def test_player_id_input():
    # ID for Skubal is 669373, Judge is 592450
    pred = run({"pitcher": 669373, "batter": 592450})
    assert "Tarik Skubal" in pred.inputs["pitcher"]
    assert "Aaron Judge" in pred.inputs["batter"]


def test_shrinkage_weight_formula():
    model = registry.load_model("bvp_similarity")
    p = model.params
    w0 = float(p.formula("bvp_weight", n_direct=0))
    w10 = float(p.formula("bvp_weight", n_direct=10))
    w100 = float(p.formula("bvp_weight", n_direct=100))
    assert w0 == 0.0
    assert 0.0 < w10 < w100 < 1.0


def test_backtest_case_contract():
    model = registry.load_model("bvp_similarity")
    row = {"pitcher": "669373", "batter": "592450", "pa": "4", "observed_xwoba": "0.4120",
           "k": "1", "bb": "1"}
    inputs, actual = model.backtest_case(row)
    assert inputs == {"pitcher": "669373", "batter": "592450", "pa": 4}
    assert actual == {"pa": 4, "xwoba": pytest.approx(0.4120), "k": 1, "bb": 1}


def test_score_counts_strikeouts_and_walks_per_pa():
    model = registry.load_model("bvp_similarity")
    pred = model.predict({"pitcher": "Tarik Skubal", "batter": "Aaron Judge", "pa": 4})
    pk = pred.outcome("Strikeout probability").probability
    pbb = pred.outcome("Walk probability").probability
    s = model.score(pred, {"pa": 4, "xwoba": 0.3, "k": 2, "bb": 1})
    expected = -(2 * math.log(pk) + math.log(pbb) + math.log(1 - pk - pbb)) / 4
    assert s["log_loss"] == pytest.approx(expected)
    assert s["abs_error"] == pytest.approx(abs(pred.primary.estimate - 0.3))
    assert s["in_80"] in (0.0, 1.0)


def test_range_is_for_observed_pa_and_narrows_with_more_pa():
    one = run({"pitcher": "Tarik Skubal", "batter": "Aaron Judge", "pa": 1}).extras["interval_half_width"]
    many = run({"pitcher": "Tarik Skubal", "batter": "Aaron Judge", "pa": 25}).extras["interval_half_width"]
    assert one > many > 0
    model = registry.load_model("bvp_similarity")
    p = model.params
    z = z_for_level(p.interval_level)
    assert one == pytest.approx(z * math.sqrt(p.interval_talent_sd ** 2 + p.per_pa_xwoba_sd ** 2), abs=1e-4)


def test_regress_formula_hand_value():
    p = registry.load_model("bvp_similarity").params
    assert p.formula("regress", x=0.30, n=100, prior=0.20, n0=100) == pytest.approx(0.25)
    # a huge prior sample pulls the baseline to league average
    league = run({"pitcher": "Tarik Skubal", "batter": "Aaron Judge"},
                 regress_k_pa=5000.0).extras["base_k"]
    raw = run({"pitcher": "Tarik Skubal", "batter": "Aaron Judge"}, regress_k_pa=1.0).extras["base_k"]
    assert abs(league - p.league_k_pct) < abs(raw - p.league_k_pct)


def _row(**values):
    return pd.Series(values)


def test_microsim_takes_are_strikes_only_by_location():
    """Swing at every zone pitch, never chase, no whiffs or fouls, no out-of-zone called strikes:
    each pitch is a ball in play (zone, p = 0.5) or a ball, so P(BB) = 0.5 ** 4 by hand."""
    overrides = {"ms_foul_share": 0.0}
    for g in ("first", "even", "behind", "two"):
        overrides.update({f"ms_{g}_zone_swing": 1.0, f"ms_{g}_chase": 0.0, f"ms_{g}_whiff": 0.0,
                          f"ms_{g}_cs_out": 0.0})
    model = registry.load_model("bvp_similarity", None, overrides)
    p = model.params
    pitcher = _row(zone_pct=0.5, f_zone_pct=0.5, ahead_zone_pct=0.5, behind_zone_pct=0.5,
                   chase_pct=p.league_chase_pct, whiff_pct=p.league_whiff_pct)
    batter = _row(f_swing_pct=p.league_f_swing_pct, z_swing_pct=p.league_z_swing_pct,
                  chase_pct=p.league_chase_pct, whiff_pct=p.league_whiff_pct,
                  k_pct=p.league_k_pct, bb_pct=p.league_bb_pct, xwoba=p.league_xwoba)
    pk, pbb, pbip, _, _ = model.solve_count_microsim(pitcher, batter)
    assert pk == pytest.approx(0.0, abs=1e-12)
    assert pbb == pytest.approx(0.5 ** 4)
    assert pbip == pytest.approx(1 - 0.5 ** 4)


def test_microsim_all_called_strikes_is_a_strikeout():
    overrides = {}
    for g in ("first", "even", "behind", "two"):
        overrides.update({f"ms_{g}_zone_swing": 0.0, f"ms_{g}_chase": 0.0, f"ms_{g}_cs_zone": 1.0})
    model = registry.load_model("bvp_similarity", None, overrides)
    p = model.params
    pitcher = _row(zone_pct=1.0, f_zone_pct=1.0, ahead_zone_pct=1.0, behind_zone_pct=1.0,
                   chase_pct=p.league_chase_pct, whiff_pct=p.league_whiff_pct)
    batter = _row(f_swing_pct=p.league_f_swing_pct, z_swing_pct=p.league_z_swing_pct,
                  chase_pct=p.league_chase_pct, whiff_pct=p.league_whiff_pct,
                  k_pct=p.league_k_pct, bb_pct=p.league_bb_pct, xwoba=p.league_xwoba)
    pk, pbb, pbip, _, _ = model.solve_count_microsim(pitcher, batter)
    assert pk == pytest.approx(1.0)


def test_unknown_or_missing_players_raise_value_error():
    with pytest.raises(ValueError, match="no pitcher"):
        run({"pitcher": "Nobody Atall", "batter": "Aaron Judge"})
    with pytest.raises(ValueError, match="Aaron Judge"):  # close-match hint
        run({"pitcher": "Tarik Skubal", "batter": "Aaron Jdge"})
    with pytest.raises(ValueError, match="required"):
        run({"pitcher": "Tarik Skubal"})


def test_names_match_without_accents():
    assert run({"pitcher": "Jose Berrios", "batter": "Aaron Judge"}).inputs["pitcher"] == "José Berríos"


def test_rates_are_probabilities_and_peers_are_similarities():
    pred = run({"pitcher": "Tarik Skubal", "batter": "Aaron Judge"})
    e = pred.extras
    assert e["ms_k"] + e["ms_bb"] + e["ms_bip"] == pytest.approx(1.0, abs=2e-3)
    assert e["w_direct"] + e["w_arch"] + e["w_baseline"] == pytest.approx(1.0, abs=1e-3)
    peers = [o for o in pred.outcomes if o.group.startswith("Similar")]
    assert peers and all(o.probability is None and 0 < o.estimate <= 1 for o in peers)


def test_microsim_params_move_results():
    inputs = {"pitcher": "Tarik Skubal", "batter": "Aaron Judge"}
    base = run(inputs).extras
    more_whiff = run(inputs, ms_two_whiff=0.45).extras
    assert more_whiff["ms_k"] > base["ms_k"]
    offset = registry.load_model("bvp_similarity").params.ms_xwoba_offset
    no_offset = run(inputs, ms_xwoba_offset=0.0).extras
    assert no_offset["ms_xwoba"] == pytest.approx(base["ms_xwoba"] - offset, abs=1e-3)
    no_ms = run(inputs, microsim_weight=0.0)
    assert no_ms.extras["w_microsim"] == 0.0


def test_site_page_is_valid():
    from ballmonitor.core import views
    from ballmonitor.models.bvp_similarity import site

    model = registry.load_model("bvp_similarity", None, {"site_hitters": 5, "site_pitchers": 5})
    page = site.page(model)
    assert views.check(page) == []
    picker = page["views"][0]
    assert len(picker["options"]) == 5
    for row in picker["options"][0]["views"][0]["rows"]:
        assert 0 < row["k"] < 1 and 0 < row["bb"] < 1 and 40 < row["quality"] < 200
