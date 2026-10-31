"""Bullpen run prevention: reliever ratings and expected bullpen runs (v0.6.0).

Shared by model.py and research_runs.py so the study and the model compute the same thing.

* Rating (runs per out) of a reliever = his runs on the mound per out over earlier relief
  outings, shrunk toward `runs_prior_rate` with `runs_prior_outs` pseudo-outs:
      rate = (ra_runs + runs_prior_outs * runs_prior_rate) / (ra_outs + runs_prior_outs)
  A reliever with no history gets runs_prior_rate.
* Expected outs of a reliever today (config `runs_outs_source`):
      "reported":  P(appear) (the model's blended probability) x simulated outs per
                   simulated appearance (no simulated appearance -> `runs_default_outs_per_app`)
      "simulated": simulated outs per game (total outs / simulations)
* Expected bullpen runs  E = sum_i xOuts_i * rate_i  over the pool, X = sum_i xOuts_i.
  "vs average" = E - X * runs_league_rate  (same workload pitched by a league-average pen).
  "vs usual"   = E - X * usual_rate, usual_rate = mean rating weighted by each arm's share of
                 the pool's recent relief outs (`outs` history field; no history at all ->
                 plain mean): the same bullpen at its usual usage mix, so this isolates who is
                 available / likely to pitch today.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


def parse_history(item: Mapping[str, Any], name: str) -> tuple[float, float]:
    """(ra_outs, ra_runs) of one reliever input; missing = 0 (no history). Raises ValueError."""
    try:
        outs, runs = float(item.get("ra_outs", 0) or 0), float(item.get("ra_runs", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError(f"reliever '{name}': ra_outs and ra_runs must be numbers") from None
    if outs < 0 or runs < 0 or math.isnan(outs) or math.isnan(runs):
        raise ValueError(f"reliever '{name}': ra_outs and ra_runs cannot be negative")
    return outs, runs


def reliever_rate(ra_outs: float, ra_runs: float, params: Any) -> float:
    """Shrunk runs per out from earlier relief outings (no history -> runs_prior_rate).
    Uses config formula `reliever_rating` when `params` has it (the model); the closed form
    (same as the default formula) otherwise (research_runs.py fits with plain namespaces)."""
    ra_outs, ra_runs = max(float(ra_outs or 0), 0.0), max(float(ra_runs or 0), 0.0)
    if hasattr(params, "formula"):
        return float(params.formula("reliever_rating", ra_outs=ra_outs, ra_runs=ra_runs))
    k, m = float(params.runs_prior_outs), float(params.runs_prior_rate)
    if ra_outs + k <= 0:
        return m
    return (ra_runs + k * m) / (ra_outs + k)


def expected_outs(p_appear: float, sim_apps: float, sim_outs: float, n_sims: int, params: Any) -> float:
    """Expected outs today for one reliever (see module docstring)."""
    if str(params.runs_outs_source) == "simulated":
        return sim_outs / n_sims if n_sims else 0.0
    per_app = sim_outs / sim_apps if sim_apps > 0 else float(params.runs_default_outs_per_app)
    return p_appear * per_app


def bullpen_runs(
    x_outs: Mapping[str, float],
    rates: Mapping[str, float],
    usual_outs: Mapping[str, float],
    params: Any,
) -> dict[str, float]:
    """Expected bullpen runs and the two comparisons. `usual_outs` = recent relief outs per
    arm (the `outs` history input), used only for the usual-mix weights."""
    names = list(x_outs)
    X = sum(x_outs[n] for n in names)
    E = sum(x_outs[n] * rates[n] for n in names)
    league = float(params.runs_league_rate)
    tot_usual = sum(max(float(usual_outs.get(n, 0) or 0), 0.0) for n in names)
    if tot_usual > 0:
        usual_rate = sum(max(float(usual_outs.get(n, 0) or 0), 0.0) * rates[n] for n in names) / tot_usual
    else:
        usual_rate = sum(rates[n] for n in names) / len(names) if names else league
    return {
        "expected_outs": X,
        "expected_runs": E,
        "league_runs": X * league,
        "usual_runs": X * usual_rate,
        "usual_rate": usual_rate,
        "vs_average": E - X * league,
        "vs_usual": E - X * usual_rate,
    }
