"""Reproducible walk-forward study for bvp_similarity: measure, tune on 2025, report on 2026.

    python -m ballmonitor.models.bvp_similarity.research        # writes RESEARCH.md (~10 min)

Every number in RESEARCH.md comes from this file; never edit RESEARCH.md by hand.

Two folds, each with player tables built only from earlier seasons (build.build_datasets):

    tune fold   tables from 2021-2024, cases = pitcher-batter pairs of 2025
    test fold   tables from 2021-2025, cases = pitcher-batter pairs of 2026 (the shipped tables)

1. League rates (Log5 references, regression targets, micro-simulation count-group rates,
   per-PA xwOBA noise) are MEASURED from each fold's training pitches. No outcomes of the
   case season are used.
2. On the tune fold only (2025): choose the regression constants on the Log5 baseline, then
   the blend weights, the micro-sim xwOBA offset and BIP clip, then the range's talent SD.
3. Freeze those choices and report on the test fold (2026) against benchmarks: league average,
   raw Log5 (no regression), regressed Log5, and v0.2.1 (the previous defaults, re-run here on
   the rebuilt data with its micro-simulation reimplemented below as `legacy_microsim`).

Scoring is per plate appearance and PA-weighted over a uniform random sample of pairs, so it
estimates the whole season: K/BB/other log loss, and squared error of the pair's observed xwOBA
(weighted by PA, which is a proper score for the mean). Cases share pitchers and batters, so
uncertainty comes from a bootstrap that resamples pitchers.
"""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ballmonitor.core import registry
from ballmonitor.core.stats import z_for_level
from ballmonitor.models.bvp_similarity import features as F
from ballmonitor.models.bvp_similarity.build import build_datasets

MODEL_DIR = Path(__file__).resolve().parent
FOLDS_DIR = MODEL_DIR / "data" / "raw" / "folds"
RESEARCH_MD = MODEL_DIR / "RESEARCH.md"
RESEARCH_JSON = MODEL_DIR / "data" / "research.json"
FOLDS = {"tune": (list(range(2021, 2025)), 2025), "test": (list(range(2021, 2026)), 2026)}
N_CASES = 20000          # uniform random sample of pairs per case season
SEED = 20261026
N_BOOT = 1000
WORKERS = 8
GROUPS = ("first", "even", "behind", "two")

# grids searched on the tune fold
REGRESS_GRID = [1.0, 25.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0]
N0_GRID = [30.0, 60.0, 120.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0]
M0_GRID = [50.0, 150.0, 350.0, 1000.0, 3000.0]
CAP_GRID = [0.0, 0.1, 0.2, 0.35, 0.5, 0.7]
WMS_GRID = [0.0, 0.1, 0.2, 0.3, 0.5]
CLIP_GRID = [0.46, 0.55, 0.65, 0.80]
TALENT_SD_GRID = [round(0.005 * i, 3) for i in range(0, 41)]
PA_SD_GRID = [round(0.01 * i, 2) for i in range(15, 41)]

# the previous defaults (v0.2.1), kept here as a frozen benchmark
LEGACY = {
    "n0": 120.0, "m0": 350.0, "cap": 0.5, "w_ms": 0.30, "league_xwoba": 0.315, "league_k": 0.225,
    "league_bb": 0.082, "half_width": 0.045, "f_swing": 0.285, "zs_first": 0.65, "chase_first": 0.6,
    "whiff_first": 0.90, "zs_two": 0.72, "whiff_two": 1.25, "zs_behind": 0.76, "chase_behind": 0.8,
    "whiff_behind": 0.80, "zs_even": 0.68, "foul": 0.50, "wbb": 0.69, "offset": 0.021,
    "bip_min": 0.28, "bip_max": 0.46,
}


# ── 1. data ─────────────────────────────────────────────────────────────────

def fold_data_dir(season: int) -> Path:
    return FOLDS_DIR / str(season) / "data"


def build_fold(train: list[int], season: int) -> None:
    fold_dir = FOLDS_DIR / str(season)
    if not (fold_data_dir(season) / "backtest.csv").exists():
        print(f"building tables {train[0]}-{train[-1]} with {N_CASES} cases from {season} ...", flush=True)
        build_datasets(fold_dir, seasons=[*train, season], backtest_season=season, n_backtest=N_CASES)


def measure_league(train: list[int]) -> tuple[dict[str, float], dict[str, Any]]:
    """League rates from the training pitches -> param overrides (plus a few diagnostics)."""
    d = F.load_pitches(F.find_pitches_dir(MODEL_DIR), seasons=train)
    info = {"pitches": len(d), "in_zone_missing": float(d["in_zone"].isna().mean())}
    d = d[d["in_zone"].notna()]
    pa = d[d["is_pa"] == 1]
    iz = d["in_zone"] == 1
    swing = d["swing"] == 1
    take = ~swing
    contact = swing & (d["whiff"] == 0)
    called = (d["csw"] == 1) & take
    first = (d["balls"] == 0) & (d["strikes"] == 0)
    group = np.where(first, "first", np.where(d["strikes"] == 2, "two",
                     np.where(d["balls"] >= 2, "behind", "even")))
    out = {
        "league_xwoba": pa["xwoba_val"].mean(),
        "league_k_pct": pa["is_k"].mean(),
        "league_bb_pct": pa["is_bb"].mean(),
        "per_pa_xwoba_sd": pa["xwoba_val"].std(),
        "league_f_swing_pct": swing[first].mean(),
        "league_z_swing_pct": swing[iz].mean(),
        "league_chase_pct": swing[~iz].mean(),
        "league_whiff_pct": d.loc[swing, "whiff"].mean(),
        "ms_foul_share": 1.0 - d.loc[contact, "events"].notna().mean(),
    }
    for g in GROUPS:
        m = group == g
        out[f"ms_{g}_zone_swing"] = swing[m & iz].mean()
        out[f"ms_{g}_chase"] = swing[m & ~iz].mean()
        out[f"ms_{g}_whiff"] = d.loc[m & swing, "whiff"].mean()
        out[f"ms_{g}_cs_zone"] = called[m & iz & take].mean()
        out[f"ms_{g}_cs_out"] = called[m & ~iz & take].mean()
    info["hbp_rate"] = float(pa["is_hbp"].mean())
    return {k: round(float(v), 4) for k, v in out.items()}, info


# ── 2. one model pass per fold (parallel) ───────────────────────────────────

def _run_chunk(args: tuple[str, dict[str, Any], list[tuple[int, int, int]]]) -> list[dict[str, Any]]:
    data_dir, overrides, rows = args
    model = registry.load_model("bvp_similarity", None, overrides)
    model.data_dir = Path(data_dir)
    out = []
    for pitcher, batter, pa in rows:
        pred = model.predict({"pitcher": str(pitcher), "batter": str(batter), "pa": int(pa)})
        c = dict(pred.extras["_components"])
        c["lo"], c["hi"] = pred.primary.interval
        out.append(c)
    return out


def model_pass(cases: pd.DataFrame, data_dir: Path, overrides: dict[str, Any]) -> pd.DataFrame:
    rows = list(zip(cases["pitcher"], cases["batter"], cases["pa"]))
    chunks = [rows[i::WORKERS] for i in range(WORKERS)]
    with ProcessPoolExecutor(WORKERS) as pool:
        parts = list(pool.map(_run_chunk, [(str(data_dir), overrides, ch) for ch in chunks]))
    # undo the round-robin split
    out: list[dict[str, Any]] = [None] * len(rows)  # type: ignore[list-item]
    for w, part in enumerate(parts):
        for j, rec in enumerate(part):
            out[w + j * WORKERS] = rec
    return pd.DataFrame(out, index=cases.index)


# ── 3. vectorised re-computation of the blend (mirrors model.py) ────────────

def raw_rates(cases: pd.DataFrame, data_dir: Path) -> pd.DataFrame:
    """Per-case player rates and PA counts that model.predict feeds to regress/log5."""
    P = pd.read_parquet(data_dir / "pitchers.parquet")
    B = pd.read_parquet(data_dir / "batters.parquet")
    p = P.loc[cases["pitcher"]].reset_index(drop=True)
    b = B.loc[cases["batter"]].reset_index(drop=True)
    p_hand = p["throws"].to_numpy()
    b_hand = b["bats"].to_numpy()
    stand = np.where(b_hand == "R", "R", np.where(b_hand == "L", "L", np.where(p_hand == "L", "R", "L")))
    pick = lambda df, stem, side: np.where(side == "L", df[f"{stem}_vs_L"], df[f"{stem}_vs_R"]).astype(float)
    r = pd.DataFrame({
        "b_n": b["pa"].astype(float), "p_n": p["pa"].astype(float),
        "b_n_split": pick(b, "pa", p_hand), "p_n_split": pick(p, "pa", stand),
        "b_xw": b["xwoba"], "p_xw": p["xwoba"], "b_k": b["k_pct"], "p_k": p["k_pct"],
        "b_bb": b["bb_pct"], "p_bb": p["bb_pct"],
        "b_xw_split": pick(b, "xwoba", p_hand), "p_xw_split": pick(p, "xwoba", stand),
        "b_k_split": pick(b, "k_pct", p_hand), "p_k_split": pick(p, "k_pct", stand),
    })
    r.index = cases.index
    return r


def baselines(params: Any, r: pd.DataFrame, n0_xw: float, n0_k: float, n0_bb: float,
              league: dict[str, float]) -> dict[str, np.ndarray]:
    """Regressed platoon Log5 baselines, using the config formulas on numpy arrays."""
    reg = lambda x, n, prior, n0: params.formula("regress", x=x, n=n, prior=prior, n0=n0)
    log5 = lambda pb, pp, pl: params.formula("log5", pb=pb, pp=pp, pl=pl)

    def talent(split, n_split, overall, n_all, lg, n0):
        return reg(split, n_split, reg(overall, n_all, lg, n0), n0)

    a = {c: r[c].to_numpy() for c in r.columns}
    lx, lk, lb = league["league_xwoba"], league["league_k_pct"], league["league_bb_pct"]
    return {
        "xwoba": log5(talent(a["b_xw_split"], a["b_n_split"], a["b_xw"], a["b_n"], lx, n0_xw),
                      talent(a["p_xw_split"], a["p_n_split"], a["p_xw"], a["p_n"], lx, n0_xw), lx),
        "k": log5(talent(a["b_k_split"], a["b_n_split"], a["b_k"], a["b_n"], lk, n0_k),
                  talent(a["p_k_split"], a["p_n_split"], a["p_k"], a["p_n"], lk, n0_k), lk),
        "bb": log5(reg(a["b_bb"], a["b_n"], lb, n0_bb), reg(a["p_bb"], a["p_n"], lb, n0_bb), lb),
    }


def raw_log5(params: Any, r: pd.DataFrame, league: dict[str, float]) -> dict[str, np.ndarray]:
    log5 = lambda pb, pp, pl: params.formula("log5", pb=pb, pp=pp, pl=pl)
    return {
        "xwoba": log5(r["b_xw_split"].to_numpy(), r["p_xw_split"].to_numpy(), league["league_xwoba"]),
        "k": log5(r["b_k_split"].to_numpy(), r["p_k_split"].to_numpy(), league["league_k_pct"]),
        "bb": log5(r["b_bb"].to_numpy(), r["p_bb"].to_numpy(), league["league_bb_pct"]),
    }


def blend(c: pd.DataFrame, base: dict[str, np.ndarray], n0: float, m0: float, cap: float,
          ms: dict[str, np.ndarray], w_ms: float, w_ms_rates: float, clamps: dict[str, float]) -> dict[str, np.ndarray]:
    """bvp_weight, archetype_weight, blend_estimate and final_microsim_blend, vectorised."""
    n = c["direct_pa"].to_numpy(float)
    eff = c["eff_pa"].to_numpy(float)
    w_d = n / (n + n0)
    w_a = np.minimum(cap, (1.0 - w_d) * eff / (eff + m0))
    out = {}
    for key, w in (("xwoba", w_ms), ("k", w_ms_rates), ("bb", w_ms_rates)):
        direct = np.where(n > 0, c[f"direct_{key}"].to_numpy(float), base[key])
        y = w_d * direct + w_a * c[f"arch_{key}"].to_numpy(float) + (1 - w_d - w_a) * base[key]
        out[key] = (1 - w) * y + w * ms[key]
    out["xwoba"] = np.clip(out["xwoba"], clamps["xwoba_min"], clamps["xwoba_max"])
    out["k"] = np.clip(out["k"], clamps["k_pct_min"], clamps["k_pct_max"])
    out["bb"] = np.clip(out["bb"], clamps["bb_pct_min"], clamps["bb_pct_max"])
    return out


def ms_xwoba(c: pd.DataFrame, clip_max: float, clip_min: float, wbb: float, offset: float) -> np.ndarray:
    bip = np.clip(c["xwoba_bip_raw"].to_numpy(float), clip_min, clip_max)
    return c["ms_bb"].to_numpy(float) * wbb + c["ms_bip"].to_numpy(float) * bip + offset


# ── 4. the previous (v0.2.1) micro-simulation, as a benchmark ───────────────

def legacy_microsim(p_row: pd.Series, b_row: pd.Series) -> tuple[float, float, float]:
    """v0.2.1 chain (with its bug: a take is a called strike with prob. = the zone rate,
    regardless of where the pitch was). Returns (P(K), P(BB), xwOBA)."""
    L, lg = LEGACY, F.LEAGUE_DEFAULTS
    z0, z00 = float(p_row["zone_pct"]), float(p_row["f_zone_pct"])
    z_ahead, z_behind = float(p_row["ahead_zone_pct"]), float(p_row["behind_zone_pct"])
    b_swing00, chase, chase2 = float(b_row["f_swing_pct"]), float(b_row["chase_pct"]), float(b_row["chase_2s_pct"])
    whiff0 = 0.5 * float(p_row["whiff_pct"]) + 0.5 * float(b_row["whiff_pct"])
    memo: dict[tuple[int, int], np.ndarray] = {}

    def solve(b: int, s: int) -> np.ndarray:
        if (b, s) in memo:
            return memo[(b, s)]
        if b >= 4:
            return np.array([0.0, 1.0, 0.0])
        if s >= 3:
            return np.array([1.0, 0.0, 0.0])
        if b == 0 and s == 0:
            z = z00
            sw = z * L["zs_first"] * (b_swing00 / L["f_swing"]) + (1 - z) * chase * L["chase_first"]
            wh = whiff0 * L["whiff_first"]
        elif s == 2:
            z = z_ahead
            sw = z * L["zs_two"] + (1 - z) * chase2
            wh = whiff0 * L["whiff_two"]
        elif b >= 2 and s <= 1:
            z = z_behind
            sw = z * L["zs_behind"] + (1 - z) * chase * L["chase_behind"]
            wh = whiff0 * L["whiff_behind"]
        else:
            z = z0
            sw = z * L["zs_even"] + (1 - z) * chase
            wh = whiff0
        sw, wh = min(max(sw, 0.0), 1.0), min(max(wh, 0.0), 1.0)
        p_whiff, p_foul = sw * wh, sw * (1 - wh) * L["foul"]
        p_bip = sw * (1 - wh) * (1 - L["foul"])
        p_cs, p_ball = (1 - sw) * z, (1 - sw) * (1 - z)
        res = p_bip * np.array([0.0, 0.0, 1.0]) + p_ball * solve(b + 1, s)
        if s < 2:
            res = res + (p_cs + p_whiff + p_foul) * solve(b, s + 1)
        else:
            res = (res + (p_cs + p_whiff) * np.array([1.0, 0.0, 0.0])) / (1 - p_foul)
        memo[(b, s)] = res
        return res

    pk, pbb, pbip = solve(0, 0)
    b_k, b_bb = float(b_row["k_pct"]), float(b_row["bb_pct"])
    bip_xw = (float(b_row["xwoba"]) - L["wbb"] * b_bb) / max(0.1, 1 - b_k - b_bb)
    bip_xw = min(max(bip_xw, L["bip_min"]), L["bip_max"])
    return float(pk), float(pbb), float(pbb * L["wbb"] + pbip * bip_xw + L["offset"])


def legacy_predictions(params: Any, cases: pd.DataFrame, c: pd.DataFrame, r: pd.DataFrame,
                       data_dir: Path, clamps: dict[str, float]) -> dict[str, np.ndarray]:
    P = pd.read_parquet(data_dir / "pitchers.parquet")
    B = pd.read_parquet(data_dir / "batters.parquet")
    sims = np.array([legacy_microsim(P.loc[pi], B.loc[bi]) for pi, bi in zip(cases["pitcher"], cases["batter"])])
    league = {"league_xwoba": LEGACY["league_xwoba"], "league_k_pct": LEGACY["league_k"],
              "league_bb_pct": LEGACY["league_bb"]}
    base = raw_log5(params, r, league)
    ms = {"k": sims[:, 0], "bb": sims[:, 1], "xwoba": sims[:, 2]}
    out = blend(c, base, LEGACY["n0"], LEGACY["m0"], LEGACY["cap"], ms, LEGACY["w_ms"], LEGACY["w_ms"], clamps)
    out["ms_k"], out["ms_bb"] = ms["k"], ms["bb"]
    return out


# ── 5. scoring ──────────────────────────────────────────────────────────────

def case_losses(pred: dict[str, np.ndarray], cases: pd.DataFrame) -> dict[str, np.ndarray]:
    """Per-case SUMS over its PAs (so sums over cases / total PA = PA-weighted means)."""
    n = cases["pa"].to_numpy(float)
    k, bb = cases["k"].to_numpy(float), cases["bb"].to_numpy(float)
    pk = np.clip(pred["k"], 1e-6, 1)
    pbb = np.clip(pred["bb"], 1e-6, 1)
    po = np.clip(1 - pk - pbb, 1e-6, 1)
    obs = cases["xwoba_sum"].to_numpy(float) / n
    return {
        "n": n,
        "ll": -(k * np.log(pk) + bb * np.log(pbb) + (n - k - bb) * np.log(po)),
        "ll_k": -(k * np.log(pk) + (n - k) * np.log(1 - pk)),
        "ll_bb": -(bb * np.log(pbb) + (n - bb) * np.log(1 - pbb)),
        "sq": n * (pred["xwoba"] - obs) ** 2,
        "abs": np.abs(pred["xwoba"] - obs),   # per case, unweighted (the old metric)
        "pk": n * pred["k"], "pbb": n * pred["bb"], "px": n * pred["xwoba"],
    }


def summary(L: dict[str, np.ndarray], cases: pd.DataFrame) -> dict[str, float]:
    N = L["n"].sum()
    return {
        "ll": L["ll"].sum() / N, "ll_k": L["ll_k"].sum() / N, "ll_bb": L["ll_bb"].sum() / N,
        "mse": L["sq"].sum() / N, "mae_case": L["abs"].mean(),
        "mean_k": L["pk"].sum() / N, "mean_bb": L["pbb"].sum() / N, "mean_x": L["px"].sum() / N,
        "obs_k": cases["k"].sum() / N, "obs_bb": cases["bb"].sum() / N, "obs_x": cases["xwoba_sum"].sum() / N,
    }


def cluster_boot_diff(A: dict[str, np.ndarray], B: dict[str, np.ndarray], pitchers: np.ndarray,
                      key: str, rng: np.random.Generator) -> tuple[float, float, float]:
    """PA-weighted mean of key for A minus B, with a 90% interval from resampling pitchers."""
    ids, inv = np.unique(pitchers, return_inverse=True)
    sa = np.bincount(inv, A[key], len(ids))
    sb = np.bincount(inv, B[key], len(ids))
    sn = np.bincount(inv, A["n"], len(ids))
    diff = (sa.sum() - sb.sum()) / sn.sum()
    draws = rng.integers(0, len(ids), size=(N_BOOT, len(ids)))
    boots = (sa[draws].sum(1) - sb[draws].sum(1)) / sn[draws].sum(1)
    return float(diff), float(np.quantile(boots, 0.05)), float(np.quantile(boots, 0.95))


def coverage(lo: np.ndarray, hi: np.ndarray, cases: pd.DataFrame) -> float:
    obs = cases["xwoba_sum"].to_numpy(float) / cases["pa"].to_numpy(float)
    return float(np.mean((lo <= obs) & (obs <= hi)))


def interval(est: np.ndarray, n: np.ndarray, talent_sd: float, pa_sd: float, level: float):
    half = z_for_level(level) * np.sqrt(talent_sd ** 2 + pa_sd ** 2 / n)
    return np.maximum(0.0, est - half), est + half


# ── 6. the study ────────────────────────────────────────────────────────────

def load_cases(season: int) -> pd.DataFrame:
    cases = pd.read_csv(fold_data_dir(season) / "backtest.csv")
    cases["xwoba_sum"] = cases["observed_xwoba"] * cases["pa"]   # 4-dp rounded; fine for scoring
    return cases.reset_index(drop=True)


def clamps_of(params: Any) -> dict[str, float]:
    return {k: params[k] for k in ("xwoba_min", "xwoba_max", "k_pct_min", "k_pct_max", "bb_pct_min", "bb_pct_max")}


def main() -> None:
    rng = np.random.default_rng(SEED)
    params = registry.load_model("bvp_similarity").params
    clamps = clamps_of(params)
    level = float(params.interval_level)
    report: dict[str, Any] = {"folds": {}}

    measured, info, cases, comps, rates = {}, {}, {}, {}, {}
    for name, (train, season) in FOLDS.items():
        build_fold(train, season)
        measured[name], info[name] = measure_league(train)
        cases[name] = load_cases(season)
        rates[name] = raw_rates(cases[name], fold_data_dir(season))

    # ── tune fold: one model pass with measured rates (blend params do not matter here)
    tune = "tune"
    ct, rt, ft = cases[tune], rates[tune], measured[tune]
    print("model pass on the tune fold ...", flush=True)
    comps[tune] = model_pass(ct, fold_data_dir(FOLDS[tune][1]), ft)

    # check the vectorised mirror reproduces model.predict at the pass's params
    base_chk = baselines(params, rt, params.regress_xwoba_pa, params.regress_k_pa, params.regress_bb_pa, ft)
    ms_chk = {"xwoba": comps[tune]["ms_xwoba"].to_numpy(), "k": comps[tune]["ms_k"].to_numpy(),
              "bb": comps[tune]["ms_bb"].to_numpy()}
    chk = blend(comps[tune], base_chk, params.bvp_shrinkage_n0, params.archetype_shrinkage_m0,
                params.max_archetype_weight, ms_chk, params.microsim_weight, params.microsim_weight_rates, clamps)
    mirror_err = max(float(np.max(np.abs(chk[k] - comps[tune][f"final_{k}"]))) for k in ("xwoba", "k", "bb"))
    assert mirror_err < 1e-3, f"vectorised mirror disagrees with model.predict by {mirror_err}"

    def score(pred):
        return summary(case_losses(pred, ct), ct)

    # step A: regression constants on the Log5 baseline alone
    reg_rows = []
    best = {}
    for key, metric in (("k", "ll_k"), ("bb", "ll_bb"), ("xwoba", "mse")):
        results = []
        for n0 in REGRESS_GRID:
            b = baselines(params, rt, n0, n0, n0, ft)
            pred = {"k": b["k"], "bb": b["bb"], "xwoba": b["xwoba"]}
            results.append((score(pred)[metric], n0))
        reg_rows.append((key, results))
        best[key] = min(results)[1]
    reg = {"regress_xwoba_pa": best["xwoba"], "regress_k_pa": best["k"], "regress_bb_pa": best["bb"]}
    base_t = baselines(params, rt, reg["regress_xwoba_pa"], reg["regress_k_pa"], reg["regress_bb_pa"], ft)

    # step B: micro-sim xwOBA offset (PA-weighted mean residual) for each BIP clip
    obs_t = ct["xwoba_sum"].to_numpy() / ct["pa"].to_numpy()
    n_t = ct["pa"].to_numpy(float)
    offsets = {}
    for clip in CLIP_GRID:
        no_off = ms_xwoba(comps[tune], clip, params.ms_bip_xwoba_min, params.woba_bb_weight, 0.0)
        offsets[clip] = round(float(np.sum(n_t * (obs_t - no_off)) / n_t.sum()), 4)

    # step C: blend weights. Score each setting by the share of Log5's gain over league average it
    # achieves (1 = as good as regressed Log5), summed over xwOBA (MSE) and K/BB (log loss).
    lg_pred = {"xwoba": np.full(len(ct), ft["league_xwoba"]), "k": np.full(len(ct), ft["league_k_pct"]),
               "bb": np.full(len(ct), ft["league_bb_pct"])}
    s_lg, s_b5 = score(lg_pred), score(dict(base_t))
    gain = lambda s, m: (s_lg[m] - s[m]) / (s_lg[m] - s_b5[m])
    ms_rates = {"k": comps[tune]["ms_k"].to_numpy(), "bb": comps[tune]["ms_bb"].to_numpy()}
    ms_x = {clip: ms_xwoba(comps[tune], clip, params.ms_bip_xwoba_min, params.woba_bb_weight, offsets[clip])
            for clip in CLIP_GRID}
    best_c = None
    for n0, m0, cap in product(N0_GRID, M0_GRID, CAP_GRID):
        br = None
        for w in WMS_GRID:
            s = score(blend(comps[tune], base_t, n0, m0, cap, {**ms_rates, "xwoba": ms_x[0.46]}, 0.0, w, clamps))
            g = gain(s, "ll")
            if br is None or g > br[0]:
                br = (g, w)
        bx = max(((gain(score(blend(comps[tune], base_t, n0, m0, cap, {**ms_rates, "xwoba": ms_x[clip]},
                                    w, 0.0, clamps)), "mse"), w, clip)
                  for w, clip in product(WMS_GRID, CLIP_GRID)))
        total = bx[0] + br[0]
        if best_c is None or total > best_c[0]:
            best_c = (total, n0, m0, cap, bx, br)
    _, n0, m0, cap, bx, br = best_c
    chosen = {
        **reg, "bvp_shrinkage_n0": n0, "archetype_shrinkage_m0": m0, "max_archetype_weight": cap,
        "microsim_weight": bx[1], "microsim_weight_rates": br[1], "ms_bip_xwoba_max": bx[2],
        "ms_xwoba_offset": offsets[bx[2]],
    }
    # one-at-a-time sensitivity around the chosen point (tune fold)
    def tuned_pred(ch):
        msx = ms_xwoba(comps[tune], ch["ms_bip_xwoba_max"], params.ms_bip_xwoba_min, params.woba_bb_weight,
                       ch["ms_xwoba_offset"])
        return blend(comps[tune], base_t, ch["bvp_shrinkage_n0"], ch["archetype_shrinkage_m0"],
                     ch["max_archetype_weight"], {**ms_rates, "xwoba": msx},
                     ch["microsim_weight"], ch["microsim_weight_rates"], clamps)

    s_best = score(tuned_pred(chosen))
    sens = []
    for key, grid in (("bvp_shrinkage_n0", N0_GRID), ("archetype_shrinkage_m0", M0_GRID),
                      ("max_archetype_weight", CAP_GRID), ("microsim_weight", WMS_GRID),
                      ("microsim_weight_rates", WMS_GRID)):
        row = []
        for v in grid:
            s = score(tuned_pred({**chosen, key: v}))
            row.append((v, gain(s, "mse"), gain(s, "ll")))
        sens.append((key, row))

    # step D: the range. One PA's xwOBA is lumpy (0 for a strikeout), so a normal band with the raw
    # per-PA SD over-covers 1-PA pairs. Fit an effective per-PA SD and the talent SD on 2025 so
    # that every PA bucket is as close to the target coverage as possible (case-weighted).
    est_t = np.round(tuned_pred(chosen)["xwoba"], 3)
    bucket_t = np.digitize(n_t, [1.5, 2.5, 4.5, 7.5])
    cov_rows = []
    for pa_sd, sd in product(PA_SD_GRID, TALENT_SD_GRID):
        lo_t, hi_t = interval(est_t, n_t, sd, pa_sd, level)
        inside = (lo_t <= obs_t) & (obs_t <= hi_t)
        per_bucket = np.array([inside[bucket_t == i].mean() for i in range(5)])
        counts = np.bincount(bucket_t, minlength=5)
        loss = float(np.sum(counts * (per_bucket - level) ** 2) / counts.sum())
        cov_rows.append((loss, pa_sd, sd, float(inside.mean())))
    _, pa_sd_best, talent_sd, cov_tune = min(cov_rows)
    chosen["per_pa_xwoba_sd"] = pa_sd_best
    chosen["interval_talent_sd"] = talent_sd
    tune_cov = cov_tune

    # ── test fold: frozen choices + 2021-2025 measured rates, straight through model.predict
    test = "test"
    cs, rs, fs = cases[test], rates[test], measured[test]
    overrides = {**fs, **chosen}
    print("model pass on the test fold ...", flush=True)
    comps[test] = model_pass(cs, fold_data_dir(FOLDS[test][1]), overrides)
    model_pred = {"xwoba": comps[test]["final_xwoba"].to_numpy(), "k": comps[test]["final_k"].to_numpy(),
                  "bb": comps[test]["final_bb"].to_numpy()}
    base_s = baselines(params, rs, chosen["regress_xwoba_pa"], chosen["regress_k_pa"], chosen["regress_bb_pa"], fs)
    print("legacy (v0.2.1) benchmark ...", flush=True)
    legacy = legacy_predictions(params, cs, comps[test], rs, fold_data_dir(FOLDS[test][1]), clamps)
    no_ms = blend(comps[test], base_s, chosen["bvp_shrinkage_n0"], chosen["archetype_shrinkage_m0"],
                  chosen["max_archetype_weight"], {"k": comps[test]["ms_k"].to_numpy(),
                  "bb": comps[test]["ms_bb"].to_numpy(), "xwoba": comps[test]["ms_xwoba"].to_numpy()},
                  0.0, 0.0, clamps)
    ms_only = {"xwoba": comps[test]["ms_xwoba"].to_numpy(), "k": comps[test]["ms_k"].to_numpy(),
               "bb": comps[test]["ms_bb"].to_numpy()}
    models = {
        "league average": {"xwoba": np.full(len(cs), fs["league_xwoba"]), "k": np.full(len(cs), fs["league_k_pct"]),
                           "bb": np.full(len(cs), fs["league_bb_pct"])},
        "raw Log5 (v0.2 baseline)": raw_log5(params, rs, fs),
        "regressed Log5": dict(base_s),
        "micro-sim alone (new)": ms_only,
        "v0.2.1 defaults": {k: legacy[k] for k in ("xwoba", "k", "bb")},
        "v0.2.1 micro-sim alone": {"xwoba": legacy["xwoba"] * 0 + np.nan, "k": legacy["ms_k"], "bb": legacy["ms_bb"]},
        "v0.3.0 without micro-sim": no_ms,
        "v0.3.0 (shipped)": model_pred,
    }
    losses = {m: case_losses(p, cs) for m, p in models.items()}
    sums = {m: summary(L, cs) for m, L in losses.items()}

    pitchers = cs["pitcher"].to_numpy()
    diffs = []
    for m in ("raw Log5 (v0.2 baseline)", "v0.2.1 defaults", "v0.3.0 without micro-sim", "v0.3.0 (shipped)"):
        for key in ("ll", "ll_k", "ll_bb", "sq"):
            diffs.append((m, key, *cluster_boot_diff(losses[m], losses["regressed Log5"], pitchers, key, rng)))

    # coverage on test
    n_s = cs["pa"].to_numpy(float)
    lo, hi = comps[test]["lo"].to_numpy(), comps[test]["hi"].to_numpy()
    legacy_lo, legacy_hi = legacy["xwoba"] - LEGACY["half_width"], legacy["xwoba"] + LEGACY["half_width"]
    buckets = [(1, 1), (2, 2), (3, 4), (5, 7), (8, 999)]
    cov_bucket = []
    for a, b in buckets:
        m = (n_s >= a) & (n_s <= b)
        sub = cs[m]
        cov_bucket.append((f"{a}" if a == b else (f"{a}+" if b == 999 else f"{a}-{b}"), int(m.sum()),
                           coverage(lo[m], hi[m], sub), coverage(legacy_lo[m], legacy_hi[m], sub)))

    report = {
        "measured": measured, "info": info, "chosen": chosen, "mirror_err": mirror_err,
        "tune_scores": {"league": s_lg, "log5": s_b5, "best": s_best}, "test_scores": sums,
        "coverage_test": coverage(lo, hi, cs), "coverage_test_legacy": coverage(legacy_lo, legacy_hi, cs),
        "coverage_tune": tune_cov,
    }
    RESEARCH_JSON.write_text(json.dumps(report, indent=1, default=float))
    write_markdown(report, cases, reg_rows, offsets, sens, diffs, cov_bucket, measured, params)
    print(f"wrote {RESEARCH_MD.relative_to(MODEL_DIR.parents[2])}")


# ── 7. report ───────────────────────────────────────────────────────────────

def _fmt(x: float, nd: int = 4) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def write_markdown(rep, cases, reg_rows, offsets, sens, diffs, cov_bucket, measured, params) -> None:
    ch, ms = rep["chosen"], rep["test_scores"]
    L = []
    w = L.append
    w("# RESEARCH — bvp_similarity (generated by research.py; do not edit by hand)\n")
    w("Walk-forward study: every league rate is measured from seasons before the case season, every")
    w("tuned value is chosen on 2025 matchups (tables from 2021-2024), and the report is on 2026")
    w("matchups (tables from 2021-2025) with those values frozen.\n")
    w("## Data\n")
    w("| fold | tables from | cases (pairs) | PAs | distinct pitchers | distinct batters | mean PA per pair |")
    w("|---|---|---|---|---|---|---|")
    for name, (train, season) in FOLDS.items():
        c = cases[name]
        w(f"| {name} ({season}) | {train[0]}-{train[-1]} | {len(c):,} | {int(c['pa'].sum()):,} | "
          f"{c['pitcher'].nunique():,} | {c['batter'].nunique():,} | {c['pa'].mean():.2f} |")
    w("")
    w(f"Cases are a uniform random sample (seed 42) of all pairs in the season whose pitcher (150+")
    w("pitches) and batter (40+ PA) have training profiles, so PA-weighted metrics estimate the whole")
    w("season. Pairs share players, so they are not independent: the independent units are closer")
    w("to the number of distinct pitchers, and there is ONE out-of-sample period (2026) and one")
    w("tuning period (2025).\n")
    w("## 1. Measured league rates (micro-simulation and Log5 references)\n")
    w("| param | 2021-2024 (tune fold) | 2021-2025 (test fold, shipped) |")
    w("|---|---|---|")
    for k in measured["test"]:
        w(f"| `{k}` | {measured['tune'][k]:.4f} | {measured['test'][k]:.4f} |")
    w("")
    w(f"Pitches with no zone call (excluded): {rep['info']['test']['in_zone_missing']:.2%}. HBP rate "
      f"{rep['info']['test']['hbp_rate']:.2%} of PA (not modelled by the chain; covered by the offset).\n")
    w("## 2. Tuning on 2025 (tune fold only)\n")
    w("**A. Regression constants** (Log5 baseline alone; PA of league average added):\n")
    w("| n0 (PA) | " + " | ".join(f"{g:g}" for g in REGRESS_GRID) + " |")
    w("|---|" + "---|" * len(REGRESS_GRID))
    names = {"k": "K log loss", "bb": "BB log loss", "xwoba": "xwOBA MSE"}
    for key, results in reg_rows:
        w(f"| {names[key]} | " + " | ".join(f"{v:.5f}" for v, _ in results) + " |")
    w(f"\nChosen: xwOBA {ch['regress_xwoba_pa']:g}, K {ch['regress_k_pa']:g}, BB {ch['regress_bb_pa']:g} PA.\n")
    w("**B. Micro-sim xwOBA offset** (PA-weighted mean residual on 2025, per BIP clip): " +
      ", ".join(f"clip {k:g} -> {v:+.4f}" for k, v in offsets.items()) + ".\n")
    w("**C. Blend weights.** Each setting is scored by the share of the regressed Log5 baseline's gain")
    w("over league average that it achieves (1.0 = same as Log5, >1 = better), for xwOBA (PA-weighted")
    w("squared error) and for K/BB/other (per-PA log loss); the setting with the largest sum wins.")
    w(f"Grid: N0 {N0_GRID}, M0 {M0_GRID}, cap {CAP_GRID}, micro-sim weights {WMS_GRID}, BIP clip {CLIP_GRID}.\n")
    w("| chosen | value |")
    w("|---|---|")
    for k in ("bvp_shrinkage_n0", "archetype_shrinkage_m0", "max_archetype_weight", "microsim_weight",
              "microsim_weight_rates", "ms_bip_xwoba_max", "ms_xwoba_offset", "per_pa_xwoba_sd",
              "interval_talent_sd"):
        w(f"| `{k}` | {ch[k]:g} |")
    w("")
    tsc = rep["tune_scores"]
    w(f"Tune-fold (in-sample for these choices) per-PA log loss: league {tsc['league']['ll']:.5f}, "
      f"Log5 {tsc['log5']['ll']:.5f}, chosen {tsc['best']['ll']:.5f}; xwOBA MSE: league "
      f"{tsc['league']['mse']:.5f}, Log5 {tsc['log5']['mse']:.5f}, chosen {tsc['best']['mse']:.5f}.\n")
    w("Sensitivity on 2025 (one parameter moved, others at the chosen values; gain vs Log5 = 1.0):\n")
    for key, row in sens:
        w(f"- `{key}`: " + "; ".join(f"{v:g} -> xwOBA {gx:.2f}, K/BB {gr:.2f}" for v, gx, gr in row))
    w("")
    w(f"**D. Range.** Half-width = z * sqrt(talent_sd^2 + per-PA SD^2 / PA). One PA's xwOBA is lumpy")
    w(f"(0 for every strikeout), so the measured per-PA SD ({measured['tune']['per_pa_xwoba_sd']:.3f}) over-covers")
    w(f"1-PA pairs. Both terms were fitted on 2025 to bring each PA bucket (1, 2, 3-4, 5-7, 8+) closest")
    w(f"to {params.interval_level:.0%}: effective per-PA SD {ch['per_pa_xwoba_sd']:g}, talent SD "
      f"{ch['interval_talent_sd']:g} (2025 coverage {rep['coverage_tune']:.1%}).\n")
    w("## 3. Out-of-sample results (2026, frozen choices)\n")
    w("PA-weighted over all sampled pairs. Log loss is per PA over K / BB / other; K and BB log loss")
    w("are the binary versions. xwOBA MSE weights each pair's squared error by its PA (proper for the")
    w("mean). Case MAE is the old unweighted metric, shown for continuity (mostly noise).\n")
    w("| model | log loss K/BB/other | K log loss | BB log loss | xwOBA MSE | case MAE | mean K% | mean BB% | mean xwOBA |")
    w("|---|---|---|---|---|---|---|---|---|")
    any_s = next(iter(ms.values()))
    for m, s in ms.items():
        ll = f"{s['ll']:.5f}"
        mse = "n/a" if m == "v0.2.1 micro-sim alone" else f"{s['mse']:.5f}"
        mae = "n/a" if m == "v0.2.1 micro-sim alone" else f"{s['mae_case']:.4f}"
        mx = "n/a" if m == "v0.2.1 micro-sim alone" else f"{s['mean_x']:.3f}"
        w(f"| {m} | {ll} | {s['ll_k']:.5f} | {s['ll_bb']:.5f} | {mse} | {mae} | {s['mean_k']:.1%} | "
          f"{s['mean_bb']:.1%} | {mx} |")
    w(f"| *observed* | | | | | | {any_s['obs_k']:.1%} | {any_s['obs_bb']:.1%} | {any_s['obs_x']:.3f} |")
    w("")
    w("Differences vs regressed Log5 (negative = better), with 90% intervals from resampling pitchers:\n")
    w("| model | metric | difference | 90% interval |")
    w("|---|---|---|---|")
    labels = {"ll": "log loss K/BB/other", "ll_k": "K log loss", "ll_bb": "BB log loss", "sq": "xwOBA MSE"}
    for m, key, d, lo, hi in diffs:
        w(f"| {m} | {labels[key]} | {d:+.5f} | {lo:+.5f} to {hi:+.5f} |")
    w("")
    w(f"**Range coverage on 2026** (target {params.interval_level:.0%}): shipped {rep['coverage_test']:.1%}, "
      f"v0.2.1 (+/- 0.045) {rep['coverage_test_legacy']:.1%}.\n")
    w("| PA in pair | cases | shipped | v0.2.1 |")
    w("|---|---|---|---|")
    for b, n, c1, c2 in cov_bucket:
        w(f"| {b} | {n:,} | {c1:.1%} | {c2:.1%} |")
    w("")
    w("## Caveats\n")
    w("- One tuning season and one test season; results could differ in other years.")
    w("- Pairs share pitchers and batters; the bootstrap resamples pitchers to account for this.")
    w("- xwOBA per PA is very noisy (per-PA SD about 0.37), so xwOBA differences between models are")
    w("  small relative to the noise; the K/BB log loss is the sharper test.")
    w("- The v0.2.1 benchmark is re-run on the rebuilt (fixed batted-ball) data, so its similarity")
    w("  peers differ slightly from the shipped v0.2.1 results; its micro-simulation is the")
    w("  `legacy_microsim` reimplementation in this file.")
    w(f"- Mirror check: the vectorised blend used for tuning matches model.predict to {rep['mirror_err']:.1e}.")
    RESEARCH_MD.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
