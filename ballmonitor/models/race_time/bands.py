"""Weighted Riegel point prediction and empirical uncertainty bands (v0.5.0 default).

Point prediction ("weighted Riegel"), for target distance D:
    T_i = predict(t_i, d_i, D, k)                    formula `predict`, default t * (D/d)^k
    w_i = race_weight(x_i, years_i)                  formula `race_weight`, x_i = ln(D/d_i)
    point = exp(sum w_i ln T_i / sum w_i)            (race_combination = "geometric")

Bands: the log error ln(actual / point) was measured on 2,560 train runners and its
quantiles were fitted as linear functions of three features (research_bands.py):
    q_tau = a + b_gap * gap + b_years * years + b_races / races   formula `band_log_quantile`
    (a, b_gap, b_years, b_races = params band_<p>_base/_gap/_years/_races per quantile)
    gap   = sum w_i |x_i| / sum w_i     (how far, on average, the races are from D)
    years = years since the most recent race (capped at band_max_years)
    races = number of races (capped at band_max_races)
The median is point * exp(q_50) (formula `median_time`); every other quantile is
median * exp(band_scale * (q_tau - q_50)) (formula `band_time`).

Everything here is stdlib-only; config.toml supplies every number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

# The output contract: 2.5/10/25/50/75/90/97.5% quantiles -> median + 50/80/95% bands.
QUANTILE_LEVELS = (0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975)
QUANTILE_KEYS = ("p025", "p10", "p25", "p50", "p75", "p90", "p975")
BAND_LEVELS = (0.5, 0.8, 0.95)
MEDIAN_INDEX = 3
# config.toml holds one scalar param per quantile and feature: band_<key>_<feature>,
# e.g. band_p975_gap (the text report needs scalars to stay within 78 columns).
BAND_FEATURES = ("base", "gap", "years", "races")

_STD = NormalDist()
_Z_KNOTS = [_STD.inv_cdf(t) for t in QUANTILE_LEVELS]


@dataclass
class Race:
    distance: float      # meters
    time: float          # seconds, environment-neutral
    years_before: float  # years before the target race (>= 0)


@dataclass
class WeightedRiegel:
    point: float                       # combined projection (seconds), before median shift
    implied: list[float]               # each race's projection to D (seconds)
    weights: list[float]               # normalised weights (sum to 1)
    gap: float                         # weighted mean |ln(D / d_i)|
    steps: list[str] = field(default_factory=list)


def weighted_riegel(races: list[Race], D: float, exponent: float, p: Any) -> WeightedRiegel:
    """Project every race to distance D and combine them with the race weights."""
    implied, raw_w, xs = [], [], []
    for r in races:
        x = math.log(D / r.distance)
        t = p.formula("predict", t=r.time, d=r.distance, D=D, k=exponent)
        if not (t > 0 and math.isfinite(t)):
            raise ValueError(f"formula 'predict' gave a non-positive time ({t}); check overrides")
        w = p.formula("race_weight", x=x, years=r.years_before)
        if not (w >= 0 and math.isfinite(w)):
            raise ValueError(f"formula 'race_weight' gave an invalid weight ({w})")
        implied.append(t)
        raw_w.append(w)
        xs.append(x)
    total = sum(raw_w)
    if total <= 0:
        raise ValueError("all race weights are zero; check race_weight / its parameters")
    weights = [w / total for w in raw_w]
    if p.race_combination == "arithmetic":
        point = sum(w * t for w, t in zip(weights, implied))
    else:
        point = math.exp(sum(w * math.log(t) for w, t in zip(weights, implied)))
    gap = sum(w * abs(x) for w, x in zip(weights, xs))
    return WeightedRiegel(point, implied, weights, gap)


def param_name(key: str, feature: str) -> str:
    return f"band_{key}_{feature}"


def band_coefficients(p: Any) -> list[list[float]]:
    """[base, gap, years, races] coefficient lists, one entry per quantile level."""
    return [[float(p[param_name(k, f)]) for k in QUANTILE_KEYS] for f in BAND_FEATURES]


def band_features(gap: float, years_since_last: float, n_races: int, p: Any) -> tuple[float, float, int]:
    """Cap the features at the range seen in the training data."""
    years = min(max(years_since_last, 0.0), p.band_max_years)
    races = max(1, min(n_races, p.band_max_races))
    return gap, years, races


def log_quantiles(gap: float, years: float, races: int, p: Any) -> list[float]:
    """Fitted quantiles of ln(actual / point) at QUANTILE_LEVELS (sorted, so never crossing)."""
    a, bg, by, br = band_coefficients(p)
    qs = [
        p.formula("band_log_quantile", a=a[i], b_gap=bg[i], b_years=by[i], b_races=br[i],
                  gap=gap, years=years, races=races)
        for i in range(len(QUANTILE_LEVELS))
    ]
    return sorted(qs)


def quantile_times(median: float, log_q: list[float], p: Any) -> list[float]:
    """Times (s) at QUANTILE_LEVELS around `median` via formula `band_time`."""
    q50 = log_q[MEDIAN_INDEX]
    out = [p.formula("band_time", median=median, q=q, q50=q50) for q in log_q]
    out[MEDIAN_INDEX] = median
    for i in range(1, len(out)):  # a formula override must not make the bands cross
        out[i] = max(out[i], out[i - 1])
    return out


def normal_log_quantiles(sigma_pct: float) -> list[float]:
    """Symmetric log-normal quantiles (the v0.4 curve method's sigma model)."""
    return [z * sigma_pct / 100.0 for z in _Z_KNOTS]


def time_at_level(times: list[float], tau: float) -> float:
    """Time at any quantile level tau, interpolating ln(time) linearly in normal-z space
    between the seven fitted levels (linear extrapolation beyond 2.5% / 97.5%)."""
    if not 0.0 < tau < 1.0:
        raise ValueError(f"quantile level must be between 0 and 1, got {tau}")
    z = _STD.inv_cdf(tau)
    logs = [math.log(t) for t in times]
    k = len(_Z_KNOTS)
    if z <= _Z_KNOTS[0]:
        i = 0
    elif z >= _Z_KNOTS[-1]:
        i = k - 2
    else:
        i = max(j for j in range(k - 1) if _Z_KNOTS[j] <= z)
    z0, z1 = _Z_KNOTS[i], _Z_KNOTS[i + 1]
    frac = (z - z0) / (z1 - z0)
    return math.exp(logs[i] + frac * (logs[i + 1] - logs[i]))


def interval_at(times: list[float], level: float) -> tuple[float, float]:
    """Central interval at `level` (0.8 -> 10% and 90% quantiles)."""
    return time_at_level(times, (1 - level) / 2), time_at_level(times, (1 + level) / 2)
