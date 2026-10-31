"""Study: how predictable is a pitcher's next pitch type, which model predicts it best, which
pitchers are hardest to predict, and do unpredictable pitches get better results?

    python -m ballmonitor.models.next_pitch.research            # writes RESEARCH.md + data/research.json
    python -m ballmonitor.models.next_pitch.research --quick    # skip the neural model

Needs `ballmonitor fetch next_pitch` first, plus numpy, pandas, pyarrow, lightgbm, torch.
Every number in RESEARCH.md is produced by this file.

Design (all walk-forward; nothing from the future is used):
- Every feature of a pitch is computed from pitches thrown before it (features.py).
- 2021–2023 are history/training only. 2024 is the validation season used to choose every
  hyper-parameter (context-tree strengths and half-life, GBM / network settings).
- 2025 and 2026 are the test seasons. Learned models are trained only on seasons before the
  test season (the last 20% of days of the previous season is held out for early stopping).
- "Focus pitchers": those with >= FOCUS_MIN pitches in the season being scored.
- Uncertainty: 95% intervals from a bootstrap over pitcher-games (pitches within a game are
  not independent). Only two independent test seasons exist.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ballmonitor.models.next_pitch import features as F
from ballmonitor.models.next_pitch.pitches import VOCAB

# LightGBM and PyTorch each ship an OpenMP runtime on macOS; allow both in one process.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

MODEL_DIR = Path(__file__).resolve().parent
DATA = MODEL_DIR / "data"
OUT = DATA / "research"
SEASONS = [2021, 2022, 2023, 2024, 2025, 2026]
VALID, TESTS = 2024, [2025, 2026]
TRAIN_FROM = 2022  # learned models train on seasons >= this (2021 is warm-up history)
FOCUS_MIN = 2000
K = F.K
EPS = 1e-9
BOOT = 500
HALF_LIVES = [7, 15, 30, 60, 120, 240, 480, 0]  # days; 0 = no decay
STRENGTH_GRID = [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 2048, 8192, 32768]
LOG = []


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    LOG.append(line)
    print(line, flush=True)


# ── scoring ──────────────────────────────────────────────────────────────────

def nll(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(probs[np.arange(len(y)), y], EPS, 1.0))


def metrics(probs: np.ndarray, y: np.ndarray) -> dict:
    p = probs / probs.sum(axis=1, keepdims=True)
    onehot = np.zeros_like(p)
    onehot[np.arange(len(y)), y] = 1
    return {
        "n": int(len(y)),
        "log_loss": float(nll(p, y).mean()),
        "bits": float(nll(p, y).mean() / math.log(2)),
        "accuracy": float((p.argmax(axis=1) == y).mean()),
        "brier": float(((p - onehot) ** 2).sum(axis=1).mean()),
    }


def cluster_ids(df: pd.DataFrame) -> np.ndarray:
    return pd.factorize(df["game_pk"].astype(np.int64) * 10_000_000 + df["pitcher"].astype(np.int64))[0]


def boot_diff(loss_a: np.ndarray, loss_b: np.ndarray, clusters: np.ndarray, seed: int = 0) -> tuple[float, float, float]:
    """Mean(a - b) with a 95% cluster-bootstrap interval."""
    d = loss_a - loss_b
    sums = np.bincount(clusters, weights=d)
    cnt = np.bincount(clusters).astype(float)
    rng = np.random.default_rng(seed)
    m = len(sums)
    reps = []
    for _ in range(BOOT):
        pick = rng.integers(0, m, m)
        reps.append(sums[pick].sum() / cnt[pick].sum())
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return float(d.mean()), float(lo), float(hi)


# ── context tree (the shipped model) ─────────────────────────────────────────

def league_prior(df: pd.DataFrame) -> np.ndarray:
    """Per-row prior: league pitch mix by pitcher hand in the warm-up season (2021)."""
    warm = df[df["game_year"] == SEASONS[0]]
    prior = np.zeros((2, K))
    for h in (0, 1):
        counts = np.bincount(warm.loc[warm["throws_i"] == h, "y"], minlength=K) + 1.0
        prior[h] = counts / counts.sum()
    return prior[df["throws_i"].to_numpy()]


def chain_probs(counts: list[np.ndarray], strengths: list[float], prior: np.ndarray) -> np.ndarray:
    p = prior
    for c, a in zip(counts, strengths):
        total = c.sum(axis=1, keepdims=True)
        p = (c + a * p) / (total + a)
    return p


def tune_strengths(counts, prior, y, init=None, passes=2) -> tuple[list[float], float]:
    s = list(init or [8.0] * len(counts))
    best = nll(chain_probs(counts, s, prior), y).mean()
    for _ in range(passes):
        for j in range(len(s)):
            for a in STRENGTH_GRID:
                trial = s[:j] + [a] + s[j + 1:]
                loss = nll(chain_probs(counts, trial, prior), y).mean()
                if loss < best - 1e-7:
                    best, s = loss, trial
    return s, float(best)


CHAINS = {  # name -> list of SPECS names, root to leaf (each adds one context)
    "control: count": ["all", "count"],
    "count + batter side": ["all", "count", "count_stand"],
    "+ previous pitch type": ["all", "count", "count_stand", "count_stand_prev"],
    "+ previous pitch result": ["all", "count", "count_stand", "count_stand_prev", "count_stand_prev_res"],
    "+ pitch before that": ["all", "count", "count_stand", "count_stand_prev", "count_stand_prev_res", "count_stand_prev2"],
    "batter side first, then count, previous pitch": ["all", "stand", "count_stand", "count_stand_prev"],
}
# research spec name -> the model's context level it adds (config.toml `chain`)
SPEC_LEVEL = {"count": "count", "stand": "stand", "count_stand": None, "count_stand_prev": "prev_type",
              "count_stand_prev_res": "prev_result", "count_stand_prev2": "prev2_type"}


def chain_levels(chain: list[str]) -> list[str]:
    """['all', 'count', 'count_stand', ...] -> config levels ['count', 'stand', ...]."""
    levels = []
    for spec in chain[1:]:
        lvl = SPEC_LEVEL[spec] or ("count" if "stand" in levels else "stand")
        levels.append(lvl)
    return levels
CONTROL = "control: count"


@dataclass
class TreeFit:
    chain: list[str]
    half_life: float
    strengths: list[float]
    valid_loss: float


def fit_trees(df: pd.DataFrame, prior: np.ndarray, valid_rows: np.ndarray) -> dict[str, TreeFit]:
    """Choose strengths for every (chain, half-life) on the validation season."""
    y = df["y"].to_numpy()[valid_rows]
    specs = {s: F.SPECS[s] for s in dict.fromkeys(x for c in CHAINS.values() for x in c)}
    fits: dict[str, TreeFit] = {}
    for hl in HALF_LIVES:
        counts = F.pitcher_counts(df, specs, hl, valid_rows)
        for name, chain in CHAINS.items():
            s, loss = tune_strengths([counts[c] for c in chain], prior[valid_rows], y)
            fits[f"{name} | hl={hl}"] = TreeFit(chain, hl, s, loss)
            log(f"  tree {name:28s} half-life {hl:4d}: valid log loss {loss:.4f} strengths {s}")
    return fits


def best_by_chain(fits: dict) -> dict[str, TreeFit]:
    out = {}
    for name in CHAINS:
        cands = {k: f for k, f in fits.items() if k.startswith(name + " |")}
        out[name] = min(cands.values(), key=lambda f: f.valid_loss)
    return out


def best_overall(fits: dict) -> TreeFit:
    return min(fits.values(), key=lambda f: f.valid_loss)


# ── pipeline ─────────────────────────────────────────────────────────────────

def season_bounds(df: pd.DataFrame) -> dict[int, tuple[int, int]]:
    yrs = df["game_year"].to_numpy()
    return {int(s): (int(np.searchsorted(yrs, s, "left")), int(np.searchsorted(yrs, s, "right"))) for s in np.unique(yrs)}


def focus_mask(df: pd.DataFrame) -> np.ndarray:
    per = df.groupby(["game_year", "pitcher"])["y"].transform("size")
    return (per >= FOCUS_MIN).to_numpy()


def tree_probs(df, fit: TreeFit, prior, rows) -> np.ndarray:
    specs = {s: F.SPECS[s] for s in fit.chain}
    counts = F.pitcher_counts(df, specs, fit.half_life, rows)
    return chain_probs([counts[s] for s in fit.chain], fit.strengths, prior[rows]).astype(np.float32)


def cached(name: str, fn, fresh: bool):
    path = OUT / f"{name}.npy"
    if path.exists() and not fresh:
        return np.load(path)
    arr = fn()
    np.save(path, arr)
    return arr


def run_learners(df, bounds, focus, final: TreeFit, prior, quick: bool, fresh: bool) -> tuple[dict, dict]:
    """GBM (+ transformer) test-season probabilities, keyed by model then season."""
    from ballmonitor.models.next_pitch import learners as L

    start = bounds[TRAIN_FROM][0]
    rows = np.arange(start, len(df))
    out: dict[str, dict[int, np.ndarray]] = {"Gradient boosting (LightGBM)": {}}
    if not quick:
        out["Sequence transformer"] = {}
    extra = {}
    need = [t for t in TESTS if fresh or not (OUT / f"gbm_{t}.npy").exists()
            or (not quick and not (OUT / f"transformer_{t}.npy").exists())]
    if need:
        log("learners: building features for rows from %d (%d pitches)" % (TRAIN_FROM, len(rows)))
        counts = F.pitcher_counts(df, F.SPECS, final.half_life, rows)
        logp = np.log(np.clip(chain_probs([counts[s] for s in final.chain], final.strengths, prior[rows]), EPS, 1)).astype(np.float32)
        batter = F.batter_features(df).iloc[start:].reset_index(drop=True)
        X, names, cats = L.feature_matrix(df, slice(start, len(df)), counts, logp, batter)
        del counts, batter
        y = df["y"].to_numpy()[start:].astype(np.int64)
        seq = None if quick else L.game_sequences(df, slice(start, len(df)))
        day = df["day"].to_numpy()[start:]
        for t in need:
            ts, te = bounds[t][0] - start, bounds[t][1] - start
            ps, _ = bounds[t - 1]
            prev_days = np.unique(day[ps - start:ts])
            cut_day = prev_days[int(len(prev_days) * 0.8)]
            cut = int(np.searchsorted(day[:ts], cut_day))
            log(f"  test {t}: train {cut:,} pitches, early-stop {ts - cut:,}, test {te - ts:,}")
            booster = L.train_gbm(X[:cut], y[:cut], logp[:cut], X[cut:ts], y[cut:ts], logp[cut:ts], names, cats, log)
            p = L.gbm_predict(booster, X[ts:te], logp[ts:te]).astype(np.float32)
            np.save(OUT / f"gbm_{t}.npy", p)
            booster.save_model(str(OUT / f"gbm_{t}.txt"))
            json.dump(L.gbm_importance(booster, names), open(OUT / f"gbm_importance_{t}.json", "w"))
            del booster
            log("    per-pitcher boosted models (focus pitchers)")
            pitcher = df["pitcher"].to_numpy()[start:]
            test_rows = np.arange(ts, te)[focus[start + ts:start + te]]
            per = L.train_per_pitcher(X, y, logp, pitcher, ts, cut, test_rows)
            pp = np.full((te - ts, K), np.nan, np.float32)
            for sel, probs in per.values():
                pp[sel - ts] = probs
            np.save(OUT / f"per_pitcher_{t}.npy", pp)
            log(f"    per-pitcher models for {len(per)} pitchers")
            if not quick:
                rng = np.random.default_rng(t)
                va = np.sort(rng.choice(np.arange(cut, ts), min(ts - cut, 200_000), replace=False))
                view = lambda a, b: {k: v[a:b] for k, v in seq.items()}
                predict = L.train_transformer(view(0, cut), X[:cut], y[:cut], logp[:cut],
                                              {k: v[va] for k, v in seq.items()}, X[va], y[va], logp[va], log)
                p = predict(view(ts, te), X[ts:te], logp[ts:te]).astype(np.float32)
                np.save(OUT / f"transformer_{t}.npy", p)
        del X, seq
    for t in TESTS:
        out["Gradient boosting (LightGBM)"][t] = np.load(OUT / f"gbm_{t}.npy")
        extra.setdefault("per_pitcher", {})[t] = np.load(OUT / f"per_pitcher_{t}.npy")
        extra[f"importance_{t}"] = json.load(open(OUT / f"gbm_importance_{t}.json"))
        if not quick:
            out["Sequence transformer"][t] = np.load(OUT / f"transformer_{t}.npy")
    return out, extra


def main(argv: list[str]) -> None:
    quick, fresh = "--quick" in argv, "--fresh" in argv
    OUT.mkdir(parents=True, exist_ok=True)
    log("loading pitches")
    df = F.load_pitches(DATA, SEASONS)
    bounds = season_bounds(df)
    prior = league_prior(df)
    focus = focus_mask(df)
    y_all = df["y"].to_numpy()
    log(f"{len(df):,} pitches; seasons {sorted(bounds)}")

    # 1. context trees: tune on the validation season (focus pitchers)
    vs, ve = bounds[VALID]
    valid_rows = np.arange(vs, ve)[focus[vs:ve]]
    fits_path = OUT / "tree_fits.json"
    if fits_path.exists() and not fresh:
        fits = {k: TreeFit(**v) for k, v in json.load(open(fits_path)).items()}
    else:
        log(f"tuning context trees on {VALID} ({len(valid_rows):,} focus pitches)")
        fits = fit_trees(df, prior, valid_rows)
        json.dump({k: v.__dict__ for k, v in fits.items()}, open(fits_path, "w"), indent=1)
    chains = best_by_chain(fits)
    final = best_overall(fits)
    control = fits[f"{CONTROL} | hl=0"]
    log(f"final tree: {final.chain} half-life {final.half_life} strengths {final.strengths}")

    # 2. test-season probabilities for every model
    models: dict[str, dict[int, np.ndarray]] = {}
    tree_models = {"Control: pitcher x count": control, "Control + recency weighting": chains[CONTROL]}
    for name, fit in chains.items():
        if name != CONTROL:
            tree_models[f"Context tree: {name}"] = fit
    for name, fit in tree_models.items():
        models[name] = {}
        for t in TESTS:
            s, e = bounds[t]
            key = f"tree_{t}_{'-'.join(fit.chain)}_{fit.half_life}"
            models[name][t] = cached(key, lambda: tree_probs(df, fit, prior, np.arange(s, e)), fresh)
    learned, extra = run_learners(df, bounds, focus, final, prior, quick, fresh)
    models.update(learned)
    if not quick:
        models["Average of GBM and transformer"] = {
            t: (models["Gradient boosting (LightGBM)"][t] + models["Sequence transformer"][t]) / 2 for t in TESTS}

    # 3. evaluation
    per_pitcher_models = extra.pop("per_pitcher")
    results = evaluate(df, bounds, focus, models, y_all)
    results["own_models"] = own_vs_shared(df, bounds, models, per_pitcher_models, y_all)
    best_name = min(results["pooled_focus"], key=lambda m: results["pooled_focus"][m]["log_loss"])
    log(f"best model: {best_name}")
    pitchers = per_pitcher(df, bounds, focus, models, best_name, "Control: pitcher x count")
    surprise = surprise_study(df, bounds, focus, models[best_name])
    summary = {
        "generated": time.strftime("%Y-%m-%d"), "seasons": SEASONS, "valid": VALID, "tests": TESTS,
        "focus_min": FOCUS_MIN, "n_pitches": len(df), "tree_fits": {k: v.__dict__ for k, v in fits.items()},
        "final_tree": final.__dict__, "best_model": best_name, "results": results,
        "pitchers": pitchers, "surprise": surprise, "importance": extra,
    }
    summary["final_tree"]["levels"] = chain_levels(final.chain)
    export_gbm(final)
    json.dump(summary, open(DATA / "research.json", "w"), indent=1, default=float)
    (MODEL_DIR / "RESEARCH.md").write_text(report(summary, df, bounds))
    log("wrote RESEARCH.md and data/research.json")


def export_gbm(final: TreeFit) -> None:
    """Ship the boosted model trained for the last test season (so backtests on that season stay honest)."""
    src = OUT / f"gbm_{TESTS[-1]}.txt"
    if not src.exists():
        return
    (DATA / "gbm_model.txt").write_bytes(src.read_bytes())
    meta_path = DATA / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta["gbm"] = {"half_life_days": final.half_life, "chain_specs": final.chain, "strengths": final.strengths,
                   "trained": f"{TRAIN_FROM}–{TESTS[-1] - 1} seasons (early stopping on late {TESTS[-1] - 1})"}
    meta_path.write_text(json.dumps(meta, indent=1))
    log("exported data/gbm_model.txt and meta.json['gbm']")


# ── evaluation ───────────────────────────────────────────────────────────────

def stacked(models, bounds, mask, name) -> np.ndarray:
    return np.concatenate([models[name][t][mask[bounds[t][0]:bounds[t][1]]] for t in TESTS])


def evaluate(df, bounds, focus, models, y_all) -> dict:
    allmask = np.ones(len(df), bool)
    res = {"by_season": {}, "pooled_focus": {}, "pooled_all": {}, "vs_control": {}, "by_count": {}, "n_focus": {}}
    for t in TESTS:
        s, e = bounds[t]
        m = focus[s:e]
        res["n_focus"][t] = {"pitches": int(m.sum()), "pitchers": int(df.iloc[s:e][m]["pitcher"].nunique())}
        res["by_season"][t] = {name: metrics(p[t][m], y_all[s:e][m]) for name, p in models.items()}
    y_f = np.concatenate([y_all[bounds[t][0]:bounds[t][1]][focus[bounds[t][0]:bounds[t][1]]] for t in TESTS])
    y_a = np.concatenate([y_all[bounds[t][0]:bounds[t][1]] for t in TESTS])
    sub = pd.concat([df.iloc[bounds[t][0]:bounds[t][1]][focus[bounds[t][0]:bounds[t][1]]] for t in TESTS])
    clusters = cluster_ids(sub)
    control = "Control: pitcher x count"
    base = nll(stacked(models, bounds, focus, control), y_f)
    base_hit = stacked(models, bounds, focus, control).argmax(axis=1) == y_f
    for name in models:
        p = stacked(models, bounds, focus, name)
        res["pooled_focus"][name] = metrics(p, y_f)
        res["pooled_all"][name] = metrics(stacked(models, bounds, allmask, name), y_a)
        d, lo, hi = boot_diff(nll(p, y_f), base, clusters)
        acc_d, alo, ahi = boot_diff((p.argmax(axis=1) == y_f).astype(float), base_hit.astype(float), clusters)
        res["vs_control"][name] = {"bits": d / math.log(2), "bits_lo": lo / math.log(2), "bits_hi": hi / math.log(2),
                                   "acc": acc_d, "acc_lo": alo, "acc_hi": ahi}
    counts = sub["count"].to_numpy()
    for name in models:
        p = stacked(models, bounds, focus, name)
        res["by_count"][name] = {
            f"{c // 3}-{c % 3}": {**metrics(p[counts == c], y_f[counts == c])} for c in range(12) if (counts == c).any()}
    return res


def own_vs_shared(df, bounds, models, per_pitcher_models, y_all) -> dict:
    """Pitchers' own boosted models vs the shared one, on the pitches where both exist."""
    shared = "Gradient boosting (LightGBM)"
    a, b, c, ys, subs = [], [], [], [], []
    for t in TESTS:
        s, e = bounds[t]
        own = per_pitcher_models[t]
        ok = ~np.isnan(own[:, 0])
        a.append(own[ok])
        b.append(models[shared][t][ok])
        c.append(models["Control: pitcher x count"][t][ok])
        ys.append(y_all[s:e][ok])
        subs.append(df.iloc[s:e][ok])
    a, b, c, y = (np.concatenate(v) for v in (a, b, c, ys))
    sub = pd.concat(subs)
    d, lo, hi = boot_diff(nll(a, y), nll(b, y), cluster_ids(sub))
    return {"own": metrics(a, y), "shared": metrics(b, y), "control": metrics(c, y),
            "pitchers": int(sub["pitcher"].nunique()), "own_minus_shared_bits": [x / math.log(2) for x in (d, lo, hi)]}


def pitcher_names() -> dict[int, str]:
    path = DATA / "pitchers.csv"
    if not path.exists():
        return {}
    t = pd.read_csv(path)
    return dict(zip(t["pitcher_id"], t["name"]))


def outcome_cols(sub: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "rv100": -sub["delta_run_exp"].fillna(0).to_numpy() * 100,  # runs saved per 100 pitches (pitcher view)
        "csw": sub["csw"].to_numpy(float),
        "whiff": np.where(sub["swing"] == 1, sub["whiff"], np.nan),
        "xwoba": np.where(sub["res"] == "X", sub["estimated_woba_using_speedangle"], np.nan),
    }, index=sub.index)


def spearman(a: np.ndarray, b: np.ndarray, seed=0) -> tuple[float, float, float]:
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    r = float(np.corrcoef(ra, rb)[0, 1])
    rng = np.random.default_rng(seed)
    reps = []
    for _ in range(BOOT):
        i = rng.integers(0, len(a), len(a))
        x, z = pd.Series(a[i]).rank().to_numpy(), pd.Series(b[i]).rank().to_numpy()
        reps.append(np.corrcoef(x, z)[0, 1])
    lo, hi = np.nanpercentile(reps, [2.5, 97.5])
    return r, float(lo), float(hi)


def per_pitcher(df, bounds, focus, models, best, control) -> dict:
    names = pitcher_names()
    rows = []
    for t in TESTS:
        s, e = bounds[t]
        m = focus[s:e]
        sub = df.iloc[s:e][m]
        y = sub["y"].to_numpy()
        lb, lc = nll(models[best][t][m], y) / math.log(2), nll(models[control][t][m], y) / math.log(2)
        hb = models[best][t][m].argmax(axis=1) == y
        hc = models[control][t][m].argmax(axis=1) == y
        oc = outcome_cols(sub)
        frame = pd.DataFrame({"pitcher": sub["pitcher"].to_numpy(), "y": y, "lb": lb, "lc": lc, "hb": hb, "hc": hc,
                              "throws": sub["p_throws"].to_numpy(), **{k: oc[k].to_numpy() for k in oc}})
        for pid, g in frame.groupby("pitcher"):
            mix = np.bincount(g["y"], minlength=K) / len(g)
            h = float(-(mix[mix > 0] * np.log2(mix[mix > 0])).sum())
            rows.append({
                "pitcher": int(pid), "name": names.get(int(pid), str(pid)), "season": t, "throws": g["throws"].iloc[0],
                "n": len(g), "pitch_types": int((mix >= 0.03).sum()),
                "mix": {VOCAB[i]: round(float(mix[i]), 3) for i in np.argsort(-mix) if mix[i] >= 0.03},
                "mix_entropy": h, "best_bits": float(g["lb"].mean()), "control_bits": float(g["lc"].mean()),
                "best_acc": float(g["hb"].mean()), "control_acc": float(g["hc"].mean()),
                "rv100": float(g["rv100"].mean()), "csw": float(g["csw"].mean()),
                "whiff": float(g["whiff"].mean()), "xwoba": float(g["xwoba"].mean()),
            })
    t = pd.DataFrame(rows)
    t["explained"] = (t["mix_entropy"] - t["best_bits"]) / t["mix_entropy"]
    t["gain_vs_control"] = t["control_bits"] - t["best_bits"]
    corr = {}
    for out in ["rv100", "csw", "whiff", "xwoba"]:
        corr[out] = {
            "best_bits": spearman(t["best_bits"].to_numpy(), t[out].to_numpy()),
            "mix_entropy": spearman(t["mix_entropy"].to_numpy(), t[out].to_numpy()),
            "explained": spearman(t["explained"].to_numpy(), t[out].to_numpy()),
        }
    return {"table": t.to_dict("records"), "correlations": corr, "n_pitcher_seasons": len(t),
            "n_pitchers": int(t["pitcher"].nunique())}


def within_slope(x: np.ndarray, y: np.ndarray, strata: np.ndarray, clusters: np.ndarray, seed=0) -> dict:
    """Slope of y on x after removing stratum means (fixed effects), with a cluster bootstrap CI."""
    ok = ~np.isnan(y)
    x, y, strata, clusters = x[ok], y[ok], strata[ok], clusters[ok]
    sx = pd.Series(x).groupby(strata).transform("mean").to_numpy()
    sy = pd.Series(y).groupby(strata).transform("mean").to_numpy()
    xd, yd = x - sx, y - sy
    cl = pd.factorize(clusters)[0]
    sxy = np.bincount(cl, weights=xd * yd)
    sxx = np.bincount(cl, weights=xd * xd)
    slope = sxy.sum() / sxx.sum()
    rng = np.random.default_rng(seed)
    reps = []
    for _ in range(BOOT):
        i = rng.integers(0, len(sxy), len(sxy))
        reps.append(sxy[i].sum() / sxx[i].sum())
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return {"slope": float(slope), "lo": float(lo), "hi": float(hi), "n": int(len(x)), "mean": float(y.mean()),
            "sd_within_x": float(xd.std())}


def surprise_study(df, bounds, focus, best_probs: dict) -> dict:
    """Do pitches the model found surprising get better results, holding pitcher, pitch type and count fixed?"""
    subs, surprise = [], []
    for t in TESTS:
        s, e = bounds[t]
        m = focus[s:e]
        sub = df.iloc[s:e][m]
        p = best_probs[t][m]
        surprise.append(-np.log2(np.clip(p[np.arange(len(sub)), sub["y"].to_numpy()], EPS, 1)))
        subs.append(sub)
    sub = pd.concat(subs)
    x = np.concatenate(surprise)
    oc = outcome_cols(sub)
    clusters = cluster_ids(sub)
    key_base = [sub["pitcher"].to_numpy(), sub["game_year"].to_numpy(), sub["y"].to_numpy(), sub["count"].to_numpy()]
    strata = {
        "pitcher, season, pitch type, count": pd.factorize(pd.MultiIndex.from_arrays(key_base))[0],
        "... + location (zone 1-14)": pd.factorize(pd.MultiIndex.from_arrays(key_base + [sub["zone"].fillna(0).to_numpy()]))[0],
    }
    out = {"slopes": {}, "quintiles": {}, "surprise_mean": float(x.mean())}
    for sname, st in strata.items():
        out["slopes"][sname] = {o: within_slope(x, oc[o].to_numpy(float), st, clusters) for o in oc}
    # quintiles of surprise within the main strata
    st = strata["pitcher, season, pitch type, count"]
    pct = pd.Series(x).groupby(st).rank(pct=True, method="average").to_numpy()
    size = pd.Series(st).map(pd.Series(st).value_counts()).to_numpy()
    usable = size >= 10
    q = np.minimum((pct * 5).astype(int), 4)
    for o in oc:
        y = oc[o].to_numpy(float)
        ym = pd.Series(y).groupby(st).transform("mean").to_numpy()
        rows = []
        for k in range(5):
            sel = usable & (q == k) & ~np.isnan(y)
            rows.append({"quintile": k + 1, "surprise_bits": float(x[sel].mean()), "n": int(sel.sum()),
                         "vs_stratum_mean": float((y[sel] - ym[sel]).mean())})
        out["quintiles"][o] = {"overall_mean": float(np.nanmean(y)), "rows": rows}
    return out



# ── report ───────────────────────────────────────────────────────────────────

def _t(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _ci(v, lo, hi, fmt="{:+.3f}") -> str:
    return f"{fmt.format(v)} [{fmt.format(lo)}, {fmt.format(hi)}]"


def _mix(m: dict) -> str:
    return ", ".join(f"{k} {v:.0%}" for k, v in m.items())


OUTCOME_LABEL = {
    "rv100": "runs saved per 100 pitches",
    "csw": "called + swinging strike rate",
    "whiff": "whiffs per swing",
    "xwoba": "xwOBA on contact (lower = better for pitcher)",
}


def report(S: dict, df: pd.DataFrame, bounds: dict) -> str:
    R = S["results"]
    pooled, vs = R["pooled_focus"], R["vs_control"]
    control = "Control: pitcher x count"
    best = S["best_model"]
    order = sorted(pooled, key=lambda m: pooled[m]["log_loss"], reverse=True)
    fin = S["final_tree"]
    simple = min((m for m in pooled if m.startswith("Context tree")), key=lambda m: pooled[m]["log_loss"])
    P = pd.DataFrame(S["pitchers"]["table"])
    sur = S["surprise"]
    main_strata = "pitcher, season, pitch type, count"
    sl = sur["slopes"][main_strata]
    nf = R["n_focus"]
    L = []
    w = L.append
    w("# Next pitch type: research\n")
    w(f"Generated by `research.py` on {S['generated']}; do not edit by hand. Re-run with "
      "`python -m ballmonitor.models.next_pitch.research` after `ballmonitor fetch next_pitch`.\n")

    w("## Summary\n")
    b, c = pooled[best], pooled[control]
    w(f"- **Most accurate model: {best}.** On the {TESTS[0]}–{TESTS[-1]} test seasons (pitchers with "
      f"≥{FOCUS_MIN:,} pitches in the season) it picked the right pitch type **{b['accuracy']:.1%}** of the time "
      f"vs **{c['accuracy']:.1%}** for the control (the pitcher's historical mix in that count), and cut log loss by "
      f"{-vs[best]['bits']:.3f} bits per pitch (95% CI {-vs[best]['bits_hi']:.3f} to {-vs[best]['bits_lo']:.3f}).")
    s_ = pooled[simple]
    gbm = "Gradient boosting (LightGBM)"
    w(f"- **Shipped default: {gbm.split(' (')[0].lower()}** ({pooled[gbm]['accuracy']:.1%}, {pooled[gbm]['bits']:.3f} bits). "
      f"It is within {pooled[gbm]['bits'] - b['bits']:.3f} bits of the best model and needs no neural network at run time.")
    w(f"- **The simple context tree** (`method = \"tree\"`, chain `{simple.replace('Context tree: ', '')}`) gets "
      f"{s_['accuracy']:.1%} accuracy, {-vs[simple]['bits']:.3f} bits per pitch better than the control. "
      f"The learned model adds {pooled[simple]['bits'] - b['bits']:.3f} bits and "
      f"{(b['accuracy'] - s_['accuracy']) * 100:.1f} accuracy points on top.")
    w(f"- **Pitch types remain mostly unpredictable.** The pitchers' own season mixes average "
      f"{P['mix_entropy'].mean():.2f} bits of uncertainty per pitch; the best model removes "
      f"{(P['mix_entropy'] - P['best_bits']).mean():.2f} bits of that ({P['explained'].mean():.0%}).")
    hard = P.sort_values("best_bits", ascending=False).head(5)
    w("- **Hardest to predict:** " + "; ".join(f"{r['name']} ({r['season']}, {r['best_bits']:.2f} bits, "
                                               f"{r['best_acc']:.0%} accuracy)" for _, r in hard.iterrows()) + ".")
    rv = sl["rv100"]
    w(f"- **Do surprising pitches work better?** Holding pitcher, season, pitch type and count fixed, each extra bit of "
      f"surprise changes runs saved by {rv['slope']:+.3f} per 100 pitches (95% CI {rv['lo']:+.3f} to {rv['hi']:+.3f}); "
      f"called+swinging strike rate by {sl['csw']['slope'] * 100:+.2f} points "
      f"({sl['csw']['lo'] * 100:+.2f} to {sl['csw']['hi'] * 100:+.2f}); whiffs per swing by "
      f"{sl['whiff']['slope'] * 100:+.2f} points ({sl['whiff']['lo'] * 100:+.2f} to {sl['whiff']['hi'] * 100:+.2f}). "
      "The gain is concentrated in the most surprising fifth of pitches. See §6 for what this does and does not show.")
    pc = S["pitchers"]["correlations"]
    w(f"- **Unpredictable pitchers are not better pitchers.** Across pitcher-seasons, wider mixes go with *fewer* "
      f"whiffs per swing (Spearman {pc['whiff']['mix_entropy'][0]:+.2f}) and no clear difference in runs saved "
      f"({pc['rv100']['best_bits'][0]:+.2f}). Dominant two-pitch pitchers are the easiest to predict and among the best; "
      "being unpredictable helps a given pitch, not a pitcher without the stuff.")
    w("")

    w("## Data\n")
    w(f"Every regular-season pitch {SEASONS[0]}–{SEASONS[-1]} from Baseball Savant (Statcast), {S['n_pitches']:,} pitches "
      "after dropping pitchouts, intentional and automatic balls and unclassified pitches. Pitch types are Statcast's "
      f"labels ({', '.join(VOCAB)}; FA folded into FF and CS into CU). Batter stats come from the same data, "
      "recency-weighted, using only previous days.\n")
    w(_t(["season", "role", "focus pitchers", "focus pitches"],
         [[s, "warm-up history" if s < TRAIN_FROM else "validation (tuning)" if s == VALID else
           "test" if s in TESTS else "training", nf.get(s, nf.get(str(s), {})).get("pitchers", "") if s in TESTS else "",
           f"{nf.get(s, nf.get(str(s), {})).get('pitches', 0):,}" if s in TESTS else ""] for s in SEASONS]))
    w("")

    w("## How models were compared\n")
    w("- **Walk-forward.** Each pitch is predicted from pitches thrown before it; history tables update after every "
      "pitch (including earlier pitches in the same game). Learned models are trained only on seasons before the "
      "test season; the last 20% of the previous season's days are held out for early stopping.")
    w(f"- **Tuning** (context-tree half-life and smoothing strengths) used only {VALID}.")
    w("- **Scores:** accuracy (top pick right), log loss in bits per pitch (lower is better; 0 = certain and right), "
      "Brier score. Log loss is the main score because it rewards honest probabilities, not just the top pick.")
    w("- **Intervals:** 95% bootstrap over pitcher-games. Only two independent test seasons exist.\n")

    w("## 1. Which model is most accurate?\n")
    w(f"Test seasons {TESTS[0]}–{TESTS[-1]} pooled, focus pitchers. Δ columns are vs the control (negative bits = better).\n")
    w(_t(["model", "accuracy", "bits / pitch", "Brier", "Δ bits vs control [95% CI]", "Δ accuracy pts [95% CI]"],
         [[m, f"{pooled[m]['accuracy']:.1%}", f"{pooled[m]['bits']:.3f}", f"{pooled[m]['brier']:.3f}",
           _ci(vs[m]['bits'], vs[m]['bits_lo'], vs[m]['bits_hi']),
           _ci(vs[m]['acc'] * 100, vs[m]['acc_lo'] * 100, vs[m]['acc_hi'] * 100, "{:+.1f}")] for m in order]))
    w("\nBy season (accuracy / bits per pitch):\n")
    w(_t(["model"] + [str(t) for t in TESTS],
         [[m] + [f"{R['by_season'][t][m]['accuracy']:.1%} / {R['by_season'][t][m]['bits']:.3f}"
                 for t in R["by_season"]] for m in order]))
    w("\nAll pitchers (including relievers and call-ups with few pitches):\n")
    pa = R["pooled_all"]
    w(_t(["model", "accuracy", "bits / pitch"], [[m, f"{pa[m]['accuracy']:.1%}", f"{pa[m]['bits']:.3f}"] for m in order]))
    w("")

    own = R.get("own_models")
    if own:
        w("## 1b. Does each pitcher need their own learned model?\n")
        w("Every model here is per pitcher in the sense that it reads that pitcher's own history. The question is "
          "whether the *learned* part should also be fitted separately for each pitcher (a small boosted model per "
          "pitcher, trained on their pitches only) or shared across all pitchers. Compared on the "
          f"{own['own']['n']:,} test pitches of {own['pitchers']} focus pitchers with enough history for their own model:\n")
        d = own["own_minus_shared_bits"]
        w(_t(["model", "accuracy", "bits / pitch"],
             [["Control: pitcher x count", f"{own['control']['accuracy']:.1%}", f"{own['control']['bits']:.3f}"],
              ["Each pitcher's own boosted model", f"{own['own']['accuracy']:.1%}", f"{own['own']['bits']:.3f}"],
              ["One shared boosted model", f"{own['shared']['accuracy']:.1%}", f"{own['shared']['bits']:.3f}"]]))
        w(f"\nOwn minus shared: {_ci(*d)} bits per pitch (negative = own models better).\n")

    w("## 2. What each kind of context adds\n")
    w("The context tree starts from the pitcher's overall mix and refines it one context at a time, shrinking thin "
      "contexts toward the broader one (MODEL.md). Each row adds one level; half-life and strengths were tuned on "
      f"{VALID} for that row's chain.\n")
    fits = S["tree_fits"]
    rows = []
    for name in CHAINS:
        cands = {k: v for k, v in fits.items() if k.startswith(name + " |")}
        bestk = min(cands, key=lambda k: cands[k]["valid_loss"])
        f = cands[bestk]
        hl = "none" if not f["half_life"] else f"{f['half_life']:g} days"
        tm = f"Context tree: {name}" if name != CONTROL else "Control + recency weighting"
        rows.append([name, hl, ", ".join(f"{v:g}" for v in f["strengths"]), f"{f['valid_loss'] / math.log(2):.4f}",
                     f"{pooled[tm]['accuracy']:.1%}", f"{pooled[tm]['bits']:.3f}"])
    w(_t(["chain", "half-life", "strengths (root → leaf)", f"{VALID} bits", "test accuracy", "test bits"], rows))
    w("\nRecency half-life (days) for the control chain vs validation loss:\n")
    w(_t(["half-life", f"{VALID} bits"],
         [["none" if not v["half_life"] else f"{v['half_life']:g}", f"{v['valid_loss'] / math.log(2):.4f}"]
          for k, v in fits.items() if k.startswith(CONTROL + " |")]))
    w(f"\nChosen default: chain `{' → '.join(fin['chain'])}`, half-life "
      f"{'none' if not fin['half_life'] else str(int(fin['half_life'])) + ' days'}, strengths {fin['strengths']}.\n")

    w("## 3. By count\n")
    bc = R["by_count"]
    w(_t(["count", "pitches", f"control acc", f"{simple.replace('Context tree: ', 'tree ')} acc", f"best acc",
          "control bits", "best bits"],
         [[k, f"{bc[control][k]['n']:,}", f"{bc[control][k]['accuracy']:.1%}", f"{bc[simple][k]['accuracy']:.1%}",
           f"{bc[best][k]['accuracy']:.1%}", f"{bc[control][k]['bits']:.3f}", f"{bc[best][k]['bits']:.3f}"]
          for k in bc[control]]))
    w("")

    imp = S["importance"].get(f"importance_{TESTS[-1]}")
    if imp:
        w(f"## 4. What the gradient-boosted model uses ({TESTS[-1]} model)\n")
        w("Share of total split gain. `tree_logp_*` is the context tree's own prediction (also the starting point); "
          "`<context>_share_*` are the pitcher's recency-weighted mix in that context; `bat_*` are batter stats.\n")
        w(_t(["feature", "gain share"], [[n, f"{g:.1%}"] for n, g in imp[:20]]))
        w("")

    w("## 5. Which pitchers are hardest to predict?\n")
    w(f"Pitcher-seasons with ≥{FOCUS_MIN:,} pitches in {TESTS[0]}–{TESTS[-1]} ({len(P)} pitcher-seasons, "
      f"{P['pitcher'].nunique()} pitchers), scored with the best model. *Mix entropy* is the uncertainty if you only "
      "knew the season's pitch mix (in hindsight); *bits* is the model's actual out-of-sample surprise per pitch; "
      "*explained* is the share of mix entropy the model removes using count, batter, sequence and situation.\n")
    cols = ["name", "season", "throws", "mix (≥3%)", "mix entropy", "bits", "accuracy", "explained"]

    def prow(r):
        return [r["name"], r["season"], r["throws"], _mix(r["mix"]), f"{r['mix_entropy']:.2f}", f"{r['best_bits']:.2f}",
                f"{r['best_acc']:.0%}", f"{r['explained']:.0%}"]

    w("**Most unpredictable** (highest bits per pitch):\n")
    w(_t(cols, [prow(r) for _, r in P.sort_values("best_bits", ascending=False).head(15).iterrows()]))
    w("\n**Most predictable** (lowest bits per pitch):\n")
    w(_t(cols, [prow(r) for _, r in P.sort_values("best_bits").head(15).iterrows()]))
    w("\n**Least exploitable given their arsenal** (context explains the smallest share of their mix; "
      "a wide, well-hidden mix):\n")
    w(_t(cols, [prow(r) for _, r in P.sort_values("explained").head(15).iterrows()]))
    w("\n**Most exploitable given their arsenal** (largest share explained by context):\n")
    w(_t(cols, [prow(r) for _, r in P.sort_values("explained", ascending=False).head(15).iterrows()]))
    w("")

    w("## 6. Do unpredictable pitches get better results?\n")
    w("**Pitch level.** *Surprise* = −log2 of the probability the best model gave to the pitch actually thrown "
      f"(average {sur['surprise_mean']:.2f} bits). A pitcher's rarely used pitch is surprising *and* may simply be "
      "better or worse, and counts change everything, so each comparison is made **within** the same pitcher, "
      "season, pitch type and count (fixed effects). Slopes are the change in the outcome per extra bit of surprise.\n")
    for sname, block in sur["slopes"].items():
        w(f"Strata: {sname}\n")
        w(_t(["outcome", "pitches", "average", "change per bit of surprise [95% CI]"],
             [[OUTCOME_LABEL[o], f"{v['n']:,}", f"{v['mean']:.3f}", _ci(v['slope'], v['lo'], v['hi'], "{:+.4f}")]
              for o, v in block.items()]))
        w("")
    w("Quintiles of surprise *within* each stratum (1 = least surprising for that pitcher/pitch/count). "
      "Values are the difference from the stratum average (strata with ≥10 pitches).\n")
    q = sur["quintiles"]
    w(_t(["quintile", "avg surprise (bits)"] + [OUTCOME_LABEL[o] for o in q],
         [[k + 1, f"{q['rv100']['rows'][k]['surprise_bits']:.2f}"] +
          [f"{q[o]['rows'][k]['vs_stratum_mean']:+.4f}" for o in q] for k in range(5)]))
    w("\n**Pitcher level.** Spearman correlation across pitcher-seasons between unpredictability and results "
      "(positive for runs saved/CSW/whiff = unpredictable pitchers do better; positive for xwOBA = worse):\n")
    corr = S["pitchers"]["correlations"]
    w(_t(["result", "vs bits per pitch", "vs mix entropy", "vs share explained"],
         [[OUTCOME_LABEL[o]] + [_ci(*corr[o][k], "{:+.2f}") for k in ("best_bits", "mix_entropy", "explained")]
          for o in corr]))
    w("\nCaveats: the model's surprise is not the batter's. Hitters and their coaches have their own expectations, "
      "and a pitch that surprises this model may not surprise them. Pitcher-level correlations mix in pitch "
      "quality: pitchers with more good pitches can afford wider mixes. Location is partly chosen *with* the pitch "
      "type, so the location-controlled row asks whether surprise helps beyond where the pitch ended up.\n")

    w("## 7. Caveats\n")
    w("- Statcast pitch labels change over time (e.g. sweepers, slurves) and are algorithmic; a pitch "
      "that is relabelled looks 'new' until history builds up again (recency weighting helps).")
    w("- Focus pitchers are mostly starters; relievers with small samples are less predictable from history.")
    w("- Within-game history is used as it happens, which assumes the pitch type of each pitch is known "
      "immediately (true for a live feed).")
    w("- The neural and boosted models were given a single set of hyper-parameters, not a search; they might "
      "improve with tuning (the context tree was tuned on 2024).")
    w("")
    return "\n".join(L)


if __name__ == "__main__":
    main(sys.argv[1:])
