import math

import pytest

from ballmonitor.core import registry
from ballmonitor.models.lichess_rating.dist import (
    LEVELS, active_cdf, active_quantile, features, mixture_exceed, mixture_quantile,
)

BASE = {
    "speed": "blitz", "rating": 1650, "horizon_days": 182, "games_total": 900,
    "games_last_28_days": 60, "games_last_91_days": 170, "days_since_last_game": 1,
    "peak_rating": 1720, "rating_91_days_ago": 1610, "score_last_91_days": 90,
    "opponents_avg_last_91_days": 1640,
}
CAPS = {"games": 5000.0, "below_peak": 4.0, "trend": 3.0, "form": 4.0}


def run(inputs, variant=None, **overrides):
    return registry.load_model("lichess_rating", variant, overrides).predict(inputs)


# ---- distribution helpers (hand-checked values)

def test_mixture_quantile_point_mass_at_zero():
    qs = [-100, -50, -20, 0, 20, 50, 100]
    # p = 0.5: half the mass at 0, so the median is 0 and the 10% quantile is the
    # active distribution's 20% point (between -50 at 10% and -20 at 25%: -30).
    assert mixture_quantile(0.5, qs, 0.5) == 0.0
    assert mixture_quantile(0.5, qs, 0.1) == pytest.approx(-50 + 30 * (0.2 - 0.1) / 0.15)
    assert mixture_quantile(0.0, qs, 0.9) == 0.0  # never plays: rating can't move


def test_cdf_and_quantile_are_inverses_including_tails():
    qs = [-150, -80, -30, 5, 40, 90, 160]
    for level in (0.001, 0.02, 0.1, 0.33, 0.5, 0.8, 0.99, 0.999):
        assert active_cdf(qs, active_quantile(qs, level)) == pytest.approx(level, abs=1e-9)
    assert active_cdf(qs, 160) == pytest.approx(0.975)
    # exponential tail through the 90% and 97.5% quantiles: P(X > 230) = 0.025 * exp(-70 / s)
    s = 70 / math.log(0.1 / 0.025)
    assert 1 - active_cdf(qs, 230) == pytest.approx(0.025 * math.exp(-70 / s))


def test_exceed_scales_with_chance_of_playing():
    qs = [-150, -80, -30, 5, 40, 90, 160]
    assert mixture_exceed(0.5, qs, 40) == pytest.approx(0.5 * 0.25)
    with pytest.raises(ValueError):
        mixture_exceed(0.5, qs, -1)


def test_features_hand_values():
    x = features(rating=1650, games_total=900, games_28=60, days_since_last=1, peak=1720,
                 rating_91_ago=1610, score_91=90, games_91=170, opp_mean_91=1640, horizon=91, caps=CAPS)
    assert x["activity"] == pytest.approx(math.log(61))
    assert x["below_peak"] == pytest.approx(0.7)
    assert x["trend"] == pytest.approx(0.4)
    assert x["level"] == pytest.approx(1.5)
    perf = 1640 + 400 * (2 * 90 / 170 - 1)
    assert x["form"] == pytest.approx((perf - 1650) / 100)
    assert x["log_horizon"] == pytest.approx(0.0)


def test_research_features_match_model_features():
    pd = pytest.importorskip("pandas")
    from ballmonitor.models.lichess_rating.research import feature_frame
    row = {"rating": 1650, "games_total": 900, "games_28": 60, "days_since_last": 1, "peak": 1720,
           "rating_91_ago": 1610, "score_91": 90.0, "games_91": 170, "opp_mean_91": 1640.0, "horizon": 182}
    f = feature_frame(pd.DataFrame([row]), CAPS).iloc[0]
    x = features(rating=1650, games_total=900, games_28=60, days_since_last=1, peak=1720, rating_91_ago=1610,
                 score_91=90, games_91=170, opp_mean_91=1640, horizon=182, caps=CAPS)
    for k, v in x.items():
        assert f[k] == pytest.approx(v), k


# ---- the model

def test_output_shape_and_order():
    pred = run(BASE)
    lo, hi = pred.primary.interval
    assert lo < pred.primary.estimate < hi
    pct = [o.estimate for o in pred.outcomes if o.group == "Range"]
    assert pct == sorted(pct)
    probs = {o.label: o.probability for o in pred.outcomes if o.probability is not None}
    assert 0 < probs["Reaches 1700"] < probs["Higher than today"] <= probs["Plays again in this speed"]


def test_not_playing_means_no_change():
    # Long idle, no recent games: chance of playing is lower and the range narrower.
    idle = dict(BASE, games_last_28_days=0, games_last_91_days=0, days_since_last_game=300,
                score_last_91_days=0)
    a, b = run(BASE), run(idle)
    assert b.extras["p_active"] < a.extras["p_active"]
    width = lambda p: p.primary.interval[1] - p.primary.interval[0]
    assert width(b) < width(a)


def test_keep_playing_sets_p_to_one():
    pred = run(dict(BASE, keep_playing=True))
    assert pred.extras["p_active"] == 1.0


def test_longer_horizon_wider_band():
    width = lambda p: p.primary.interval[1] - p.primary.interval[0]
    assert width(run(dict(BASE, horizon_days=365))) > width(run(dict(BASE, horizon_days=30)))


def test_band_scale_widens_and_variant_loads():
    width = lambda p: p.primary.interval[1] - p.primary.interval[0]
    assert width(run(BASE, band_scale=2.0)) > width(run(BASE))
    assert width(run(BASE, "wide_bands")) > width(run(BASE))


def test_below_peak_and_good_form_raise_the_median():
    base = run(dict(BASE, keep_playing=True)).extras["quantiles"][0.5]
    dipped = run(dict(BASE, keep_playing=True, peak_rating=1950)).extras["quantiles"][0.5]
    hot = run(dict(BASE, keep_playing=True, score_last_91_days=130)).extras["quantiles"][0.5]
    assert dipped > base and hot > base


def test_target_date_and_goal():
    pred = run(dict({k: v for k, v in BASE.items() if k != "horizon_days"},
                    as_of="2026-11-18", target_date="2027-11-18", goal_rating=1600))
    assert pred.extras["horizon"] == 365
    goal = next(o for o in pred.outcomes if o.label.startswith("At or above goal"))
    higher = next(o for o in pred.outcomes if o.label == "Higher than today")
    assert goal.probability > higher.probability  # a goal below today's rating is easier


@pytest.mark.parametrize("bad", [
    {"rating": "abc"}, {"rating": 100}, {"speed": "bughouse"}, {"horizon_days": 0},
    {"games_last_91_days": 10}, {"score_last_91_days": 500},
])
def test_bad_inputs_raise(bad):
    with pytest.raises(ValueError):
        run(dict(BASE, **bad))
