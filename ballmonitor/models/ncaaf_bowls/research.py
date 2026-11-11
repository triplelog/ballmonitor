"""Accuracy study for ncaaf_bowls -> RESEARCH.md (generated; never edit by hand).

    python -m ballmonitor.models.ncaaf_bowls.research_data        # once: past seasons from ESPN
    python -m ballmonitor.models.ncaaf_bowls.research             # all parts + RESEARCH.md
    python -m ballmonitor.models.ncaaf_bowls.research committee   # one part (+ RESEARCH.md)
    python -m ballmonitor.models.ncaaf_bowls.research report      # RESEARCH.md from saved JSON

Parts (each saves data/research/<part>.json):
  games      one game: rating gap -> win probability (margin_sd, home_field_points), the
             results-only rating and FPI/results blends, how far ahead; writes data/backtest.csv
  wins       the rest of a season: are the simulated win totals too narrow? fits
             rating_uncertainty_points
  committee  the resume score vs. the committee's real final top 25; fits the resume_* weights
             and resume_noise_points
  season     the season simulator itself on 2024 and 2025 from four dates each: playoff field
             and conference champions, old defaults vs. new vs. ESPN's own numbers

Every fitted number is tested walk-forward: fitted on the seasons before the test season only.
Needs numpy and scipy (`pip install -e '.[data]'`).
"""

from __future__ import annotations

import collections
import csv
import json
import math
import random
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr

MODEL_DIR = Path(__file__).resolve().parent
HIST = MODEL_DIR / "data" / "historical"
OUT = MODEL_DIR / "data" / "research"
PARTS = ("games", "wins", "committee", "season")

SEASONS = list(range(2016, 2026))
FIRST_TEST = 2019            # walk-forward tests start here (three seasons to fit on)
FIRST_SNAPSHOT = 2           # ESPN's "week 1" FPI was recomputed in December in some seasons
# The values this study started from (config.toml 0.4.3).
OLD = {"home_field_points": 2.5, "margin_sd": 14.0, "fcs_opponent_rating": -21.7,
       "resume_win_pct_weight": 65.0, "resume_loss_penalty_scale": 3.5,
       "resume_loss_penalty_exponent": 1.5, "resume_power_weight": 1.0,
       "resume_conf_champ_bonus": 8.0, "resume_p4_champ_bonus": 3.0, "resume_power4_bonus": 4.0}
POWER = {"SEC", "Big Ten", "Big 12", "ACC"}
NOTRE_DAME = "87"            # ESPN team id


# ----------------------------------------------------------------------------- data

def _rows(name: str) -> list[dict]:
    path = HIST / name
    if not path.exists():
        raise SystemExit(f"{path} missing: run `python -m ballmonitor.models.ncaaf_bowls.research_data`")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


class Data:
    """games.csv + fpi_weekly.csv. snap[(season, n)] = FPI after week n's games (see
    research_data.py for why the week label, not the timestamp, is what can be trusted)."""

    def __init__(self) -> None:
        self.games = _rows("games.csv")
        for g in self.games:
            for k in ("season", "season_type", "week", "home_score", "away_score"):
                g[k] = int(g[k])
            for k in ("home_fbs", "away_fbs", "neutral", "conf_game", "title_game"):
                g[k] = g[k] == "1"
        self.snap: dict[tuple[int, int], dict[str, float]] = collections.defaultdict(dict)
        self.espn: dict[tuple[int, int], dict[str, dict]] = collections.defaultdict(dict)
        for r in _rows("fpi_weekly.csv"):
            if r["season_type"] != "2":
                continue
            key = (int(r["season"]), int(r["week"]))
            self.snap[key][r["team_id"]] = float(r["fpi"])
            self.espn[key][r["team_id"]] = r
        self.last_week = {s: max(w for (ss, w) in self.snap if ss == s) for s in SEASONS}
        self.name = {}
        for g in self.games:
            self.name[g["home_id"]] = g["home"]
            self.name[g["away_id"]] = g["away"]
        self.cfp: dict[int, dict[str, int]] = collections.defaultdict(dict)
        self.poll_date: dict[int, str] = {}
        for r in _rows("cfp_rankings.csv"):
            self.cfp[int(r["season"])][r["team_id"]] = int(r["rank"])
            self.poll_date[int(r["season"])] = r["poll_date"]

    def game_week(self, g: dict) -> int:
        """Bowls and playoff games count as the week after the last regular-season snapshot."""
        return g["week"] if g["season_type"] == 2 else self.last_week[g["season"]] + 1

    def game_table(self, lag: int) -> np.ndarray:
        """FBS-vs-FBS games with the FPI from `lag` weeks before: columns season, week,
        rating gap (home - away), home (1/0), margin, index into self.games."""
        out = []
        for i, g in enumerate(self.games):
            if not (g["home_fbs"] and g["away_fbs"]) or g["home_score"] == g["away_score"]:
                continue
            w = self.game_week(g)
            f = self.snap.get((g["season"], w - lag))
            if f is None or w - lag < FIRST_SNAPSHOT or g["home_id"] not in f or g["away_id"] not in f:
                continue
            out.append((g["season"], w, f[g["home_id"]] - f[g["away_id"]], 0 if g["neutral"] else 1,
                        g["home_score"] - g["away_score"], i))
        return np.array(out, float)


def game_metrics(a: np.ndarray, hfa: float, sd: float) -> dict:
    p = np.clip(ndtr((a[:, 2] + hfa * a[:, 3]) / sd), 1e-9, 1 - 1e-9)
    y = a[:, 4] > 0
    return {"n": int(len(a)), "brier": float(np.mean((p - y) ** 2)),
            "log_loss": float(-np.mean(np.where(y, np.log(p), np.log(1 - p)))),
            "accuracy": float(np.mean((p > 0.5) == y))}


def fit_game(a: np.ndarray) -> tuple[float, float]:
    """Home field = mean (margin - rating gap) at home sites; SD = the one with the best log loss."""
    hfa = float(np.mean((a[:, 4] - a[:, 2])[a[:, 3] == 1]))
    sd = min(np.arange(10.0, 22.01, 0.1), key=lambda s: game_metrics(a, hfa, s)["log_loss"])
    return round(hfa, 2), round(float(sd), 1)


# ----------------------------------------------------------------------------- part: games

def part_games(d: Data) -> dict:
    a = d.game_table(1)
    res: dict = {"n_games": int(len(a)), "seasons": len(SEASONS)}

    # hindsight check: the same-week snapshot (which already contains the game) must look too good
    res["placebo_same_week"] = game_metrics(d.game_table(0), OLD["home_field_points"], OLD["margin_sd"])
    res["old_all"] = game_metrics(a, OLD["home_field_points"], OLD["margin_sd"])
    res["fit_all"] = dict(zip(("home_field_points", "margin_sd"), fit_game(a)))
    res["margin_residual_sd"] = float(np.std(a[:, 4] - a[:, 2] - res["fit_all"]["home_field_points"] * a[:, 3]))

    wf = []
    for s in SEASONS:
        if s < FIRST_TEST:
            continue
        hfa, sd = fit_game(a[a[:, 0] < s])
        test = a[a[:, 0] == s]
        wf.append({"season": s, "fit_home": hfa, "fit_sd": sd,
                   "old": game_metrics(test, OLD["home_field_points"], OLD["margin_sd"]),
                   "fitted": game_metrics(test, hfa, sd)})
    res["walk_forward"] = wf

    # calibration of the old defaults: favourite's predicted chance vs how often it won
    p = ndtr((a[:, 2] + OLD["home_field_points"] * a[:, 3]) / OLD["margin_sd"])
    fav = np.maximum(p, 1 - p)
    won = np.where(p >= 0.5, a[:, 4] > 0, a[:, 4] < 0)
    res["calibration"] = [{"lo": lo, "hi": hi, "n": int(m.sum()), "predicted": float(fav[m].mean()),
                           "actual": float(won[m].mean())}
                          for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, .95), (.95, 1.001))
                          for m in [(fav >= lo) & (fav < hi)]]

    # how far ahead: the same games predicted from older ratings
    res["horizon"] = []
    for lag in (1, 2, 3, 4, 6, 8):
        t = d.game_table(lag)
        res["horizon"].append({"weeks_ahead": lag, **game_metrics(t, OLD["home_field_points"], OLD["margin_sd"]),
                               "best_sd": fit_game(t)[1]})
    late = []
    for lag in (1, 2, 3, 4):
        t = d.game_table(lag)
        t = t[(t[:, 1] - lag >= 8)]
        late.append({"weeks_ahead": lag, "n": int(len(t)), "best_sd": fit_game(t)[1]})
    res["horizon_from_week_8"] = late

    res["blend"] = _blend(d)
    _write_backtest_csv(d, a)
    return res


def _blend(d: Data) -> dict:
    """FPI vs the model's own results-only rating (fetch.py's fit on the season so far) vs mixes."""
    from ballmonitor.models.ncaaf_bowls.fetch import _fit_results_rating, _rating_params
    params = _rating_params(MODEL_DIR)
    rows = []
    for s in SEASONS:
        gs = [g for g in d.games if g["season"] == s and g["season_type"] == 2]
        for w in range(3, d.last_week[s]):
            f = d.snap.get((s, w))
            if not f:
                continue
            past = [{"home": g["home_id"], "away": g["away_id"], "home_score": g["home_score"],
                     "away_score": g["away_score"], "neutral": g["neutral"]} for g in gs if g["week"] <= w]
            rr, _ = _fit_results_rating(past, set(f), params)
            for g in gs:
                if g["week"] == w + 1 and g["home_id"] in f and g["away_id"] in f and g["home_score"] != g["away_score"]:
                    rows.append((s, w, f[g["home_id"]] - f[g["away_id"]], rr[g["home_id"]] - rr[g["away_id"]],
                                 0 if g["neutral"] else 1, g["home_score"] - g["away_score"]))
    b = np.array(rows, float)

    def m(x: np.ndarray, w_fpi: float) -> dict:
        t = np.column_stack([x[:, 0], x[:, 1], w_fpi * x[:, 2] + (1 - w_fpi) * x[:, 3], x[:, 4], x[:, 5]])
        return game_metrics(t, OLD["home_field_points"], OLD["margin_sd"])

    out = {"n": int(len(b)), "weights": []}
    for w_fpi in (1.0, 0.85, 0.7, 0.5, 0.0):
        better = sum(m(b[b[:, 0] == s], w_fpi)["log_loss"] < m(b[b[:, 0] == s], 1.0)["log_loss"] for s in SEASONS)
        out["weights"].append({"fpi_weight": w_fpi, **m(b, w_fpi), "seasons_better_than_fpi": int(better)})
    return out


def _write_backtest_csv(d: Data, a: np.ndarray) -> None:
    path = MODEL_DIR / "data" / "backtest.csv"
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["season", "week", "kind", "home", "away", "home_rating", "away_rating", "site", "winner"])
        for row in a:
            g = d.games[int(row[5])]
            wk = d.game_week(g)
            f = d.snap[(g["season"], wk - 1)]
            kind = "postseason" if g["season_type"] == 3 else ("title game" if g["title_game"] else "regular season")
            w.writerow([g["season"], wk, kind, g["home"], g["away"], f[g["home_id"]], f[g["away_id"]],
                        "neutral" if g["neutral"] else "home", "home" if row[4] > 0 else "away"])


# ----------------------------------------------------------------------------- part: wins

_NODES, _WTS = np.polynomial.hermite_e.hermegauss(21)
_WTS = _WTS / _WTS.sum()
WIN_SEASONS = [s for s in SEASONS if s != 2020]     # 2020: shortened, rescheduled season
WIN_WEEKS = list(range(2, 13))
SIGMAS = [0.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]


def _remaining(d: Data, s: int, w: int) -> dict[str, dict]:
    """Per FBS team after week w: wins so far and its remaining regular-season games as
    (rating gap incl. home field, won)."""
    f = d.snap[(s, w)]
    t: dict[str, dict] = {x: {"wins": 0, "left": []} for x in f}
    for g in d.games:
        if g["season"] != s or g["season_type"] != 2 or g["title_game"]:
            continue
        hw = g["home_score"] > g["away_score"]
        home = 0.0 if g["neutral"] else OLD["home_field_points"]
        rh, ra = f.get(g["home_id"], OLD["fcs_opponent_rating"]), f.get(g["away_id"], OLD["fcs_opponent_rating"])
        for tid, gap, won in ((g["home_id"], rh - ra + home, hw), (g["away_id"], ra - rh - home, not hw)):
            if tid not in t:
                continue
            if g["week"] <= w:
                t[tid]["wins"] += won
            else:
                t[tid]["left"].append((gap, won))
    return t


def _win_dist(gaps: np.ndarray, sd_total: float, sigma: float) -> np.ndarray:
    """P(0..n wins) when the team's rating is off by Normal(0, sigma) in every game. The
    opponent's own error is independent from game to game, so it stays inside the game SD."""
    sd = math.sqrt(max(sd_total ** 2 - sigma ** 2, 1.0))
    p = ndtr((gaps[None, :] + sigma * _NODES[:, None]) / sd)
    dist = np.zeros((len(_NODES), len(gaps) + 1))
    dist[:, 0] = 1.0
    for i in range(len(gaps)):
        dist[:, 1:i + 2] = dist[:, 1:i + 2] * (1 - p[:, [i]]) + dist[:, 0:i + 1] * p[:, [i]]
        dist[:, 0] *= 1 - p[:, i]
    return _WTS @ dist


def _win_scores(teams: dict[str, dict], sigma: float, eligible_wins: int = 6) -> dict:
    log_score, z, inside, elig = [], [], [], []
    for t in teams.values():
        if not t["left"]:
            continue
        gaps = np.array([g[0] for g in t["left"]])
        k = sum(g[1] for g in t["left"])
        pm = _win_dist(gaps, OLD["margin_sd"], sigma)
        log_score.append(-math.log(max(pm[k], 1e-12)))
        n = np.arange(len(pm))
        mean = float((n * pm).sum())
        var = float(((n - mean) ** 2 * pm).sum())
        if var > 0.05:
            z.append((k - mean) / math.sqrt(var))
        c = np.cumsum(pm)
        inside.append(int(np.searchsorted(c, 0.1) <= k <= np.searchsorted(c, 0.9)))
        need = eligible_wins - t["wins"]
        if 0 < need <= len(gaps):                    # bowl eligibility still open
            elig.append((float(pm[need:].sum()) - (k >= need)) ** 2)
    return {"n": len(log_score), "log_score_sum": float(np.sum(log_score)), "z2_sum": float(np.sum(np.square(z))),
            "z_n": len(z), "inside_sum": int(np.sum(inside)), "elig_sum": float(np.sum(elig)), "elig_n": len(elig)}


def part_wins(d: Data) -> dict:
    cell = {(s, w, sg): _win_scores(_remaining(d, s, w), sg)
            for s in WIN_SEASONS for w in WIN_WEEKS for sg in SIGMAS}

    def pool(seasons, weeks, sg) -> dict:
        c = [cell[(s, w, sg)] for s in seasons for w in weeks]
        n = sum(x["n"] for x in c)
        return {"n": n, "log_score": sum(x["log_score_sum"] for x in c) / n,
                "spread_ratio": sum(x["z2_sum"] for x in c) / sum(x["z_n"] for x in c),
                "inside_80": sum(x["inside_sum"] for x in c) / n,
                "elig_brier": sum(x["elig_sum"] for x in c) / max(sum(x["elig_n"] for x in c), 1),
                "elig_n": sum(x["elig_n"] for x in c)}

    res: dict = {"seasons": WIN_SEASONS, "weeks": WIN_WEEKS, "sigmas": SIGMAS}
    res["by_week"] = []
    for w in WIN_WEEKS:
        tot = {sg: pool(WIN_SEASONS, [w], sg) for sg in SIGMAS}
        best = min(SIGMAS, key=lambda sg: tot[sg]["log_score"])
        res["by_week"].append({
            "week": w, "best_sigma": best, "zero": tot[0.0], "best": tot[best],
            "seasons_better": sum(cell[(s, w, best)]["log_score_sum"] < cell[(s, w, 0.0)]["log_score_sum"]
                                  for s in WIN_SEASONS)})
    res["all_seasons_best_sigma"] = min(SIGMAS, key=lambda sg: pool(WIN_SEASONS, WIN_WEEKS, sg)["log_score"])
    res["all_seasons"] = {str(sg): pool(WIN_SEASONS, WIN_WEEKS, sg) for sg in SIGMAS}

    wf = []
    for s in WIN_SEASONS:
        if s < FIRST_TEST:
            continue
        train = [x for x in WIN_SEASONS if x < s]
        sg = min(SIGMAS, key=lambda v: pool(train, WIN_WEEKS, v)["log_score"])
        row = {"season": s, "sigma": sg, "old": pool([s], WIN_WEEKS, 0.0), "new": pool([s], WIN_WEEKS, sg),
               "old_late": pool([s], [9, 10, 11, 12], 0.0), "new_late": pool([s], [9, 10, 11, 12], sg)}
        wf.append(row)
    res["walk_forward"] = wf
    return res


# ----------------------------------------------------------------------------- part: committee

FEATURES = ["winpct", "losspow", "rating", "champ", "p4champ", "p4"]
NOISE_MULTS = [0.0, 0.25, 0.5, 0.75, 1.0]


def _power(conf: str, season: int) -> bool:
    return conf in POWER or (conf == "Pac-12" and season <= 2023)   # the old Pac-12 was a power league


def _resumes(d: Data, s: int) -> dict[str, dict]:
    """Every FBS team on selection day: record, conference title, and the FPI published after
    the title games (before any bowl)."""
    title_week = max(g["week"] for g in d.games if g["season"] == s and g["title_game"])
    f = d.snap[(s, title_week)]
    t = {x: {"w": 0, "l": 0, "cw": 0, "cl": 0, "champ": 0, "conf": "", "rating": f[x]} for x in f}
    for g in d.games:
        if g["season"] != s or g["season_type"] != 2 or g["kickoff_utc"][:10] > d.poll_date[s]:
            continue
        hw = g["home_score"] > g["away_score"]
        for tid, won, conf in ((g["home_id"], hw, g["home_conf"]), (g["away_id"], not hw, g["away_conf"])):
            if tid not in t:
                continue
            x = t[tid]
            x["conf"] = conf
            x["w" if won else "l"] += 1
            if g["conf_game"] and not g["title_game"]:
                x["cw" if won else "cl"] += 1
            if g["title_game"] and won:
                x["champ"] = 1
    # a conference without a title game that season: best conference record (ties share it)
    with_game = {x["conf"] for x in t.values() if x["champ"]}
    for conf in {x["conf"] for x in t.values()} - with_game - {"Independent", ""}:
        members = [x for x in t.values() if x["conf"] == conf and x["cw"] + x["cl"] > 0]
        if members:
            best = max(x["cw"] / (x["cw"] + x["cl"]) for x in members)
            for x in members:
                x["champ"] = int(x["cw"] / (x["cw"] + x["cl"]) == best)
    out = {}
    for tid, x in t.items():
        p4 = _power(x["conf"], s) or tid == NOTRE_DAME
        out[tid] = {"winpct": x["w"] / max(x["w"] + x["l"], 1), "losspow": -(x["l"] ** OLD["resume_loss_penalty_exponent"]),
                    "rating": x["rating"], "champ": x["champ"], "p4champ": x["champ"] * int(_power(x["conf"], s)),
                    "p4": int(p4)}
    return out


def _weights_vector(w: dict) -> np.ndarray:
    return np.array([w["resume_win_pct_weight"], w["resume_loss_penalty_scale"], w["resume_power_weight"],
                     w["resume_conf_champ_bonus"], w["resume_p4_champ_bonus"], w["resume_power4_bonus"]])


def _pl_fit(table: dict[int, tuple[list[str], np.ndarray]], cfp: dict, seasons: list[int]) -> np.ndarray:
    """Plackett-Luce: the committee picks #1 from all FBS teams, #2 from the rest, ... #25."""
    def nll(beta: np.ndarray) -> float:
        tot = 0.0
        for s in seasons:
            ids, x = table[s]
            sc = x @ beta
            alive = np.ones(len(ids), bool)
            index = {t: i for i, t in enumerate(ids)}
            for t in sorted(cfp[s], key=cfp[s].get):
                i = index[t]
                m = sc[alive].max()
                tot -= sc[i] - m - math.log(np.exp(sc[alive] - m).sum())
                alive[i] = False
        return tot + 1e-3 * float(beta @ beta)
    return minimize(nll, np.zeros(len(FEATURES)), method="BFGS").x


def _rank_scores(ids: list[str], score: np.ndarray, rank: dict[str, int]) -> dict:
    order = [ids[i] for i in np.argsort(-score)]
    pos = {t: i + 1 for i, t in enumerate(order)}
    val = dict(zip(ids, score))
    ranked = sorted(rank, key=rank.get)
    pairs = [(a, b) for i, a in enumerate(ranked) for b in ranked[i + 1:]]
    return {"top12": len({t for t in ranked[:12]} & set(order[:12])),
            "top4": len({t for t in ranked[:4]} & set(order[:4])),
            "top25": len(set(ranked) & set(order[:25])),
            "pair_order": float(np.mean([val[a] > val[b] for a, b in pairs])),
            "rank_error_top12": float(np.mean([abs(pos[t] - rank[t]) for t in ranked[:12]]))}


def _top_k_brier(ids, score, rank, k: int, noise: float, rng: np.random.Generator, draws: int = 4000) -> float:
    """Sum over all FBS teams of (P(in the top k) - was in the committee's top k)^2."""
    y = np.array([1.0 if rank.get(t, 99) <= k else 0.0 for t in ids])
    if noise <= 0:
        p = np.zeros(len(ids))
        p[np.argsort(-score)[:k]] = 1.0
    else:
        top = np.argsort(-(score[None, :] + rng.gumbel(size=(draws, len(ids))) * noise), axis=1)[:, :k]
        p = np.bincount(top.ravel(), minlength=len(ids)) / draws
    return float(np.sum((p - y) ** 2))


def part_committee(d: Data) -> dict:
    table = {}
    for s in SEASONS:
        r = _resumes(d, s)
        ids = list(r)
        table[s] = (ids, np.array([[r[t][f] for f in FEATURES] for t in ids], float))
    old = _weights_vector(OLD)
    tests = [s for s in SEASONS if s >= FIRST_TEST]
    rng = np.random.default_rng(1)
    res: dict = {"seasons": SEASONS, "test_seasons": tests}

    def total(rows: list[dict]) -> dict:
        return {"top12": sum(r["top12"] for r in rows), "top4": sum(r["top4"] for r in rows),
                "top25": sum(r["top25"] for r in rows),
                "pair_order": float(np.mean([r["pair_order"] for r in rows])),
                "rank_error_top12": float(np.mean([r["rank_error_top12"] for r in rows])),
                "per_season_top12": [r["top12"] for r in rows]}

    res["old_all"] = total([_rank_scores(table[s][0], table[s][1] @ old, d.cfp[s]) for s in SEASONS])
    res["old_test"] = total([_rank_scores(table[s][0], table[s][1] @ old, d.cfp[s]) for s in tests])
    res["fpi_only_test"] = total([_rank_scores(table[s][0], table[s][1][:, 2], d.cfp[s]) for s in tests])

    wf_beta = {s: _pl_fit(table, d.cfp, [x for x in SEASONS if x < s]) for s in tests}
    res["walk_forward_test"] = total([_rank_scores(table[s][0], table[s][1] @ wf_beta[s], d.cfp[s]) for s in tests])
    res["walk_forward_weights"] = [
        {"season": s, **{f: round(float(v), 2) for f, v in zip(FEATURES, wf_beta[s] / wf_beta[s][2])},
         "noise_scale": round(float(1 / wf_beta[s][2]), 2)} for s in tests]

    # committee noise: Gumbel of (mult x the fit's own scale); walk-forward weights throughout
    brier = {(s, k, m): _top_k_brier(table[s][0], table[s][1] @ wf_beta[s], d.cfp[s], k, m, rng)
             for s in tests for k in (12, 4) for m in NOISE_MULTS}
    res["noise"] = [{"mult": m, "top12_brier_sum": sum(brier[(s, 12, m)] for s in tests),
                     "top4_brier_sum": sum(brier[(s, 4, m)] for s in tests),
                     "per_season_top12": [round(brier[(s, 12, m)], 2) for s in tests]} for m in NOISE_MULTS]
    nested = []
    for s in tests[2:]:      # the multiplier itself picked on the earlier test seasons only
        earlier = [x for x in tests if x < s]
        m = min(NOISE_MULTS, key=lambda v: sum(brier[(x, 12, v)] + brier[(x, 4, v)] for x in earlier))
        nested.append({"season": s, "mult": m, "top12_old": brier[(s, 12, 0.0)], "top12_new": brier[(s, 12, m)],
                       "top4_old": brier[(s, 4, 0.0)], "top4_new": brier[(s, 4, m)]})
    res["noise_nested"] = nested

    beta = _pl_fit(table, d.cfp, SEASONS)
    scaled = beta / beta[2]
    best_mult = min(NOISE_MULTS, key=lambda v: sum(brier[(s, 12, v)] + brier[(s, 4, v)] for s in tests))
    res["final_fit"] = {**{f: round(float(v), 2) for f, v in zip(FEATURES, scaled)},
                        "noise_scale": round(float(1 / beta[2]), 2), "noise_mult": best_mult}
    new = _config_weights()
    res["config_weights"] = new
    nv = _weights_vector(new)
    res["config_all_in_sample"] = total([_rank_scores(table[s][0], table[s][1] @ nv, d.cfp[s]) for s in SEASONS])

    misses = []
    for s in (2024, 2025):
        ids = table[s][0]
        actual = sorted(d.cfp[s], key=d.cfp[s].get)[:12]
        row = {"season": s}
        for label, score in (("old", table[s][1] @ old), ("new", table[s][1] @ wf_beta[s])):
            top = [ids[i] for i in np.argsort(-score)[:12]]
            row[label + "_missed"] = [d.name[t] for t in actual if t not in top]
            row[label + "_instead"] = [d.name[t] for t in top if t not in actual]
        misses.append(row)
    res["misses"] = misses
    return res


def _config_weights() -> dict:
    """The model's current defaults (config.toml), for the committee and season parts."""
    import tomllib
    params = tomllib.loads((MODEL_DIR / "config.toml").read_text())["params"]
    return {k: v["value"] for k, v in params.items() if isinstance(v["value"], (int, float))}


# ----------------------------------------------------------------------------- part: season

SEASON_TESTS = [(s, w) for s in (2024, 2025) for w in (4, 7, 10, 12)]
SEASON_SIMS = 3000


def _season_inputs(d: Data, s: int, w: int):
    from ballmonitor.models.ncaaf_bowls.domain import Game, Team
    from ballmonitor.models.ncaaf_bowls.simulator import CONFERENCES_WITH_TITLE_GAME
    f = d.snap[(s, w)]
    with_title = {c for g in d.games if g["season"] == s and g["title_game"] for c in (g["home_conf"], g["away_conf"])}
    rec = {t: {"conf": "", "w": 0, "l": 0, "cw": 0, "cl": 0} for t in f}
    schedule, champs = [], set()
    for g in d.games:
        if g["season"] != s or g["season_type"] != 2:
            continue
        hw = g["home_score"] > g["away_score"]
        if g["title_game"]:
            champs.add(g["home_id"] if hw else g["away_id"])
            continue
        for tid, won, conf in ((g["home_id"], hw, g["home_conf"]), (g["away_id"], not hw, g["away_conf"])):
            if tid in rec:
                rec[tid]["conf"] = conf
                if g["week"] <= w:
                    rec[tid]["w" if won else "l"] += 1
                    if g["conf_game"]:
                        rec[tid]["cw" if won else "cl"] += 1
        if g["week"] > w:
            ref = lambda t: ("notre_dame" if t == NOTRE_DAME else t) if t in f else f"fcs_{t}"  # noqa: E731
            schedule.append(Game(home=ref(g["home_id"]), away=ref(g["away_id"]), neutral=g["neutral"], conf=g["conf_game"]))
    teams = []
    for tid, r in rec.items():
        # a league with no title game that season (the two-team Pac-12) must not get one simulated
        conf = r["conf"] if r["conf"] in with_title or r["conf"] not in CONFERENCES_WITH_TITLE_GAME else r["conf"] + " (no title game)"
        teams.append(Team(id="notre_dame" if tid == NOTRE_DAME else tid, name=d.name[tid], conf=conf, rating=f[tid],
                          apr=980, brand=5, city="", state="", lat=0.0, lon=0.0, wins=r["w"], losses=r["l"],
                          conf_wins=r["cw"], conf_losses=r["cl"]))
    field = {t for g in d.games if g["season"] == s and g["season_type"] == 3 and "College Football Playoff" in g["note"]
             for t in (g["home_id"], g["away_id"])}
    fix = lambda ids: {"notre_dame" if t == NOTRE_DAME else t for t in ids}  # noqa: E731
    return teams, schedule, fix(field), fix(champs)


def _simulate(teams, schedule, values: dict, sims: int) -> tuple[dict, dict]:
    """P(playoff field), P(conference champion) per team from the model's own SeasonSimulator.
    Field = the 2024 and 2025 rule: the five best-ranked champions + the seven best others."""
    from ballmonitor.models.ncaaf_bowls.config import SimConfig
    from ballmonitor.models.ncaaf_bowls.simulator import SeasonSimulator
    names = set(SimConfig.__dataclass_fields__)
    cfg = SimConfig(**{k: v for k, v in values.items() if k in names and k not in ("simulations", "random_seed")})
    sim = SeasonSimulator(teams, schedule, cfg)
    rng = random.Random(7)
    in_field: dict = collections.Counter()
    champ: dict = collections.Counter()
    for _ in range(sims):
        ranked = sorted(sim.simulate_season(rng).values(), key=lambda x: x.resume_score, reverse=True)
        chosen = [x.id for x in ranked if x.is_conf_champ][:5]
        for x in ranked:
            if len(chosen) >= 12:
                break
            if x.id not in chosen:
                chosen.append(x.id)
        in_field.update(chosen)
        champ.update(x.id for x in ranked if x.is_conf_champ)
    return ({t.id: in_field[t.id] / sims for t in teams}, {t.id: champ[t.id] / sims for t in teams})


def _prob_scores(p: dict, actual: set) -> dict:
    """Summed over every FBS team (most are easy zeros), so read it per season, not per team."""
    b = sum((p[t] - (t in actual)) ** 2 for t in p)
    ll = -sum(math.log(min(max(p[t] if t in actual else 1 - p[t], 0.005), 1.0)) for t in p)
    return {"brier_sum": b, "log_loss_sum": ll}


def part_season(d: Data) -> dict:
    new = _config_weights()
    old = {**new, **OLD, "rating_uncertainty_points": 0.0, "resume_noise_points": 0.0}
    rows = []
    for s, w in SEASON_TESTS:
        teams, schedule, field, champs = _season_inputs(d, s, w)
        espn = d.espn[(s, w)]
        back = lambda tid: NOTRE_DAME if tid == "notre_dame" else tid  # noqa: E731
        row = {"season": s, "after_week": w, "teams": len(teams), "games_left": len(schedule),
               "field": len(field), "champions": len(champs)}
        steps = (("old", old), ("sigma_only", {**old, "rating_uncertainty_points": new["rating_uncertainty_points"]}),
                 ("weights_only", {**new, "rating_uncertainty_points": 0.0, "resume_noise_points": 0.0}),
                 ("new", new))
        for label, values in steps:
            p_field, p_champ = _simulate(teams, schedule, values, SEASON_SIMS)
            row[label] = {"field": _prob_scores(p_field, field), "champ": _prob_scores(p_champ, champs)}
        row["espn"] = {
            "field": _prob_scores({t.id: float(espn[back(t.id)]["probmakeplayoffs"] or 0) / 100 for t in teams}, field),
            "champ": _prob_scores({t.id: float(espn[back(t.id)]["probwinconf"] or 0) / 100 for t in teams}, champs)}
        rows.append(row)
        print(f"  {s} after week {w}: field brier old {row['old']['field']['brier_sum']:.2f} "
              f"new {row['new']['field']['brier_sum']:.2f} espn {row['espn']['field']['brier_sum']:.2f}")
    return {"sims": SEASON_SIMS, "rows": rows}


# ----------------------------------------------------------------------------- driver

def save(part: str, obj: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{part}.json").write_text(json.dumps(obj, indent=1, default=float))


def load(part: str) -> dict | None:
    path = OUT / f"{part}.json"
    return json.loads(path.read_text()) if path.exists() else None


def main(argv: list[str]) -> None:
    parts = argv or list(PARTS)
    todo = [p for p in parts if p != "report"]
    if todo:
        d = Data()
        for part in todo:
            if part not in PARTS:
                raise SystemExit(f"unknown part {part!r}; choose from {', '.join(PARTS)}, report")
            t = time.time()
            print(f"[{part}]")
            save(part, globals()[f"part_{part}"](d))
            print(f"[{part}] done in {time.time() - t:.0f}s")
    from ballmonitor.models.ncaaf_bowls.research_report import write_report
    write_report(MODEL_DIR / "RESEARCH.md", {p: load(p) for p in PARTS})
    print("wrote RESEARCH.md")


if __name__ == "__main__":
    main(sys.argv[1:])
