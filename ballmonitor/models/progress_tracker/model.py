"""Progress tracker: a plan from a start value to a goal (even / faster early / faster late, like a
race pacing strategy), tracking how much of the planned progress a log has made, and the result
that rate leads to on the goal date. See MODEL.md.

The public page's tool (web/static/apps/progress_tracker.js) is a line-by-line copy of predict();
tests/test_progress_tracker_app.py runs it against this file.
"""

from __future__ import annotations

import datetime as dt
import math
from statistics import NormalDist
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.core.prediction import Table

# Preset measures: label, kind (selects the scale param), default unit, default direction, display
# format. Definitions, not tunables.
PRESETS = {
    "chess_rating": ("Chess rating", "chess", "points", "higher", "int"),
    "lift": ("Weight lifted / estimated 1-rep max", "strength", "kg", "higher", "number"),
    "running_pace": ("Running pace", "running", "min/km", "lower", "time"),
    "race_time": ("Race time", "running", "h:mm:ss", "lower", "time"),
    "body_weight": ("Body weight", "body", "kg", "lower", "number"),
    "body_fat": ("Body fat %", "body", "%", "lower", "number"),
    "custom": ("Custom measure", "other", "", "higher", "number"),
}
KINDS = ("chess", "strength", "running", "body", "other")
SHAPES = ("even", "faster_early", "faster_late")
NEXT_WORDS = {"on_plan": "on plan: the plan's next step", "ahead": "ahead: keep your own pace",
              "catch_up": "behind: one plan step plus a share of the gap (catch_up_share)",
              "waypoint": "behind: back to the plan's own waypoint", "minimum": "the minimum to still reach the goal on time"}
SHAPE_WORDS = {"even": "even", "faster_early": "faster early", "faster_late": "faster late"}


def as_date(value: Any, name: str = "date") -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise ValueError(f"{name} {value!r} is not a date (YYYY-MM-DD)") from None


def parse_value(value: Any) -> float:
    """A number, or a time "m:ss" / "h:mm:ss" (-> seconds)."""
    if isinstance(value, bool):
        raise ValueError(f"value {value!r} is not a number")
    if isinstance(value, (int, float)):
        x = float(value)
    else:
        s = str(value).strip()
        if ":" in s:
            parts = s.split(":")
            if len(parts) > 3 or not all(p.strip().replace(".", "", 1).isdigit() for p in parts):
                raise ValueError(f"value {value!r} is not a time (m:ss or h:mm:ss)")
            x = 0.0
            for p in parts:
                x = x * 60 + float(p)
        else:
            try:
                x = float(s)
            except ValueError:
                raise ValueError(f"value {value!r} is not a number") from None
    if not math.isfinite(x):
        raise ValueError(f"value {value!r} is not a finite number")
    return x


class ProgressTrackerModel(BaseModel):
    def measure(self, inputs: dict[str, Any]) -> dict:
        key = str(inputs.get("metric", "custom")).strip()
        if key not in PRESETS:
            raise ValueError(f"metric must be one of {', '.join(PRESETS)}; got {key!r}")
        label, kind, unit, direction, fmt = PRESETS[key]
        direction = str(inputs.get("direction", direction)).strip().lower()
        if direction not in ("higher", "lower"):
            raise ValueError("direction must be 'higher' or 'lower' (which way is better)")
        if key == "custom":
            scale = str(inputs.get("scale", "log")).strip().lower()
            if scale not in ("log", "linear"):
                raise ValueError("scale must be 'log' (% progress) or 'linear' (units)")
        else:
            scale = str(self.params[f"scale_{kind}"])
        return {"key": key, "label": str(inputs.get("name") or label), "kind": kind, "unit": str(inputs.get("unit", unit)),
                "direction": direction, "scale": scale, "fmt": fmt}

    def share(self, shape: str, t: float) -> float:
        """Share of the planned progress due at time share t (clipped to 0..1)."""
        return self.params.formula(f"share_{shape}", t=min(max(t, 0.0), 1.0))

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        m = self.measure(inputs)
        log = m["scale"] == "log"
        fwd = (lambda v: math.log(v)) if log else (lambda v: v)
        back = (lambda y: math.exp(y)) if log else (lambda y: y)
        shape = str(inputs.get("shape", "faster_early")).strip().lower().replace(" ", "_")
        if shape not in SHAPES:
            raise ValueError(f"shape must be one of {', '.join(SHAPES)}")

        entries = []
        for e in inputs.get("entries") or []:
            d, v = as_date(e["date"]), parse_value(e["value"])
            if log and v <= 0:
                raise ValueError(f"{m['label']} must be above 0 on a % scale (entry {d}: {v:g})")
            entries.append((d, v))
        entries.sort(key=lambda e: e[0])
        if "goal_value" not in inputs or "goal_date" not in inputs:
            raise ValueError("give goal_value and goal_date")
        start_date = as_date(inputs["start_date"], "start_date") if inputs.get("start_date") else (entries[0][0] if entries else None)
        if start_date is None:
            raise ValueError("give a start_date and start_value, or at least one entry")
        if inputs.get("start_value") not in (None, ""):
            start_value = parse_value(inputs["start_value"])
        else:
            later = [v for d, v in entries if d >= start_date]
            if not later:
                raise ValueError("give a start_value (no entry on or after the start date)")
            start_value = later[0]
        goal_value, goal_date = parse_value(inputs["goal_value"]), as_date(inputs["goal_date"], "goal_date")
        if log and (start_value <= 0 or goal_value <= 0):
            raise ValueError("start and goal must be above 0 on a % scale")
        plan_weeks = (goal_date - start_date).days / 7
        if not 0 < plan_weeks <= p.max_plan_weeks:
            raise ValueError(f"the goal date must be after the start date and within {p.max_plan_weeks:g} weeks of it")
        if goal_value == start_value:
            raise ValueError("the goal must differ from the start value")
        today = as_date(inputs["today"], "today") if inputs.get("today") else (entries[-1][0] if entries else start_date)
        S, G = fwd(start_value), fwd(goal_value)

        def planned(day: dt.date) -> float:
            t = (day - start_date).days / 7 / plan_weeks
            return p.formula("planned", start=S, share=self.share(shape, t), goal=G)

        steps = [f"{m['label']}: plan '{SHAPE_WORDS[shape]}' from {start_value:g} on {start_date} to {goal_value:g} on "
                 f"{goal_date} ({plan_weeks:.1f} weeks), scale {m['scale']}; share formula "
                 f"[{p.expr('share_' + shape)}], planned [{p.expr('planned')}]."]

        # adherence: progress made (y) vs planned (x) at entries after the start, up to today
        used = [(d, fwd(v)) for d, v in entries if start_date < d <= today]
        xs = [planned(d) - S for d, _ in used]
        ys = [y - S for _, y in used]
        raw_w = [p.formula("recency_weight", age_weeks=(today - d).days / 7) for d, _ in used]
        n = len(used)
        w = [wi * n / sum(raw_w) for wi in raw_w] if n else []
        sxx = sum(wi * x * x for wi, x in zip(w, xs))
        sxy = sum(wi * x * y for wi, x, y in zip(w, xs, ys))
        m_prior = (self.share(shape, 0.5) * (G - S)) ** 2   # one entry exactly on plan at half-time
        if sxx + p.prior_weight * m_prior > 0:
            f = p.formula("adherence", sxy=sxy, sxx=sxx, m=m_prior)
        else:
            f = 1.0                     # nothing to measure yet: on plan
        resid_var = sum(wi * (y - f * x) ** 2 for wi, x, y in zip(w, xs, ys)) / (n - 1) if n >= 2 else None
        f_var = resid_var / (sxx + p.prior_weight * m_prior) if resid_var is not None and sxx + p.prior_weight * m_prior > 0 else None
        steps.append(f"Adherence [{p.expr('adherence')}] = {f:.4g} from {n} entries after the start "
                     f"(sxy {sxy:.4g}, sxx {sxx:.4g}, half-time plan progress^2 {m_prior:.4g}, prior weight {p.prior_weight:g}).")

        past = [e for e in entries if e[0] <= today]
        latest = past[-1] if past else None
        wrong_way = f <= 0
        if wrong_way:
            pred_y = fwd(latest[1]) if latest else S
            steps.append("Adherence <= 0 (moving away from the goal): the predicted result is the latest entry.")
        else:
            pred_y = p.formula("predicted", start=S, f=f, goal=G)
            steps.append(f"Predicted on {goal_date} [{p.expr('predicted')}] = {back(pred_y):.5g}.")
        interval = None
        z = NormalDist().inv_cdf(0.5 + float(p.interval_level) / 2)
        if f_var is not None and not wrong_way:
            sd = p.formula("spread", resid_var=resid_var, goal=G, start=S, f_var=f_var)
            interval = (back(pred_y - z * sd), back(pred_y + z * sd))
            steps.append(f"Spread [{p.expr('spread')}] = {sd:.4g} (resid var {resid_var:.4g}, f var {f_var:.4g}); untested.")

        sign = 1 if G > S else -1         # the plan's direction
        as_change = (lambda d_: math.exp(d_) - 1) if log else (lambda d_: d_)
        track = None
        if latest:
            gap = fwd(latest[1]) - planned(latest[0])
            track = {"date": latest[0].isoformat(), "value": latest[1], "planned": back(planned(latest[0])),
                     "gap": gap, "gap_change": as_change(gap), "ahead": sign * gap >= 0}
        # re-plan the rest from the latest entry with the same shape
        replan = None
        rp_from_d, rp_from_y = (latest[0], fwd(latest[1])) if latest else (start_date, S)
        rem_weeks = (goal_date - rp_from_d).days / 7
        if rem_weeks > 0:
            per_week = (G - rp_from_y) / rem_weeks
            replan = {"from": rp_from_d.isoformat(), "weeks": rem_weeks, "per_week": as_change(per_week),
                      "done": sign * (rp_from_y - G) >= 0}

        def replanned(day: dt.date) -> float:
            t = (day - rp_from_d).days / 7 / rem_weeks
            return rp_from_y + self.share(shape, t) * (G - rp_from_y)

        rows = []
        if rem_weeks > 0:
            k = 1
            while True:
                d = min(today + dt.timedelta(days=7 * k), goal_date)
                if d <= today:
                    break
                rows.append({"week": k, "date": d.isoformat(), "plan": back(planned(d)), "replan": back(replanned(d)),
                             "track": back(pred_y) if wrong_way else back(S + f * (planned(d) - S))})
                if d >= goal_date:
                    break
                k += 1

        # next week's goal: from the latest entry, one plan-week of progress plus part of any gap
        next_goal = None
        if latest:
            ld, y = latest[0], fwd(latest[1])
            base = max(ld, today)                       # a stale entry: measure from today
            if base >= goal_date:
                next_goal = {"reason": "past_goal_date"}
            elif sign * (y - G) >= 0:
                next_goal = {"reason": "reached"}
            else:
                nd = min(base + dt.timedelta(days=7), goal_date)
                step = planned(nd) - planned(base)
                gap = planned(base) - y                       # > 0 in the goal's direction = behind
                if sign * gap <= p.on_track_tolerance * abs(step):
                    keep = y + step
                    target = keep if sign * keep > sign * planned(nd) else planned(nd)
                    reason = "ahead" if sign * gap < 0 and target == keep else "on_plan"
                else:
                    target = p.formula("next_goal_behind", latest=y, step=step, gap=gap)
                    reason = "catch_up"
                    if sign * target > sign * planned(nd):
                        target, reason = planned(nd), "waypoint"
                    # re-plan from the latest value at the base date to the goal, same shape
                    floor_ = y + self.share(shape, (nd - base).days / ((goal_date - base).days)) * (G - y)
                    if sign * target < sign * floor_:
                        target, reason = floor_, "minimum"
                next_goal = {"reason": reason, "date": nd.isoformat(), "value": back(target), "change": as_change(target - y),
                             "gap": as_change(sign * gap), "step": as_change(step), "latest": latest[1]}
                steps.append(f"Next week's goal ({nd}): {back(target):.5g}, {reason} (latest {latest[1]:g} on {ld}, plan step "
                             f"{step:.4g} from {base}, gap {gap:.4g}; behind formula [{p.expr('next_goal_behind')}], capped at the "
                             f"plan {back(planned(nd)):.5g}, at least the re-plan from {base}).")

        fmt = m["fmt"]
        change_fmt = "pct" if log else "points"
        outcomes = [
            Outcome(f"Predicted on {goal_date}", estimate=back(pred_y), interval=interval, fmt=fmt,
                    note="moving away from the goal so far: shown as the latest entry" if wrong_way
                    else "untested: your plan scaled by the share of it you've kept"),
            Outcome("Your goal", estimate=goal_value, fmt=fmt),
            Outcome(f"Planned for {today}", estimate=back(planned(today)), fmt=fmt),
            Outcome("Share of the planned progress made", estimate=f, fmt="pct",
                    note="no entries since the start yet" if n == 0 else f"from {n} entries"),
        ]
        if track:
            outcomes.append(Outcome("Ahead (+) or behind (-) the plan", estimate=sign * track["gap_change"], fmt=change_fmt,
                                    note=f"latest entry {track['date']}"))
        if next_goal and "value" in next_goal:
            outcomes.insert(1, Outcome(f"Next week's goal ({next_goal['date']})", estimate=next_goal["value"], fmt=fmt,
                                       note=NEXT_WORDS[next_goal["reason"]]))
        if replan and not replan["done"]:
            outcomes.append(Outcome("Needed per week from here", estimate=replan["per_week"], fmt=change_fmt,
                                    note=f"re-planned ({SHAPE_WORDS[shape]}) from {replan['from']}"))
        show = lambda v: _fmt(v, fmt)
        tables = [Table("Week-by-week", ["Week", "Date", "Plan", "Re-plan from here", "Current track"],
                        [[str(r["week"]), r["date"], show(r["plan"]), show(r["replan"]), show(r["track"])] for r in rows])]
        extras = {"measure": m, "shape": shape, "today": today.isoformat(), "start_date": start_date.isoformat(),
                  "start_value": start_value, "goal_value": goal_value, "goal_date": goal_date.isoformat(),
                  "plan_weeks": plan_weeks, "f": f, "n": n, "sxx": sxx, "sxy": sxy, "resid_var": resid_var, "f_var": f_var,
                  "wrong_way": wrong_way, "predicted": back(pred_y), "interval": list(interval) if interval else None,
                  "planned_today": back(planned(today)), "track": track, "replan": replan, "weeks_table": rows,
                  "next_goal": next_goal}
        return self.prediction(
            inputs={"measure": f"{m['label']} ({m['unit']})" if m["unit"] else m["label"],
                    "plan": f"{SHAPE_WORDS[shape]}: {start_value:g} on {start_date} -> {goal_value:g} on {goal_date}",
                    "entries": str(len(entries)), "today": today.isoformat()},
            outcomes=outcomes, steps=steps, interval_level=float(p.interval_level) if interval else None,
            extras=extras, tables=tables)


def _fmt(v: float, fmt: str) -> str:
    from ballmonitor.core.render import format_value
    return format_value(v, fmt)
