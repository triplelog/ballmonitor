"""Weight loss: Hall et al. (Lancet 2011) dynamic body-weight model. See MODEL.md.

Written from the equations published in the paper's web appendix; this is our own code,
not the NIH Body Weight Planner's (which NIDDK lists as a licensable technology).
"""

from __future__ import annotations

import ast
import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction, Table
from ballmonitor.core import formula as formula_engine
from ballmonitor.core.stats import z_for_level

# Definitional unit constants (candidates for core/units.py).
KG_PER_LB = 0.45359237
CM_PER_INCH = 2.54
CM_PER_M = 100.0
LEVELS = (0.5, 0.8, 0.95)  # band levels reported; 0.8 is the headline interval
HEADLINE_LEVEL = 0.8
DAYS_PER_WEEK = 7
SEXES = {"m": True, "male": True, "man": True, "f": False, "female": False, "woman": False}


@dataclass
class Person:
    male: bool
    age: float
    height_cm: float
    weight0: float  # kg
    fat0: float  # kg
    pal: float
    rmr: float  # kcal/day
    ei0: float  # baseline intake = expenditure, kcal/day
    delta0: float  # baseline activity coefficient, kcal/kg/day
    fat_source: str


@dataclass
class Plan:
    delta1: float  # activity coefficient after the change
    carb_fraction: float  # share of intake from carbohydrate after the change
    sodium_change: float  # mg/day


class _Compiled:
    """A config formula parsed once, for the integration's inner loop.

    Params.formula() re-parses the expression on every call, which is too slow for
    thousands of daily steps; this evaluates the same (already validated) expression.
    """

    def __init__(self, params, name: str):
        self.expr = params.expr(name)
        self.tree = ast.parse(self.expr.strip(), mode="eval").body
        self.env = {**formula_engine.CONSTANTS, **params.numeric_values()}

    def __call__(self, **variables: float) -> float:
        return formula_engine._eval(self.tree, {**self.env, **variables}, self.expr)


class WeightLossModel(BaseModel):
    # ------------------------------------------------------------------ inputs
    def _person(self, inputs: dict[str, Any], to_kg: float, steps: list[str]) -> Person:
        p = self.params
        sex = str(inputs.get("sex", "")).strip().lower()
        if sex not in SEXES:
            raise ValueError("sex must be 'M' or 'F' (the equations are sex-specific)")
        male = SEXES[sex]
        age = _number(inputs, "age")
        if age < p.min_age:
            raise ValueError(f"age must be at least {p.min_age:g}: the adult equations do not apply to children")
        if inputs.get("height_cm") is not None:
            height_cm = _number(inputs, "height_cm")
        elif inputs.get("height_in") is not None:
            height_cm = _number(inputs, "height_in") * CM_PER_INCH
        else:
            raise ValueError("give height_cm or height_in")
        if height_cm <= 0:
            raise ValueError("height must be positive")
        weight0 = _number(inputs, "weight") * to_kg
        if weight0 <= 0:
            raise ValueError("weight must be positive")
        height_m = height_cm / CM_PER_M

        if inputs.get("body_fat_pct") is not None:
            pct = _number(inputs, "body_fat_pct")
            if not 0 < pct < 100:
                raise ValueError("body_fat_pct must be between 0 and 100")
            fat0 = weight0 * pct / 100
            fat_source = f"measured {pct:g}%"
            steps.append(f"Body fat today = {pct:g}% x {weight0:.1f} kg = {fat0:.1f} kg (given).")
        else:
            fat0 = p.formula("initial_fat", weight=weight0, height_m=height_m, age=age, male=int(male))
            fat_source = "estimated from BMI (Jackson)"
            steps.append(
                f"Body fat today = {fat0:.1f} kg ({fat0 / weight0:.0%}) from BMI "
                f"{weight0 / height_m ** 2:.1f}, age and sex [{p.expr('initial_fat')}]."
            )
        lean_fixed = (1 + p.glycogen_water_ratio) * p.glycogen_init_kg
        if not 0 < fat0 < weight0 - lean_fixed:
            raise ValueError(
                f"estimated body fat {fat0:.1f} kg is impossible for {weight0:.1f} kg; "
                "check height/weight or give body_fat_pct"
            )

        activity = inputs.get("activity", "sedentary")
        if inputs.get("pal") is not None:
            pal = _number(inputs, "pal")
            spec = self.params.specs["pal_sedentary"]
            lo, hi = spec.range
            if not lo <= pal <= hi:
                raise ValueError(f"pal must be between {lo:g} and {hi:g}")
        else:
            key = f"pal_{str(activity).strip().lower()}"
            if key not in self.params.specs:
                raise ValueError("activity must be 'sedentary', 'active' or 'vigorous' (or give pal)")
            pal = getattr(p, key)
        rmr = p.formula("rmr", weight=weight0, height_cm=height_cm, age=age, male=int(male))
        ei0 = pal * rmr
        delta0 = p.formula("activity_coefficient", pal=pal, rmr=rmr, weight=weight0)
        steps.append(f"Resting rate RMR = {rmr:.0f} kcal/day [{p.expr('rmr')}].")
        steps.append(
            f"Maintenance intake today = PAL {pal:g} x RMR = {ei0:.0f} kcal/day (weight assumed stable)."
        )
        steps.append(
            f"Activity coefficient delta = {delta0:.2f} kcal/kg/day [{p.expr('activity_coefficient')}]."
        )
        return Person(male, age, height_cm, weight0, fat0, pal, rmr, ei0, delta0, fat_source)

    def _plan(self, inputs: dict[str, Any], person: Person, steps: list[str]) -> tuple[Plan, float]:
        p = self.params
        intake_change = _number(inputs, "intake_change", 0.0)
        activity_pct = _number(inputs, "activity_change_pct", 0.0)
        exercise = _number(inputs, "exercise_kcal", 0.0)
        delta1 = person.delta0 * (1 + activity_pct / 100) + exercise / person.weight0
        if delta1 < 0:
            raise ValueError("the activity change makes physical activity negative")
        if person.ei0 + intake_change <= 0:
            raise ValueError(
                f"intake_change {intake_change:+.0f} leaves no food: maintenance is {person.ei0:.0f} kcal/day"
            )
        carb = p.baseline_carb_fraction
        if inputs.get("carb_pct_after") is not None:
            carb = _number(inputs, "carb_pct_after") / 100
            if not 0 < carb <= 1:
                raise ValueError("carb_pct_after must be between 0 and 100")
        sodium = _number(inputs, "sodium_change_mg", 0.0)
        steps.append(
            f"Plan: intake {intake_change:+.0f} kcal/day -> {person.ei0 + intake_change:.0f} kcal/day; "
            f"activity delta {person.delta0:.2f} -> {delta1:.2f} kcal/kg/day "
            f"({activity_pct:+g}% and {exercise:+g} kcal/day of exercise)."
        )
        return Plan(delta1, carb, sodium), intake_change

    # ------------------------------------------------------------- simulation
    def _simulate(self, person: Person, plan: Plan, d_ei: float, days: int) -> list[tuple[float, float]]:
        """(weight kg, fat kg) for day 0..days with a constant intake change d_ei."""
        if self.params.method == "linear":
            return self._simulate_linear(person, plan, d_ei, days)
        return self._simulate_hall(person, plan, d_ei, days)

    def _simulate_hall(self, person: Person, plan: Plan, d_ei: float, days: int) -> list[tuple[float, float]]:
        p = self.params
        partition = _Compiled(p, "energy_partition")
        rho_f, rho_l, rho_g = p.rho_fat, p.rho_lean, p.rho_glycogen
        eta_f, eta_l = p.eta_fat, p.eta_lean
        g0 = p.glycogen_init_kg
        hyd = 1 + p.glycogen_water_ratio
        ei = person.ei0 + d_ei
        ci_b = p.baseline_carb_fraction * person.ei0
        ci = plan.carb_fraction * ei
        k_g = ci_b / g0 ** 2
        tef = p.beta_tef * d_ei
        at_target = p.beta_at * d_ei
        w0, f0 = person.weight0, person.fat0

        def deriv(s):
            fat, d_lean, gly, d_ecf, at = s
            if fat <= 0:
                raise ValueError("the plan drives body fat to zero before the target date; the model does not apply")
            bw = w0 + (fat - f0) + d_lean + hyd * (gly - g0) + d_ecf
            share = partition(fat=fat)
            dg = (ci - k_g * gly ** 2) / rho_g
            decf = (plan.sodium_change - p.xi_na * d_ecf - p.xi_ci * (1 - ci / ci_b)) / p.sodium_conc
            x = share * eta_l / rho_l + (1 - share) * eta_f / rho_f
            ee = (
                person.ei0 + p.gamma_fat * (fat - f0) + p.gamma_lean * d_lean
                + plan.delta1 * bw - person.delta0 * w0 + tef + at + (ei - rho_g * dg) * x
            ) / (1 + x)
            imbalance = ei - ee - rho_g * dg
            return (
                (1 - share) * imbalance / rho_f,
                share * imbalance / rho_l,
                dg,
                decf,
                (at_target - at) / p.tau_at_days,
            )

        def weight(s):
            return w0 + (s[0] - f0) + s[1] + hyd * (s[2] - g0) + s[3]

        h = 1.0 / p.steps_per_day
        state = (f0, 0.0, g0, 0.0, 0.0)
        out = [(w0, f0)]
        for _ in range(days):
            for _ in range(p.steps_per_day):
                k1 = deriv(state)
                k2 = deriv(tuple(a + h / 2 * b for a, b in zip(state, k1)))
                k3 = deriv(tuple(a + h / 2 * b for a, b in zip(state, k2)))
                k4 = deriv(tuple(a + h * b for a, b in zip(state, k3)))
                state = tuple(
                    a + h / 6 * (b1 + 2 * b2 + 2 * b3 + b4) for a, b1, b2, b3, b4 in zip(state, k1, k2, k3, k4)
                )
            out.append((weight(state), state[0]))
        return out

    def _linear_terms(self, person: Person, plan: Plan, d_ei: float) -> dict[str, float]:
        """Appendix eqs. 10-17: alpha, tau and the steady-state weight change."""
        p = self.params
        alpha = p.forbes_c_kg / person.fat0
        beta = p.beta_tef + p.beta_at
        d_delta = plan.delta1 - person.delta0
        density = (p.eta_fat + p.rho_fat + alpha * (p.eta_lean + p.rho_lean)) / (1 + alpha)
        slope = (p.gamma_fat + alpha * p.gamma_lean) / (1 + alpha) + plan.delta1
        dbw_ss = ((1 - beta) * d_ei - d_delta * person.weight0) / slope
        return {"alpha": alpha, "tau": density / slope, "dbw_ss": dbw_ss}

    def _simulate_linear(self, person: Person, plan: Plan, d_ei: float, days: int) -> list[tuple[float, float]]:
        terms = self._linear_terms(person, plan, d_ei)
        out = []
        for t in range(days + 1):
            bw = self.params.formula(
                "linear_weight", weight0=person.weight0, dbw_ss=terms["dbw_ss"], t=t, tau=terms["tau"]
            )
            fat = person.fat0 + (bw - person.weight0) / (1 + terms["alpha"])
            if fat <= 0:
                raise ValueError("the plan drives body fat to zero before the target date; the model does not apply")
            out.append((bw, fat))
        return out

    # ------------------------------------------------------------------ fit
    def _fit(self, person, plan, prior_mean, prior_sd, obs, days) -> tuple[float, float, int]:
        """1-D Gauss-Newton MAP estimate of the effective intake change; returns (mean, sd, iterations)."""
        p = self.params
        var_w = p.weighin_sd_kg ** 2
        x = prior_mean
        precision = 1 / prior_sd ** 2
        for it in range(1, p.fit_iterations + 1):
            base = self._simulate(person, plan, x, days)
            bumped = self._simulate(person, plan, x + p.fit_step_kcal, days)
            grad = -(x - prior_mean) / prior_sd ** 2
            precision = 1 / prior_sd ** 2
            for t, w in obs:
                j = (bumped[t][0] - base[t][0]) / p.fit_step_kcal
                grad += j * (w - base[t][0]) / var_w
                precision += j * j / var_w
            step = grad / precision
            x += step
            if abs(step) < p.fit_step_kcal / 100:
                break
        return x, 1 / math.sqrt(precision), it

    def _goal_intake(self, person, plan, goal, days) -> float:
        """Intake change that puts the median weight on the goal at the target date (secant)."""
        p = self.params
        a, b = 0.0, -person.ei0 / 4
        fa = self._simulate(person, plan, a, days)[days][0] - goal
        fb = self._simulate(person, plan, b, days)[days][0] - goal
        for _ in range(p.goal_iterations):
            if abs(fb) < p.goal_tolerance_kg or fb == fa:
                break
            a, b, fa = b, b - fb * (b - a) / (fb - fa), fb
            b = max(b, -person.ei0)  # cannot eat less than nothing
            fb = self._simulate(person, plan, b, days)[days][0] - goal
        return b

    def _maintenance_change(self, person, plan, weight, fat) -> float:
        """Intake change that holds `weight` steady once reached (eq. 5 with all rates zero)."""
        p = self.params
        d_ffm = weight - fat - (person.weight0 - person.fat0)  # change of fat-free mass
        beta = p.beta_tef + p.beta_at
        return (
            p.gamma_fat * (fat - person.fat0) + p.gamma_lean * d_ffm
            + plan.delta1 * weight - person.delta0 * person.weight0
        ) / (1 - beta)

    # --------------------------------------------------------------- predict
    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        steps: list[str] = []
        unit = str(inputs.get("units", "kg")).strip().lower()
        if unit not in ("kg", "lb"):
            raise ValueError("units must be 'kg' or 'lb'")
        to_kg = KG_PER_LB if unit == "lb" else 1.0
        start = _date(inputs, "start_date")
        target = _date(inputs, "target_date")
        days = (target - start).days
        if days <= 0:
            raise ValueError("target_date must be after start_date")
        if days > p.max_horizon_days:
            raise ValueError(f"target_date is more than {p.max_horizon_days} days after start_date")

        person = self._person(inputs, to_kg, steps)
        plan, planned = self._plan(inputs, person, steps)
        method = "Hall 2011 dynamic model (daily RK4)" if p.method == "hall2011" else "linear (appendix eq. 14)"
        steps.append(f"Method: {method}.")

        # Prior on the effective intake change, in energy-equivalent terms.
        activity_kcal = (plan.delta1 - person.delta0) * person.weight0
        planned_total = planned - activity_kcal
        prior_mean = p.adherence_mean * planned_total + activity_kcal
        prior_sd = math.hypot(p.adherence_sd * planned_total, p.intake_sd_floor)
        if prior_sd <= 0:
            raise ValueError("adherence_sd and intake_sd_floor are both 0: no uncertainty to work with")
        steps.append(
            f"Planned energy change = intake {planned:+.0f} - activity {activity_kcal:.0f} "
            f"= {planned_total:+.0f} kcal/day; prior effective intake change = {p.adherence_mean:g} x plan "
            f"= {prior_mean:+.0f} +/- {prior_sd:.0f} kcal/day (SD = hypot({p.adherence_sd:g} x plan, "
            f"{p.intake_sd_floor:g}))."
        )

        obs = []
        for row in inputs.get("weighins", []) or []:
            when = _date(row, "date")
            t = (when - start).days
            if t < 0:
                raise ValueError(f"weigh-in on {when} is before start_date {start}")
            w = _number(row, "weight") * to_kg
            if w <= 0:
                raise ValueError("weigh-in weights must be positive")
            obs.append((t, w))
        horizon = max([days] + [t for t, _ in obs])
        if obs:
            mean, sd, iters = self._fit(person, plan, prior_mean, prior_sd, obs, horizon)
            steps.append(
                f"Fitted {len(obs)} weigh-in(s) (SD {p.weighin_sd_kg:g} kg each) by 1-D least squares with the "
                f"prior: effective intake change = {mean:+.0f} +/- {sd:.0f} kcal/day ({iters} Gauss-Newton steps)."
            )
        else:
            mean, sd = prior_mean, prior_sd

        median_run = self._simulate(person, plan, mean, horizon)
        runs = {}
        for level in LEVELS:
            z = z_for_level(level)
            runs[level] = (
                self._simulate(person, plan, mean - z * sd, days),
                self._simulate(person, plan, mean + z * sd, days),
            )

        def band(day: int, level: float) -> tuple[float, float]:
            """Intake quantiles mapped through the (monotone) model, plus weigh-in scatter in quadrature."""
            z = z_for_level(level)
            med = median_run[day][0]
            low, high = runs[level][0][day][0], runs[level][1][day][0]
            noise = z * p.weighin_sd_kg if day > 0 else 0.0
            return med - math.hypot(med - low, noise), med + math.hypot(high - med, noise)

        w_t, fat_t = median_run[days]
        bands = {level: band(days, level) for level in LEVELS}
        lo80, hi80 = bands[HEADLINE_LEVEL]
        steps.append(
            f"Weight on {target} ({days} days) = {w_t / to_kg:.1f} {unit}; bands = model run at the effective "
            f"intake's quantiles (mean +/- z x SD), widened by z x {p.weighin_sd_kg:g} kg weigh-in scatter."
        )
        lin = self._linear_terms(person, plan, mean)
        steps.append(
            f"Linearised (appendix eqs. 15, 17): time constant tau = {lin['tau']:.0f} days; eventual change if "
            f"kept for good = {lin['dbw_ss'] / to_kg:+.1f} {unit} (alpha = C / F0 = {lin['alpha']:.2f})."
        )

        def u(kg: float) -> float:
            return kg / to_kg

        def fmt_band(level):
            lo, hi = bands[level]
            return f"{level:.0%}: {u(lo):.1f}-{u(hi):.1f}"

        outcomes = [
            Outcome(
                f"Weight on {target} ({unit})", estimate=u(w_t), interval=(u(lo80), u(hi80)),
                note=f"{fmt_band(0.5)}, {fmt_band(0.95)}",
            ),
            Outcome(f"Change from today ({unit})", estimate=u(w_t - person.weight0),
                    interval=(u(lo80 - person.weight0), u(hi80 - person.weight0)), fmt="points"),
            Outcome(f"Eventual change if kept for good ({unit})", estimate=u(lin["dbw_ss"]), fmt="points",
                    note=f"linearised; about {1 - math.exp(-days / lin['tau']):.0%} of it by the target date"),
            Outcome(f"Body fat on target date ({unit})", estimate=u(fat_t), group="Body composition (median)",
                    note=f"{fat_t / w_t:.0%} of weight; today {u(person.fat0):.1f} ({person.fat_source})"),
            Outcome(f"Fat-free mass on target date ({unit})", estimate=u(w_t - fat_t),
                    group="Body composition (median)", note=f"today {u(person.weight0 - person.fat0):.1f}"),
            Outcome("Maintenance intake today", estimate=person.ei0, fmt="int", group="Energy (kcal/day)",
                    note=f"PAL {person.pal:g} x RMR {person.rmr:.0f}"),
            Outcome("Planned intake", estimate=person.ei0 + planned, fmt="int", group="Energy (kcal/day)"),
            Outcome("Effective intake used", estimate=person.ei0 + mean, fmt="int", group="Energy (kcal/day)",
                    interval=(person.ei0 + mean - z_for_level(HEADLINE_LEVEL) * sd,
                              person.ei0 + mean + z_for_level(HEADLINE_LEVEL) * sd),
                    note="fitted to weigh-ins" if obs else "plan x adherence"),
        ]
        adherence = None
        if obs and abs(planned_total) > 0:
            adherence = (mean - activity_kcal) / planned_total
            outcomes.append(Outcome("Share of planned change achieved", estimate=adherence, fmt="pct",
                                    group="Energy (kcal/day)", note="from your weigh-ins"))

        goal_extras = {}
        if inputs.get("goal_weight") is not None:
            goal = _number(inputs, "goal_weight") * to_kg
            if goal <= 0:
                raise ValueError("goal_weight must be positive")
            d_goal = self._goal_intake(person, plan, goal, days)
            goal_run = self._simulate(person, plan, d_goal, days)
            reached, reached_fat = goal_run[days]
            d_keep = self._maintenance_change(person, plan, reached, reached_fat)
            ok = abs(reached - goal) < max(p.goal_tolerance_kg * 10, 0.1)
            outcomes.append(Outcome(f"Intake to reach {u(goal):.1f} {unit} by target", estimate=person.ei0 + d_goal,
                                    fmt="int", group="Goal (kcal/day)",
                                    note="" if ok else "not reachable by that date"))
            outcomes.append(Outcome("Intake to hold the goal afterwards", estimate=person.ei0 + d_keep,
                                    fmt="int", group="Goal (kcal/day)", note="steady state, eq. 5"))
            steps.append(
                f"Goal {u(goal):.1f} {unit}: secant search on the intake change gives {person.ei0 + d_goal:.0f} "
                f"kcal/day until {target}, then {person.ei0 + d_keep:.0f} kcal/day to hold it "
                f"(eq. 5 with all rates of change zero, intake change x (1 - beta_TEF - beta_AT))."
            )
            goal_extras = {"goal_intake": person.ei0 + d_goal, "goal_maintenance_intake": person.ei0 + d_keep,
                           "goal_reached_kg": reached}

        # Weekly trajectory table.
        weeks = list(range(0, days + 1, DAYS_PER_WEEK))
        stride = max(1, math.ceil(len(weeks) / p.trajectory_max_rows))
        rows_days = weeks[::stride]
        if rows_days[-1] != days:
            rows_days.append(days)
        rows = []
        for d in rows_days:
            lo, hi = band(d, HEADLINE_LEVEL)
            bw, fat = median_run[d]
            rows.append([
                f"{d / DAYS_PER_WEEK:g}" if d % DAYS_PER_WEEK == 0 else f"{d / DAYS_PER_WEEK:.1f}",
                (start + dt.timedelta(days=d)).isoformat(),
                f"{u(bw):.1f}", f"{u(lo):.1f}", f"{u(hi):.1f}", f"{u(fat):.1f}", f"{u(bw - fat):.1f}",
            ])
        table = Table(
            f"Weekly trajectory ({unit}, median and 80% range)",
            ["Week", "Date", "Weight", "80% low", "80% high", "Fat", "Fat-free"], rows,
            note=f"every {stride} weeks" if stride > 1 else "",
        )

        shown = {
            "sex": "male" if person.male else "female",
            "age": f"{person.age:g}",
            "height": f"{person.height_cm:.0f} cm",
            "weight today": f"{u(person.weight0):.1f} {unit}",
            "body fat": person.fat_source,
            "activity": f"PAL {person.pal:g}",
            "intake change": f"{planned:+.0f} kcal/day",
            "activity change": f"{plan.delta1 / person.delta0 - 1:+.0%}" if person.delta0 else "n/a",
            "dates": f"{start} -> {target}",
            "weigh-ins": str(len(obs)),
        }
        if inputs.get("goal_weight") is not None:
            shown["goal"] = f"{_number(inputs, 'goal_weight'):g} {unit}"
        return self.prediction(
            inputs=shown,
            outcomes=outcomes,
            steps=steps,
            interval_level=HEADLINE_LEVEL,
            tables=[table],
            extras={
                "weight_kg": w_t, "fat_kg": fat_t, "bands_kg": {str(k): v for k, v in bands.items()},
                "maintenance_kcal": person.ei0, "effective_change_kcal": mean, "effective_change_sd": sd,
                "prior_change_kcal": prior_mean, "adherence": adherence, "tau_days": lin["tau"],
                "eventual_change_kg": lin["dbw_ss"], "fat0_kg": person.fat0, "days": days,
                "trajectory_kg": [r[0] for r in median_run[: days + 1]], **goal_extras,
            },
        )


def _number(inputs: dict[str, Any], key: str, default: float | None = None) -> float:
    if key not in inputs or inputs[key] is None:
        if default is None:
            raise ValueError(f"missing input '{key}'")
        return default
    value = inputs[key]
    if isinstance(value, bool):
        raise ValueError(f"input '{key}' must be a number")
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"input '{key}' must be a number, got {value!r}") from None
    if not math.isfinite(out):
        raise ValueError(f"input '{key}' must be finite")
    return out


def _date(inputs: dict[str, Any], key: str) -> dt.date:
    if key not in inputs:
        raise ValueError(f"missing input '{key}' (YYYY-MM-DD)")
    value = inputs[key]
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(f"input '{key}' must be a date YYYY-MM-DD, got {value!r}") from None
