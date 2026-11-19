"""Public page: a weigh-in log and planner that runs in the visitor's browser, plus what a steady
calorie cut does over time for two illustrative (made-up) adults.

The planner (web/static/apps/weight_loss.js) is a copy of model.py's daily simulation, adherence
fit, bands and goal search, fed the model's parameters from here at build time;
tests/test_weight_loss_app.py runs it under node against model.predict. The visitor's log stays in
their browser (localStorage key below); nothing is uploaded. No real person's data is on the page.
"""

from __future__ import annotations

import datetime as dt

from ballmonitor.core import views as V
from ballmonitor.core.stats import z_for_level
from ballmonitor.models.weight_loss.model import CM_PER_INCH, DAYS_PER_WEEK, HEADLINE_LEVEL, KG_PER_LB, LEVELS

STORAGE_KEY = "bm.log.weight_loss.v1"

# The JS copies these config formulas by hand; if config.toml's expression changes, the build stops
# here until apps/weight_loss.js is updated (and tests/test_weight_loss_app.py checks the numbers).
COPIED_FORMULAS = {
    "rmr": "9.99 * weight + 6.25 * height_cm - 4.92 * age + (5 if male else -161)",
    "initial_fat": "weight / 100 * (0.14 * age + (37.31 * log(weight / height_m ** 2) - 103.94 if male "
                   "else 39.96 * log(weight / height_m ** 2) - 102.01))",
    "energy_partition": "forbes_c_kg * rho_lean / rho_fat / (forbes_c_kg * rho_lean / rho_fat + fat)",
    "activity_coefficient": "((1 - beta_tef) * pal - 1) * rmr / weight",
}

MODEL_PARAMS = (
    "rho_fat", "rho_lean", "rho_glycogen", "gamma_fat", "gamma_lean", "eta_fat", "eta_lean", "beta_tef",
    "beta_at", "tau_at_days", "forbes_c_kg", "glycogen_init_kg", "glycogen_water_ratio",
    "baseline_carb_fraction", "sodium_conc", "xi_na", "xi_ci", "pal_sedentary", "pal_active", "pal_vigorous",
    "adherence_mean", "adherence_sd", "intake_sd_floor", "weighin_sd_kg", "fit_iterations", "fit_step_kcal",
    "goal_iterations", "goal_tolerance_kg", "max_horizon_days", "min_age", "trajectory_max_rows",
    "steps_per_day", "site_min_weight_kg", "site_max_weight_kg", "site_default_weeks",
)

# Placeholder starting values for the planner (not a real person): replaced by the visitor's own.
EXAMPLE_SETTINGS = {"units": "lb", "sex": "F", "age": 40, "height_cm": 165.1, "start_weight": 180,
                    "body_fat_pct": None, "activity": "sedentary", "intake_change": -500,
                    "activity_change_pct": 0, "goal_weight": 165}

# Illustrative adults for the static table (made up, typical US sizes; not real people).
ILLUSTRATIVE = (
    ("Men", {"sex": "M", "age": 40, "height_cm": 177.8, "weight": 220, "units": "lb"},
     "a 40-year-old man, 5 ft 10 in, 220 lb"),
    ("Women", {"sex": "F", "age": 40, "height_cm": 162.6, "weight": 180, "units": "lb"},
     "a 40-year-old woman, 5 ft 4 in, 180 lb"),
)
CUTS = (250, 500, 750)
HORIZONS = (("m3", "3 months", 91), ("m6", "6 months", 182), ("y1", "1 year", 365), ("y3", "3 years", 1095))
TABLE_START = "2026-01-05"  # any date: the model has no seasons


def app_data(model) -> dict:
    """Everything the planner needs, read from the config so a parameter tweak reaches the page."""
    p = model.params
    if p.method != "hall2011":
        raise ValueError("the weight loss planner copies the hall2011 method; method is " + str(p.method))
    for name, expr in COPIED_FORMULAS.items():
        if " ".join(p.expr(name).split()) != expr:
            raise ValueError(f"formula {name} changed in config.toml; update web/static/apps/weight_loss.js "
                             f"and site.COPIED_FORMULAS to match")
    return {
        "model": "weight_loss",
        "storage_key": STORAGE_KEY,
        "params": {k: p[k] for k in MODEL_PARAMS},
        "levels": list(LEVELS),
        "z": {str(level): z_for_level(level) for level in LEVELS},
        "headline_level": HEADLINE_LEVEL,
        "kg_per_lb": KG_PER_LB,
        "cm_per_inch": CM_PER_INCH,
        "days_per_week": DAYS_PER_WEEK,
        "example": EXAMPLE_SETTINGS,
    }


def _lb(kg: float) -> float:
    return kg / KG_PER_LB


def page(model) -> dict:
    options, answers = [], {}
    for label, person, words in ILLUSTRATIVE:
        rows = []
        for cut in CUTS:
            longest = max(d for _, _, d in HORIZONS)
            end = model.predict({**person, "activity": "sedentary", "intake_change": -cut,
                                 "start_date": TABLE_START, "target_date": _plus(TABLE_START, longest)})
            traj = end.extras["trajectory_kg"]
            w0 = traj[0]
            row = {"cut": f"{cut} fewer a day"}
            for key, _, days in HORIZONS:
                row[key] = round(_lb(w0 - traj[days]), 1)
            row["eventual"] = round(_lb(-end.extras["eventual_change_kg"]), 1)
            rows.append(row)
            if cut == 500:
                answers[label] = (row["y1"], row["eventual"])
        tbl = V.table(
            f"steady_cut_{label.lower()}", f"A steady calorie cut, month by month ({label.lower()})",
            [V.col("cut", "Calories"), *[V.col(k, name, "number", decimals=1) for k, name, _ in HORIZONS],
             V.col("eventual", "In the long run", "number", decimals=1)],
            rows,
            subtitle=f"Pounds lost (most likely) by {words}, sedentary, who keeps eating this many fewer "
                     "calories a day than before.",
            note="Illustrative person, not a real one. Weight loss slows down as the body gets smaller "
                 "and burns less, so most of it comes in the first year or two.")
        y1, ev = answers[label]
        options.append(V.option(label, [tbl], intro=f"500 fewer calories a day: about {y1:.0f} lb in a year "
                                                    f"and {ev:.0f} lb in the long run for {words}."))

    planner = V.app(
        "planner", "Your weigh-ins and plan", "weight_loss", app_data(model),
        subtitle="Fill in your details and plan, then log your weigh-ins as you go. You see where your weight "
                 "is heading by your target date, how much to eat to reach your goal, and, once you have "
                 "weigh-ins, how much of your planned change you are actually making.",
        note="Not medical advice, and not tested against real people's weigh-ins yet: the ranges are "
             "educated guesses. Talk to a doctor before a big diet change.")

    (m1, me), (w1, we) = answers["Men"], answers["Women"]
    return V.page(
        title="Weight loss planner",
        headline=(f"Eating 500 fewer calories a day takes off about {w1:.0f} lb in the first year for a typical "
                  f"180 lb woman ({m1:.0f} lb for a 220 lb man), about half of what it does in the long run."),
        summary="Log your weigh-ins and see where your weight is heading, how much to eat to reach a goal by a "
                "date, and how well your plan is really going. Your log stays in your browser.",
        sport="More sports",
        updated="Uses the NIH body weight model (Hall et al., 2011)",
        how=("The planner follows the body day by day with a published model of how fat, muscle, water and "
             "the calories you burn change when you eat less or move more (Hall et al., The Lancet, 2011). "
             "The ranges allow for how hard plans are to stick to and for day-to-day swings on the scale; "
             "with your own weigh-ins it works out how much of the planned change you are really making. "
             "It has not been tested against real people's weigh-ins yet, and it is not medical advice."),
        views=[planner, V.picker("steady_cut", "What a steady cut does", "Person", options)],
    )


def _plus(iso: str, days: int) -> str:
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=days)).isoformat()
