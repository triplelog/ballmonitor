import math

import pytest

from ballmonitor.core import registry
from ballmonitor.core.backtest import load_rows, run_backtest

NAME = "strength_progress"


def run(inputs, variant=None, **overrides):
    return registry.load_model(NAME, variant, overrides).predict(inputs)


def weekly_log(weeks, weight=100.0, reps=5, exercise="Squat", start="2026-01-05", step=0.0):
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return [{"date": d0 + dt.timedelta(days=7 * i), "exercise": exercise,
             "weight": weight + step * i, "reps": reps} for i in range(weeks)]


def base_inputs(**kw):
    inputs = {"log": weekly_log(9), "target_date": "2026-08-31"}  # today = 2026-03-02, 26 weeks
    inputs.update(kw)
    return inputs


def test_hand_calculated_gain():
    pred = run(base_inputs())
    p = registry.load_model(NAME).params
    ex = pred.extras["exercises"]["Squat"]
    assert ex["weeks"] == pytest.approx(8.0)
    assert pred.extras["horizon_weeks"] == pytest.approx(26.0)
    expected = p.gain_max * (math.exp(-8 / p.gain_tau_weeks) - math.exp(-34 / p.gain_tau_weeks))
    assert ex["gain"] == pytest.approx(expected, rel=1e-6)
    # Epley: 100 x 5 -> 100 * (1 + 5/30); output converted back to weight at 5 reps
    assert ex["current"] == pytest.approx(100 * (1 + 5 / 30))
    q50 = ex["log_quantiles"][3]
    assert pred.primary.estimate == pytest.approx(100 * math.exp(expected + q50), rel=1e-6)


def test_bands_are_ordered_and_nested():
    pred = run(base_inputs())
    b = pred.extras["exercises"]["Squat"]["bands"]
    lo50, hi50 = b["0.5"]
    lo80, hi80 = b["0.8"]
    lo95, hi95 = b["0.95"]
    assert lo95 <= lo80 <= lo50 <= pred.primary.estimate <= hi50 <= hi80 <= hi95
    assert pred.primary.interval == pytest.approx((lo80, hi80))


def test_veteran_gains_less_than_novice():
    novice = run(base_inputs())
    veteran = run(base_inputs(training_since="2023-01-02"))
    assert novice.outcome("Change from today").estimate > 0.05
    assert abs(veteran.outcome("Change from today").estimate) < 0.01


def test_longer_horizon_widens_bands_and_adds_gain():
    short = run(base_inputs(target_date="2026-04-13"))
    long = run(base_inputs(target_date="2027-02-22"))
    width = lambda pr: pr.primary.interval[1] / pr.primary.interval[0]
    assert width(long) > width(short)
    assert long.primary.estimate > short.primary.estimate


def test_irregular_training_and_gaps_widen_bands():
    regular = run(base_inputs())
    sparse = run({"log": weekly_log(9)[::3], "target_date": "2026-08-31", "today": "2026-03-02"})
    width = lambda pr: pr.primary.interval[1] / pr.primary.interval[0]
    assert sparse.extras["exercises"]["Squat"]["freq"] < regular.extras["exercises"]["Squat"]["freq"]
    assert width(sparse) > width(regular)
    gap = run(base_inputs(today="2026-04-13"))  # 6 weeks since the last session
    assert width(gap) > width(run(base_inputs(target_date="2026-10-12", today="2026-04-13",
                                              log=weekly_log(15))))


def test_overrides_move_results():
    base = run(base_inputs()).primary.estimate
    assert run(base_inputs(), gain_max=0.5).primary.estimate > base
    assert run(base_inputs(), gain_max=0.0).primary.estimate < base
    wide = run(base_inputs(), band_scale=2.0).primary.interval
    assert wide[1] - wide[0] > run(base_inputs()).primary.interval[1] - run(base_inputs()).primary.interval[0]


def test_no_gain_variant_keeps_median_at_today():
    pred = run(base_inputs(), "no_gain")
    q50 = pred.extras["exercises"]["Squat"]["log_quantiles"][3]
    assert pred.primary.estimate == pytest.approx(100 * math.exp(q50))


def test_recent_trend_variant_uses_slope():
    log = weekly_log(9, step=2.5)
    pred = run({"log": log, "target_date": "2026-03-30"}, "recent_trend")
    ex = pred.extras["exercises"]["Squat"]
    assert ex["slope"] > 0
    assert ex["gain"] == pytest.approx(ex["slope"] * 4, rel=1e-4)


def test_duration_sets_use_the_load_and_best_set_of_the_day():
    log = [{"date": "2026-01-05", "exercise": "Leg press", "weight": 90, "duration": 120},
           {"date": "2026-01-05", "exercise": "Leg press", "weight": 95, "duration": 100},
           {"date": "2026-01-12", "exercise": "Leg press", "weight": 95, "duration": 110}]
    pred = run({"log": log, "target_date": "2026-02-09"})
    ex = pred.extras["exercises"]["Leg press"]
    assert ex["current"] == pytest.approx(95)
    assert ex["sessions"] == 2
    assert pred.primary.label == "Leg press (110 s)"


def test_exercise_choice_and_other_exercises():
    log = weekly_log(9) + weekly_log(3, weight=60, exercise="Bench")
    pred = run({"log": log, "target_date": "2026-08-31"})
    assert pred.primary.label.startswith("Squat")  # most sessions
    assert any(o.group and o.label.startswith("Bench") for o in pred.outcomes)
    pred = run({"log": log, "target_date": "2026-08-31", "exercise": "Bench"})
    assert pred.primary.label.startswith("Bench")


@pytest.mark.parametrize("bad", [
    {"log": [], "target_date": "2026-08-31"},
    {"log": weekly_log(3), "target_date": "2025-01-01"},
    {"log": weekly_log(3), "target_date": "2030-01-01"},
    {"log": weekly_log(3), "target_date": "2026-08-31", "exercise": "Deadlift"},
    {"log": [{"date": "2026-01-05", "exercise": "Squat", "weight": 100}], "target_date": "2026-08-31"},
    {"log": [{"date": "2026-01-05", "exercise": "Squat", "weight": -5, "reps": 5}], "target_date": "2026-08-31"},
    {"log": weekly_log(3)},
])
def test_bad_inputs_raise(bad):
    with pytest.raises(ValueError):
        run(bad)


def test_horizon_weeks_input():
    a = run({"log": weekly_log(9), "horizon_weeks": 26})
    b = run(base_inputs())
    assert a.primary.estimate == pytest.approx(b.primary.estimate)


def test_backtest_beats_no_change_and_is_calibrated():
    """data/backtest.csv: 5,900+ independent test members (fold A, see RESEARCH.md)."""
    model = registry.load_model(NAME)
    rows = load_rows(model.dir / "data" / "backtest.csv")[:1500]
    res = run_backtest(model, rows)
    base = run_backtest(registry.load_model(NAME, "no_gain"), rows)
    assert res.metrics["abs_log_error_pct"] < base.metrics["abs_log_error_pct"]
    assert 0.74 <= res.metrics["in_80"] <= 0.86
    assert 0.92 <= res.metrics["in_95"] <= 0.98
