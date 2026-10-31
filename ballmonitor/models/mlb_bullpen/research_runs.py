"""Bullpen run-prevention study for mlb_bullpen -> RESEARCH_RUNS.md + data/research_runs.json.

    ballmonitor fetch mlb_bullpen --offline                # builds data/pitcher_lines.csv.gz etc.
    python -m ballmonitor.models.mlb_bullpen.research_runs # needs numpy (pip install -e '.[data]')

Question: can the simulation's expected usage give "bullpen runs more or less than usual",
and does that predict anything?

Design (no test-season information in any season-forward fitted number):
  * TRAIN = 2025 regular season, TEST = 2026 (team-games from 2025-04-15, as research.py).
  * Reliever rating = shrunk runs on the mound per out from EARLIER relief outings
    (runs.reliever_rate). The prior mean and pseudo-outs are fitted on 2025 by replaying every
    2025 relief appearance in order and minimising the squared error of its runs given its
    outs (the same loss the expected-runs metric is judged on). Ratings in games.csv.gz come
    from fetch.py and use only earlier games.
  * Expected outs per reliever come from the shipped model (model.py, v0.5 usage model) run on
    every team-game; a second run with every arm fully rested gives the "rested" comparison.
  * Benchmarks: league average; the team's season-to-date bullpen runs per out x expected
    bullpen outs (naive, no availability); for whole-game runs, the starter's season-to-date
    runs per out x expected starter outs and the opponent's season-to-date runs per game.
  * Linear models fitted on 2025, scored once on 2026 (season-forward); then refit before
    every 2026 month on all earlier games (walk-forward). Effect sizes = OLS slopes with
    team-clustered standard errors (30 clusters).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from ballmonitor.core import registry
from ballmonitor.models.mlb_bullpen.fetch import read_csv_gz
from ballmonitor.models.mlb_bullpen.runs import bullpen_runs, expected_outs, reliever_rate

MODEL_DIR = Path(__file__).resolve().parent
DATA_DIR = MODEL_DIR / "data"
OUT_MD = MODEL_DIR / "RESEARCH_RUNS.md"
OUT_JSON = DATA_DIR / "research_runs.json"
CACHE_DIR = DATA_DIR / "raw" / "research_cache"
TRAIN, TEST = "2025", "2026"
CASES_FROM = "2025-04-15"
WORKERS = max(1, min(8, (os.cpu_count() or 2) - 1))
PRIOR_OUTS_GRID = (15, 30, 45, 60, 90, 120, 150, 200, 300, 450, 600, 900)
PRIOR_RATE_GRID = tuple(round(0.15 + 0.005 * i, 3) for i in range(17))  # 0.150 .. 0.230
TEAM_K_GRID = (0, 60, 120, 240, 480, 960, 1920, 3840, 7680)
STARTER_K_GRID = (0, 15, 30, 60, 90, 120, 180, 270, 400)
INTERVAL_LEVEL = 0.8


# ---------------------------------------------------------------------------- data


def load_games() -> list[dict]:
    return read_csv_gz(DATA_DIR / "games.csv.gz")


def load_lines() -> list[dict]:
    rows = read_csv_gz(DATA_DIR / "pitcher_lines.csv.gz")
    rows.sort(key=lambda r: int(r["seq"]))
    return rows


def _usage_chunk(args):
    rows, rested = args
    model = registry.load_model("mlb_bullpen")
    out = []
    for row in rows:
        inputs, _ = model.backtest_case(row)
        if rested:
            for r in inputs["relievers"]:
                r["pitches_days"] = [0] * len(r.get("pitches_days") or [0] * 5)
        pred = model.predict(inputs)
        st, pa = pred.extras["stats"], pred.extras["p_appear"]
        out.append({"n": pred.extras["n_simulations"],
                    "r": {k: [pa[k], v["appearances"], v["total_outs"]] for k, v in st.items()}})
    return out


def usage(rows: list[dict], rested: bool, chunks: int = 64) -> list[dict]:
    """Per team-game: {n: simulations, r: {reliever: [P(appear), sim appearances, sim outs]}}
    from the shipped model (cached under data/raw/research_cache/)."""
    model = registry.load_model("mlb_bullpen")
    vals = {k: s.value for k, s in model.params.specs.items() if not k.startswith("runs_")}
    srcs = "".join(str((MODEL_DIR / f).stat().st_size) for f in ("simulator.py", "calibration.py", "ledger.py"))
    blob = json.dumps({"p": vals, "rested": rested, "n": len(rows), "src": srcs,
                       "in": hashlib.sha1("".join(r["game_pk"] + r["team"] for r in rows).encode()).hexdigest()},
                      sort_keys=True, default=str)
    path = CACHE_DIR / f"usage_{hashlib.sha1(blob.encode()).hexdigest()[:16]}.json.gz"
    if path.exists():
        with gzip.open(path, "rt") as fh:
            return json.load(fh)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    parts = [(rows[i::chunks], rested) for i in range(chunks)]
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(_usage_chunk, parts))
    out = [None] * len(rows)
    for i, part in enumerate(res):
        for j, s in enumerate(part):
            out[i + j * chunks] = s
    with gzip.open(path, "wt") as fh:
        json.dump(out, fh)
    return out


# ---------------------------------------------------------------------------- fits


def fit_rating(lines: list[dict]) -> dict:
    """Fit k (pseudo-outs) and m (prior rate) on TRAIN: at the start of each 2025 month from May,
    rate every reliever from his earlier 2025 relief outings and predict his runs per out over
    that month. Loss = sum over (pitcher, month) of outs x (actual rate - rating)^2 =
    (runs - rating x outs)^2 / outs. Aggregating a month avoids scoring single outings, whose
    length depends on how they went (bad outings are short)."""
    import numpy as np

    rel = [r for r in lines if r["season"] == TRAIN and r["started"] == "0"]
    months = sorted({r["game_date"][:7] for r in rel})[2:]  # from May (Mar/Apr only build history)
    pre_o, pre_r, outs, runs = [], [], [], []
    for m in months:
        hist: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        nxt: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for r in rel:
            tgt = hist if r["game_date"][:7] < m else nxt if r["game_date"][:7] == m else None
            if tgt is not None:
                tgt[r["pitcher_id"]][0] += int(r["outs"]); tgt[r["pitcher_id"]][1] += int(r["runs"])
        for pid, (o, x) in nxt.items():
            if o > 0:
                h = hist.get(pid, [0, 0])
                pre_o.append(h[0]); pre_r.append(h[1]); outs.append(o); runs.append(x)
    pre_o, pre_r, outs, runs = map(lambda a: np.array(a, float), (pre_o, pre_r, outs, runs))
    tot_o = sum(int(r["outs"]) for r in rel)
    league = sum(int(r["runs"]) for r in rel) / tot_o
    grid = {}
    for k in PRIOR_OUTS_GRID:
        for m in PRIOR_RATE_GRID:
            rate = (pre_r + k * m) / (pre_o + k)
            grid[(k, m)] = float(((runs - rate * outs) ** 2 / outs).sum())
    best = min(grid, key=grid.get)
    sse_league = float(((runs - league * outs) ** 2 / outs).sum())
    raw = np.where(pre_o > 0, pre_r / np.maximum(pre_o, 1), league)
    sse_raw = float(((runs - raw * outs) ** 2 / outs).sum())
    no_hist = pre_o == 0
    return {
        "n_appearances": len(rel), "n_pitchers": len({r["pitcher_id"] for r in rel}),
        "n_cells": int(len(outs)), "months": months, "league_rate": float(league),
        "prior_outs": best[0], "prior_rate": best[1], "sse_best": grid[best], "sse_league": sse_league,
        "sse_raw": sse_raw,
        "sse_by_k": {str(k): min(v for (kk, _), v in grid.items() if kk == k) for k in PRIOR_OUTS_GRID},
        "first_outing_rate": float(runs[no_hist].sum() / outs[no_hist].sum()), "n_first_outings": int(no_hist.sum()),
        "first_outing_outs": int(outs[no_hist].sum()),
    }


def shrunk(runs, outs, k, m):
    return (runs + k * m) / (outs + k) if outs + k > 0 else m


def fit_k(rows, runs_key, outs_key, act_runs_key, act_outs, mean, grid):
    """Pseudo-count k for a season-to-date rate (team bullpen / starter): minimise squared
    error of the game's runs given its actual outs."""
    best, sse = None, {}
    for k in grid:
        s = 0.0
        for r in rows:
            rate = shrunk(float(r[runs_key]), float(r[outs_key]), k, mean)
            s += (float(r[act_runs_key]) - rate * float(act_outs(r))) ** 2
        sse[k] = s
        best = min(sse, key=sse.get)
    return best, {str(k): v for k, v in sse.items()}


# ---------------------------------------------------------------------------- regression


def ols(X, y, w=None):
    import numpy as np

    if w is not None:
        sw = np.sqrt(w)
        X, y = X * sw[:, None], y * sw
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def cluster_se(X, y, groups, w=None):
    """OLS (or WLS) coefficients with CR1 team-clustered standard errors."""
    import numpy as np

    if w is not None:
        sw = np.sqrt(w)
        X, y = X * sw[:, None], y * sw
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    u = y - X @ beta
    meat = np.zeros((k, k))
    ug = defaultdict(lambda: np.zeros(k))
    for i, g in enumerate(groups):
        ug[g] += X[i] * u[i]
    for v in ug.values():
        meat += np.outer(v, v)
    G = len(ug)
    c = G / (G - 1) * (n - 1) / (n - k)
    V = c * XtX_inv @ meat @ XtX_inv
    return beta, np.sqrt(np.diag(V))


def paired_mse(e_base, e_new, groups, w=None):
    """Mean of (base sq. error - new sq. error) per case (positive = new better), with naive
    and team-clustered s.e. With weights: weighted mean."""
    import numpy as np

    d = e_base ** 2 - e_new ** 2
    if w is None:
        w = np.ones_like(d)
    W = w.sum()
    mean = float((w * d).sum() / W)
    dev = w * (d - mean)
    naive = float(np.sqrt((dev ** 2).sum()) / W)
    g = defaultdict(float)
    for i, t in enumerate(groups):
        g[t] += dev[i]
    clus = float(math.sqrt(sum(v * v for v in g.values())) / W)
    return mean, naive, clus


# ---------------------------------------------------------------------------- study


def build_cases(rows, use, use_rested, par, fit):
    """One dict per team-game: predictors (all pre-game) and outcomes."""
    import numpy as np  # noqa: F401

    # opponent season-to-date runs per game (earlier dates only)
    by_team: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for r in rows:
        by_team[(r["season"], r["team"])].append((r["game_date"], int(r["runs_for"])))
    cases = []
    for i, r in enumerate(rows):
        rels = json.loads(r["relievers_json"])
        rates = {x["name"]: reliever_rate(x.get("ra_outs", 0), x.get("ra_runs", 0), par) for x in rels}
        hist_outs = {x["name"]: x.get("outs", 0) for x in rels}
        out = {}
        for tag, u in (("rep", use[i]), ("rest", use_rested[i])):
            for src in ("reported", "simulated"):
                p = SimpleNamespace(**{**vars(par), "runs_outs_source": src})
                xo = {n: expected_outs(v[0], v[1], v[2], u["n"], p) for n, v in u["r"].items()}
                out[(tag, src)] = bullpen_runs(xo, rates, hist_outs, p)
        prev = [x for d, x in by_team[(r["season"], r["opponent"])] if d < r["game_date"]]
        opp_rpg = (sum(prev) + fit["opp_k"] * fit["league_rpg"]) / (len(prev) + fit["opp_k"])
        team_rate = shrunk(float(r["team_bp_runs"]), float(r["team_bp_outs"]), fit["team_k"], fit["league_rate"])
        st_rate = shrunk(float(r["starter_prior_runs"]), float(r["starter_prior_outs"]), fit["starter_k"],
                         fit["starter_rate"])
        n_hist = sum(1 for x in rels if x.get("ra_outs", 0) > 0)
        cases.append({
            "i": i, "team": r["team"], "season": r["season"], "month": r["game_date"][:7],
            "game_pk": r["game_pk"], "out": out, "team_rate": team_rate, "st_rate": st_rate,
            "opp_rpg": opp_rpg, "y_bp": float(r["bullpen_runs"]), "bp_outs": float(r["bullpen_outs"]),
            "y_all": float(r["runs_against"]), "st_outs": float(r["starter_outs"]),
            "pool": len(rels), "pool_no_hist": len(rels) - n_hist,
        })
    return cases


def design(cases, spec, src, fit):
    """Matrix of predictors for a named spec (column 0 = intercept)."""
    import numpy as np

    cols = []
    names = []
    for c in cases:
        o = c["out"][("rep", src)]
        orst = c["out"][("rest", src)]
        X = o["expected_outs"]
        S = max(fit["defensive_outs"] - X, 0.0)
        f = {
            "workload": X * fit["league_rate"],                       # league-average pen, today's workload
            "team_naive": X * c["team_rate"],                          # team season-to-date rate x workload
            "vs_avg": o["vs_average"],
            "usual_vs_avg": o["usual_runs"] - X * fit["league_rate"],  # usual mix quality vs league
            "vs_usual": o["vs_usual"],
            "vs_rested": o["expected_runs"] - X * (orst["expected_runs"] / orst["expected_outs"]
                                                   if orst["expected_outs"] > 0 else fit["league_rate"]),
            "starter": S * c["st_rate"],
            "opp": c["opp_rpg"],
        }
        cols.append([1.0] + [f[k] for k in spec])
    names = ["const"] + list(spec)
    return np.array(cols), names


SPECS_A = [
    ("league average (constant)", ()),
    ("expected workload x league rate", ("workload",)),
    ("naive: team season-to-date rate x expected outs", ("team_naive",)),
    ("workload + vs average (availability-aware)", ("workload", "vs_avg")),
    ("naive + vs average", ("team_naive", "vs_avg")),
    ("naive + vs usual (availability only)", ("team_naive", "vs_usual")),
    ("workload + usual-mix quality + vs usual", ("workload", "usual_vs_avg", "vs_usual")),
    ("naive + vs rested (availability only, rested sim)", ("team_naive", "vs_rested")),
]
SPECS_B = [
    ("league average (constant)", ()),
    ("starter + naive bullpen + opponent offense", ("starter", "team_naive", "opp")),
    ("... + vs average", ("starter", "team_naive", "opp", "vs_avg")),
    ("... + vs usual", ("starter", "team_naive", "opp", "vs_usual")),
]


def evaluate(cases, specs, ykey, src, fit, per_out=False):
    """Season-forward (fit 2025, score 2026) and monthly walk-forward MSE for each spec,
    plus clustered OLS slopes on each season."""
    import numpy as np

    sel = [c for c in cases if (c["bp_outs"] > 0 if per_out else True)]
    y = np.array([c[ykey] for c in sel])
    w = None
    if per_out:
        w = np.array([c["bp_outs"] for c in sel])
        y = y / w
    teams = [c["team"] for c in sel]
    train = np.array([c["season"] == TRAIN for c in sel])
    test = ~train
    months = sorted({c["month"] for c in sel if c["season"] == TEST})
    month = np.array([c["month"] for c in sel])
    res = []
    errs = {}
    for label, spec in specs:
        X, names = design(sel, spec, src, fit)
        if per_out:  # per-out: divide expected-run predictors by expected outs
            xo = np.array([c["out"][("rep", src)]["expected_outs"] for c in sel])
            xo = np.where(xo > 0, xo, 1.0)
            for j, nm in enumerate(names):
                if nm not in ("const", "opp"):
                    X[:, j] = X[:, j] / xo
        b = ols(X[train], y[train], None if w is None else w[train])
        e_sf = y - X @ b
        e_wf = np.empty(len(y))
        for m in months:
            fm = month < m if True else None
            fm = np.array([(c["season"] == TRAIN) or (c["month"] < m) for c in sel])
            tm = month == m
            bm = ols(X[fm], y[fm], None if w is None else w[fm])
            e_wf[tm] = y[tm] - X[tm] @ bm
        errs[label] = (e_sf, e_wf)
        slopes = {}
        for season in (TRAIN, TEST):
            msk = np.array([c["season"] == season for c in sel])
            bs, se = cluster_se(X[msk], y[msk], [t for t, k in zip(teams, msk) if k],
                                None if w is None else w[msk])
            slopes[season] = {n: [float(v), float(s)] for n, v, s in zip(names, bs, se)}
        wt = np.ones(test.sum()) if w is None else w[test]
        mse = float((wt * e_sf[test] ** 2).sum() / wt.sum())
        mse_wf = float((wt * e_wf[test] ** 2).sum() / wt.sum())
        res.append({"label": label, "spec": list(spec), "coef_train": dict(zip(names, map(float, b))),
                    "mse": mse, "mse_wf": mse_wf, "slopes": slopes})
    # R2 vs the constant, paired differences vs chosen baselines
    base0 = errs[specs[0][0]]
    wt = None if w is None else w[test]
    tt = [t for t, k in zip(teams, test) if k]
    for r in res:
        r["r2_oos"] = 1 - r["mse"] / res[0]["mse"]
        r["r2_wf"] = 1 - r["mse_wf"] / res[0]["mse_wf"]
        r["vs_const"] = paired_mse(base0[0][test], errs[r["label"]][0][test], tt, wt)
    return res, errs, {"n_test": int(test.sum()), "n_train": int(train.sum()),
                       "n_games_test": len({c["game_pk"] for c, k in zip(sel, test) if k}),
                       "months": months, "test_mask": test, "teams": teams, "w": w}


def compare(errs, meta, a, b):
    """Paired MSE improvement of spec b over spec a on the test season (positive = b better);
    season-forward and walk-forward."""
    test = meta["test_mask"]
    tt = [t for t, k in zip(meta["teams"], test) if k]
    wt = None if meta["w"] is None else meta["w"][test]
    sf = paired_mse(errs[a][0][test], errs[b][0][test], tt, wt)
    wf = paired_mse(errs[a][1][test], errs[b][1][test], tt, wt)
    return {"a": a, "b": b, "sf": sf, "wf": wf}


def run_study() -> dict:
    import numpy as np

    rows = load_games()
    lines = load_lines()
    print(f"{len(rows)} team-games, {len(lines)} pitcher lines")
    rating = fit_rating(lines)
    print("rating fit", {k: v for k, v in rating.items() if k != "sse_by_k"})
    tr = [r for r in rows if r["season"] == TRAIN]
    st_lines = [r for r in lines if r["season"] == TRAIN and r["started"] == "1"]
    starter_rate = sum(int(r["runs"]) for r in st_lines) / sum(int(r["outs"]) for r in st_lines)
    team_k, team_sse = fit_k(tr, "team_bp_runs", "team_bp_outs", "bullpen_runs", lambda r: r["bullpen_outs"],
                             rating["league_rate"], TEAM_K_GRID)
    starter_k, st_sse = fit_k(tr, "starter_prior_runs", "starter_prior_outs", "starter_runs",
                              lambda r: r["starter_outs"], starter_rate, STARTER_K_GRID)
    league_rpg = sum(float(r["runs_for"]) for r in tr) / len(tr)
    defensive_outs = sum(float(r["starter_outs"]) + float(r["bullpen_outs"]) for r in tr) / len(tr)
    fit = {"league_rate": rating["league_rate"], "team_k": team_k, "starter_k": starter_k,
           "starter_rate": starter_rate, "league_rpg": league_rpg, "opp_k": 20.0,
           "defensive_outs": defensive_outs, "team_sse": team_sse, "starter_sse": st_sse}
    print("fit", fit)
    cfg = registry.load_model("mlb_bullpen").params
    par = SimpleNamespace(runs_prior_outs=rating["prior_outs"], runs_prior_rate=rating["prior_rate"],
                          runs_league_rate=round(rating["league_rate"], 4), runs_outs_source="reported",
                          runs_default_outs_per_app=float(cfg.runs_default_outs_per_app))
    use = usage(rows, rested=False)
    use_rested = usage(rows, rested=True)
    cases = build_cases(rows, use, use_rested, par, fit)

    # expected-outs source: choose on TRAIN (R2 of bullpen runs on workload + vs_avg)
    src_r2 = {}
    for src in ("reported", "simulated"):
        tr_cases = [c for c in cases if c["season"] == TRAIN]
        X, _ = design(tr_cases, ("workload", "vs_avg"), src, fit)
        y = np.array([c["y_bp"] for c in tr_cases])
        e = y - X @ ols(X, y)
        src_r2[src] = float(1 - (e ** 2).mean() / y.var())
    src = max(src_r2, key=src_r2.get)
    print("outs source", src_r2, "->", src)

    out = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rating": rating,
           "fit": {k: v for k, v in fit.items()}, "src_r2": src_r2, "src": src}
    resA, errA, metaA = evaluate(cases, SPECS_A, "y_bp", src, fit)
    resAp, errAp, metaAp = evaluate(cases, SPECS_A, "y_bp", src, fit, per_out=True)
    resB, errB, metaB = evaluate(cases, SPECS_B, "y_all", src, fit)
    L = [s[0] for s in SPECS_A]
    LB = [s[0] for s in SPECS_B]
    out["A"] = {"res": resA, "n": {k: v for k, v in metaA.items() if k in ("n_test", "n_train", "n_games_test", "months")},
                "cmp": [compare(errA, metaA, L[1], L[3]), compare(errA, metaA, L[2], L[4]),
                        compare(errA, metaA, L[2], L[5]), compare(errA, metaA, L[2], L[7]),
                        compare(errA, metaA, L[1], L[2])]}
    out["Ap"] = {"res": resAp, "n": {k: v for k, v in metaAp.items() if k in ("n_test", "n_train", "n_games_test")},
                 "cmp": [compare(errAp, metaAp, L[1], L[3]), compare(errAp, metaAp, L[2], L[4]),
                         compare(errAp, metaAp, L[2], L[5])]}
    out["B"] = {"res": resB, "n": {k: v for k, v in metaB.items() if k in ("n_test", "n_train", "n_games_test")},
                "cmp": [compare(errB, metaB, LB[1], LB[2]), compare(errB, metaB, LB[1], LB[3])]}

    # descriptive: distribution of the metric, decile table of vs_avg vs actual (test)
    def col(cs, key):
        return np.array([c["out"][("rep", src)][key] for c in cs])

    te = [c for c in cases if c["season"] == TEST]
    trc = [c for c in cases if c["season"] == TRAIN]
    va, vu = col(te, "vs_average"), col(te, "vs_usual")
    X_te = col(te, "expected_outs")
    y_te = np.array([c["y_bp"] for c in te])
    resid = y_te - X_te * fit["league_rate"]
    order = np.argsort(va)
    dec = []
    for q in range(5):
        idx = order[q * len(order) // 5:(q + 1) * len(order) // 5]
        dec.append({"q": q + 1, "pred": float(va[idx].mean()), "actual": float(resid[idx].mean()),
                    "n": int(len(idx))})
    order_u = np.argsort(vu)
    dec_u = []
    team_naive_te = np.array([c["team_rate"] for c in te]) * X_te
    resid_u = y_te - team_naive_te
    for q in range(5):
        idx = order_u[q * len(order_u) // 5:(q + 1) * len(order_u) // 5]
        dec_u.append({"q": q + 1, "pred": float(vu[idx].mean()), "actual": float(resid_u[idx].mean()),
                      "n": int(len(idx))})
    # Model display: scale (2025 slope of bullpen runs on vs average, given workload) and the
    # interval half-width per sqrt(expected out) giving INTERVAL_LEVEL coverage on 2025.
    scale = float(resA[3]["coef_train"]["vs_avg"])
    X_tr = col(trc, "expected_outs")
    y_tr = np.array([c["y_bp"] for c in trc])
    ctr_tr = X_tr * par.runs_league_rate + scale * col(trc, "vs_average")
    ctr_te = X_te * par.runs_league_rate + scale * va
    half = float(np.quantile(np.abs(y_tr - ctr_tr) / np.sqrt(np.maximum(X_tr, 1e-9)), INTERVAL_LEVEL))
    cover_tr = float(np.mean(np.abs(y_tr - ctr_tr) <= half * np.sqrt(X_tr)))
    cover = float(np.mean(np.abs(y_te - ctr_te) <= half * np.sqrt(X_te)))
    out["desc"] = {
        "vs_avg_sd": float(va.std()), "vs_avg_p10_p90": [float(np.percentile(va, 10)), float(np.percentile(va, 90))],
        "vs_usual_sd": float(vu.std()),
        "vs_usual_p10_p90": [float(np.percentile(vu, 10)), float(np.percentile(vu, 90))],
        "expected_outs_mean": float(X_te.mean()), "actual_outs_mean": float(np.mean([c["bp_outs"] for c in te])),
        "expected_runs_mean": float(col(te, "expected_runs").mean()), "actual_runs_mean": float(y_te.mean()),
        "y_sd": float(y_te.std()), "quintiles": dec, "quintiles_usual": dec_u,
        "scale": scale, "half_width": half, "cover_train": cover_tr, "cover_test": cover,
        "corr_vs_avg_team_naive": float(np.corrcoef(va, team_naive_te - X_te * fit["league_rate"])[0, 1]),
        "corr_vs_avg_y": float(np.corrcoef(va, resid)[0, 1]),
        "corr_vs_usual_y_resid": float(np.corrcoef(vu, resid_u)[0, 1]),
        "pool_no_hist_share": float(np.mean([c["pool_no_hist"] / c["pool"] for c in te])),
        "rate_sd_test": float(np.std([reliever_rate(x.get("ra_outs", 0), x.get("ra_runs", 0), par)
                                      for r in rows if r["season"] == TEST
                                      for x in json.loads(r["relievers_json"])])),
    }
    out["params"] = {"runs_prior_outs": par.runs_prior_outs, "runs_prior_rate": par.runs_prior_rate,
                     "runs_league_rate": par.runs_league_rate, "runs_outs_source": src,
                     "runs_scale": round(scale, 2), "runs_interval_halfwidth": round(half, 2),
                     "runs_interval_level": INTERVAL_LEVEL}

    # slopes by half season and pooled (team-clustered), key specs, bullpen runs
    halves = [("2025 Apr-Jun", lambda c: c["season"] == TRAIN and c["month"] < "2025-07"),
              ("2025 Jul-Sep", lambda c: c["season"] == TRAIN and c["month"] >= "2025-07"),
              ("2026 Mar-Jun", lambda c: c["season"] == TEST and c["month"] < "2026-07"),
              ("2026 Jul-Sep", lambda c: c["season"] == TEST and c["month"] >= "2026-07"),
              ("pooled 2025-26", lambda c: True)]
    out["halves"] = []
    for lab, fn in halves:
        sel = [c for c in cases if fn(c)]
        y = np.array([c["y_bp"] for c in sel])
        row = {"label": lab, "n": len(sel)}
        for key, spec in (("wl_avg", ("workload", "vs_avg")), ("naive_avg", ("team_naive", "vs_avg")),
                          ("naive_usual", ("team_naive", "vs_usual"))):
            X, _ = design(sel, spec, src, fit)
            b, se = cluster_se(X, y, [c["team"] for c in sel])
            row[key] = [float(b[-1]), float(se[-1])]
        out["halves"].append(row)
    return out


# ---------------------------------------------------------------------------- render


def _f(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def _pm(t, nd=3):
    m, s, c = t
    return f"{m:+.{nd}f} ± {s:.{nd}f} ({c:.{nd}f})"


def render_md(o: dict) -> str:
    r, f, d = o["rating"], o["fit"], o["desc"]
    md = [
        "# Research: bullpen run prevention (mlb_bullpen)", "",
        "_Generated by `python -m ballmonitor.models.mlb_bullpen.research_runs`; do not edit by hand._", "",
        "**Question.** Can the simulated bullpen usage tell us how many runs more or fewer than usual a",
        "team's relievers should allow today, and does that number predict anything out of sample?", "",
        "Data: MLB Stats API box scores and play-by-play (`fetch.py`). **Train** = 2025 regular season "
        f"({o['A']['n']['n_train']} team-games from {CASES_FROM}), **test** = 2026 "
        f"({o['A']['n']['n_test']} team-games from {o['A']['n']['n_games_test']} games, 30 teams). Every "
        "fitted number in the season-forward rows uses 2025 only; the walk-forward rows refit the linear "
        f"models before each of the {len(o['A']['n']['months'])} 2026 months on all earlier games. "
        "Standard errors are shown naive and, in brackets, clustered by team (30 clusters): a team's "
        "games share a bullpen, so the effective sample is far smaller than the case count.", "",
        "## 1. Metric", "",
        "* **Runs on the mound**: runs that scored during plate appearances a pitcher pitched (play-by-play "
        "score changes). Inherited runners count against the pitcher on the mound. The cached box scores "
        "carry no per-pitcher R / ER / H / BB / K / HR, so an earned-run or FIP-style rate is not possible "
        "without re-downloading every box score.",
        "* **Reliever rating** (runs per out) = (runs + k × m) / (outs + k) over all his EARLIER relief "
        "outings in the data (any team, from 2025 opening day). No history → m.",
        f"* k and m fitted on 2025 ({r['n_appearances']} relief appearances, {r['n_pitchers']} pitchers): at "
        "the start of each month from May, every reliever is rated from his earlier 2025 relief outings "
        "and the rating predicts his runs per out over that month; loss = Σ (runs − rating × outs)² / outs "
        f"over {r['n_cells']} pitcher-months (a month, not single outings, because an outing's length "
        "depends on how it went). "
        f"**k = {r['prior_outs']} pseudo-outs, m = {r['prior_rate']:.3f} runs/out**. League reliever "
        f"rate 2025 = {r['league_rate']:.4f} runs/out ({r['league_rate'] * 27:.2f} per 9 innings). "
        f"Relievers with no earlier 2025 relief outing ran at {r['first_outing_rate']:.3f} runs/out "
        f"({r['n_first_outings']} pitcher-months, {r['first_outing_outs']} outs), hence m slightly above "
        "the league rate (unknown arms lean replacement-level). Loss: shrunk rating "
        f"{r['sse_best']:.1f}, league-average constant {r['sse_league']:.1f}, unshrunk own rate "
        f"{r['sse_raw']:.1f}: individual run prevention is mostly noise, hence the heavy shrinkage "
        f"({r['prior_outs']} outs ≈ {r['prior_outs'] / 3:.0f} innings).",
        "",
        "| k (pseudo-outs) | " + " | ".join(r["sse_by_k"]) + " |",
        "| :--- | " + " | ".join(":---:" for _ in r["sse_by_k"]) + " |",
        "| loss (best m) | " + " | ".join(f"{v:.1f}" for v in r["sse_by_k"].values()) + " |", "",
        f"* **Expected outs per reliever**: `{o['src']}` (chosen on 2025: R² of bullpen runs on workload "
        f"+ vs-average = {o['src_r2']['reported']:.4f} with P(appear) × simulated outs per appearance "
        f"(`reported`) vs {o['src_r2']['simulated']:.4f} with simulated outs per game (`simulated`)). "
        "Usage comes from the shipped v0.5 model (blend probabilities, 500 simulations).",
        "* **Bullpen runs vs average** = Σ xOuts_i × (rating_i − league rate): positive = this bullpen, "
        "as it is expected to be used today, should allow more runs than a league-average bullpen "
        "pitching the same expected outs.",
        "* **Bullpen runs vs usual** = Σ xOuts_i × rating_i − X × usual rate, usual rate = ratings weighted "
        "by each arm's share of the pool's relief outs over his last 30 roster-games: the availability / "
        "usage-mix effect alone. A second version (**vs rested**) compares with the same pool simulated "
        "fully rested (all `pitches_days` = 0).",
        f"* Benchmarks (all pre-game): team season-to-date bullpen runs/out shrunk with "
        f"{f['team_k']} pseudo-outs toward the league rate, × expected bullpen outs (**naive**); starter "
        f"season-to-date runs/out (as a starter) shrunk with {f['starter_k']} pseudo-outs toward "
        f"{f['starter_rate']:.3f}, × expected starter outs ({f['defensive_outs']:.1f} − expected bullpen "
        f"outs); opponent season-to-date runs per game (shrunk with 20 pseudo-games). Pseudo-counts chosen "
        "on 2025 by squared error.", "",
        "Distribution on 2026: bullpen runs vs average sd "
        f"{d['vs_avg_sd']:.2f} runs (10th–90th percentile {d['vs_avg_p10_p90'][0]:+.2f} to "
        f"{d['vs_avg_p10_p90'][1]:+.2f}); vs usual sd {d['vs_usual_sd']:.2f} "
        f"({d['vs_usual_p10_p90'][0]:+.2f} to {d['vs_usual_p10_p90'][1]:+.2f}). Expected bullpen outs "
        f"{d['expected_outs_mean']:.2f} (actual {d['actual_outs_mean']:.2f} incl. non-pool arms); expected "
        f"bullpen runs {d['expected_runs_mean']:.2f} (actual {d['actual_runs_mean']:.2f}, sd per game "
        f"{d['y_sd']:.2f}). Reliever rating sd across pool arms {d['rate_sd_test']:.4f} runs/out; "
        f"{100 * d['pool_no_hist_share']:.1f}% of pool arms have no relief history. Correlation of vs "
        f"average with the naive team-rate deviation: {d['corr_vs_avg_team_naive']:.2f}.", "",
    ]

    def table(block, title, unit):
        res = block["res"]
        md.extend([f"## {title}", "", f"Test season 2026, n = {block['n']['n_test']} team-games "
                   f"({block['n']['n_games_test']} games). {unit}", "",
                   "| Model (linear, fitted on 2025) | MSE | R² vs constant | MSE walk-forward | R² walk-forward | "
                   "ΔMSE vs constant ± s.e. (clustered) |",
                   "| :--- | :---: | :---: | :---: | :---: | :---: |"])
        for x in res:
            md.append(f"| {x['label']} | {x['mse']:.4f} | {x['r2_oos']:+.4f} | {x['mse_wf']:.4f} | "
                      f"{x['r2_wf']:+.4f} | {_pm(x['vs_const'], 4)} |")
        md.extend(["", "Paired MSE improvement (positive = the second model is better), season-forward and "
                   "walk-forward:", "", "| Baseline → with | ΔMSE season-forward | ΔMSE walk-forward |",
                   "| :--- | :---: | :---: |"])
        for c in block["cmp"]:
            md.append(f"| {c['a']} → {c['b']} | {_pm(c['sf'], 4)} | {_pm(c['wf'], 4)} |")
        md.extend(["", "Slopes (OLS on each season separately, ± team-clustered s.e.; a slope of 1 on a "
                   "runs-scale predictor = calibrated):", "",
                   "| Model | 2025 slopes | 2026 slopes |", "| :--- | :--- | :--- |"])
        for x in res[1:]:
            cells = []
            for s in (TRAIN, TEST):
                cells.append(", ".join(f"{k} {v[0]:+.2f} ± {v[1]:.2f}" for k, v in x["slopes"][s].items()
                                       if k != "const"))
            md.append(f"| {x['label']} | {cells[0]} | {cells[1]} |")
        md.append("")

    table(o["A"], "2. Outcome A: runs allowed by the bullpen in the game",
          "y = runs scored while the team's relievers were on the mound (all relievers, incl. position "
          "players).")
    table(o["Ap"], "3. Outcome A per out: bullpen runs per bullpen out",
          "y = bullpen runs / actual bullpen outs, weighted by actual outs (games with 0 bullpen outs "
          "dropped); predictors divided by expected bullpen outs (rates).")
    table(o["B"], "4. Outcome B: total runs allowed by the team", "y = opponent's final score.")
    md.extend(["## 5. Calibration by quintile (2026)", "",
               "Teams sorted by the pre-game metric into fifths; mean prediction vs mean actual.", "",
               "| Quintile | n | vs average (pred.) | actual bullpen runs − X × league rate | vs usual (pred.) | "
               "actual − naive team expectation |", "| :---: | :---: | :---: | :---: | :---: | :---: |"])
    for a, b in zip(d["quintiles"], d["quintiles_usual"]):
        md.append(f"| {a['q']} | {a['n']} | {a['pred']:+.3f} | {a['actual']:+.3f} | {b['pred']:+.3f} | "
                  f"{b['actual']:+.3f} |")
    md.extend(["", f"Correlations (2026): vs average with actual − X × league rate {d['corr_vs_avg_y']:.3f}; "
               f"vs usual with actual − naive {d['corr_vs_usual_y_resid']:.3f}.", "",
               "Slope of the last predictor by half season (team-clustered s.e.); the history behind "
               "the ratings grows over time (April 2025 ratings rest on a few weeks of outings):", "",
               "| Period | n | vs average (with workload) | vs average (with naive) | vs usual (with naive) |",
               "| :--- | :---: | :---: | :---: | :---: |"])
    for h in o["halves"]:
        md.append(f"| {h['label']} | {h['n']} | {h['wl_avg'][0]:+.2f} ± {h['wl_avg'][1]:.2f} | "
                  f"{h['naive_avg'][0]:+.2f} ± {h['naive_avg'][1]:.2f} | "
                  f"{h['naive_usual'][0]:+.2f} ± {h['naive_usual'][1]:.2f} |")
    s26 = o["A"]["res"][3]["slopes"][TEST]["vs_avg"][0]
    md.extend(["", "**Model display (v0.6.0).** The raw sums are under-dispersed: individually shrunk "
               "ratings miss what a team's relievers share (park, defence, catchers, coaching), so a run "
               "of raw difference is worth about two actual runs. The model reports `runs_scale` × raw, "
               f"`runs_scale` = {d['scale']:.2f} = the 2025 slope of bullpen runs on vs average given the "
               f"workload (2026 slope {s26:.2f}, i.e. {s26 / d['scale']:.2f} after scaling). Interval: "
               f"expected bullpen runs ± `runs_interval_halfwidth` × √(expected outs), half-width "
               f"{d['half_width']:.2f} = the {int(100 * INTERVAL_LEVEL)}th percentile of |actual − expected| / "
               f"√X on 2025 (coverage 2025 {100 * d['cover_train']:.1f}%, 2026 {100 * d['cover_test']:.1f}%).",
               ""])
    cfg = registry.load_model("mlb_bullpen").params
    md.extend(["Config vs this study (config.toml values should match after rounding):", "",
               "| Param | config.toml | study |", "| :--- | :---: | :---: |"])
    for k, v in o["params"].items():
        md.append(f"| `{k}` | {getattr(cfg, k)} | {v} |")
    md.append("")
    md.extend(conclusions(o))
    return "\n".join(md) + "\n"


def conclusions(o: dict) -> list[str]:
    A, B = o["A"], o["B"]
    sl = {s: A["res"][4]["slopes"][s]["vs_avg"] for s in (TRAIN, TEST)}
    su = {s: A["res"][5]["slopes"][s]["vs_usual"] for s in (TRAIN, TEST)}
    c_avg, c_usual = A["cmp"][1], A["cmp"][2]
    pooled = o["halves"][-1]
    lines = ["## 6. Conclusions", "",
             f"* **Beyond season-average team quality** (naive → naive + vs average): ΔMSE "
             f"{_pm(c_avg['sf'], 4)} season-forward, {_pm(c_avg['wf'], 4)} walk-forward. Slope on vs average "
             f"given the naive rate: 2025 {sl[TRAIN][0]:+.2f} ± {sl[TRAIN][1]:.2f}, 2026 {sl[TEST][0]:+.2f} ± "
             f"{sl[TEST][1]:.2f} (clustered).",
             f"* **Availability alone** (naive → naive + vs usual): ΔMSE {_pm(c_usual['sf'], 4)}; slope 2025 "
             f"{su[TRAIN][0]:+.2f} ± {su[TRAIN][1]:.2f}, 2026 {su[TEST][0]:+.2f} ± {su[TEST][1]:.2f}.",
             f"* Pooled 2025-26 slopes (clustered): vs average given the naive rate "
             f"{pooled['naive_avg'][0]:+.2f} ± {pooled['naive_avg'][1]:.2f}; vs usual given the naive rate "
             f"{pooled['naive_usual'][0]:+.2f} ± {pooled['naive_usual'][1]:.2f}.",
             f"* Whole-game runs: adding vs average to starter + naive bullpen + opponent: ΔMSE "
             f"{_pm(B['cmp'][0]['sf'], 4)} season-forward, {_pm(B['cmp'][0]['wf'], 4)} walk-forward; vs "
             f"usual {_pm(B['cmp'][1]['sf'], 4)}, {_pm(B['cmp'][1]['wf'], 4)}.",
             "* Per-game runs are very noisy (R² of any pre-game bullpen predictor is around 1%); "
             "effects are small relative to the game-to-game spread, so read slopes with their s.e.", ""]
    return lines


def main() -> None:
    o = run_study()
    OUT_MD.write_text(render_md(o))
    with open(OUT_JSON, "w") as fh:
        json.dump(o, fh, indent=1, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x))
    print("Wrote RESEARCH_RUNS.md and data/research_runs.json")


if __name__ == "__main__":
    main()
