"""Shared pieces of the lichess_rating model: case features and the mixture distribution.

Used by model.py (a person's prediction) and research.py (fitting and scoring), so the
fitted coefficients mean exactly the same thing in both.

The rating at the target date is a mixture: with probability 1 - p the player plays no
more rated games in that speed before the target and keeps today's rating (Lichess
ratings only change when you play); with probability p they play, and the change has
the quantile function Q(level) of a linear quantile regression.
"""

from __future__ import annotations

import math
from typing import Sequence

# Quantile levels of the "change if you keep playing" regression (definitions, not tunables).
LEVELS = (0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975)
LEVEL_KEYS = ("q025", "q10", "q25", "q50", "q75", "q90", "q975")
HORIZONS = (30, 91, 182, 365)

# Feature names, in coefficient order (after the intercept).
FEATURES = ("activity", "experience", "below_peak", "trend", "level", "form")
ACTIVE_FEATURES = ("activity", "idle", "experience", "log_horizon")


def features(*, rating: float, games_total: float, games_28: float, days_since_last: float,
             peak: float, rating_91_ago: float, score_91: float, games_91: float,
             opp_mean_91: float | None, horizon: float, caps: dict[str, float]) -> dict[str, float]:
    """Features of one case; `caps` holds the clipping limits from config.toml.

    activity   = ln(1 + games in the last 28 days)
    experience = ln(1 + rated games so far in this speed), games capped at caps['games']
    below_peak = (peak - rating) / 100, capped at caps['below_peak'] (hundreds of points)
    trend      = (rating - rating 91 days ago) / 100, clipped to +-caps['trend']
    level      = (rating - 1500) / 100
    form       = (performance in the last 91 days - rating) / 100, clipped to +-caps['form'];
                 performance = mean opponent rating + 400 x (2 x score rate - 1); 0 with no games
    idle       = ln(1 + days since the last game)
    log_horizon= ln(horizon / 91)
    """
    clip = lambda x, lim: max(-lim, min(lim, x))
    if games_91 and opp_mean_91 is not None and not math.isnan(opp_mean_91):
        perf = opp_mean_91 + 400.0 * (2.0 * score_91 / games_91 - 1.0)
        form = clip((perf - rating) / 100.0, caps["form"])
    else:
        form = 0.0
    return {
        "activity": math.log1p(games_28),
        "experience": math.log1p(min(games_total, caps["games"])),
        "below_peak": min(max(peak - rating, 0.0) / 100.0, caps["below_peak"]),
        "trend": clip((rating - rating_91_ago) / 100.0, caps["trend"]),
        "level": (rating - 1500.0) / 100.0,
        "form": form,
        "idle": math.log1p(days_since_last),
        "log_horizon": math.log(horizon / 91.0),
    }


def linear(intercept: float, coefs: Sequence[float], names: Sequence[str], x: dict[str, float]) -> float:
    return intercept + sum(c * x[n] for c, n in zip(coefs, names))


def interpolate_horizon(horizon: float, values: dict[int, float]) -> float:
    """Linear interpolation in ln(horizon) between the fitted horizons (flat outside)."""
    hs = sorted(values)
    if horizon <= hs[0]:
        return values[hs[0]]
    if horizon >= hs[-1]:
        return values[hs[-1]]
    for a, b in zip(hs, hs[1:]):
        if a <= horizon <= b:
            w = (math.log(horizon) - math.log(a)) / (math.log(b) - math.log(a))
            return values[a] * (1 - w) + values[b] * w
    raise AssertionError


def _tail_scales(qs: Sequence[float], levels: Sequence[float]) -> tuple[float, float]:
    """Exponential tail scales beyond the outer quantiles, matched to the outer two of each side:
    P(X > x) = (1 - l_top) exp(-(x - q_top) / s_hi) for x > q_top (and the mirror below)."""
    s_lo = (qs[1] - qs[0]) / math.log(levels[1] / levels[0]) if qs[1] > qs[0] else 1.0
    s_hi = (qs[-1] - qs[-2]) / math.log((1 - levels[-2]) / (1 - levels[-1])) if qs[-1] > qs[-2] else 1.0
    return s_lo, s_hi


def active_cdf(q_values: Sequence[float], x: float, levels: Sequence[float] = LEVELS) -> float:
    """P(change <= x) for the change-if-playing distribution: piecewise linear between the
    fitted quantiles, exponential tails beyond the outer ones (see _tail_scales)."""
    qs = sorted(q_values)  # quantile crossing guard
    s_lo, s_hi = _tail_scales(qs, levels)
    if x < qs[0]:
        return levels[0] * math.exp((x - qs[0]) / s_lo)
    if x >= qs[-1]:
        return 1.0 - (1.0 - levels[-1]) * math.exp(-(x - qs[-1]) / s_hi)
    for (xa, la), (xb, lb) in zip(zip(qs, levels), zip(qs[1:], levels[1:])):
        if xa <= x < xb:
            return la + (lb - la) * (x - xa) / (xb - xa)
    return levels[-1]


def active_quantile(q_values: Sequence[float], level: float, levels: Sequence[float] = LEVELS) -> float:
    """Inverse of active_cdf."""
    qs = sorted(q_values)
    s_lo, s_hi = _tail_scales(qs, levels)
    if level <= levels[0]:
        return qs[0] + s_lo * math.log(max(level, 1e-12) / levels[0])
    if level >= levels[-1]:
        return qs[-1] - s_hi * math.log(max(1.0 - level, 1e-12) / (1.0 - levels[-1]))
    for (xa, la), (xb, lb) in zip(zip(qs, levels), zip(qs[1:], levels[1:])):
        if la <= level <= lb:
            return xa + (xb - xa) * (level - la) / (lb - la)
    return qs[-1]


def mixture_quantile(p_active: float, q_values: Sequence[float], tau: float,
                     levels: Sequence[float] = LEVELS) -> float:
    """tau-quantile of: change 0 with probability 1 - p, else the change-if-playing
    distribution (active_cdf)."""
    p0 = 1.0 - p_active
    below0 = p_active * active_cdf(q_values, -1e-9, levels)
    if tau < below0:
        return active_quantile(q_values, tau / p_active, levels)
    if tau <= below0 + p0:
        return 0.0
    return active_quantile(q_values, (tau - p0) / p_active, levels)


def mixture_exceed(p_active: float, q_values: Sequence[float], x: float) -> float:
    """P(change > x) for x >= 0: only players who keep playing can gain."""
    if x < 0:
        raise ValueError("mixture_exceed is for gains (x >= 0)")
    return p_active * (1.0 - active_cdf(q_values, x))
