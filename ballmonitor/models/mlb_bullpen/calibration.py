"""Post-simulation probability adjustments (stdlib).

The Monte Carlo simulation gives raw frequencies: P_sim(appear) and P_sim(first out of the
pen) per reliever. This module turns them into the reported probabilities:

* **appearance** -- config formula `appear_logit`, a logistic recalibration fitted on 2025:

      logit P = calib_intercept_<role> + calib_slope * logit(P_sim)
                + tendency_weight * log_ratio + blend_weight_direct * logit(P_direct)

  `log_ratio` = team bullpen-usage tendency (tendency.py); `P_direct` = the direct
  per-reliever logistic regression below (0 weight = not used).
* **first reliever** -- a softmax over the active pool of

      first_weight_sim * ln P_sim(first) + first_weight_direct * sum(first_direct_<f> * f)

  i.e. the simulated first-out-of-the-pen frequency blended with a direct conditional logit
  on pre-game features (`FIRST_FEATURES`); weights 1 / 0 = the simulation as-is.

The direct appearance model is a plain logistic regression on pre-game features
(`DIRECT_FEATURES`), P_direct = logistic(sum of direct_<feature> * feature); research.py
fits all weights on the 2025 season.
Shared by model.py and research.py so both use exactly the same features.
"""

from __future__ import annotations

import math
from typing import Any

DIRECT_FEATURES = (
    "intercept",
    "role_closer", "role_setup", "role_long",   # inferred / given role (middle = 0)
    "usage",              # ln(shrunk recent appearance rate / usage_prior_rate), as in the score
    "yesterday",          # pitched yesterday
    "back_to_back",       # pitched yesterday and the day before
    "two_days_ago",       # pitched 2 days ago but not yesterday
    "pitches_3d",         # pitches over the last 3 days / 10
    "high_workload",      # high_workload_pitches+ yesterday
    "unavailable",        # ruled out by the hard rest rules
    "starter_length",     # ln(starter_stamina / starter_stamina_default)
    "long_x_starter",     # role_long * starter_length (long men after short starts)
    "off_day_tomorrow",
    "is_home",
    "log_available",      # ln(number of available arms in the pool)
    "tendency",           # team bullpen-usage log ratio (tendency.py)
    "new_arrival",        # joined the active roster today (not on yesterday's roster)
)


FIRST_FEATURES = (
    "first_rate",         # ln(shrunk rate of being first out of the pen / first_prior_rate)
    "role_closer", "role_setup", "role_long",
    "yesterday", "back_to_back",
    "pitches_3d",         # pitches over the last 3 days / 10
    "high_workload",
    "unavailable",        # ruled out by the hard rest rules
    "long_x_starter",     # role_long * ln(starter_stamina / starter_stamina_default)
    "setup_x_starter",    # role_setup * ln(starter_stamina / starter_stamina_default)
    "new_arrival",
)


def logit(p: float, eps: float) -> float:
    p = min(max(p, eps), 1.0 - eps)
    return math.log(p / (1.0 - p))


def logistic(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def direct_features(rel: Any, *, available: bool, n_available: int, starter_stamina: float,
                    off_day_tomorrow: bool, is_home: bool, log_ratio: float, params: Any) -> list[float]:
    """Feature vector (order = DIRECT_FEATURES) for one reliever before the game."""
    p = params
    length = math.log(max(float(starter_stamina), 1.0) / float(p.starter_stamina_default))
    long_ = 1.0 if rel.role == "long" else 0.0
    two_days = 1.0 if (not rel.yesterday and len(rel.pitches_days) > 1 and rel.pitches_days[1] > 0) else 0.0
    return [
        1.0,
        1.0 if rel.role == "closer" else 0.0,
        1.0 if rel.role == "setup" else 0.0,
        long_,
        math.log(max(rel.usage_rate(p), 1e-6) / float(p.usage_prior_rate)),
        float(rel.yesterday),
        float(rel.back_to_back),
        two_days,
        rel.pitches_3d / 10.0,
        float(rel.high_workload(int(p.high_workload_pitches))),
        0.0 if available else 1.0,
        length,
        long_ * length,
        1.0 if off_day_tomorrow else 0.0,
        1.0 if is_home else 0.0,
        math.log(max(n_available, 1)),
        log_ratio,
        1.0 if getattr(rel, "new_arrival", False) else 0.0,
    ]


def direct_logit(features: list[float], params: Any) -> float:
    """sum of direct_<feature> * feature."""
    return sum(float(getattr(params, f"direct_{f}")) * x for f, x in zip(DIRECT_FEATURES, features))


def appear_probability(p_sim: float, role: str, log_ratio: float, logit_direct: float,
                       params: Any, eps: float) -> float:
    """Reported P(appear): config formula `appear_logit` through the logistic function."""
    role_key = role if role in ("closer", "setup", "middle", "long") else "middle"
    z = float(params.formula(
        "appear_logit",
        logit_sim=logit(p_sim, eps),
        role_intercept=float(getattr(params, f"calib_intercept_{role_key}")),
        log_ratio=log_ratio,
        logit_direct=logit_direct,
    ))
    return logistic(z)


def first_features(rel: Any, *, available: bool, starter_stamina: float, params: Any) -> list[float]:
    """Feature vector (order = FIRST_FEATURES) for the first-reliever direct model."""
    p = params
    k, q0 = float(p.first_prior_games), float(p.first_prior_rate)
    length = math.log(max(float(starter_stamina), 1.0) / float(p.starter_stamina_default))
    rate = (rel.firsts + k * q0) / (rel.games + k) if (rel.games + k) > 0 else q0
    return [
        math.log(max(rate, 1e-6) / q0),
        1.0 if rel.role == "closer" else 0.0,
        1.0 if rel.role == "setup" else 0.0,
        1.0 if rel.role == "long" else 0.0,
        float(rel.yesterday),
        float(rel.back_to_back),
        rel.pitches_3d / 10.0,
        float(rel.high_workload(int(p.high_workload_pitches))),
        0.0 if available else 1.0,
        (1.0 if rel.role == "long" else 0.0) * length,
        (1.0 if rel.role == "setup" else 0.0) * length,
        1.0 if getattr(rel, "new_arrival", False) else 0.0,
    ]


def first_direct_score(features: list[float], params: Any) -> float:
    """sum of first_direct_<feature> * feature."""
    return sum(float(getattr(params, f"first_direct_{f}")) * x for f, x in zip(FIRST_FEATURES, features))


def first_probabilities(p_first_sim: dict[str, float], direct_scores: dict[str, float],
                        active: dict[str, bool], params: Any, eps: float) -> dict[str, float]:
    """Softmax over active arms of first_weight_sim * ln(max(P_sim, eps))
    + first_weight_direct * direct score; inactive arms get 0."""
    ws, wd = float(params.first_weight_sim), float(params.first_weight_direct)
    score = {n: ws * math.log(max(v, eps)) + wd * direct_scores.get(n, 0.0)
             for n, v in p_first_sim.items() if active.get(n, True)}
    if not score:
        return {n: 0.0 for n in p_first_sim}
    mx = max(score.values())
    w = {n: math.exp(s - mx) for n, s in score.items()}
    tot = sum(w.values())
    return {n: w.get(n, 0.0) / tot for n in p_first_sim}
