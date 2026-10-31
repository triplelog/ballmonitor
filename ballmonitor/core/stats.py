"""Small statistical helpers shared across models. Stdlib only."""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import NormalDist

STANDARD_NORMAL = NormalDist()


def z_for_level(level: float) -> float:
    """Two-sided z multiplier for a central interval, e.g. 0.8 -> 1.2816."""
    if not 0 < level < 1:
        raise ValueError(f"interval level must be in (0, 1), got {level}")
    return STANDARD_NORMAL.inv_cdf(0.5 + level / 2)


def normal_cdf(x: float, mu: float = 0.0, sd: float = 1.0) -> float:
    return NormalDist(mu, sd).cdf(x)


def logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def softmax(scores: Sequence[float], temperature: float = 1.0) -> list[float]:
    """Turn arbitrary scores into probabilities that sum to 1."""
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    m = max(scores)
    exps = [math.exp((s - m) / temperature) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


def weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    total = sum(weights)
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    return sum(v * w for v, w in zip(values, weights)) / total


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """Ordinary least squares y = a + b*x. Returns (a, b)."""
    n = len(xs)
    if n < 2:
        raise ValueError("need at least two points to fit a line")
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("x values are all identical")
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b
