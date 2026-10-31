"""Walk-forward study of division podium times (v0.8) -> RESEARCH.md.

Data: data/division_panel.csv, built by download_runsignup.build_division_panel from *every*
finisher of each edition (cached in data/raw/runsignup_full/, gitignored).

Protocol (no hindsight):
* A case is one race x distance x division x year with at least one earlier edition of the
  same race, distance and division. Only earlier editions are used.
* The expected division field size is the latest earlier edition's size (known at the start),
  not the target's actual size. A hindsight-N run is reported separately.
* Parameters are fitted on an expanding window: for each test year Y, the grid search sees
  only cases with target year < Y and is scored on year Y. Pooled test-year results are the
  out-of-sample numbers. The production defaults are then refitted on all cases (in-sample;
  flagged in the report).
* Headline cases are divisions with >= MIN_TARGET_FIELD finishers in the target year (so
  places 1-5 exist). Divisions are non-overlapping 5-year brackets plus the gender opens
  (which overlap the brackets), so cases within a race-year are correlated; the number of
  independent race editions is reported alongside.

Usage:
    python -m ballmonitor.models.race_podium.download_runsignup --full   # download + panel
    python -m ballmonitor.models.race_podium.research                    # study + backtest.csv
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from statistics import NormalDist
from typing import Any, Callable

from ballmonitor.core.stats import normal_cdf, z_for_level
from ballmonitor.core.units import format_time, parse_distance
from ballmonitor.models.race_podium.age_curves import continuous_age_factor, get_annual_aging_decline_pct

_ND = NormalDist()
MODEL_DIR = Path(__file__).resolve().parent
PANEL_CSV = MODEL_DIR / "data" / "division_panel.csv"
BACKTEST_CSV = MODEL_DIR / "data" / "backtest.csv"
RESEARCH_MD = MODEL_DIR / "RESEARCH.md"

LEVEL = 0.80
MIN_TARGET_FIELD = 5
FIRST_TEST_YEAR = 2022  # earlier target years are only ever used for fitting

# Grids for the walk-forward fit
SPREAD_GRID = [0.0, 0.03, 0.06, 0.09, 0.12, 0.15, 0.18]
DECAY_GRID = [0.4, 0.55, 0.7, 0.85, 1.0]
HALF_N_GRID = [0.0, 2.0, 5.0, 10.0, 20.0, 50.0]
PRIOR_GRID = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0]
AGE_CAP = 85  # mid-age of an open-ended bracket (75+) uses this as its upper age
S_YEAR_GRID = [x / 4 for x in range(2, 41)]  # 0.5% .. 10% in 0.25% steps
S_FIELD_GRID = [x / 2 for x in range(0, 61)]  # 0% .. 30% in 0.5% steps
FIELD_REF = 100.0  # N at which s_field applies (formula constant, also in config.toml)


@dataclass
class Edition:
    year: int
    n: int
    times: list[float]  # sorted, up to 5
    boundary_prev: float | None


@dataclass
class Series:
    race_id: int
    race_name: str
    distance: str
    division: str
    gender: str
    age_min: int
    age_max: int
    editions: list[Edition] = field(default_factory=list)


@dataclass
class Case:
    s: Series
    hist: list[Edition]
    target: Edition

    @property
    def year(self) -> int:
        return self.target.year

    @property
    def n_hat(self) -> float:
        """Plain mean of earlier division sizes (what v0.7 assumed when no field_size is given)."""
        return sum(e.n for e in self.hist) / len(self.hist)


def load_panel(path: Path = PANEL_CSV) -> dict[tuple[Any, ...], Series]:
    series: dict[tuple[Any, ...], Series] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (int(r["race_id"]), r["distance"], r["division"])
            if key not in series:
                series[key] = Series(int(r["race_id"]), r["race_name"], r["distance"], r["division"],
                                     r["gender"], int(r["age_min"]), int(r["age_max"]))
            times = [float(r[f"t{i}"]) for i in range(1, 6) if r[f"t{i}"]]
            bp = float(r["boundary_prev"]) if r["boundary_prev"] else None
            series[key].editions.append(Edition(int(r["year"]), int(r["field_size"]), times, bp))
    for s in series.values():
        s.editions.sort(key=lambda e: e.year)
    return series


def build_cases(series: dict[tuple[Any, ...], Series], min_target_field: int = MIN_TARGET_FIELD) -> list[Case]:
    cases = []
    for s in series.values():
        for i in range(1, len(s.editions)):
            if s.editions[i].n >= min_target_field:
                cases.append(Case(s, s.editions[:i], s.editions[i]))
    return cases


# ----------------------------------------------------------------------------- predictors
# Each returns (times[5] with None where undefined, sigma_log[5] or None)


def _fill(pred: list[float | None], gap: float = 30.0, min_step: float = 2.0) -> list[float]:
    """Fill places with no history from the place above (+gap) and enforce ordering."""
    out: list[float] = []
    for v in pred:
        if v is None:
            v = out[-1] + gap
        if out:
            v = max(v, out[-1] + min_step)
        out.append(v)
    return out


def pred_lag1(c: Case, n: float) -> tuple[list[float], None]:
    last = c.hist[-1].times
    return _fill([last[k] if k < len(last) else None for k in range(5)]), None


def pred_mean(c: Case, n: float) -> tuple[list[float], None]:
    out: list[float | None] = []
    for k in range(5):
        v = [e.times[k] for e in c.hist if len(e.times) > k]
        out.append(sum(v) / len(v) if v else None)
    return _fill(out), None


def pred_v07(c: Case, n: float) -> tuple[list[float], list[float]]:
    """Faithful replica of model.py v0.7 on backtest inputs (no weather given)."""
    hist = []
    for e in c.hist:
        t = list(e.times)
        while len(t) < 6:
            t.append(t[-1] + 30.0)  # missing_rank_gap_sec
        hist.append((e.n, t))
    t1 = [t[0] for _, t in hist]
    t_ref = sum(t1) / len(t1)
    n_ref = sum(nn for nn, _ in hist) / len(hist)
    gaps = [max(sum(t[r] - t[0] for _, t in hist) / len(hist), 2.0 * r) for r in range(1, 6)]
    sd = math.sqrt(sum((x - t_ref) ** 2 for x in t1) / (len(t1) - 1)) if len(t1) > 1 else 0.015 * t_ref
    f1 = t_ref * (n_ref / max(n, 1)) ** 0.05
    ft = [f1]
    prev = 0.0
    for r in range(2, 7):
        g = max(gaps[r - 2] * (n_ref / max(n, 1)) ** 0.25, prev + 2.0)
        ft.append(f1 + g)
        prev = g
    times = list(ft)
    bp = c.target.boundary_prev
    if bp is not None and c.s.age_min > 0:
        dist_m = parse_distance(c.s.distance)
        proj = bp * (1 + get_annual_aging_decline_pct(float(c.s.age_min - 1), dist_m, c.s.gender) / 100)
        pw = min(max(0.40 * normal_cdf((f1 - proj) / max(sd, 5.0)), 0.0), 0.40)
        if pw > 0:
            times = [pw * min(proj, f1) + (1 - pw) * f1]
            for r in range(2, 7):
                times.append(max(pw * ft[r - 2] + (1 - pw) * ft[r - 1], times[-1] + 2.0))
    excl = {("M", 40): 0.15, ("M", 35): 0.10, ("M", 45): 0.10, ("F", 35): 0.08, ("F", 40): 0.08}
    p = excl.get((c.s.gender, c.s.age_min), 0.0) if c.s.age_max < 90 else 0.0
    if p > 0:
        times = [(1 - p) * times[r] + p * times[r + 1] for r in range(5)] + [times[5]]
    sig = math.sqrt((sd / t_ref * 100) ** 2 + 1.5**2 + (1.5 * math.sqrt(n_ref / max(n, 1))) ** 2) / 100
    return times[:5], [sig] * 5


@lru_cache(maxsize=None)
def order_score(k: int, n: float, alpha: float = 0.375) -> float:
    """Expected standard-normal score of the k-th fastest of n (Blom 1958 approximation)."""
    n = max(n, float(k))
    return _ND.inv_cdf((k - alpha) / (n + 1 - 2 * alpha))


@dataclass
class Fit:
    spread: float = 0.10  # log-SD of division finishing times (order-statistic field-size shift)
    decay: float = 1.0  # recency weight per year back
    half_n: float = 10.0  # edition weight N / (N + half_n)
    prior_weight: float = 0.5  # editions-worth of weight given to the cross-division prior
    s_year: float = 3.0  # % 1-sigma, inter-year
    s_field: float = 5.0  # % 1-sigma at N = FIELD_REF, scales with sqrt(FIELD_REF / N)
    aging: bool = True
    p_ret: float = 0.40


def expected_n(c: Case, decay: float) -> float:
    sw = sum(decay ** (c.year - e.year) for e in c.hist)
    return sum(decay ** (c.year - e.year) * e.n for e in c.hist) / sw


def own_estimate(c: Case, k: int, n: float, fit: Fit) -> tuple[float, float]:
    """Weighted mean of earlier editions' log time at place k+1, each shifted to field size n.

    An edition with fewer than k+1 finishers contributes its slowest known place, shifted by
    the order-score difference. Returns (log time, total weight)."""
    sw = sa = 0.0
    zt = order_score(k + 1, n)
    for e in c.hist:
        m = min(k + 1, len(e.times))
        w = fit.decay ** (c.year - e.year) * e.n / (e.n + fit.half_n)
        sw += w
        sa += w * (math.log(e.times[m - 1]) + fit.spread * (zt - order_score(m, e.n)))
    return sa / sw, sw


def prior_estimate(c: Case, k: int, n: float, fit: Fit, open_hist: list[Edition] | None) -> float | None:
    """Cross-division prior: earlier gender-open winners shifted to this division's field size
    and place, times the age factor of the bracket mid-age."""
    if not open_hist or c.s.age_min <= 0:
        return None
    zt = order_score(k + 1, n)
    sw = sa = 0.0
    for e in open_hist:
        w = fit.decay ** (c.year - e.year)
        sw += w
        sa += w * (math.log(e.times[0]) + fit.spread * (zt - order_score(1, e.n)))
    mid = (c.s.age_min + min(c.s.age_max, AGE_CAP)) / 2.0
    return sa / sw + math.log(continuous_age_factor(mid, parse_distance(c.s.distance), c.s.gender))


def sigma_log(fit: Fit, n: float, weight: float) -> float:
    var = (fit.s_year**2 + fit.s_field**2 * FIELD_REF / max(n, 1.0)) * (1.0 + 1.0 / max(weight, 1e-6))
    return math.sqrt(var) / 100.0


OPEN_HIST: dict[tuple[Any, ...], list[Edition]] = {}


def open_history(c: Case) -> list[Edition] | None:
    s = OPEN_HIST.get((c.s.race_id, c.s.distance, c.s.gender))
    return [e for e in s if e.year < c.year] if s else None


def pred_v08(c: Case, n: float | None, fit: Fit) -> tuple[list[float], list[float]]:
    if n is None:
        n = expected_n(c, fit.decay)
    oh = open_history(c)
    pts: list[float | None] = []
    sig: list[float] = []
    for k in range(5):
        a, w = own_estimate(c, k, n, fit)
        pr = prior_estimate(c, k, n, fit, oh)
        if pr is not None and fit.prior_weight > 0:
            a = (w * a + fit.prior_weight * pr) / (w + fit.prior_weight)
            w += fit.prior_weight
        pts.append(math.exp(a))
        sig.append(sigma_log(fit, n, w))
    times = _fill(pts)
    bp = c.target.boundary_prev
    if fit.aging and bp is not None and c.s.age_min > 0:
        dist_m = parse_distance(c.s.distance)
        proj = bp * (1 + get_annual_aging_decline_pct(float(c.s.age_min - 1), dist_m, c.s.gender) / 100)
        pw = fit.p_ret * normal_cdf((times[0] - proj) / max(sig[0] * times[0], 5.0))
        if pw > 0:
            new = [pw * min(proj, times[0]) + (1 - pw) * times[0]]
            for r in range(1, 5):
                new.append(max(pw * times[r - 1] + (1 - pw) * times[r], new[-1] + 2.0))
            times = new
    return times, sig


# ----------------------------------------------------------------------------- scoring


def interval_score(y: float, mid: float, sig: float, z: float, alpha: float) -> float:
    """Interval score (Gneiting & Raftery 2007) on the log scale, in %."""
    ly, lm = math.log(y), math.log(mid)
    lo, hi = lm - z * sig, lm + z * sig
    s = hi - lo
    if ly < lo:
        s += 2 / alpha * (lo - ly)
    elif ly > hi:
        s += 2 / alpha * (ly - hi)
    return 100 * s


def evaluate(cases: list[Case], fn: Callable[[Case], tuple[list[float], list[float] | None]]) -> dict[str, float]:
    z = z_for_level(LEVEL)
    ae1 = ape1 = bias1 = 0.0
    ae5 = 0.0
    n5 = 0
    cov1 = cov5 = 0
    ncov5 = 0
    width1 = 0.0
    isc = 0.0
    apes = []
    for c in cases:
        pred, sig = fn(c)
        y = c.target.times
        e = pred[0] - y[0]
        ae1 += abs(e)
        bias1 += e
        ape1 += abs(e) / y[0] * 100
        apes.append(abs(e) / y[0] * 100)
        for k in range(min(5, len(y))):
            ae5 += abs(pred[k] - y[k])
            n5 += 1
        if sig is not None:
            cov1 += abs(math.log(y[0] / pred[0])) <= z * sig[0]
            width1 += 2 * z * sig[0] * 100
            isc += interval_score(y[0], pred[0], sig[0], z, 1 - LEVEL)
            for k in range(min(5, len(y))):
                cov5 += abs(math.log(y[k] / pred[k])) <= z * sig[k]
                ncov5 += 1
    m = len(cases)
    apes.sort()
    out = {"n": m, "medape1": apes[m // 2], "mae1": ae1 / m, "mape1": ape1 / m, "bias1": bias1 / m, "mae5": ae5 / max(n5, 1)}
    if ncov5:
        out.update(cov1=cov1 / m, cov5=cov5 / ncov5, width1=width1 / m, iscore=isc / m)
    return out


def _point_error(cases: list[Case], fit: Fit) -> float:
    """Mean |log error| of 1st place (point estimate before the aging-in step)."""
    tot = 0.0
    for c in cases:
        n = expected_n(c, fit.decay)
        a, w = own_estimate(c, 0, n, fit)
        pr = prior_estimate(c, 0, n, fit, open_history(c))
        if pr is not None and fit.prior_weight > 0:
            a = (w * a + fit.prior_weight * pr) / (w + fit.prior_weight)
        tot += abs(a - math.log(c.target.times[0]))
    return tot / len(cases)


POINT_GRID = {
    "spread": SPREAD_GRID,
    "decay": DECAY_GRID,
    "half_n": HALF_N_GRID,
    "prior_weight": PRIOR_GRID,
}


def fit_params(train: list[Case], aging: bool = True, fixed: dict[str, float] | None = None) -> Fit:
    """Coordinate search: point parameters by mean |log error| of 1st place, then the two
    sigma parameters by the 80% interval score of places 1-5 (a proper score: it rewards
    calibrated and narrow intervals), rescaled to 80% training coverage."""
    fit = Fit(aging=aging, **(fixed or {}))
    for _ in range(3):
        for name, grid in POINT_GRID.items():
            if fixed and name in fixed:
                continue
            best = min(grid, key=lambda v: _point_error(train, Fit(**{**fit.__dict__, name: v})))
            setattr(fit, name, best)
    z = z_for_level(LEVEL)
    resid = []  # (|log err|, FIELD_REF / N, 1 + 1/weight) for every place
    for c in train:
        n = expected_n(c, fit.decay)
        pred, _ = pred_v08(c, n, fit)
        oh = open_history(c)
        for k in range(min(5, len(c.target.times))):
            _, w = own_estimate(c, k, n, fit)
            if prior_estimate(c, k, n, fit, oh) is not None:
                w += fit.prior_weight
            resid.append((abs(math.log(c.target.times[k] / pred[k])), FIELD_REF / max(n, 1), 1 + 1 / max(w, 1e-6)))
    alpha = 1 - LEVEL

    def score(sy: float, sf: float) -> float:
        tot = 0.0
        for r, inv_n, inf in resid:
            half = z * math.sqrt((sy**2 + sf**2 * inv_n) * inf) / 100
            tot += 2 * half + (2 / alpha) * max(0.0, r - half)
        return tot

    sy, sf = 3.0, 5.0
    for _ in range(3):
        sy = min(S_YEAR_GRID, key=lambda v: score(v, sf))
        sf = min(S_FIELD_GRID, key=lambda v: score(sy, v))
    # The interval score fixes the *shape* (how sigma grows in small fields / with few
    # editions); errors are heavier-tailed than normal, so finally rescale both terms so that
    # exactly LEVEL of the training residuals fall inside their intervals.
    ratios = sorted(r / (math.sqrt((sy**2 + sf**2 * inv_n) * inf) / 100) for r, inv_n, inf in resid)
    scale = ratios[int(LEVEL * len(ratios))] / z
    fit.s_year, fit.s_field = round(sy * scale, 2), round(sf * scale, 2)
    return fit


def walk_forward(cases: list[Case], aging: bool = True, fixed: dict[str, float] | None = None) -> tuple[list[tuple[Case, list[float], list[float]]], dict[int, Fit]]:
    years = sorted({c.year for c in cases if c.year >= FIRST_TEST_YEAR})
    out = []
    fits = {}
    for y in years:
        train = [c for c in cases if c.year < y]
        test = [c for c in cases if c.year == y]
        if not train or not test:
            continue
        fit = fit_params(train, aging=aging, fixed=fixed)
        fits[y] = fit
        for c in test:
            p, s = pred_v08(c, None, fit)
            out.append((c, p, s))
    return out, fits


# ----------------------------------------------------------------------------- backtest.csv

BACKTEST_FIELDS = [
    "race", "race_id", "year", "gender", "age_min", "age_max", "distance", "field_size",
    "actual_field_size", "hist_editions", "history", "open_history", "prior_fastest_aging_in",
    "actual_time", "actual_times",
]


def _hist_str(eds: list[Edition], places: int = 5) -> str:
    return ";".join(f"{e.year}:{e.n}:" + "|".join(format_time(t) for t in e.times[:places]) for e in eds)


def build_backtest_csv(cases: list[Case], path: Path = BACKTEST_CSV) -> int:
    """One row per walk-forward case, using only information known before the target edition.

    `field_size` is left blank so the model assumes its expected field (recency-weighted mean
    of earlier editions); `actual_field_size` is for reference only and not read by the model.
    """
    rows = []
    for c in cases:
        oh = open_history(c) if c.s.age_min > 0 else None
        rows.append({
            "race": c.s.race_name, "race_id": c.s.race_id, "year": c.year, "gender": c.s.gender,
            "age_min": c.s.age_min, "age_max": c.s.age_max, "distance": c.s.distance,
            "field_size": "", "actual_field_size": c.target.n, "hist_editions": len(c.hist),
            "history": _hist_str(c.hist),
            "open_history": _hist_str(oh, 1) if oh else "",
            "prior_fastest_aging_in": (
                format_time(c.target.boundary_prev) if c.target.boundary_prev and c.s.age_min > 0 else ""
            ),
            "actual_time": format_time(c.target.times[0]),
            "actual_times": "|".join(format_time(t) for t in c.target.times),
        })
    rows.sort(key=lambda r: (r["race_id"], r["distance"], r["gender"], r["age_min"], r["year"]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=BACKTEST_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# ----------------------------------------------------------------------------- study


def _row(name: str, m: dict[str, float]) -> str:
    cov = f"{m['cov1']:.1%}" if "cov1" in m else "—"
    cov5 = f"{m['cov5']:.1%}" if "cov5" in m else "—"
    wid = f"±{m['width1'] / 2:.1f}%" if "width1" in m else "—"
    isc = f"{m['iscore']:.1f}" if "iscore" in m else "—"
    return (f"| {name} | {m['mae1']:.1f} | {m['mape1']:.2f}% | {m['medape1']:.2f}% | {m['bias1']:+.1f} "
            f"| {m['mae5']:.1f} | {cov} | {cov5} | {wid} | {isc} |")


HEADER = [
    "| model | 1st MAE (s) | 1st MAPE | 1st median APE | 1st bias (s) | places 1-5 MAE (s) "
    "| 80% cov. 1st | 80% cov. 1-5 | 80% half-width | interval score |",
    "|---|---|---|---|---|---|---|---|---|---|",
]


def set_open_hist(series: dict[tuple[Any, ...], Series]) -> None:
    OPEN_HIST.clear()
    for (rid, dist, div), s in series.items():
        if s.age_min == 0:
            OPEN_HIST[(rid, dist, s.gender)] = s.editions


def run_study() -> None:
    series = load_panel()
    set_open_hist(series)
    cases = build_cases(series)
    n_bt = build_backtest_csv(cases)
    print(f"{len(series)} division series, {len(cases)} cases; wrote {n_bt} rows to {BACKTEST_CSV.name}")

    runs = {
        "v0.8 model": walk_forward(cases),
        "v0.8 without cross-division prior": walk_forward(cases, fixed={"prior_weight": 0.0}),
        "v0.8 without field-size shift": walk_forward(cases, fixed={"spread": 0.0}),
        "v0.8 without aging-in step": walk_forward(cases, aging=False),
    }
    wf, fits = runs["v0.8 model"]
    test = [c for c, _, _ in wf]
    preds = {name: {id(c): (p, q) for c, p, q in r[0]} for name, r in runs.items()}
    v8 = preds["v0.8 model"]

    races = {c.s.race_id for c in test}
    race_eds = {(c.s.race_id, c.s.distance, c.year) for c in test}
    res = {
        "last edition (lag 1)": evaluate(test, lambda c: pred_lag1(c, c.n_hat)),
        "mean of earlier editions": evaluate(test, lambda c: pred_mean(c, c.n_hat)),
        "v0.7 model": evaluate(test, lambda c: pred_v07(c, c.n_hat)),
    }
    for name in runs:
        if name != "v0.8 model":
            res[name] = evaluate(test, lambda c, d=preds[name]: d[id(c)])
    res["**v0.8 model**"] = evaluate(test, lambda c: v8[id(c)])
    fit_by_year = fits
    hind = {
        "v0.7 model": evaluate(test, lambda c: pred_v07(c, float(c.target.n))),
        "v0.8 model": evaluate(test, lambda c: pred_v08(c, float(c.target.n), fit_by_year[c.year])),
    }
    for name, m in {**res, **{f"{k} (actual N)": v for k, v in hind.items()}}.items():
        print(f"{name:40s} MAE {m['mae1']:6.1f}  MAPE {m['mape1']:5.2f}%  cov {m.get('cov1', float('nan')):.3f}")

    strata = []
    for label, cond in [
        ("expected N < 15", lambda c: c.n_hat < 15), ("expected N 15-49", lambda c: 15 <= c.n_hat < 50),
        ("expected N >= 50", lambda c: c.n_hat >= 50), ("1 earlier edition", lambda c: len(c.hist) == 1),
        ("2-3 earlier editions", lambda c: 2 <= len(c.hist) <= 3), ("4+ earlier editions", lambda c: len(c.hist) >= 4),
        ("open divisions", lambda c: c.s.age_min == 0), ("age brackets", lambda c: c.s.age_min > 0),
        ("5k / 8k", lambda c: c.s.distance in ("5k", "8k")), ("10k / 10mi", lambda c: c.s.distance in ("10k", "10mi")),
        ("half / marathon", lambda c: c.s.distance in ("half", "marathon")),
    ]:
        sub = [c for c in test if cond(c)]
        if not sub:
            continue
        mm = evaluate(sub, lambda c: pred_mean(c, c.n_hat))
        m7 = evaluate(sub, lambda c: pred_v07(c, c.n_hat))
        m8 = evaluate(sub, lambda c: v8[id(c)])
        strata.append(f"| {label} | {len(sub)} | {mm['mape1']:.2f}% | {m7['mape1']:.2f}% | {m8['mape1']:.2f}% "
                      f"| {m7['cov1']:.1%} | {m8['cov1']:.1%} | {m8['cov5']:.1%} |")
    per_year = []
    for y, fit in sorted(fits.items()):
        sub = [c for c in test if c.year == y]
        m8 = evaluate(sub, lambda c: v8[id(c)])
        mm = evaluate(sub, lambda c: pred_mean(c, c.n_hat))
        per_year.append(
            f"| {y} | {len(sub)} | {len({(c.s.race_id, c.s.distance) for c in sub})} | {fit.spread:.2f} "
            f"| {fit.decay:.2f} | {fit.half_n:.0f} | {fit.prior_weight:.2f} | {fit.s_year:.2f}% | {fit.s_field:.1f}% "
            f"| {mm['mape1']:.2f}% | {m8['mape1']:.2f}% | {m8['cov1']:.1%} |"
        )

    final = fit_params(cases)
    final_in = evaluate(cases, lambda c: pred_v08(c, None, final))
    sens = {
        name: [(v, _point_error(cases, Fit(**{**final.__dict__, name: v}))) for v in grid]
        for name, grid in POINT_GRID.items()
    }
    print(f"final fit (all cases): {final}")
    write_report(cases, test, races, race_eds, res, hind, strata, per_year, final, final_in, sens,
                 n_series=len(series))
    print(f"wrote {RESEARCH_MD.name}")


def write_report(cases, test, races, race_eds, res, hind, strata, per_year, final, final_in, sens,
                 n_series) -> None:
    all_races = {c.s.race_id for c in cases}
    all_eds = {(c.s.race_id, c.s.distance, c.year) for c in cases}
    years = sorted({c.year for c in test})
    v7, v8, mean = res["v0.7 model"], res["**v0.8 model**"], res["mean of earlier editions"]
    lag = res["last edition (lag 1)"]
    sens_lines = []
    for name, curve in sens.items():
        sens_lines += [
            f"| {name} | " + " | ".join(f"{v:g}" for v, _ in curve) + " |",
            "|---|" + "---|" * len(curve),
            "| error | " + " | ".join(f"{e * 100:.2f}" for _, e in curve) + " |",
            "",
        ]
    lines = [
        "# Race podium study (generated by research.py; do not edit by hand)",
        "",
        "**Question:** how well can division 1st-5th place times be predicted from earlier",
        "editions of the same race, and are the 80% intervals honest?",
        "",
        "## Data",
        "",
        f"- `data/division_panel.csv`: every finisher of {len(all_races)} RunSignup races with a "
        f"usable earlier edition ({len(all_eds)} race-distance-years as targets; {n_series} division "
        "series), downloaded with all result pages (`download_runsignup.download_full_results`). "
        "The v0.7 study used only the top 150 finishers per edition, which truncated division sizes "
        "and dropped most age brackets of large races.",
        "- Divisions: M/F open plus 5-year brackets 15-19 ... 70-74 and 75+. Cleaning: finishes faster "
        "than 3:50/mile, duplicate rows, editions with < 30 finishers, and result lists filed under "
        "two distances are dropped; years with two events of one distance are skipped.",
        f"- Cases: {len(cases)} division-years with >= 1 earlier edition and >= {MIN_TARGET_FIELD} "
        "finishers in the target year (so places 1-5 exist).",
        "",
        "## Protocol",
        "",
        "- Walk-forward: a case uses only earlier editions of the same race/distance/division (and, "
        "for the cross-division prior, earlier editions of the same race's gender-open division).",
        "- The target edition's field size is not used: the model assumes the recency-weighted mean "
        "of earlier division sizes (v0.7: plain mean). Results with the actual size (a hindsight "
        "input, like knowing registrations) are shown separately.",
        f"- Parameters are refitted for each test year Y in {years[0]}-{years[-1]} on cases with "
        "target year < Y only (expanding window) and scored on year Y. Point parameters minimise "
        "mean |log error| of 1st place; the two sigma parameters minimise the 80% interval score "
        "(Gneiting & Raftery 2007) of places 1-5 and are then rescaled together so that 80% of the "
        "training residuals fall inside their intervals. Benchmarks have no fitted parameters.",
        f"- **Out-of-sample test set: {len(test)} division-years from {len(race_eds)} independent "
        f"race editions ({len(races)} races).** Divisions of one race edition share weather, course "
        "and timing, so the race-edition count is the honest sample size.",
        "",
        "## Results (out of sample, test years pooled)",
        "",
        *HEADER,
        *[_row(k, m) for k, m in res.items()],
        "",
        "With the target's actual division size (hindsight): " + "; ".join(
            f"{k}: MAPE {m['mape1']:.2f}%, 80% coverage {m['cov1']:.1%}" for k, m in hind.items()
        ) + ".",
        "",
        f"- 1st-place MAPE: last edition {lag['mape1']:.2f}%, mean of earlier editions "
        f"{mean['mape1']:.2f}%, v0.7 {v7['mape1']:.2f}%, v0.8 {v8['mape1']:.2f}% "
        f"({(1 - v8['mape1'] / mean['mape1']) * 100:.1f}% lower than the mean benchmark).",
        f"- 80% interval coverage of 1st place: v0.7 {v7['cov1']:.1%} -> v0.8 {v8['cov1']:.1%} "
        f"(places 1-5: {v7['cov5']:.1%} -> {v8['cov5']:.1%}). Lower interval score is better.",
        "- Errors are heavy-tailed (tiny earlier divisions, course changes, mislabelled events): the "
        "median APE is far below the mean. MAE in seconds is dominated by long races; MAPE is the "
        "fairer cross-distance summary.",
        "",
        "### By stratum (1st place MAPE and 80% coverage, test years)",
        "",
        "| stratum | cases | mean-benchmark MAPE | v0.7 MAPE | v0.8 MAPE | v0.7 cov. 1st | v0.8 cov. 1st | v0.8 cov. 1-5 |",
        "|---|---|---|---|---|---|---|---|",
        *strata,
        "",
        "### Per test year (parameters fitted on earlier years only)",
        "",
        "| test year | cases | race-distances | spread | decay | half_n | prior wt | s_year | s_field "
        "| mean MAPE | v0.8 MAPE | v0.8 cov. |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
        *per_year,
        "",
        "## Production defaults (refitted on all cases: in-sample)",
        "",
        f"- `time_spread` = {final.spread:g}, `recency_decay` = {final.decay:g}, "
        f"`edition_weight_half_n` = {final.half_n:g}, `prior_weight` = {final.prior_weight:g}, "
        f"`sigma_year_pct` = {final.s_year:g}, `sigma_field_pct` = {final.s_field:g} "
        f"(at N = {FIELD_REF:.0f}).",
        f"- In-sample on all {final_in['n']} cases: MAPE {final_in['mape1']:.2f}%, 80% coverage "
        f"1st {final_in['cov1']:.1%}, places 1-5 {final_in['cov5']:.1%}. `ballmonitor backtest "
        "race_podium` runs the model itself on the same cases (data/backtest.csv) and should "
        "reproduce these numbers.",
        "",
        "Sensitivity of 1st-place mean |log error| (%, all cases) to each point parameter, others "
        "at their defaults:",
        "",
        *sens_lines,
        "## Caveats",
        "",
        "- The target is the fastest division finisher. Award rules that move overall winners out of "
        "age groups are not scored (the backtest turns that step off).",
        "- Races were sampled from RunSignup's search (US, mostly small and medium local races); "
        "results may not transfer to large championship races.",
        "- Course changes, timing errors and mislabelled events are left in; they make the large-error tail.",
        "- The age factor in the cross-division prior comes from `age_curves.py`, whose curves were "
        "fitted on the earlier top-150 RunSignup download (partly overlapping races), so the prior is "
        "not entirely independent of the test data.",
        "",
    ]
    RESEARCH_MD.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    run_study()
