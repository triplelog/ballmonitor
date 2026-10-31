"""Tests for the race_time model (v0.5.0: weighted Riegel + empirical bands; curve method)."""

import csv
import json
import math
from pathlib import Path

import pytest

from ballmonitor.core import registry
from ballmonitor.core.units import parse_time
from ballmonitor.models.race_time.bands import (
    QUANTILE_KEYS,
    QUANTILE_LEVELS,
    interval_at,
    normal_log_quantiles,
    time_at_level,
)

MODEL_DIR = Path(__file__).resolve().parent
HALF, MARATHON = 21097.5, 42195.0


@pytest.fixture
def model():
    return registry.load_model("race_time")


def curve_model(**overrides):
    return registry.load_model("race_time", overrides={"method": "curve", **overrides})


def coef(p, key):
    return [p[f"band_{key}_{f}"] for f in ("base", "gap", "years", "races")]


def log_q(p, key, gap, years, races):
    a, bg, by, br = coef(p, key)
    return a + bg * gap + by * min(years, p.band_max_years) + br / min(races, p.band_max_races)


# ── weighted Riegel (default) ──────────────────────────────────────────────

def test_hand_calculated_weighted_riegel(model):
    """5K 20:00 (2024) + half 1:33:00 (2025) -> marathon in 2025, man (b = 1.09)."""
    pred = model.predict({
        "races": [{"distance": "5k", "time": "20:00", "year": 2024},
                  {"distance": "half", "time": "1:33:00", "year": 2025}],
        "target": "marathon", "gender": "M", "target_year": 2025,
    })
    p = model.params
    b = p.riegel_exponent + p.exponent_offset_male
    assert b == pytest.approx(1.09)
    x1, x2 = math.log(MARATHON / 5000), math.log(MARATHON / HALF)
    t1, t2 = 1200 * (MARATHON / 5000) ** b, 5580 * (MARATHON / HALF) ** b
    w1 = math.exp(-x1 / p.race_weight_distance_scale) * 0.5 ** (1 / p.race_weight_half_life_years)
    w2 = math.exp(-x2 / p.race_weight_distance_scale)
    point = math.exp((w1 * math.log(t1) + w2 * math.log(t2)) / (w1 + w2))
    gap = (w1 * x1 + w2 * x2) / (w1 + w2)
    median = point * math.exp(log_q(p, "p50", gap, 0.0, 2))
    assert pred.extras["exponent"] == pytest.approx(b)
    assert pred.extras["gap"] == pytest.approx(gap)
    assert pred.primary.estimate == pytest.approx(median, rel=1e-9)
    used = pred.extras["races_used"]
    assert [u["weight"] for u in used] == pytest.approx([w1 / (w1 + w2), w2 / (w1 + w2)], abs=1e-4)
    assert used[0]["implied_target_sec"] == pytest.approx(t1, abs=0.1)
    # 80% interval = 10% / 90% quantiles around the median
    lo, hi = pred.primary.interval
    q10, q90, q50 = (log_q(p, k, gap, 0.0, 2) for k in ("p10", "p90", "p50"))
    assert lo == pytest.approx(median * math.exp(q10 - q50), rel=1e-9)
    assert hi == pytest.approx(median * math.exp(q90 - q50), rel=1e-9)


def test_one_race_is_plain_riegel_times_median_shift(model):
    pred = model.predict({"races": [{"distance": "5k", "time": "20:00"}], "target": "10k"})
    p = model.params
    point = 1200 * 2 ** p.riegel_exponent  # gender not given -> riegel_exponent
    shift = log_q(p, "p50", math.log(2), 0.0, 1)
    assert pred.primary.estimate == pytest.approx(point * math.exp(shift), rel=1e-9)
    assert pred.extras["races_used"][0]["weight"] == 1.0


def test_gender_exponent(model):
    race = {"races": [{"distance": "5k", "time": "20:00"}], "target": "marathon"}
    p = model.params
    assert model.predict({**race, "gender": "M"}).extras["exponent"] == pytest.approx(1.09)
    assert model.predict({**race, "gender": "F"}).extras["exponent"] == pytest.approx(1.06)
    assert model.predict(race).extras["exponent"] == pytest.approx(p.riegel_exponent)
    # up in distance: a lower exponent (women) means a faster marathon
    assert (model.predict({**race, "gender": "F"}).primary.estimate
            < model.predict({**race, "gender": "M"}).primary.estimate)


def test_weights_favour_near_and_recent_races(model):
    base = {"target": "10k", "target_year": 2025}
    pred = model.predict({**base, "races": [
        {"distance": "10k", "time": "45:00", "year": 2025},
        {"distance": "marathon", "time": "3:30:00", "year": 2025},
        {"distance": "10k", "time": "42:00", "year": 2022},
    ]})
    w = [u["weight"] for u in pred.extras["races_used"]]
    assert sum(w) == pytest.approx(1.0, abs=1e-3)
    assert w[0] > w[1]  # same distance beats a marathon
    assert w[0] > w[2]  # recent beats 3 years old
    assert w[0] / w[2] == pytest.approx(8.0, rel=1e-3)  # 3 half-lives


def test_overrides_move_results(model):
    race = {"races": [{"distance": "5k", "time": "20:00"}], "target": "marathon"}
    base = model.predict(race)
    steeper = registry.load_model("race_time", overrides={"riegel_exponent": 1.10}).predict(race)
    assert steeper.primary.estimate > base.primary.estimate
    wide = registry.load_model("race_time", overrides={"band_scale": 2.0}).predict(race)
    narrow = registry.load_model("race_time", overrides={"band_scale": 0.5}).predict(race)
    width = lambda pr: pr.primary.interval[1] - pr.primary.interval[0]  # noqa: E731
    assert width(narrow) < width(base) < width(wide)
    assert wide.primary.estimate == pytest.approx(base.primary.estimate)


def test_predict_override_is_the_median():
    m = registry.load_model("race_time", overrides={"formulas.predict": "t * D / d"})
    pred = m.predict({"races": [{"distance": "5k", "time": "20:00"}], "target": "10k"})
    assert pred.primary.estimate == pytest.approx(2400)
    lo, hi = pred.primary.interval
    assert lo < 2400 < hi


def test_more_races_and_recent_races_tighten_bands(model):
    one = model.predict({"races": [{"distance": "half", "time": "1:40:00", "year": 2025}],
                         "target": "half", "target_year": 2025})
    three = model.predict({"races": [{"distance": "half", "time": "1:40:00", "year": 2025}] * 3,
                           "target": "half", "target_year": 2025})
    old = model.predict({"races": [{"distance": "half", "time": "1:40:00", "year": 2022}],
                         "target": "half", "target_year": 2025})
    q = lambda pr: pr.extras["_target_quantiles_sec"]  # noqa: E731
    assert q(three)[0] > q(one)[0]   # fewer surprise fast days with more races
    assert q(old)[-1] > q(one)[-1]   # more room to be slower after a 3-year gap


# ── bands: lookup, interpolation, ordering ─────────────────────────────────

def test_quantile_interpolation():
    times = [80.0, 90.0, 95.0, 100.0, 106.0, 115.0, 130.0]
    for t, lv in zip(times, QUANTILE_LEVELS):
        assert time_at_level(times, lv) == pytest.approx(t)
    assert interval_at(times, 0.8) == pytest.approx((90.0, 115.0))
    assert interval_at(times, 0.5) == pytest.approx((95.0, 106.0))
    assert interval_at(times, 0.95) == pytest.approx((80.0, 130.0))
    lo, hi = interval_at(times, 0.9)
    assert 80.0 < lo < 90.0 and 115.0 < hi < 130.0
    lo99, hi99 = interval_at(times, 0.99)  # linear extrapolation in z beyond 97.5%
    assert lo99 < 80.0 and hi99 > 130.0
    # normal log quantiles -> any level is the log-normal interval
    sig = 10.0
    nt = [100 * math.exp(q) for q in normal_log_quantiles(sig)]
    lo, hi = interval_at(nt, 0.9)
    assert math.log(hi / 100) == pytest.approx(1.6448536 * sig / 100, rel=1e-6)


@pytest.mark.parametrize("example", ["default", "one_race", "three_races", "hot_and_hilly",
                                     "fitness_drift", "female_half", "masters_profile"])
@pytest.mark.parametrize("method", ["weighted_riegel", "curve"])
def test_band_ordering_and_monotone_curve(example, method):
    m = registry.load_model("race_time", overrides={"method": method})
    pred = m.predict(registry.load_example("race_time", example))
    keys = [f"{k}_sec" for k in QUANTILE_KEYS]
    for pt in pred.extras["curve_points"] + pred.extras["benchmarks"]:
        vals = [pt[k] for k in keys]
        assert vals == sorted(vals)
        assert pt["estimate_sec"] == pt["p50_sec"]
    for pt in pred.extras["curve_points"]:
        assert (pt["lo_95_sec"] <= pt["lo_80_sec"] <= pt["lo_50_sec"] <= pt["estimate_sec"]
                <= pt["hi_50_sec"] <= pt["hi_80_sec"] <= pt["hi_95_sec"])
        assert pt["lo_80_sec"] == pt["p10_sec"] and pt["hi_80_sec"] == pt["p90_sec"]
    for key in keys:
        series = [pt[key] for pt in pred.extras["curve_points"]]
        assert series == sorted(series), f"{key} not increasing with distance"
    for o in pred.outcomes:
        if o.interval:
            assert o.interval[0] <= o.estimate <= o.interval[1]


def test_monotone_with_inconsistent_races(model):
    pred = model.predict({"races": [{"distance": "5k", "time": "30:00"},
                                    {"distance": "marathon", "time": "3:00:00"}],
                          "target": "half"})
    p50 = [pt["p50_sec"] for pt in pred.extras["curve_points"]]
    assert p50 == sorted(p50)


# ── output contract ────────────────────────────────────────────────────────

CONTRACT_KEYS = {
    "method", "exponent", "races_used", "band_levels", "curve_points", "benchmarks",
    "runner_points", "target_distance_m", "target_label", "gap", "target_multiplier",
    "target_elevation_gain_m", "target_altitude_m", "target_temp_f",
}


def test_extras_contract(model):
    pred = model.predict(registry.load_example("race_time", "default"))
    public = {k for k in pred.extras if not k.startswith("_")}
    assert public == CONTRACT_KEYS
    ex = pred.extras
    assert ex["method"] == "weighted_riegel" and ex["band_levels"] == [0.5, 0.8, 0.95]
    assert set(ex["races_used"][0]) == {"distance", "distance_label", "time_sec", "time_str",
                                        "date", "year", "weight", "implied_target_sec"}
    cps = ex["curve_points"]
    assert len(cps) == 60
    assert cps[0]["distance"] == pytest.approx(800) and cps[-1]["distance"] == pytest.approx(50000)
    assert set(cps[0]) == {"distance", "distance_label", "pace_mile_sec", "pace_km_sec",
                           "estimate_sec", "lo_50_sec", "hi_50_sec", "lo_80_sec", "hi_80_sec",
                           "lo_95_sec", "hi_95_sec", *(f"{k}_sec" for k in QUANTILE_KEYS)}
    labels = [b["label"] for b in ex["benchmarks"]]
    assert labels == ["Mile", "5K", "8K", "10K", "15K", "10 Mile", "Half Marathon",
                      "Marathon", "50K"]
    assert [b["label"] for b in ex["benchmarks"] if b["common"]] == [
        "Mile", "5K", "10K", "Half Marathon", "Marathon"]
    assert set(ex["benchmarks"][0]) == {
        "label", "distance_meters", "common", *(f"{k}_sec" for k in QUANTILE_KEYS),
        "estimate_sec", "estimate_str", "interval_str", "range50_str", "range95_str",
        "pace_per_mile_sec", "pace_per_mile_str", "pace_per_km_str"}
    assert set(ex["runner_points"][0]) >= {"distance", "distance_label", "time_sec", "time_str",
                                           "year", "pace_per_mile_str"}
    assert ex["target_distance_m"] == MARATHON and ex["target_label"] == "Marathon"
    json.dumps(pred.to_dict())  # serialisable


def test_outcomes_layout(model):
    pred = model.predict(registry.load_example("race_time", "default"))
    labels = [o.label for o in pred.outcomes]
    assert labels[:5] == ["Marathon time", "Target 50% range", "Target 95% range",
                          "Pace per mile", "Pace per km"]
    common = [o for o in pred.outcomes if o.group.startswith("Common distances")]
    assert [o.label for o in common] == ["Mile", "5K", "10K", "Half marathon", "Marathon"]
    assert all("50%:" in o.note and "95%:" in o.note for o in common)
    assert pred.interval_level == 0.8
    assert pred.outcome("Target 50% range").note.startswith("50%: ")


def test_method_switch():
    inputs = registry.load_example("race_time", "three_races")
    wr = registry.load_model("race_time").predict(inputs)
    cv = registry.load_model("race_time", "curve_v04").predict(inputs)
    assert wr.extras["method"] == "weighted_riegel" and "beta1" not in wr.extras
    assert cv.extras["method"] == "curve" and cv.extras["exponent"] == cv.extras["beta1"]
    assert CONTRACT_KEYS <= set(cv.extras)
    assert wr.primary.estimate != cv.primary.estimate


# ── environment (applies to both methods) ──────────────────────────────────

def test_elevation_and_weather_target_adjustment(model):
    base = {"races": [{"distance": "5k", "time": "20:00"}], "target": "10k"}
    flat = model.predict(base)
    hot = model.predict({**base, "target_elevation_gain": "500ft", "target_temp_f": 85.0,
                         "target_humidity_pct": 70.0})
    assert hot.primary.estimate > flat.primary.estimate
    assert hot.extras["target_multiplier"] > 1.0
    neutral = hot.outcome("Flat/neutral equivalent")
    assert neutral.estimate == pytest.approx(flat.primary.estimate)
    ratio = hot.primary.estimate / flat.primary.estimate
    assert hot.primary.interval[1] == pytest.approx(flat.primary.interval[1] * ratio)


def test_input_race_environmental_normalization(model):
    hot = model.predict({"races": [{"distance": "5k", "time": "21:15", "temp_f": 85.0,
                                    "humidity_pct": 70.0}], "target": "marathon"})
    neutral = model.predict({"races": [{"distance": "5k", "time": "21:15", "temp_f": 50.0}],
                             "target": "marathon"})
    assert hot.primary.estimate < neutral.primary.estimate


def test_gpx_course_parsing_and_projection(model):
    pred = model.predict({"races": [{"distance": "5k", "time": "20:00"}], "target": "10k",
                          "target_gpx_path": str(MODEL_DIR / "data" / "sample_course.gpx")})
    assert pred.extras["target_elevation_gain_m"] > 0
    assert pred.extras["target_altitude_m"] > 1500
    assert pred.extras["target_multiplier"] > 1.0
    assert pred.primary.estimate > pred.outcome("Flat/neutral equivalent").estimate


# ── backtest ───────────────────────────────────────────────────────────────

def test_backtest_case_and_band_scores(model):
    row = {
        "scenario": "cross_distance", "split": "test", "gender": "F", "age": "33",
        "race1_distance": "5k", "race1_time": "24:00", "race1_date": "2024-05-01",
        "race1_year": "2024", "race2_distance": "", "race2_time": "", "race2_date": "",
        "race2_year": "", "target": "half", "target_date": "2024-10-01",
        "target_year": "2024", "actual_time": "1:55:00",
    }
    inputs, actual = model.backtest_case(row)
    assert inputs["target_date"] == "2024-10-01"
    assert inputs["races"][0]["date"] == "2024-05-01"
    assert actual == parse_time("1:55:00")
    assert model.backtest_group(row) == "cross_distance / test"
    pred = model.predict(inputs)
    scores = model.score(pred, actual)
    assert {"abs_error", "in_interval", "in_50", "in_80", "in_95"} <= set(scores)
    assert scores["in_50"] <= scores["in_80"] <= scores["in_95"]
    # 5 months before the target -> years feature ~0.42
    assert pred.extras["races_used"][0]["date"] == "2024-05-01"


def test_coverage_sanity_on_test_runners(model):
    with open(MODEL_DIR / "data" / "backtest.csv", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["split"] == "test"][::8]
    hits = {"in_50": 0.0, "in_80": 0.0, "in_95": 0.0}
    for row in rows:
        inputs, actual = model.backtest_case(row)
        s = model.score(model.predict(inputs), actual)
        for k in hits:
            hits[k] += s[k]
    cov = {k: v / len(rows) for k, v in hits.items()}
    assert 0.42 <= cov["in_50"] <= 0.60
    assert 0.73 <= cov["in_80"] <= 0.87
    assert 0.91 <= cov["in_95"] <= 0.99


# ── curve method (v0.4.0) ──────────────────────────────────────────────────

def test_curve_two_races_empirical_bayes_shrinkage():
    m = curve_model()
    endurance = m.predict({"races": [{"distance": "5k", "time": "20:00", "year": 2026},
                                     {"distance": "half", "time": "1:29:00", "year": 2026}],
                           "target": "marathon"})
    speed = m.predict({"races": [{"distance": "5k", "time": "20:00", "year": 2026},
                                 {"distance": "half", "time": "1:38:00", "year": 2026}],
                       "target": "marathon"})
    assert endurance.extras["beta1"] < speed.extras["beta1"]
    assert endurance.primary.estimate < speed.primary.estimate
    assert endurance.extras["shrinkage_weight"] > 0.0


def test_curve_temporal_fitness_drift_improvement():
    pred = curve_model().predict({
        "races": [{"distance": "marathon", "time": "3:30:00", "year": 2024},
                  {"distance": "5k", "time": "22:00", "year": 2024},
                  {"distance": "5k", "time": "19:30", "year": 2026}],
        "target": "marathon", "target_year": 2026,
    })
    assert pred.primary.estimate < parse_time("3:22:00")
    assert pred.extras["fitness_delta_pct"] > 5.0
    assert "Temporal fitness tracking" in " ".join(pred.steps)


def test_curve_hand_calculated_two_race_case():
    m = curve_model(use_demographic_priors=True)
    pred = m.predict({"races": [{"distance": "5k", "time": "20:00", "year": 2025},
                                {"distance": "half", "time": "1:33:00", "year": 2025}],
                      "target": "marathon", "age": 38, "gender": "M"})
    prior = json.loads((MODEL_DIR / "data" / "demographic_priors.json").read_text())["M_35-49"]["beta1"]
    p = m.params
    c = p.marathon_curvature
    x2 = math.log(HALF / 5000.0)
    obs = min(max((math.log(5580 / 1200) - c * x2**2) / x2, p.min_exponent), p.max_exponent)
    span = math.log2(HALF / 5000.0)
    w = span / (span + p.shrinkage_prior_strength) * p.fit_weight
    beta1 = w * obs + (1 - w) * prior
    assert pred.extras["beta1_pop"] == prior
    assert pred.extras["beta1"] == pytest.approx(beta1, abs=1e-9)
    a1, a2 = math.log(1200), math.log(5580) - beta1 * x2 - c * x2**2
    e1, e2 = a1, math.log(5580) - prior * x2 - c * x2**2
    w1 = math.exp(-100 * (e1 - min(e1, e2)) / p.off_day_tolerance_pct)
    w2 = math.exp(-100 * (e2 - min(e1, e2)) / p.off_day_tolerance_pct)
    alpha = (w1 * a1 + w2 * a2) / (w1 + w2)
    X = math.log(MARATHON / 5000.0)
    assert pred.primary.estimate == pytest.approx(math.exp(alpha + beta1 * X + c * X**2), abs=1e-6)


def test_curve_sigma_formula_override_reaches_bands():
    m = curve_model(**{"formulas.sigma_pct": "5.0"})
    pred = m.predict({"races": [{"distance": "5k", "time": "20:00"}], "target": "10k"})
    assert pred.extras["sigma_pct"] == pytest.approx(5.0)
    b = pred.extras["benchmarks"][1]
    assert math.log(b["p90_sec"] / b["p50_sec"]) == pytest.approx(1.2815516 * 0.05, rel=1e-3)


def test_curve_dates_give_fractional_recency():
    m = curve_model()
    base = {"target": "10k", "target_date": "2025-10-01"}
    recent = m.predict({**base, "races": [{"distance": "5k", "time": "20:00", "date": "2025-09-01"}]})
    old = m.predict({**base, "races": [{"distance": "5k", "time": "20:00", "date": "2024-03-01"}]})
    drift = m.params.annual_fitness_drift_pct
    assert recent.extras["temporal_sigma_pct"] == pytest.approx(drift * 30 / 365.25, abs=0.01)
    assert old.extras["sigma_pct"] > recent.extras["sigma_pct"]


# ── input validation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("inputs", [
    {"races": [{"time": "20:00"}]},
    {"races": [{"distance": "5k"}]},
    {"races": [{"distance": 0, "time": "20:00"}]},
    {"races": "5k"},
    {"races": []},
    {"races": [{"distance": "5k", "time": "20:00"}], "gender": "X"},
    {"races": [{"distance": "5k", "time": "20:00"}], "age": "old"},
    {"races": [{"distance": "5k", "time": "20:00"}], "target_gpx_path": "no_such_file.gpx"},
    {"races": [{"distance": "5k", "time": "20:00"}], "target_elevation_gain": "lots"},
    {"races": [{"distance": "5k", "time": "20:00", "date": "May 3"}], "target": "10k"},
])
def test_bad_inputs_raise_value_error(model, inputs):
    with pytest.raises(ValueError):
        model.predict(inputs)
