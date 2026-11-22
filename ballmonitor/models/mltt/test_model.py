import math

import pytest

from ballmonitor.core import registry
from ballmonitor.models.mltt import engine as E


def load(variant=None, **overrides):
    return registry.load_model("mltt", variant, overrides)


def rules(**kw):
    return E.rules(load(**kw).params)


# ----------------------------------------------------------------- rules arithmetic

def test_game_win_hand_calculated():
    # game to 2, golden point at 1-1: win 2-0 (q^2) or 2-1 after 1-1 (2q(1-q) * q) = q^2 (3 - 2q)
    assert E.game_win(0.6, to=2) == pytest.approx(0.36 * 1.8)
    assert E.game_win(0.5) == pytest.approx(0.5)
    assert E.game_win(0.55) > 0.55  # a game magnifies a rally edge


def test_game_win_to_11_counts_every_score():
    q = 0.53
    # sum the chance of every final score: 11-k for k = 0..9, plus 11-10 after 10-10
    by_hand = sum(math.comb(10 + k, k) * q ** 11 * (1 - q) ** k for k in range(10))
    by_hand += math.comb(20, 10) * q ** 10 * (1 - q) ** 10 * q
    assert E.game_win(q) == pytest.approx(by_hand)


def test_golden_game_race():
    assert E.race_win(0, 0, 0.5) == pytest.approx(0.5)
    assert E.race_win(0, 0, 0.45) + E.race_win(0, 0, 0.55) == pytest.approx(1.0)
    chances = [E.race_win(h, 0, 0.5) for h in range(6)]
    assert chances == sorted(chances) and chances[5] == pytest.approx(0.7975, abs=1e-4)
    assert E.race_win(20, 20, 0.6) == pytest.approx(0.6)  # one Ultimate Golden Point


def test_even_teams_win_probability():
    r = rules()
    assert E.win_prob_even(0, 0, r) == pytest.approx(0.5)
    # Stage One 11-4: clinched (11 + 0 > 4 + 6); 4-11: lost
    assert E.win_prob_even(15, 7, r) == pytest.approx(1.0)
    assert E.win_prob_even(15, -7, r) == pytest.approx(0.0)
    # 10-5: A must win the Golden Game (10 + 0 < 5 + 6) from a 5-point head start
    assert E.win_prob_even(15, 5, r) == pytest.approx(E.race_win(5, 0, 0.5))
    # no head start rule: a 10-5 lead is a coin flip
    assert E.win_prob_even(15, 5, rules(max_head_start=0)) == pytest.approx(0.5)


def test_match_distribution():
    r = rules()
    dist = E.match_distribution([0.5] * 15, 0.5, r)
    assert sum(dist) == pytest.approx(1.0)
    win, pts = E.summarize(dist, r)
    assert win == pytest.approx(0.5) and pts == pytest.approx(10.5)
    better, _ = E.summarize(E.match_distribution([0.55] * 15, 0.52, r), r)
    assert better > 0.5


# ---------------------------------------------------------------------------- ratings

def _toy(pa: int, pb: int, n: int) -> E.Data:
    games = [E.Game(4, f"m{i}", "2026-10-01", 1, "singles_1", 1, "A", "B", ("x",), ("y",), pa, pb) for i in range(n)]
    return E.Data([], games, {"x": {"mltt_rating": "2700"}, "y": {"mltt_rating": "2700"}}, {}, {})


def test_fit_recovers_rally_share():
    p = load(use_rating_prior=False, prior_rallies=0.001).params
    R = E.fit_ratings(_toy(11, 9, 200), p, season=4)  # 55% of rallies
    assert R.value["x"] - R.value["y"] == pytest.approx(math.log(0.55 / 0.45), abs=1e-3)


def test_prior_pulls_toward_rating():
    data = _toy(11, 9, 5)
    data.players["x"]["mltt_rating"] = "2500"
    weak = E.fit_ratings(data, load(prior_rallies=0.001, rating_source="current").params, season=4)
    strong = E.fit_ratings(data, load(prior_rallies=100000.0, rating_source="current").params, season=4)
    assert strong.value["x"] < weak.value["x"]  # a low rating drags x down when the prior counts
    p = load().params
    assert strong.value["x"] == pytest.approx(p.formula("prior_mean", rating=2500.0), abs=1e-3)


def test_dated_rating_has_no_hindsight():
    data = _toy(11, 9, 1)
    data.players["x"]["spindex_id"] = "M1"
    data.history["M1"] = [("2026-09-12", 2600, 2620), ("2026-10-03", 2620, 2580)]
    assert data.rating_on("x", "2026-09-01") == 2600  # the seed, before any result
    assert data.rating_on("x", "2026-09-12") == 2600  # same-day results don't count yet
    assert data.rating_on("x", "2026-09-13") == 2620
    assert data.rating_on("x", None) == 2580
    assert data.rating_on("y", None) is None  # no history: no prior (average)
    p = load(prior_rallies=100000.0).params
    R = E.fit_ratings(data, p, as_of="2026-09-13", season=4)
    assert R.prior["x"] == pytest.approx(p.formula("prior_mean", rating=2620.0))
    assert R.prior["y"] == 0.0


# ------------------------------------------------------------------------ the model

def test_match_prediction_shape_and_backtest_label():
    m = load()
    row = {"season": "3", "date": "2026-04-19", "team_a": "Portland Paddlers", "team_b": "Carolina Gold Rush",
           "winner": "Portland Paddlers"}
    inputs, actual = m.backtest_case(row)
    pred = m.predict(inputs)
    assert actual == pred.outcomes[0].label
    assert pred.outcomes[0].probability + pred.outcomes[1].probability == pytest.approx(1.0)
    a, b = pred.outcome("Portland Paddlers team points"), pred.outcome("Carolina Gold Rush team points")
    assert a.estimate + b.estimate == pytest.approx(21)
    assert set(m.score(pred, actual)) == {"brier", "log_loss", "top_pick_correct"}


def test_walk_forward_uses_only_earlier_games():
    m = load()
    R = m.ratings(season=3, as_of="2025-09-01")  # before Season 3: only Season 2 games
    data = m.data()
    seen = {x for g in data.games if g.date < "2025-09-01" for x in g.a + g.b}
    assert set(R.value) <= seen


def test_season_simulation_totals():
    pred = load(simulations=300).predict({"kind": "season"})
    ff = sum(o.probability for o in pred.outcomes if o.group == "Final Four")
    champ = sum(o.probability for o in pred.outcomes if o.group == "MLTT Cup")
    assert ff == pytest.approx(4.0) and champ == pytest.approx(1.0)
    teams = pred.extras["teams"]
    for d in teams.values():  # points shares from real standings
        assert d["pf"] + d["pa"] == 21 * d["played"]


def test_wpa_is_zero_sum_per_season():
    m = load()
    stats = E.player_season(m.data(), m.ratings(season=3), 3, m.params)
    # every game moves the two teams' chances by equal and opposite amounts
    assert sum(d["wpa"] for d in stats.values()) == pytest.approx(0.0, abs=1e-6)
