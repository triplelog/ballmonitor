"""Strength progress: what will this lifter lift on a future date? See MODEL.md.

Today's strength on the exercise (best set of the last session, as one strength number) is
moved along a saturating training curve in weeks trained (formula `expected_gain`), and
empirical 50/80/95% bands fitted on fit20 members' real errors are put around it
(progress.py, research.py -> RESEARCH.md).
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.models.strength_progress.progress import (
    BAND_LEVELS,
    MEDIAN_INDEX,
    QUANTILE_LEVELS,
    Exercise,
    band_inputs,
    features,
    interval_at,
    log_quantiles,
    parse_date,
    parse_log,
    quantile_values,
)

DAYS_PER_WEEK = 7.0


def _opt_date(value: Any, name: str) -> dt.date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_date(value, name)


def _fmt(x: float) -> str:
    return f"{x:,.1f}".rstrip("0").rstrip(".")


class StrengthProgressModel(BaseModel):
    # ── one exercise ───────────────────────────────────────────────────────

    def _forecast(self, ex: Exercise, today: dt.date, target: dt.date,
                  since: dt.date | None) -> dict[str, Any]:
        p = self.params
        f = features(ex, today, since, p)
        h = (target - today).days / DAYS_PER_WEEK
        pace = p.formula("pace", freq=f.freq)
        gain = p.formula("expected_gain", weeks=f.weeks, h=h, pace=pace, slope=f.slope,
                         sessions=f.n_sessions)
        if not math.isfinite(gain):
            raise ValueError(f"formula 'expected_gain' gave {gain}; check overrides")
        x = band_inputs(f, h, p)
        log_q = log_quantiles(x, p)
        median = p.formula("median_value", current=f.current, gain=gain, q50=log_q[MEDIAN_INDEX])
        if not (median > 0 and math.isfinite(median)):
            raise ValueError(f"formula 'median_value' gave {median}; check overrides")
        values = quantile_values(median, log_q, p)
        last = f.last
        if last.reps is not None:
            factor = p.formula("rep_index", weight=1.0, reps=last.reps)
            usual = f"{_fmt(last.reps)} reps"
        else:
            factor = p.formula("duration_index", weight=1.0, duration=last.duration)
            usual = f"{_fmt(last.duration)} s"
        return dict(f=f, h=h, pace=pace, gain=gain, x=x, log_q=log_q, median=median,
                    values=values, factor=factor, usual=usual)

    # ── predict ────────────────────────────────────────────────────────────

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        exercises = parse_log(inputs.get("log"), p)
        last_logged = max(s.date for ex in exercises.values() for s in ex.sessions)
        today = _opt_date(inputs.get("today"), "today") or last_logged
        target = _opt_date(inputs.get("target_date"), "target_date")
        if target is None:
            if inputs.get("horizon_weeks") in (None, ""):
                raise ValueError("give target_date (e.g. 2026-09-01) or horizon_weeks")
            target = today + dt.timedelta(days=round(float(inputs["horizon_weeks"]) * DAYS_PER_WEEK))
        h = (target - today).days / DAYS_PER_WEEK
        if h <= 0:
            raise ValueError(f"target_date {target} must be after today ({today})")
        if h > p.max_horizon_weeks:
            raise ValueError(f"target is {h:.0f} weeks away; the model was tested up to "
                             f"max_horizon_weeks = {p.max_horizon_weeks:g}")
        since = _opt_date(inputs.get("training_since"), "training_since")
        unit = str(inputs.get("unit") or "kg")

        name = inputs.get("exercise")
        if name:
            if name not in exercises:
                raise ValueError(f"exercise {name!r} is not in the log (have: {', '.join(exercises)})")
        else:
            name = max(exercises, key=lambda n: len(exercises[n].sessions))
        order = [name] + [n for n in exercises if n != name]

        steps: list[str] = []
        outcomes: list[Outcome] = []
        extras: dict[str, Any] = {"today": today.isoformat(), "target_date": target.isoformat(),
                                  "horizon_weeks": round(h, 2), "exercises": {}}
        steps.append(f"Today = {today}, target = {target}: horizon h = {h:.1f} weeks.")
        steps.append(f"Each set -> strength number: reps sets [{p.expr('rep_index')}], "
                     f"timed sets [{p.expr('duration_index')}]; best set per day.")
        for i, ex_name in enumerate(order):
            ex = exercises[ex_name]
            r = self._forecast(ex, today, target, since)
            f, v = r["f"], r["values"]
            w = [q / r["factor"] for q in v]  # weight at the usual reps / duration
            current_w = f.current / r["factor"]
            lo50, hi50 = interval_at(w, 0.5)
            lo80, hi80 = interval_at(w, 0.8)
            lo95, hi95 = interval_at(w, 0.95)
            primary = i == 0
            if primary:
                steps.append(
                    f"{ex_name}: {f.n_sessions} sessions since {f.start}; last {f.last.date} "
                    f"({_fmt(f.last.weight)} {unit} x {r['usual']}) -> strength {f.current:.1f}.")
                steps.append(
                    f"Weeks trained = {f.weeks:.1f}; sessions/week (last "
                    f"{p.consistency_window_weeks:g} weeks) = {f.freq:.2f}; days since last "
                    f"session = {f.days_since_last:.0f}; recent trend {f.slope * 100:+.2f}%/week.")
                steps.append(f"Pace = {r['pace']:.2f} [{p.expr('pace')}].")
                steps.append(
                    f"Expected log gain = {r['gain']:+.4f} ({(math.exp(r['gain']) - 1) * 100:+.1f}%) "
                    f"[{p.expr('expected_gain')}].")
                x = r["x"]
                steps.append(
                    f"Band features: horizon {x['horizon']:.2f}, novice {x['novice']:.2f}, "
                    f"irregular {x['irregular']:.2f}, gap {x['gap']:.2f}.")
                steps.append(
                    "Log-error quantiles [" + p.expr("band_log_quantile") + "]: "
                    + ", ".join(f"{lv * 100:g}% {q * 100:+.1f}%" for lv, q in zip(QUANTILE_LEVELS, r["log_q"])) + ".")
                steps.append(
                    f"Median [{p.expr('median_value')}] = {r['median']:.1f}; at "
                    f"{r['usual']}: {_fmt(w[MEDIAN_INDEX])} {unit}; 50% {_fmt(lo50)}-{_fmt(hi50)}, "
                    f"80% {_fmt(lo80)}-{_fmt(hi80)}, 95% {_fmt(lo95)}-{_fmt(hi95)} [{p.expr('band_value')}].")
                if f.days_since_last > p.band_gap_cap_days:
                    steps.append(f"Note: last session {f.days_since_last:.0f} days ago is beyond the "
                                 f"backtest's {p.band_gap_cap_days:g} days; bands are capped there.")
                outcomes.append(Outcome(
                    f"{ex_name} ({r['usual']})", estimate=w[MEDIAN_INDEX], interval=(lo80, hi80),
                    note=f"{unit}; 50%: {_fmt(lo50)}-{_fmt(hi50)} · 95%: {_fmt(lo95)}-{_fmt(hi95)}"))
                outcomes.append(Outcome(
                    "Change from today", estimate=w[MEDIAN_INDEX] / current_w - 1,
                    interval=(lo80 / current_w - 1, hi80 / current_w - 1), fmt="pct",
                    note=f"today {_fmt(current_w)} {unit}"))
                if f.last.reps is not None:
                    outcomes.append(Outcome(
                        "Estimated one-rep max", estimate=v[MEDIAN_INDEX], interval=interval_at(v, 0.8),
                        note=f"{unit}; today {f.current:.1f} [{p.expr('rep_index')}]"))
                extras["_quantiles"] = w
            else:
                steps.append(f"{ex_name}: strength {f.current:.1f} after {f.weeks:.1f} weeks, "
                             f"{f.freq:.2f}/week -> gain {(math.exp(r['gain']) - 1) * 100:+.1f}%, "
                             f"median {_fmt(w[MEDIAN_INDEX])} {unit} at {r['usual']}.")
                outcomes.append(Outcome(
                    f"{ex_name} ({r['usual']})", estimate=w[MEDIAN_INDEX], interval=(lo80, hi80),
                    group="Other exercises in the log", note=f"{unit}; today {_fmt(current_w)}"))
            extras["exercises"][ex_name] = {
                "current": round(f.current, 4), "current_weight": round(current_w, 4),
                "weeks": round(f.weeks, 3), "freq": round(f.freq, 4),
                "days_since_last": f.days_since_last, "slope": round(f.slope, 6),
                "sessions": f.n_sessions, "gain": round(r["gain"], 6),
                "log_quantiles": [round(q, 6) for q in r["log_q"]],
                "median_weight": round(w[MEDIAN_INDEX], 4),
                "bands": {f"{lv:g}": [round(a, 4) for a in interval_at(w, lv)] for lv in BAND_LEVELS},
            }

        shown = {"today": str(today), "target date": f"{target} ({h:.1f} weeks)", "exercise": name}
        if since:
            shown["training since"] = str(since)
        for key in ("sex", "age", "bodyweight"):
            if inputs.get(key) not in (None, ""):
                shown[key] = f"{inputs[key]} (not used)"
        shown["log"] = ", ".join(f"{n}: {len(e.sessions)} sessions {e.sessions[0].date}..{e.sessions[-1].date}"
                                 for n, e in exercises.items())
        return self.prediction(inputs=shown, outcomes=outcomes, steps=steps, interval_level=0.8,
                               extras=extras)

    # ── backtest ───────────────────────────────────────────────────────────

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        metrics = super().score(prediction, actual)
        w = prediction.extras["_quantiles"]
        med = prediction.primary.estimate
        metrics["abs_log_error_pct"] = abs(math.log(actual / med)) * 100
        metrics["bias_pct"] = math.log(med / actual) * 100
        for lv in BAND_LEVELS:
            lo, hi = interval_at(w, lv)
            metrics[f"in_{lv * 100:.0f}"] = float(lo <= actual <= hi)
        return metrics

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], float]:
        """data/backtest.csv: log = 'YYYY-MM-DD:weight:duration;...' (last 12 weeks before today)."""
        log = []
        for item in row["log"].split(";"):
            d, wt, du = item.split(":")
            log.append({"date": d, "exercise": row["exercise"], "weight": float(wt), "duration": float(du)})
        inputs = {"today": row["today"], "target_date": row["target_date"], "exercise": row["exercise"],
                  "training_since": row["training_since"] or None, "log": log}
        for key in ("sex", "age"):
            if row.get(key):
                inputs[key] = row[key]
        return inputs, float(row["actual_weight"])

    def backtest_group(self, row: dict[str, str]) -> str | None:
        h = float(row["horizon_weeks"])
        return "horizon <= 10 wk" if h <= 10 else "horizon 11-32 wk" if h <= 32 else "horizon 33-54 wk"
