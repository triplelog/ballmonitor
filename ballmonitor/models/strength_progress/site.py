"""Public page: a workout log kept in the visitor's browser + what it says they'll lift on a
chosen date, and a table of typical progress.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views strength_progress`). The
log tool (web/static/apps/strength_progress.js) is a copy of model.py's default method, fed the
model's parameters from here; tests/test_strength_progress_app.py checks it against
model.predict. The log is stored only in the visitor's browser (localStorage); nothing is sent.
The "typical progress" table is model.predict on placeholder weekly logs (not anyone's data).
"""

from __future__ import annotations

import datetime as dt
from ballmonitor.core import views as V
from ballmonitor.models.strength_progress.progress import BAND_FEATURES, QUANTILE_KEYS, QUANTILE_LEVELS, param_name

KG_PER_LB = 0.45359237  # definition of the pound
# The formulas the browser copy implements; if config.toml's differ, the build stops.
FORMULAS = {
    "rep_index": "weight * (1 + reps / rep_divisor)",
    "duration_index": "weight",
    "pace": "clamp(freq / consistency_ref_per_week, pace_min, pace_max) ** consistency_exponent",
    "expected_gain": "gain_max * (exp(-weeks / gain_tau_weeks) - exp(-(weeks + h * pace) / gain_tau_weeks))",
    "band_log_quantile": "a + b_h * horizon + b_nov * novice + b_irr * irregular + b_gap * gap",
    "median_value": "current * exp(gain + q50)",
    "band_value": "median * exp(band_scale * (q - q50))",
}
TYPICAL_WEEKS = ((0, "Just starting"), (4, "1 month"), (13, "3 months"), (26, "6 months"),
                 (52, "1 year"), (104, "2 years"))
TYPICAL_HORIZONS = (("next3", 13, "Next 3 months"), ("next6", 26, "Next 6 months"), ("next12", 52, "Next year"))
DEFAULT_HORIZON_WEEKS = 26
REF_DATE = dt.date(2026, 1, 5)  # any Monday: the typical table's placeholder logs end here


def app_data(model) -> dict:
    """Everything the log tool needs, read from the config so a tweak reaches the page."""
    p = model.params
    for name, expr in FORMULAS.items():
        if p.expr(name).replace(" ", "") != expr.replace(" ", ""):
            raise ValueError(f"the strength log tool copies formula {name} = {expr!r}; config has {p.expr(name)!r}")
    num = lambda k: float(p[k])
    return {
        "model": model.name,
        "storage_key": f"bm.log.{model.name}.v1",
        "rep_divisor": num("rep_divisor"),
        "window_weeks": num("consistency_window_weeks"),
        "ref_per_week": num("consistency_ref_per_week"),
        "gain_max": num("gain_max"), "tau_weeks": num("gain_tau_weeks"),
        "pace": {"exponent": num("consistency_exponent"), "min": num("pace_min"), "max": num("pace_max")},
        "max_horizon_weeks": num("max_horizon_weeks"),
        "gap_cap_days": num("band_gap_cap_days"),
        "band_scale": num("band_scale"),
        "levels": list(QUANTILE_LEVELS),
        "coef": [[num(param_name(k, f)) for f in BAND_FEATURES] for k in QUANTILE_KEYS],
        "kg_per_lb": KG_PER_LB,
        "default_horizon_weeks": DEFAULT_HORIZON_WEEKS,
    }


def _typical(model, weeks: int, horizon: int) -> tuple[float, float, float]:
    """Median and 80% range of the % change for a placeholder lifter training once a week."""
    log = [{"date": REF_DATE - dt.timedelta(days=7 * i), "exercise": "Lift", "weight": 100.0, "reps": 8}
           for i in range(int(weeks) + 1)]
    pred = model.predict({"log": log, "today": REF_DATE,
                          "target_date": REF_DATE + dt.timedelta(days=7 * horizon)})
    o = pred.outcome("Change from today")
    return o.estimate * 100, o.interval[0] * 100, o.interval[1] * 100


def page(model) -> dict:
    rows = []
    for w, label in TYPICAL_WEEKS:
        row = {"trained": label}
        for key, h, _ in TYPICAL_HORIZONS:
            row[key] = f"{_typical(model, w, h)[0]:+.0f}%"
        mid, lo, hi = _typical(model, w, 26)
        row["range6"] = f"{lo:+.0f}% to {hi:+.0f}%"
        rows.append(row)
    typical = V.table(
        "typical", "Typical progress, training once a week",
        [V.col("trained", "Training so far"),
         *[V.col(k, label, align="num") for k, _, label in TYPICAL_HORIZONS],
         V.col("range6", "8 in 10, next 6 months", align="num")],
        rows,
        subtitle="Most likely change in the weight you lift for the same reps, by how long you've been training.",
        note="From fit20 studio members (one slow set to failure per machine, about once a week). "
             "Bigger programmes may keep gaining for longer.")

    log = V.app(
        "log", "Your training log", "strength_progress", app_data(model),
        subtitle="Add your sets (or import them from Hevy, Strong or a spreadsheet), pick a lift and a date, "
                 "and see what you'll most likely lift then.",
        note="Your log is saved only in this browser. Nothing is uploaded.")

    first6 = _typical(model, 0, 26)[0]
    year = _typical(model, 52, 26)[0]
    headline = (f"A beginner training once a week lifts about {first6:.0f}% more after six months; "
                + ("after a year, most people hold steady." if abs(year) < 1 else
                   f"after a year, the most likely change over the next six months is {year:+.0f}%."))
    return V.page(
        title="Strength progress calculator",
        headline=headline,
        summary="Keep your lifting log in your browser and see how much you'll most likely lift on any date in "
                "the next year.",
        sport="More sports",
        updated="Learned from 2011-2016 fit20 training records",
        how=("Your latest best set is the starting point. Beginners gain fast and the gains slow down: most of "
             "the progress comes in the first six months. The ranges are how real people's later lifts compared "
             "with that forecast, and they widen if you train less than once a week or have had a break. "
             "Everything was learned from one machine-training programme (fit20: one slow set to failure per "
             "machine, about once a week, 2011-2016), so for free weights or bigger programmes treat it as a "
             "rough guide."),
        views=[log, typical],
    )
