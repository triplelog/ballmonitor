"""Team-strength study for college_diamond (part of research.py; needs numpy).

Walk-forward: for every season and every weekly cutoff (Mondays from March 1 through the
end of the College World Series), ratings are fitted on games BEFORE the cutoff and used
to predict the games of the following 7 days. Configurations are tuned by coordinate
search on the development seasons only (baseball 2015-2019, softball 2017-2019); the test
seasons (2021-2026) are scored once with the frozen choice. The win-probability scale
(P(win) = logistic(a * rating difference)) and the runs-per-rating-unit factor are
fitted on development predictions only.

The objective is exactly ratings.py's; it is solved here as one sparse linear system
with numpy for speed (research.py checks both solvers agree).
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import asdict, replace

import numpy as np

from ballmonitor.models.college_diamond.data import Game, load_games
from ballmonitor.models.college_diamond.ratings import RatingParams, midweek_flags, transform

DEV = {"baseball": [2015, 2016, 2017, 2018, 2019], "softball": [2017, 2018, 2019]}
MATERIAL = 0.001  # dev log-loss gain needed to ship the extra midweek parameters
TEST = {"baseball": [2021, 2022, 2023, 2024, 2025, 2026], "softball": [2021, 2022, 2023, 2024, 2025, 2026]}


def fit_np(games: list[Game], flags: list[bool], p: RatingParams, as_of: dt.date,
           prior: dict[str, float] | None = None) -> tuple[dict, dict, float]:
    prior = prior or {}
    teams = sorted({g.home for g in games} | {g.away for g in games} | set(prior))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    N = 2 * n + 1
    H = 2 * n
    A = np.zeros((N, N))
    b = np.zeros(N)
    if games:
        h = np.array([idx[g.home] for g in games])
        a = np.array([idx[g.away] for g in games])
        y = np.array([transform(g.margin, p.margin_cap, p.margin_power) for g in games])
        x = np.array([0.0 if g.neutral else 1.0 for g in games])
        mid = np.array(flags, dtype=float)
        k = mid if p.split_midweek else np.zeros(len(games))
        age = np.array([(as_of - g.day).days for g in games], dtype=float)
        w = np.ones(len(games))
        if p.half_life_days > 0:
            w *= 0.5 ** (np.maximum(age, 0) / p.half_life_days)
        w *= np.where(mid > 0, p.midweek_weight, 1.0)
        w *= np.array([p.postseason_weight if g.game_type == "N" else 1.0 for g in games])
        # design row: +r_h -r_a +k m_h -k m_a +x H
        cols = [h, a, n + h, n + a, np.full(len(games), H)]
        vals = [np.ones(len(games)), -np.ones(len(games)), k, -k, x]
        for ci, vi in zip(cols, vals):
            np.add.at(b, ci, w * vi * y)
            for cj, vj in zip(cols, vals):
                np.add.at(A, (ci, cj), w * vi * vj)
    pv = np.array([prior.get(t, 0.0) for t in teams])
    lam, lm, beta = p.ridge, p.midweek_ridge, p.midweek_beta
    A[np.arange(n), np.arange(n)] += lam + lm * beta * beta
    b[:n] += lam * pv
    A[np.arange(n, 2 * n), np.arange(n, 2 * n)] += lm if p.split_midweek else 1.0
    A[np.arange(n), np.arange(n, 2 * n)] -= lm * beta if p.split_midweek else 0.0
    A[np.arange(n, 2 * n), np.arange(n)] -= lm * beta if p.split_midweek else 0.0
    A[H, H] += 1e-9
    sol = np.linalg.solve(A, b)
    r = {t: float(sol[i]) for t, i in idx.items()}
    m = {t: float(sol[n + i]) for t, i in idx.items()}
    return r, m, float(sol[H])


def season_predictions(sport: str, season: int, p: RatingParams, prior: dict[str, float]) -> list[dict]:
    games = sorted((g for g in load_games(sport) if g.season == season), key=lambda g: g.date)
    flags = midweek_flags(games)
    out = []
    day = dt.date(season, 3, 1)
    while day.weekday() != 0:
        day += dt.timedelta(days=1)
    end = max(g.day for g in games)
    while day <= end:
        nxt = day + dt.timedelta(days=7)
        train = [(g, f) for g, f in zip(games, flags) if g.day < day]
        test = [(g, f) for g, f in zip(games, flags) if day <= g.day < nxt]
        if test and train:
            r, m, H = fit_np([g for g, _ in train], [f for _, f in train], p, day, prior)
            for g, f in test:
                d = r.get(g.home, prior.get(g.home, 0.0)) - r.get(g.away, prior.get(g.away, 0.0))
                if f and p.split_midweek:
                    d += m.get(g.home, 0.0) - m.get(g.away, 0.0)
                if not g.neutral:
                    d += H
                out.append({"d": d, "margin": g.margin, "win": 1.0 if g.margin > 0 else 0.0 if g.margin < 0 else 0.5,
                            "mid": f, "type": g.game_type, "week": (day - dt.date(season, 3, 1)).days // 7,
                            "season": season})
        day = nxt
    return out


def final_ratings(sport: str, season: int, p: RatingParams, prior: dict[str, float]) -> dict[str, float]:
    games = [g for g in load_games(sport) if g.season == season]
    end = max(g.day for g in games) + dt.timedelta(days=1)
    r, _, _ = fit_np(games, midweek_flags(games), replace(p, half_life_days=0.0), end, prior)
    return r


def all_predictions(sport: str, seasons: list[int], p: RatingParams) -> list[dict]:
    out = []
    all_seasons = sorted({g.season for g in load_games(sport)})
    prev = None
    priors: dict[int, dict] = {}
    for s in all_seasons:
        if s > max(seasons):
            break
        prior = {}
        if p.prior_carry > 0 and prev is not None and prev in priors:
            mean = sum(priors[prev].values()) / max(len(priors[prev]), 1)
            prior = {t: p.prior_carry * (v - mean) for t, v in priors[prev].items()}
        if s in seasons:
            out += season_predictions(sport, s, p, prior)
        if p.prior_carry > 0:
            priors[s] = final_ratings(sport, s, p, prior)
        prev = s
    return out


def fit_scale(preds: list[dict]) -> float:
    """MLE of a in P(home win) = logistic(a * d) (Newton steps; ties dropped)."""
    d = np.array([q["d"] for q in preds if q["win"] != 0.5])
    y = np.array([q["win"] for q in preds if q["win"] != 0.5])
    a = 0.3
    for _ in range(50):
        pr = 1 / (1 + np.exp(-a * d))
        g = np.sum((y - pr) * d)
        hss = -np.sum(pr * (1 - pr) * d * d)
        step = g / hss
        a -= step
        if abs(step) < 1e-9:
            break
    return float(a)


def fit_runs(preds: list[dict]) -> float:
    d = np.array([q["d"] for q in preds])
    m = np.array([q["margin"] for q in preds])
    return float(np.sum(d * m) / np.sum(d * d))


def score(preds: list[dict], a: float, c: float) -> dict:
    if not preds:
        return {}
    d = np.array([q["d"] for q in preds])
    y = np.array([q["win"] for q in preds])
    m = np.array([q["margin"] for q in preds])
    keep = y != 0.5
    pr = np.clip(1 / (1 + np.exp(-a * d)), 1e-6, 1 - 1e-6)
    ll = -np.mean(y[keep] * np.log(pr[keep]) + (1 - y[keep]) * np.log(1 - pr[keep]))
    br = np.mean((pr[keep] - y[keep]) ** 2)
    rmse = math.sqrt(np.mean((c * d - m) ** 2))
    acc = np.mean((pr[keep] > 0.5) == (y[keep] == 1))
    return {"games": int(keep.sum()), "log_loss": float(ll), "brier": float(br), "rmse_runs": rmse,
            "accuracy": float(acc)}


def evaluate(sport: str, p: RatingParams, seasons: list[int], scale_from: list[dict] | None = None):
    preds = all_predictions(sport, seasons, p)
    base = scale_from if scale_from is not None else preds
    a, c = fit_scale(base), fit_runs(base)
    return preds, a, c


SEARCH = {
    "margin_cap": [4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 100.0],
    "margin_power": [0.5, 0.7, 1.0],
    "ridge": [1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 16.0],
    "prior_carry": [0.0, 0.3, 0.5, 0.7, 0.85, 1.0],
    "half_life_days": [0.0, 30.0, 60.0, 120.0, 240.0],
    "midweek_weight": [0.25, 0.5, 0.75, 1.0],
    "midweek_ridge": [2.0, 5.0, 10.0, 25.0],
    "midweek_beta": [-0.2, 0.0, 0.2, 0.4, 0.6],
}


def tune(sport: str, start: RatingParams, keys: list[str], log=print) -> tuple[RatingParams, list]:
    """Coordinate search on development seasons, minimising log loss (scale refit each time)."""
    seasons = DEV[sport]
    trail = []
    best = start
    preds, a, c = evaluate(sport, best, seasons)
    best_ll = score(preds, a, c)["log_loss"]
    for rnd in range(2):
        improved = False
        for key in keys:
            for v in SEARCH[key]:
                if getattr(best, key) == v:
                    continue
                cand = replace(best, **{key: v})
                preds, a, c = evaluate(sport, cand, seasons)
                ll = score(preds, a, c)["log_loss"]
                trail.append({"round": rnd, key: v, "dev_log_loss": round(ll, 5)})
                if ll < best_ll - 1e-5:
                    best, best_ll, improved = cand, ll, True
                    log(f"    {sport}: {key}={v} -> dev log loss {ll:.5f}")
        if not improved:
            break
    return best, trail


def run(log=print) -> dict:
    result: dict = {"dev": DEV, "test": TEST, "sports": {}}
    for sport in ("baseball", "softball"):
        have = {g.season for g in load_games(sport)}
        dev = [s for s in DEV[sport] if s in have]
        test = [s for s in TEST[sport] if s in have]
        DEV[sport], TEST[sport] = dev, test
        log(f"  {sport}: dev {dev}, test {test}")
        baseline = RatingParams(margin_cap=100.0, margin_power=1.0, ridge=4.0, split_midweek=False,
                                midweek_weight=1.0, half_life_days=0.0, prior_carry=0.0)
        no_split, trail1 = tune(sport, baseline, ["margin_cap", "margin_power", "ridge", "prior_carry",
                                                  "half_life_days", "midweek_weight"], log)
        split_start = replace(no_split, split_midweek=True, midweek_weight=1.0)
        with_split, trail2 = tune(sport, split_start, ["midweek_ridge", "midweek_beta", "midweek_weight",
                                                       "ridge", "margin_cap"], log)
        configs = {
            "baseline (raw margin ridge)": baseline,
            "+ margin compression / prior / recency (no midweek split)": no_split,
            "+ per-team midweek offset": with_split,
            "midweek split, no preseason prior": replace(with_split, prior_carry=0.0),
            "midweek split, no margin compression": replace(with_split, margin_cap=100.0, margin_power=1.0),
        }
        rows = {}
        for name, p in configs.items():
            dev_preds, a, c = evaluate(sport, p, dev)
            test_preds = all_predictions(sport, test, p)
            rows[name] = {
                "params": asdict(p), "scale_a": a, "runs_per_unit": c,
                "dev": score(dev_preds, a, c), "test": score(test_preds, a, c),
                "test_weekend": score([q for q in test_preds if not q["mid"] and q["type"] != "N"], a, c),
                "test_midweek": score([q for q in test_preds if q["mid"]], a, c),
                "test_postseason": score([q for q in test_preds if q["type"] == "N"], a, c),
                "test_by_season": {s: score([q for q in test_preds if q["season"] == s], a, c) for s in test},
                "test_early": score([q for q in test_preds if q["week"] < 4], a, c),
            }
            log(f"  {sport} {name}: test {rows[name]['test']}")
        # The shipped default: the midweek split only if it lowers DEV log loss materially.
        dev_ns = rows["+ margin compression / prior / recency (no midweek split)"]["dev"]["log_loss"]
        dev_ws = rows["+ per-team midweek offset"]["dev"]["log_loss"]
        chosen = with_split if dev_ws < dev_ns - MATERIAL else no_split
        # Separate win-probability scales for midweek and weekend games (dev fit).
        dp = all_predictions(sport, dev, chosen)
        a_mid = fit_scale([q for q in dp if q["mid"]])
        a_wkd = fit_scale([q for q in dp if not q["mid"]])
        result["sports"][sport] = {"configs": rows, "trail": trail1 + trail2, "chosen": asdict(chosen),
                                   "chosen_name": "midweek split" if chosen is with_split else "no midweek split",
                                   "scale_midweek": a_mid, "scale_weekend": a_wkd,
                                   "split_params": asdict(with_split)}
    return result
