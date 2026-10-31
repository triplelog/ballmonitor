"""Walk-forward study for the mlb_bullpen model -> RESEARCH.md + data/research.json.

    ballmonitor fetch mlb_bullpen                     # builds data/games.csv.gz, decisions.csv.gz
    python -m ballmonitor.models.mlb_bullpen.research # needs numpy (pip install -e '.[data]')

Design (no test-season information is used for any season-forward fitted number):
  * TRAIN = 2025 regular season (team-games from 2025-04-15), TEST = 2026 regular season.
  * Workload table: relief appearance rate by recent workload (train) -> hard rest rules.
  * Choice model: conditional logit over every real bullpen call in TRAIN (unchanged since
    v0.4.0; its coefficients are the config defaults).
  * Game engine: hook settings chosen on a home/away-BALANCED train sample (v0.4.0 used a
    home-teams-only sample by accident).
  * v0.5 improvements, each alone and combined: (1) logistic calibration of the simulated
    appearance frequencies, (2a) engine refit, (2b) rolling team/league usage tendency,
    (3) active-roster filter, (4) a direct logistic model and its blend with the simulator.
    Fitted on 2025 (season-forward) and, as a second check, refit before every 2026 month on
    all earlier games (walk-forward). Raw simulations are cached in data/raw/research_cache/.
  * Scored on TEST against v0.4.0 and two benchmarks fitted on TRAIN (uniform,
    usage-frequency), with naive and team-clustered paired standard errors; finally the
    shipped config is run through model.py on the whole test season.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ballmonitor.core import registry
from ballmonitor.models.mlb_bullpen.fetch import read_csv_gz
from ballmonitor.models.mlb_bullpen.ledger import BullpenLedger
from ballmonitor.models.mlb_bullpen.simulator import (
    SITUATION_ROLES,
    SITUATIONS,
    classify_situation,
    compute_leverage_index,
)

MODEL_DIR = Path(__file__).resolve().parent
DATA_DIR = MODEL_DIR / "data"
RESEARCH_MD = MODEL_DIR / "RESEARCH.md"
RESEARCH_JSON = DATA_DIR / "research.json"

TRAIN_SEASON, TEST_SEASON = "2025", "2026"
RIDGE = 1.0  # L2 penalty on logit coefficients (stabilises sparse situation x role cells)
PRIOR_GAMES_GRID = (1, 2, 5, 10)
OFFDAY_GRID = (1.0, 0.75, 0.5)
ENGINE_SAMPLE = 1500  # train team-games simulated for the game-engine check
EVAL_SIMS = 500
WORKERS = max(1, min(8, (os.cpu_count() or 2) - 1))
REST_BUCKETS = ("b2b", "yesterday", "2_days", "rested")
ROLE_GRID = [
    {"closer_min_saves": cs, "setup_count": sc, "setup_min_holds": sh, "long_min_outs_per_app": lo}
    for cs in (1, 2, 4) for sc in (2, 3, 4) for sh in (1, 2, 4) for lo in (4.5, 6.0)
]
# Game-engine (hook) settings tried; chosen by matching train means of relievers used and
# starter outs. The first entry is the v0.3.0 hook setup.
_V03_HOOKS = {"pitches_per_pa": 3.9, "hook_soft_ratio": 0.9, "hook_force_ratio": 1.05, "late_hook_prob": 0.5,
              "tto_hook_prob": 0.6, "jam_hook_prob": 0.45, "jam_hook_prob_tto": 0.8, "reliever_extend_prob": 0.0,
              "reliever_traffic_hook_prob": 0.65, "reliever_mid_max_pitches": 28, "reliever_mid_max_runs": 2}
ENGINE_GRID = [_V03_HOOKS] + [
    {"pitches_per_pa": ppa, "hook_soft_ratio": 1.05, "hook_force_ratio": 1.15, "late_hook_prob": 0.1,
     "tto_hook_prob": 0.1, "jam_hook_prob": jam, "jam_hook_prob_tto": jam_tto, "reliever_extend_prob": ext,
     "reliever_traffic_hook_prob": 0.3, "reliever_mid_max_pitches": 35, "reliever_mid_max_runs": 3}
    for ppa in (3.9, 3.75) for jam, jam_tto in ((0.45, 0.8), (0.2, 0.4)) for ext in (0.25, 0.35)
]
ENGINE_GAMES_PER_CASE = 40

ROLES3 = SITUATION_ROLES
SITS = [s for s in SITUATIONS if s != "middle"]
FATIGUE = ["yesterday", "back_to_back", "three_straight", "pitches_3d_10", "high_workload"]
FEATURES = (
    [f"role_{r}" for r in ROLES3]
    + [f"sit_{s}_{r}" for s in SITS for r in ROLES3]
    + ["usage"] + FATIGUE + ["platoon"]
)
# config param for each feature, and the sign (fatigue features are penalties)
PARAM_OF = {f: (f, 1.0) for f in FEATURES}
PARAM_OF.update({
    "usage": ("usage_weight", 1.0),
    "yesterday": ("penalty_pitched_yesterday", -1.0),
    "back_to_back": ("penalty_back_to_back", -1.0),
    "three_straight": ("penalty_three_straight", -1.0),
    "pitches_3d_10": ("penalty_per_10_pitches_3d", -1.0),
    "high_workload": ("penalty_high_workload_yesterday", -1.0),
    "platoon": ("platoon_bonus", 1.0),
})


# --------------------------------------------------------------------------- data

def load() -> tuple[list[dict], dict]:
    games = read_csv_gz(DATA_DIR / "games.csv.gz")
    decisions: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in read_csv_gz(DATA_DIR / "decisions.csv.gz"):
        decisions[(d["game_pk"], d["team"])].append(d)
    for v in decisions.values():
        v.sort(key=lambda d: int(d["call"]))
    return games, decisions


def ledger_for(row: dict, params) -> BullpenLedger:
    return BullpenLedger.from_inputs(json.loads(row["relievers_json"]), params)


def rest_bucket(rel) -> str:
    if rel.back_to_back:
        return "b2b"
    if rel.yesterday:
        return "yesterday"
    if len(rel.pitches_days) > 1 and rel.pitches_days[1] > 0:
        return "2_days"
    return "rested"


# ------------------------------------------------------------ workload table (train)

def workload_table(games: list[dict], params) -> dict:
    buckets: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    def add(key, y):
        buckets[key][0] += y
        buckets[key][1] += 1

    for row in games:
        used = set(row["actual_relievers_used"].split(";"))
        for rel in ledger_for(row, params).relievers.values():
            y = int(rel.name in used)
            py = rel.pitches_yesterday
            add("yesterday " + ("0" if py == 0 else "01-14" if py < 15 else "15-24" if py < 25
                                else "25-34" if py < 35 else "35-44" if py < 45 else "45+"), y)
            p3 = rel.pitches_3d
            add("3-day " + ("00-19" if p3 < 20 else "20-39" if p3 < 40 else "40-54" if p3 < 55
                            else "55-69" if p3 < 70 else "70+"), y)
            streak = next((i for i, x in enumerate(rel.pitches_days) if x == 0), len(rel.pitches_days))
            add(f"pitched {min(streak, 4)}{'+' if streak >= 4 else ''} straight days", y)
            add("off day tomorrow" if row["off_day_tomorrow"] == "1" else "game tomorrow", y)
    return {k: {"rate": v[0] / v[1], "n": v[1]} for k, v in sorted(buckets.items())}


# ------------------------------------------------------------- conditional logit

def decision_sets(games, decisions, params, prior_games, offday):
    """Feature matrices for every train bullpen call. Returns (X, chosen, group, counts)."""
    import numpy as np

    r0 = float(params.usage_prior_rate)
    idx = {f: i for i, f in enumerate(FEATURES)}
    rows_x, chosen, group = [], [], []
    counts = defaultdict(int)
    g = 0
    for row in games:
        decs = decisions.get((row["game_pk"], row["team"]), [])
        if not decs:
            continue
        ledger = ledger_for(row, params)
        rels = list(ledger.relievers.values())
        avail = {r.name for r in rels if ledger.is_available(r, params)}
        off = row["off_day_tomorrow"] == "1"
        used = {row["starter_name"]}
        static = {}
        for r in rels:
            v = [0.0] * len(FEATURES)
            if r.role in ROLES3:
                v[idx[f"role_{r.role}"]] = 1.0
            rate = (r.apps + prior_games * r0) / (r.games + prior_games)
            v[idx["usage"]] = math.log(rate / r0)
            m = offday if off else 1.0
            v[idx["yesterday"]] = m * r.yesterday
            v[idx["back_to_back"]] = m * r.back_to_back
            v[idx["three_straight"]] = m * r.three_straight
            v[idx["pitches_3d_10"]] = m * r.pitches_3d / 10
            v[idx["high_workload"]] = m * r.high_workload(int(params.high_workload_pitches))
            static[r.name] = v
        for d in decs:
            counts["calls"] += 1
            name = d["chosen"]
            cands = [r for r in rels if r.name not in used and r.name in avail]
            used.add(name)
            if name not in ledger.relievers:
                counts["chosen not in pool"] += 1
                continue
            if name not in avail:
                counts["chosen ruled out by hard rules"] += 1
                continue
            if name not in {r.name for r in cands}:
                counts["chosen re-entered / duplicate"] += 1
                continue
            inning, lead, outs = int(d["inning"]), int(d["lead"]), int(d["outs"])
            li = compute_leverage_index(inning, lead, outs, d["on_1b"] == "1", d["on_2b"] == "1", d["on_3b"] == "1")
            sit = classify_situation(inning, lead, li, params)
            counts[f"situation {sit}"] += 1
            nxt = d["next_hands"].split(",")
            for r in cands:
                v = list(static[r.name])
                if sit != "middle" and r.role in ROLES3:
                    v[idx[f"sit_{sit}_{r.role}"]] = 1.0
                v[idx["platoon"]] = float(nxt.count(r.hand) >= params.platoon_min_batters)
                rows_x.append(v)
                chosen.append(r.name == name)
                group.append(g)
            g += 1
            counts["calls fitted"] += 1
    return np.array(rows_x), np.array(chosen, dtype=float), np.array(group), dict(counts)


def fit_logit(X, y, grp, ridge=RIDGE, iters=50):
    """Newton-Raphson for the conditional (McFadden) logit; returns (beta, se, loglik, n)."""
    import numpy as np

    n_groups = int(grp.max()) + 1
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        s = X @ beta
        s -= np.bincount(grp, weights=s, minlength=n_groups)[grp] / np.bincount(grp, minlength=n_groups)[grp]
        e = np.exp(s)
        p = e / np.bincount(grp, weights=e, minlength=n_groups)[grp]
        xbar = np.zeros((n_groups, X.shape[1]))
        np.add.at(xbar, grp, X * p[:, None])
        grad = X[y == 1].sum(0) - xbar.sum(0) - ridge * beta
        H = (X * p[:, None]).T @ X - xbar.T @ (xbar) + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, grad)
        beta += step
        if np.abs(step).max() < 1e-7:
            break
    s = X @ beta
    ll = float((s[y == 1]).sum() - np.log(np.bincount(grp, weights=np.exp(s), minlength=n_groups)).sum())
    se = np.sqrt(np.diag(np.linalg.inv(H)))
    return beta, se, ll, n_groups


def null_loglik(grp) -> float:
    import numpy as np

    sizes = np.bincount(grp)
    return float(-np.log(sizes[sizes > 0]).sum())


# ---------------------------------------------------------------- benchmarks

def fit_benchmarks(train: list[dict], params, k: float = 10.0) -> dict:
    """Uniform + usage-frequency benchmark parameters, from TRAIN only."""
    apps = games_n = firsts = 0
    used_pool, pool_n, n_rows = 0, 0, 0
    for row in train:
        used = set(row["actual_relievers_used"].split(";"))
        for r in json.loads(row["relievers_json"]):
            apps += r["apps"]; games_n += r["games"]; firsts += r["firsts"]
            used_pool += r["name"] in used
            pool_n += 1
        n_rows += 1
    r0, q0 = apps / games_n, firsts / games_n
    obs = defaultdict(float); exp_ = defaultdict(float); obs_f = defaultdict(float); exp_f = defaultdict(float)
    for row in train:
        used = set(row["actual_relievers_used"].split(";"))
        for rel in ledger_for(row, params).relievers.values():
            b = rest_bucket(rel)
            obs[b] += rel.name in used
            exp_[b] += (rel.apps + k * r0) / (rel.games + k)
            obs_f[b] += rel.name == row["first_reliever"]
            exp_f[b] += (rel.firsts + k * q0) / (rel.games + k)
    return {
        "k": k, "r0": r0, "q0": q0,
        "uniform_used_per_pool": used_pool / pool_n,
        "rest_factor": {b: obs[b] / exp_[b] for b in REST_BUCKETS if exp_[b]},
        "rest_factor_first": {b: obs_f[b] / exp_f[b] for b in REST_BUCKETS if exp_f[b]},
    }


def score_probs(p_app: dict, p_first: dict, used: set, first: str) -> dict:
    """Same metrics as MlbBullpenModel.score, for benchmark probabilities."""
    eps = 1e-3
    names = list(p_app)
    sq = [(p_app[n] - (n in used)) ** 2 for n in names]
    ll = [-math.log(min(max(p_app[n], eps), 1 - eps) if n in used else 1 - min(max(p_app[n], eps), 1 - eps)) for n in names]
    ranked = sorted(names, key=lambda n: p_app[n], reverse=True)
    in_pool = used & set(names)
    out = {
        "brier": sum(sq) / len(sq), "log_loss_appear": sum(ll) / len(ll),
        "top_pick_correct": float(ranked[0] in used),
        "top_3_recall": len(set(ranked[:3]) & in_pool) / min(3, len(in_pool)) if in_pool else math.nan,
        "brier_first": math.nan, "log_loss": math.nan,
    }
    if first in p_first:
        out["brier_first"] = sum((p_first[n] - (n == first)) ** 2 for n in names)
        out["log_loss"] = -math.log(max(p_first[first], eps))
    return out


def benchmark_scores(rows, bench, params, kind: str) -> list[dict]:
    out = []
    k, r0, q0 = bench["k"], bench["r0"], bench["q0"]
    for row in rows:
        rels = list(ledger_for(row, params).relievers.values())
        used = set(row["actual_relievers_used"].split(";"))
        if kind == "uniform":
            pa = {r.name: bench["uniform_used_per_pool"] for r in rels}
            pf = {r.name: 1 / len(rels) for r in rels}
        else:
            pa, raw_f = {}, {}
            for r in rels:
                b = rest_bucket(r)
                pa[r.name] = min(0.99, max(0.001, (r.apps + k * r0) / (r.games + k) * bench["rest_factor"][b]))
                raw_f[r.name] = (r.firsts + k * q0) / (r.games + k) * bench["rest_factor_first"][b]
            tot = sum(raw_f.values()) or 1.0
            pf = {n: v / tot for n, v in raw_f.items()}
        s = score_probs(pa, pf, used, row["first_reliever"])
        s["_probs"] = [(pa[r.name], int(r.name in used), r.role) for r in rels]
        out.append(s)
    return out


# ------------------------------------------------------------- game engine

def _engine_chunk(args):
    import random

    from ballmonitor.models.mlb_bullpen.simulator import GameSimulator

    rows, overrides = args
    model = registry.load_model("mlb_bullpen", overrides=overrides)
    tot = [0.0] * 7  # starter outs, starter pitches, relievers, relief outs, n, runs for, against
    for row in rows:
        inp, _ = model.backtest_case(row)
        sim = GameSimulator(
            starter_name=inp["starter_name"], starter_hand=inp["starter_hand"],
            starter_stamina=inp.get("starter_stamina", int(model.params.starter_stamina_default)),
            ledger=BullpenLedger.from_inputs(inp["relievers"], model.params), lineup=inp["lineup"],
            params=model.params, is_home=inp["is_home"], off_day_tomorrow=inp["off_day_tomorrow"],
        )
        rng = random.Random(int(row["game_pk"]))
        for _ in range(ENGINE_GAMES_PER_CASE):
            res = sim.simulate_game(rng)
            tot[0] += res.pitchers_used[0].outs_recorded
            tot[1] += res.pitchers_used[0].pitches
            tot[2] += len(res.pitchers_used) - 1
            tot[3] += sum(p.outs_recorded for p in res.pitchers_used[1:])
            tot[4] += 1
            tot[5] += res.team_score
            tot[6] += res.opp_score
    return tot


def engine_stats(rows, overrides) -> dict:
    parts = [(rows[i::WORKERS * 2], dict(overrides)) for i in range(WORKERS * 2)]
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(_engine_chunk, parts))
    t = [sum(r[i] for r in res) for i in range(7)]
    return {"starter_outs": t[0] / t[4], "starter_pitches": t[1] / t[4],
            "relievers": t[2] / t[4], "outs_per_reliever": t[3] / max(t[2], 1),
            "runs_for": t[5] / t[4], "runs_against": t[6] / t[4]}


# ------------------------------------------------------------ model evaluation

def _eval_chunk(args):
    rows, overrides = args
    model = registry.load_model("mlb_bullpen", overrides=overrides)
    out = []
    for row in rows:
        inputs, actual = model.backtest_case(row)
        pred = model.predict(inputs)
        s = model.score(pred, actual)
        n = pred.extras["n_simulations"]
        st = pred.extras["stats"]
        roles = {r.name: r.role for r in BullpenLedger.from_inputs(inputs["relievers"], model.params).relievers.values()}
        pa, pf = pred.extras["p_appear"], pred.extras["p_first"]
        s["_probs"] = [(pa[k], int(k in actual["used"]), roles[k]) for k in st]
        s["_first"] = [(pf[k], int(k == actual["first_reliever"]), roles[k]) for k in st]
        s["_expected_used"] = sum(pa.values())
        s["_actual_used"] = len(set(actual["used"]) & set(st))
        out.append(s)
    return out


def eval_model(rows, overrides=None, chunks=48) -> list[dict]:
    overrides = dict(overrides or {})
    parts = [(rows[i::chunks], overrides) for i in range(chunks)]
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(_eval_chunk, parts))
    # restore original order
    out = [None] * len(rows)
    for i, part in enumerate(res):
        for j, s in enumerate(part):
            out[i + j * chunks] = s
    return out


METRICS = ["brier", "log_loss_appear", "top_pick_correct", "top_3_recall", "brier_first", "log_loss"]


def summarise(scores: list[dict]) -> dict:
    out = {}
    for m in METRICS:
        vals = [s[m] for s in scores if not math.isnan(s[m])]
        out[m] = sum(vals) / len(vals) if vals else math.nan
        if m == "log_loss":
            out["n_first_scored"] = len(vals)
    return out


def paired_se(a: list[dict], b: list[dict], m: str) -> float:
    d = [x[m] - y[m] for x, y in zip(a, b) if not (math.isnan(x[m]) or math.isnan(y[m]))]
    if len(d) < 2:
        return math.nan
    mu = sum(d) / len(d)
    return math.sqrt(sum((x - mu) ** 2 for x in d) / (len(d) - 1) / len(d))


def calibration(scores: list[dict], key="_probs", bins=(0, .1, .2, .3, .4, .5, .6, .7, .8, 1.01)) -> list[dict]:
    cells = [[0.0, 0.0, 0] for _ in bins[:-1]]
    for s in scores:
        for p, y, _ in s[key]:
            for i in range(len(bins) - 1):
                if bins[i] <= p < bins[i + 1]:
                    cells[i][0] += p; cells[i][1] += y; cells[i][2] += 1
                    break
    return [
        {"bin": f"{bins[i]:.1f}-{min(bins[i + 1], 1):.1f}", "n": c[2],
         "mean_p": c[0] / c[2] if c[2] else math.nan, "actual": c[1] / c[2] if c[2] else math.nan}
        for i, c in enumerate(cells)
    ]


def by_role(scores: list[dict], key="_probs") -> dict:
    acc = defaultdict(lambda: [0.0, 0.0, 0])
    for s in scores:
        for p, y, role in s[key]:
            acc[role][0] += p; acc[role][1] += y; acc[role][2] += 1
    return {r: {"n": v[2], "pred": v[0] / v[2], "actual": v[1] / v[2]} for r, v in sorted(acc.items())}


# ======================================================================== v0.5 study
# Improvements evaluated on top of the v0.4.0 simulator (all fitted on 2025 only):
#   1. calibration of the simulated appearance probabilities (+ first-reliever temperature)
#   2. bullpen size: engine (hook) refit on a home/away-balanced 2025 sample, and a rolling
#      team / league usage tendency term
#   3. active-roster filter (MLB Stats API roster on the game date)
#   4. a direct per-reliever logistic regression, and its blend with the simulator

POST_PREFIXES = ("calib_", "direct_", "blend_", "tendency_", "first_", "bullpen_baseline")
CACHE_DIR = DATA_DIR / "raw" / "research_cache"
# v0.4.0 engine (hook) settings, chosen on a home-teams-only sample (see section 1).
V04_HOOKS = {"pitches_per_pa": 3.75, "hook_soft_ratio": 1.05, "hook_force_ratio": 1.15, "late_hook_prob": 0.1,
             "tto_hook_prob": 0.1, "jam_hook_prob": 0.2, "jam_hook_prob_tto": 0.4, "reliever_extend_prob": 0.35,
             "reliever_traffic_hook_prob": 0.3, "reliever_mid_max_pitches": 35, "reliever_mid_max_runs": 3}
IDENTITY_POST = {"calib_intercept_closer": 0.0, "calib_intercept_setup": 0.0, "calib_intercept_middle": 0.0,
                 "calib_intercept_long": 0.0, "calib_slope": 1.0, "tendency_weight": 0.0,
                 "blend_weight_direct": 0.0, "first_weight_sim": 1.0, "first_weight_direct": 0.0}
TEAM_WINDOW_GRID = (10, 20, 40, 80)
TENDENCY_K_GRID = (5, 10, 20, 40, 80, 160)
LEAGUE_DAYS = 30
ROLE_ORDER = ("closer", "setup", "middle", "long")
EPS = 1e-3  # 0.5 / num_simulations: probability clip, same as MlbBullpenModel.score
DIRECT_RIDGE = 1.0


def strip_roster(row: dict) -> dict:
    """Row without the roster columns (v0.4.0 inputs): drop `active` / `new_arrival` flags."""
    rels = json.loads(row["relievers_json"])
    for r in rels:
        r.pop("active", None)
        r.pop("new_arrival", None)
    return dict(row, relievers_json=json.dumps(rels, separators=(",", ":")))


def _strip_ratings(relievers_json: str) -> str:
    """relievers_json without the v0.6.0 run-prevention fields (they do not affect the
    simulation), so cached simulations stay valid."""
    rels = json.loads(relievers_json)
    if not any("ra_outs" in r or "ra_runs" in r for r in rels):
        return relievers_json
    for r in rels:
        r.pop("ra_outs", None)
        r.pop("ra_runs", None)
    return json.dumps(rels, separators=(",", ":"))


def _sim_chunk(args):
    rows, overrides, roster = args
    model = registry.load_model("mlb_bullpen", overrides=overrides)
    out = []
    for row in rows:
        inputs, _ = model.backtest_case(row if roster else strip_roster(row))
        pred = model.predict(inputs)
        n = pred.extras["n_simulations"]
        out.append({k: (v["appearances"] / n, v["first_in"] / n) for k, v in pred.extras["stats"].items()})
    return out


def _sim_key(overrides: dict, roster: bool, rows: list[dict]) -> str:
    import hashlib

    pr = registry.load_model("mlb_bullpen", overrides=overrides).params
    vals = {k: s.value for k, s in pr.specs.items() if not k.startswith(POST_PREFIXES + ("runs_",))}
    blob = json.dumps({"p": vals, "roster": roster, "n": len(rows), "first": rows[0]["game_pk"],
                       "last": rows[-1]["game_pk"], "sim": (MODEL_DIR / "simulator.py").stat().st_size,
                       "inputs": hashlib.sha1("".join(_strip_ratings((r if roster else strip_roster(r))["relievers_json"])
                                                      for r in rows).encode()).hexdigest()},
                      sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def simulate(rows: list[dict], overrides: dict, roster: bool, chunks: int = 64) -> list[dict]:
    """Raw simulated (P_sim(appear), P_sim(first)) per pool reliever for every row (cached)."""
    import gzip

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"sim_{_sim_key(overrides, roster, rows)}.json.gz"
    if path.exists():
        with gzip.open(path, "rt") as fh:
            return json.load(fh)
    parts = [(rows[i::chunks], dict(overrides), roster) for i in range(chunks)]
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(_sim_chunk, parts))
    out = [None] * len(rows)
    for i, part in enumerate(res):
        for j, s in enumerate(part):
            out[i + j * chunks] = s
    with gzip.open(path, "wt") as fh:
        json.dump(out, fh)
    return out


def build_frame(rows: list[dict], params) -> dict:
    """Per reliever-game arrays (pre-game features + outcomes) for every row. `params` must
    carry first_prior_rate / first_prior_games for the first-reliever features."""
    import numpy as np

    from ballmonitor.models.mlb_bullpen.calibration import DIRECT_FEATURES, direct_features, first_features

    ri, names, y, yf, role, X, XF, active, new = [], [], [], [], [], [], [], [], []
    starts, first_in_pool = [], []
    for i, row in enumerate(rows):
        ledger = ledger_for(row, params)
        rels = list(ledger.relievers.values())
        used = set(row["actual_relievers_used"].split(";"))
        avail = {r.name: ledger.is_available(r, params) for r in rels}
        n_av = sum(avail.values())
        stamina = float(row["starter_stamina"]) if row["starter_stamina"] else float(params.starter_stamina_default)
        starts.append(len(names))
        first_in_pool.append(row["first_reliever"] in ledger.relievers)
        for r in rels:
            ri.append(i); names.append(r.name)
            y.append(r.name in used); yf.append(r.name == row["first_reliever"])
            role.append(ROLE_ORDER.index(r.role)); active.append(r.active); new.append(r.new_arrival)
            X.append(direct_features(r, available=avail[r.name], n_available=n_av, starter_stamina=stamina,
                                     off_day_tomorrow=row["off_day_tomorrow"] == "1",
                                     is_home=row["is_home"] == "1", log_ratio=0.0, params=params))
            XF.append(first_features(r, available=avail[r.name], starter_stamina=stamina, params=params))
    return {
        "row": np.array(ri), "name": names, "y": np.array(y, float), "yf": np.array(yf, float),
        "role": np.array(role), "X": np.array(X), "XF": np.array(XF), "active": np.array(active, bool),
        "new": np.array(new, bool), "starts": np.array(starts), "first_in_pool": np.array(first_in_pool),
        "n_rows": len(rows), "tend_col": DIRECT_FEATURES.index("tendency"),
    }


def sim_arrays(frame: dict, sims: list[dict]):
    import numpy as np

    pa = np.empty(len(frame["name"])); pf = np.empty(len(frame["name"]))
    for j, (i, n) in enumerate(zip(frame["row"], frame["name"])):
        pa[j], pf[j] = sims[i][n]
    return pa, pf


def _logit(p):
    import numpy as np

    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def _sigmoid(z):
    import numpy as np

    return 1 / (1 + np.exp(-z))


def fit_logistic(X, y, offset=None, ridge=1e-4, iters=60):
    """Binary logistic regression (Newton, small L2); returns (beta, se)."""
    import numpy as np

    off = np.zeros(len(y)) if offset is None else offset
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        p = _sigmoid(X @ beta + off)
        grad = X.T @ (y - p) - ridge * beta
        H = (X * (p * (1 - p))[:, None]).T @ X + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, grad)
        beta += step
        if np.abs(step).max() < 1e-8:
            break
    se = np.sqrt(np.diag(np.linalg.inv(H)))
    return beta, se


def softmax_rows(score, row, n_rows):
    import numpy as np

    mx = np.full(n_rows, -np.inf)
    np.maximum.at(mx, row, score)
    e = np.exp(score - mx[row])
    return e / np.bincount(row, weights=e, minlength=n_rows)[row]


def score_arrays(frame: dict, p, pf) -> "np.ndarray":
    """Per-row metrics (n_rows x 6, METRICS order) -- same definitions as MlbBullpenModel.score."""
    import numpy as np

    row, y, yf, n = frame["row"], frame["y"], frame["yf"], frame["n_rows"]
    cnt = np.bincount(row, minlength=n)
    pc = np.clip(p, EPS, 1 - EPS)
    brier = np.bincount(row, weights=(p - y) ** 2, minlength=n) / cnt
    ll = np.bincount(row, weights=-(y * np.log(pc) + (1 - y) * np.log(1 - pc)), minlength=n) / cnt
    bf = np.bincount(row, weights=(pf - yf) ** 2, minlength=n)
    lf = -np.log(np.maximum(np.bincount(row, weights=pf * yf, minlength=n), EPS))
    fin = frame["first_in_pool"]
    bf[~fin] = np.nan; lf[~fin] = np.nan
    top = np.zeros(n); top3 = np.full(n, np.nan)
    starts = list(frame["starts"]) + [len(row)]
    for i in range(n):
        a, b = starts[i], starts[i + 1]
        order = a + np.argsort(-p[a:b], kind="stable")
        top[i] = y[order[0]]
        k = y[a:b].sum()
        if k:
            top3[i] = y[order[:3]].sum() / min(3, k)
    return np.column_stack([brier, ll, top, top3, bf, lf])


def dicts_to_array(scores: list[dict]):
    import numpy as np

    return np.array([[s[m] for m in METRICS] for s in scores], float)


def summarise_arr(a, mask=None) -> dict:
    import numpy as np

    a = a if mask is None else a[mask]
    out = {m: float(np.nanmean(a[:, j])) for j, m in enumerate(METRICS)}
    out["n_first_scored"] = int((~np.isnan(a[:, 5])).sum())
    return out


def paired_se_arr(a, b, teams, mask=None) -> dict:
    """Mean difference a - b per metric with naive and team-clustered standard errors."""
    import numpy as np

    teams = np.asarray(teams)
    if mask is not None:
        a, b, teams = a[mask], b[mask], teams[mask]
    out = {}
    for j, m in enumerate(METRICS):
        d = a[:, j] - b[:, j]
        ok = ~np.isnan(d)
        d, t = d[ok], teams[ok]
        n = len(d)
        mu = d.mean()
        se = d.std(ddof=1) / math.sqrt(n)
        groups = {}
        for x, g in zip(d - mu, t):
            groups[g] = groups.get(g, 0.0) + x
        G = len(groups)
        cse = math.sqrt(sum(v * v for v in groups.values()) / n ** 2 * G / (G - 1))
        out[m] = {"diff": float(mu), "se": float(se), "cluster_se": float(cse)}
    return out


def calibration_arr(p, y, bins=(0, .1, .2, .3, .4, .5, .6, .7, .8, 1.01)) -> list[dict]:
    import numpy as np

    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p >= lo) & (p < hi)
        out.append({"bin": f"{lo:.1f}-{min(hi, 1):.1f}", "n": int(m.sum()),
                    "mean_p": float(p[m].mean()) if m.any() else math.nan,
                    "actual": float(y[m].mean()) if m.any() else math.nan})
    return out


def by_role_arr(frame, p, pf) -> dict:
    out = {}
    for k, r in enumerate(ROLE_ORDER):
        m = frame["role"] == k
        out[r] = {"n": int(m.sum()), "pred": float(p[m].mean()), "actual": float(frame["y"][m].mean()),
                  "pred_first": float(pf[m].mean()), "actual_first": float(frame["yf"][m].mean())}
    return out


def tendency_column(rows: list[dict], all_rows: list[dict], team_games: int, k: float, baseline: float):
    """ln(shrunk team relievers per game / baseline) per row (pre-game, earlier dates only)."""
    import numpy as np

    from ballmonitor.models.mlb_bullpen.tendency import rolling_usage

    roll = rolling_usage(all_rows, team_games, LEAGUE_DAYS)

    class _P:  # minimal params for shrunk_relievers
        tendency_prior_games = k
        bullpen_baseline_relievers = baseline

    from ballmonitor.models.mlb_bullpen.tendency import log_usage_ratio

    return np.array([
        log_usage_ratio(v["team_recent_relievers"], v["team_recent_games"], v["league_recent_relievers"], _P)[0]
        for v in (roll[(r["game_pk"], r["team"])] for r in rows)
    ])


# ---- appearance-probability methods (fit on a mask of reliever rows, predict all)

def design_cal(frame, ls, per_role_slope=False):
    import numpy as np

    R = np.eye(4)[frame["role"]]
    cols = [R, ls[:, None]] if not per_role_slope else [R, R * ls[:, None]]
    return np.hstack(cols)


def fit_predict_appear(method: str, frame, ls, lnR, fit_mask, ldir=None) -> tuple:
    """Fit `method` on reliever rows `fit_mask`, return (probabilities for all rows, params)."""
    import numpy as np

    y = frame["y"]
    if method == "raw":
        return _sigmoid(ls), {}
    if method == "tendency":
        X = lnR[:, None]
        b, se = fit_logistic(X[fit_mask], y[fit_mask], offset=ls[fit_mask])
        return _sigmoid(ls + X @ b), {"tendency_weight": (b[0], se[0])}
    if method in ("cal", "cal_tend", "blend"):
        R = np.eye(4)[frame["role"]]
        cols = [R, ls[:, None]]
        names = [f"calib_intercept_{r}" for r in ROLE_ORDER] + ["calib_slope"]
        if method in ("cal_tend", "blend"):
            cols.append(lnR[:, None]); names.append("tendency_weight")
        if method == "blend":
            cols.append(ldir[:, None]); names.append("blend_weight_direct")
        X = np.hstack(cols)
        b, se = fit_logistic(X[fit_mask], y[fit_mask])
        return _sigmoid(X @ b), {n: (bb, s) for n, bb, s in zip(names, b, se)}
    if method == "cal_global":
        X = np.column_stack([np.ones(len(ls)), ls])
        b, se = fit_logistic(X[fit_mask], y[fit_mask])
        return _sigmoid(X @ b), {"intercept": (b[0], se[0]), "slope": (b[1], se[1])}
    if method == "cal_role_slope":
        X = design_cal(frame, ls, per_role_slope=True)
        b, se = fit_logistic(X[fit_mask], y[fit_mask])
        return _sigmoid(X @ b), {}
    raise ValueError(method)


def fit_direct(frame, lnR, fit_mask):
    """Direct logistic regression on DIRECT_FEATURES (intercept unpenalised in effect: tiny ridge)."""
    import numpy as np

    X = frame["X"].copy()
    X[:, frame["tend_col"]] = lnR
    b, se = fit_logistic(X[fit_mask], frame["y"][fit_mask], ridge=DIRECT_RIDGE)
    return b, se, X


def oof_direct(frame, lnR, fit_rows_mask_fn, months_rel):
    """Out-of-fold direct-model logits on the fitting set: 2 folds by month parity."""
    import numpy as np

    X = frame["X"].copy()
    X[:, frame["tend_col"]] = lnR
    out = np.full(len(X), np.nan)
    fit = fit_rows_mask_fn
    for parity in (0, 1):
        tr = fit & (months_rel % 2 != parity)
        te = fit & (months_rel % 2 == parity)
        b, _ = fit_logistic(X[tr], frame["y"][tr], ridge=DIRECT_RIDGE)
        out[te] = X[te] @ b
    return out


def fit_first(method: str, frame, lsf, fit_mask_rows, ldirf=None):
    """First-reliever methods (conditional logit over the pool, rows where the first arm was in
    the pool). Returns (probabilities for all reliever rows, params)."""
    import numpy as np

    row, n = frame["row"], frame["n_rows"]
    if method == "raw":
        return np.exp(lsf) / np.bincount(row, weights=np.exp(lsf), minlength=n)[row], {}
    fin = frame["first_in_pool"][row]
    m = fit_mask_rows & fin
    # regroup rows to consecutive ids for fit_logit
    _, grp = np.unique(row[m], return_inverse=True)
    if method == "temperature":
        X = lsf[:, None]
    elif method == "direct":
        X = frame["XF"]
    elif method == "blend":
        X = np.column_stack([lsf, ldirf])
    else:
        raise ValueError(method)
    beta, se, _, _ = fit_logit(X[m], frame["yf"][m], grp, ridge=1e-3 if method != "direct" else 1.0)
    s = X @ beta
    p = softmax_rows(s, row, n)
    return p, {"beta": beta.tolist(), "se": se.tolist()}


def oof_first_direct(frame, fit_mask_rows, months_rel):
    import numpy as np

    row = frame["row"]
    fin = frame["first_in_pool"][row]
    out = np.full(len(row), np.nan)
    for parity in (0, 1):
        tr = fit_mask_rows & fin & (months_rel % 2 != parity)
        te = fit_mask_rows & (months_rel % 2 == parity)
        _, grp = np.unique(row[tr], return_inverse=True)
        beta = fit_logit(frame["XF"][tr], frame["yf"][tr], grp, ridge=1.0)[0]
        out[te] = frame["XF"][te] @ beta
    return out


def roster_stats(rows: list[dict], frame: dict, sims_v04: list[dict]) -> dict:
    """Roster diagnostics: arms in the (game-day) pool that the API's date roster no longer
    lists (end-of-day moves), same-day arrivals, departures since yesterday, later IL moves,
    with their actual appearance rates and the v0.4.0 simulated probability."""
    import numpy as np

    pa, _ = sim_arrays(frame, sims_v04)
    y, new = frame["y"], frame["new"]

    def flag(col):
        look = {(i, nm) for i, r in enumerate(rows) for nm in (r.get(col) or "").split(";") if nm}
        return np.array([(i, nm) in look for i, nm in zip(frame["row"], frame["name"])])

    eod, later = flag("off_roster_eod"), flag("later_il")
    dep = [int(r["roster_departed"]) for r in rows if (r.get("roster_departed") or "") != ""]
    rate = lambda m: float(y[m].mean()) if m.any() else math.nan  # noqa: E731
    simm = lambda m: float(pa[m].mean()) if m.any() else math.nan  # noqa: E731
    return {
        "reliever_games": int(len(y)), "inactive_in_pool": int((~frame["active"]).sum()),
        "off_eod": int(eod.sum()), "off_eod_appeared": int(y[eod].sum()),
        "new_arrivals": int(new.sum()), "new_appear_rate": rate(new), "new_sim_mean": simm(new),
        "others_appear_rate": rate(~new), "others_sim_mean": simm(~new),
        "departed_per_game": sum(dep) / len(dep) if dep else math.nan,
        "games_with_departure": sum(1 for x in dep if x) / len(dep) if dep else math.nan,
        "later_il": int(later.sum()), "later_il_appear_rate": rate(later), "later_il_sim_mean": simm(later),
    }


# ------------------------------------------------------------------------ study

ENGINE_GRID_V05 = [_V03_HOOKS] + [
    dict(V04_HOOKS, reliever_extend_prob=ext, jam_hook_prob=jam, jam_hook_prob_tto=jam_tto, pitches_per_pa=ppa)
    for ext in (0.35, 0.45, 0.55) for jam, jam_tto in ((0.2, 0.4), (0.1, 0.25)) for ppa in (3.75, 3.65)
]


def _r3(x: float) -> float:
    return round(float(x), 3)


def study_v05(games: list[dict], train: list[dict], test: list[dict], p, new_hooks: dict, bench: dict) -> dict:
    """Improvements 1-4 (see the v0.5 block above). Everything is fitted on reliever rows from
    2025 (season-forward) or from all games before each 2026 month (walk-forward)."""
    import numpy as np

    from ballmonitor.models.mlb_bullpen.calibration import DIRECT_FEATURES, FIRST_FEATURES

    rows = train + test
    q0 = _r3(bench["q0"])
    pf_params = registry.load_model("mlb_bullpen", overrides={"first_prior_rate": q0, "first_prior_games": 10.0}).params
    print("simulating (cached) ...")
    sims = {"v04": simulate(rows, V04_HOOKS, roster=False), "eng": simulate(rows, new_hooks, roster=False)}
    has_flags = any("active" in x or "new_arrival" in x for r in rows for x in json.loads(r["relievers_json"]))
    # roster flags only change the simulation through `active` (new_arrival is a direct-model
    # feature); the built pool is the game-day roster, so these are normally identical
    has_active = any("active" in x for r in rows for x in json.loads(r["relievers_json"]))
    sims["v04_roster"] = simulate(rows, V04_HOOKS, roster=True) if has_active else sims["v04"]
    sims["eng_roster"] = simulate(rows, new_hooks, roster=True) if has_active else sims["eng"]
    print(f"  roster flags in data: {has_flags}, active flags: {has_active}")
    fr = build_frame(rows, pf_params)
    row_season = np.array([r["season"] for r in rows])
    row_month = np.array([r["game_date"][:7] for r in rows])
    rel_month = row_month[fr["row"]]
    month_idx = np.array([int(m[:4]) * 12 + int(m[5:7]) for m in rel_month])
    tr = row_season[fr["row"]] == TRAIN_SEASON
    rows_te = row_season == TEST_SEASON
    teams = np.array([r["team"] for r in rows])
    PA, PF, LS, LSF = {}, {}, {}, {}
    for k, v in sims.items():
        PA[k], PF[k] = sim_arrays(fr, v)
        LS[k] = _logit(PA[k])
        LSF[k] = np.log(np.clip(PF[k], EPS, 1))
    baseline = round(float(fr["y"][tr].sum() / (~rows_te).sum()), 2)

    # --- tendency window / shrinkage grid (train log-likelihood of calibration + tendency)
    tgrid, best = [], None
    for n_games in TEAM_WINDOW_GRID:
        for k in TENDENCY_K_GRID:
            lnr = tendency_column(rows, rows, n_games, k, baseline)[fr["row"]]
            pp, par = fit_predict_appear("cal_tend", fr, LS["eng_roster"], lnr, tr)
            y = fr["y"]
            pc = np.clip(pp, EPS, 1 - EPS)
            ll = float((y * np.log(pc) + (1 - y) * np.log(1 - pc))[tr].sum())
            tgrid.append({"team_games": n_games, "k": k, "loglik": ll, "weight": float(par["tendency_weight"][0])})
            if best is None or ll > best[0]:
                best = (ll, n_games, k, lnr)
    _, t_games, t_k, lnR = best
    print(f"  tendency: last {t_games} team-games, k = {t_k}")

    # --- methods: fit on a reliever mask, predict every row
    def predict(kind: str, fit: "np.ndarray") -> tuple:
        info = {}
        if kind in ("v04", "eng", "v04_roster", "eng_roster"):
            return PA[kind], PF[kind], info
        if kind == "cal":
            pa, info = fit_predict_appear("cal", fr, LS["v04"], lnR, fit)
            return pa, PF["v04"], info
        if kind == "tend":
            pa, info = fit_predict_appear("tendency", fr, LS["v04"], lnR, fit)
            return pa, PF["v04"], info
        if kind == "eng_tend":
            pa, info = fit_predict_appear("tendency", fr, LS["eng"], lnR, fit)
            return pa, PF["eng"], info
        if kind == "cal_eng_tend":
            pa, info = fit_predict_appear("cal_tend", fr, LS["eng"], lnR, fit)
            return pa, PF["eng"], info
        if kind == "sim_all":
            pa, info = fit_predict_appear("cal_tend", fr, LS["eng_roster"], lnR, fit)
            return pa, PF["eng_roster"], info
        if kind == "first_temp":
            pf, info = fit_first("temperature", fr, LSF["eng_roster"], fit)
            return PA["eng_roster"], pf, info
        fit_rows = fit.copy()
        if kind == "direct_noroster":
            fr0 = {**fr, "X": fr["X"].copy(), "XF": fr["XF"].copy()}
            fr0["X"][:, DIRECT_FEATURES.index("new_arrival")] = 0.0
            fr0["XF"][:, FIRST_FEATURES.index("new_arrival")] = 0.0
            b, se, X = fit_direct(fr0, lnR, fit_rows)
            pfd, _ = fit_first("direct", fr0, LSF["eng_roster"], fit_rows)
            return _sigmoid(X @ b), pfd, {}
        b, se, X = fit_direct(fr, lnR, fit_rows)
        ldir = X @ b
        pfd, finfo = fit_first("direct", fr, LSF["eng_roster"], fit_rows)
        if kind == "direct":
            return _sigmoid(ldir), pfd, {"direct": (b, se), "first_direct": finfo}
        if kind == "blend":
            oof = oof_direct(fr, lnR, fit_rows, month_idx)
            ldir_b = np.where(fit_rows, oof, ldir)
            pa, info = fit_predict_appear("blend", fr, LS["eng_roster"], lnR, fit_rows, ldir=ldir_b)
            ooff = oof_first_direct(fr, fit_rows, month_idx)
            sfd = fr["XF"] @ np.array(finfo["beta"])
            pf, finfo2 = fit_first("blend", fr, LSF["eng_roster"], fit_rows, ldirf=np.where(fit_rows, ooff, sfd))
            return pa, pf, {"blend": info, "first_blend": finfo2, "direct": (b, se), "first_direct": finfo}
        raise ValueError(kind)

    VARIANTS = [
        ("v04", "v0.4.0 (simulation as-is)"),
        ("cal", "1. calibration (role intercepts + slope on logit P_sim)"),
        ("eng", "2a. engine refit on a home/away-balanced 2025 sample"),
        ("tend", "2b. team / league usage tendency"),
        ("eng_tend", "2a + 2b"),
        ("sim_all", "1 + 2 (simulator, all simulator-side improvements)"),
        ("first_temp", "2a, plus first-reliever temperature"),
        ("direct_noroster", "4. direct model without the roster feature (3)"),
        ("direct", "3 + 4. direct logistic model (no simulator)"),
        ("blend", "blend: simulator (1 + 2) + direct model (3 + 4)"),
    ]
    WF = ("cal", "tend", "sim_all", "direct", "blend")
    preds, info = {}, {}
    for key, _ in VARIANTS:
        pa, pf, inf = predict(key, tr)
        preds[key] = (pa, pf)
        info[key] = inf
        print(f"  {key}: done")
    # walk-forward inside 2026: refit before each month on everything earlier
    months = sorted(set(row_month[rows_te]))
    wf_preds = {}
    for key in WF:
        pa_w, pf_w = np.full(len(fr["y"]), np.nan), np.full(len(fr["y"]), np.nan)
        for m in months:
            fit = rel_month < m
            pa, pf, _ = predict(key, fit)
            sel = rel_month == m
            pa_w[sel], pf_w[sel] = pa[sel], pf[sel]
        wf_preds[key] = (np.where(tr, preds[key][0], pa_w), np.where(tr, preds[key][1], pf_w))
        print(f"  walk-forward {key}: done")

    test_rows = [r for r in rows if r["season"] == TEST_SEASON]
    bench_freq = dicts_to_array(benchmark_scores(test_rows, bench, p, "frequency"))
    bench_unif = dicts_to_array(benchmark_scores(test_rows, bench, p, "uniform"))
    scores = {k: score_arrays(fr, *preds[k])[rows_te] for k, _ in VARIANTS}
    wf_scores = {k: score_arrays(fr, *wf_preds[k])[rows_te] for k in WF}
    te_teams = teams[rows_te]
    n_te = int(rows_te.sum())
    te = ~tr

    def used(pa, mask):
        return float(pa[mask].sum() / len(set(fr["row"][mask])))

    summary = {}
    for key, label in VARIANTS:
        summary[label] = {**summarise_arr(scores[key]), "key": key, "used": used(preds[key][0], te),
                          "vs_v04": paired_se_arr(scores[key], scores["v04"], te_teams),
                          "vs_freq": paired_se_arr(scores[key], bench_freq, te_teams)}
    summary["usage-frequency benchmark"] = {**summarise_arr(bench_freq), "key": "freq", "used": math.nan,
                                            "vs_v04": paired_se_arr(bench_freq, scores["v04"], te_teams),
                                            "vs_freq": None}
    summary["uniform benchmark"] = {**summarise_arr(bench_unif), "key": "uniform", "used": math.nan,
                                    "vs_v04": paired_se_arr(bench_unif, scores["v04"], te_teams), "vs_freq": None}
    wf_summary = {}
    for key in WF:
        label = dict(VARIANTS)[key]
        wf_summary[label] = {**summarise_arr(wf_scores[key]), "key": key,
                             "vs_v04": paired_se_arr(wf_scores[key], scores["v04"], te_teams),
                             "vs_freq": paired_se_arr(wf_scores[key], bench_freq, te_teams),
                             "vs_season_forward": paired_se_arr(wf_scores[key], scores[key], te_teams)}
    by_month = {}
    for m in months:
        mm = row_month[rows_te] == m
        by_month[m] = {"n": int(mm.sum()), "v04": summarise_arr(scores["v04"], mm),
                       "blend": summarise_arr(scores["blend"], mm), "sim_all": summarise_arr(scores["sim_all"], mm),
                       "direct": summarise_arr(scores["direct"], mm), "freq": summarise_arr(bench_freq, mm)}
    freq_probs = [x for s in benchmark_scores(test_rows, bench, p, "frequency") for x in s["_probs"]]
    calib = {k: calibration_arr(preds[k][0][te], fr["y"][te]) for k in ("v04", "cal", "sim_all", "direct", "blend")}
    calib["freq"] = calibration_arr(np.array([x[0] for x in freq_probs]), np.array([x[1] for x in freq_probs]))
    roles = {k: by_role_arr({**fr, "role": fr["role"][te], "y": fr["y"][te], "yf": fr["yf"][te]},
                            preds[k][0][te], preds[k][1][te]) for k in ("v04", "cal", "sim_all", "direct", "blend")}
    used_table = {
        "actual": {"2025": used(fr["y"], tr), "2026": used(fr["y"], te)},
        **{k: {"2025": used(preds[k][0], tr), "2026": used(preds[k][0], te)}
           for k in ("v04", "eng", "cal", "tend", "sim_all", "direct", "blend")},
    }
    roster = {"2025": roster_stats(train, build_sub(fr, tr), sims["v04"][: len(train)]),
              "2026": roster_stats(test, build_sub(fr, te), sims["v04"][len(train):])}

    # fitted numbers that become config defaults (from the promoted blend, fitted on 2025)
    bl = info["blend"]
    fitted = {
        "tendency_prior_games": {"value": float(t_k), "se": None},
        "bullpen_baseline_relievers": {"value": baseline, "se": None},
        "first_prior_rate": {"value": q0, "se": None},
        "first_prior_games": {"value": 10.0, "se": None},
    }
    for name, (b, s_) in bl["blend"].items():
        fitted[name] = {"value": _r3(b), "se": _r3(s_)}
    fitted["first_weight_sim"] = {"value": _r3(bl["first_blend"]["beta"][0]), "se": _r3(bl["first_blend"]["se"][0])}
    fitted["first_weight_direct"] = {"value": _r3(bl["first_blend"]["beta"][1]), "se": _r3(bl["first_blend"]["se"][1])}
    for f, b, s_ in zip(DIRECT_FEATURES, *bl["direct"]):
        fitted[f"direct_{f}"] = {"value": _r3(b), "se": _r3(s_)}
    for f, b, s_ in zip(FIRST_FEATURES, bl["first_direct"]["beta"], bl["first_direct"]["se"]):
        fitted[f"first_direct_{f}"] = {"value": _r3(b), "se": _r3(s_)}
    params_info = {
        k: {n: [float(v[0]), float(v[1])] for n, v in info[k].items()} for k in ("cal", "tend", "eng_tend", "sim_all")
    }
    params_info["first_temp"] = info["first_temp"]
    return {
        "summary": summary, "walk_forward": wf_summary, "by_month": by_month, "calibration": calib,
        "by_role": roles, "used": used_table, "roster": roster, "fitted": fitted, "params": params_info,
        "tendency": {"grid": tgrid, "team_games": t_games, "k": t_k, "league_days": LEAGUE_DAYS, "baseline": baseline},
        "n_test": n_te, "months": months,
    }


def build_sub(fr: dict, mask) -> dict:
    """Restrict a frame to the reliever rows in `mask` (whole team-games), renumbering rows."""
    import numpy as np

    rows_kept = np.unique(fr["row"][mask])
    remap = {int(r): i for i, r in enumerate(rows_kept)}
    new_row = np.array([remap[int(r)] for r in fr["row"][mask]])
    starts = np.searchsorted(new_row, np.arange(len(rows_kept)))
    return {**fr, "row": new_row, "name": [n for n, m in zip(fr["name"], mask) if m],
            "y": fr["y"][mask], "yf": fr["yf"][mask], "role": fr["role"][mask], "X": fr["X"][mask],
            "XF": fr["XF"][mask], "active": fr["active"][mask], "new": fr["new"][mask], "starts": starts,
            "first_in_pool": fr["first_in_pool"][rows_kept], "n_rows": len(rows_kept)}


def run_study() -> dict:
    import numpy as np

    from ballmonitor.models.mlb_bullpen.tendency import pool_used

    games, decisions = load()
    train = [g for g in games if g["season"] == TRAIN_SEASON]
    test = [g for g in games if g["season"] == TEST_SEASON]
    model = registry.load_model("mlb_bullpen")
    p = model.params
    print(f"train {len(train)} team-games, test {len(test)}")

    # 1. workload table (train)
    wl = workload_table(train, p)

    # 2a. role-inference rules: grid on train calls (log-likelihood of the full logit)
    r0 = round(fit_benchmarks(train, p)["r0"], 3)  # train-average relief appearance rate
    role_grid = []
    for rg in ROLE_GRID:
        pr = registry.load_model("mlb_bullpen", overrides={**rg, "usage_prior_rate": r0}).params
        X, y, grp, _ = decision_sets(train, decisions, pr, 10, 1.0)
        ll = fit_logit(X, y, grp)[2]
        role_grid.append({**rg, "loglik": ll})
    best_roles = max(role_grid, key=lambda g: g["loglik"])
    role_overrides = {k: best_roles[k] for k in ROLE_GRID[0]}
    p_roles = registry.load_model("mlb_bullpen", overrides={**role_overrides, "usage_prior_rate": r0}).params
    print("  roles:", role_overrides)

    # 2b. conditional logit (train), grid over shrinkage and off-day discount
    grid = []
    best = None
    for k in PRIOR_GAMES_GRID:
        for off in OFFDAY_GRID:
            X, y, grp, counts = decision_sets(train, decisions, p_roles, k, off)
            beta, se, ll, n = fit_logit(X, y, grp)
            grid.append({"usage_prior_games": k, "off_day_tomorrow_discount": off, "loglik": ll, "calls": n})
            if best is None or ll > best["loglik"]:
                best = {"usage_prior_games": k, "off_day_tomorrow_discount": off, "loglik": ll,
                        "beta": beta, "se": se, "n": n, "counts": counts, "null": null_loglik(grp)}
    fitted = {}
    for f, b, s in zip(FEATURES, best["beta"], best["se"]):
        param, sign = PARAM_OF[f]
        fitted[param] = {"value": round(float(sign * b), 2), "se": round(float(s), 2)}
    fitted["usage_prior_games"] = {"value": best["usage_prior_games"], "se": None}
    fitted["off_day_tomorrow_discount"] = {"value": best["off_day_tomorrow_discount"], "se": None}
    fitted["usage_prior_rate"] = {"value": r0, "se": None}
    for k2, v2 in role_overrides.items():
        fitted[k2] = {"value": v2, "se": None}
    pseudo_r2 = 1 - best["loglik"] / best["null"]

    # 3. benchmarks (train fit) + game-engine grid on a home/away-BALANCED train sample
    # (both teams of every even game_pk; v0.4.0 used every 2nd row = home teams only)
    bench = fit_benchmarks(train, p)
    eng_rows = [r for r in train if int(r["game_pk"]) % 2 == 0]

    def actual_of(rs):
        return {"relievers": sum(pool_used(r) for r in rs) / len(rs),
                "all_relievers": sum(int(r["n_relievers"]) for r in rs) / len(rs),
                "starter_outs": sum(int(r["starter_outs"]) for r in rs) / len(rs),
                "starter_pitches": sum(int(r["starter_pitches"]) for r in rs) / len(rs),
                "runs": sum(int(r["runs_for"]) for r in rs) / len(rs), "n": len(rs)}

    actual_engine = actual_of(eng_rows)
    engine_grid = []
    for ov in ENGINE_GRID_V05:
        st = engine_stats(eng_rows, ov)
        err = ((st["relievers"] - actual_engine["relievers"]) / actual_engine["relievers"]) ** 2 + (
            (st["starter_outs"] - actual_engine["starter_outs"]) / actual_engine["starter_outs"]) ** 2
        engine_grid.append({"settings": ov, **st, "error": err})
        print("  engine", {k: round(v, 2) for k, v in st.items()})
    best_engine = min(engine_grid, key=lambda g: g["error"])
    home_old = train[:: max(1, len(train) // ENGINE_SAMPLE)]  # the v0.4.0 sample
    split = {}
    for side, rs in (("home", [r for r in eng_rows if r["is_home"] == "1"]),
                     ("away", [r for r in eng_rows if r["is_home"] == "0"])):
        split[side] = {"actual": actual_of(rs), "v04": engine_stats(rs, V04_HOOKS),
                       "chosen": engine_stats(rs, best_engine["settings"])}
    engine_check = {"n": len(eng_rows), "actual": actual_engine, "grid": engine_grid,
                    "chosen": best_engine["settings"], "config": engine_stats(eng_rows, {}), "split": split,
                    "v04_sample": {"n": len(home_old), "home_share": sum(r["is_home"] == "1" for r in home_old) / len(home_old),
                                   "actual": actual_of(home_old)}}
    for k2, v2 in best_engine["settings"].items():
        fitted[k2] = {"value": v2, "se": None}

    # 4. v0.5 improvements (calibration, tendency, roster, direct model, blend)
    v05 = study_v05(games, train, test, p, best_engine["settings"], bench)
    fitted.update(v05["fitted"])

    if os.environ.get("BP_FIT_ONLY"):
        print(json.dumps({k: v["value"] for k, v in fitted.items()}, indent=1))
        return {}
    config_vs_fit = {k: {"fit": v["value"], "config": float(getattr(p, k))} for k, v in fitted.items()}
    mismatched = {k: v for k, v in config_vs_fit.items() if abs(v["fit"] - v["config"]) > 1e-9}
    if mismatched:
        print("WARNING: config defaults differ from the train fit:", mismatched)

    # 5. the shipped model (config defaults, model.py code path) on the whole test season
    print("evaluating config defaults on test ...")
    res_model = eval_model(test)
    cfg = dicts_to_array(res_model)
    out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "train": {"team_games": len(train), "dates": [train[0]["game_date"], train[-1]["game_date"]],
                  "teams": len({r["team"] for r in train})},
        "test": {"team_games": len(test), "dates": [test[0]["game_date"], test[-1]["game_date"]],
                 "teams": len({r["team"] for r in test}), "games": len({r["game_pk"] for r in test})},
        "workload_table": wl,
        "role_grid": role_grid,
        "logit": {"features": FEATURES, "fitted": {k: fitted[k] for k in [PARAM_OF[f][0] for f in FEATURES]},
                  "grid": grid, "counts": best["counts"], "calls": best["n"], "loglik": best["loglik"],
                  "null_loglik": best["null"], "pseudo_r2": pseudo_r2, "ridge": RIDGE},
        "fitted": fitted,
        "config_vs_fit": config_vs_fit,
        "benchmarks_fit": bench,
        "engine_check": engine_check,
        "v05": v05,
        "config_defaults": {**summarise_arr(cfg), "used": sum(s["_expected_used"] for s in res_model) / len(res_model),
                            "actual_used": sum(s["_actual_used"] for s in res_model) / len(res_model)},
    }
    RESEARCH_JSON.write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    RESEARCH_MD.write_text(render_md(out), encoding="utf-8")
    return out


def _f(x, nd=4):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def _d(se: dict | None, m: str, nd=4) -> str:
    if not se:
        return "—"
    v = se[m]
    return f"{v['diff']:+.{nd}f} ± {v['se']:.{nd}f} ({v['cluster_se']:.{nd}f})"


def render_md(o: dict) -> str:
    tr, te, lg, v = o["train"], o["test"], o["logit"], o["v05"]
    S = v["summary"]
    md = [
        "# Research: mlb_bullpen walk-forward study",
        "",
        "_Generated by `python -m ballmonitor.models.mlb_bullpen.research`; do not edit by hand._",
        "",
        f"Data: MLB Stats API box scores, play-by-play, active rosters and transactions (`fetch.py`). "
        f"**Train** = 2025 regular season, {tr['team_games']} team-games ({tr['dates'][0]} to {tr['dates'][1]}, "
        f"{tr['teams']} teams). **Test** = 2026 regular season, {te['team_games']} team-games from {te['games']} "
        f"games ({te['dates'][0]} to {te['dates'][1]}, {te['teams']} teams). Every fitted number in the "
        "season-forward results uses train only; the test season is scored once. The walk-forward rows refit "
        "the fitted parts before each 2026 month on all earlier games (2025 + earlier 2026 months; the "
        "simulator's choice weights and hook settings stay at their 2025 fit), giving "
        f"{len(v['months'])} monthly test splits. A team-game is one case; cases within a team share a "
        "bullpen, so the effective sample is smaller than the count: standard errors are shown naive and, "
        "in brackets, clustered by team (30 clusters).",
        "",
        "Every input is pre-game information: workloads from earlier games, usage history and inferred "
        "roles from earlier roster-games, starter stamina from earlier starts, posted lineups, the "
        "published schedule, the game-day active roster, and team / league usage from earlier dates.",
        "",
        "## 1. Test-season results (2026, out of sample)",
        "",
        "Season-forward: fitted on 2025, scored on all of 2026. `Used` = expected pool relievers per "
        f"team-game (actual {v['used']['actual']['2026']:.2f}).",
        "",
        "| Method | Brier | Log loss | Top pick | Top-3 | First Brier | First LL | Used |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for name, s in S.items():
        md.append(
            f"| {name} | {_f(s['brier'])} | {_f(s['log_loss_appear'])} | {s['top_pick_correct']:.1%} | "
            f"{s['top_3_recall']:.1%} | {_f(s['brier_first'])} | {_f(s['log_loss'], 3)} | {_f(s['used'], 2)} |"
        )
    c = o["config_defaults"]
    md += [
        "",
        f"**Shipped config (v0.5.0 defaults, run through `model.py`)**: Brier {_f(c['brier'])}, log loss "
        f"{_f(c['log_loss_appear'])}, top pick {c['top_pick_correct']:.1%}, first-reliever log loss "
        f"{_f(c['log_loss'], 3)}, {c['used']:.2f} expected vs {c['actual_used']:.2f} actual pool relievers "
        "per team-game (should match the blend row up to coefficient rounding).",
        "",
        "Paired differences over test team-games (± naive s.e. (team-clustered s.e.); negative = better "
        "for Brier / log loss):",
        "",
        "| Method | Brier vs v0.4.0 | Log loss vs v0.4.0 | First LL vs v0.4.0 | Log loss vs usage-freq. | First LL vs usage-freq. |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]
    for name, s in S.items():
        if s["key"] in ("v04", "uniform"):
            continue
        md.append(f"| {name} | {_d(s['vs_v04'], 'brier')} | {_d(s['vs_v04'], 'log_loss_appear')} | "
                  f"{_d(s['vs_v04'], 'log_loss', 3)} | {_d(s['vs_freq'], 'log_loss_appear')} | "
                  f"{_d(s['vs_freq'], 'log_loss', 3)} |")
    md += ["", "### Walk-forward inside 2026 (monthly refits)", "",
           "| Method | Brier | Log loss | Top pick | First LL | Log loss vs v0.4.0 | Log loss vs season-forward |",
           "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |"]
    for name, s in v["walk_forward"].items():
        md.append(f"| {name} | {_f(s['brier'])} | {_f(s['log_loss_appear'])} | {s['top_pick_correct']:.1%} | "
                  f"{_f(s['log_loss'], 3)} | {_d(s['vs_v04'], 'log_loss_appear')} | "
                  f"{_d(s['vs_season_forward'], 'log_loss_appear')} |")
    md += ["", "### By month (test, season-forward)", "",
           "| Month | Team-games | Log loss v0.4.0 | sim 1+2 | direct | blend | usage-freq. | First LL v0.4.0 | First LL blend |",
           "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"]
    for m, b in v["by_month"].items():
        md.append(f"| {m} | {b['n']} | {_f(b['v04']['log_loss_appear'])} | {_f(b['sim_all']['log_loss_appear'])} | "
                  f"{_f(b['direct']['log_loss_appear'])} | {_f(b['blend']['log_loss_appear'])} | "
                  f"{_f(b['freq']['log_loss_appear'])} | {_f(b['v04']['log_loss'], 3)} | {_f(b['blend']['log_loss'], 3)} |")
    labels = {"v04": "v0.4.0", "cal": "1. calibrated", "sim_all": "sim 1+2", "direct": "direct", "blend": "blend",
              "freq": "usage-freq."}
    md += ["", "### Calibration of appearance probabilities (test): mean predicted → actual rate (n) per bin", "",
           "| Predicted | " + " | ".join(labels.values()) + " |",
           "| :---: | " + " | ".join(":---:" for _ in labels) + " |"]
    for i, row in enumerate(v["calibration"]["v04"]):
        cells = []
        for k in labels:
            cc = v["calibration"][k][i]
            cells.append(f"{_f(cc['mean_p'], 2)} → {_f(cc['actual'], 3)} ({cc['n']})" if cc["n"] else "—")
        md.append(f"| {row['bin']} | " + " | ".join(cells) + " |")
    md += ["", "### By inferred role (test): mean predicted vs actual", "",
           "| Role | n | Actual appear | v0.4.0 | 1. calibrated | sim 1+2 | direct | blend | Actual first | v0.4.0 first | blend first |",
           "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"]
    for role, a in v["by_role"]["v04"].items():
        r = {k: v["by_role"][k][role] for k in ("cal", "sim_all", "direct", "blend")}
        md.append(f"| {role} | {a['n']} | {a['actual']:.3f} | {a['pred']:.3f} | {r['cal']['pred']:.3f} | "
                  f"{r['sim_all']['pred']:.3f} | {r['direct']['pred']:.3f} | {r['blend']['pred']:.3f} | "
                  f"{a['actual_first']:.3f} | {a['pred_first']:.3f} | {r['blend']['pred_first']:.3f} |")
    u = v["used"]
    md += ["", "### Pool relievers used per team-game (expected vs actual)", "",
           "| | actual | v0.4.0 | 2a. engine refit | 1. calibrated | 2b. tendency | sim 1+2 | direct | blend |",
           "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"]
    for season in ("2025", "2026"):
        md.append(f"| {season} | " + " | ".join(f"{u[k][season]:.2f}" for k in
                                                 ("actual", "v04", "eng", "cal", "tend", "sim_all", "direct", "blend")) + " |")
    md += ["", "(2025 values of the fitted rows are in-sample.)", ""]

    # ---- improvement details
    P = v["params"]
    fmt = lambda d: ", ".join(f"`{k}` {x[0]:+.3f} ± {x[1]:.3f}" for k, x in d.items())  # noqa: E731
    md += [
        "## 2. The four improvements",
        "",
        "### 2.1 Calibration",
        "",
        "Logistic recalibration of the simulated appearance frequency, fitted on 2025 (where the "
        "simulator is partly in-sample: its choice weights were fitted on the same season's calls): "
        "logit P = calib_intercept_<role> + calib_slope × logit P_sim.",
        "",
        f"* calibration alone (v0.4.0 simulator): {fmt(P['cal'])}.",
        f"* with 2a + 2b (simulator after the engine refit, with tendency): {fmt(P['sim_all'])}.",
        f"* First reliever: a temperature on the simulated first-out distribution was fitted as "
        f"weight {P['first_temp']['beta'][0]:.3f} ± {P['first_temp']['se'][0]:.3f} on ln P_sim (1 = no change), "
        "so the simulator's first-reliever distribution is already calibrated in spread; only the blend "
        "with the direct model (2.4) improves it.",
        "",
        "### 2.2 Bullpen size: engine refit and team / league tendency",
        "",
    ]
    eg = o["engine_check"]
    vs = eg["v04_sample"]
    md += [
        f"**Diagnosis.** The v0.4.0 hook settings were tuned on every 2nd train row; rows alternate home / "
        f"away, so that sample was {vs['home_share']:.0%} home teams ({vs['n']} team-games, "
        f"{vs['actual']['all_relievers']:.2f} relievers per game). Home teams use more relievers than away "
        f"teams (they always pitch the 9th; the away team skips the bottom of the 9th when trailing), "
        f"so the target was too high: the 2025 average is {u['actual']['2025']:.2f} pool relievers per "
        f"team-game, 2026 {u['actual']['2026']:.2f}. The 3.43 vs 3.24 gap reported for v0.4.0 was this "
        "tuning bias, not league drift.",
        "",
        f"**Engine refit.** Same grid search, now on a home/away-balanced train sample (both teams of every "
        f"even game_pk, {eg['n']} team-games × {ENGINE_GAMES_PER_CASE} simulated games), target = pool "
        f"relievers per game ({eg['actual']['relievers']:.2f}) and starter outs ({eg['actual']['starter_outs']:.1f}).",
        "",
        "| Settings (changes from v0.4.0) | Relievers | Starter outs | Starter pitches | Outs per reliever | Error |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]
    for g in eg["grid"]:
        diff = {k: x for k, x in g["settings"].items() if V04_HOOKS.get(k) != x}
        sett = ", ".join(f"{k}={x}" for k, x in diff.items()) or "v0.4.0 settings"
        if g["settings"] == eg["chosen"]:
            sett = f"**{sett}** (chosen)"
        md.append(f"| {sett} | {g['relievers']:.2f} | {g['starter_outs']:.1f} | {g['starter_pitches']:.1f} | "
                  f"{g['outs_per_reliever']:.2f} | {g['error']:.4f} |")
    sp = eg["split"]
    md += [
        "",
        f"Home / away check (balanced sample): actual pool relievers home {sp['home']['actual']['relievers']:.2f}, "
        f"away {sp['away']['actual']['relievers']:.2f}; simulated with v0.4.0 hooks {sp['home']['v04']['relievers']:.2f} / "
        f"{sp['away']['v04']['relievers']:.2f}, with the refit {sp['home']['chosen']['relievers']:.2f} / "
        f"{sp['away']['chosen']['relievers']:.2f}. With the config defaults our team scores "
        f"{eg['config']['runs_for']:.2f} and the opponent {eg['config']['runs_against']:.2f} runs per game "
        f"(actual {eg['actual']['runs']:.2f}).",
        "",
    ]
    t = v["tendency"]
    md += [
        f"**Team / league tendency.** Before each game: the team's pool relievers per game over its last N "
        f"team-games on earlier dates, shrunk toward the league mean of the previous {t['league_days']} days "
        f"with k pseudo-games; log ratio = ln(shrunk / {t['baseline']}) ({t['baseline']} = 2025 average). "
        f"It enters the appearance log-odds with weight `tendency_weight`. N and k chosen on train "
        f"log-likelihood (calibration + tendency on the refit simulator): N = {t['team_games']}, k = {t['k']}.",
        "",
        f"* tendency alone on the v0.4.0 simulator: {fmt(P['tend'])};",
        f"* on the refit engine: {fmt(P['eng_tend'])}.",
        "",
        "| N team-games | k | train log-lik | weight |",
        "| :---: | :---: | :---: | :---: |",
    ]
    for g in sorted(t["grid"], key=lambda g: -g["loglik"])[:8]:
        md.append(f"| {g['team_games']} | {g['k']} | {g['loglik']:.1f} | {g['weight']:.2f} |")
    md += ["", "(top 8 of the grid shown; differences are a few log-likelihood units, so the tendency term "
           "is weak.)", ""]
    ro = v["roster"]
    md += [
        "### 2.3 Active roster",
        "",
        "**Finding: the pool is already the game-day active roster.** It is built from the box score's "
        "roster (the 26-man roster at game time), so arms on the IL, optioned or DFA'd before the game "
        f"are never in it: {ro['2025']['inactive_in_pool']} / {ro['2026']['inactive_in_pool']} inactive pool "
        "reliever-games in 2025 / 2026, i.e. no prediction mass sits on inactive arms and a roster filter "
        "cannot change the backtest. To check, the MLB Stats API active roster was fetched for every team on "
        "every game date and the day before (11k cached requests).",
        "",
        "| | 2025 | 2026 |",
        "| :--- | :---: | :---: |",
        f"| pool reliever-games | {ro['2025']['reliever_games']} | {ro['2026']['reliever_games']} |",
        f"| missing from the API roster *for the game date* | {ro['2025']['off_eod']} | {ro['2026']['off_eod']} |",
        f"| ... of whom pitched in the game | {ro['2025']['off_eod_appeared']} | {ro['2026']['off_eod_appeared']} |",
        f"| pitchers on yesterday's roster missing from today's game roster, per team-game | "
        f"{_f(ro['2025']['departed_per_game'], 3)} | {_f(ro['2026']['departed_per_game'], 3)} |",
        f"| team-games with such a departure | {ro['2025']['games_with_departure']:.1%} | {ro['2026']['games_with_departure']:.1%} |",
        f"| new arrivals (not on yesterday's roster) | {ro['2025']['new_arrivals']} | {ro['2026']['new_arrivals']} |",
        f"| appearance rate: new arrivals / everyone else | {_f(ro['2025']['new_appear_rate'], 3)} / "
        f"{_f(ro['2025']['others_appear_rate'], 3)} | {_f(ro['2026']['new_appear_rate'], 3)} / "
        f"{_f(ro['2026']['others_appear_rate'], 3)} |",
        f"| v0.4.0 mean P_sim: new arrivals / everyone else | {_f(ro['2025']['new_sim_mean'], 3)} / "
        f"{_f(ro['2025']['others_sim_mean'], 3)} | {_f(ro['2026']['new_sim_mean'], 3)} / "
        f"{_f(ro['2026']['others_sim_mean'], 3)} |",
        f"| diagnostic: placed on the IL 1-3 days later (post-game info) | {ro['2025']['later_il']} | {ro['2026']['later_il']} |",
        f"| ... their appearance rate / v0.4.0 mean P_sim | {_f(ro['2025']['later_il_appear_rate'], 3)} / "
        f"{_f(ro['2025']['later_il_sim_mean'], 3)} | {_f(ro['2026']['later_il_appear_rate'], 3)} / "
        f"{_f(ro['2026']['later_il_sim_mean'], 3)} |",
        "",
        "* The API roster for a date is an **end-of-day** state: nearly every pool arm it misses pitched that "
        "day and was optioned / put on the IL afterwards. Filtering on it would leak post-game moves (and "
        "remove arms who pitched), so it is not an input.",
        "* Same-day moves matter for live use: on about a fifth of team-games a pitcher left the roster since "
        "yesterday. Build the pool from the day's announced roster (or mark departed arms `active = false`); "
        "a pool built from yesterday's roster would carry those arms.",
        "* What the roster data adds as a pre-game signal is `new_arrival` (joined today), a feature of both "
        "direct models; its value is the difference between the two direct-model rows in section 1.",
        "* Arms placed on the IL in the next days (unknowable before the game) are a small source of error.",
        "",
    ]
    fd = o["fitted"]
    from ballmonitor.models.mlb_bullpen.calibration import DIRECT_FEATURES, FIRST_FEATURES

    md += [
        "### 2.4 Direct model and blend",
        "",
        "**Direct model**: one logistic regression per reliever-game, P(appear) = logistic(Σ direct_<f> × f), "
        f"fitted on 2025 (ridge {DIRECT_RIDGE}). **First-reliever direct model**: a conditional logit over the "
        "pool on the first-reliever features. **Blend**: the appearance log-odds = calibration of the "
        "(refit) simulator + tendency + `blend_weight_direct` × logit P_direct, all "
        "weights fitted on 2025 with *out-of-fold* direct predictions (2 folds by month parity) so the "
        "direct model's in-sample fit does not inflate its weight; the first-reliever blend is a softmax of "
        "`first_weight_sim` × ln P_sim(first) + `first_weight_direct` × direct score (also out-of-fold).",
        "",
        "| Direct appearance feature | weight ± s.e. | | First-reliever feature | weight ± s.e. |",
        "| :--- | :---: | :--- | :--- | :---: |",
    ]
    for i in range(max(len(DIRECT_FEATURES), len(FIRST_FEATURES))):
        a = DIRECT_FEATURES[i] if i < len(DIRECT_FEATURES) else None
        b = FIRST_FEATURES[i] if i < len(FIRST_FEATURES) else None
        ca = f"`{a}` | {fd['direct_' + a]['value']:+.3f} ± {fd['direct_' + a]['se']:.3f}" if a else " | "
        cb = f"`{b}` | {fd['first_direct_' + b]['value']:+.3f} ± {fd['first_direct_' + b]['se']:.3f}" if b else " | "
        md.append(f"| {ca} | | {cb} |")
    md += [
        "",
        "Blend weights (2025): " + ", ".join(
            f"`{k}` {fd[k]['value']:+.3f} ± {fd[k]['se']:.3f}" for k in
            ("calib_intercept_closer", "calib_intercept_setup", "calib_intercept_middle", "calib_intercept_long",
             "calib_slope", "tendency_weight", "blend_weight_direct", "first_weight_sim", "first_weight_direct")) + ".",
        "",
        "The simulator adds value to the direct model if the blend beats the direct model out of sample "
        "and its weight is clearly non-zero (see section 1 tables).",
        "",
    ]

    # ---- v0.4 sections kept: choice model, workload table
    md += [
        "## 3. Choice model: conditional logit on real bullpen calls (train)",
        "",
        f"{lg['calls']} train bullpen calls (ridge {lg['ridge']}). Log-likelihood {lg['loglik']:.1f} vs "
        f"{lg['null_loglik']:.1f} for a uniform pick among available arms (McFadden pseudo-R² "
        f"{lg['pseudo_r2']:.3f}). Calls not fitted: "
        + ", ".join(f"{k} {x}" for k, x in lg["counts"].items() if k.startswith("chosen")) + ". "
        "Calls by situation: "
        + ", ".join(f"{k.split()[1]} {x}" for k, x in lg["counts"].items() if k.startswith("situation")) + ".",
        "",
        "Coefficients are in score units at temperature 1 (fatigue terms shown as positive penalties). "
        "The config defaults are these values (rounded); unchanged since v0.4.0.",
        "",
        "| Parameter | Fitted | s.e. | Config default |",
        "| :--- | :---: | :---: | :---: |",
    ]
    for k in list(lg["fitted"]) + ["usage_prior_games", "off_day_tomorrow_discount", "usage_prior_rate",
                                    "closer_min_saves", "setup_count", "setup_min_holds", "long_min_outs_per_app"]:
        x = o["fitted"][k]
        cfg = o["config_vs_fit"][k]["config"]
        md.append(f"| `{k}` | {x['value']} | {x['se'] if x['se'] is not None else 'grid'} | {cfg:g} |")
    md += ["", "Role-inference rules (grid, train log-likelihood of the logit at usage_prior_games 10):", "",
           "| closer_min_saves | setup_count | setup_min_holds | long_min_outs_per_app | log-lik |",
           "| :---: | :---: | :---: | :---: | :---: |"]
    md += [f"| {g['closer_min_saves']} | {g['setup_count']} | {g['setup_min_holds']} | "
           f"{g['long_min_outs_per_app']} | {g['loglik']:.1f} |"
           for g in sorted(o["role_grid"], key=lambda g: -g["loglik"])[:8]]
    md += ["", "(top 8 of the grid shown)", ""]
    md += ["Grid (shrinkage pseudo-games × off-day fatigue discount), train log-likelihood:", "",
           "| usage_prior_games | off_day_tomorrow_discount | log-lik |", "| :---: | :---: | :---: |"]
    md += [f"| {g['usage_prior_games']} | {g['off_day_tomorrow_discount']} | {g['loglik']:.1f} |" for g in lg["grid"]]
    bf = o["benchmarks_fit"]
    md += [
        "",
        "Benchmarks (fitted on train): **uniform** = every pool reliever gets the train-average share of "
        f"pool arms used ({bf['uniform_used_per_pool']:.3f}), first reliever 1/pool. **Usage-frequency** = "
        f"the reliever's shrunk appearance rate over his last 30 roster-games ((apps + {bf['k']:g} × "
        f"{bf['r0']:.3f}) / (games + {bf['k']:g})) × a rest-days factor; first reliever ∝ shrunk "
        "first-out-of-pen rate × rest factor. Rest factors: "
        + ", ".join(f"{b} {x:.2f}" for b, x in bf["rest_factor"].items()) + ".",
        "",
        "## 4. Relief appearance rate by recent workload (train)", "",
        "| Bucket | Reliever-games | Appearance rate |", "| :--- | :---: | :---: |",
    ]
    md += [f"| {k} | {x['n']} | {x['rate']:.3f} |" for k, x in o["workload_table"].items()]
    md += [
        "",
        "The hard rest rules (`max_pitches_yesterday`, `max_pitches_3d`, 3 straight days) remove arms "
        "whose train appearance rate is near zero; softer effects are the fitted fatigue penalties.",
        "",
    ]
    return "\n".join(md)


if __name__ == "__main__":
    run_study()
    print("Wrote RESEARCH.md and data/research.json")
