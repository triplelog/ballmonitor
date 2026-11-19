"""Shared, stdlib-only pieces of strength_progress: parsing a training log, the features
the model uses, and the empirical quantile bands.  research.py re-implements the same
feature definitions in numpy for fitting and then scores this code end to end.

Per exercise, from the sessions dated on or before `today`:
    index_s  = best set of the day, as a strength index      formulas `rep_index` / `duration_index`
    current  = index of the most recent session
    weeks    = (today - start) / 7, start = first session of this exercise (or `training_since`)
    freq     = sessions in the last `consistency_window_weeks` / min(window, max(weeks, 1))
    days     = days since the most recent session
    slope    = least-squares slope of ln(index) per week over the last `trend_window_weeks`
               (0 if fewer than `trend_min_sessions` sessions or they span < `trend_min_span_weeks`)
Point:   gain = expected_gain(weeks, h, pace, slope)          (log scale)
Bands:   q_tau = a + b_h sqrt(h/52) + b_nov novice + b_irr irregular + b_gap gap
         novice = exp(-weeks / gain_tau_weeks), irregular = clamp(1 - freq / consistency_ref_per_week, 0, 1),
         gap = min(days, band_gap_cap_days) / band_gap_cap_days
Median = current * exp(gain + q_50); other quantiles = median * exp(band_scale * (q_tau - q_50)).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

# Output contract (definitions, not tunables): 2.5/10/25/50/75/90/97.5% -> median + 50/80/95%.
QUANTILE_LEVELS = (0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975)
QUANTILE_KEYS = ("p025", "p10", "p25", "p50", "p75", "p90", "p975")
BAND_LEVELS = (0.5, 0.8, 0.95)
MEDIAN_INDEX = 3
BAND_FEATURES = ("base", "horizon", "novice", "irregular", "gap")
DAYS_PER_WEEK = 7.0
HORIZON_UNIT_WEEKS = 52.0  # the horizon feature is sqrt(h / 52): 1.0 at one year

_STD = NormalDist()
_Z = [_STD.inv_cdf(t) for t in QUANTILE_LEVELS]


def parse_date(value: Any, name: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ValueError(f"{name} must be a date like 2026-03-01, got {value!r}") from exc


def _num(value: Any, name: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return x


@dataclass
class Session:
    date: dt.date
    index: float      # best strength index of the day
    weight: float     # weight of that best set
    reps: float | None
    duration: float | None


@dataclass
class Exercise:
    name: str
    sessions: list[Session]  # sorted by date, one per day
    kind: str                # "reps" or "duration" (of the most recent session)


def parse_log(entries: Any, p: Any) -> dict[str, Exercise]:
    """Turn [[log]] entries into per-exercise day-best sessions (insertion order kept)."""
    if isinstance(entries, dict):
        entries = [entries]
    if not entries or not isinstance(entries, list):
        raise ValueError("inputs need a training log: [[log]] date = 2026-01-05, exercise = 'squat', "
                         "weight = 100, reps = 5  (or duration = 110 seconds instead of reps)")
    by_ex: dict[str, dict[dt.date, Session]] = {}
    for i, e in enumerate(entries, 1):
        if not isinstance(e, dict):
            raise ValueError(f"log entry {i} must be a table with date, exercise, weight, reps/duration")
        for key in ("date", "exercise", "weight"):
            if key not in e:
                raise ValueError(f"log entry {i} needs '{key}'")
        d = parse_date(e["date"], f"log entry {i} date")
        name = str(e["exercise"]).strip()
        if not name:
            raise ValueError(f"log entry {i}: exercise name is empty")
        w = _num(e["weight"], f"log entry {i} weight")
        if w <= 0:
            raise ValueError(f"log entry {i}: weight must be positive, got {w:g}")
        reps = e.get("reps")
        dur = e.get("duration")
        if (reps is None) == (dur is None):
            raise ValueError(f"log entry {i}: give exactly one of 'reps' or 'duration' (seconds)")
        if reps is not None:
            r = _num(reps, f"log entry {i} reps")
            if r < 1:
                raise ValueError(f"log entry {i}: reps must be at least 1, got {r:g}")
            idx = p.formula("rep_index", weight=w, reps=r)
            s = Session(d, idx, w, r, None)
        else:
            t = _num(dur, f"log entry {i} duration")
            if t <= 0:
                raise ValueError(f"log entry {i}: duration must be positive seconds, got {t:g}")
            idx = p.formula("duration_index", weight=w, duration=t)
            s = Session(d, idx, w, None, t)
        if not (idx > 0 and math.isfinite(idx)):
            raise ValueError(f"strength index formula gave {idx} for log entry {i}; check overrides")
        day = by_ex.setdefault(name, {})
        if d not in day or idx > day[d].index:
            day[d] = s
    out = {}
    for name, days in by_ex.items():
        sessions = [days[d] for d in sorted(days)]
        out[name] = Exercise(name, sessions, "reps" if sessions[-1].reps is not None else "duration")
    return out


@dataclass
class Features:
    current: float
    weeks: float
    freq: float
    days_since_last: float
    slope: float
    n_sessions: int
    n_window: int
    start: dt.date
    last: Session
    steps: list[str] = field(default_factory=list)


def features(ex: Exercise, today: dt.date, training_since: dt.date | None, p: Any) -> Features:
    sessions = [s for s in ex.sessions if s.date <= today]
    if not sessions:
        raise ValueError(f"{ex.name}: no logged sessions on or before {today}")
    last = sessions[-1]
    start = sessions[0].date
    if training_since is not None and training_since < start:
        start = training_since
    weeks = (today - start).days / DAYS_PER_WEEK
    window = p.consistency_window_weeks
    in_win = [s for s in sessions if (today - s.date).days < window * DAYS_PER_WEEK]
    freq = len(in_win) / min(window, max(weeks, 1.0))
    # recent trend (used by the recent_trend variant's formula; 0 when there is too little data)
    tw = [s for s in sessions if (today - s.date).days < p.trend_window_weeks * DAYS_PER_WEEK]
    slope = 0.0
    if len(tw) >= p.trend_min_sessions:
        xs = [(s.date - today).days / DAYS_PER_WEEK for s in tw]
        if max(xs) - min(xs) >= p.trend_min_span_weeks:
            ys = [math.log(s.index) for s in tw]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return Features(last.index, weeks, freq, float((today - last.date).days), slope,
                    len(sessions), len(in_win), start, last)


def param_name(key: str, feature: str) -> str:
    return f"band_{key}_{feature}"


def band_inputs(f: Features, h_weeks: float, p: Any) -> dict[str, float]:
    """The four band features (definitions in the module docstring), capped to the data range."""
    h = min(max(h_weeks, 0.0), p.max_horizon_weeks)
    return {
        "horizon": math.sqrt(h / HORIZON_UNIT_WEEKS),
        "novice": math.exp(-f.weeks / p.gain_tau_weeks),
        "irregular": min(max(1.0 - f.freq / p.consistency_ref_per_week, 0.0), 1.0),
        "gap": min(f.days_since_last, p.band_gap_cap_days) / p.band_gap_cap_days,
    }


def log_quantiles(x: dict[str, float], p: Any) -> list[float]:
    """Fitted quantiles of ln(actual / (current * exp(gain))) at QUANTILE_LEVELS (sorted)."""
    qs = []
    for key in QUANTILE_KEYS:
        c = {feat: float(p[param_name(key, feat)]) for feat in BAND_FEATURES}
        qs.append(p.formula("band_log_quantile", a=c["base"], b_h=c["horizon"], b_nov=c["novice"],
                            b_irr=c["irregular"], b_gap=c["gap"], **x))
    return sorted(qs)


def quantile_values(median: float, log_q: list[float], p: Any) -> list[float]:
    q50 = log_q[MEDIAN_INDEX]
    out = [p.formula("band_value", median=median, q=q, q50=q50) for q in log_q]
    out[MEDIAN_INDEX] = median
    for i in range(1, len(out)):  # an override must not make the bands cross
        out[i] = max(out[i], out[i - 1])
    return out


def value_at_level(values: list[float], tau: float) -> float:
    """Value at quantile level tau: ln(value) interpolated linearly in normal-z space."""
    if not 0.0 < tau < 1.0:
        raise ValueError(f"quantile level must be between 0 and 1, got {tau}")
    z = _STD.inv_cdf(tau)
    logs = [math.log(v) for v in values]
    k = len(_Z)
    if z <= _Z[0]:
        i = 0
    elif z >= _Z[-1]:
        i = k - 2
    else:
        i = max(j for j in range(k - 1) if _Z[j] <= z)
    frac = (z - _Z[i]) / (_Z[i + 1] - _Z[i])
    return math.exp(logs[i] + frac * (logs[i + 1] - logs[i]))


def interval_at(values: list[float], level: float) -> tuple[float, float]:
    return value_at_level(values, (1 - level) / 2), value_at_level(values, (1 + level) / 2)

