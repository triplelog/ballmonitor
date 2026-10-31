"""Smooth curve fitting, Empirical Bayes shrinkage, and probabilistic uncertainty funnel.

Fits a continuous log-quadratic power curve across running distances:
    ln T(D) = alpha + beta1 * ln(D / D0) + beta2 * (ln(D / D0))^2
where:
    D0 = 5,000m (reference 5K anchor)
    alpha = latent velocity / overall fitness
    beta1 = personal speed-endurance tilt (shrunk toward demographic prior)
    beta2 = marathon / aerobic threshold curvature (inflection at longer distances)

Uncertainty funnels outward as distance moves further from any observed race,
pinching tightly at distances the runner has logged and widening in unobserved regimes.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ballmonitor.core.stats import weighted_mean, z_for_level
from ballmonitor.core.units import (
    METERS_PER_KM,
    METERS_PER_MILE,
    distance_label,
    format_time,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
PRIORS_FILE = DATA_DIR / "demographic_priors.json"
D0_REF = 5000.0  # 5,000 meters

# Standard benchmark distances
BENCHMARKS = [
    ("Mile", 1609.344),
    ("5K", 5000.0),
    ("8K", 8000.0),
    ("10K", 10000.0),
    ("10 Mile", 16093.44),
    ("Half Marathon", 21097.5),
    ("Marathon", 42195.0),
    ("50K", 50000.0),
]


@dataclass
class CurveFitResult:
    alpha: float
    beta1: float
    beta2: float
    beta1_pop: float
    beta2_pop: float
    shrinkage_weight: float
    observed_beta1: float | None
    anchor_distances: list[float]
    steps: list[str] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)  # final per-race weights used


def load_demographic_priors() -> dict[str, Any]:
    """Load precomputed demographic priors or provide fallback defaults."""
    if PRIORS_FILE.exists():
        try:
            with open(PRIORS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {
        "global": {"beta1": 1.0539, "beta2": 0.015, "sigma_beta1": 0.0784},
        "F_35-49": {"beta1": 1.0459, "beta2": 0.015, "sigma_beta1": 0.0681},
        "M_35-49": {"beta1": 1.0448, "beta2": 0.015, "sigma_beta1": 0.0806},
        "M_25-34": {"beta1": 1.0651, "beta2": 0.015, "sigma_beta1": 0.0834},
        "F_25-34": {"beta1": 1.0482, "beta2": 0.015, "sigma_beta1": 0.0883},
    }


def get_cohort_prior(age: int | None, gender: str | None) -> tuple[float, str] | None:
    """Lookup the demographic prior slope (beta1, label) for a runner's cohort.

    Returns None when gender is unknown (the caller then falls back to `default_exponent`).
    Only beta1 is taken from the priors file; curvature comes from `marathon_curvature`.
    """
    priors = load_demographic_priors()
    g = (gender or "").strip().upper()
    if g not in ("M", "F"):
        return None

    if age is None or age <= 0:
        cohort = f"{g}_35-49"
        if cohort in priors:
            return priors[cohort]["beta1"], f"{g} adult (35-49 cohort, age unknown)"
        return None

    if age < 25:
        bracket = "<25"
    elif age < 35:
        bracket = "25-34"
    elif age < 50:
        bracket = "35-49"
    elif age < 65:
        bracket = "50-64"
    else:
        bracket = "65+"

    cohort_key = f"{g}_{bracket}"
    if cohort_key in priors:
        return priors[cohort_key]["beta1"], f"{g} {bracket} cohort"
    return None


def _weighted_slope(xs: list[float], ys: list[float], ws: list[float]) -> float:
    """Weighted least-squares slope of ys on xs."""
    tw = sum(ws)
    mx = sum(w * x for x, w in zip(xs, ws)) / tw
    my = sum(w * y for y, w in zip(ys, ws)) / tw
    sxx = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws))
    if sxx <= 0:
        raise ValueError("cannot fit a slope: all races are at the same distance")
    return sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws)) / sxx


def fit_runner_curve(
    races: list[tuple[float, float, float]],  # (distance, time, weight)
    age: int | None = None,
    gender: str | None = None,
    *,
    fit_weight: float,
    shrinkage_prior_strength: float,
    default_exponent: float,
    marathon_curvature: float,
    min_exponent: float,
    max_exponent: float,
    use_demographic_priors: bool = True,
    off_day_tolerance_pct: float | None = None,
) -> CurveFitResult:
    """Fit the smooth log-quadratic curve with Empirical Bayes shrinkage.

    With 2+ distinct distances the runner's slope is a recency-weighted least-squares
    fit (after removing the fixed curvature term), clamped to [min_exponent,
    max_exponent], then shrunk toward the prior with weight
        w = span / (span + shrinkage_prior_strength) * fit_weight
    where span is the number of distance doublings covered by the races.
    """
    steps: list[str] = []

    if not races:
        raise ValueError("Cannot fit runner curve without at least one race result.")

    # 1. Population prior: cohort slope from data/demographic_priors.json, else default_exponent
    cohort = get_cohort_prior(age, gender) if use_demographic_priors else None
    if cohort is not None:
        beta1_pop, cohort_label = cohort
    else:
        beta1_pop = default_exponent
        cohort_label = (
            "default_exponent (no gender given)" if use_demographic_priors
            else "default_exponent (demographic priors off)"
        )
    beta2_pop = marathon_curvature

    steps.append(
        f"Population prior: {cohort_label} slope beta1 = {beta1_pop:.4f}, "
        f"curvature beta2 = marathon_curvature = {beta2_pop:.4f}."
    )

    distinct_dists = {d for d, _, _ in races}
    anchor_distances = sorted(distinct_dists)

    # Off-day weighting: a race that is much slower than the runner's best performance
    # (both converted to a 5K equivalent with the prior slope) is often a jog, a pacing
    # duty or a bad day, so it gets weight x exp(-excess% / off_day_tolerance_pct).
    if off_day_tolerance_pct and len(races) > 1:
        equiv = [
            math.log(t) - beta1_pop * math.log(d / D0_REF) - beta2_pop * math.log(d / D0_REF) ** 2
            for d, t, _ in races
        ]
        best = min(equiv)
        excess = [100.0 * (e - best) for e in equiv]
        mults = [math.exp(-x / off_day_tolerance_pct) for x in excess]
        races = [(d, t, w * m) for (d, t, w), m in zip(races, mults)]
        down = [
            f"{distance_label(d)} {format_time(t)} ({x:+.1f}% vs best, weight x{m:.2f})"
            for (d, t, _), x, m in zip(races, excess, mults) if m < 0.9
        ]
        if down:
            steps.append(
                "Off-day weighting [x exp(-excess% / off_day_tolerance_pct)]: "
                + "; ".join(down) + "."
            )
    final_weights = [w for _, _, w in races]

    # CASE A: 1 Distinct Distance
    if len(distinct_dists) == 1:
        beta1 = beta1_pop
        beta2 = beta2_pop
        alphas = [
            math.log(t) - beta1 * math.log(d / D0_REF) - beta2 * (math.log(d / D0_REF) ** 2)
            for d, t, _ in races
        ]
        alpha = weighted_mean(alphas, [w for _, _, w in races])
        d_single = races[0][0]
        steps.append(
            f"Only 1 distinct distance ({distance_label(d_single)}, {len(races)} race(s)): "
            f"anchored speed level alpha = {alpha:.4f}, using prior slope beta1 = {beta1:.4f}."
        )
        return CurveFitResult(
            alpha=alpha,
            beta1=beta1,
            beta2=beta2,
            beta1_pop=beta1_pop,
            beta2_pop=beta2_pop,
            shrinkage_weight=0.0,
            observed_beta1=None,
            anchor_distances=anchor_distances,
            steps=steps,
            weights=final_weights,
        )

    # CASE B: 2+ Distinct Distances -> weighted fit of the runner's own slope, then shrink
    xs = [math.log(d / D0_REF) for d, _, _ in races]
    ys = [math.log(t) - beta2_pop * (x**2) for (_, t, _), x in zip(races, xs)]
    ws = [w for _, _, w in races]
    obs_slope = _weighted_slope(xs, ys, ws)
    obs_clamped = min(max(obs_slope, min_exponent), max_exponent)

    span_doublings = abs(math.log2(max(distinct_dists) / min(distinct_dists)))
    w_bayes = span_doublings / (span_doublings + shrinkage_prior_strength)
    w_final = w_bayes * fit_weight

    beta1 = w_final * obs_clamped + (1.0 - w_final) * beta1_pop
    beta2 = beta2_pop

    alphas = [
        math.log(t) - beta1 * math.log(d / D0_REF) - beta2 * (math.log(d / D0_REF) ** 2)
        for d, t, _ in races
    ]
    alpha = weighted_mean(alphas, ws)

    names = ", ".join(distance_label(d) for d in anchor_distances)
    clamp_note = f" (raw {obs_slope:.4f}, clamped)" if obs_clamped != obs_slope else ""
    steps.append(
        f"Observed personal slope beta1_obs = {obs_clamped:.4f}{clamp_note} from "
        f"{len(races)} race(s) at {names} ({span_doublings:.1f} doublings span; "
        f"recency-weighted least squares)."
    )
    steps.append(
        f"Empirical Bayes shrinkage: w = span / (span + shrinkage_prior_strength) x fit_weight "
        f"= {w_final:.0%} on runner slope + {1 - w_final:.0%} on {cohort_label} prior "
        f"-> blended beta1 = {beta1:.4f}."
    )

    return CurveFitResult(
        alpha=alpha,
        beta1=beta1,
        beta2=beta2,
        beta1_pop=beta1_pop,
        beta2_pop=beta2_pop,
        shrinkage_weight=w_final,
        observed_beta1=obs_clamped,
        anchor_distances=anchor_distances,
        steps=steps,
        weights=final_weights,
    )


TimeFn = Callable[[float], float]  # target distance (m) -> neutral time (s)
SigmaFn = Callable[[float], float]  # gap (doublings) -> 1-sigma uncertainty (%)


def predict_time_and_uncertainty(
    target_distance: float,
    fit: CurveFitResult,
    *,
    time_fn: TimeFn,
    sigma_fn: SigmaFn,
    interval_level: float,
) -> tuple[float, tuple[float, float], float, float]:
    """Predict point estimate, prediction interval, 1-sigma uncertainty %, and distance gap.

    `time_fn` and `sigma_fn` are supplied by the model so that the config formulas
    (`predict_time` / `predict`, `sigma_pct`) drive every distance, not only the target.
    """
    estimate = time_fn(target_distance)
    # Distance extrapolation gap: doublings from the nearest anchor race
    gap = min(abs(math.log2(target_distance / d)) for d in fit.anchor_distances)
    sigma_pct = sigma_fn(gap)
    z = z_for_level(interval_level)
    lo = estimate * math.exp(-z * sigma_pct / 100.0)
    hi = estimate * math.exp(+z * sigma_pct / 100.0)
    return estimate, (lo, hi), sigma_pct, gap


def generate_benchmark_predictions(
    fit: CurveFitResult,
    *,
    time_fn: TimeFn,
    sigma_fn: SigmaFn,
    interval_level: float,
) -> list[dict[str, Any]]:
    """Generate predictions for common benchmark distances (Mile to 50K)."""
    out = []
    for label, dist in BENCHMARKS:
        est, (lo, hi), sigma, gap = predict_time_and_uncertainty(
            dist, fit, time_fn=time_fn, sigma_fn=sigma_fn, interval_level=interval_level
        )
        miles = dist / METERS_PER_MILE
        km = dist / METERS_PER_KM

        out.append({
            "label": label,
            "distance_meters": dist,
            "estimate_sec": round(est, 1),
            "estimate_str": format_time(est),
            "interval_sec": (round(lo, 1), round(hi, 1)),
            "interval_str": f"{format_time(lo)} – {format_time(hi)}",
            "pace_per_mile_sec": round(est / miles, 1),
            "pace_per_mile_str": format_time(est / miles),
            "pace_per_km_sec": round(est / km, 1),
            "pace_per_km_str": format_time(est / km),
            "sigma_pct": round(sigma, 2),
            "gap_doublings": round(gap, 2),
        })
    return out


def generate_dense_curve_points(
    fit: CurveFitResult,
    *,
    time_fn: TimeFn,
    sigma_fn: SigmaFn,
    points_count: int = 50,
) -> list[dict[str, Any]]:
    """Generate a dense log-spaced curve (400m to 50K) with 50% and 80% bands for UI plotting."""
    min_dist = 400.0
    max_dist = 50000.0
    log_min = math.log(min_dist)
    log_max = math.log(max_dist)
    step = (log_max - log_min) / (points_count - 1)

    points = []
    z80 = z_for_level(0.80)
    z50 = z_for_level(0.50)

    for i in range(points_count):
        d = math.exp(log_min + i * step)
        est, _, sigma, _ = predict_time_and_uncertainty(
            d, fit, time_fn=time_fn, sigma_fn=sigma_fn, interval_level=0.80
        )
        miles = d / METERS_PER_MILE
        km = d / METERS_PER_KM

        points.append({
            "distance": round(d, 1),
            "distance_label": distance_label(d),
            "estimate_sec": round(est, 1),
            "lo_80_sec": round(est * math.exp(-z80 * sigma / 100.0), 1),
            "hi_80_sec": round(est * math.exp(+z80 * sigma / 100.0), 1),
            "lo_50_sec": round(est * math.exp(-z50 * sigma / 100.0), 1),
            "hi_50_sec": round(est * math.exp(+z50 * sigma / 100.0), 1),
            "pace_mile_sec": round(est / miles, 1),
            "pace_km_sec": round(est / km, 1),
        })

    return points
