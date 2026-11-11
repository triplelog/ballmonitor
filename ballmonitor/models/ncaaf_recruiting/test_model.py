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
    # Georgia's 2023 SRS in data/outcomes/fbs_team_srs.csv (the season before the class)
    assert e["projection"]["prior_seasons"] == [2023]
    expected = (float(p.proj_intercept) + float(p.proj_slope) * math.log(e["rank"])
                + float(p.proj_prior_weight) * e["projection"]["prior_srs"])
    assert e["projection"]["estimate"] == pytest.approx(expected, abs=0.06)
    lo, hi = e["projection"]["interval"]
    assert lo < e["projection"]["estimate"] < hi
    assert pred.interval_level == pytest.approx(0.8)
    # a lower-ranked class projects a weaker team
    weak = m.predict({"year": 2024, "team": "Kansas"}).extras
    assert weak["rank"] > e["rank"]
    assert weak["projection"]["estimate"] < e["projection"]["estimate"]


def test_prior_strength_moves_projection():
    inputs = {"year": 2024, "team": "Georgia"}  # a strong program: prior SRS well above 0
    base = _model().predict(inputs).extras["projection"]
    assert base["prior_srs"] > 10
    more = _model(proj_prior_weight=0.6).predict(inputs).extras["projection"]
    none = _model(proj_prior_weight=0.0).predict(inputs).extras["projection"]
    assert none["estimate"] < base["estimate"] < more["estimate"]
    # hand calculation: rank 1 -> ln(1) = 0, so the estimate is intercept + weight * prior
    p = _model().params
    assert base["estimate"] == pytest.approx(
        float(p.proj_intercept) + float(p.proj_prior_weight) * base["prior_srs"], abs=0.06)
    # a longer window averages more seasons
    three = _model(proj_prior_seasons=3).predict(inputs).extras["projection"]
    assert three["prior_seasons"] == [2021, 2022, 2023]


def test_prior_strength_edge_cases():
    m = _model()
    # no season before 2012 in the data: no projection, and the steps say why
    old = m.predict({"year": 2012, "team": "Alabama"})
    assert old.extras["projection"] is None and "No projected SRS" in " ".join(old.steps)
    # ... but the rank-only variant still projects
    rank_only = registry.load_model("ncaaf_recruiting", variant="class_rank_only")
    e = rank_only.predict({"year": 2012, "team": "Alabama"}).extras
    assert e["projection"]["estimate"] == pytest.approx(25.62 - 6.56 * math.log(e["rank"]), abs=0.06)
    # a class newer than the game data uses the latest season there is
    new = m.predict({"year": 2027, "team": "Texas A&M"})
    assert new.extras["projection"]["prior_seasons"] == [2025]
    assert "not in it yet" in " ".join(new.steps)
    # a program with no FBS season before the class gets proj_prior_default
    jmu = m.predict({"year": 2022, "team": "James Madison"}).extras["projection"]
    assert jmu["prior_seasons"] == [] and jmu["prior_srs"] == pytest.approx(float(m.params.proj_prior_default))


def test_roster_classes_average_the_class_ranks():
    one = _model().predict({"year": 2024, "team": "Kansas"}).extras
    four = _model(proj_roster_classes=4).predict({"year": 2024, "team": "Kansas"}).extras
    assert one["projection"]["rank"] == one["rank"] == four["rank"]  # the class rank itself is unchanged
    assert four["projection"]["rank_classes"] == [2024, 2023, 2022, 2021]
    assert four["projection"]["rank"] != one["projection"]["rank"]


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
    # conference ranks run 1..n within each conference, in overall order; independents have none
    by_conf: dict = {}
    for r in rows:
        if r["conf"] and r["conf"] != "Independent":
            by_conf.setdefault(r["conf"], []).append(r["conf_rank"])
        else:
            assert r["conf_rank"] is None
    assert len(by_conf) >= 9 and all(v == list(range(1, len(v) + 1)) for v in by_conf.values())
    assert all(r["industry"] for r in rows[:50])  # the industry consensus covers every top program
    units = options[1]["views"][1]["rows"]
    assert len(units) == len(rows) and units[0]["team"] == rows[0]["team"]
    for k in ("off", "def", "run_o", "pass_o", "run_d", "pass_d"):
        ranks = sorted(u[k] for u in units if u[k] is not None)
        assert ranks[0] == 1 and len(ranks) > 100, k
