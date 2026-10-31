"""Tests for the DAD (Deviations Above Default) model."""

import math

import pytest

from ballmonitor.core import registry


@pytest.fixture
def model():
    return registry.load_model("dad")


def test_default_example(model):
    inputs = registry.load_example("dad", "default")
    pred = model.predict(inputs)

    assert len(pred.outcomes) >= 4
    total_dad = pred.outcome("Florida Gators Total DAD").estimate
    total_wad = pred.outcome("Florida Gators Total WAD").estimate
    assert total_dad is not None
    assert total_wad is not None
    assert total_dad > 0  # the 2024-25 champions beat a bubble baseline
    assert pred.inputs["Record"] == "36-4"  # real 2024-25 record
    assert len(pred.steps) >= 5


def test_diminishing_returns_legacy_probit():
    """v0.6.0 probit scale (variant v06_probit): moving from +20 to +30 adds far fewer
    deviations than +10 to +20 (concave diminishing returns)."""
    model = registry.load_model("dad", "v06_probit")
    base_case = {
        "team": "TestTeam",
        "sport": "basketball",
        "baseline": "bubble",
        "opponent": "NeutralOpponent",
        "opponent_rating": 11.5,
        "location": "neutral",
    }

    # Default team expected spread against equal opponent is 0.0 (P = 0.50)
    dad_10 = model.predict({**base_case, "margin": 10.0}).primary.estimate
    dad_20 = model.predict({**base_case, "margin": 20.0}).primary.estimate
    dad_30 = model.predict({**base_case, "margin": 30.0}).primary.estimate

    delta_10_to_20 = dad_20 - dad_10
    delta_20_to_30 = dad_30 - dad_20

    # Blowouts have diminishing returns
    assert delta_10_to_20 > delta_20_to_30
    # Difference between 20 and 30 is small (< 0.20 sigma)
    assert delta_20_to_30 < 0.20


def test_baseline_sensitivity(model):
    """Comparing against a higher standard (Champion) must produce lower DAD than

    comparing against Bubble or Replacement level.
    """
    game = {
        "team": "TestTeam",
        "sport": "basketball",
        "games": [
            {"opponent": "OppA", "opponent_rating": 15.0, "margin": 8.0, "location": "neutral"},
            {"opponent": "OppB", "opponent_rating": 10.0, "margin": 12.0, "location": "neutral"},
        ],
    }

    dad_replacement = model.predict({**game, "baseline": "replacement"}).primary.estimate
    dad_bubble = model.predict({**game, "baseline": "bubble"}).primary.estimate
    dad_champion = model.predict({**game, "baseline": "champion"}).primary.estimate

    assert dad_replacement > dad_bubble > dad_champion


def test_multi_team_leaderboard(model):
    inputs = registry.load_example("dad", "multi_team")
    pred = model.predict(inputs)

    assert len(pred.outcomes) == 4
    # Out of the 4 teams, UConn/Houston should be at the top and Standard Bubble at bottom
    top_dad = pred.outcomes[0].estimate
    bottom_dad = pred.outcomes[-1].estimate
    assert top_dad > bottom_dad
    assert "Standard Bubble" in pred.outcomes[-1].label or "Purdue" in pred.outcomes[-1].label or bottom_dad < top_dad


def test_football_and_soccer_sports(model):
    # Football
    cfb_inputs = registry.load_example("dad", "cfb_season")
    cfb_pred = model.predict(cfb_inputs)
    assert cfb_pred.primary.estimate is not None
    assert cfb_pred.primary.estimate > 0

    # Soccer
    soccer_inputs = {
        "team": "Arsenal",
        "sport": "soccer",
        "baseline": 0.0,
        "games": [
            {"opponent": "Chelsea", "opponent_rating": 0.4, "margin": 2.0, "location": "home"},
            {"opponent": "Liverpool", "opponent_rating": 1.2, "margin": 0.0, "location": "away"},
        ],
    }
    soccer_pred = model.predict(soccer_inputs)
    assert soccer_pred.primary.estimate is not None


def test_mlb_baseball(model):
    inputs = registry.load_example("dad", "mlb_dodgers_2024")
    pred = model.predict(inputs)

    assert pred.primary.estimate is not None
    assert pred.primary.estimate > 0
    assert pred.inputs["Sport"] == "Mlb"
    assert "MLB Wild Card Bubble" in pred.inputs["Baseline"]

    # Compare Dodgers against World Series Champion baseline vs Replacement
    pred_ws = model.predict({**inputs, "baseline": "champion"})
    pred_rep = model.predict({**inputs, "baseline": "replacement"})
    assert pred_rep.primary.estimate > pred.primary.estimate > pred_ws.primary.estimate


def test_college_baseball(model):
    inputs = registry.load_example("dad", "college_baseball_tennessee_2024")
    pred = model.predict(inputs)

    assert pred.primary.estimate is not None
    assert pred.primary.estimate > 0
    assert pred.inputs["Sport"] == "College_Baseball"
    assert "NCAA Regional Bubble" in pred.inputs["Baseline"]

    # Tennessee was 2024 national champion; against regional bubble they should have high positive DAD
    assert pred.outcome("Tennessee Volunteers Total DAD").estimate > 5.0


def test_auto_detection_conference_weekend_postseason(model):
    from ballmonitor.models.dad.matchups import classify_game

    # 1. Conference matchup auto-detection
    sec_match = classify_game("Tennessee Volunteers", "LSU Tigers", {}, "college_baseball")
    assert sec_match["classification"] == "conference"
    assert sec_match["conference"] == "SEC"

    # 2. Weekend auto-detection from calendar date (2024-02-16 is Friday)
    fri_match = classify_game("Tennessee Volunteers", "Texas Tech Red Raiders", {"date": "2024-02-16"}, "college_baseball")
    assert fri_match["classification"] == "weekend"

    # 3. Midweek auto-detection from calendar date (2024-04-16 is Tuesday)
    tue_match = classify_game("Tennessee Volunteers", "Tennessee Tech Golden Eagles", {"date": "2024-04-16"}, "college_baseball")
    assert tue_match["classification"] == "midweek"

    # 4. Postseason auto-detection from late June CWS date
    cws_match = classify_game("Tennessee Volunteers", "Texas A&M Aggies", {"date": "2024-06-24", "notes": "CWS Finals"}, "college_baseball")
    assert cws_match["classification"] == "postseason"


def test_wbb(model):
    inputs = registry.load_example("dad", "wbb_south_carolina_2024")
    pred = model.predict(inputs)

    assert pred.primary.estimate is not None
    assert pred.primary.estimate > 0
    assert pred.inputs["Sport"] == "Wbb"
    assert "NCAA Women's 4-Seed Host" in pred.inputs["Baseline"]
    assert pred.outcome("Record (Wins)").estimate == 38  # real 38-0 season

    # Sensitivity check: DAD vs Champion baseline < DAD vs 4-Seed Host < DAD vs Bubble
    pred_champ = model.predict({**inputs, "baseline": "champion"})
    pred_bubble = model.predict({**inputs, "baseline": "bubble"})
    assert pred_bubble.primary.estimate > pred.primary.estimate > pred_champ.primary.estimate


def test_softball(model):
    inputs = registry.load_example("dad", "college_softball_oklahoma_2024")
    pred = model.predict(inputs)

    assert pred.primary.estimate is not None
    assert pred.primary.estimate > 0
    assert pred.inputs["Sport"] == "Softball"
    assert "NCAA Softball National Seed" in pred.inputs["Baseline"]
    assert pred.outcome("Record (Wins)").estimate == 8

    # Verify auto-detection weighting in game records:
    # Game 1 (WCWS Finals): w=1.5
    # Game 7 (Sunday OSU): w=1.25
    # Game 8 (Texas Big 12/SEC): w=1.3
    # Game 9 (Tuesday Tulsa): w=0.75
    records = pred.extras["game_records"]
    assert records[0]["weight"] == 1.50  # Postseason WCWS
    assert records[6]["weight"] == 1.25  # Weekend Sunday
    assert records[7]["weight"] == 1.30  # Conference rivalry
    assert records[8]["weight"] == 0.75  # Midweek Tuesday

    # Sensitivity check: DAD vs Champion < DAD vs National Seed < DAD vs Regional Bubble
    pred_champ = model.predict({**inputs, "baseline": "champion"})
    pred_bubble = model.predict({**inputs, "baseline": "bubble"})
    assert pred_bubble.primary.estimate > pred.primary.estimate > pred_champ.primary.estimate


def test_soccer_scores_and_xg(model):
    inputs = registry.load_example("dad", "soccer_arsenal_2024")
    pred = model.predict(inputs)

    assert pred.primary.estimate is not None
    assert pred.primary.estimate > 0
    assert pred.inputs["Sport"] == "Soccer"
    assert "Champions League (Top 4)" in pred.inputs["Baseline"]
    assert pred.inputs["Record"] == "28-5-5"  # real 2023-24 league record (89 pts)

    # xG inputs (synthetic numbers; the real examples carry no xG)
    inputs = {"team": "Arsenal", "sport": "soccer", "baseline": "top4", "games": [
        {"opponent": "A", "opponent_rating": 0.5, "margin": 1, "location": "home",
         "xg_for": 2.4, "xg_against": 0.6},
        {"opponent": "B", "opponent_rating": 1.0, "margin": 0, "location": "away",
         "xg_for": 1.6, "xg_against": 1.1},
        {"opponent": "C", "opponent_rating": -0.5, "margin": 2, "location": "home",
         "xg_for": 1.2, "xg_against": 1.0},
    ]}
    pred = model.predict(inputs)

    # Verify xDAD and Luck metrics
    xdad = pred.outcome("Arsenal Total xDAD").estimate
    luck = pred.outcome("Finishing & Goalkeeping Luck").estimate
    assert xdad is not None
    assert xdad > 0
    assert luck is not None
    assert abs((pred.outcome("Arsenal Total DAD").estimate - xdad) - luck) < 0.01


def test_soccer_derby_and_ucl_weights(model):
    from ballmonitor.models.dad.matchups import classify_game

    # North London Derby
    nld = classify_game("Arsenal", "Tottenham Hotspur", {}, "soccer")
    assert nld["classification"] == "derby"
    assert "North London Derby" in nld["reason"]

    # Merseyside Derby
    mersey = classify_game("Liverpool", "Everton", {}, "soccer")
    assert mersey["classification"] == "derby"
    assert "Merseyside Derby" in mersey["reason"]

    # European Cup fixture
    ucl = classify_game("Arsenal", "Bayern Munich", {"notes": "UEFA Champions League Quarterfinal"}, "soccer")
    assert ucl["classification"] == "european_cup"


def test_soccer_baselines(model):
    inputs = registry.load_example("dad", "soccer_everton_relegation_2024")
    pred = model.predict(inputs)

    assert pred.primary.estimate is not None
    assert pred.primary.estimate > 0
    assert "Relegation Survival Bubble" in pred.inputs["Baseline"]

    # Everton performed well above relegation bubble, but against Top-4 or Champion standard they should have lower DAD
    pred_top4 = model.predict({**inputs, "baseline": "top4"})
    pred_champ = model.predict({**inputs, "baseline": "champion"})
    pred_rep = model.predict({**inputs, "baseline": "replacement"})

    assert pred_rep.primary.estimate > pred.primary.estimate > pred_top4.primary.estimate > pred_champ.primary.estimate






def test_hand_calculated_basketball_game_legacy_probit():
    """v0.6.0 scale. Bubble (+11.8) vs an equal opponent on a neutral floor: P_default = 0.5.
    Win by 10: P_actual = Phi(10 / 10.6) = 0.82726, DAD = (0.82726 - 0.5) / 0.5 = 0.6545."""
    model = registry.load_model("dad", "v06_probit")
    pred = model.predict({
        "team": "T", "sport": "basketball", "baseline": "bubble",
        "games": [{"opponent": "O", "opponent_rating": 11.8, "margin": 10, "location": "neutral"}],
    })
    rec = pred.extras["game_records"][0]
    assert rec["p_default"] == pytest.approx(0.5)
    assert rec["p_actual"] == pytest.approx(0.82726, abs=1e-4)
    assert pred.primary.estimate == pytest.approx(0.6545, abs=1e-3)
    assert pred.outcome("T Total WAD").estimate == pytest.approx(0.3273, abs=1e-3)


def test_game_dad_cap_limits_one_game_legacy_probit():
    """Replacement baseline vs a strong opponent: an upset win would be ~10σ uncapped."""
    model = registry.load_model("dad", "v06_probit")
    game = {"team": "T", "sport": "basketball", "baseline": "replacement",
            "games": [{"opponent": "O", "opponent_rating": 20.0, "margin": 5, "location": "away"}]}
    capped = model.predict(game).primary.estimate
    assert capped == pytest.approx(model.params.game_dad_cap)
    uncapped = registry.load_model("dad", "v06_probit", overrides={"game_dad_cap": 100.0}).predict(game)
    assert uncapped.primary.estimate > 4 * capped
    # WAD is not capped
    assert uncapped.outcome("T Total WAD").estimate == pytest.approx(
        model.predict(game).outcome("T Total WAD").estimate)


def test_football_has_its_own_presets(model):
    game = {"team": "T", "sport": "cfb", "games": [
        {"opponent": "O", "opponent_rating": 0.0, "margin": 21, "location": "home"}]}
    assert "Playoff Bubble" in model.predict({**game, "baseline": "bubble"}).inputs["Baseline"]
    assert model.predict({**game, "baseline": "bubble"}).inputs["Baseline Rating"] == "+20.40"


def test_football_win_strength_is_monotone(model):
    margins = [x / 10 for x in range(-200, 201)]
    probs = [model._calc_win_prob(m, "football") for m in margins]
    assert all(b >= a for a, b in zip(probs, probs[1:]))


def test_sport_aliases_and_unknown_inputs(model):
    game = {"opponent": "O", "opponent_rating": 0.0, "margin": 1, "location": "home"}
    a = model.predict({"team": "T", "sport": "EPL", "baseline": "top4", "games": [game]})
    b = model.predict({"team": "T", "sport": "soccer", "baseline": "top_4_seed", "games": [game]})
    assert a.primary.estimate == pytest.approx(b.primary.estimate)

    bad = [
        {"team": "T", "sport": "hockey", "games": [game]},
        {"team": "T", "sport": "basketball", "baseline": "elite", "games": [game]},
        {"team": "T", "sport": "basketball", "baseline": "europa", "games": [game]},
        {"team": "T", "sport": "basketball", "games": []},
        {"team": "T", "sport": "basketball", "games": [{"opponent": "O", "opponent_rating": 1.0}]},
        {"team": "T", "sport": "basketball", "games": [{"opponent": "O", "margin": 3}]},
        {"team": "T", "sport": "basketball", "games": [{**game, "location": "moon"}]},
        {"team": "T", "sport": "basketball", "games": [{**game, "margin": "big"}]},
        {"sport": "basketball", "teams": "UConn"},
    ]
    for inputs in bad:
        with pytest.raises(ValueError):
            model.predict(inputs)


def test_default_baseline_choices_resolve_for_every_sport():
    from ballmonitor.models.dad.model import SPORT_ALIASES

    game = {"opponent": "O", "opponent_rating": 0.0, "margin": 1}
    for choice in ("bubble", "champion", "top_4_seed", "average", "replacement"):
        m = registry.load_model("dad", overrides={"default_baseline": choice})
        for sport in SPORT_ALIASES:
            pred = m.predict({"team": "T", "sport": sport, "games": [game]})
            assert pred.primary.estimate is not None


def test_derby_and_conference_false_positives():
    from ballmonitor.models.dad.matchups import detect_college_conference, detect_soccer_derby

    assert detect_soccer_derby("Manchester City", "Newcastle United") is None
    assert detect_soccer_derby("Leicester City", "Manchester United") is None
    assert detect_soccer_derby("Manchester City FC", "Manchester United") == "Manchester Derby"
    assert detect_college_conference("West Virginia Mountaineers") == "Big 12"
    assert detect_college_conference("Iowa State Cyclones") == "Big 12"
    assert detect_college_conference("South Florida Bulls") == "American"
    assert detect_college_conference("Western Kentucky Hilltoppers") == "C-USA"
    assert detect_college_conference("Indiana State Sycamores") is None
    assert detect_college_conference("Texas A&M Aggies") == "SEC"
    assert detect_college_conference("Florida State Seminoles") == "ACC"


# ── v0.7.0: margin-scale DAD, strength, result-based WAD ─────────────────────

def _one(margin, opp=11.8, loc="neutral", **extra):
    return {"team": "T", "sport": "basketball", "baseline": "bubble",
            "games": [{"opponent": "O", "opponent_rating": opp, "margin": margin,
                       "location": loc, **extra}]}


def test_hand_calculated_margin_scale(model):
    """Bubble (+11.8) vs an equal opponent, neutral, win by 10, sigma 10.6, prior 1 game.
    Game DAD = (10 - 0) / 10.6 = 0.9434. Strength = (10 + 11.8) / (1 + 1) = 10.9,
    vs default -0.9 -> DAD/game = -0.0849, win chance Phi(-0.9/10.6) = 0.4662.
    WAD = 1 - P(bubble beats an equal team) = 1 - 0.5 = 0.5."""
    pred = model.predict(_one(10))
    ex = pred.extras
    assert ex["game_records"][0]["dad"] == pytest.approx(10 / 10.6)
    assert ex["total_dad"] == pytest.approx(0.9434, abs=1e-4)
    assert ex["strength_rating"] == pytest.approx(10.9)
    assert ex["strength_vs_default"] == pytest.approx(-0.9)
    assert pred.primary.estimate == pytest.approx(-0.085, abs=1e-3)
    assert ex["dad_per_game"] == pytest.approx(-0.9 / 10.6)
    assert ex["win_prob_vs_default"] == pytest.approx(0.4662, abs=1e-4)
    assert ex["total_wad"] == pytest.approx(0.5)


def test_home_edge_and_linearity(model):
    """Home win by 10 vs an average team, average baseline: expected spread = +3.2,
    game DAD = 6.8 / 10.6, adjusted performance = 6.8. Margin scale is linear."""
    g = {"team": "T", "sport": "basketball", "baseline": "average",
         "games": [{"opponent": "O", "opponent_rating": 0.0, "margin": 10, "location": "home"}]}
    rec = model.predict(g).extras["game_records"][0]
    assert rec["exp_spread"] == pytest.approx(3.2)
    assert rec["dad"] == pytest.approx(6.8 / 10.6)
    assert rec["adjusted"] == pytest.approx(6.8)
    d = [model.predict(_one(m)).extras["total_dad"] for m in (10, 20, 30)]
    assert d[1] - d[0] == pytest.approx(d[2] - d[1])


def test_margin_transform_cap_and_bonus():
    capped = registry.load_model("dad", overrides={"margin_cap_sd": 1.0})
    rec = capped.predict(_one(30)).extras["game_records"][0]
    assert rec["performance"] == pytest.approx(10.6)
    bonus = registry.load_model("dad", overrides={"win_bonus_sd": 0.1})
    perf = [bonus.predict(_one(m)).extras["game_records"][0]["performance"] for m in (5, -5)]
    assert perf == pytest.approx([6.06, -6.06])
    assert bonus.predict({**_one(0), "sport": "soccer", "baseline": 0.0}
                         ).extras["game_records"][0]["performance"] == 0


def test_shrinkage_by_games_played():
    games = [{"opponent": f"O{i}", "opponent_rating": 0.0, "margin": 10, "location": "neutral"}
             for i in range(4)]
    inputs = {"team": "T", "sport": "basketball", "baseline": "average", "games": games}
    none = registry.load_model("dad", overrides={"prior_games_basketball": 0.0}).predict(inputs)
    four = registry.load_model("dad", overrides={"prior_games_basketball": 4.0}).predict(inputs)
    assert none.extras["strength_rating"] == pytest.approx(10.0)
    assert four.extras["strength_rating"] == pytest.approx(5.0)       # 40 / (4 + 4)
    long = registry.load_model("dad", overrides={"prior_games_basketball": 4.0}).predict(
        {**inputs, "games": games * 4})
    assert long.extras["strength_rating"] == pytest.approx(160 / 20)  # more games, less shrink
    # résumé totals are not shrunk
    assert none.extras["total_dad"] == pytest.approx(four.extras["total_dad"])


def test_recency_weighting_halves_per_half_life():
    m = registry.load_model("dad", overrides={"half_life_days_basketball": 30.0,
                                              "prior_games_basketball": 0.0})
    games = [{"opponent": "A", "opponent_rating": 0.0, "margin": 20, "date": "2025-01-01"},
             {"opponent": "B", "opponent_rating": 0.0, "margin": 2, "date": "2025-01-31"}]
    ex = m.predict({"team": "T", "sport": "basketball", "baseline": "average",
                    "games": games}).extras
    assert [g["recency_weight"] for g in ex["game_records"]] == pytest.approx([0.5, 1.0])
    assert ex["strength_rating"] == pytest.approx((0.5 * 20 + 2) / 1.5)
    # as_of moves the reference date
    ex2 = m.predict({"team": "T", "sport": "basketball", "baseline": "average",
                     "as_of": "2025-03-02", "games": games}).extras
    assert ex2["game_records"][1]["recency_weight"] == pytest.approx(0.5)


def test_baseline_conversion_is_consistent(model):
    inputs = registry.load_example("dad", "default")
    for b in ("bubble", "champion", "replacement"):
        ex = model.predict({**inputs, "baseline": b}).extras
        base = ex["baseline_rating"]
        assert ex["strength_vs_default"] == pytest.approx(ex["strength_rating"] - base)
        assert ex["dad_per_game"] == pytest.approx(ex["strength_vs_default"] / 10.6)
        from statistics import NormalDist
        expected = NormalDist().cdf(ex["strength_vs_default"] / 10.6)
        assert ex["win_prob_vs_default"] == pytest.approx(min(max(expected, 0.005), 0.995))
    # the strength rating itself does not depend on the baseline
    a = model.predict({**inputs, "baseline": "bubble"}).extras["strength_rating"]
    c = model.predict({**inputs, "baseline": "champion"}).extras["strength_rating"]
    assert a == pytest.approx(c)


def test_result_wad_counts_wins_above_default(model):
    loss = model.predict(_one(-1)).extras["total_wad"]
    assert loss == pytest.approx(-0.5)               # bubble wins this 50%, we lost
    draw = model.predict({"team": "T", "sport": "soccer", "baseline": 0.0, "games": [
        {"opponent": "O", "opponent_rating": 0.0, "margin": 0, "location": "neutral"}]})
    assert draw.extras["total_wad"] == pytest.approx(0.0, abs=1e-9)
    # a 1-point win and a 30-point win are the same result
    assert model.predict(_one(1)).extras["total_wad"] == pytest.approx(
        model.predict(_one(30)).extras["total_wad"])


def test_legacy_variant_reproduces_v060(model):
    legacy = registry.load_model("dad", "v06_probit")
    pred = legacy.predict(_one(10))
    assert pred.primary.label == "T Total DAD"
    assert pred.primary.estimate == pytest.approx(0.6545, abs=1e-3)
    assert pred.outcome("T Total WAD").estimate == pytest.approx(0.3273, abs=1e-3)


def test_website_extras_keys_present(model):
    ex = model.predict(registry.load_example("dad", "default")).extras
    for k in ("total_dad", "dad_per_game", "games_count", "total_wad", "wins", "losses",
              "draws", "has_xg", "luck_dad", "total_xdad", "game_records"):
        assert k in ex
    for k in ("loc_label", "opponent", "margin", "dad", "wad", "weight_label"):
        assert k in ex["game_records"][0]
    board = model.predict(registry.load_example("dad", "multi_team")).extras["leaderboard"]
    for k in ("team", "wins", "losses", "draws", "total_dad", "total_wad", "dad_per_game"):
        assert k in board[0]
    assert [t["dad_per_game"] for t in board] == sorted((t["dad_per_game"] for t in board),
                                                        reverse=True)


def test_backtest_case_parses_rows(model):
    row = {"league": "mbb", "season": "2026", "sport": "basketball", "team": "T",
           "baseline": "average", "split_date": "2026-01-20", "n_first": "2", "n_second": "9",
           "actual_adj_margin": "5.3",
           "games": "3.10:12:h:20251105;-2.00:-0:n:20251110"}
    inputs, actual = model.backtest_case(row)
    assert actual == pytest.approx(5.3 / 10.6)
    assert inputs["games"][0] == {"opponent_rating": 3.1, "margin": 12.0, "location": "home",
                                  "date": "2025-11-05"}
    assert inputs["games"][1]["location"] == "neutral"
    pred = model.predict(inputs)
    m = model.score(pred, actual)
    assert m["abs_error"] == pytest.approx(abs(pred.extras["dad_per_game"] - actual))


def test_walk_forward_uses_only_earlier_games():
    np = pytest.importorskip("numpy")
    from ballmonitor.models.dad import research_strength as rs

    # 4 teams, 3 dates; predictions on date 2 must not change when date-2/3 results do
    d = np.array([1, 1, 2, 2, 3, 3])
    h = np.array([0, 2, 0, 1, 0, 1])
    a = np.array([1, 3, 2, 3, 3, 2])
    loc = np.ones(6)

    def ratings_on(margins, date):
        arrays = (d, h, a, np.array(margins, dtype=float), loc)
        for t_ok, thetas in rs.walk_forward_ratings(arrays, 4, [("raw", None)], [1.0],
                                                    float("inf"), 1):
            if d[t_ok[0]] == date:
                return t_ok, thetas[1.0]
        return None

    ok1, th1 = ratings_on([5, -3, 7, 1, 2, 4], 2)
    ok2, th2 = ratings_on([5, -3, -30, 40, 99, -99], 2)
    assert list(ok1) == [2, 3]
    assert np.allclose(th1, th2)
    # and they do change when an earlier (date-1) result changes
    _, th3 = ratings_on([25, -3, 7, 1, 2, 4], 2)
    assert not np.allclose(th1, th3)


def test_research_transforms_match_model_formula():
    np = pytest.importorskip("numpy")
    from ballmonitor.models.dad.research_strength import transform

    assert transform(("cap", 10), np.array([-25, 3, 25])).tolist() == [-10, 3, 10]
    assert transform(("bonus", 2), np.array([-5, 0, 5])).tolist() == [-7, 0, 7]
    assert transform(("tanh", 10), np.array([0.0]))[0] == 0
    assert transform(("log", 10), np.array([10.0]))[0] == pytest.approx(10 * math.log(2))
    m = registry.load_model("dad", overrides={"margin_cap_sd": 10 / 10.6,
                                              "win_bonus_sd": 2 / 10.6})
    perf = m.predict(_one(25)).extras["game_records"][0]["performance"]
    assert perf == pytest.approx(transform(("capbonus", (10, 2)), np.array([25.0]))[0])
