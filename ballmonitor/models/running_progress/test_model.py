import csv
import datetime as dt
import math

import pytest

from ballmonitor.core import registry
from ballmonitor.models.running_progress import features

NAME = "running_progress"
NO_SEASON = {f"season_{w}_m{m:02d}": 0.0 for w in ("pace", "km") for m in range(1, 13)}


def model(variant=None, **overrides):
    return registry.load_model(NAME, variant, overrides)


def steady(weeks=20, km=40.0, pace_min=5.5, **extra):
    """A runner who runs exactly the same every week."""
    return {"today": "2026-06-01", "weeks_ahead": 8, "weekly_km": [km] * weeks,
            "weekly_minutes": [km * pace_min] * weeks, **extra}


def test_steady_runner_hand_calculation():
    """Identical weeks -> every trend is 0; with the season switched off and ref_pace at the
    runner's pace, ln(median pace) = ln(330 s/km) + pace_loc_a + scale * pace_z_p50."""
    m = model(ref_pace=330.0, **NO_SEASON)
    p = m.params
    pred = m.predict(steady(pace_min=5.5))
    f = pred.extras["features"]
    assert f["tr_recent"] == pytest.approx(0) and f["tr_long"] == pytest.approx(0)
    assert f["share"] == 1.0 and f["since"] == 0
    scale = math.exp(p.pace_scale_a + p.pace_scale_h * math.log(8 / 4) + p.pace_scale_share * 1.0)
    expected = math.exp(math.log(330.0) + p.pace_loc_a + scale * p.pace_z_p50)
    assert pred.primary.estimate == pytest.approx(expected, rel=1e-9)
    km_scale = math.exp(p.km_scale_a + p.km_scale_h * math.log(2) + p.km_scale_share
                        + p.km_scale_rel * (math.log(41) - math.log(p.ref_km + 1)))
    km_loc = math.log(41) + p.km_loc_a + p.km_loc_share + p.km_loc_rel * (math.log(41) - math.log(p.ref_km + 1))
    assert pred.outcome("Weekly km, if training").estimate == pytest.approx(
        math.exp(km_loc + km_scale * p.km_z_p50) - 1, rel=1e-9)


def test_tanda_hand_calculation():
    # K = 40 km/week, P = 330 s/km -> 42.195 * (17.1 + 140 exp(-0.212) + 181.5) s
    pred = model().predict(steady(pace_min=5.5))
    expected = 42.195 * (17.1 + 140.0 * math.exp(-0.0053 * 40) + 0.55 * 330)
    assert pred.outcome("Marathon now (Tanda)").estimate == pytest.approx(expected, rel=1e-9)


def test_bands_are_ordered_and_widen_with_horizon():
    m = model()
    near = m.predict(steady(weeks_ahead=4)).extras["pace_quantiles"]
    far = m.predict(steady(weeks_ahead=26)).extras["pace_quantiles"]
    assert near == sorted(near) and far == sorted(far)
    assert far[6] - far[0] > near[6] - near[0]


def test_recent_speed_up_moves_median_faster():
    base = steady()
    faster = dict(base, weekly_minutes=[40 * 5.5] * 16 + [40 * 5.0] * 4)
    m = model()
    assert m.predict(faster).primary.estimate < m.predict(base).primary.estimate


def test_override_moves_median():
    a = model().predict(steady()).primary.estimate
    p = model().params
    b = model(pace_loc_a=p.pace_loc_a + 0.05).predict(steady()).primary.estimate
    assert b == pytest.approx(a * math.exp(0.05), rel=1e-9)


def test_consistent_runner_more_likely_still_training():
    m = model()
    regular = m.predict(steady())
    patchy = dict(steady(), weekly_km=[40.0, 0.0, 0.0, 0.0] * 5)
    assert m.predict(patchy).extras["p_running"] < regular.extras["p_running"]


def test_daily_log_equals_weekly_totals():
    today = dt.date(2026, 6, 1)
    log = []
    for k in range(12):  # week k before today: three runs
        for d in (1, 3, 5):
            log.append({"date": (today - dt.timedelta(days=7 * k + d)).isoformat(), "km": 10.0, "time": "55:00"})
    a = model().predict({"today": today.isoformat(), "weeks_ahead": 8, "log": log})
    b = model().predict({"today": today.isoformat(), "weeks_ahead": 8,
                         "weekly_km": [30.0] * 12, "weekly_minutes": [165.0] * 12})
    assert a.extras["pace_quantiles"] == pytest.approx(b.extras["pace_quantiles"])
    assert a.extras["p_running"] == pytest.approx(b.extras["p_running"])


def test_miles_and_target_date():
    today = dt.date(2026, 6, 1)
    log = [{"date": (today - dt.timedelta(days=7 * k + 2)).isoformat(), "miles": 10.0, "minutes": 90}
           for k in range(12)]
    pred = model().predict({"today": today, "target_date": today + dt.timedelta(weeks=10), "log": log})
    assert pred.extras["horizon_weeks"] == pytest.approx(10)
    assert pred.outcome("Weekly km now").estimate == pytest.approx(16.09344)


def test_implausible_week_is_dropped():
    data = steady()
    data["weekly_km"][-2] = 200.0          # 200 km in 30 min: not running
    data["weekly_minutes"][-2] = 30.0
    pred = model().predict(data)
    assert pred.extras["features"]["missing_weeks"] == 1
    assert pred.extras["features"]["tr_recent"] == pytest.approx(0)


def test_southern_hemisphere_shifts_season():
    m = model()
    north = m.predict(steady(hemisphere="north")).extras["season_km"]
    south = m.predict(steady(country="Australia")).extras["season_km"]
    assert north != pytest.approx(south)


def test_refuses_too_little_running_and_bad_horizon():
    with pytest.raises(ValueError, match="min_run_weeks"):
        model().predict(dict(steady(), weekly_km=[0.0] * 18 + [10.0, 10.0]))
    with pytest.raises(ValueError, match="weeks after today"):
        model().predict(steady(weeks_ahead=2))
    with pytest.raises(ValueError, match="weeks after today"):
        model().predict(steady(weeks_ahead=40))


def test_persistence_variant_keeps_base_pace():
    pred = model("persistence").predict(dict(steady(), weekly_minutes=[40 * 5.5] * 16 + [40 * 5.0] * 4))
    p = model("persistence").params
    base = (40 * 5.5 * 8 + 40 * 5.0 * 4) * 60 / (40 * 12)
    scale = math.exp(p.pace_scale_a + p.pace_scale_h * math.log(2))
    assert pred.primary.estimate == pytest.approx(base * math.exp(scale * p.pace_z_p50), rel=1e-9)


def test_backtest_rows_score():
    m = model()
    path = m.dir / "data" / "backtest.csv"
    rows = list(csv.DictReader(open(path)))[:20]
    assert {r["split"] for r in csv.DictReader(open(path))} == {"pre2020", "covid", "new19"}
    for row in rows:
        inputs, actual = m.backtest_case(row)
        scores = m.score(m.predict(inputs), actual)
        assert 0 <= scores["brier_running"] <= 1
        if actual["running"]:
            assert scores["abs_pct_error"] >= 0


def test_parse_minutes():
    assert features.parse_minutes("1:02:30") == pytest.approx(62.5)
    assert features.parse_minutes("45:30") == pytest.approx(45.5)
    assert features.parse_minutes(40) == 40.0
