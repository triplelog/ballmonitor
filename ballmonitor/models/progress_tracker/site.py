"""Public page: a goal planner and progress log kept in the visitor's browser (any measure: lifts,
pace, race times, chess rating, body weight, body fat %, or their own). The visitor sets a goal, a
goal date and a plan shape (even / faster early / faster late, like a race pacing strategy); the
tool tracks whether they are ahead of or behind the plan and shows the result their current rate
leads to. Plus a table from the study of how newcomers' progress was spread over their first year.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views progress_tracker`). The tool
(web/static/apps/progress_tracker.js) is a copy of model.py's predict, fed the model's parameters
from here; tests/test_progress_tracker_app.py checks it against model.predict. The log is stored
only in the visitor's browser (localStorage); nothing is sent. The table reads data/study.json
(written by research.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import NormalDist

from ballmonitor.core import views as V
from ballmonitor.models.progress_tracker.model import KINDS, PRESETS, SHAPES

STUDY = Path(__file__).resolve().parent / "data" / "study.json"
# The formulas the browser copy implements; if config.toml's differ, the build stops.
FORMULAS = {
    "share_even": "t",
    "share_faster_early": "1 - (1 - t) ** split_strength",
    "share_faster_late": "t ** split_strength",
    "planned": "start + share * (goal - start)",
    "recency_weight": "1 if recency_half_life_weeks <= 0 else 0.5 ** (age_weeks / recency_half_life_weeks)",
    "adherence": "clamp((sxy + prior_weight * m) / (sxx + prior_weight * m), -max_adherence, max_adherence)",
    "predicted": "start + f * (goal - start)",
    "spread": "sqrt(resid_var + (goal - start) ** 2 * f_var)",
    "next_goal_behind": "latest + step + catch_up_share * gap",
}
# Units a visitor can pick per preset (labels only: the model works on ratios or differences).
UNITS = {"chess_rating": ["points"], "lift": ["kg", "lb"], "running_pace": ["min/km", "min/mi"],
         "race_time": ["h:mm:ss"], "body_weight": ["kg", "lb"], "body_fat": ["%"], "custom": []}
KIND_WORDS = {"chess": "Chess rating", "strength": "Weight lifted"}


def _study() -> dict:
    return json.loads(STUDY.read_text())


def front_share(kind: str) -> float:
    """Share of newcomers' first-year change that came in the first 26 weeks (study.json)."""
    n = _study()["kinds"][kind]["newcomers"]
    return n["26"]["mean_change"] / n["52"]["mean_change"]


def app_data(model) -> dict:
    """Everything the tool needs, read from the config so a tweak reaches the page."""
    p = model.params
    for name, expr in FORMULAS.items():
        if p.expr(name).replace(" ", "") != expr.replace(" ", ""):
            raise ValueError(f"the progress tool copies formula {name} = {expr!r}; config has {p.expr(name)!r}")
    return {
        "model": model.name,
        "storage_key": f"bm.log.{model.name}.v1",
        "presets": [{"key": key, "label": label, "kind": kind, "units": UNITS[key], "unit": unit,
                     "direction": direction, "time": fmt == "time", "fmt": fmt}
                    for key, (label, kind, unit, direction, fmt) in PRESETS.items()],
        "scales": {k: str(p[f"scale_{k}"]) for k in KINDS if k != "other"},
        "shapes": list(SHAPES),
        "default_shape": "faster_early",
        "split_strength": float(p.split_strength),
        "prior_weight": float(p.prior_weight),
        "recency_half_life_weeks": float(p.recency_half_life_weeks),
        "max_adherence": float(p.max_adherence),
        "catch_up_share": float(p.catch_up_share), "on_track_tolerance": float(p.on_track_tolerance),
        "max_plan_weeks": float(p.max_plan_weeks),
        "z": NormalDist().inv_cdf(0.5 + float(p.interval_level) / 2),
        "front_share": {k: round(front_share(k), 2) for k in ("strength", "chess")},
    }


def page(model) -> dict:
    st = _study()["kinds"]
    rows = []
    for kind, label in KIND_WORDS.items():
        n = st[kind]["newcomers"]
        unit = (lambda x: f"{x:+.0f} points") if kind == "chess" else (lambda x: f"{x:+.0f}%")
        rows.append({"measure": label, "m3": unit(n["13"]["mean_change"]), "m6": unit(n["26"]["mean_change"]),
                     "m12": unit(n["52"]["mean_change"]), "share": f"{front_share(kind) * 100:.0f}%"})
    newcomers = V.table(
        "newcomers", "How real newcomers progressed",
        [V.col("measure", "Measure"), V.col("m3", "After 3 months", align="num"),
         V.col("m6", "After 6 months", align="num"), V.col("m12", "After 1 year", align="num"),
         V.col("share", "Of the year's gain, by 6 months", align="num")],
        rows,
        subtitle="Average change for people in their first two months of logging, among those still logging later. "
                 "Most of the first year's progress came early: that's why \"faster early\" is the realistic plan.",
        note="Chess: Lichess blitz ratings 2014-2017. Weight lifted: fit20 machine training 2010-2016 (% = 100 x the "
             "log of the ratio). Thousands of people each; see the full method for the details.")

    tool = V.app(
        "log", "Your goal and progress log", "progress_tracker", app_data(model),
        subtitle="Pick what you track, set a goal, a date and a plan (like a race: even, faster early or faster late), "
                 "and log an entry every week or so. You'll see whether you're ahead of or behind your plan and "
                 "where your current rate takes you.",
        note="Your log is saved only in this browser. Nothing is uploaded.")

    fs = front_share("strength")
    headline = (f"Plan for faster early: lifters new to training made {fs * 100:.0f}% of their first year's gain "
                f"in the first six months.")
    return V.page(
        title="Progress tracker",
        headline=headline,
        summary="Set a goal for anything you're trying to improve, from your squat to your chess rating, plan how "
                "to get there, and see where you're heading as you log your progress.",
        sport="More sports",
        updated="Plan shapes from Lichess 2014-2017 and fit20 2010-2016 logs",
        how=("Your plan runs from where you start to your goal by your goal date: evenly, faster early or faster late, "
             "in % for lifts, pace and race times and in points for ratings, body weight and body fat %. Each entry "
             "is compared with what the plan asked for by that day; the share of the planned progress you've made "
             "so far (pulled toward 100% while you have only a few entries) scales the rest of the plan into your "
             "predicted result. It is a motivating guide, not a tested forecast."),
        views=[tool, newcomers],
    )
