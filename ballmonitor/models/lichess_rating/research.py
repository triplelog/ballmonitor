"""Fit and test the lichess_rating model.  Writes RESEARCH.md, data/backtest.csv, data/fit.json.

    python -m ballmonitor.models.lichess_rating.research              # needs data/raw/cases.parquet
    python -m ballmonitor.models.lichess_rating.research --write-config   # also copy the fit into config.toml

Data: data/raw/cases.parquet from pipeline.py (Lichess open database, 1 player in 4,
per-player daily totals). Walk-forward: TRAIN = train-split players, cases whose target
date is before SPLIT_DATE; TEST = the other half of the players, cutoffs on or after
SPLIT_DATE. Nothing about test players or test dates is used to fit. RESEARCH.md is
generated — never edit it by hand.

1. Keeps playing: logistic regression of "plays >= 1 rated game in this speed before the
   target date" on activity, idle, experience and ln(horizon / 91).
2. Change if playing: linear quantile regression (pinball loss, linear programme) of
   target - rating at the 2.5 ... 97.5% levels on the dist.FEATURES plus ln(horizon / 91),
   horizons pooled (compared with a separate fit per horizon).
3. Test: the mixture vs two baselines — "no features" (train rates and change quantiles
   per horizon) and "rating stays, typical spread" (train quantiles of the change over all
   cases per horizon) — mean pinball loss, error of the median, coverage of the 50/80/95%
   bands, overall and by horizon, experience and speed.
4. Practice (hindsight): how the change relates to games actually played after the cutoff,
   given everything known at the cutoff — association, not a forecast input.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from sklearn.linear_model import LogisticRegression

from ballmonitor.models.lichess_rating.dist import (
    ACTIVE_FEATURES, FEATURES, HORIZONS, LEVEL_KEYS, LEVELS, mixture_quantile,
)

MODEL_DIR = Path(__file__).resolve().parent
CASES = MODEL_DIR / "data" / "raw" / "cases.parquet"
MANIFEST = MODEL_DIR / "data" / "raw" / "lichess_days" / "manifest.jsonl"
OUT_MD = MODEL_DIR / "RESEARCH.md"
OUT_FIT = MODEL_DIR / "data" / "fit.json"
OUT_BACKTEST = MODEL_DIR / "data" / "backtest.csv"
CONFIG = MODEL_DIR / "config.toml"

SPLIT_DATE = dt.date(2016, 4, 1)
EPOCH = dt.date(2014, 1, 1)
SPEED = "blitz"  # fitted on blitz; other speeds are scored with the blitz fit
FIT_ROWS_ACTIVE = 300_000  # random train rows for the logistic fit
FIT_ROWS_PER_HORIZON = 12_000  # random train rows (playing cases) per horizon for the quantile fit
TEST_ROWS = 60_000  # random test rows scored (all horizons and speeds)
BACKTEST_ROWS = 4_000  # committed test cases (data/backtest.csv)
SEED = 20261118
BAND_LEVELS = {0.5: (2, 4), 0.8: (1, 5), 0.95: (0, 6)}  # interval -> indexes into LEVELS
QR_FEATURES = FEATURES + ("log_horizon",)


def caps_from_config() -> dict[str, float]:
    """Feature caps straight from config.toml (read raw: the fitted block may not exist yet)."""
    import tomllib
    params = tomllib.loads(CONFIG.read_text())["params"]
    return {k: float(params[f"cap_{k}"]["value"]) for k in ("games", "below_peak", "trend", "form")}


def feature_frame(c: pd.DataFrame, caps: dict[str, float]) -> pd.DataFrame:
    """Vectorised dist.features (tests check they agree)."""
    f = pd.DataFrame(index=c.index)
    f["activity"] = np.log1p(c.games_28)
    f["experience"] = np.log1p(c.games_total.clip(upper=caps["games"]))
    f["below_peak"] = ((c.peak - c.rating).clip(lower=0) / 100).clip(upper=caps["below_peak"])
    f["trend"] = ((c.rating - c.rating_91_ago) / 100).clip(-caps["trend"], caps["trend"])
    f["level"] = (c.rating - 1500) / 100
    perf = c.opp_mean_91 + 400 * (2 * c.score_91 / c.games_91.replace(0, np.nan) - 1)
    f["form"] = ((perf - c.rating) / 100).clip(-caps["form"], caps["form"]).fillna(0.0)
    f["idle"] = np.log1p(c.days_since_last)
    f["log_horizon"] = np.log(c.horizon / 91)
    return f


def quantile_lp(X: np.ndarray, y: np.ndarray, tau: float) -> np.ndarray:
    """Linear quantile regression (with intercept) as an LP: min sum tau*u + (1-tau)*v."""
    n, k = X.shape
    A = np.hstack([np.ones((n, 1)), X])
    # variables: beta+ (k+1), beta- (k+1), u (n), v (n)
    from scipy.sparse import eye, hstack, csr_matrix
    Aeq = hstack([csr_matrix(A), csr_matrix(-A), eye(n), -eye(n)]).tocsr()
    cost = np.concatenate([np.zeros(2 * (k + 1)), np.full(n, tau), np.full(n, 1 - tau)])
    res = linprog(cost, A_eq=Aeq, b_eq=y, bounds=(0, None), method="highs")
    if not res.success:
        raise RuntimeError(res.message)
    return res.x[: k + 1] - res.x[k + 1: 2 * (k + 1)]


def pinball(y: np.ndarray, q: np.ndarray, tau: float) -> np.ndarray:
    d = y - q
    return np.maximum(tau * d, (tau - 1) * d)


def predict_quantiles(p: np.ndarray, qa: np.ndarray) -> np.ndarray:
    """Mixture quantiles (n x levels) from p_active (n) and change-if-playing quantiles (n x levels)."""
    out = np.empty_like(qa)
    for i in range(len(p)):
        for j, tau in enumerate(LEVELS):
            out[i, j] = mixture_quantile(float(p[i]), qa[i], tau)
    return out


def score(y: np.ndarray, Q: np.ndarray) -> dict[str, float]:
    m = {"pinball": float(np.mean([pinball(y, Q[:, j], t).mean() for j, t in enumerate(LEVELS)])),
         "median_abs_err": float(np.abs(y - Q[:, 3]).mean()),
         "median_bias": float((Q[:, 3] - y).mean())}
    for lvl, (lo, hi) in BAND_LEVELS.items():
        m[f"cov{int(lvl * 100)}"] = float(((Q[:, lo] <= y) & (y <= Q[:, hi])).mean())
    return m


def fmt_table(rows: list[dict], cols: list[tuple[str, str, str]]) -> str:
    head = "| " + " | ".join(c[1] for c in cols) + " |"
    sep = "|" + "|".join("---:" if c[2] != "s" else "---" for c in cols) + "|"
    body = []
    for r in rows:
        cells = []
        for key, _, f in cols:
            v = r[key]
            cells.append(str(v) if f == "s" else format(v, f))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep, *body])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-config", action="store_true", help="copy the fitted coefficients into config.toml")
    ap.add_argument("--split", default=str(SPLIT_DATE), help="walk-forward split date (YYYY-MM-DD)")
    args = ap.parse_args(argv)
    split_date = dt.date.fromisoformat(args.split)
    rng = np.random.default_rng(SEED)
    caps = caps_from_config()
    c = pd.read_parquet(CASES)
    c = c[c.speed.isin(["blitz", "bullet", "classical"])].reset_index(drop=True)
    c["change"] = c.target - c.rating
    c["active"] = c.future_games > 0
    F = feature_frame(c, caps)
    split = (split_date - EPOCH).days
    is_train = (c.split_player == "train") & (c.cutoff + c.horizon < split)
    is_test = (c.split_player == "test") & (c.cutoff >= split)
    blitz = c.speed == SPEED
    manifest = {}
    for line in MANIFEST.read_text().splitlines():
        m = json.loads(line)
        manifest[m["month"]] = m
    months = sorted(manifest)
    n_games = sum(manifest[m]["games"] for m in months)
    cutoff_dates = lambda mask: (pd.Timestamp(EPOCH) + pd.to_timedelta(c.cutoff[mask], unit="D"))

    # 1. Keeps playing (logistic, blitz train).
    tr_idx = np.where(is_train & blitz)[0]
    fit_idx = rng.choice(tr_idx, min(FIT_ROWS_ACTIVE, len(tr_idx)), replace=False)
    lr = LogisticRegression(C=1e6, max_iter=2000).fit(F.iloc[fit_idx][list(ACTIVE_FEATURES)], c.active.iloc[fit_idx])
    active_coef = {"intercept": float(lr.intercept_[0]), **dict(zip(ACTIVE_FEATURES, map(float, lr.coef_[0])))}

    # 2. Change if playing (pooled quantile regression, blitz train, equal rows per horizon).
    act_rows = []
    for h in HORIZONS:
        ii = np.where(is_train & blitz & c.active & (c.horizon == h))[0]
        act_rows.append(rng.choice(ii, min(FIT_ROWS_PER_HORIZON, len(ii)), replace=False))
    act_rows = np.concatenate(act_rows)
    X = F.iloc[act_rows][list(QR_FEATURES)].to_numpy()
    y = c.change.iloc[act_rows].to_numpy(dtype=float)
    # Pool drift: the whole rating pool inflates or deflates for months at a time (RESEARCH.md
    # section 2b), which no single player's history can predict. Each cutoff quarter gets its own
    # effect in the fit, and the model uses the median quarter's effect (a typical quarter),
    # not the train-period average.
    quarters = (pd.Timestamp(EPOCH) + pd.to_timedelta(c.cutoff.iloc[act_rows], unit="D")).dt.to_period("Q").astype(str)
    q_names = sorted(quarters.unique())
    D = np.column_stack([(quarters == q).to_numpy(dtype=float) for q in q_names[1:]])
    change_coef, drift = {}, {}
    for key, tau in zip(LEVEL_KEYS, LEVELS):
        b = quantile_lp(np.column_stack([X, D]), y, tau)
        k = len(QR_FEATURES)
        effects = np.concatenate([[0.0], b[k + 1:]])
        typical = float(np.median(effects))
        drift[key] = {q: float(e - typical) for q, e in zip(q_names, effects)}
        change_coef[key] = {"intercept": float(b[0]) + typical, **dict(zip(QR_FEATURES, map(float, b[1:k + 1])))}
    # Per-horizon fit (comparison only).
    per_h = {}
    for h in HORIZONS:
        ii = np.where(is_train & blitz & c.active & (c.horizon == h))[0]
        ii = rng.choice(ii, min(FIT_ROWS_PER_HORIZON, len(ii)), replace=False)
        Xh = F.iloc[ii][list(FEATURES)].to_numpy()
        yh = c.change.iloc[ii].to_numpy(dtype=float)
        per_h[h] = [quantile_lp(Xh, yh, tau) for tau in LEVELS]

    # 3. Test.
    te_idx = np.where(is_test)[0]
    te_idx = np.sort(rng.choice(te_idx, min(TEST_ROWS, len(te_idx)), replace=False))
    T = c.iloc[te_idx].reset_index(drop=True)
    FT = F.iloc[te_idx].reset_index(drop=True)
    yt = T.change.to_numpy(dtype=float)
    z = active_coef["intercept"] + sum(active_coef[n] * FT[n] for n in ACTIVE_FEATURES)
    p_model = 1 / (1 + np.exp(-z.to_numpy()))
    XT = FT[list(QR_FEATURES)].to_numpy()
    qa_model = np.column_stack([change_coef[k]["intercept"] + XT @ np.array([change_coef[k][n] for n in QR_FEATURES])
                                for k in LEVEL_KEYS])
    qa_perh = np.zeros_like(qa_model)
    XTh = FT[list(FEATURES)].to_numpy()
    for h in HORIZONS:
        m = (T.horizon == h).to_numpy()
        qa_perh[m] = np.column_stack([b[0] + XTh[m] @ b[1:] for b in per_h[h]])
    # Baselines from train (blitz).
    base_p, base_qa, stay_q = {}, {}, {}
    for h in HORIZONS:
        mh = is_train & blitz & (c.horizon == h)
        base_p[h] = float(c.active[mh].mean())
        base_qa[h] = np.quantile(c.change[mh & c.active], LEVELS)
        stay_q[h] = np.quantile(c.change[mh], LEVELS)
    p_base = T.horizon.map(base_p).to_numpy()
    qa_base = np.vstack([base_qa[h] for h in T.horizon])
    Q_model = predict_quantiles(p_model, qa_model)
    Q_perh = predict_quantiles(p_model, qa_perh)
    Q_base = predict_quantiles(p_base, qa_base)
    Q_stay = np.vstack([stay_q[h] for h in T.horizon])
    methods = {"model": Q_model, "model, separate fit per horizon": Q_perh,
               "no features (train rates and spreads per horizon)": Q_base,
               "rating stays, typical spread": Q_stay}

    def rows_for(mask_fn, label_fn, groups):
        out = []
        for g in groups:
            m = mask_fn(g)
            if m.sum() < 100:
                continue
            for name, Q in methods.items():
                if name.startswith("model, separate") and label_fn is not None and False:
                    continue
                r = score(yt[m], Q[m])
                out.append({"group": label_fn(g), "method": name, "n": int(m.sum()), **r})
        return out

    is_b = (T.speed == SPEED).to_numpy()
    overall = rows_for(lambda g: is_b, lambda g: "blitz, all horizons", [0])
    by_h = rows_for(lambda h: is_b & (T.horizon == h).to_numpy(), lambda h: f"blitz, {h} days", HORIZONS)
    exp_bins = [(0, 50, "under 50 games"), (50, 500, "50-499 games"), (500, 10**9, "500+ games")]
    by_exp = rows_for(lambda b: is_b & (T.games_total >= b[0]).to_numpy() & (T.games_total < b[1]).to_numpy(),
                      lambda b: f"blitz, {b[2]}", exp_bins)
    by_speed = rows_for(lambda s: (T.speed == s).to_numpy(), lambda s: f"{s} (blitz fit)", ["bullet", "classical"])

    # Calibration of p_active (blitz test).
    pa = pd.DataFrame({"p": p_model[is_b], "a": T.active[is_b].to_numpy()})
    pa["bin"] = pd.cut(pa.p, [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0])
    calib = pa.groupby("bin", observed=True).agg(n=("a", "size"), predicted=("p", "mean"), actual=("a", "mean")).reset_index()
    brier = float(((pa.p - pa.a) ** 2).mean())
    brier_base = float(((p_base[is_b] - T.active[is_b].to_numpy()) ** 2).mean())

    # 4. Practice (hindsight): median change if playing vs future games per week, given the
    # same features — a quantile regression with an extra ln(1 + future games/week) term.
    fut = np.log1p(c.future_games.iloc[act_rows].to_numpy() / (c.horizon.iloc[act_rows].to_numpy() / 7))
    b_fut = quantile_lp(np.column_stack([X, fut]), y, 0.5)
    practice_coef = float(b_fut[-1])
    prac = []
    for gpw in (1, 3, 7, 15, 30):
        prac.append({"gpw": gpw, "effect": practice_coef * (math.log1p(gpw) - math.log1p(3))})

    # Backtest CSV (test cases, blitz + other speeds), committed.
    bt_idx = np.sort(rng.choice(len(T), min(BACKTEST_ROWS, len(T)), replace=False))
    B = T.iloc[bt_idx]
    bt = pd.DataFrame({
        "cutoff_date": (pd.Timestamp(EPOCH) + pd.to_timedelta(B.cutoff, unit="D")).dt.date.astype(str),
        "horizon_days": B.horizon, "speed": B.speed,
        "rating": B.rating, "games_total": B.games_total, "games_28": B.games_28,
        "days_since_last": B.days_since_last, "peak": B.peak, "rating_91_ago": B.rating_91_ago,
        "games_91": B.games_91, "score_91": B.score_91, "opp_mean_91": B.opp_mean_91.round(1),
        "actual_rating": B.target, "played_after": B.active.astype(int),
    })
    bt.to_csv(OUT_BACKTEST, index=False)

    fit = {"generated_by": "research.py", "split_date": str(split_date), "speed": SPEED,
           "active": active_coef, "change": change_coef, "quarter_effects": drift, "practice_coef_median": practice_coef}
    OUT_FIT.write_text(json.dumps(fit, indent=1) + "\n")
    if args.write_config:
        write_config(fit)

    # ---- RESEARCH.md
    cols = [("group", "cases", "s"), ("method", "method", "s"), ("n", "n", "d"), ("pinball", "mean pinball", ".2f"),
            ("median_abs_err", "median abs err", ".1f"), ("median_bias", "median bias", "+.1f"),
            ("cov50", "50% band", ".1%"), ("cov80", "80% band", ".1%"), ("cov95", "95% band", ".1%")]
    n_players = c.player.nunique()
    tr_dates, te_dates = cutoff_dates(is_train & blitz), cutoff_dates(is_test & blitz)
    md = [
        "# lichess_rating: walk-forward study",
        "",
        "_Generated by `research.py` — do not edit by hand._",
        "",
        f"Data: the Lichess open database (database.lichess.org, CC0), every rated standard game {months[0]} – "
        f"{months[-1]} ({n_games:,} games), reduced by `download.py` to per-player daily totals for a fixed "
        f"1-in-4 sample of players (hash of the name). `pipeline.py` turns them into {len(c):,} cases "
        f"({n_players:,} players; blitz, bullet and classical) — one per player, speed, monthly cutoff and horizon "
        f"(30/91/182/365 days) for players who played that speed in the 91 days before the cutoff.",
        "",
        f"Split: **train** = half the players (hash), cases whose target date is before {split_date} "
        f"(cutoffs {tr_dates.min().date()} – {tr_dates.max().date()}); **test** = the other half, cutoffs from {split_date} "
        f"(to {te_dates.max().date()}). Fitted on blitz train cases only; {len(T):,} random test cases scored. "
        f"Test targets span about 17 months, so the 365-day results rest on about one independent year; "
        f"cases of one player at different cutoffs overlap and are not independent.",
        "",
        "## 1. Chance of playing again before the target date",
        "",
        "Logistic regression on " + ", ".join(f"`{n}`" for n in ACTIVE_FEATURES) + " (see `dist.features`).",
        "",
        "| term | coefficient |", "|---|---:|",
        *[f"| {k} | {v:+.3f} |" for k, v in active_coef.items()],
        "",
        f"Test (blitz): Brier {brier:.4f} vs {brier_base:.4f} for the per-horizon train rate.",
        "",
        fmt_table(calib.assign(bin=calib.bin.astype(str)).to_dict("records"),
                  [("bin", "predicted range", "s"), ("n", "n", "d"), ("predicted", "mean predicted", ".3f"),
                   ("actual", "share who played", ".3f")]),
        "",
        "## 2. Change if they keep playing",
        "",
        "Linear quantile regression, horizons pooled with `log_horizon` as a feature "
        f"({FIT_ROWS_PER_HORIZON:,} train cases per horizon). Coefficients (rating points per unit of the feature):",
        "",
        "| level | " + " | ".join(("intercept",) + QR_FEATURES) + " |",
        "|---|" + "---:|" * (len(QR_FEATURES) + 1),
        *[f"| {k} | " + " | ".join(f"{change_coef[k][n]:+.1f}" for n in ("intercept",) + QR_FEATURES) + " |"
          for k in LEVEL_KEYS],
        "",
        "### 2b. Pool drift (quarter effects)",
        "",
        "Median change if playing in each cutoff quarter, relative to the typical (median) train "
        "quarter, given the features — a shift of the whole rating pool that no one player's history "
        "predicts. The model uses the typical quarter; the train quarters below show how far a real "
        "quarter can be from it.",
        "",
        "| cutoff quarter | effect on the median (points) |", "|---|---:|",
        *[f"| {q} | {e:+.1f} |" for q, e in drift["q50"].items()],
        "",
        "## 3. Test results",
        "",
        "Change = rating at the target date minus rating at the cutoff (rating points). Mean pinball = average "
        "quantile loss over the 7 levels (lower is better). Bands are the model's 50/80/95% intervals.",
        "",
        fmt_table(overall + by_h, cols),
        "",
        "By experience (rated games in this speed so far; counted from 2014-01, so long-time players "
        "who started before then are undercounted):",
        "",
        fmt_table(by_exp, cols),
        "",
        "Other speeds, scored with the blitz fit:",
        "",
        fmt_table(by_speed, cols),
        "",
        "## 4. Practice (hindsight, association only)",
        "",
        "Median change if playing, with ln(1 + games per week actually played after the cutoff) added "
        f"to the train fit: coefficient {practice_coef:+.1f} points per unit. Relative to 3 games a week:",
        "",
        "| games per week after the cutoff | median change vs 3/week |", "|---:|---:|",
        *[f"| {r['gpw']} | {r['effect']:+.0f} |" for r in prac],
        "",
        "This uses the future, so it is not a forecast input. It is also not proof that playing more causes "
        "improvement: players who are improving may simply play more.",
        "",
    ]
    OUT_MD.write_text("\n".join(md))
    print(f"wrote {OUT_MD.name}, {OUT_FIT.name}, {OUT_BACKTEST.name}")
    for r in overall + by_h:
        print(f"{r['group']:24s} {r['method'][:30]:30s} pin {r['pinball']:.2f} mae {r['median_abs_err']:.1f} "
              f"cov {r['cov50']:.2f}/{r['cov80']:.2f}/{r['cov95']:.2f}")


FITTED_BEGIN = "# ---- BEGIN FITTED (research.py --write-config; do not edit by hand) ----"
FITTED_END = "# ---- END FITTED ----"


def write_config(fit: dict) -> None:
    """Replace the fitted block of config.toml with the coefficients in `fit`."""
    lines = [FITTED_BEGIN]
    src = (f'"research.py (RESEARCH.md): fitted on blitz train players, targets before {fit["split_date"]}."')
    for name, v in fit["active"].items():
        lines += [f"[params.active_{name}]", f"value = {v:.4f}",
                  f'description = "Keeps playing (logistic): coefficient on {name}."', f"source = {src}", ""]
    level_of = dict(zip(LEVEL_KEYS, LEVELS))
    for key, coefs in fit["change"].items():
        for name, v in coefs.items():
            lines += [f"[params.change_{key}_{name}]", f"value = {v:.2f}",
                      f'description = "Change if playing, {level_of[key] * 100:g}% quantile: rating points per unit of {name}."',
                      f"source = {src}", ""]
    lines.append(FITTED_END)
    text = CONFIG.read_text()
    block = re.compile(re.escape(FITTED_BEGIN) + ".*?" + re.escape(FITTED_END), re.S)
    if not block.search(text):
        raise RuntimeError("config.toml has no fitted block markers")
    CONFIG.write_text(block.sub(lambda _: "\n".join(lines), text))


if __name__ == "__main__":
    main()
