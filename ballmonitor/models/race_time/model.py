"""Race time prediction at any distance, with bands measured from real runners' errors.

Default method ("weighted_riegel", v0.5.0): project every race with Riegel's power law,
combine the projections with a weighted geometric mean (races near the target distance
and recent races count more), then put empirical bands around it: quantiles of the log
error fitted on 2,560 train runners (research_bands.py -> RESEARCH_BANDS.md).

Alternative method ("curve", v0.4.0): log-quadratic curve with Empirical Bayes slope
shrinkage, fitness transfer and a normal (log-scale) sigma model.

See MODEL.md for the method, formulas and backtest.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field
from typing import Any, Callable

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.core.units import (
    METERS_PER_KM,
    METERS_PER_MILE,
    distance_label,
    format_time,
    parse_distance,
    parse_time,
)
from ballmonitor.models.race_time.bands import (
    BAND_LEVELS,
    MEDIAN_INDEX,
    QUANTILE_KEYS,
    QUANTILE_LEVELS,
    Race,
    band_features,
    interval_at,
    log_quantiles,
    normal_log_quantiles,
    quantile_times,
    weighted_riegel,
)
from ballmonitor.models.race_time.curve import fit_runner_curve
from ballmonitor.models.race_time.environment import (
    compute_environmental_multipliers,
    extract_conditions,
    normalize_to_neutral,
)
from ballmonitor.models.race_time.fitness import evaluate_fitness_over_time

# Output layout (definitions, not tunables): the chart curve and the benchmark table.
CURVE_MIN_M = 800.0
CURVE_MAX_M = 50000.0
CURVE_POINTS = 60
BENCHMARKS = [  # (label, meters, common)
    ("Mile", METERS_PER_MILE, True),
    ("5K", 5000.0, True),
    ("8K", 8000.0, False),
    ("10K", 10000.0, True),
    ("15K", 15000.0, False),
    ("10 Mile", 10 * METERS_PER_MILE, False),
    ("Half Marathon", 21097.5, True),
    ("Marathon", 42195.0, True),
    ("50K", 50000.0, False),
]
COMMON_OUTCOME_LABELS = {
    "Mile": "Mile", "5K": "5K", "10K": "10K",
    "Half Marathon": "Half marathon", "Marathon": "Marathon",
}

QuantileFn = Callable[[float], list[float]]  # distance (m) -> 7 neutral times (s)


def _opt_int(value: Any, name: str) -> int | None:
    """Parse an optional whole number (accepts 38, 38.0, "38"); None/"" -> None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a whole number, got {value!r}") from exc
    if f != int(f):
        raise ValueError(f"{name} must be a whole number, got {value!r}")
    return int(f)


def _opt_date(value: Any, name: str) -> _dt.date | None:
    """Parse an optional date (TOML date, datetime, or 'YYYY-MM-DD'); None/"" -> None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ValueError(f"{name} must be a date like 2025-04-26, got {value!r}") from exc


def _year_fraction(d: _dt.date) -> float:
    """Date as a fractional year (2025-07-02 -> ~2025.50)."""
    return d.year + (d.timetuple().tm_yday - 1) / 365.25


def _range_str(lo: float, hi: float) -> str:
    return f"{format_time(lo)}–{format_time(hi)}"


@dataclass
class Prepared:
    """Parsed, environment-normalised inputs shared by both methods."""
    target: float
    age: int | None
    gender: str | None
    target_year: int | None
    target_date: _dt.date | None
    races: list[dict[str, Any]]
    target_when: float | None  # fractional year "now" for recency (None = no dates given)
    steps: list[str] = field(default_factory=list)

    def years_before(self, race: dict[str, Any]) -> float:
        if self.target_when is None:
            return 0.0
        when = race["when"] if race["when"] is not None else (
            float(race["year"]) if race["year"] else self.target_when)
        return max(0.0, self.target_when - when)


@dataclass
class Engine:
    """What a method hands to the shared output code."""
    quantiles: QuantileFn
    exponent: float
    gap: float
    weights: list[float]
    implied: list[float]
    steps: list[str]
    extras: dict[str, Any]


class RaceTimeModel(BaseModel):
    # ── input parsing ──────────────────────────────────────────────────────

    def prepare(self, inputs: dict[str, Any]) -> Prepared:
        p = self.params
        raw_races = inputs.get("races", [])
        if isinstance(raw_races, dict):
            raw_races = [raw_races]
        if not raw_races or not isinstance(raw_races, list):
            raise ValueError(
                "inputs need at least one race: [[races]] distance = '5k', time = '20:00'"
            )
        target_str = inputs.get("target", "marathon")
        target = parse_distance(target_str)
        if target <= 0:
            raise ValueError(f"target distance must be positive, got {target_str!r}")

        age = _opt_int(inputs.get("age"), "age")
        gender_in = inputs.get("gender")
        gender = str(gender_in).strip().upper() if gender_in else None
        if gender is not None and gender not in ("M", "F"):
            raise ValueError(f"gender must be 'M' or 'F' (or omitted), got {gender_in!r}")
        target_year = _opt_int(inputs.get("target_year"), "target_year")
        target_date = _opt_date(inputs.get("target_date"), "target_date")
        if target_date is not None and target_year is None:
            target_year = target_date.year

        steps: list[str] = []
        races = []
        for i, r in enumerate(raw_races, 1):
            if not isinstance(r, dict) or "distance" not in r or "time" not in r:
                raise ValueError(
                    f"race {i} needs both 'distance' and 'time' (e.g. distance = '5k', time = '20:00')"
                )
            d_val = parse_distance(r["distance"])
            if d_val <= 0:
                raise ValueError(f"race {i}: distance must be positive, got {r['distance']!r}")
            raw_t = parse_time(r["time"])
            if raw_t <= 0:
                raise ValueError(f"race {i}: time must be positive, got {r['time']!r}")
            y_int = _opt_int(r.get("year"), f"race {i} year")
            r_date = _opt_date(r.get("date"), f"race {i} date")
            if r_date is not None and y_int is None:
                y_int = r_date.year

            r_cond = extract_conditions(r, base_dir=self.dir)
            neutral_t, r_mults = normalize_to_neutral(raw_t, d_val, r_cond, p)
            if abs(r_mults["total_multiplier"] - 1.0) > 0.002:
                steps.append(
                    f"Environmental normalization: {distance_label(d_val)} in "
                    f"{format_time(raw_t)} adjusted to neutral {format_time(neutral_t)} "
                    f"({_factor_text(r_mults)})."
                )
            races.append({
                "distance": d_val,
                "time": neutral_t,
                "raw_time": raw_t,
                "year": y_int,
                "when": _year_fraction(r_date) if r_date is not None else None,
                "date": r_date,
                "name": r.get("name", ""),
                "conditions": r_cond,
            })

        # "Now" for recency: the target date, else the start of target_year but never
        # before the latest race; with no dates/years at all every race counts as current.
        whens = [r["when"] if r["when"] is not None else float(r["year"])
                 for r in races if r["when"] is not None or r["year"]]
        if target_date is not None:
            target_when: float | None = _year_fraction(target_date)
        elif target_year is not None:
            target_when = max([float(target_year)] + whens)
        else:
            target_when = max(whens) if whens else None
        return Prepared(target, age, gender, target_year, target_date, races, target_when, steps)

    # ── methods ────────────────────────────────────────────────────────────

    def weighted_riegel_engine(self, prep: Prepared) -> Engine:
        p = self.params
        steps: list[str] = []
        exponent = p.formula(
            "exponent", male=1.0 if prep.gender == "M" else 0.0,
            female=1.0 if prep.gender == "F" else 0.0,
        )
        who = {"M": "men", "F": "women"}.get(prep.gender or "", "gender not given")
        steps.append(f"Riegel exponent b = {exponent:.3f} ({who}) [{p.expr('exponent')}].")

        races = [Race(r["distance"], r["time"], prep.years_before(r)) for r in prep.races]
        years_since_last = min(r.years_before for r in races)
        shift_on = not p.formulas["predict"].overridden

        def quantiles(D: float) -> list[float]:
            wr = weighted_riegel(races, D, exponent, p)
            gap, years, n = band_features(wr.gap, years_since_last, len(races), p)
            lq = log_quantiles(gap, years, n, p)
            median = p.formula("median_time", point=wr.point,
                               q50=lq[MEDIAN_INDEX] if shift_on else 0.0)
            return quantile_times(median, lq, p)

        D = prep.target
        wr = weighted_riegel(races, D, exponent, p)
        for r, t_i, w_i in zip(races, wr.implied, wr.weights):
            steps.append(
                f"{distance_label(r.distance)} {format_time(r.time)}, "
                f"{r.years_before:.1f} y before target -> {distance_label(D)} "
                f"{format_time(t_i)} [{p.expr('predict')}], weight {w_i:.2f}."
            )
        if len(races) > 1:
            steps.append(
                f"Race weights [{p.expr('race_weight')}], x = ln(D/d); "
                f"{p.race_combination} mean -> {format_time(wr.point)}."
            )
        gap, years, n = band_features(wr.gap, years_since_last, len(races), p)
        lq = log_quantiles(gap, years, n, p)
        steps.append(
            f"Band features: gap = {gap:.2f} (weighted mean |ln(D/d)|), years since "
            f"last race = {years:.1f}, races = {n} (caps: band_max_years, "
            f"band_max_races)."
        )
        steps.append(
            f"Log-error quantiles [{p.expr('band_log_quantile')}]: "
            + ", ".join(f"{lv * 100:g}% {q * 100:+.1f}%" for lv, q in zip(QUANTILE_LEVELS, lq))
            + "."
        )
        if shift_on:
            median = p.formula("median_time", point=wr.point, q50=lq[MEDIAN_INDEX])
            steps.append(
                f"Median [{p.expr('median_time')}]: {format_time(wr.point)} x "
                f"exp({lq[MEDIAN_INDEX] * 100:+.1f}%) = {format_time(median)}."
            )
        else:
            steps.append(
                "Formula 'predict' is overridden: its result is used as the median "
                "(the fitted median shift belongs to the default formula); bands keep "
                "their fitted widths."
            )
        return Engine(quantiles, exponent, wr.gap, wr.weights, wr.implied, steps, {})

    def curve_engine(self, prep: Prepared) -> Engine:
        """The v0.4.0 method: curve fit + fitness transfer + normal sigma model."""
        p = self.params
        fitness_eval = evaluate_fitness_over_time(
            prep.races, target_distance=prep.target, target_year=prep.target_year, params=p,
            target_when=_year_fraction(prep.target_date) if prep.target_date else None,
        )
        steps = list(fitness_eval.steps)
        effective = fitness_eval.effective_races
        fit = fit_runner_curve(
            [(e.distance, e.time, e.weight) for e in effective],
            age=prep.age, gender=prep.gender, fit_weight=p.fit_weight,
            shrinkage_prior_strength=p.shrinkage_prior_strength,
            default_exponent=p.default_exponent, marathon_curvature=p.marathon_curvature,
            min_exponent=p.min_exponent, max_exponent=p.max_exponent,
            use_demographic_priors=p.use_demographic_priors,
            off_day_tolerance_pct=p.off_day_tolerance_pct,
        )
        steps.extend(fit.steps)
        use_power_law = p.formulas["predict"].overridden
        weights = fit.weights or [e.weight for e in effective]

        def time_fn(D: float) -> float:
            if use_power_law:
                projs = [p.formula("predict", t=e.time, d=e.distance, D=D, k=fit.beta1)
                         for e in effective]
                return sum(pr * w for pr, w in zip(projs, weights)) / max(sum(weights), 1e-9)
            return p.formula("predict_time", alpha=fit.alpha, beta1=fit.beta1,
                             beta2=fit.beta2, D=D)

        def sigma_at(D: float) -> tuple[float, float]:
            gap = min(abs(math.log2(D / d)) for d in fit.anchor_distances)
            return gap, p.formula("sigma_pct", gap=gap,
                                  temporal_sigma_pct=fitness_eval.temporal_sigma_pct)

        def quantiles(D: float) -> list[float]:
            est = time_fn(D)
            if not (est > 0 and math.isfinite(est)):
                raise ValueError(f"prediction formula gave a non-positive time ({est}); "
                                 "check formula overrides")
            return [est * math.exp(q) for q in normal_log_quantiles(sigma_at(D)[1])]

        D = prep.target
        estimate = time_fn(D)
        gap, sigma_pct = sigma_at(D)
        steps.append(
            f"Target {distance_label(D)}: {gap:.2f} doublings from nearest race; 1-sigma "
            f"error = {sigma_pct:.2f}% [{p.expr('sigma_pct')}]; bands are log-normal."
        )
        total_w = max(sum(weights), 1e-12)
        implied = [e.time * time_fn(D) / time_fn(e.distance) for e in effective]
        extras = {
            "alpha": fit.alpha, "beta1": fit.beta1, "beta2": fit.beta2,
            "beta1_pop": fit.beta1_pop, "observed_beta1": fit.observed_beta1,
            "shrinkage_weight": fit.shrinkage_weight, "sigma_pct": sigma_pct,
            "gap_doublings": gap, "temporal_sigma_pct": fitness_eval.temporal_sigma_pct,
            "fitness_delta_pct": fitness_eval.fitness_delta_pct,
            "neutral_estimate_sec": estimate,
        }
        return Engine(quantiles, fit.beta1, gap, [w / total_w for w in weights], implied,
                      steps, extras)

    # ── prediction ─────────────────────────────────────────────────────────

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        prep = self.prepare(inputs)
        engine = (self.curve_engine(prep) if p.method == "curve"
                  else self.weighted_riegel_engine(prep))
        steps = prep.steps + engine.steps
        target = prep.target
        level = p.interval_level

        neutral_q = engine.quantiles(target)
        neutral_median = neutral_q[MEDIAN_INDEX]

        # Target course conditions (DRAFT multipliers) scale the median and every band.
        target_cond = extract_conditions(inputs, prefix="target_", base_dir=self.dir)
        target_mults = compute_environmental_multipliers(target, target_cond, p)
        target_mult = target_mults["total_multiplier"]
        course_median = p.formula("course_adjusted_time", neutral_time=neutral_median,
                                  total_multiplier=target_mult)
        ratio = course_median / neutral_median
        course_q = [t * ratio for t in neutral_q]
        has_env = abs(target_mult - 1.0) > 1e-9
        if abs(target_mult - 1.0) > 0.002:
            steps.append(
                f"Target course conditions: neutral {format_time(neutral_median)} scaled to "
                f"{format_time(course_median)} ({_factor_text(target_mults)}; total "
                f"x{target_mult:.3f}); bands scaled by the same factor."
            )

        lo, hi = interval_at(course_q, level)
        r50, r95 = interval_at(course_q, 0.5), interval_at(course_q, 0.95)
        steps.append(
            f"Target {distance_label(target)}: median {format_time(course_median)}; "
            f"50% {_range_str(*r50)}; {level:.0%} {_range_str(lo, hi)}; "
            f"95% {_range_str(*r95)}."
        )

        miles = target / METERS_PER_MILE
        km = target / METERS_PER_KM
        label = distance_label(target) + (" course time" if has_env else " time")
        outcomes = [
            Outcome(label, estimate=course_median, interval=(lo, hi), fmt="time",
                    note=f"Pace: {format_time(course_median / miles)}/mi "
                         f"({format_time(course_median / km)}/km)"),
            Outcome("Target 50% range", estimate=course_median, fmt="time",
                    note=f"50%: {_range_str(*r50)}"),
            Outcome("Target 95% range", estimate=course_median, fmt="time",
                    note=f"95%: {_range_str(*r95)}"),
        ]
        if has_env:
            nlo, nhi = interval_at(neutral_q, level)
            outcomes.append(Outcome(
                "Flat/neutral equivalent", estimate=neutral_median, interval=(nlo, nhi),
                fmt="time",
                note=f"Pace: {format_time(neutral_median / miles)}/mi "
                     f"({format_time(neutral_median / km)}/km)"))
        outcomes += [
            Outcome("Pace per mile", estimate=course_median / miles,
                    interval=(lo / miles, hi / miles), fmt="time"),
            Outcome("Pace per km", estimate=course_median / km,
                    interval=(lo / km, hi / km), fmt="time"),
        ]

        benchmarks = [self._benchmark(lbl, d, common, engine.quantiles(d), level)
                      for lbl, d, common in BENCHMARKS]
        for b in benchmarks:
            if b["common"]:
                outcomes.append(Outcome(
                    COMMON_OUTCOME_LABELS[b["label"]], estimate=b["p50_sec"],
                    interval=b["_interval"], fmt="time", group="Common distances (flat)",
                    note=f"50%: {b['range50_str']} · 95%: {b['range95_str']}"))
        for b in benchmarks:
            del b["_interval"]

        step = (math.log(CURVE_MAX_M) - math.log(CURVE_MIN_M)) / (CURVE_POINTS - 1)
        curve_points = [
            self._curve_point(d, engine.quantiles(d))
            for d in (math.exp(math.log(CURVE_MIN_M) + i * step) for i in range(CURVE_POINTS))
        ]

        races_used, runner_points = [], []
        for r, w, t_i in zip(prep.races, engine.weights, engine.implied):
            d, t = r["distance"], r["time"]
            races_used.append({
                "distance": d, "distance_label": distance_label(d),
                "time_sec": round(t, 1), "time_str": format_time(t),
                "date": r["date"].isoformat() if r["date"] else None, "year": r["year"],
                "weight": round(w, 4), "implied_target_sec": round(t_i, 1),
            })
            runner_points.append({
                "distance": d, "distance_label": distance_label(d),
                "time_sec": t, "time_str": format_time(t),
                "raw_time_sec": r["raw_time"], "raw_time_str": format_time(r["raw_time"]),
                "year": r["year"],
                "pace_per_mile_str": format_time(t / (d / METERS_PER_MILE)),
            })

        extras = {
            "method": p.method,
            "exponent": engine.exponent,
            "races_used": races_used,
            "band_levels": list(BAND_LEVELS),
            "curve_points": curve_points,
            "benchmarks": benchmarks,
            "runner_points": runner_points,
            "target_distance_m": target,
            "target_label": distance_label(target),
            "gap": engine.gap,
            "target_multiplier": target_mult,
            "target_elevation_gain_m": target_cond.elevation_gain_m,
            "target_altitude_m": target_cond.altitude_m,
            "target_temp_f": target_cond.temp_f,
            **engine.extras,
            "_target_quantiles_sec": course_q,
        }
        if p.method == "curve":
            extras["course_estimate_sec"] = course_median

        return self.prediction(
            inputs=self._shown_inputs(prep, target_cond if has_env else None),
            outcomes=outcomes, steps=steps, interval_level=level, extras=extras,
        )

    # ── output helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _quantile_fields(times: list[float]) -> dict[str, float]:
        return {f"{k}_sec": round(t, 1) for k, t in zip(QUANTILE_KEYS, times)}

    def _curve_point(self, d: float, times: list[float]) -> dict[str, Any]:
        med = times[MEDIAN_INDEX]
        out: dict[str, Any] = {"distance": round(d, 1), "distance_label": distance_label(d)}
        out.update(self._quantile_fields(times))
        out["pace_mile_sec"] = round(med / (d / METERS_PER_MILE), 1)
        out["pace_km_sec"] = round(med / (d / METERS_PER_KM), 1)
        out["estimate_sec"] = round(med, 1)
        for lv in BAND_LEVELS:
            lo, hi = interval_at(times, lv)
            out[f"lo_{lv * 100:.0f}_sec"] = round(lo, 1)
            out[f"hi_{lv * 100:.0f}_sec"] = round(hi, 1)
        return out

    def _benchmark(self, label: str, d: float, common: bool, times: list[float],
                   level: float) -> dict[str, Any]:
        med = times[MEDIAN_INDEX]
        miles, km = d / METERS_PER_MILE, d / METERS_PER_KM
        lo, hi = interval_at(times, 0.8)
        out: dict[str, Any] = {"label": label, "distance_meters": d, "common": common}
        out.update(self._quantile_fields(times))
        out.update({
            "estimate_sec": round(med, 1),
            "estimate_str": format_time(med),
            "interval_str": f"{format_time(lo)} – {format_time(hi)}",
            "range50_str": _range_str(*interval_at(times, 0.5)),
            "range95_str": _range_str(*interval_at(times, 0.95)),
            "pace_per_mile_sec": round(med / miles, 1),
            "pace_per_mile_str": format_time(med / miles),
            "pace_per_km_str": format_time(med / km),
            "_interval": interval_at(times, level),
        })
        return out

    @staticmethod
    def _shown_inputs(prep: Prepared, target_cond: Any) -> dict[str, str]:
        shown: dict[str, str] = {}
        if prep.age:
            shown["age"] = str(prep.age)
        if prep.gender:
            shown["gender"] = prep.gender
        for i, r in enumerate(prep.races, 1):
            when = (f" ({r['date'].isoformat()})" if r["date"]
                    else f" ({r['year']})" if r["year"] else "")
            shown[f"race {i}"] = f"{distance_label(r['distance'])} in {format_time(r['raw_time'])}{when}"
        if prep.target_date:
            shown["target_date"] = prep.target_date.isoformat()
        elif prep.target_year:
            shown["target_year"] = str(prep.target_year)
        shown["target"] = f"{distance_label(prep.target)} ({prep.target / 1000:g} km)"
        if target_cond is not None:
            env = []
            if target_cond.elevation_gain_m:
                env.append(f"+{target_cond.elevation_gain_m:.0f}m gain")
            if target_cond.elevation_loss_m:
                env.append(f"-{target_cond.elevation_loss_m:.0f}m loss")
            if target_cond.altitude_m:
                env.append(f"{target_cond.altitude_m:.0f}m alt")
            if target_cond.temp_f is not None:
                env.append(f"{target_cond.temp_f:.0f}°F")
            shown["target_conditions"] = ", ".join(env)
        return shown

    # ── backtest ───────────────────────────────────────────────────────────

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        """Default error metrics plus coverage of the 50% / 80% / 95% bands."""
        metrics = super().score(prediction, actual)
        times = prediction.extras["_target_quantiles_sec"]
        for lv in BAND_LEVELS:
            lo, hi = interval_at(times, lv)
            metrics[f"in_{lv * 100:.0f}"] = float(lo <= actual <= hi)
        return metrics

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], float]:
        """Convert a row from data/backtest.csv into inputs dict and actual finish time."""
        races = []
        i = 0
        while True:
            i += 1
            if f"race{i}_distance" not in row:
                break
            d_val = row.get(f"race{i}_distance")
            t_val = row.get(f"race{i}_time")
            if d_val and t_val:
                race = {"distance": d_val, "time": t_val,
                        "year": _opt_int(row.get(f"race{i}_year"), f"race{i}_year")}
                if row.get(f"race{i}_date"):
                    race["date"] = row[f"race{i}_date"]
                races.append(race)
        inputs = {
            "races": races,
            "target": row["target"],
            "age": _opt_int(row.get("age"), "age"),
            "gender": row.get("gender") or None,
            "target_year": _opt_int(row.get("target_year"), "target_year"),
        }
        if row.get("target_date"):
            inputs["target_date"] = row["target_date"]
        return inputs, parse_time(row["actual_time"])

    def backtest_group(self, row: dict[str, str]) -> str | None:
        """Report backtest metrics by scenario and train/test split (see RESEARCH.md)."""
        scenario = row.get("scenario")
        split = row.get("split")
        return f"{scenario} / {split}" if scenario and split else scenario


def _factor_text(mults: dict[str, Any]) -> str:
    parts = []
    for key, name in (("elevation_factor", "elevation"), ("altitude_factor", "altitude"),
                      ("weather_factor", "weather")):
        if mults[key] != 1.0:
            parts.append(f"{name} x{mults[key]:.3f}")
    return ", ".join(parts)
