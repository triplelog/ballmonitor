"""Model-level tests for ncaaf_recruiting (the ballmonitor predict() contract)."""

import math

import pytest

from ballmonitor.core import registry


def _model(**overrides):
    return registry.load_model("ncaaf_recruiting", overrides=overrides or None)


def test_class_score_is_sum_of_recruit_points():
    # With recruit_points = rating (no decay) the class score is the plain sum of
    # recruit scores, i.e. commits * average recruit score.
    pred = _model(**{"formulas.recruit_points": "rating"}).predict({"year": 2024, "team": "Georgia"})
    e = pred.extras
    assert e["score"] == pytest.approx(e["commits"] * e["avg_score"], abs=0.2)


def test_decay_lowers_class_score():
    base = _model().predict({"year": 2024, "team": "Georgia"}).extras["score"]
    steep = _model(rank_decay=0.8).predict({"year": 2024, "team": "Georgia"}).extras["score"]
    flat = _model(rank_decay=1.0).predict({"year": 2024, "team": "Georgia"}).extras["score"]
    assert steep < base < flat


def test_basketball_uses_basketball_params():
    m = _model(bball_quality_power=0.4)
    a = m.predict({"sport": "mbb", "year": 2025, "team": "Duke"}).extras["score"]
    b = _model().predict({"sport": "mbb", "year": 2025, "team": "Duke"}).extras["score"]
    assert a != b
    # Football params must not leak into basketball runs.
    c = _model(quality_power=0.9).predict({"sport": "mbb", "year": 2025, "team": "Duke"}).extras["score"]
    assert c == b


@pytest.mark.parametrize(
    "inputs, match",
    [
        ({"team": "Hogwarts"}, "no committed recruits"),
        ({"sport": "nhl"}, "unknown sport"),
        ({"year": "abc"}, "integer"),
        ({"year": 2011}, "no NCAAF Football recruit data"),
        ({"method": "magic"}, "unknown method"),
        ({"sport": "wbb", "year": 2024, "team": "UCLA"}, "competing offers"),
    ],
)
def test_bad_inputs_raise_value_error(inputs, match):
    with pytest.raises(ValueError, match=match):
        _model().predict(inputs)


def test_sequential_elo_runs_without_positional_breakdown():
    pred = _model().predict({"year": 2024, "team": "Georgia", "method": "sequential_elo"})
    assert pred.extras["unit_breakdown"] is None
    assert pred.extras["rank"] >= 1


def test_projection_matches_formula_and_falls_with_rank():
    m = _model()
    pred = m.predict({"year": 2024, "team": "Georgia"})
    e = pred.extras
    import math
    p = m.params
    expected = float(p.proj_intercept) + float(p.proj_slope) * math.log(e["rank"])
    assert e["projection"]["estimate"] == pytest.approx(expected, abs=0.06)
    lo, hi = e["projection"]["interval"]
    assert lo < e["projection"]["estimate"] < hi
    assert pred.interval_level == pytest.approx(0.8)
    # a lower-ranked class projects a weaker team
    weak = m.predict({"year": 2024, "team": "Kansas"}).extras
    assert weak["rank"] > e["rank"]
    assert weak["projection"]["estimate"] < e["projection"]["estimate"]


def test_wider_projection_sd_widens_range():
    a = _model().predict({"year": 2024, "team": "Georgia"}).extras["projection"]["interval"]
    b = _model(projection_sd=10.0).predict({"year": 2024, "team": "Georgia"}).extras["projection"]["interval"]
    assert (b[1] - b[0]) > (a[1] - a[0])


def test_basketball_has_no_projection():
    e = _model().predict({"sport": "mbb", "year": 2025, "team": "Duke"}).extras
    assert e["projection"] is None


def test_backtest_case_and_score():
    m = _model()
    inputs, actual = m.backtest_case({"year": "2021", "team": "Georgia", "future_srs": "20.5"})
    assert inputs == {"sport": "ncaaf", "year": 2021, "team": "Georgia"}
    scores = m.score(m.predict(inputs), actual)
    assert set(scores) == {"abs_error", "bias", "in_interval"}
    assert scores["abs_error"] == pytest.approx(abs(scores["bias"]))


def test_prestige_years_pools_previous_class():
    one = _model().predict({"year": 2024, "team": "Georgia"})
    two = _model(prestige_years=2).predict({"year": 2024, "team": "Georgia"})
    assert one.extras["commits"] == two.extras["commits"]  # only this class is scored
    assert one.extras["elo"] != two.extras["elo"]
    assert "earlier class" in " ".join(two.steps)


def test_in_progress_class_is_flagged():
    pred = _model().predict({"year": 2027, "team": "Texas A&M"})
    assert pred.extras["class_status"] == "in_progress"
    assert "in progress" in pred.steps[0]


def test_mbb_history_class_runs_without_pro_destinations():
    e = _model().predict({"sport": "mbb", "year": 2021, "team": "Duke"}).extras
    assert e["sport_label"] == "Men's Basketball" and e["year"] == 2021
    names = [r["team"] for r in e["rankings"]]
    assert "NBA G League" not in names and "Professional" not in names
    old = _model().predict({"sport": "mbb", "year": 2014, "team": "Duke"}).extras
    assert old["commits"] >= 1 and old["projection"] is None


def test_engine_seed_prior_and_commit_weight():
    from src.elo_engine import EloEngine
    from src.models import Recruit
    # One recruit, one school listed: the original score is 0; a committed-school term
    # gives him credit, and a seed is the strength programs start from.
    r = Recruit(url="u", year=2019, name="A", position="G", hometown="", stars=5,
                committed_team="Duke", offers=[])
    base = EloEngine(l2_reg=1.0).run(2019, [r])
    assert base.recruits[0].score == 0.0
    seeded = EloEngine(l2_reg=1.0, prior_gamma={"Duke": 2.0}, commit_weight=1.0).run(2019, [r])
    # no offer battles, so Duke's strength is its seed (2.0): score = (1 * e^2) ** 0.5 = e
    assert seeded.recruits[0].score == pytest.approx(math.e, rel=1e-6)
    assert seeded.teams[0].elo > base.teams[0].elo  # seed raised Duke's strength


def test_mbb_seed_reorders_toward_strong_programs():
    inputs = {"sport": "mbb", "year": 2019, "team": "Duke"}
    off = _model().predict(inputs).extras["rankings"]
    on = _model(bball_seed_beta=1.0, bball_l2_reg=5.0, bball_commit_weight=3.0,
                bball_aggregate="max").predict(inputs).extras["rankings"]
    blue = {"Duke", "North Carolina", "Kentucky", "Villanova", "Kansas", "Gonzaga"}
    top = lambda rk: sum(1 for t in rk[:5] if t["team"] in blue)  # noqa: E731
    assert top(on) > top(off)


def test_site_page_is_valid_and_ranks_programs():
    from ballmonitor.core import views
    from ballmonitor.models.ncaaf_recruiting import site

    model = _model()
    p = views.clean(site.page(model))
    assert views.check(p) == []
    options = p["views"][0]["options"]
    assert options[0]["label"].startswith("2027")  # newest class first
    rows = options[1]["views"][0]["rows"]  # 2026, every program with a commit
    assert len(rows) > 130 and all(r["commits"] > 0 for r in rows)
    assert [r["rank"] for r in rows] == sorted(r["rank"] for r in rows)
    top = model.predict({"sport": "ncaaf", "year": 2026, "team": rows[0]["team"]})
    assert top.extras["rank"] == 1 and top.extras["score"] == rows[0]["score"]
