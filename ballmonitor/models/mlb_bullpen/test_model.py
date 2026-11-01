"""Tests for mlb_bullpen model, rest ledger, and Monte Carlo simulator."""

import pytest

from ballmonitor.core import registry
from ballmonitor.models.mlb_bullpen.ledger import BullpenLedger, RelieverWorkload
from ballmonitor.models.mlb_bullpen.model import MlbBullpenModel
from ballmonitor.models.mlb_bullpen.simulator import GameSimulator, MonteCarloSimulator


def test_ledger_availability_and_penalties():
    rested = RelieverWorkload(name="Rested", hand="R", role="closer", pitches_days=[0, 0, 0, 0, 0])
    yesterday = RelieverWorkload(name="Yesterday", hand="R", role="setup", pitches_days=[15, 0, 0, 0, 0])
    b2b = RelieverWorkload(name="BackToBack", hand="R", role="middle", pitches_days=[15, 12, 0, 0, 0])
    three_days = RelieverWorkload(name="ThreeDays", hand="R", role="middle", pitches_days=[10, 12, 14, 0, 0])
    high_pitch = RelieverWorkload(name="HighPitch", hand="R", role="long", pitches_days=[40, 0, 0, 0, 0])

    ledger = BullpenLedger([rested, yesterday, b2b, three_days, high_pitch])
    params = registry.load_model("mlb_bullpen").params

    # Availability constraints (hard rules from config)
    assert ledger.is_available(rested, params) is True
    assert ledger.is_available(yesterday, params) is True
    assert ledger.is_available(b2b, params) is (2 < params.max_consecutive_days)
    assert ledger.is_available(three_days, params) is (3 < params.max_consecutive_days)
    assert ledger.is_available(high_pitch, params) is (40 < params.max_pitches_yesterday)

    # Penalty comparisons
    pen_rested = ledger.compute_fatigue_penalty(rested, params)
    pen_yesterday = ledger.compute_fatigue_penalty(yesterday, params)
    pen_b2b = ledger.compute_fatigue_penalty(b2b, params)

    assert pen_rested == 0.0
    assert pen_yesterday > pen_rested
    assert pen_b2b > pen_yesterday
    # Hand check: 15 pitches yesterday -> penalty_pitched_yesterday + per_10 * 1.5
    assert pen_yesterday == pytest.approx(
        params.penalty_pitched_yesterday + params.penalty_per_10_pitches_3d * 1.5
    )


def test_consecutive_days_rule_is_a_param():
    four = RelieverWorkload(name="F", hand="R", role="middle", pitches_days=[10, 10, 10, 0, 0])
    ledger = BullpenLedger([four])
    strict = registry.load_model("mlb_bullpen", overrides={"max_consecutive_days": 3}).params
    loose = registry.load_model("mlb_bullpen", overrides={"max_consecutive_days": 4}).params
    assert not ledger.is_available(four, strict)
    assert ledger.is_available(four, loose)


def test_role_inference_from_history():
    params = registry.load_model("mlb_bullpen").params
    ledger = BullpenLedger.from_inputs([
        {"name": "Closer", "games": 30, "apps": 14, "saves": 9, "finishes": 12, "outs": 42},
        {"name": "Setup", "games": 30, "apps": 15, "holds": 8, "outs": 45},
        {"name": "Long", "games": 30, "apps": 6, "outs": 50},
        {"name": "Middle", "games": 30, "apps": 10, "outs": 30},
        {"name": "New", "pitches_days": [0, 0, 0, 0, 0]},
        {"name": "Given", "role": "closer", "games": 30, "apps": 1},
    ], params)
    roles = {n: r.role for n, r in ledger.relievers.items()}
    # an explicitly given closer wins (no second closer is inferred)
    assert roles["Given"] == "closer" and roles["Closer"] != "closer"
    assert roles["Long"] == "long"
    assert roles["Middle"] == "middle" and roles["New"] == "middle"
    assert ledger.relievers["Given"].role_source == "given"
    assert ledger.relievers["New"].role_source.startswith("no history")
    auto = BullpenLedger.from_inputs([
        {"name": "Closer", "games": 30, "apps": 14, "saves": 9, "finishes": 12, "outs": 42},
        {"name": "Setup", "games": 30, "apps": 15, "holds": 8, "outs": 45},
    ], params)
    assert auto.relievers["Closer"].role == "closer"
    assert auto.relievers["Setup"].role == "setup"


def test_usage_term_direction():
    params = registry.load_model("mlb_bullpen").params
    busy = RelieverWorkload(name="B", hand="R", role="middle", games=30, apps=18)
    idle = RelieverWorkload(name="I", hand="R", role="middle", games=30, apps=3)
    new = RelieverWorkload(name="N", hand="R", role="middle")
    assert busy.usage_score(params) > 0 > idle.usage_score(params)
    assert new.usage_score(params) == pytest.approx(0.0)


def test_situation_classification():
    from ballmonitor.models.mlb_bullpen.simulator import classify_situation

    p = registry.load_model("mlb_bullpen").params
    assert classify_situation(9, 2, 1.0, p) == "save"
    assert classify_situation(10, 0, 1.0, p) == "late_tie"
    assert classify_situation(9, 7, 0.1, p) == "blowout"
    assert classify_situation(8, 1, 1.0, p) == "late_close"
    assert classify_situation(8, 1, 5.0, p) == "fireman"
    assert classify_situation(7, 4, 0.5, p) == "late_other"
    assert classify_situation(3, 0, 0.5, p) == "early"
    assert classify_situation(6, 0, 1.0, p) == "middle"


def test_closer_is_held_for_late_leads():
    """The v0.3 weakness: the closer was often the first arm out in neutral middle innings."""
    model = registry.load_model("mlb_bullpen", overrides={"num_simulations": 400})
    pen = [{"name": n, "hand": "R", "role": r, "pitches_days": [0, 0, 0, 0, 0]}
           for n, r in [("C", "closer"), ("S1", "setup"), ("S2", "setup"), ("M1", "middle"),
                        ("M2", "middle"), ("M3", "middle"), ("L", "long")]]
    pred = model.predict({"starter_name": "SP", "starter_stamina": 90, "lineup": ["R"] * 9,
                          "relievers": pen})
    st, n = pred.extras["stats"], pred.extras["n_simulations"]
    assert st["C"]["first_in"] / n < 0.08
    assert st["C"]["first_in"] < min(st[m]["first_in"] for m in ("M1", "M2", "M3"))
    assert 0.25 < st["C"]["appearances"] / n < 0.7
    # nearly all of the closer's appearances happen with him finishing (saves in wins)
    assert st["C"]["saves"] > 0.3 * st["C"]["appearances"]


def test_fatigue_formula_override_is_respected():
    """A user formula that evaluates to 0 must not be replaced by the default."""
    tired = RelieverWorkload(name="T", hand="R", role="setup", pitches_days=[30, 20, 0, 0, 0])
    ledger = BullpenLedger([tired])
    params = registry.load_model("mlb_bullpen", overrides={"formulas.fatigue_penalty": "0"}).params
    assert ledger.compute_fatigue_penalty(tired, params) == 0.0


def test_simulator_three_batter_minimum():
    """Verify modern MLB rule: a reliever cannot be removed mid-inning before facing 3 batters."""
    ledger = BullpenLedger([
        RelieverWorkload(name="Reliever A", hand="R", role="setup", pitches_days=[0, 0, 0, 0, 0]),
        RelieverWorkload(name="Reliever B", hand="R", role="closer", pitches_days=[0, 0, 0, 0, 0]),
    ])

    sim = GameSimulator(
        starter_name="Starter",
        starter_hand="R",
        starter_stamina=90,
        ledger=ledger,
        lineup=["R"] * 9,
        params=registry.load_model("mlb_bullpen").params,
    )

    from ballmonitor.models.mlb_bullpen.simulator import PitchingAppearance
    import random
    r = random.Random(42)

    reliever = PitchingAppearance(
        name="Reliever A",
        is_starter=False,
        role="setup",
        hand="R",
        batters_faced=2,  # Has only faced 2 batters
        pitches=40,  # High pitch count (above reliever_mid_max_pitches)
    )

    # Mid-inning hook should be False because batters_faced < 3
    hooked = sim._should_hook_mid_inning(
        reliever, inning=7, team_score=3, opp_score=2, runs_in_half=1, outs=1,
        on_1b=True, on_2b=True, on_3b=False, r=r
    )
    assert hooked is False

    # Once batters_faced >= 3, hook can trigger
    reliever.batters_faced = 3
    hooked_after_3 = sim._should_hook_mid_inning(
        reliever, inning=7, team_score=3, opp_score=2, runs_in_half=1, outs=1,
        on_1b=True, on_2b=True, on_3b=False, r=r
    )
    assert hooked_after_3 is True


def test_end_to_end_mlb_bullpen_predict():
    model = registry.load_model("mlb_bullpen")
    example = registry.load_example("mlb_bullpen", "default")
    pred = model.predict(example)

    assert pred.primary.probability is not None
    assert 0.0 <= pred.primary.probability <= 1.0
    assert len(pred.outcomes) > 5
    assert len(pred.steps) >= 4

    # Verify appearance probabilities for all relievers are valid probabilities
    for outcome in pred.outcomes:
        if outcome.group == "Appearance Probability":
            assert 0.0 <= outcome.probability <= 1.0


def test_fatigue_reduces_usage_probability():
    """Verify that a fatigued pitcher gets selected significantly less than a rested one."""
    model = registry.load_model("mlb_bullpen", overrides={"num_simulations": 300, "seed": 123})

    # Scenario 1: Setup man rested
    inputs_rested = {
        "starter_name": "Ace",
        "starter_hand": "R",
        "starter_stamina": 80,
        "lineup": ["R", "L", "R", "L", "R", "L", "R", "L", "R"],
        "relievers": [
            {"name": "Setup Man", "hand": "R", "role": "setup", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Middle Guy 1", "hand": "R", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Middle Guy 2", "hand": "R", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Middle Guy 3", "hand": "R", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Middle Guy 4", "hand": "R", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Middle Guy 5", "hand": "L", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Long Man", "hand": "R", "role": "long", "pitches_days": [0, 0, 0, 0, 0]},
        ],
    }
    pred_rested = model.predict(inputs_rested)
    p_setup_rested = pred_rested.outcome("Setup Man (RHP)").probability

    # Scenario 2: Setup man pitched back-to-back days
    inputs_fatigued = {
        "starter_name": "Ace",
        "starter_hand": "R",
        "starter_stamina": 80,
        "lineup": ["R", "L", "R", "L", "R", "L", "R", "L", "R"],
        "relievers": [
            {"name": "Setup Man", "hand": "R", "role": "setup", "pitches_days": [22, 18, 0, 0, 0]},
            {"name": "Middle Guy 1", "hand": "R", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Middle Guy 2", "hand": "R", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Middle Guy 3", "hand": "R", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Middle Guy 4", "hand": "R", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Middle Guy 5", "hand": "L", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]},
            {"name": "Long Man", "hand": "R", "role": "long", "pitches_days": [0, 0, 0, 0, 0]},
        ],
    }
    pred_fatigued = model.predict(inputs_fatigued)
    p_setup_fatigued = pred_fatigued.outcome("Setup Man (RHP)").probability

    assert p_setup_fatigued < p_setup_rested


def test_backtest_case_and_scoring():
    """Verify parsing a backtest row and scoring the resulting prediction."""
    model = registry.load_model("mlb_bullpen")
    row = {
        "game_pk": "12345",
        "game_date": "2024-07-05",
        "team": "NYY",
        "is_home": "1",
        "starter_name": "Gerrit Cole",
        "starter_hand": "R",
        "starter_stamina": "90",
        "lineup": "R,L,R,L,R,R,L,R,S",
        "relievers_json": (
            '[{"name": "Reliever A", "hand": "R", "role": "closer", "pitches_days": [0, 0, 0, 0, 0]}, '
            '{"name": "Reliever B", "hand": "R", "role": "middle", "pitches_days": [0, 0, 0, 0, 0]}]'
        ),
        "actual_relievers_used": "Reliever A",
        "first_reliever": "Reliever A",
    }

    model = registry.load_model("mlb_bullpen", overrides={"num_simulations": 100})
    inputs, actual = model.backtest_case(row)
    assert inputs["starter_stamina"] == 90
    del row["starter_stamina"]
    assert "starter_stamina" not in model.backtest_case(row)[0]  # blank -> default
    row["starter_stamina"] = "90"
    pred = model.predict(inputs)
    scores = model.score(pred, actual)

    assert "brier" in scores
    assert "top_pick_correct" in scores
    assert "top_3_recall" in scores
    assert 0.0 <= scores["brier"] <= 1.0
    assert 0.0 <= scores["top_pick_correct"] <= 1.0
    assert scores["log_loss"] >= 0 and scores["log_loss_appear"] > 0

    # first reliever outside the listed pool (e.g. a position player): first metrics skipped
    import math
    _, actual2 = model.backtest_case({**row, "first_reliever": "Somebody Else",
                                      "actual_relievers_used": "Somebody Else;Reliever A"})
    s2 = model.score(pred, actual2)
    assert math.isnan(s2["log_loss"]) and math.isnan(s2["brier_first"])
    assert not math.isnan(s2["brier"])


def test_leverage_index_and_schedule_context():
    """Verify Leverage Index calculation and off-day fatigue discount."""
    from ballmonitor.models.mlb_bullpen.simulator import compute_leverage_index

    # 1. LI checks
    early_empty = compute_leverage_index(1, score_diff=0, outs=0)
    jam_8th = compute_leverage_index(8, score_diff=1, outs=2, on_1b=True, on_2b=True, on_3b=True)
    blowout = compute_leverage_index(7, score_diff=7, outs=0)

    assert jam_8th > early_empty > blowout
    assert jam_8th >= 3.5  # Extreme leverage
    assert blowout <= 0.40  # Low leverage / garbage time

    # 2. Off-day tomorrow fatigue discount check
    reliever = RelieverWorkload(name="Reliever", hand="R", role="setup", pitches_days=[20, 0, 0, 0, 0])
    ledger = BullpenLedger([reliever])

    params = registry.load_model("mlb_bullpen", overrides={"off_day_tomorrow_discount": 0.5}).params
    regular_pen = ledger.compute_fatigue_penalty(reliever, params, off_day_tomorrow=False)
    off_day_pen = ledger.compute_fatigue_penalty(reliever, params, off_day_tomorrow=True)

    assert off_day_pen == pytest.approx(regular_pen * 0.50)
    assert regular_pen > 0


def test_seed_reproducible_and_changes_with_seed():
    example = registry.load_example("mlb_bullpen", "default")
    a = registry.load_model("mlb_bullpen", overrides={"num_simulations": 100}).predict(example)
    b = registry.load_model("mlb_bullpen", overrides={"num_simulations": 100}).predict(example)
    c = registry.load_model("mlb_bullpen", overrides={"num_simulations": 100, "seed": 7}).predict(example)
    assert a.extras["stats"] == b.extras["stats"]
    assert a.extras["stats"] != c.extras["stats"]


def test_save_rule():
    """Saves need a held lead: walk-off wins and blown leads are never saves."""
    from ballmonitor.models.mlb_bullpen.simulator import PitchingAppearance

    model = registry.load_model("mlb_bullpen", overrides={"num_simulations": 300})
    example = registry.load_example("mlb_bullpen", "default")
    pred = model.predict(example)
    total_saves = sum(st["saves"] for st in pred.extras["stats"].values())
    # Saves can only happen in wins, at most one per game
    assert 0 < total_saves < 300

    from ballmonitor.models.mlb_bullpen.simulator import is_save

    def app(**kw):
        return PitchingAppearance(name="x", is_starter=False, role="closer", hand="R", **kw)

    assert is_save(app(entry_lead=3, outs_recorded=3))  # classic 3-run save
    assert not is_save(app(entry_lead=4, outs_recorded=3))  # 4-run lead, bases empty
    assert is_save(app(entry_lead=4, entry_runners=2, outs_recorded=1))  # tying run on deck
    assert not is_save(app(entry_lead=3, outs_recorded=1))  # < 1 inning, tying run not up
    assert is_save(app(entry_lead=2, outs_recorded=1))  # tying run on deck
    assert not is_save(app(entry_lead=1, outs_recorded=3, lead_lost=True))  # blown lead
    assert not is_save(app(entry_lead=0, outs_recorded=3))  # entered tied (walk-off win)
    assert is_save(app(entry_lead=6, outs_recorded=9))  # 3+ innings


def test_bad_inputs_raise_value_error():
    model = registry.load_model("mlb_bullpen", overrides={"num_simulations": 50})
    good = registry.load_example("mlb_bullpen", "default")
    bad_cases = [
        {**good, "relievers": []},
        {**good, "lineup": ["R", "X"]},
        {**good, "starter_hand": "Q"},
        {**good, "starter_stamina": "lots"},
        {**good, "is_home": "maybe"},
        {**good, "relievers": [{"hand": "R"}]},
        {**good, "relievers": [{"name": "A", "role": "ace"}]},
        {**good, "relievers": [{"name": "A", "pitches_days": ["x"]}]},
        {**good, "relievers": [{"name": "A", "games": 3, "apps": 5}]},
        {**good, "relievers": [{"name": "A", "saves": -1}]},
    ]
    for inputs in bad_cases:
        with pytest.raises(ValueError):
            model.predict(inputs)




# --------------------------------------------------------------------------- v0.5

def test_calibration_mapping_hand_values():
    """appear_logit: logit P = calib_intercept_<role> + calib_slope * logit P_sim + ..."""
    import math

    from ballmonitor.models.mlb_bullpen.calibration import appear_probability, logit

    identity = registry.load_model("mlb_bullpen", overrides={
        "calib_intercept_setup": 0.0, "calib_slope": 1.0, "tendency_weight": 0.0, "blend_weight_direct": 0.0,
    }).params
    assert appear_probability(0.3, "setup", 0.7, 2.0, identity, 1e-3) == pytest.approx(0.3)
    p = registry.load_model("mlb_bullpen", overrides={
        "calib_intercept_setup": -0.2, "calib_slope": 0.5, "tendency_weight": 1.0, "blend_weight_direct": 0.6,
    }).params
    # hand calculation: z = -0.2 + 0.5 * logit(0.9) + 1.0 * 0.1 + 0.6 * (-1.0)
    z = -0.2 + 0.5 * math.log(0.9 / 0.1) + 0.1 - 0.6
    assert appear_probability(0.9, "setup", 0.1, -1.0, p, 1e-3) == pytest.approx(1 / (1 + math.exp(-z)))
    # slope < 1 pulls extreme simulated frequencies toward the middle
    shrink = registry.load_model("mlb_bullpen", overrides={"calib_slope": 0.8, "calib_intercept_middle": 0.0,
                                                           "tendency_weight": 0.0, "blend_weight_direct": 0.0}).params
    assert appear_probability(0.95, "middle", 0.0, 0.0, shrink, 1e-3) < 0.95
    assert appear_probability(0.02, "middle", 0.0, 0.0, shrink, 1e-3) > 0.02
    assert logit(0.0, 1e-3) == pytest.approx(math.log(1e-3 / (1 - 1e-3)))  # clipped, finite


def test_first_reliever_blend_and_roster():
    from ballmonitor.models.mlb_bullpen.calibration import first_probabilities

    raw = registry.load_model("mlb_bullpen", overrides={"first_weight_sim": 1.0, "first_weight_direct": 0.0}).params
    pf = first_probabilities({"A": 0.6, "B": 0.3, "C": 0.1}, {}, {"A": True, "B": True, "C": True}, raw, 1e-3)
    assert pf == pytest.approx({"A": 0.6, "B": 0.3, "C": 0.1})
    pf = first_probabilities({"A": 0.6, "B": 0.3, "C": 0.1}, {}, {"A": False, "B": True, "C": True}, raw, 1e-3)
    assert pf["A"] == 0.0 and pf["B"] == pytest.approx(0.75)
    flat = registry.load_model("mlb_bullpen", overrides={"first_weight_sim": 0.5, "first_weight_direct": 0.0}).params
    pf = first_probabilities({"A": 0.8, "B": 0.2}, {}, {}, flat, 1e-3)
    assert pf["A"] == pytest.approx(2 / 3)  # sqrt(0.8) / (sqrt(0.8) + sqrt(0.2))
    mixed = registry.load_model("mlb_bullpen", overrides={"first_weight_sim": 0.0, "first_weight_direct": 1.0}).params
    pf = first_probabilities({"A": 0.5, "B": 0.5}, {"A": math.log(3.0), "B": 0.0}, {}, mixed, 1e-3)
    assert pf["A"] == pytest.approx(0.75)


import math  # noqa: E402  (used by the tests above and below)


def test_roster_filter_inactive_arm_never_pitches():
    model = registry.load_model("mlb_bullpen", overrides={"num_simulations": 200})
    pen = [{"name": n, "hand": "R", "role": r, "pitches_days": [0, 0, 0, 0, 0]}
           for n, r in [("C", "closer"), ("S1", "setup"), ("M1", "middle"), ("M2", "middle"), ("L", "long")]]
    pen[1]["active"] = "false"  # optioned / on the IL today
    pred = model.predict({"starter_name": "SP", "starter_stamina": 90, "relievers": pen})
    assert pred.extras["stats"]["S1"]["appearances"] == 0
    assert pred.extras["p_appear"]["S1"] == 0.0 and pred.extras["p_first"]["S1"] == 0.0
    assert "not active" in pred.outcome("S1 (RHP)").note
    # even when everyone else is exhausted, an inactive arm is not used as an emergency arm
    tired = [{"name": "T", "hand": "R", "pitches_days": [30, 30, 30, 0, 0]},
             {"name": "X", "hand": "R", "pitches_days": [0, 0, 0, 0, 0], "active": False}]
    pred = model.predict({"starter_name": "SP", "starter_stamina": 60, "relievers": tired})
    assert pred.extras["stats"]["X"]["appearances"] == 0
    assert pred.extras["stats"]["T"]["appearances"] > 0
    with pytest.raises(ValueError):
        model.predict({"starter_name": "SP", "relievers": [{"name": "A", "active": "maybe"}]})


def test_tendency_shrinkage_hand_values():
    from ballmonitor.models.mlb_bullpen.tendency import log_usage_ratio, shrunk_relievers

    p = registry.load_model("mlb_bullpen", overrides={"tendency_prior_games": 20.0,
                                                      "bullpen_baseline_relievers": 3.0}).params
    # (40 * 4.0 + 20 * 3.3) / 60 = 3.7667
    assert shrunk_relievers(4.0, 40, 3.3, p) == pytest.approx(226 / 60)
    lr, s = log_usage_ratio(4.0, 40, 3.3, p)
    assert lr == pytest.approx(math.log(226 / 60 / 3.0))
    assert shrunk_relievers(None, 0, 3.3, p) == pytest.approx(3.3)  # no team history -> league
    assert shrunk_relievers(4.0, 40, None, p) == pytest.approx((160 + 60) / 60)  # league -> baseline
    assert log_usage_ratio(None, None, None, p) == (0.0, None)  # no inputs -> no adjustment
    more = registry.load_model("mlb_bullpen", overrides={"tendency_prior_games": 200.0}).params
    assert abs(shrunk_relievers(4.0, 40, 3.3, more) - 3.3) < abs(shrunk_relievers(4.0, 40, 3.3, p) - 3.3)


def test_rolling_usage_uses_earlier_dates_only():
    from ballmonitor.models.mlb_bullpen.tendency import rolling_usage

    rows = [
        {"game_pk": "1", "team": "A", "game_date": "2026-04-01", "pool_used": 2},
        {"game_pk": "1", "team": "B", "game_date": "2026-04-01", "pool_used": 4},
        {"game_pk": "2", "team": "A", "game_date": "2026-04-02", "pool_used": 5},  # doubleheader
        {"game_pk": "3", "team": "A", "game_date": "2026-04-02", "pool_used": 1},
        {"game_pk": "4", "team": "A", "game_date": "2026-04-03", "pool_used": 3},
    ]
    r = rolling_usage(rows, team_games=2, league_days=30)
    assert r[("1", "A")] == {"team_recent_games": 0, "team_recent_relievers": None, "league_recent_relievers": None}
    assert r[("2", "A")]["team_recent_relievers"] == 2.0 and r[("3", "A")]["team_recent_relievers"] == 2.0
    assert r[("2", "A")]["league_recent_relievers"] == 3.0
    assert r[("4", "A")]["team_recent_games"] == 2  # window: last 2 games (both on 04-02)
    assert r[("4", "A")]["team_recent_relievers"] == 3.0
    assert r[("4", "A")]["league_recent_relievers"] == pytest.approx(12 / 4)


def test_tendency_input_moves_expected_relievers():
    model = registry.load_model("mlb_bullpen", overrides={"num_simulations": 200, "tendency_weight": 1.0})
    ex = registry.load_example("mlb_bullpen", "default")
    busy = model.predict({**ex, "team_recent_relievers": 4.0, "team_recent_games": 40,
                          "league_recent_relievers": 3.3})
    quiet = model.predict({**ex, "team_recent_relievers": 2.6, "team_recent_games": 40,
                           "league_recent_relievers": 3.3})
    assert busy.extras["log_ratio"] > 0 > quiet.extras["log_ratio"]
    assert sum(busy.extras["p_appear"].values()) > sum(quiet.extras["p_appear"].values())
    assert busy.extras["stats"] == quiet.extras["stats"]  # the simulation itself is unchanged


def test_direct_model_features_and_direction():
    from ballmonitor.models.mlb_bullpen.calibration import DIRECT_FEATURES, direct_features, direct_logit

    p = registry.load_model("mlb_bullpen").params
    rel = RelieverWorkload(name="A", hand="R", role="long", pitches_days=[0, 12, 0, 0, 0], games=30, apps=12,
                           new_arrival=True)
    x = dict(zip(DIRECT_FEATURES, direct_features(
        rel, available=True, n_available=8, starter_stamina=p.starter_stamina_default / 2,
        off_day_tomorrow=True, is_home=False, log_ratio=0.1, params=p)))
    assert x["intercept"] == 1 and x["role_long"] == 1 and x["role_closer"] == 0
    assert x["two_days_ago"] == 1 and x["yesterday"] == 0 and x["pitches_3d"] == pytest.approx(1.2)
    assert x["starter_length"] == pytest.approx(math.log(0.5)) and x["long_x_starter"] == pytest.approx(math.log(0.5))
    assert x["log_available"] == pytest.approx(math.log(8)) and x["tendency"] == 0.1
    assert x["off_day_tomorrow"] == 1 and x["is_home"] == 0 and x["new_arrival"] == 1
    rate = (12 + p.usage_prior_games * p.usage_prior_rate) / (30 + p.usage_prior_games)
    assert x["usage"] == pytest.approx(math.log(rate / p.usage_prior_rate))
    # the fitted weights: pitching yesterday and a bigger pen lower the direct probability
    rested = direct_features(rel, available=True, n_available=8, starter_stamina=90, off_day_tomorrow=False,
                             is_home=True, log_ratio=0.0, params=p)
    tired_rel = RelieverWorkload(name="B", hand="R", role="long", pitches_days=[20, 0, 0, 0, 0], games=30, apps=12)
    tired = direct_features(tired_rel, available=True, n_available=8, starter_stamina=90, off_day_tomorrow=False,
                            is_home=True, log_ratio=0.0, params=p)
    big_pen = direct_features(rel, available=True, n_available=12, starter_stamina=90, off_day_tomorrow=False,
                              is_home=True, log_ratio=0.0, params=p)
    assert direct_logit(tired, p) < direct_logit(rested, p)
    assert direct_logit(big_pen, p) < direct_logit(rested, p)
    # hand check of the linear predictor
    assert direct_logit(rested, p) == pytest.approx(sum(getattr(p, f"direct_{f}") * v
                                                        for f, v in zip(DIRECT_FEATURES, rested)))


def test_blend_weight_zero_reports_calibrated_simulation():
    ex = registry.load_example("mlb_bullpen", "default")
    sim_only = registry.load_model("mlb_bullpen", overrides={
        "num_simulations": 200, "blend_weight_direct": 0.0, "calib_slope": 1.0, "tendency_weight": 0.0,
        "calib_intercept_closer": 0.0, "calib_intercept_setup": 0.0, "calib_intercept_middle": 0.0,
        "calib_intercept_long": 0.0, "first_weight_sim": 1.0, "first_weight_direct": 0.0,
    }).predict(ex)
    n = sim_only.extras["n_simulations"]
    for name, st in sim_only.extras["stats"].items():
        assert sim_only.extras["p_appear"][name] == pytest.approx(min(max(st["appearances"] / n, 0.5 / n), 1 - 0.5 / n))
        assert sim_only.extras["p_first"][name] == pytest.approx(
            max(st["first_in"] / n, 0.5 / n) / sum(max(s["first_in"] / n, 0.5 / n)
                                                    for s in sim_only.extras["stats"].values()))
    assert sim_only.extras["p_direct"] == {}
    blended = registry.load_model("mlb_bullpen", overrides={"num_simulations": 200}).predict(ex)
    assert blended.extras["stats"] == sim_only.extras["stats"]
    for o in blended.outcomes:
        if o.group == "Appearance Probability":
            assert any(r in o.note for r in ("closer", "setup", "middle", "long")) and "|" in o.note


# ---------------------------------------------------------------- bullpen runs (v0.6.0)


def test_reliever_rating_hand_values_and_no_history_prior():
    from types import SimpleNamespace

    from ballmonitor.models.mlb_bullpen.runs import reliever_rate

    p = registry.load_model("mlb_bullpen", overrides={"runs_prior_outs": 300, "runs_prior_rate": 0.19}).params
    # (9 + 300 x 0.19) / (30 + 300) = 66 / 330 = 0.2 runs per out
    assert reliever_rate(30, 9, p) == pytest.approx(0.2)
    assert reliever_rate(0, 0, p) == pytest.approx(0.19)  # no history -> prior
    ns = SimpleNamespace(runs_prior_outs=300, runs_prior_rate=0.19)  # research's closed form
    assert reliever_rate(30, 9, ns) == pytest.approx(reliever_rate(30, 9, p))
    # the config formula is used (tweakable)
    flat = registry.load_model("mlb_bullpen", overrides={"formulas.reliever_rating": "runs_prior_rate"}).params
    assert reliever_rate(30, 9, flat) == pytest.approx(0.19)


def test_bullpen_runs_hand_calculation():
    from types import SimpleNamespace

    from ballmonitor.models.mlb_bullpen.runs import bullpen_runs, expected_outs

    p = SimpleNamespace(runs_league_rate=0.2, runs_outs_source="reported", runs_default_outs_per_app=3.0)
    # A: 3 outs at 0.1, B: 6 outs at 0.3 -> X = 9, E = 0.3 + 1.8 = 2.1, league 1.8
    # usual mix: A 10 / B 30 recent outs -> usual rate (1 + 9) / 40 = 0.25 -> 2.25
    out = bullpen_runs({"A": 3.0, "B": 6.0}, {"A": 0.1, "B": 0.3}, {"A": 10, "B": 30}, p)
    assert out["expected_outs"] == pytest.approx(9.0)
    assert out["expected_runs"] == pytest.approx(2.1)
    assert out["vs_average"] == pytest.approx(0.3)
    assert out["usual_rate"] == pytest.approx(0.25)
    assert out["vs_usual"] == pytest.approx(-0.15)
    # expected outs: P(appear) 0.5 x (40 simulated outs / 10 simulated appearances) = 2
    assert expected_outs(0.5, 10, 40, 100, p) == pytest.approx(2.0)
    assert expected_outs(0.5, 0, 0, 100, p) == pytest.approx(1.5)  # never simulated -> default
    p.runs_outs_source = "simulated"
    assert expected_outs(0.5, 10, 40, 100, p) == pytest.approx(0.4)


def _pen(ra=None):
    pen = [{"name": n, "hand": "R", "role": r, "pitches_days": [0, 0, 0, 0, 0], "games": 30, "apps": 10,
            "outs": 30} for n, r in [("C", "closer"), ("S1", "setup"), ("M1", "middle"), ("M2", "middle"),
                                     ("L", "long")]]
    for r in pen:
        if ra is not None:
            r["ra_outs"], r["ra_runs"] = ra
    return pen


def test_model_bullpen_runs_outcome_and_direction():
    model = registry.load_model("mlb_bullpen", overrides={"num_simulations": 200})
    p = model.params
    base = model.predict({"starter_name": "SP", "starter_stamina": 90, "relievers": _pen()})
    br = base.extras["bullpen_runs"]
    # no history: every rating = prior; equal ratings -> vs usual = 0
    assert all(v == pytest.approx(p.runs_prior_rate) for v in base.extras["ratings"].values())
    assert br["vs_usual"] == pytest.approx(0.0)
    X = br["expected_outs"]
    assert X == pytest.approx(sum(base.extras["expected_outs"].values()))
    assert br["vs_average"] == pytest.approx(p.runs_scale * X * (p.runs_prior_rate - p.runs_league_rate))
    assert br["expected_runs"] == pytest.approx(X * p.runs_league_rate + br["vs_average"])
    lo, hi = br["interval"]
    assert hi - br["expected_runs"] == pytest.approx(p.runs_interval_halfwidth * math.sqrt(X))
    assert lo >= 0.0
    out = base.outcome("Bullpen runs vs average")
    assert out.group == "Bullpen Runs" and out.estimate == pytest.approx(br["vs_average"], abs=0.005)
    # a pen with a good record allows fewer expected runs than average; a bad one more
    good = model.predict({"starter_name": "SP", "starter_stamina": 90, "relievers": _pen((600, 60))})
    bad = model.predict({"starter_name": "SP", "starter_stamina": 90, "relievers": _pen((600, 180))})
    assert good.extras["bullpen_runs"]["vs_average"] < 0 < bad.extras["bullpen_runs"]["vs_average"]
    # the primary outcome is unchanged (most likely reliever)
    assert base.primary.label.startswith("Most likely to pitch")
    assert "| RA9" in base.outcome("C (RHP)").note


def test_bullpen_runs_vs_usual_tracks_availability():
    """A good arm who usually pitches a lot but is exhausted today -> worse than usual."""
    model = registry.load_model("mlb_bullpen", overrides={"num_simulations": 200})
    pen = _pen((300, 57))
    pen[0].update(ra_outs=600, ra_runs=30, outs=60)  # the best arm, usually the most used
    rested = model.predict({"starter_name": "SP", "starter_stamina": 90, "relievers": pen})
    pen[0]["pitches_days"] = [30, 30, 0, 0, 0]  # unavailable today
    tired = model.predict({"starter_name": "SP", "starter_stamina": 90, "relievers": pen})
    assert tired.extras["bullpen_runs"]["vs_usual"] > rested.extras["bullpen_runs"]["vs_usual"]
    assert tired.extras["bullpen_runs"]["vs_usual"] > 0


def test_bullpen_runs_bad_inputs():
    model = registry.load_model("mlb_bullpen", overrides={"num_simulations": 50})
    for bad in ({"ra_outs": -3}, {"ra_runs": "lots"}):
        pen = _pen()
        pen[0].update(bad)
        with pytest.raises(ValueError):
            model.predict({"starter_name": "SP", "relievers": pen})


def test_runs_on_mound_attribution():
    from ballmonitor.models.mlb_bullpen.fetch import _runs_on_mound

    def play(top, pitcher, away, home):
        return {"about": {"isTopInning": top, "inning": 1}, "matchup": {"pitcher": {"id": pitcher}},
                "result": {"awayScore": away, "homeScore": home}}

    pbp = {"allPlays": [
        play(True, 1, 0, 0), play(True, 1, 2, 0),   # home starter 1 allows 2
        play(False, 9, 2, 1),                       # away pitcher 9 allows 1
        play(True, 2, 2, 1), play(True, 2, 3, 1),   # home reliever 2 allows 1
    ]}
    home = _runs_on_mound(pbp, "home")
    assert home[1] == [2, 2] and home[2] == [2, 1]
    assert _runs_on_mound(pbp, "away")[9] == [1, 1]


def test_rating_inputs_use_earlier_games_only():
    """fetch.py: ra_outs / ra_runs = sum of the reliever's relief lines in EARLIER games
    (pitcher_lines.csv.gz order), and the team's season-to-date bullpen line likewise."""
    import json
    from collections import defaultdict
    from pathlib import Path

    from ballmonitor.models.mlb_bullpen.fetch import read_csv_gz

    data = Path(__file__).resolve().parent / "data"
    if not (data / "pitcher_lines.csv.gz").exists() or not (data / "games.csv.gz").exists():
        pytest.skip("data not built")
    lines = read_csv_gz(data / "pitcher_lines.csv.gz")
    games = read_csv_gz(data / "games.csv.gz")
    first_seq = {}
    ids_by_name = defaultdict(set)
    for ln in lines:
        key = (ln["game_pk"], ln["team"])
        first_seq[key] = min(first_seq.get(key, 10 ** 9), int(ln["seq"]))
        ids_by_name[ln["name"]].add(ln["pitcher_id"])
    checked = 0
    for row in games[::400]:
        start = first_seq[(row["game_pk"], row["team"])]
        team_o = sum(int(ln["outs"]) for ln in lines if ln["team"] == row["team"] and ln["season"] == row["season"]
                     and ln["started"] == "0" and int(ln["seq"]) < start)
        assert int(row["team_bp_outs"]) == team_o
        for rel in json.loads(row["relievers_json"])[:3]:
            ids = ids_by_name.get(rel["name"], set())
            if len(ids) != 1:
                continue
            pid = next(iter(ids))
            prior = [ln for ln in lines if ln["pitcher_id"] == pid and ln["started"] == "0" and int(ln["seq"]) < start]
            assert rel["ra_outs"] == sum(int(ln["outs"]) for ln in prior)
            assert rel["ra_runs"] == sum(int(ln["runs"]) for ln in prior)
            checked += 1
    assert checked > 20


def test_site_page_builds():
    from ballmonitor.core import views
    from ballmonitor.models.mlb_bullpen import site

    p = site.page(registry.load_model("mlb_bullpen"))
    assert views.check(p) == []
    assert len(p["views"][0]["options"]) == 30
