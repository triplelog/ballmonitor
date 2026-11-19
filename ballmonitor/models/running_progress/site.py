"""Public page: keep a training log in your browser and see where your running is heading.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views running_progress`). The
main view is the log tool (web/static/apps/running_progress.js): the visitor's runs stay in their
browser (localStorage), and the forecast is a JavaScript copy of model.py's formulas fed the
model's parameters from `log_data`; tests/test_running_progress_app.py checks it against
model.predict. The two tables are made here: a steady example runner (model.predict, no data)
and how the model did on the committed test cases (data/backtest.csv, anonymised BMClab
athletes; no names).
"""

from __future__ import annotations

import csv
import datetime as dt
import math

from ballmonitor.core import views as V
from ballmonitor.models.running_progress.features import KM_PER_MILE, SOUTHERN_COUNTRIES
from ballmonitor.models.running_progress.model import BAND_INDEX, MEDIAN, QUANTILE_KEYS, QUANTILE_LEVELS

STORAGE_KEY = "bm.log.running_progress.v1"
EXAMPLE_HORIZONS = (4, 8, 13, 26)
WINDOW_DAYS = 7


def _f(x) -> float:
    return float(x)


def log_data(model) -> dict:
    """Everything the log tool needs: the model's parameters (read from config.toml, so a tweak
    reaches the page) and the example log."""
    p = model.params
    keys = ("min_pace_min_per_km", "max_pace_min_per_km", "max_week_km", "recent_weeks", "base_weeks",
            "lookback_weeks", "target_weeks", "min_run_weeks", "km_offset", "min_horizon_weeks",
            "max_horizon_weeks", "ref_pace", "ref_km", "tanda_weeks", "marathon_km", "tanda_a", "tanda_b",
            "tanda_k", "tanda_c", "tanda_valid_lo", "tanda_valid_hi")
    data = {k: _f(p[k]) for k in keys}
    for what, loc, scale in (
        ("pace", ("a", "recent", "long", "season", "rel"), ("a", "h", "share", "rel", "trend")),
        ("km", ("a", "recent", "long", "season", "share", "rel"), ("a", "h", "share", "rel", "trend")),
    ):
        data[f"{what}_loc"] = {k: _f(p[f"{what}_loc_{k}"]) for k in loc}
        data[f"{what}_scale"] = {k: _f(p[f"{what}_scale_{k}"]) for k in scale}
        data[f"{what}_z"] = [_f(p[f"{what}_z_{k}"]) for k in QUANTILE_KEYS]
        data[f"season_{what}"] = [_f(p[f"season_{what}_m{m:02d}"]) for m in range(1, 13)]
    data["run"] = {k: _f(p[f"run_{k}"]) for k in ("a", "share", "since", "level", "h")}
    data["levels"] = list(QUANTILE_LEVELS)
    data["bands"] = {str(k): list(v) for k, v in BAND_INDEX.items()}
    data["median"] = MEDIAN
    data["km_per_mile"] = KM_PER_MILE
    data["southern_countries"] = sorted(SOUTHERN_COUNTRIES)
    data["default_weeks_ahead"] = int(p.site_default_weeks_ahead)
    data["storage_key"] = STORAGE_KEY
    data["model"] = model.name
    data["example"] = _example_log(model)
    return data


def _example_log(model) -> dict:
    """The default example: a real anonymised BMClab runner's 26 weekly totals (2019). The tool
    moves the dates so the last week ends yesterday (the season then is today's, not 2019's)."""
    from ballmonitor.core import registry
    ex = registry.load_example(model.name, "default")
    today = ex["today"] if isinstance(ex["today"], dt.date) else dt.date.fromisoformat(str(ex["today"]))
    weeks = []
    for e in ex["log"]:
        d = e["date"] if isinstance(e["date"], dt.date) else dt.date.fromisoformat(str(e["date"]))
        weeks.append({"days_before": (today - d).days, "km": float(e["km"]), "minutes": float(e["minutes"])})
    return {"label": "a real runner's 26 weeks of training from the BMClab dataset (2019)", "weeks": weeks}


def _steady(model, weeks_ahead: int, today: dt.date) -> dict:
    p = model.params
    km, pace = float(p.site_example_km_per_week), float(p.site_example_pace_sec)
    n = int(p.lookback_weeks)
    return model.predict({"today": today, "weeks_ahead": weeks_ahead, "hemisphere": "north",
                          "weekly_km": [km] * n, "weekly_minutes": [km * pace / 60] * n}).extras


def _clock(sec: float) -> str:
    sec = int(round(sec))
    h, m, s = sec // 3600, sec // 60 % 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _test_table(model) -> dict:
    """How the forecast did on runners the model never saw (Jan to early Mar 2020), by horizon."""
    rows_by_h: dict[int, list] = {}
    with open(model.dir / "data" / "backtest.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["split"] != "pre2020":
                continue
            inputs, actual = model.backtest_case(row)
            x = model.predict(inputs).extras
            rows_by_h.setdefault(int(float(row["weeks_ahead"])), []).append((x, actual))
    lo, hi = BAND_INDEX[0.8]
    out = []
    for h in sorted(rows_by_h):
        cases = rows_by_h[h]
        ran = [(x, a) for x, a in cases if a["running"] and a["pace"]]
        miss = sorted(abs(x["pace_quantiles"][MEDIAN] / a["pace"] - 1) for x, a in ran)
        inside = sum(x["pace_quantiles"][lo] <= a["pace"] <= x["pace_quantiles"][hi] for x, a in ran) / len(ran)
        km_in = sum(x["km_quantiles"][lo] <= a["km"] <= x["km_quantiles"][hi] for x, a in ran) / len(ran)
        out.append({"weeks": h, "runners": len(cases), "miss": miss[len(miss) // 2] * 100,
                    "pace_in": inside, "km_in": km_in,
                    "still_pred": sum(x["p_running"] for x, _ in cases) / len(cases),
                    "still_real": sum(a["running"] for _, a in cases) / len(cases)})
    return V.table(
        "test", "How it did on runners it had never seen",
        [V.col("weeks", "Weeks ahead", "int"), V.col("runners", "Runners", "int"),
         V.col("miss", "Typical pace miss (%)", "number", decimals=1),
         V.col("pace_in", "Pace inside the 8-in-10 range", "pct"),
         V.col("km_in", "Weekly distance inside its 8-in-10 range", "pct"),
         V.col("still_pred", "Expected still running", "pct"),
         V.col("still_real", "Actually still running", "pct")],
        out,
        subtitle="Forecasts for January to early March 2020, made from each runner's log before then. "
                 "None of these runners were used to build the model.",
        note="A sample of the test runners (anonymised BMClab/Strava users). The ranges should hold 8 in 10; "
             "the typical miss is the middle one (half the forecasts miss by less).")


def page(model) -> dict:
    p = model.params
    today = dt.date.today()
    pace = float(p.site_example_pace_sec)
    km = float(p.site_example_km_per_week)
    rows = []
    for h in EXAMPLE_HORIZONS:
        x = _steady(model, h, today)
        q, kq = x["pace_quantiles"], x["km_quantiles"]
        lo, hi = BAND_INDEX[0.8]
        rows.append({"weeks": h, "date": (today + dt.timedelta(weeks=h)).strftime("%b %-d"),
                     "pace": q[MEDIAN], "pace_lo": q[lo], "pace_hi": q[hi],
                     "km": round(kq[MEDIAN], 1), "km_range": f"{kq[lo]:.0f} - {kq[hi]:.0f}",
                     "still": x["p_running"]})
    ex = f"{km:g} km a week at {_clock(pace)} per km"
    steady = V.table(
        "steady", f"What to expect: a runner doing {ex}, every week",
        [V.col("weeks", "Weeks ahead", "int"), V.col("date", "Four weeks to"),
         V.col("pace", "Most likely pace / km", "time"), V.col("pace_lo", "8 in 10: from", "time"),
         V.col("pace_hi", "to", "time"), V.col("km", "Km a week", "number", decimals=1),
         V.col("km_range", "8 in 10 (km)"), V.col("still", "Still running", "pct")],
        rows,
        subtitle="The further ahead, the wider the range: plans change, injuries happen, seasons turn.",
        note="Starting today, northern hemisphere. Pace is the average over all runs (easy runs, workouts and "
             "races together), so it moves with the kind of training as well as with fitness.")
    r13 = next(r for r in rows if r["weeks"] == 13)

    tool = V.app(
        "log", "Your training log and forecast", "running_progress", log_data(model),
        subtitle="Add your runs (or weekly totals), or import them from Strava, Garmin or a spreadsheet. "
                 "Pick a date up to 26 weeks ahead to see your likely pace and weekly distance then.",
        note="Your log is saved only in this browser. Nothing is uploaded.")

    headline = (f"A steady runner doing {ex} is most likely at about {_clock(r13['pace'])} per km "
                f"13 weeks from now; 8 in 10 land between {_clock(r13['pace_lo'])} and {_clock(r13['pace_hi'])}.")
    return V.page(
        title="Running progress",
        headline=headline,
        summary="Keep a running log in your browser and see where your pace and weekly distance are heading.",
        sport="Running",
        updated="Model built from 2019 training logs, tested on early 2020",
        how=("The forecast starts from your last 12 weeks, leans a little toward your last 4 and back toward "
             "your last 6 months, and adjusts for the time of year. The ranges come from the real ups and downs "
             "of about 36,000 Strava runners who had run a big-city marathon, in 2019; it was checked on "
             "other runners in early 2020, before the pandemic changed everyone's training. It knows only "
             "distance and time, not heart rate or races, and the marathon time is a published formula we "
             "could not check."),
        views=[tool, steady, _test_table(model)],
    )
