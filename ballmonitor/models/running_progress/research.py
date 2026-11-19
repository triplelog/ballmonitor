"""Fit and test the running_progress model.  Writes RESEARCH.md, data/fit.json, data/backtest.csv.

    python -m ballmonitor.models.running_progress.download      # weekly parquet files, ~59 MB
    python -m ballmonitor.models.running_progress.research --write-config
                                                                # needs numpy, scipy, pandas, pyarrow

Data: BMClab weekly training totals of 36,412 Strava users who had run a World Marathon
Major (Afonseca, Watanabe & Duarte 2022; doi:10.6084/m9.figshare.16620238.v5, CC BY 4.0),
104 weeks from 2019-01-01. RESEARCH.md is generated: never edit it by hand.

Cases: a cutoff ("today") every 2 weeks from week 12, horizons 4/6/9/13/19/26 weeks; a
case is an athlete with at least `min_run_weeks` run weeks among the 12 before the cutoff.
The features come from the weeks before the cutoff only; the outcome is the 4 weeks
ending at the target date.

Splits: athletes by md5(id) (60% train / 40% test), and time:
    train   = train athletes, target windows ending in 2019            (fit)
    new19   = test athletes, target windows ending in 2019             (new people, same year)
    pre2020 = test athletes, target windows 2020-01-01 .. 2020-03-10   (new people, later
              period, before COVID-19 lockdowns: the honest out-of-sample test)
    covid   = test athletes, target windows from 2020-03-11            (reported separately)

Fit (train only): median (L1) regressions for the location of ln pace and ln(km+off);
L1 regression of ln|residual| for the scale; empirical quantiles of residual / scale for
the band shapes; logistic regression for still training; seasonal curves from the 2019
weeks of train athletes. Baselines (persistence of the 12-week or the 4-week pace,
horizon-only bands) are fitted the same way, so the comparison is like for like.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import linprog, minimize

from ballmonitor.core import registry
from ballmonitor.core.backtest import run_backtest
from ballmonitor.models.running_progress import features as feat
from ballmonitor.models.running_progress.model import QUANTILE_KEYS, QUANTILE_LEVELS

MODEL = "running_progress"
MODEL_DIR = Path(__file__).resolve().parent
RAW = MODEL_DIR / "data" / "raw"
CONFIG = MODEL_DIR / "config.toml"
OUT_MD = MODEL_DIR / "RESEARCH.md"
FIT_JSON = MODEL_DIR / "data" / "fit.json"
BACKTEST = MODEL_DIR / "data" / "backtest.csv"
VARIANTS = MODEL_DIR / "variants"

HORIZONS = (4, 6, 9, 13, 19, 26)
FIRST_CUTOFF = 12
CUTOFF_STEP = 2
TRAIN_TENTHS = 6                  # md5(athlete) % 10 < 6 -> train
YEAR_WEEKS = 52                   # week index 52 = 2020-01-01
PRE_END = 62                      # target windows ending at week 62 (2020-03-11) or earlier
SAMPLE = {"train": 0.35, "new19": 0.15, "pre2020": 1.0, "covid": 0.15}
FIT_ROWS = 60000                  # rows per L1 linear programme
BOOT = 500
SEED = 20261118
BACKTEST_ROWS = {"pre2020": 1200, "covid": 500, "new19": 300}
BANISTER_TAU = (6.0, 1.0)         # fitness / fatigue time constants in weeks (42 d, 7 d)
LEVELS = np.array(QUANTILE_LEVELS)
SETS = ("train", "new19", "pre2020", "covid")


class P:
    """Minimal stand-in for Params (attribute + item access) for features.py."""

    def __init__(self, values: dict[str, Any]):
        self.__dict__.update(values)

    def __getitem__(self, k):
        return self.__dict__[k]


# ── data ───────────────────────────────────────────────────────────────────

def load(p: P):
    frames = [pd.read_parquet(RAW / f"run_ww_{y}_w.parquet") for y in (2019, 2020)]
    d = pd.concat(frames).sort_values(["athlete", "datetime"])
    athletes = np.sort(d.athlete.unique())
    A = len(athletes)
    W = len(d) // A
    starts = sorted(d.datetime.dt.date.unique())
    assert W == len(starts) == 104
    km_raw = d.distance.to_numpy().reshape(A, W)
    mn_raw = d.duration.to_numpy().reshape(A, W)
    mn_raw = np.where(km_raw > 0, mn_raw, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        pace = mn_raw / km_raw
    bad = (km_raw > 0) & ((pace < p.min_pace_min_per_km) | (pace > p.max_pace_min_per_km) | (km_raw > p.max_week_km))
    km = np.where(bad, np.nan, km_raw)
    mn = np.where(bad, np.nan, mn_raw)
    meta = d.drop_duplicates("athlete").set_index("athlete").loc[athletes, ["gender", "age_group", "country"]]
    train = np.array([int(hashlib.md5(str(a).encode()).hexdigest(), 16) % 10 < TRAIN_TENTHS for a in athletes])
    south = meta.country.isin(feat.SOUTHERN_COUNTRIES).to_numpy()
    stats = {
        "athletes": A, "weeks": W, "run_weeks": int((km_raw > 0).sum()), "bad_weeks": int(bad.sum()),
        "bad_fast": int(((km_raw > 0) & (pace < p.min_pace_min_per_km)).sum()),
        "bad_slow": int(((km_raw > 0) & (pace > p.max_pace_min_per_km)).sum()),
        "bad_km": int((km_raw > p.max_week_km).sum()),
        "train_athletes": int(train.sum()), "south": int(south.sum()),
        "male": float((meta.gender == "M").mean()),
        "age": meta.age_group.value_counts(normalize=True).round(3).to_dict(),
        "countries": meta.country.value_counts().head(5).to_dict(),
        "zero_share": {str(y): float((km_raw[:, i:i + 52] == 0).mean()) for y, i in ((2019, 0), (2020, 52))},
    }
    return dict(km=km, mn=mn, km_raw=km_raw, mn_raw=mn_raw, starts=starts, meta=meta, train=train,
                south=south, athletes=athletes, stats=stats)


def season_curves(D, p: P) -> tuple[np.ndarray, np.ndarray]:
    """Within-athlete monthly means (2019, train athletes, northern) of ln pace and ln(km+off)."""
    keep = D["train"] & ~D["south"]
    km, mn = D["km"][keep, :YEAR_WEEKS], D["mn"][keep, :YEAR_WEEKS]
    month = np.array([(s + dt.timedelta(days=3)).month for s in D["starts"][:YEAR_WEEKS]])
    with np.errstate(divide="ignore", invalid="ignore"):
        lp = np.where(km > 0, np.log(mn / km), np.nan)
    lk = np.log(km + p.km_offset)
    out = []
    for arr in (lp, lk):
        dm = arr - np.nanmean(arr, axis=1, keepdims=True)
        s = np.array([np.nanmean(dm[:, month == m]) for m in range(1, 13)])
        out.append(s - s.mean())
    return out[0], out[1]


# ── cases ──────────────────────────────────────────────────────────────────

def _win(k, m, n):
    k, m = k[:, -n:], m[:, -n:]
    valid = ~np.isnan(k)
    return valid.sum(1), (np.nan_to_num(k) > 0).sum(1), np.nansum(k, 1), np.nansum(m, 1)


def cutoff_features(D, c: int, p: P) -> dict[str, np.ndarray]:
    """features.summarise for every athlete at cutoff week c (same definitions)."""
    n = min(c, int(p.lookback_weeks))
    k, m = D["km"][:, c - n:c], D["mn"][:, c - n:c]
    rw, rr, rk, rm = _win(k, m, int(p.recent_weeks))
    bw, br, bk, bm = _win(k, m, int(p.base_weeks))
    lw, lr, lk_, lm = _win(k, m, n)
    tw, tr, tk, tm = _win(k, m, int(p.tanda_weeks))
    ok = br >= p.min_run_weeks
    ran = np.nan_to_num(k) > 0
    last = n - 1 - np.argmax(ran[:, ::-1], axis=1)
    since = np.minimum(n - 1 - last, int(p.base_weeks))
    with np.errstate(divide="ignore", invalid="ignore"):
        base_pace = bm * 60 / bk
        recent_pace = np.where(rk > 0, rm * 60 / rk, np.nan)
        long_pace = lm * 60 / lk_
        lp_base = np.log(base_pace)
        tr_recent = np.where(rk > 0, np.log(recent_pace / base_pace), 0.0)
        tr_long = np.log(base_pace / long_pace)
        off = p.km_offset
        bkw, rkw, lkw = bk / bw, rk / np.maximum(rw, 1), lk_ / lw
        rkw = np.where(rw > 0, rkw, 0.0)
        lk_base = np.log(bkw + off)
        # Banister impulse-response (research only): EWMA of weekly minutes, normalised
        ages = np.arange(n)[::-1]          # oldest week has age n-1
        mz = np.nan_to_num(m)
        ew = {}
        for tau in BANISTER_TAU:
            w = np.exp(-ages / tau)
            ew[tau] = (mz * w).sum(1) / w.sum()
    return dict(
        ok=ok, n=np.full(len(ok), n), share=br / bw, since=since, lp_base=lp_base, tr_recent=tr_recent,
        tr_long=tr_long, lk_base=lk_base, ktr_recent=np.log(rkw + off) - lk_base,
        ktr_long=lk_base - np.log(lkw + off), recent_pace=recent_pace,
        tanda_K=tk / np.maximum(tw, 1), tanda_P=np.where(tk > 0, tm * 60 / np.where(tk > 0, tk, 1), np.nan),
        recent_kmw=rkw, base_kmw=bkw,
        banister=np.log((ew[BANISTER_TAU[1]] + 1) / (ew[BANISTER_TAU[0]] + 1)),
        fitness=np.log(ew[BANISTER_TAU[0]] + 1),
    )


def outcome(D, e: int, p: P):
    """Target window = the target_weeks weeks before week e."""
    k, m = D["km"][:, e - int(p.target_weeks):e], D["mn"][:, e - int(p.target_weeks):e]
    w, r, kk, mm = _win(k, m, int(p.target_weeks))
    with np.errstate(divide="ignore", invalid="ignore"):
        pace = np.where(kk > 0, mm * 60 / kk, np.nan)
        kmw = kk / w
    return w > 0, r > 0, pace, kmw


def set_of(e: int, h: int, p: P) -> str | None:
    if e <= YEAR_WEEKS:
        return "year2019"
    start = e - int(p.target_weeks)
    if start >= YEAR_WEEKS and e <= PRE_END:
        return "pre2020"
    if start >= PRE_END:
        return "covid"
    return None  # windows straddling the new year or the lockdown start


def season_diff(D, c: int, h: int, south: bool, p: P) -> tuple[float, float]:
    today = D["starts"][c]
    base = [feat.week_mid(today, k) for k in range(int(p.base_weeks) - 1, -1, -1)]
    tgt = feat.target_week_mids(today, h, int(p.target_weeks))
    return (feat.season_value(tgt, "season_pace", south, p) - feat.season_value(base, "season_pace", south, p),
            feat.season_value(tgt, "season_km", south, p) - feat.season_value(base, "season_km", south, p))


def build_cases(D, p: P) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(SEED)
    A, W = D["km"].shape
    cols: dict[str, list] = {}
    for c in range(FIRST_CUTOFF, W - min(HORIZONS) + 1, CUTOFF_STEP):
        F = cutoff_features(D, c, p)
        for h in HORIZONS:
            e = c + h
            if e > W:
                continue
            period = set_of(e, h, p)
            if period is None:
                continue
            valid, running, pace, kmw = outcome(D, e, p)
            base_ok = F["ok"] & valid
            if period == "year2019":
                masks = {"train": base_ok & D["train"], "new19": base_ok & ~D["train"]}
            else:
                masks = {period: base_ok & ~D["train"]}
            sp = {s: season_diff(D, c, h, s, p) for s in (False, True)}
            for name, mask in masks.items():
                mask = mask & (rng.random(A) < SAMPLE[name])
                idx = np.where(mask)[0]
                if not len(idx):
                    continue
                south = D["south"][idx]
                add = {
                    "set": np.full(len(idx), SETS.index(name)), "ath": idx, "c": np.full(len(idx), c),
                    "h": np.full(len(idx), h, dtype=float), "e": np.full(len(idx), e),
                    "south": south,
                    "sp": np.where(south, sp[True][0], sp[False][0]),
                    "sk": np.where(south, sp[True][1], sp[False][1]),
                    "running": running[idx], "pace_t": pace[idx], "kmw_t": kmw[idx],
                }
                for k, v in F.items():
                    if k != "ok":
                        add[k] = v[idx]
                for k, v in add.items():
                    cols.setdefault(k, []).append(v)
    return {k: np.concatenate(v) for k, v in cols.items()}


# ── fitting ────────────────────────────────────────────────────────────────

def l1_fit(X: np.ndarray, y: np.ndarray, rng) -> np.ndarray:
    """Least absolute deviations (median regression) as a linear programme (HiGHS)."""
    if len(y) > FIT_ROWS:
        i = rng.choice(len(y), FIT_ROWS, replace=False)
        X, y = X[i], y[i]
    m, k = X.shape
    cost = np.r_[np.zeros(k), np.ones(m), np.ones(m)]
    A = sparse.hstack([sparse.csr_matrix(X), sparse.eye(m), -sparse.eye(m)]).tocsr()
    res = linprog(cost, A_eq=A, b_eq=y, bounds=[(None, None)] * k + [(0, None)] * (2 * m), method="highs")
    if res.status != 0:
        raise RuntimeError(res.message)
    return res.x[:k]


def logit_fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    def nll(b):
        z = X @ b
        return np.sum(np.logaddexp(0, z) - y * z) / len(y), X.T @ (1 / (1 + np.exp(-z)) - y) / len(y)
    res = minimize(nll, np.zeros(X.shape[1]), jac=True, method="BFGS")
    return res.x


def design(C: dict, cols: list[str]) -> np.ndarray:
    return np.column_stack([np.ones(len(C["h"]))] + [C[c] for c in cols]) if cols else np.ones((len(C["h"]), 1))


def add_derived(C: dict, p: P) -> None:
    off = p.km_offset
    C["rel"] = C["lp_base"] - math.log(p.ref_pace)
    C["krel"] = C["lk_base"] - math.log(p.ref_km + off)
    C["logh"] = np.log(C["h"] / p.min_horizon_weeks)
    C["abs_tr"] = np.abs(C["tr_recent"])
    C["abs_ktr"] = np.abs(C["ktr_recent"])
    with np.errstate(divide="ignore", invalid="ignore"):
        C["y_pace"] = np.log(C["pace_t"]) - C["lp_base"]
    C["y_km"] = np.log(C["kmw_t"] + off) - C["lk_base"]
    C["male"] = (C["gender"] == "M").astype(float)
    C["age18"] = (C["age_group"] == "18 - 34").astype(float)
    C["age55"] = (C["age_group"] == "55 +").astype(float)


# Specification of each fitted location-scale model: (location columns, fixed location
# columns with weight 1, scale columns, intercept in location?)
SPECS = {
    "pace": dict(y="y_pace", loc=["tr_recent", "tr_long", "sp", "rel"], scale=["logh", "share", "rel", "abs_tr"]),
    "pace_persistence": dict(y="y_pace", loc=None, scale=["logh"]),
    "pace_last_month": dict(y="y_pace", loc=None, fixed="tr_recent", scale=["logh"]),
    "pace_no_season": dict(y="y_pace", loc=["tr_recent", "tr_long", "rel"], scale=["logh", "share", "rel", "abs_tr"]),
    "pace_banister": dict(y="y_pace", loc=["tr_recent", "tr_long", "sp", "rel", "banister", "fitness"],
                          scale=["logh", "share", "rel", "abs_tr"]),
    "pace_demog": dict(y="y_pace", loc=["tr_recent", "tr_long", "sp", "rel", "male", "age18", "age55"],
                       scale=["logh", "share", "rel", "abs_tr"]),
    "km": dict(y="y_km", loc=["ktr_recent", "ktr_long", "sk", "share", "krel"], scale=["logh", "share", "krel", "abs_ktr"]),
    "km_persistence": dict(y="y_km", loc=None, scale=["logh"]),
    "km_no_season": dict(y="y_km", loc=["ktr_recent", "ktr_long", "share", "krel"], scale=["logh", "share", "krel", "abs_ktr"]),
}


def fit_ls(C: dict, rows: np.ndarray, spec: dict, rng) -> dict:
    y = C[spec["y"]][rows]
    fixed = C[spec["fixed"]][rows] if spec.get("fixed") else 0.0
    if spec["loc"] is None:
        b = np.zeros(0)
        loc = fixed + np.zeros(len(y))
    else:
        X = design({k: C[k][rows] for k in ["h"] + spec["loc"]}, spec["loc"])
        b = l1_fit(X, y - fixed, rng)
        loc = fixed + X @ b
    r = y - loc
    G = design({k: C[k][rows] for k in ["h"] + spec["scale"]}, spec["scale"])
    g = l1_fit(G, np.log(np.maximum(np.abs(r), 1e-6)), rng)
    z = np.quantile(r / np.exp(G @ g), LEVELS)
    return {"b": b.tolist(), "g": g.tolist(), "z": z.tolist(), "spec": spec}


def predict_ls(C: dict, rows: np.ndarray, fit: dict) -> np.ndarray:
    """Quantiles (n x 7) of the log change y (location + scale * z), as the model computes them."""
    spec = fit["spec"]
    loc = C[spec["fixed"]][rows] if spec.get("fixed") else np.zeros(len(rows))
    if spec["loc"] is not None:
        loc = loc + design({k: C[k][rows] for k in ["h"] + spec["loc"]}, spec["loc"]) @ np.array(fit["b"])
    scale = np.exp(design({k: C[k][rows] for k in ["h"] + spec["scale"]}, spec["scale"]) @ np.array(fit["g"]))
    return loc[:, None] + scale[:, None] * np.sort(np.array(fit["z"]))[None, :]


# ── scoring ────────────────────────────────────────────────────────────────

def pinball(q: np.ndarray, y: np.ndarray) -> np.ndarray:
    d = y[:, None] - q
    return np.mean(np.maximum(LEVELS * d, (LEVELS - 1) * d), axis=1)


def score_pace(q: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
    """Per-case metrics in pace terms; q and y are log changes from the base pace."""
    return {
        "ape": np.abs(np.exp(q[:, 3] - y) - 1) * 100,
        "bias": (np.exp(q[:, 3] - y) - 1) * 100,
        "in50": ((q[:, 2] <= y) & (y <= q[:, 4])).astype(float),
        "in80": ((q[:, 1] <= y) & (y <= q[:, 5])).astype(float),
        "in95": ((q[:, 0] <= y) & (y <= q[:, 6])).astype(float),
        "pinball": pinball(q, y) * 100,
    }


def summary(m: dict[str, np.ndarray], mask=None) -> dict[str, float]:
    if mask is None:
        mask = np.ones(len(m["ape"]), bool)
    return {
        "n": int(mask.sum()), "mape": float(m["ape"][mask].mean()), "medape": float(np.median(m["ape"][mask])),
        "bias": float(np.median(m["bias"][mask])), "in50": float(m["in50"][mask].mean()),
        "in80": float(m["in80"][mask].mean()), "in95": float(m["in95"][mask].mean()),
        "pinball": float(m["pinball"][mask].mean()),
    }


def cluster_boot(ath: np.ndarray, diff: np.ndarray, rng) -> tuple[float, float]:
    """95% interval of the mean of diff, resampling athletes (cases of one athlete together)."""
    u, inv = np.unique(ath, return_inverse=True)
    s = np.bincount(inv, weights=diff)
    n = np.bincount(inv).astype(float)
    out = []
    for _ in range(BOOT):
        w = np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u))
        out.append((w * s).sum() / (w * n).sum())
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


# ── config / variant writing ───────────────────────────────────────────────

LOC_NAMES = {
    "pace": {"const": "pace_loc_a", "tr_recent": "pace_loc_recent", "tr_long": "pace_loc_long", "sp": "pace_loc_season",
             "rel": "pace_loc_rel"},
    "km": {"const": "km_loc_a", "ktr_recent": "km_loc_recent", "ktr_long": "km_loc_long", "sk": "km_loc_season",
           "share": "km_loc_share", "krel": "km_loc_rel"},
}
SCALE_NAMES = {
    "pace": {"const": "pace_scale_a", "logh": "pace_scale_h", "share": "pace_scale_share", "rel": "pace_scale_rel",
             "abs_tr": "pace_scale_trend"},
    "km": {"const": "km_scale_a", "logh": "km_scale_h", "share": "km_scale_share", "krel": "km_scale_rel",
           "abs_ktr": "km_scale_trend"},
}
RUN_COLS = ["share", "since", "krel", "logh"]
RUN_NAMES = ["run_a", "run_share", "run_since", "run_level", "run_h"]


def param_values(what: str, fit: dict) -> dict[str, float]:
    """config.toml param values of a fitted location-scale spec (zeros for unused terms)."""
    out = {name: 0.0 for name in LOC_NAMES[what].values()}
    out.update({name: 0.0 for name in SCALE_NAMES[what].values()})
    spec = fit["spec"]
    if spec["loc"] is not None:
        for col, v in zip(["const"] + spec["loc"], fit["b"]):
            out[LOC_NAMES[what][col]] = v
    if spec.get("fixed"):
        out[LOC_NAMES[what][spec["fixed"]]] = 1.0
    for col, v in zip(["const"] + spec["scale"], fit["g"]):
        out[SCALE_NAMES[what][col]] = v
    for k, v in zip(QUANTILE_KEYS, sorted(fit["z"])):
        out[f"{what}_z_{k}"] = v
    return {k: round(float(v), 4) for k, v in out.items()}


def write_config(values: dict[str, float]) -> None:
    text = CONFIG.read_text()
    for name, v in values.items():
        pat = re.compile(rf"(\[params\.{re.escape(name)}\]\nvalue = )([^\n]+)")
        if not pat.search(text):
            raise KeyError(f"config.toml has no [params.{name}]")
        text = pat.sub(lambda m: m.group(1) + repr(v), text)
    CONFIG.write_text(text)


def write_variant(name: str, description: str, values: dict[str, float]) -> None:
    lines = [f"# Generated by research.py; see RESEARCH.md", f'description = "{description}"', "", "[params]"]
    lines += [f"{k} = {v!r}" for k, v in values.items()]
    (VARIANTS / f"{name}.toml").write_text("\n".join(lines) + "\n")


# ── backtest.csv ───────────────────────────────────────────────────────────

def write_backtest(D, C: dict, rng) -> list[int]:
    chosen = []
    for name, n in BACKTEST_ROWS.items():
        idx = np.where(C["set"] == SETS.index(name))[0]
        chosen += sorted(rng.choice(idx, min(n, len(idx)), replace=False).tolist())
    fields = ["case", "split", "athlete", "gender", "age_group", "country", "hemisphere", "today", "weeks_ahead",
              "weekly_km", "weekly_minutes", "actual_running", "actual_pace", "actual_km"]
    with open(BACKTEST, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        for j, i in enumerate(chosen):
            a, c, h = int(C["ath"][i]), int(C["c"][i]), int(C["h"][i])
            n = int(C["n"][i])
            meta = D["meta"].iloc[a]
            km = " ".join(f"{x:.6g}" for x in D["km_raw"][a, c - n:c])
            mn = " ".join(f"{x:.6g}" for x in D["mn_raw"][a, c - n:c])
            pace = C["pace_t"][i]
            w.writerow([j, SETS[int(C["set"][i])], int(D["athletes"][a]), meta.gender, meta.age_group, meta.country,
                        "south" if C["south"][i] else "north", D["starts"][c].isoformat(), h, km, mn,
                        int(C["running"][i]), "" if np.isnan(pace) else f"{pace:.3f}", f"{C['kmw_t'][i]:.3f}"])
    return chosen


# ── report ─────────────────────────────────────────────────────────────────

def fmt_pace(sec: float) -> str:
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d}"


def table(header: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return out + [""]


def srow(label: str, s: dict) -> list[Any]:
    return [label, f"{s['n']:,}", f"{s['mape']:.2f}", f"{s['medape']:.2f}", f"{s['bias']:+.2f}",
            f"{s['in50']:.3f}", f"{s['in80']:.3f}", f"{s['in95']:.3f}", f"{s['pinball']:.3f}"]


SHEAD = ["", "cases", "MAPE %", "median APE %", "median bias %", "in 50%", "in 80%", "in 95%", "pinball x100"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-config", action="store_true", help="write fitted values to config.toml + variants")
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)

    model = registry.load_model(MODEL)
    pv = {k: s.value for k, s in model.params.specs.items()}
    p = P(pv)
    D = load(p)
    sp_curve, sk_curve = season_curves(D, p)
    for i in range(12):
        pv[f"season_pace_m{i + 1:02d}"] = round(float(sp_curve[i]), 4)
        pv[f"season_km_m{i + 1:02d}"] = round(float(sk_curve[i]), 4)
    p = P(pv)
    print("building cases ...")
    C = build_cases(D, p)
    for col in ("gender", "age_group", "country"):
        C[col] = D["meta"][col].to_numpy()[C["ath"]]
    sets = {name: C["set"] == SETS.index(name) for name in SETS}
    tr = sets["train"]
    pv["ref_pace"] = float(round(np.median(np.exp(C["lp_base"][tr]))))
    pv["ref_km"] = float(round(np.median(C["base_kmw"][tr]), 1))
    p = P(pv)
    add_derived(C, p)
    run = C["running"].astype(bool)
    print({k: int(v.sum()) for k, v in sets.items()})

    # ── fit ──
    fits = {}
    for name, spec in SPECS.items():
        rows = np.where(tr & run)[0]
        fits[name] = fit_ls(C, rows, spec, rng)
        print("fitted", name, np.round(fits[name]["b"], 4), np.round(fits[name]["g"], 3))
    Xr = design(C, RUN_COLS)
    run_b = logit_fit(Xr[tr], run[tr].astype(float))
    run_b0 = logit_fit(design(C, ["logh"])[tr], run[tr].astype(float))

    values = {}
    values.update(param_values("pace", fits["pace"]))
    values.update(param_values("km", fits["km"]))
    values.update({n: round(float(v), 4) for n, v in zip(RUN_NAMES, run_b)})
    values.update({k: pv[k] for k in pv if k.startswith("season_")})
    values["ref_pace"] = pv["ref_pace"]
    values["ref_km"] = pv["ref_km"]

    # ── evaluate (vectorised, rounded coefficients = exactly what config.toml gets) ──
    def rounded(fit):
        return {**fit, "b": [round(x, 4) for x in fit["b"]], "g": [round(x, 4) for x in fit["g"]],
                "z": [round(x, 4) for x in fit["z"]]}

    res: dict[str, dict] = {}
    for name in SPECS:
        what = "pace" if name.startswith("pace") else "km"
        res[name] = {}
        for sname, smask in sets.items():
            rows = np.where(smask & run)[0]
            q = predict_ls(C, rows, rounded(fits[name]))
            y = C[f"y_{what}"][rows]
            res[name][sname] = (rows, q, score_pace(q, y))
    rb = np.array([round(float(v), 4) for v in run_b])

    def p_run(mask, b, X):
        z = X[mask] @ b
        return 1 / (1 + np.exp(-z))

    run_res = {}
    for sname, smask in sets.items():
        y = run[smask].astype(float)
        pm = p_run(smask, rb, Xr)
        pb = p_run(smask, run_b0, design(C, ["logh"]))
        def ll(pp):
            return float(np.mean(-(y * np.log(pp) + (1 - y) * np.log(1 - pp))))
        run_res[sname] = dict(n=int(smask.sum()), rate=float(y.mean()), brier=float(np.mean((pm - y) ** 2)),
                              brier0=float(np.mean((pb - y) ** 2)), ll=ll(pm), ll0=ll(pb), pm=pm, y=y)

    # ── write config, variants, backtest ──
    if args.write_config:
        write_config(values)
        write_variant(
            "persistence",
            "Baseline: pace and weekly km stay at their 12-week level (no trend, season or pull to the "
            "typical runner); bands widen with the horizon only. Fitted the same way as the default.",
            {**param_values("pace", fits["pace_persistence"]), **param_values("km", fits["km_persistence"])})
        write_variant(
            "last_month",
            "Baseline: pace stays at its last-4-week level (the 12-week level if no recent run); weekly km "
            "at its 12-week level; bands widen with the horizon only.",
            {**param_values("pace", fits["pace_last_month"]), **param_values("km", fits["km_persistence"])})
        write_variant(
            "no_season",
            "Default model refitted without the seasonal terms (pace and km), for comparison.",
            {**param_values("pace", fits["pace_no_season"]), **param_values("km", fits["km_no_season"])})
    chosen = write_backtest(D, C, np.random.default_rng(SEED + 1))
    FIT_JSON.write_text(json.dumps({
        "values": values, "fits": {k: {kk: vv for kk, vv in v.items()} for k, v in fits.items()},
        "run_b": run_b.tolist(), "run_b_horizon_only": run_b0.tolist(), "stats": D["stats"],
    }, indent=1, default=str))

    # ── end-to-end check: the model (config.toml) on backtest.csv vs the vectorised fit ──
    e2e = None
    if args.write_config:
        model = registry.load_model(MODEL)
        rows = list(csv.DictReader(open(BACKTEST)))
        worst = 0.0
        for row, i in zip(rows, chosen):
            inputs, actual = model.backtest_case(row)
            pred = model.predict(inputs)
            q = pred.extras["pace_quantiles"]
            ref = np.exp(C["lp_base"][i] + predict_ls(C, np.array([i]), rounded(fits["pace"]))[0])
            pr = 1 / (1 + np.exp(-(Xr[i] @ rb)))
            worst = max(worst, float(np.max(np.abs(np.array(q) / ref - 1))), abs(pred.extras["p_running"] - pr))
        e2e = {"worst": worst, "default": run_backtest(model, rows),
               "persistence": run_backtest(registry.load_model(MODEL, "persistence"), rows)}
        print("end-to-end worst relative difference", worst)

    write_report(D, C, sets, fits, res, run_res, values, run_b, e2e, rng, p)
    print("wrote", OUT_MD)


def write_report(D, C, sets, fits, res, run_res, values, run_b, e2e, rng, p: P) -> None:
    st = D["stats"]
    tr = sets["train"]
    L = ["# Running progress: research", "",
         "_Generated by `python -m ballmonitor.models.running_progress.research --write-config`; do not edit._", ""]

    L += ["## Data", "",
          f"BMClab weekly training totals (Afonseca, Watanabe & Duarte 2022, PeerJ 10:e13192; data "
          f"doi:10.6084/m9.figshare.16620238.v5, CC BY 4.0): {st['athletes']:,} Strava users who had run a "
          f"World Marathon Major, {st['weeks']} weeks from 2019-01-01 (each year binned in 52 weeks from "
          "1 January, so 31 December is not in the weekly files). Columns used: weekly distance (km) and "
          "duration (min); gender, age group and country for checks. The dataset has no heart rate and no "
          "race results.", "",
          f"- {st['male'] * 100:.0f}% men; age groups {st['age']}; top countries {st['countries']}.",
          f"- Weeks with no running: {st['zero_share']['2019'] * 100:.1f}% in 2019, "
          f"{st['zero_share']['2020'] * 100:.1f}% in 2020.",
          f"- Cleaning: of {st['run_weeks']:,} run weeks, {st['bad_weeks']:,} "
          f"({st['bad_weeks'] / st['run_weeks'] * 100:.2f}%) are treated as missing: {st['bad_fast']:,} faster "
          f"than 3:00/km, {st['bad_slow']:,} slower than 15:00/km, {st['bad_km']:,} over 300 km.",
          f"- Southern-hemisphere athletes (seasons shifted 6 months): {st['south']:,}.", ""]

    n = {k: int(v.sum()) for k, v in sets.items()}
    runn = {k: int((v & C['running'].astype(bool)).sum()) for k, v in sets.items()}
    L += ["## Cases and splits", "",
          f"A cutoff ('today') every {CUTOFF_STEP} weeks from week {FIRST_CUTOFF}, horizons {HORIZONS} weeks; "
          "a case is an athlete with at least 3 run weeks in the 12 weeks before the cutoff. Features use "
          "only weeks before the cutoff (up to 26); the outcome is the 4 weeks ending at the target date. "
          f"Athletes are split by md5(id): {st['train_athletes']:,} train, "
          f"{st['athletes'] - st['train_athletes']:,} test. Cases were subsampled per cutoff and horizon "
          f"(shares {SAMPLE}).", "",
          *table(["set", "who", "target windows", "cases", "of which still training"], [
              ["train", "train athletes", "ending in 2019", f"{n['train']:,}", f"{runn['train']:,}"],
              ["new19", "test athletes", "ending in 2019", f"{n['new19']:,}", f"{runn['new19']:,}"],
              ["pre2020", "test athletes", "2020-01-01 .. 2020-03-10", f"{n['pre2020']:,}", f"{runn['pre2020']:,}"],
              ["covid", "test athletes", "from 2020-03-11", f"{n['covid']:,}", f"{runn['covid']:,}"],
          ]),
          "**Independent periods.** Cases overlap heavily: one athlete appears at many cutoffs and "
          "horizons, and every athlete shares the same calendar. The fit sees one year (2019; about 13 "
          "non-overlapping 4-week target windows, one seasonal cycle). The honest test, **pre2020**, covers "
          "about **2.5 non-overlapping 4-week windows** (January to early March 2020) of new athletes, so it "
          "says little about other seasons. **new19** is out of sample in people but not in time (same "
          "weeks as the fit). **covid** is out of sample in people and time but the lockdowns changed "
          "training (Afonseca et al. report 7.5% less distance in 2020), so it is reported separately and "
          "not used to choose anything. Intervals below resample athletes (cluster bootstrap), which "
          "ignores the calendar dependence and so are too narrow.", ""]

    L += ["## What to predict, and why", "",
          "- **Average pace over the 4 weeks before the target date** (total time / total distance; primary). "
          "It is the only fitness signal in the data. It mixes easy runs, workouts and races, so it is a "
          "loose fitness proxy: a runner who adds easy volume gets slower on this measure while getting "
          "fitter. Four weeks smooth out single runs; the forecast is conditional on still training.",
          "- **Mean weekly km over the same 4 weeks**, given still training (rest weeks count as 0).",
          "- **The chance of still training**: at least one run logged in those 4 weeks.",
          "- **Implied marathon time (Tanda 2011)**: from the paper only, not validated here (no races).", "",
          "The starting point is the 12-week pace, not the last 4 weeks: as a forecast it is better at every "
          "horizon (baselines below). Days with a run would be a natural consistency measure, but the "
          "daily files (~309 MB) were not needed: everything is computed from weekly totals so a weekly "
          "log works as well as a daily one.", ""]

    sp = [values[f"season_pace_m{i:02d}"] for i in range(1, 13)]
    sk = [values[f"season_km_m{i:02d}"] for i in range(1, 13)]
    L += ["## Seasonal curves (2019, train athletes, northern hemisphere)", "",
          "Within-athlete monthly means of ln weekly pace and ln(weekly km + 1), centred. Pace: + = slower.", "",
          *table(["month"] + "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
                 [["pace (%)"] + [f"{x * 100:+.1f}" for x in sp], ["km (log)"] + [f"{x:+.2f}" for x in sk]]),
          "Pace is slowest in July (heat) and fastest in March; volume peaks in September (autumn "
          "marathons) and is lowest in December. The curves are in-sample for the train set (same year) "
          "and a prior-year estimate for pre2020 and covid.", ""]

    def coef_rows(what):
        f = fits[what]
        spec = f["spec"]
        rows = [["location: " + c, f"{v:+.4f}"] for c, v in zip(["const"] + (spec["loc"] or []), f["b"])]
        rows += [["ln scale: " + c, f"{v:+.4f}"] for c, v in zip(["const"] + spec["scale"], f["g"])]
        rows += [["z " + k, f"{v:+.3f}"] for k, v in zip(QUANTILE_KEYS, sorted(f["z"]))]
        return rows

    L += ["## Fitted model (config.toml defaults)", "",
          f"Reference runner: base pace {fmt_pace(values['ref_pace'])}/km, {values['ref_km']} km/week "
          "(medians of the train cases).", "",
          "**Pace**: y = ln(target pace / 12-week pace). Location (median regression) on tr_recent = "
          "ln(4-wk / 12-wk pace), tr_long = ln(12-wk / 26-wk pace), the season change and rel = "
          "ln(12-wk pace / ref pace); ln scale on ln(h/4), share, rel and |tr_recent|.", "",
          *table(["term", "value"], coef_rows("pace")),
          "**Weekly km**: y = ln((target km/wk + 1) / (12-wk km/wk + 1)), terms analogous (ktr_recent, ktr_long, "
          "season, share, krel).", "",
          *table(["term", "value"], coef_rows("km")),
          "**Still training**: logistic regression.", "",
          *table(["term", "value"], [[n, f"{v:+.4f}"] for n, v in zip(["const"] + RUN_COLS, run_b)])]
    b = dict(zip(["const"] + fits["pace"]["spec"]["loc"], fits["pace"]["b"]))
    L += [f"Read: the median moves {b['tr_recent'] * 100:.0f}% of the way from the 12-week to the 4-week "
          f"pace, and {abs(b['tr_long']) * 100:.0f}% of the way back from the 12-week to the 26-week pace: "
          "both a recent change and the longer history count. Slow runners are predicted to speed up a "
          f"little and fast ones to slow down ({b['rel']:+.3f} per log unit of pace).", ""]

    # pace results
    def block(sname: str, title: str, names=("pace", "pace_persistence", "pace_last_month", "pace_no_season")):
        labels = {"pace": "model (default)", "pace_persistence": "12-week pace stays (variant persistence)",
                  "pace_last_month": "4-week pace stays (variant last_month)",
                  "pace_no_season": "model without season (variant no_season)",
                  "pace_banister": "model + Banister fitness/fatigue", "pace_demog": "model + gender/age"}
        return [f"### {title}", "", *table(SHEAD, [srow(labels[nm], summary(res[nm][sname][2])) for nm in names])]

    L += ["## Results: pace", "",
          "MAPE = mean |median / actual - 1|; pinball = mean quantile loss over the 7 levels on ln pace "
          "(x100, lower is better; it scores the whole band, not just the median). The baselines are fitted "
          "on the same train cases with bands that widen with the horizon only.", ""]
    L += block("pre2020", "pre2020: new athletes, Jan to early Mar 2020 (the honest test)")
    rows_m, _, mm = res["pace"]["pre2020"]
    _, _, mb = res["pace_persistence"]["pre2020"]
    ath = C["ath"][rows_m]
    d_ape = mm["ape"] - mb["ape"]
    d_pin = mm["pinball"] - mb["pinball"]
    ci1 = cluster_boot(ath, d_ape, rng)
    ci2 = cluster_boot(ath, d_pin, rng)
    L += [f"Model minus 12-week persistence on pre2020: MAPE {d_ape.mean():+.3f} points "
          f"(athlete bootstrap 95%: {ci1[0]:+.3f} to {ci1[1]:+.3f}); pinball {d_pin.mean():+.4f} "
          f"({ci2[0]:+.4f} to {ci2[1]:+.4f}). Relative to persistence the model cuts the pace MAPE by "
          f"{-d_ape.mean() / mb['ape'].mean() * 100:.1f}% and the pinball loss by "
          f"{-d_pin.mean() / mb['pinball'].mean() * 100:.1f}%. These intervals treat the ~2.5 calendar "
          "windows as if they were many, so they are optimistic.", ""]
    L += block("new19", "new19: new athletes, 2019 (same weeks as the fit)")
    L += block("train", "train (in sample)")
    L += block("covid", "covid: new athletes, 2020-03-11 onwards (lockdowns; separate)")

    # breakdowns on pre2020
    def by(sname, key_fn, labels, what="pace"):
        rows, _, m = res[what][sname]
        keys = key_fn(rows)
        out = []
        for k in labels:
            mask = keys == k
            if mask.sum():
                out.append(srow(str(k), summary(m, mask)))
        return out

    L += ["### pre2020 by group (default model)", "",
          *table(["horizon (weeks)"] + SHEAD[1:], by("pre2020", lambda r: C["h"][r].astype(int), HORIZONS)),
          *table(["weeks with a run (of 12)"] + SHEAD[1:],
                 by("pre2020", lambda r: np.array(["3-5", "6-8", "9-11", "12"])[
                     np.round(C["share"][r] * 12).astype(int).clip(3, 12) // 3 - 1], ["3-5", "6-8", "9-11", "12"])),
          *table(["gender"] + SHEAD[1:], by("pre2020", lambda r: C["gender"][r], ["M", "F"])),
          *table(["age group"] + SHEAD[1:], by("pre2020", lambda r: C["age_group"][r], ["18 - 34", "35 - 54", "55 +"])),
          *table(["12-week pace"] + SHEAD[1:],
                 by("pre2020", lambda r: np.array(["< 5:00/km", "5:00-6:00", "> 6:00/km"])[
                     np.digitize(np.exp(C["lp_base"][r]), [300, 360])], ["< 5:00/km", "5:00-6:00", "> 6:00/km"])),
          *table(["target window ends (week index)"] + SHEAD[1:],
                 by("pre2020", lambda r: C["e"][r].astype(int), list(range(56, PRE_END + 1)))),
          "(Week 56 ends 2020-01-29, week 62 ends 2020-03-10.)", "",
          "### covid by target month (default model)", "",
          *table(["month (2020)"] + SHEAD[1:],
                 by("covid", lambda r: np.array([D["starts"][int(e) - 1].month for e in C["e"][r]]), range(3, 13))),
          ]

    L += ["## Results: weekly km (given still training)", "",
          "Same metrics on km/week (MAPE on km can be huge for small volumes; the median APE is the "
          "more useful number). Persistence = the 12-week mean stays.", ""]
    for sname in ("pre2020", "new19", "covid"):
        L += [f"### {sname}", "", *table(SHEAD, [srow(lab, summary(res[nm][sname][2])) for nm, lab in (
            ("km", "model (default)"), ("km_persistence", "12-week km stays"), ("km_no_season", "model without season"))])]
    L += ["Note: the km 'APE' is computed on km + 1 (the log scale of the fit), which is close to km for "
          "regular runners.", ""]

    L += ["## Results: still training", "",
          *table(["set", "cases", "share still training", "Brier model", "Brier horizon-only", "log loss model",
                  "log loss horizon-only"],
                 [[s, f"{r['n']:,}", f"{r['rate']:.3f}", f"{r['brier']:.4f}", f"{r['brier0']:.4f}", f"{r['ll']:.4f}",
                   f"{r['ll0']:.4f}"] for s, r in run_res.items()])]
    r = run_res["pre2020"]
    bins = np.quantile(r["pm"], [0, .1, .25, .5, .75, 1])
    cal = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (r["pm"] >= lo) & (r["pm"] <= hi)
        cal.append([f"{lo:.2f}-{hi:.2f}", f"{mask.sum():,}", f"{r['pm'][mask].mean():.3f}", f"{r['y'][mask].mean():.3f}"])
    L += ["Calibration on pre2020:", "", *table(["predicted", "cases", "mean predicted", "observed"], cal)]

    def pin(name, sname="pre2020"):
        return summary(res[name][sname][2])["pinball"]

    def gain(name, ref):
        return (pin(ref) - pin(name)) / pin(ref) * 100

    L += ["## Things tried that did not help much (negative results)", ""]
    L += block("pre2020", "pace on pre2020: extra terms",
               names=("pace", "pace_banister", "pace_demog"))
    bb = dict(zip(["const"] + fits["pace_banister"]["spec"]["loc"], fits["pace_banister"]["b"]))
    bd = dict(zip(["const"] + fits["pace_demog"]["spec"]["loc"], fits["pace_demog"]["b"]))
    L += [f"- **Banister impulse-response.** Fitness and fatigue as exponentially weighted weekly minutes "
          f"(time constants {BANISTER_TAU[0]:g} and {BANISTER_TAU[1]:g} weeks, i.e. 42 and 7 days; training load = "
          "minutes, as there is no heart rate for TRIMP). Adding ln(fatigue/fitness) "
          f"({bb['banister']:+.4f}) and ln fitness ({bb['fitness']:+.4f}) to the pace location improves the "
          f"pre2020 pinball loss by {gain('pace_banister', 'pace'):.1f}%: with weekly totals and a pace that "
          "mixes easy and hard running, the fitness-fatigue balance adds almost nothing to the pace trends. "
          "Not in the model.",
          f"- **Gender and age group.** Men {bd['male']:+.4f}, 18-34 {bd['age18']:+.4f}, 55+ {bd['age55']:+.4f} "
          f"(log pace change); pinball gain {gain('pace_demog', 'pace'):.1f}%. Not worth three more inputs, so "
          "they are accepted only for display. The by-group table shows that women and the 55+ group "
          "ran slightly slower than predicted (bias = median / actual - 1, so negative = predicted too "
          "fast) and that the bands are too wide for women.",
          f"- **Season.** Pace: dropping it costs {-gain('pace_no_season', 'pace'):.1f}% pinball on pre2020 and "
          f"{(pin('pace_no_season', 'covid') - pin('pace', 'covid')) / pin('pace_no_season', 'covid') * 100:.1f}% "
          "on covid. Weekly km: the season terms help on pre2020 "
          f"({-gain('km_no_season', 'km'):.1f}% pinball) but hurt on covid "
          f"({(pin('km', 'covid') - pin('km_no_season', 'covid')) / pin('km_no_season', 'covid') * 100:+.1f}%), "
          "where lockdowns cancelled the spring marathons the 2019 curve expects. Kept, with that caveat.", ""]

    # Tanda
    rows, q, _ = res["pace"]["pre2020"]
    K, Pp = C["tanda_K"][rows], C["tanda_P"][rows]
    t = values_tanda(K, np.where(np.isnan(Pp), np.exp(C['lp_base'][rows]), Pp), p) / 60
    inside = (t >= p.tanda_valid_lo) & (t <= p.tanda_valid_hi)
    L += ["## Tanda (2011) implied marathon time", "",
          "Tanda's formula Pm (s/km) = 17.1 + 140 exp(-0.0053 K) + 0.55 P from mean weekly km K and mean "
          "training pace P over the 8 weeks before a race was fitted on 22 runners (46 marathons, 2:47-3:36). "
          "Tanda & Knechtle (2013) found a standard error of 28 min when applying it to 126 recreational "
          "runners. This dataset has no race results, so the implied times are shown as a literature "
          "translation only. On the pre2020 cases (today's 8 weeks):", "",
          f"- median implied marathon {int(np.nanmedian(t) // 60)}:{int(np.nanmedian(t) % 60):02d}; "
          f"10-90%: {int(np.nanpercentile(t, 10) // 60)}:{int(np.nanpercentile(t, 10) % 60):02d} to "
          f"{int(np.nanpercentile(t, 90) // 60)}:{int(np.nanpercentile(t, 90) % 60):02d};",
          f"- {inside.mean() * 100:.0f}% fall inside the paper's 2:47-3:36 range (the rest are extrapolation).", ""]

    if e2e:
        def bt(r):
            m = r.metrics
            return [r.variant or "default", r.n, f"{m.get('abs_pct_error', float('nan')):.2f}",
                    f"{m.get('in_50', float('nan')):.3f}", f"{m.get('in_80', float('nan')):.3f}",
                    f"{m.get('in_95', float('nan')):.3f}", f"{m.get('km_in_80', float('nan')):.3f}",
                    f"{m.get('brier_running', float('nan')):.4f}"]
        L += ["## End-to-end check (data/backtest.csv through model.py)", "",
              f"{sum(BACKTEST_ROWS.values()):,} test cases ({BACKTEST_ROWS}) written to data/backtest.csv "
              "(weekly km and minutes before the cutoff, as a user would enter them) and run through "
              "`model.predict` with the config.toml defaults: the largest relative difference from the "
              f"vectorised research code is {e2e['worst']:.1e}. `ballmonitor backtest running_progress` "
              "reproduces:", "",
              *table(["variant", "cases", "pace MAPE %", "in 50%", "in 80%", "in 95%", "km in 80%", "Brier running"],
                     [bt(e2e["default"]), bt(e2e["persistence"])])]
        rows_g = []
        for g in ("pre2020", "covid", "new19"):
            m = e2e["default"].groups.get(g, {})
            rows_g.append([g, e2e["default"].group_n.get(g, 0), f"{m.get('abs_pct_error', float('nan')):.2f}",
                           f"{m.get('in_50', float('nan')):.3f}", f"{m.get('in_80', float('nan')):.3f}",
                           f"{m.get('in_95', float('nan')):.3f}", f"{m.get('km_in_80', float('nan')):.3f}",
                           f"{m.get('brier_running', float('nan')):.4f}"])
        L += table(["split (default)", "cases", "pace MAPE %", "in 50%", "in 80%", "in 95%", "km in 80%",
                    "Brier running"], rows_g)

    L += ["## Literature", "",
          "- Afonseca LA, Watanabe RN, Duarte M (2022). A worldwide comparison of long-distance running "
          "training in 2019 and 2020: associated effects of the COVID-19 pandemic. PeerJ 10:e13192, "
          "doi:10.7717/peerj.13192. The dataset paper: descriptive (2020 vs 2019: 3.6% fewer athletes "
          "running, 7.5% less distance, 6.7% less duration). No forecasting study using this dataset was "
          "found.",
          "- Banister EW, Calvert TW, Savage MV, Bach T (1975). A systems model of training for athletic "
          "performance. Aust J Sports Med 7:57-61; Calvert TW et al. (1976), IEEE Trans Syst Man Cybern "
          "SMC-6:94-102. Fitness-fatigue model; tested above as features (no gain). Its usual use needs "
          "performance tests to fit per person, which this data lacks.",
          "- Tanda G (2011). Prediction of marathon performance time on the basis of training indices. "
          "J Hum Sport Exerc 6(3):511-520, doi:10.4100/jhse.2011.63.05. Tanda G, Knechtle B (2013). "
          "Marathon performance in relation to body fat percentage and training indices in recreational "
          "male runners. Open Access J Sports Med 4:141-149, doi:10.2147/OAJSM.S44945.",
          "- Koenker R, Bassett G (1978). Regression quantiles. Econometrica 46:33-50 (median regression "
          "as a linear programme).", ""]
    OUT_MD.write_text("\n".join(L))


def values_tanda(K: np.ndarray, pace: np.ndarray, p: P) -> np.ndarray:
    """Tanda (2011) marathon time in seconds (formula tanda_marathon with the config values)."""
    return p.marathon_km * (p.tanda_a + p.tanda_b * np.exp(-p.tanda_k * K) + p.tanda_c * pace)


if __name__ == "__main__":
    main()
