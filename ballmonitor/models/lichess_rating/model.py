"""Lichess rating progress: the rating on a future date, with its range.

Two fitted parts (research.py -> RESEARCH.md; coefficients in config.toml):
  1. p = chance of playing at least one more rated game in this speed before the target
     date (formula p_active). If not, the rating stays where it is.
  2. If they play, the change has quantiles at 2.5 ... 97.5% from a linear quantile
     regression on the features in dist.py (rating level, experience, activity, distance
     below peak, 3-month trend, recent results, ln(horizon)).
The answer is the mixture of the two. See MODEL.md.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.models.lichess_rating.dist import (
    ACTIVE_FEATURES, FEATURES, LEVEL_KEYS, LEVELS, active_cdf, features, mixture_exceed, mixture_quantile,
)

BANDS = {0.5: (0.25, 0.75), 0.8: (0.1, 0.9), 0.95: (0.025, 0.975)}
SHOWN = (0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975)
SPEEDS = ("blitz", "bullet", "rapid", "classical")


def _num(inputs: dict, key: str, default: float | None = None, lo: float | None = 0.0) -> float:
    value = inputs.get(key, default)
    if value is None or value == "":
        raise ValueError(f"input '{key}' is required")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"input '{key}' must be a number, got {value!r}") from None
    if lo is not None and x < lo:
        raise ValueError(f"input '{key}' must be >= {lo:g}, got {x:g}")
    return x


def _date(value: Any, key: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"input '{key}' must be a date (YYYY-MM-DD), got {value!r}") from None


class LichessRatingModel(BaseModel):
    def _horizon(self, inputs: dict) -> tuple[int, str]:
        if inputs.get("target_date") not in (None, ""):
            start = _date(inputs.get("as_of", dt.date.today()), "as_of")
            target = _date(inputs["target_date"], "target_date")
            days = (target - start).days
            label = target.isoformat()
        else:
            days = int(_num(inputs, "horizon_days"))
            label = f"in {days} days"
        if days < 1:
            raise ValueError("the target date must be after today (as_of)")
        return days, label

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        rating = _num(inputs, "rating", lo=400)
        speed = str(inputs.get("speed", "blitz")).lower()
        if speed not in SPEEDS:
            raise ValueError(f"input 'speed' must be one of {', '.join(SPEEDS)}")
        horizon, target_label = self._horizon(inputs)
        games_total = _num(inputs, "games_total")
        games_28 = _num(inputs, "games_last_28_days")
        games_91 = _num(inputs, "games_last_91_days", default=games_28)
        if games_91 < games_28:
            raise ValueError("games_last_91_days can't be fewer than games_last_28_days")
        days_since_last = _num(inputs, "days_since_last_game", default=0.0 if games_28 else None)
        peak = _num(inputs, "peak_rating", default=rating, lo=400)
        rating_91 = _num(inputs, "rating_91_days_ago", default=rating, lo=400)
        score_91 = _num(inputs, "score_last_91_days", default=games_91 / 2)
        if score_91 > games_91:
            raise ValueError("score_last_91_days can't be more than games_last_91_days")
        opp_mean = inputs.get("opponents_avg_last_91_days")
        opp_mean = rating if opp_mean in (None, "") else _num(inputs, "opponents_avg_last_91_days", lo=400)
        keep_playing = bool(inputs.get("keep_playing", False))
        goal = inputs.get("goal_rating")

        caps = {"games": p.cap_games, "below_peak": p.cap_below_peak, "trend": p.cap_trend, "form": p.cap_form}
        x = features(rating=rating, games_total=games_total, games_28=games_28,
                     days_since_last=days_since_last, peak=max(peak, rating), rating_91_ago=rating_91,
                     score_91=score_91, games_91=games_91, opp_mean_91=opp_mean, horizon=horizon, caps=caps)
        steps = [
            f"Horizon {horizon} days. Features (dist.features): "
            + ", ".join(f"{k} = {x[k]:.2f}" for k in FEATURES + ("idle", "log_horizon")) + ".",
        ]
        if keep_playing:
            p_active = 1.0
            steps.append("keep_playing = true: assume at least one more rated game (p = 1).")
        else:
            p_active = p.formula("p_active", **{k: x[k] for k in ACTIVE_FEATURES})
            steps.append(f"Chance of playing again before the target: p = {p_active:.3f} [{p.expr('p_active')}].")

        q = {}
        for key in LEVEL_KEYS:
            q[key] = getattr(p, f"change_{key}_intercept") + sum(
                getattr(p, f"change_{key}_{n}") * x[n] for n in FEATURES + ("log_horizon",))
        med = q["q50"]
        qa = sorted(med + p.band_scale * (q[k] - med) for k in LEVEL_KEYS)
        steps.append("Change if playing (quantile regression, x band_scale "
                     f"{p.band_scale:g} around the median): "
                     + ", ".join(f"{lvl * 100:g}% {v:+.0f}" for lvl, v in zip(LEVELS, qa)) + " points.")

        quant = {tau: mixture_quantile(p_active, qa, tau) for tau in SHOWN}
        steps.append(f"Mixture: rating stays with probability {1 - p_active:.3f}; quantiles of the "
                     "change " + ", ".join(f"{t * 100:g}% {quant[t]:+.0f}" for t in SHOWN) + ".")
        lo_t, hi_t = BANDS[p.interval_level]
        outcomes = [Outcome(f"Rating on {target_label}" if inputs.get("target_date") else f"Rating {target_label}",
                            estimate=rating + quant[0.5],
                            interval=(rating + quant[lo_t], rating + quant[hi_t]), fmt="int",
                            note=f"median, {p.interval_level:.0%} range")]
        for t in SHOWN:
            if t != 0.5:
                outcomes.append(Outcome(f"{t * 100:g}th percentile", estimate=rating + quant[t], fmt="int",
                                        group="Range"))
        outcomes.append(Outcome("Plays again in this speed", probability=p_active, group="Chances"))
        outcomes.append(Outcome("Higher than today", probability=mixture_exceed(p_active, qa, 0.0), group="Chances"))
        step = p.milestone_step
        next_m = math.floor(rating / step + 1) * step
        for m in (next_m, next_m + step):
            outcomes.append(Outcome(f"Reaches {m:.0f}", probability=mixture_exceed(p_active, qa, m - rating),
                                    group="Chances", note="on the target date"))
        if goal not in (None, ""):
            g = _num(inputs, "goal_rating", lo=400)
            if g > rating:
                prob = mixture_exceed(p_active, qa, g - rating)
            else:  # at or below today's rating: only a drop below the goal misses it
                prob = 1.0 - p_active * active_cdf(qa, g - rating - 1e-9)
            outcomes.append(Outcome(f"At or above goal {g:.0f}", probability=prob, group="Chances"))

        shown_inputs = {"speed": speed, "rating": f"{rating:.0f}", "target": target_label,
                        "games so far": f"{games_total:.0f}", "games last 28 days": f"{games_28:.0f}",
                        "games last 91 days": f"{games_91:.0f}", "days since last game": f"{days_since_last:.0f}",
                        "peak rating": f"{max(peak, rating):.0f}", "rating 91 days ago": f"{rating_91:.0f}",
                        "score last 91 days": f"{score_91:g} / {games_91:.0f}", "keep playing": str(keep_playing)}
        if speed != "blitz":
            steps.append(f"Note: fitted on blitz; {speed} uses the same coefficients (RESEARCH.md scores bullet/classical).")
        return self.prediction(inputs=shown_inputs, outcomes=outcomes, steps=steps,
                               interval_level=p.interval_level,
                               extras={"p_active": p_active, "change_if_playing": qa, "features": x,
                                       "quantiles": quant, "horizon": horizon})

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], Any]:
        inputs = {
            "rating": row["rating"], "speed": row["speed"], "horizon_days": row["horizon_days"],
            "games_total": row["games_total"], "games_last_28_days": row["games_28"],
            "games_last_91_days": row["games_91"], "days_since_last_game": row["days_since_last"],
            "peak_rating": row["peak"], "rating_91_days_ago": row["rating_91_ago"],
            "score_last_91_days": row["score_91"],
            "opponents_avg_last_91_days": row["opp_mean_91"] or None,
        }
        return inputs, float(row["actual_rating"])

    def backtest_group(self, row: dict[str, str]) -> str | None:
        return f"{row['speed']} {int(row['horizon_days']):>3} days"

