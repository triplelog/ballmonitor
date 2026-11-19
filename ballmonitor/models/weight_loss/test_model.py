import math

import pytest

from ballmonitor.core import registry

BASE = {
    "sex": "M", "age": 40, "height_cm": 180, "weight": 100, "units": "kg",
    "activity": "sedentary", "intake_change": -500,
    "start_date": "2026-01-05", "target_date": "2027-01-05",
}


def run(inputs=None, variant=None, **overrides):
    return registry.load_model("weight_loss", variant, overrides).predict({**BASE, **(inputs or {})})


def test_mifflin_and_jackson_by_hand():
    pred = run({"intake_change": 0})
    rmr = 9.99 * 100 + 6.25 * 180 - 4.92 * 40 + 5  # Mifflin-St Jeor, men
    assert pred.extras["maintenance_kcal"] == pytest.approx(1.5 * rmr)
    fat = 100 / 100 * (0.14 * 40 + 37.31 * math.log(100 / 1.8 ** 2) - 103.94)  # appendix eq. 4
    assert pred.extras["fat0_kg"] == pytest.approx(fat)


def test_zero_energy_balance_keeps_weight():
    pred = run({"intake_change": 0, "target_date": "2029-01-05"})
    assert pred.extras["weight_kg"] == pytest.approx(100.0, abs=1e-6)
    assert max(abs(w - 100) for w in pred.extras["trajectory_kg"]) < 1e-6


def test_500_kcal_cut_matches_hall_2011_time_course():
    """Hall et al. 2011 (Lancet 378:826), summary: for an average overweight adult,
    ~10 kcal/day per lb (100 kJ/day per kg) of eventual change; about half reached in ~1 year
    and ~95% in ~3 years."""
    pred = run({"target_date": "2034-01-05"})  # 8 years: essentially steady state
    traj = pred.extras["trajectory_kg"]
    final = traj[-1] - 100
    rule_of_thumb = -500 / 10 * 0.45359237  # 50 lb = 22.7 kg
    assert final == pytest.approx(rule_of_thumb, rel=0.2)
    assert 0.4 < (traj[365] - 100) / final < 0.65
    assert (traj[3 * 365] - 100) / final > 0.85
    assert pred.extras["tau_days"] == pytest.approx(365, rel=0.5)


def test_linear_variant_close_to_full_model():
    full = run()
    lin = run(variant="linear")
    assert lin.extras["weight_kg"] == pytest.approx(full.extras["weight_kg"], abs=1.5)
    # early on the full model drops faster (glycogen and its water, fluid)
    early_full = run({"target_date": "2026-01-19"}).extras["weight_kg"]
    early_lin = run({"target_date": "2026-01-19"}, variant="linear").extras["weight_kg"]
    assert early_full < early_lin


def test_more_activity_more_loss():
    base = run().extras["weight_kg"]
    assert run({"activity_change_pct": 30}).extras["weight_kg"] < base
    assert run({"exercise_kcal": 200}).extras["weight_kg"] < base


def test_bigger_cut_more_loss_and_bands_ordered():
    small = run({"intake_change": -300})
    big = run({"intake_change": -800})
    assert big.extras["weight_kg"] < small.extras["weight_kg"]
    b = big.extras["bands_kg"]
    w = big.extras["weight_kg"]
    assert b["0.95"][0] < b["0.8"][0] < b["0.5"][0] < w < b["0.5"][1] < b["0.8"][1] < b["0.95"][1]


def test_weighins_below_plan_raise_adherence():
    plan = run()
    traj = plan.extras["trajectory_kg"]
    dates = ["2026-02-02", "2026-03-02", "2026-03-30"]
    days = [28, 56, 84]
    behind = [{"date": d, "weight": traj[t] + 1.5} for d, t in zip(dates, days)]
    ahead = [{"date": d, "weight": traj[t] - 1.5} for d, t in zip(dates, days)]
    on_plan = [{"date": d, "weight": traj[t]} for d, t in zip(dates, days)]
    a_behind = run({"weighins": behind}).extras["adherence"]
    a_ahead = run({"weighins": ahead}).extras["adherence"]
    a_on = run({"weighins": on_plan}).extras["adherence"]
    assert a_ahead > a_on > a_behind
    assert a_on == pytest.approx(1.0, abs=0.02)
    assert run({"weighins": ahead}).extras["weight_kg"] < plan.extras["weight_kg"]


def test_weighins_narrow_the_band():
    plan = run()
    traj = plan.extras["trajectory_kg"]
    rows = [{"date": f"2026-{m:02d}-05", "weight": traj[t]} for m, t in ((2, 31), (3, 59), (4, 90), (5, 120))]
    fitted = run({"weighins": rows})
    assert fitted.extras["effective_change_sd"] < plan.extras["effective_change_sd"]


def test_goal_intake_reaches_goal():
    pred = run({"intake_change": 0, "goal_weight": 92})
    assert pred.extras["goal_reached_kg"] == pytest.approx(92, abs=0.05)
    assert pred.extras["goal_intake"] < pred.extras["maintenance_kcal"]
    # holding a lower weight needs less than today's maintenance but more than the dieting intake
    assert pred.extras["goal_intake"] < pred.extras["goal_maintenance_intake"] < pred.extras["maintenance_kcal"]


def test_pounds_and_inches_match_metric():
    metric = run()
    imperial = run({"units": "lb", "weight": 100 / 0.45359237, "height_cm": None, "height_in": 180 / 2.54})
    assert imperial.extras["weight_kg"] == pytest.approx(metric.extras["weight_kg"], abs=1e-6)


def test_measured_body_fat_changes_composition():
    lean = run({"body_fat_pct": 15})
    fat = run({"body_fat_pct": 35})
    # Forbes: a leaner person loses more lean mass, so less eventual weight per kcal (eq. 17)
    # but gets there faster (eq. 16: tau grows with body fat)
    assert abs(lean.extras["eventual_change_kg"]) < abs(fat.extras["eventual_change_kg"])
    assert lean.extras["tau_days"] < fat.extras["tau_days"]
    lean_drop = 100 - lean.extras["weight_kg"]
    lean_fat_drop = lean.extras["fat0_kg"] - lean.extras["fat_kg"]
    fat_fat_drop = fat.extras["fat0_kg"] - fat.extras["fat_kg"]
    assert lean_fat_drop / lean_drop < fat_fat_drop / (100 - fat.extras["weight_kg"])


@pytest.mark.parametrize("bad, message", [
    ({"sex": "X"}, "sex"),
    ({"age": 12}, "age"),
    ({"weight": -5}, "weight"),
    ({"target_date": "2025-12-01"}, "after start_date"),
    ({"target_date": "2045-01-01"}, "more than"),
    ({"start_date": "soon"}, "YYYY-MM-DD"),
    ({"units": "stone"}, "units"),
    ({"activity": "couch"}, "activity"),
    ({"intake_change": -5000}, "no food"),
    ({"body_fat_pct": 120}, "body_fat_pct"),
    ({"weighins": [{"date": "2025-12-25", "weight": 101}]}, "before start_date"),
    ({"age": "forty"}, "number"),
])
def test_bad_inputs_raise(bad, message):
    with pytest.raises(ValueError, match=message):
        run(bad)


def test_missing_height_raises():
    with pytest.raises(ValueError, match="height"):
        registry.load_model("weight_loss").predict({k: v for k, v in BASE.items() if k != "height_cm"})
