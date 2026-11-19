"""Walk-forward study of strength progress on the fit20 cohort.  Writes RESEARCH.md.

    python -m ballmonitor.models.strength_progress.download   # once: data/raw/fit20_final.csv
    python -m ballmonitor.models.strength_progress.research   # ~1 min (cached cases); needs pandas, numpy, scipy

Data: fit20 training records (Steele et al. 2022, OSF jn6ay, CC BY 4.0): one set to failure per
machine per session (slow tempo), leg press / chest press / pulldown, 2010-2016 (the paper's
window: sensor equipment changed loads from 2017). Cleaning follows the paper's R code
(weight > 0, leg press <= 200 kg, chest press and pulldown < 116 kg) plus durations 30-300 s
and the best set per member, machine and day.

Cases: on the 1st of every month ("today"), every member-machine with a session in the last
`band_gap_cap_days` days gets one horizon drawn from 4/8/13/26/39/52 weeks; the actual is the
load at the member's session on that machine nearest today + horizon (within 14 days, so
targets are only observed for people still training then). Features use only sessions
strictly before today, with the same definitions as progress.py.

Splits (people and time both separate): members are split train/test by an md5 hash of the
member id; fold A trains on train members' cases whose *target* is before 2015-07-01 and
tests on test members' cases from cutoffs 2015-07-01..2016-11 (targets through 2016);
fold B (an earlier check) trains on targets before 2014-07-01 and tests on cutoffs
2014-07-01..2015-06. Everything is fitted on train only and scored once on test.
RESEARCH.md is generated: never edit it by hand.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

from ballmonitor.core import registry
from ballmonitor.core.backtest import run_backtest, load_rows

MODEL_DIR = Path(__file__).resolve().parent
RAW = MODEL_DIR / "data" / "raw"
RAW_CSV = RAW / "fit20_final.csv"
SESSIONS_CACHE = RAW / "sessions.parquet"
CASES_CACHE = RAW / "cases.parquet"
BACKTEST = MODEL_DIR / "data" / "backtest.csv"
FIT_JSON = MODEL_DIR / "data" / "fit.json"
OUT_MD = MODEL_DIR / "RESEARCH.md"

EPOCH = pd.Timestamp("2010-01-01")
END = pd.Timestamp("2017-01-01")
MACHINES = {1001: ("Leg press", 200.0, True), 3001: ("Chest press", 116.0, False),
            5001: ("Pulldown", 116.0, False)}  # name, max load, max inclusive (paper's R code)
DUR_RANGE = (30.0, 300.0)
HORIZONS = (4, 8, 13, 26, 39, 52)
TOL_DAYS = 14
LOG_WEEKS = 12          # weeks of log written per backtest row (= trend window)
FOLDS = {
    "A": dict(train_target_before="2015-07-01", test_from="2015-07-01", test_to="2016-12-01"),
    "B": dict(train_target_before="2014-07-01", test_from="2014-07-01", test_to="2015-06-30"),
}
TAU_GRID = (4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 20, 25, 30, 40)
Q = (0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975)
QKEYS = ("p025", "p10", "p25", "p50", "p75", "p90", "p975")
BAND_FEATS = ("base", "horizon", "novice", "irregular", "gap")
BOOT = 1000
SEED = 20261118


def day(ts) -> np.ndarray:
    return ((pd.to_datetime(ts) - EPOCH) / pd.Timedelta(days=1)).astype(int)


def member_is_test(m) -> bool:
    return int(hashlib.md5(str(int(m)).encode()).hexdigest(), 16) % 2 == 1


# ── data ────────────────────────────────────────────────────────────────────

def load_sessions() -> pd.DataFrame:
    if SESSIONS_CACHE.exists():
        return pd.read_parquet(SESSIONS_CACHE)
    if not RAW_CSV.exists():
        raise SystemExit(f"missing {RAW_CSV}; run python -m ballmonitor.models.strength_progress.download")
    df = pd.read_csv(RAW_CSV, usecols=["memberId", "sessionNumber", "sessionDate", "birthMonth", "Weight", "machineId",
                                       "exerciseWeight", "exerciseDuration", "Sex"])
    df = df.dropna(subset=["sessionDate", "machineId", "exerciseWeight"])
    df["date"] = pd.to_datetime(df.sessionDate.str[:10], errors="coerce")
    df = df[(df.date >= EPOCH) & (df.date < END) & (df.exerciseWeight > 0)]
    df["machineId"] = df.machineId.astype(int)
    keep = np.zeros(len(df), bool)
    for m, (_, mx, incl) in MACHINES.items():
        sel = (df.machineId == m) & ((df.exerciseWeight <= mx) if incl else (df.exerciseWeight < mx))
        keep |= sel.values
    df = df[keep & df.exerciseDuration.between(*DUR_RANGE).values]
    # member ids are published rounded to 7 significant digits (e.g. 5.208429e+15); drop the few
    # ids whose session numbers map to more than one date (two people sharing a rounded id)
    clash = df.groupby(["memberId", "sessionNumber", "machineId"]).date.nunique()
    bad = clash[clash > 1].index.get_level_values(0).unique()
    df = df[~df.memberId.isin(bad)]
    df = df.sort_values("exerciseWeight").groupby(["memberId", "machineId", "date"], as_index=False).last()
    df = df.sort_values(["memberId", "machineId", "date"]).reset_index(drop=True)
    df["d"] = day(df.date)
    df = df.drop(columns=["sessionDate"])
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SESSIONS_CACHE)
    return df


def build_cases(df: pd.DataFrame, p) -> pd.DataFrame:
    """One row per member x machine x monthly cutoff (one random horizon each)."""
    if CASES_CACHE.exists():
        return pd.read_parquet(CASES_CACHE)
    rng = np.random.default_rng(SEED)
    cutoffs = day(pd.date_range("2011-01-01", "2016-12-01", freq="MS"))
    end = int(day([END])[0])
    win, tw = p.consistency_window_weeks * 7, p.trend_window_weeks * 7
    rows = []
    for (mem, mach), g in df.groupby(["memberId", "machineId"], sort=False):
        d = g.d.values
        lw = np.log(g.exerciseWeight.values)
        for c in cutoffs:
            k = int(np.searchsorted(d, c))  # sessions strictly before c: [0, k)
            if k == 0 or c - d[k - 1] > p.band_gap_cap_days:
                continue
            h = HORIZONS[rng.integers(len(HORIZONS))]
            t = c + 7 * h
            if t + TOL_DAYS >= end:
                continue
            j0, j1 = np.searchsorted(d, t - TOL_DAYS), np.searchsorted(d, t + TOL_DAYS, side="right")
            if j1 <= j0:
                continue
            j = j0 + int(np.argmin(np.abs(d[j0:j1] - t)))
            past = d[:k]
            weeks = (c - d[0]) / 7
            n_win = int(np.sum(c - past < win))
            sel = c - past < tw
            xs, ys = (past[sel] - c) / 7, lw[:k][sel]
            slope = 0.0
            if len(xs) >= p.trend_min_sessions and xs.max() - xs.min() >= p.trend_min_span_weeks:
                slope = float(np.polyfit(xs, ys, 1)[0])
            rows.append((mem, mach, c, (d[j] - c) / 7, d[0], k, weeks, n_win / min(p.consistency_window_weeks, max(weeks, 1.0)),
                         c - d[k - 1], slope, lw[k - 1], lw[j], g.exerciseDuration.values[j],
                         g.Weight.values[k - 1], g.birthMonth.iloc[0], g.Sex.iloc[0]))
    cols = ["member", "machine", "cut", "h", "first_d", "n", "weeks", "freq", "gap", "slope", "lw0", "lw1",
            "dur1", "bw", "birth", "sex"]
    X = pd.DataFrame(rows, columns=cols)
    X["test_member"] = X.member.map(member_is_test)
    X["tgt_d"] = X.cut + (X.h * 7).round().astype(int)
    X["y"] = X.lw1 - X.lw0
    birth = pd.to_datetime(X.birth.astype("string") + "-01", errors="coerce")
    X["age"] = ((EPOCH + pd.to_timedelta(X.cut, unit="D")) - birth).dt.days / 365.25
    X.loc[(X.age < 16) | (X.age > 95), "age"] = np.nan
    X.to_parquet(CASES_CACHE)
    return X


def folds(X: pd.DataFrame) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    out = {}
    for name, f in FOLDS.items():
        tb, t0, t1 = (int(day([f[k]])[0]) for k in ("train_target_before", "test_from", "test_to"))
        tr = X[(~X.test_member) & (X.tgt_d < tb)]
        te = X[X.test_member & (X.cut >= t0) & (X.cut <= t1)]
        out[name] = (tr, te)
    return out


# ── fitting ─────────────────────────────────────────────────────────────────

def wmedian_ratio(x: np.ndarray, y: np.ndarray) -> float:
    """argmin_A sum |y - A x| = weighted median of y/x with weights |x|."""
    m = np.abs(x) > 1e-12
    r, w = y[m] / x[m], np.abs(x[m])
    o = np.argsort(r)
    cw = np.cumsum(w[o])
    return float(r[o][np.searchsorted(cw, cw[-1] / 2)])


def qreg(F: np.ndarray, y: np.ndarray, tau: float) -> np.ndarray:
    """Linear quantile regression: L-BFGS on a softplus-smoothed pinball loss (eps 0.02 -> 0.001),
    keeping the stage with the lowest exact pinball loss."""
    n, k = F.shape

    def f(b, eps):
        u = y - F @ b
        z = -u / eps
        loss = tau * u + eps * np.logaddexp(0, z)
        g = -(tau - expit(z))
        return loss.mean(), F.T @ g / n

    def pinball(b):
        u = y - F @ b
        return float(np.mean(np.maximum(tau * u, (tau - 1) * u)))

    b = np.zeros(k)
    b[0] = np.quantile(y, tau)
    best = (pinball(b), b)
    for eps in (0.02, 0.005, 0.001):
        b = minimize(f, best[1], args=(eps,), jac=True, method="L-BFGS-B").x
        if pinball(b) < best[0]:
            best = (pinball(b), b)
    return best[1]


def pace(D, alpha, p):
    return np.clip(D.freq.values / p.consistency_ref_per_week, p.pace_min, p.pace_max) ** alpha


def x_weeks_exp(D, tau, alpha=0.0, p=None):
    w0 = D.weeks.values
    m = 1.0 if alpha == 0 else pace(D, alpha, p)
    return np.exp(-w0 / tau) - np.exp(-(w0 + D.h.values * m) / tau)


def x_sessions_exp(D, tau):
    n0 = D.n.values
    return np.exp(-n0 / tau) - np.exp(-(n0 + D.freq.values * D.h.values) / tau)


def x_linlog(D):
    return np.log((D.weeks.values + D.h.values + 1) / (D.weeks.values + 1))


def fit_curve(tr, xfun):
    """Grid tau, closed-form A; returns (tau, A, train MAE)."""
    best = None
    for tau in TAU_GRID:
        x = xfun(tr, tau)
        a = wmedian_ratio(x, tr.y.values)
        m = float(np.mean(np.abs(tr.y.values - a * x)))
        if best is None or m < best[2]:
            best = (tau, a, m)
    return best


def candidates(tr, te, p):
    """Point predictions (log gain) of every candidate, fitted on tr, for te."""
    out = {}
    out["no change (load stays the same)"] = (np.zeros(len(te)), "-")
    out["recent trend x horizon"] = (te.slope.values * te.h.values, "-")
    out["recent trend, capped at 4 weeks"] = (te.slope.values * np.minimum(te.h.values, 4), "-")
    b = wmedian_ratio(x_linlog(tr), tr.y.values)
    out["linear-log in weeks (paper's form)"] = (b * x_linlog(te), f"b = {b:.4f}")
    tau, a, _ = fit_curve(tr, lambda D, t: x_weeks_exp(D, t))
    out["DEFAULT saturating curve in weeks"] = (a * x_weeks_exp(te, tau), f"A = {a:.4f}, tau = {tau} wk")
    ts, as_, _ = fit_curve(tr, x_sessions_exp)
    out["saturating curve in sessions (consistency)"] = (as_ * x_sessions_exp(te, ts), f"A = {as_:.4f}, tau = {ts} sessions")
    for alpha in (0.5, 1.0):
        tc, ac, _ = fit_curve(tr, lambda D, t: x_weeks_exp(D, t, alpha, p))
        out[f"curve in weeks, clock x pace^{alpha:g}"] = (ac * x_weeks_exp(te, tc, alpha, p), f"A = {ac:.4f}, tau = {tc} wk")
    return out, dict(tau=tau, A=a, linlog_b=b, sessions_tau=ts, sessions_A=as_)


def band_matrix(D, tau, p):
    return np.column_stack([
        np.ones(len(D)),
        np.sqrt(np.clip(D.h.values, 0, p.max_horizon_weeks) / 52),
        np.exp(-D.weeks.values / tau),
        np.clip(1 - D.freq.values / p.consistency_ref_per_week, 0, 1),
        np.minimum(D.gap.values, p.band_gap_cap_days) / p.band_gap_cap_days,
    ])


def band_scores(e: np.ndarray, P: np.ndarray) -> dict[str, float]:
    out = {"pinball": float(np.mean([np.mean(np.maximum(q * (e - P[:, i]), (q - 1) * (e - P[:, i])))
                                     for i, q in enumerate(Q)]) * 100)}
    for lo, hi, lev in ((2, 4, 50), (1, 5, 80), (0, 6, 95)):
        out[f"in_{lev}"] = float(np.mean((e >= P[:, lo]) & (e <= P[:, hi])) * 100)
    return out


def boot_diff(te: pd.DataFrame, a: np.ndarray, b: np.ndarray, rng) -> tuple[float, float]:
    """95% member-cluster bootstrap interval of mean(|a|) - mean(|b|) (percentage points)."""
    codes, _ = pd.factorize(te.member)
    da, db = np.abs(a), np.abs(b)
    sa, sb, cnt = (np.bincount(codes, w) for w in (da, db, np.ones(len(da))))
    k = len(cnt)
    diffs = []
    for _ in range(BOOT):
        pick = np.bincount(rng.integers(0, k, k), minlength=k)
        diffs.append((pick @ sa) / (pick @ cnt) - (pick @ sb) / (pick @ cnt))
    lo, hi = np.percentile(diffs, [2.5, 97.5]) * 100
    return float(lo), float(hi)


# ── backtest file ───────────────────────────────────────────────────────────

def write_backtest(te: pd.DataFrame, sessions: pd.DataFrame) -> int:
    """One random test case per test member (fold A), with its last 12 weeks of log."""
    rng = np.random.default_rng(SEED + 1)
    pick = te.groupby("member").apply(lambda g: g.index[rng.integers(len(g))], include_groups=False).values
    cases = te.loc[np.sort(pick)]
    by = {k: g for k, g in sessions.groupby(["memberId", "machineId"], sort=False)}
    fields = ["case_id", "member_id", "exercise", "today", "target_date", "horizon_weeks", "training_since",
              "sex", "age", "log", "actual_weight", "actual_duration", "split"]
    BACKTEST.parent.mkdir(parents=True, exist_ok=True)
    with open(BACKTEST, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        for i, r in enumerate(cases.itertuples(), 1):
            g = by[(r.member, r.machine)]
            sel = (g.d < r.cut) & (r.cut - g.d < LOG_WEEKS * 7)
            log = ";".join(f"{(EPOCH + pd.Timedelta(days=int(dd))).date()}:{wt:g}:{du:g}"
                           for dd, wt, du in zip(g.d[sel], g.exerciseWeight[sel], g.exerciseDuration[sel]))
            to_date = lambda dd: (EPOCH + pd.Timedelta(days=int(dd))).date().isoformat()
            tgt = g[g.d == r.tgt_d].iloc[0]
            w.writerow([i, int(r.member), MACHINES[int(r.machine)][0], to_date(r.cut), to_date(r.tgt_d),
                        f"{r.h:.2f}", to_date(r.first_d), {"MALE": "M", "FEMALE": "F"}.get(r.sex, ""),
                        "" if pd.isna(r.age) else int(r.age), log, f"{tgt.exerciseWeight:g}",
                        f"{tgt.exerciseDuration:g}", "test"])
    return len(cases)


def end_to_end(variants=(None, "no_gain", "recent_trend", "linear_log", "consistency")) -> dict:
    rows = load_rows(BACKTEST)
    out = {}
    for v in variants:
        model = registry.load_model("strength_progress", v)
        res = run_backtest(model, rows)
        out[v or "default"] = {"n": res.n, **{k: float(x) for k, x in res.metrics.items()},
                               "groups": {g: {k: float(x) for k, x in m.items()} for g, m in res.groups.items()},
                               "group_n": dict(res.group_n)}
    return out


# ── report ──────────────────────────────────────────────────────────────────

def md_table(header, rows) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def main() -> None:
    p = registry.load_model("strength_progress").params
    sessions = load_sessions()
    X = build_cases(sessions, p)
    rng = np.random.default_rng(SEED)
    F = folds(X)
    md = ["# strength_progress — research (generated by research.py; do not edit)", ""]
    md += [
        "Question: given a lifter's log up to today, what will they lift at a future date?",
        "",
        "## Data",
        "",
        f"fit20 training records (Steele et al. 2022; OSF jn6ay, CC BY 4.0): {len(sessions):,} cleaned "
        f"member-machine-days from {sessions.memberId.nunique():,} members, "
        f"{sessions.date.min().date()} to {sessions.date.max().date()} (the paper's window). "
        "One protocol only: one slow set to momentary failure per machine, about once a week, "
        "supervised, in fit20 studios (NL/DE). Loads are machine kg, so every number below is "
        "a *relative* change of one person's load on one machine (log ratio), never a "
        "comparison across machines. Member ids are published rounded to 7 significant digits; "
        "ids whose session numbers point to two different dates (two people sharing an id) "
        "are dropped.",
        "",
        f"Cases: {len(X):,} (member x machine x monthly cutoff, one random horizon of "
        f"{'/'.join(map(str, HORIZONS))} weeks each; actual = load at the session nearest "
        f"the target date, within {TOL_DAYS} days). Targets exist only for people still "
        "training then, so every result is *conditional on still training at the target "
        "date* (survivorship, see weaknesses).",
        "",
        md_table(["fold", "train cases", "train members", "test cases", "test members", "test cutoffs (months)"],
                 [[k, f"{len(a):,}", f"{a.member.nunique():,}", f"{len(b):,}", f"{b.member.nunique():,}",
                   b.cut.nunique()] for k, (a, b) in F.items()]),
        "",
        "Train and test never share a member (md5 hash split) and training targets end before "
        "the first test cutoff. Independent periods: fold A tests 17 monthly cutoffs "
        "(2015-07..2016-11) and fold B 12 (2014-07..2015-06), i.e. **two non-overlapping "
        "test windows of 12-18 months**; within a window horizons overlap, so cutoffs are not "
        "independent of each other. Intervals below are member-cluster bootstraps.",
        "",
    ]
    fit = {}
    md += ["## 1. Point prediction (median of the log change)", "",
           "Each candidate is fitted on train by least absolute deviation (closed-form A for a "
           "grid of tau) and scored once on test. Metric: mean |ln(actual / predicted)| in % "
           "(about the mean absolute % error).", ""]
    for name, (tr, te) in F.items():
        preds, f = candidates(tr, te, p)
        fit[f"fold_{name}"] = f
        base = preds["no change (load stays the same)"][0]
        rows = []
        for cname, (pr, desc) in preds.items():
            err = te.y.values - pr
            ci = boot_diff(te, err, te.y.values - base, rng) if cname != "no change (load stays the same)" else None
            rows.append([cname, desc, f"{np.mean(np.abs(err)) * 100:.2f}", f"{np.mean(-err) * 100:+.2f}",
                         "-" if ci is None else f"{np.mean(np.abs(err)) * 100 - np.mean(np.abs(te.y.values)) * 100:+.2f} [{ci[0]:+.2f}, {ci[1]:+.2f}]"])
        d_sess = preds["saturating curve in sessions (consistency)"][0]
        d_def = preds["DEFAULT saturating curve in weeks"][0]
        ci = boot_diff(te, te.y.values - d_sess, te.y.values - d_def, rng)
        f["sessions_vs_default"] = [float(np.mean(np.abs(te.y.values - d_sess)) - np.mean(np.abs(te.y.values - d_def))) * 100, *ci]
        md += [f"**Fold {name}** ({len(te):,} test cases, {te.member.nunique():,} members)", "",
               md_table(["method", "fitted on train", "MAE %", "bias % (+ = too high)", "vs no change [95% CI]"], rows), ""]
    trA, teA = F["A"]
    tau, A = fit["fold_A"]["tau"], fit["fold_A"]["A"]
    pA = A * x_weeks_exp(teA, tau)
    eA = teA.y.values - pA
    sA, sB = fit["fold_A"]["sessions_vs_default"], fit["fold_B"]["sessions_vs_default"]
    md += ["Reading: the saturating curves beat doing nothing in both folds, by about 1.1 (A) and "
           "1.5 (B) points of MAE; the trend baselines are worse than doing nothing (fit20 loads "
           "move in steps, so a recent trend over-extrapolates), and the paper's linear-log form "
           "is in between (it never plateaus, so it over-predicts experienced members). "
           "Consistency: counting training age in *sessions* (future sessions = sessions per week x "
           f"horizon) is a hair better than calendar weeks: {sA[0]:+.3f} [{sA[1]:+.3f}, {sA[2]:+.3f}] "
           f"points in fold A and {sB[0]:+.3f} [{sB[1]:+.3f}, {sB[2]:+.3f}] in fold B (member "
           "bootstrap). That is real but tiny, and it needs a complete log since the first "
           "session, so the default keeps calendar weeks (a start date is enough); slowing the "
           "weeks clock for people who train less than weekly (pace) did not help.", ""]
    # by stratum
    teS = teA.assign(err=np.abs(eA) * 100, zero=np.abs(teA.y.values) * 100, bias=-eA * 100)
    teS["training"] = pd.cut(teS.weeks, [-1, 4, 12, 26, 52, 104, 1000],
                             labels=["0-4 wk", "4-12 wk", "12-26 wk", "26-52 wk", "1-2 yr", "2+ yr"])
    g1 = teS.groupby("training", observed=True).agg(n=("err", "size"), model=("err", "mean"), zero=("zero", "mean"),
                                                    bias=("bias", "mean"), med_gain=("y", "median"))
    md += ["Fold A test by training age (weeks since first session on that machine):", "",
           md_table(["training age", "cases", "model MAE %", "no-change MAE %", "model bias %", "actual median change %"],
                    [[i, f"{int(r.n):,}", f"{r.model:.2f}", f"{r.zero:.2f}", f"{r.bias:+.2f}", f"{r.med_gain * 100:+.1f}"]
                     for i, r in g1.iterrows()]), ""]
    teS["hb"] = pd.cut(teS.h, [0, 6, 10, 19, 32, 45, 60], labels=["4", "8", "13", "26", "39", "52"])
    g2 = teS.groupby("hb", observed=True).agg(n=("err", "size"), model=("err", "mean"), zero=("zero", "mean"))
    md += ["Fold A test by horizon (weeks):", "",
           md_table(["horizon", "cases", "model MAE %", "no-change MAE %"],
                    [[i, f"{int(r.n):,}", f"{r.model:.2f}", f"{r.zero:.2f}"] for i, r in g2.iterrows()]), ""]
    curve = [[w, f"{(math.exp(A * (math.exp(-w / tau) - math.exp(-(w + 52) / tau))) - 1) * 100:+.1f}",
              f"{(math.exp(A * (math.exp(-w / tau) - math.exp(-(w + 13) / tau))) - 1) * 100:+.1f}"]
             for w in (0, 4, 8, 13, 26, 52)]
    md += [f"Fitted default (fold A train): gain = A (exp(-w/tau) - exp(-(w+h)/tau)), A = {A:.4f}, tau = {tau} weeks: "
           f"a total median gain of {(math.exp(A) - 1) * 100:.0f}% from the first session, "
           f"{(1 - math.exp(-26 / tau)) * 100:.0f}% of it within 26 weeks. Median gain still to come:", "",
           md_table(["weeks trained", "next 52 weeks", "next 13 weeks"], curve), ""]

    # per machine / sex / age / ability diagnostics
    r = trA.assign(res=trA.y.values - A * x_weeks_exp(trA, tau), novice=np.where(trA.weeks < 26, "first 26 wk", "later"))
    r["machine_name"] = r.machine.map(lambda m: MACHINES[int(m)][0])
    r["age_band"] = pd.cut(r.age, [0, 35, 50, 65, 120], labels=["<35", "35-50", "50-65", "65+"])
    nov = r[r.weeks < 26].copy()
    nov["ability"] = nov.groupby("machine").lw0.transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=False))
    diag = []
    for col in ("machine_name", "sex", "age_band"):
        t = r.groupby([col, "novice"], observed=True).res.median().unstack() * 100
        for i, row in t.iterrows():
            diag.append([col.replace("_name", "").replace("_band", ""), i,
                         f"{row.get('first 26 wk', float('nan')):+.2f}", f"{row.get('later', float('nan')):+.2f}"])
    t = nov.groupby("ability").res.median() * 100
    for i, v in t.items():
        diag.append(["current load tertile (first 26 wk, within machine)", ["low", "mid", "high"][int(i)], f"{v:+.2f}", "-"])
    per_machine = []
    for m, (mname, _, _) in MACHINES.items():
        trm, tem = trA[trA.machine == m], teA[teA.machine == m]
        tm, am, _ = fit_curve(trm, lambda D, t: x_weeks_exp(D, t))
        per_machine.append([mname, f"A = {am:.3f}, tau = {tm} wk",
                            f"{np.mean(np.abs(tem.y.values - am * x_weeks_exp(tem, tm))) * 100:.2f}",
                            f"{np.mean(np.abs(tem.y.values - A * x_weeks_exp(tem, tau))) * 100:.2f}"])
    md += ["Median train residual (actual - curve, %) by group; values near 0 mean the pooled "
           "curve already fits that group:", "",
           md_table(["group", "value", "first 26 weeks", "later"], diag), "",
           "Current ability: in the first 26 weeks, members whose load is in the lowest third for "
           "their machine and training age gained about 3% more than the curve, the highest third "
           "about 1% less (a ceiling effect, as Latella et al. 2020 found in powerlifters). Not "
           "used: absolute loads are not comparable between machines or gyms, so a user's log "
           "cannot be placed in these tertiles.", "",
           "Per-machine curves (fitted on each machine's train cases, scored on its test cases):", "",
           md_table(["machine", "fitted", "test MAE % per-machine", "test MAE % pooled"], per_machine), "",
           "Sex and age move the median by about 1% or less (the paper also found minimal sex and "
           "age interactions). The leg press keeps gaining a little longer than the two upper-body "
           "machines; per-machine curves change test MAE by about 0.1 point or less (table above), so "
           "the default stays pooled (a user's exercise is not one of these machines anyway).", ""]

    # bands
    Fb_tr, Fb_te = band_matrix(trA, tau, p), band_matrix(teA, tau, p)
    etr = trA.y.values - A * x_weeks_exp(trA, tau)
    coefs = np.array([qreg(Fb_tr, etr, q) for q in Q])
    P = np.sort(Fb_te @ coefs.T, axis=1)
    hcoefs = np.array([qreg(Fb_tr[:, :2], etr, q) for q in Q])
    Ph = np.sort(Fb_te[:, :2] @ hcoefs.T, axis=1)
    sc, sch = band_scores(eA, P), band_scores(eA, Ph)
    fit["bands"] = {k: dict(zip(BAND_FEATS, map(float, c))) for k, c in zip(QKEYS, coefs)}
    md += ["## 2. Uncertainty bands", "",
           "Quantiles (2.5..97.5%) of the train log error e = ln(actual) - ln(current) - gain, as "
           "linear functions of horizon = sqrt(h/52), novice = exp(-weeks/tau), irregular = "
           "clamp(1 - sessions per week, 0, 1) and gap = days since last session / 56 (linear "
           "quantile regression, pinball loss). Fitted on fold A train, scored once on fold A test:", "",
           md_table(["bands", "pinball x100", "in 50%", "in 80%", "in 95%"],
                    [["horizon only", f"{sch['pinball']:.3f}", f"{sch['in_50']:.1f}", f"{sch['in_80']:.1f}", f"{sch['in_95']:.1f}"],
                     ["DEFAULT horizon + novice + irregular + gap", f"{sc['pinball']:.3f}", f"{sc['in_50']:.1f}",
                      f"{sc['in_80']:.1f}", f"{sc['in_95']:.1f}"]]), ""]
    cov = []
    for nm, msk in [("all", np.ones(len(teA), bool)), ("first 4 weeks", teA.weeks.values <= 4),
                    ("1+ years", teA.weeks.values >= 52), ("< 0.5 sessions/week", teA.freq.values < 0.5),
                    (">= 1 session/week", teA.freq.values >= 1), ("last session > 4 weeks ago", teA.gap.values > 28),
                    ("horizon <= 8 wk", teA.h.values <= 10), ("horizon >= 39 wk", teA.h.values >= 32)]:
        s1, s2 = band_scores(eA[msk], P[msk]), band_scores(eA[msk], Ph[msk])
        cov.append([nm, f"{msk.sum():,}", f"{s1['in_50']:.1f}", f"{s1['in_80']:.1f}", f"{s1['in_95']:.1f}",
                    f"{s2['in_80']:.1f}"])
    md += ["Coverage on fold A test by group (target 50 / 80 / 95):", "",
           md_table(["group", "cases", "in 50%", "in 80%", "in 95%", "in 80% (horizon-only bands)"], cov), "",
           "Consistency matters for the *spread*: people who train less than once a week get "
           "wider bands (mostly a longer upper tail: an irregular trainer's last load is a "
           "weaker guide), and a long gap since the last session widens the lower tail "
           "(detraining). The 50% band over-covers members trained 1+ years (60%): most of their "
           "sessions repeat the same load, so many actuals sit exactly on the median.", ""]
    wid = []
    for nm, x in [("novice, weekly, 13 wk", dict(weeks=2, freq=1, gap=7, h=13)),
                  ("1 year in, weekly, 26 wk", dict(weeks=52, freq=1, gap=7, h=26)),
                  ("1 year in, every 2nd week, 26 wk", dict(weeks=52, freq=0.5, gap=14, h=26)),
                  ("1 year in, 6-week gap, 26 wk", dict(weeks=52, freq=0.25, gap=42, h=26))]:
        D = pd.DataFrame([x])
        qs = np.sort(band_matrix(D, tau, p) @ coefs.T, axis=1)[0]
        g = A * x_weeks_exp(D, tau)[0]
        wid.append([nm, f"{(math.exp(g + qs[3]) - 1) * 100:+.1f}%",
                    f"{(math.exp(g + qs[1]) - 1) * 100:+.1f}% to {(math.exp(g + qs[5]) - 1) * 100:+.1f}%"])
    md += ["Examples (median and 80% range of the change from today's load):", "",
           md_table(["situation", "median", "80% range"], wid), ""]

    # backtest file + end to end
    n_bt = write_backtest(teA, sessions)
    fit["backtest_rows"] = n_bt
    FIT_JSON.write_text(json.dumps(fit, indent=2) + "\n")
    e2e = end_to_end()
    rows = []
    for v, m in e2e.items():
        rows.append([v, m["n"], f"{m.get('abs_log_error_pct', float('nan')):.2f}", f"{m['bias_pct']:+.2f}",
                      f"{m['in_50'] * 100:.1f}", f"{m['in_80'] * 100:.1f}", f"{m['in_95'] * 100:.1f}"])
    md += ["## 3. The model itself, end to end (data/backtest.csv)", "",
           f"`data/backtest.csv` holds one random fold A test case per test member ({n_bt:,} people, "
           "so rows are independent people; 17 monthly cutoffs), each with its last "
           f"{LOG_WEEKS} weeks of log and the first-session date, exactly the inputs a user gives. "
           "`ballmonitor backtest strength_progress [--variant ...]` reproduces this table "
           "from config.toml (it is not refitted here).", "",
           md_table(["variant", "people", "MAE %", "bias %", "in 50%", "in 80%", "in 95%"], rows), ""]
    cfg_check = []
    for k in QKEYS:
        for f_ in BAND_FEATS:
            if abs(float(p[f"band_{k}_{f_}"]) - fit["bands"][k][f_]) > 5e-4:
                cfg_check.append(f"band_{k}_{f_}")
    if abs(p.gain_max - A) > 5e-4 or p.gain_tau_weeks != tau:
        cfg_check.append("gain_max / gain_tau_weeks")
    md += ["Config check: " + ("config.toml matches this fit." if not cfg_check else
                               "**config.toml differs from this fit: " + ", ".join(cfg_check) + "**"), ""]
    md += ["## Weaknesses and hindsight flags", "",
           "- One protocol: one slow set to failure per machine, about weekly, supervised. Free-weight "
           "lifters, multi-set programs and people who train 3-4 times a week are not in the data; "
           "their curves may rise further and for longer (see MODEL.md literature).",
           "- Survivorship: targets are observed only for people still training then. The "
           "prediction answers \"if you keep training like this\".",
           "- Loads are machine kg in steps (load rises in increments; most sessions repeat the "
           "previous load), so the median change is often exactly 0 for experienced members.",
           "- Two test windows (2014-15, 2015-16) from one company's studios; the 2017+ data "
           "were left out like in the paper (sensor equipment changed the recorded loads).",
           "- No hindsight inputs: all features use sessions before the cutoff only; the target "
           "session is chosen by date, not by its value.", ""]
    OUT_MD.write_text("\n".join(md))
    print(f"wrote {OUT_MD}, {FIT_JSON}, {BACKTEST}")
    print(json.dumps(fit, indent=1)[:3000])


if __name__ == "__main__":
    main()
