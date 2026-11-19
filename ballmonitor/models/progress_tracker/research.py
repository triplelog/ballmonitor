"""Walk-forward study of "keep your current pace" vs "progress slows down".  Writes RESEARCH.md,
data/study.json (the numbers the page and MODEL.md quote). Background for model v0.2.0 (see
"How the model uses this"); the fitted values were the defaults of v0.1.0.

    python -m ballmonitor.models.progress_tracker.research      # ~1-2 min; needs pandas + numpy

Data (all already downloaded by the other progress models; raw files are gitignored):
- chess    Lichess open database 2014-01..2017-08 (CC0), the lichess_rating model's 1-in-4 player
           sample of daily totals (models/lichess_rating/data/raw/lichess_days/days_*.csv.gz); blitz
           only; the value is the rating after the day's last game.
- strength fit20 training records 2010-2016 (Steele et al. 2022, OSF jn6ay, CC BY 4.0), cleaned as in
           models/strength_progress/research.py (its data/raw/sessions.parquet cache: best set per
           member, machine and day); one series per member x machine; the value is the load.
- running  BMClab weekly Strava totals 2019-2020 (Afonseca et al. 2022, CC BY 4.0;
           models/running_progress/data/raw/run_ww_*_w.parquet); the value is the week's average pace
           (time / distance), dated at the end of the week; weeks outside 3-15 min/km or over 300 km
           are dropped as in running_progress.

Cases: on the 1st of every month ("today") every series with at least `min_entries` entries in
the last `window_weeks` weeks spanning at least `min_span_weeks` weeks gets the model's rolling
fit (weighted least squares of the value, or its log, on time). The actual at horizon h (4, 13,
26, 52 weeks) is the entry nearest today + h weeks within TOL days. Series without an entry
there (people who stopped) are excluded and counted.

Splits: people by md5(id) (half train, half test). chess and strength are also split in time
(train: targets before the split date; test: cutoffs from it). running has only 2019-2020, so it
is split by people only, and targets after 2020-03-10 (COVID lockdowns) are dropped.
Everything is chosen on train and scored once on test.
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

from ballmonitor.core import registry
from types import SimpleNamespace

MODEL_DIR = Path(__file__).resolve().parent
MODELS = MODEL_DIR.parent
OUT_MD = MODEL_DIR / "RESEARCH.md"
STUDY_JSON = MODEL_DIR / "data" / "study.json"

LICHESS_DAYS = MODELS / "lichess_rating" / "data" / "raw" / "lichess_days"
FIT20_SESSIONS = MODELS / "strength_progress" / "data" / "raw" / "sessions.parquet"
BMCLAB = MODELS / "running_progress" / "data" / "raw"

EPOCH = pd.Timestamp("1970-01-01")
HORIZONS = (4, 13, 26, 52)
TOL = {4: 7, 13: 14, 26: 14, 52: 14}            # days either side of the target date
H_GRID = (0.0, 0.5, 1, 2, 3, 4, 6, 8, 10, 13, 17, 22, 26, 35, 52, 78, 104, 156, 260, math.inf)
RECENCY_GRID = (0.0, 2.0, 4.0, 8.0)
WINDOW_GRID = (4, 8, 12, 26)
DRIFT_GRID = tuple(np.round(np.linspace(0, 1, 41) ** 2, 6))  # x unit-scale, see fit_band
K_GRID = tuple(np.round(np.arange(0.5, 4.01, 0.02), 3))
Z = {0.5: 0.6744897501960817, 0.8: 1.2815515655446004, 0.95: 1.959963984540054}
# The rolling-line settings studied (model v0.1.0's defaults; the model no longer fits a rolling line).
STUDY = SimpleNamespace(window_weeks=8.0, recency_half_life_weeks=0.0, min_entries=3, min_span_weeks=2.0)
SEED = 20261119

KINDS = {
    "chess": dict(name="Chess rating (Lichess blitz)", scale="linear", unit="points",
                  split="2016-04-01", end="2017-08-31"),
    "strength": dict(name="Weight lifted (fit20 machines)", scale="log", unit="%",
                     split="2015-07-01", end="2016-12-31"),
    "running": dict(name="Running pace (Strava weekly average)", scale="log", unit="%",
                    split=None, end="2020-03-10"),
}


def day(ts) -> np.ndarray:
    return ((pd.to_datetime(ts) - EPOCH) / pd.Timedelta(days=1)).astype(int).to_numpy() \
        if not isinstance(ts, str) else int((pd.Timestamp(ts) - EPOCH) / pd.Timedelta(days=1))


def is_test(key) -> bool:
    return int(hashlib.md5(str(key).encode()).hexdigest(), 16) % 2 == 1


def iso(d: int) -> str:
    return (EPOCH + pd.Timedelta(days=int(d))).date().isoformat()


# ── data: every dataset becomes (series id, day, value) sorted by series and day ────────────

def load_chess() -> pd.DataFrame:
    frames = []
    for path in sorted(LICHESS_DAYS.glob("days_*.csv.gz")):
        d = pd.read_csv(path, usecols=["player", "speed", "date", "rating_last"])
        frames.append(d[d.speed == "blitz"])
    d = pd.concat(frames)
    return pd.DataFrame({"sid": d.player.astype(str).to_numpy(), "day": day(d.date), "value": d.rating_last.astype(float).to_numpy()})


def load_strength() -> pd.DataFrame:
    if not FIT20_SESSIONS.exists():
        raise SystemExit(f"missing {FIT20_SESSIONS}: run python -m ballmonitor.models.strength_progress.research once")
    s = pd.read_parquet(FIT20_SESSIONS, columns=["memberId", "machineId", "date", "exerciseWeight"])
    sid = s.memberId.astype("int64").astype(str) + "/" + s.machineId.astype(str)
    return pd.DataFrame({"sid": sid.to_numpy(), "day": day(s.date), "value": s.exerciseWeight.astype(float).to_numpy()})


def load_running() -> pd.DataFrame:
    p = registry.load_model("running_progress").params
    d = pd.concat([pd.read_parquet(BMCLAB / f"run_ww_{y}_w.parquet", columns=["datetime", "athlete", "distance", "duration"])
                   for y in (2019, 2020)])
    d = d[d.distance > 0]
    pace_min = d.duration / d.distance
    d = d[pace_min.between(p.min_pace_min_per_km, p.max_pace_min_per_km) & (d.distance <= p.max_week_km)]
    return pd.DataFrame({"sid": d.athlete.astype(str).to_numpy(), "day": day(d.datetime) + 6,
                         "value": (d.duration / d.distance * 60.0).to_numpy()})


LOADERS = {"chess": load_chess, "strength": load_strength, "running": load_running}


# ── cases ───────────────────────────────────────────────────────────────────

class Series:
    """All series of one dataset in flat arrays, sorted by (series, day)."""

    def __init__(self, df: pd.DataFrame, scale: str):
        df = df.sort_values(["sid", "day"], kind="stable")
        codes, names = pd.factorize(df.sid, sort=False)
        self.names = np.asarray(names)
        self.code = codes.astype(np.int64)
        self.day = df.day.to_numpy(np.int64)
        self.value = df.value.to_numpy(float)
        self.y = np.log(self.value) if scale == "log" else self.value.copy()
        self.key = self.code * 1_000_000 + self.day
        self.test = np.array([is_test(n) for n in self.names])


def cutoffs(S: Series, start: int, end: int) -> tuple[np.ndarray, np.ndarray]:
    """(series, cutoff day) for the 1st of every month within each series' active span."""
    months = day(pd.date_range(iso(start), iso(end), freq="MS"))
    first = np.full(len(S.names), np.iinfo(np.int64).max)
    last = np.zeros(len(S.names), np.int64)
    np.minimum.at(first, S.code, S.day)
    np.maximum.at(last, S.code, S.day)
    sid, cut = [], []
    for m in months:
        ok = np.nonzero((first < m) & (last >= m - 7 * max(WINDOW_GRID)))[0]
        sid.append(ok); cut.append(np.full(len(ok), m))
    return np.concatenate(sid), np.concatenate(cut)


def window_fit(S: Series, sid, cut, window_weeks: float, recency_hl: float, min_entries: int, min_span_weeks: float) -> dict:
    """The model's rolling fit for every (series, cutoff), vectorised. Same arithmetic as model.fit."""
    i1 = np.searchsorted(S.key, sid * 1_000_000 + cut, side="right")
    i0 = np.searchsorted(S.key, sid * 1_000_000 + cut - int(round(7 * window_weeks)), side="right")
    n = i1 - i0
    ok = n >= min_entries
    ok[ok] &= (S.day[i1[ok] - 1] - S.day[i0[ok]]) >= 7 * min_span_weeks - 1e-9
    sid, cut, i0, i1, n = sid[ok], cut[ok], i0[ok], i1[ok], n[ok]
    case = np.repeat(np.arange(len(sid)), n)
    idx = np.concatenate([np.arange(a, b) for a, b in zip(i0, i1)]) if len(sid) else np.zeros(0, int)
    t = (S.day[idx] - cut[case]) / 7.0
    anchor = S.y[i1 - 1]
    y = S.y[idx] - anchor[case]
    w = np.ones_like(t) if recency_hl <= 0 else 0.5 ** (-t / recency_hl)
    C = len(sid)
    sw = np.bincount(case, w, C)
    w = w * (n[case] / sw[case])                   # normalise: weights sum to n
    sw = n.astype(float)
    swt, swy = np.bincount(case, w * t, C), np.bincount(case, w * y, C)
    tbar, ybar = swt / sw, swy / sw
    dt_, dy = t - tbar[case], y - ybar[case]
    stt = np.bincount(case, w * dt_ * dt_, C)
    sty = np.bincount(case, w * dt_ * dy, C)
    b = sty / stt
    a = ybar - b * tbar
    rss = np.bincount(case, w * (dy - b[case] * dt_) ** 2, C)
    s2 = rss / np.maximum(n - 2, 1)
    var_b = s2 / stt
    var_a = s2 * (1.0 / n + tbar ** 2 / stt)
    return dict(sid=sid, cut=cut, n=n, a=a + anchor, b=b, s2=s2, var_a=var_a, var_b=var_b,
                last=anchor, mean=ybar + anchor, first_day=S.day[i0], i0=i0, i1=i1)


def actuals(S: Series, sid, cut, h: int, data_end: int) -> tuple[np.ndarray, np.ndarray]:
    """Value (transformed) nearest cut + h weeks within TOL; NaN if none. And 'observable' mask."""
    t = cut + 7 * h
    tol = TOL[h]
    k = sid * 1_000_000 + t
    j = np.searchsorted(S.key, k)
    best = np.full(len(sid), np.nan)
    dist = np.full(len(sid), np.inf)
    for jj in (j - 1, j):
        jj = np.clip(jj, 0, len(S.key) - 1)
        same = S.code[jj] == sid
        d = np.abs(S.day[jj] - t).astype(float)
        better = same & (d <= tol) & (d < dist)
        best[better] = S.y[jj[better]]
        dist[better] = d[better]
    observable = t + tol <= data_end
    return best, observable


def damped(h, H):
    """Weeks of progress at the current weekly pace that a half-life H leaves in h weeks (formula damped_weeks)."""
    if not math.isfinite(H):
        return np.asarray(h, float)
    if H <= 0:
        return np.zeros_like(np.asarray(h, float))
    return H / math.log(2) * (1 - 0.5 ** (np.asarray(h, float) / H))


def build(kind: str, S: Series, p, window_weeks: float, recency_hl: float) -> pd.DataFrame:
    meta = KINDS[kind]
    end = day(meta["end"])
    split = day(meta["split"]) if meta["split"] else None
    sid, cut = cutoffs(S, int(S.day.min()) + 7 * int(window_weeks), end)
    F = window_fit(S, sid, cut, window_weeks, recency_hl, int(p.min_entries), float(p.min_span_weeks))
    rows = []
    for h in HORIZONS:
        act, obs = actuals(S, F["sid"], F["cut"], h, end)
        test = S.test[F["sid"]]
        if split is None:
            role = np.where(test, "test", "train")
        else:
            role = np.where(test & (F["cut"] >= split), "test",
                            np.where(~test & (F["cut"] + 7 * h < split), "train", ""))
        keep = obs & (role != "")
        df = pd.DataFrame({k: v[keep] for k, v in F.items() if k not in ("i0", "i1")})
        df["i0"], df["i1"] = F["i0"][keep], F["i1"][keep]
        df["h"] = h
        df["actual"] = act[keep]
        df["role"] = role[keep]
        rows.append(df)
    X = pd.concat(rows, ignore_index=True)
    X["stopped"] = X.actual.isna()
    return X


# ── scoring ─────────────────────────────────────────────────────────────────

def unit_err(kind: str, e):
    return np.abs(e) * (100.0 if KINDS[kind]["scale"] == "log" else 1.0)


def mae_by_h(kind, X, pred) -> dict[int, float]:
    e = unit_err(kind, pred - X.actual.to_numpy())
    return {h: float(np.mean(e[X.h.to_numpy() == h])) for h in HORIZONS if (X.h == h).any()}


ANCHORS = {"fit": "a", "last": "last", "mean": "mean"}


def start(X: pd.DataFrame, anchor: str) -> np.ndarray:
    """Where the likely line starts (formula start): the line's value today, the latest entry or the window mean."""
    return X[ANCHORS[anchor]].to_numpy()


def predictions(X: pd.DataFrame, H: float, anchor: str = "fit") -> np.ndarray:
    if not math.isfinite(H):          # the plain line always starts at the fitted value today
        return X.a.to_numpy() + X.b.to_numpy() * X.h.to_numpy()
    return start(X, anchor) + X.b.to_numpy() * damped(X.h.to_numpy(), H)


def choose_half_life(kind, tr) -> tuple[tuple[str, float], dict]:
    scores = {}
    for anchor in ANCHORS:
        for H in H_GRID:
            if not math.isfinite(H) and anchor != "fit":
                continue
            m = mae_by_h(kind, tr, predictions(tr, H, anchor))
            scores[(anchor, H)] = float(np.mean(list(m.values())))
    best = min(scores, key=scores.get)
    return best, scores


def sd(kind, X, choice, drift):
    """formula spread / band_scale: sqrt(residual var + slope var x D(h)^2 + (drift x size)^2 x h)."""
    anchor, H = choice
    D = damped(X.h.to_numpy(), H)
    size = 1.0 if KINDS[kind]["scale"] == "log" else np.abs(start(X, anchor))
    return np.sqrt(X.s2.to_numpy() + D ** 2 * X.var_b.to_numpy() + (drift * size) ** 2 * X.h.to_numpy())


def interval_score(e, half, level):
    alpha = 1 - level
    return 2 * half + (2 / alpha) * np.maximum(np.abs(e) - half, 0)


def fit_band(kind, tr, choice) -> tuple[float, float]:
    """drift (share of the value per sqrt-week) and scale k minimising the mean 80% interval score,
    each horizon weighted equally."""
    e = predictions(tr, choice[1], choice[0]) - tr.actual.to_numpy()
    hs = tr.h.to_numpy()
    best = (math.inf, 0.0, 1.0)
    for dgrid in DRIFT_GRID:
        drift = dgrid * 0.05
        s = sd(kind, tr, choice, drift)
        for k in K_GRID:
            sc = interval_score(e, k * Z[0.8] * s, 0.8)
            v = np.mean([sc[hs == h].mean() for h in HORIZONS if (hs == h).any()])
            if v < best[0]:
                best = (v, drift, k)
    return best[1], best[2]


def coverage(kind, X, choice, drift, k) -> dict[int, dict[float, float]]:
    e = np.abs(predictions(X, choice[1], choice[0]) - X.actual.to_numpy())
    s = k * sd(kind, X, choice, drift)
    hs = X.h.to_numpy()
    return {h: {lv: float(np.mean(e[hs == h] <= z * s[hs == h])) for lv, z in Z.items()} for h in HORIZONS if (hs == h).any()}


def realised_share(X) -> dict[int, float]:
    """How much of the plain line's promised change happened: slope of (actual - fitted now) on
    (weekly pace x h), through the origin."""
    out = {}
    for h in HORIZONS:
        x = X[X.h == h]
        if len(x) < 50:
            continue
        promise = x.b.to_numpy() * h
        got = x.actual.to_numpy() - x.a.to_numpy()
        out[h] = float(np.sum(promise * got) / np.sum(promise * promise))
    return out


def boot_diff(kind, X, p1, p2, reps=300, seed=SEED) -> tuple[float, float]:
    """95% interval of mean(|e1| - |e2|) resampling people (cluster bootstrap)."""
    d = unit_err(kind, p1 - X.actual.to_numpy()) - unit_err(kind, p2 - X.actual.to_numpy())
    g = pd.Series(d).groupby(X.sid.to_numpy())
    sums, counts = g.sum().to_numpy(), g.size().to_numpy()
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(reps):
        i = rng.integers(0, len(sums), len(sums))
        stats.append(sums[i].sum() / counts[i].sum())
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


# ── the study ────────────────────────────────────────────────────────────────

def study_kind(kind: str, S: Series, p) -> dict:
    W, R = float(p.window_weeks), float(p.recency_half_life_weeks)
    X = build(kind, S, p, W, R)
    obs = X[~X.stopped]
    tr, te = obs[obs.role == "train"].reset_index(drop=True), obs[obs.role == "test"].reset_index(drop=True)
    choice, scores = choose_half_life(kind, tr)
    anchor, H = choice
    drift, k = fit_band(kind, tr, choice)
    meth = {
        "no change (last entry)": lambda D: D["last"].to_numpy(),
        "no change (window average)": lambda D: D["mean"].to_numpy(),
        "no change (line's value today)": lambda D: D.a.to_numpy(),
        "keep this pace (plain line)": lambda D: predictions(D, math.inf),
        "damped from today's line value, half-life 13 weeks": lambda D: predictions(D, 13.0, "fit"),
        f"likely (from {ANCHOR_WORDS[anchor]}, half-life {fmt_h(H)})": lambda D: predictions(D, H, anchor),
    }
    res = {name: {"train": mae_by_h(kind, tr, f(tr)), "test": mae_by_h(kind, te, f(te))} for name, f in meth.items()}
    stop = X.groupby(["role", "h"]).stopped.agg(["mean", "size"])
    likely_te = predictions(te, H, anchor)
    ci_plain = boot_diff(kind, te, likely_te, predictions(te, math.inf))
    ci_last = boot_diff(kind, te, likely_te, te["last"].to_numpy())
    scale = 100 if KINDS[kind]["scale"] == "log" else 1
    bias = {name: {h: float(np.mean(((f(te) - te.actual.to_numpy()) * scale)[te.h.to_numpy() == h]))
                   for h in HORIZONS if (te.h == h).any()} for name, f in meth.items()}
    best_by_anchor = {a_: min(((H_, v) for (aa, H_), v in scores.items() if aa == a_), key=lambda t: t[1]) for a_ in ANCHORS}
    # recency and window sensitivity (train only)
    rec = {}
    for r in RECENCY_GRID:
        Xr = build(kind, S, p, W, r)
        Xr = Xr[(~Xr.stopped) & (Xr.role == "train")].reset_index(drop=True)
        cr, sc = choose_half_life(kind, Xr)
        rec[r] = {"choice": cr, "mae": sc[cr], "plain": sc[("fit", math.inf)], "n": len(Xr)}
    win = {}
    for w in WINDOW_GRID:
        Xw = build(kind, S, p, w, R)
        Xw = Xw[(~Xw.stopped) & (Xw.role == "train")].reset_index(drop=True)
        cw, sc = choose_half_life(kind, Xw)
        win[w] = {"choice": cw, "mae": sc[cw], "plain": sc[("fit", math.inf)], "n": len(Xw),
                  "last": float(np.mean(list(mae_by_h(kind, Xw, Xw["last"].to_numpy()).values())))}
    return dict(
        X=X, tr=tr, te=te, anchor=anchor, H=H, scores=scores, best_by_anchor=best_by_anchor,
        drift=drift, k=k, res=res, bias=bias,
        cov_tr=coverage(kind, tr, choice, drift, k), cov_te=coverage(kind, te, choice, drift, k),
        share_te=realised_share(te), share_tr=realised_share(tr),
        stop=stop, ci_plain=ci_plain, ci_last=ci_last, rec=rec, win=win,
        people={"train": int(tr.sid.nunique()), "test": int(te.sid.nunique())},
        test_span=(int(te.cut.min()), int(te.cut.max())) if len(te) else (0, 0),
        series=len(S.names), entries=len(S.day),
    )


METHOD_KEYS = ("last", "mean", "fit", "plain", "damped13", "likely")   # order of study_kind's methods
ANCHOR_WORDS = {"fit": "the line's value today", "last": "the latest entry", "mean": "the window average"}


def fmt_h(H) -> str:
    return "none" if not math.isfinite(H) else f"{H:g} weeks"


def md_table(header, rows) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" if i == 0 else "---:" for i in range(len(header))) + "|"]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def front_loading(S: Series, X: pd.DataFrame, kind: str) -> dict[int, dict]:
    """Newcomers (series started at most 8 weeks before the cutoff): mean change from the latest entry
    after 13 / 26 / 52 weeks, all people (train and test), people who kept logging only."""
    first = np.full(len(S.names), np.iinfo(np.int64).max)
    np.minimum.at(first, S.code, S.day)
    x = X[(~X.stopped) & (X.role != "")]
    x = x[(x.cut - first[x.sid.to_numpy()]) <= 56]
    scale = 100.0 if KINDS[kind]["scale"] == "log" else 1.0
    return {int(h): {"mean_change": float((g.actual - g["last"]).mean() * scale), "cases": int(len(g))}
            for h, g in x.groupby("h") if h >= 13}


def main(argv: list[str] | None = None) -> None:
    p = STUDY
    data, results = {}, {}
    for kind, meta in KINDS.items():
        print(f"{kind}: loading", flush=True)
        S = Series(LOADERS[kind](), meta["scale"])
        data[kind] = S
        results[kind] = study_kind(kind, S, p)
        results[kind]["front"] = front_loading(S, results[kind]["X"], kind)
        r = results[kind]
        print(f"  start={r['anchor']} H={fmt_h(r['H'])}; newcomers {r['front']}", flush=True)
    study = {"window_weeks": float(p.window_weeks), "recency_half_life_weeks": float(p.recency_half_life_weeks),
             "kinds": {}}
    for kind, r in results.items():
        study["kinds"][kind] = {
            "name": KINDS[kind]["name"], "unit": KINDS[kind]["unit"],
            "start": r["anchor"], "half_life_weeks": r["H"],
            "band_drift": r["drift"], "band_scale": r["k"],
            "test_mae": {key: v["test"] for key, v in zip(METHOD_KEYS, r["res"].values())},
            "test_cases": {int(h): int(n) for h, n in r["te"].groupby("h").size().items()},
            "stopped_share_test": {int(h): float(r["stop"].loc[("test", h)]["mean"]) for h in HORIZONS if ("test", h) in r["stop"].index},
            "coverage_test": r["cov_te"], "realised_share_test": r["share_te"],
            "newcomers": r["front"],
            "people": r["people"],
        }
    STUDY_JSON.write_text(json.dumps(study, indent=1, default=float) + "\n")
    write_md(results, p)
    print(f"wrote {OUT_MD}, {STUDY_JSON}")


def write_md(results, p) -> None:
    L = ["# Progress tracker: research", "",
         "_Generated by `python -m ballmonitor.models.progress_tracker.research`; do not edit._", "",
         "Question: when someone logs a measure every week or so and fits a straight line through the last "
         f"{p.window_weeks:g} weeks, how much of that pace is still there 1, 3, 6 and 12 months later? "
         "The tracker shows two lines: **keep this pace** (the straight line, what the owner asked for) and "
         "**likely**, where the weekly progress halves every *half-life* weeks. This study picks the "
         "half-life and the width of the range for each kind of measure, on real logs.", "",
         "## Data and cases", "",
         "| kind | data | series | entries | value | scale |", "|---|---|---:|---:|---|---|"]
    srcs = {"chess": "Lichess open database 2014-01..2017-08, 1-in-4 player sample, blitz (CC0)",
            "strength": "fit20 studio records 2010-2016, member x machine (Steele et al. 2022, CC BY 4.0)",
            "running": "BMClab Strava weekly totals 2019-2020 (Afonseca et al. 2022, CC BY 4.0)"}
    vals = {"chess": "rating after the day's last game", "strength": "load of the best set that day (kg)",
            "running": "week's average pace (s/km)"}
    for kind, r in results.items():
        L.append(f"| {kind} | {srcs[kind]} | {r['series']:,} | {r['entries']:,} | {vals[kind]} | {KINDS[kind]['scale']} |")
    L += ["",
          f"A case is a series on the 1st of a month with at least {p.min_entries:g} entries in the last "
          f"{p.window_weeks:g} weeks spanning at least {p.min_span_weeks:g} weeks (recency half-life "
          f"{p.recency_half_life_weeks:g} = {'equal weights' if p.recency_half_life_weeks <= 0 else 'weighted'}). "
          "The fit is the model's own (weighted least squares on the value, or its log, against weeks). "
          "The actual is the entry nearest the target date within " +
          ", ".join(f"{TOL[h]} days ({h} weeks)" for h in HORIZONS) + ".", "",
          "**People who stopped are excluded.** A case only counts at a horizon if the person logged an entry "
          "near that date, so everything below is *for people who kept going*. Share of observable cases with no "
          "entry near the target (stopped or paused):", ""]
    rows = []
    for kind, r in results.items():
        st = r["stop"]
        row = [kind]
        for h in HORIZONS:
            try:
                m, n = st.loc[("test", h)]
                row.append(f"{m:.0%} of {int(n):,}")
            except KeyError:
                row.append("-")
        rows.append(row)
    L += [md_table(["kind (test)"] + [f"{h} wk" for h in HORIZONS], rows), ""]
    L += ["**Splits.** People are split in half by md5 of their id. chess: train = train people with targets "
          f"before {KINDS['chess']['split']}, test = test people with cutoffs from then to the end of the data. strength: "
          f"the same with {KINDS['strength']['split']}. running: only 2019-2020 exist, so it is split by people only "
          "(train and test share the same calendar weeks), and targets after 2020-03-10 are dropped (COVID lockdowns).", "",
          "**Independent periods.** Cases overlap: each person appears at many cutoffs and all horizons, and "
          "everyone shares one calendar. Non-overlapping target windows in the test periods:", ""]
    rows = []
    for kind, r in results.items():
        a, b = r["test_span"]
        weeks = (b - a) / 7 if b > a else 0
        last = day(KINDS[kind]["end"])
        rows.append([kind, f"{iso(a)} .. {iso(b)}", *[f"{max(1, int(((min(b, last - 7 * h) - a) / 7) // h) + 1)}" if a + 7 * h <= last else "0" for h in HORIZONS],
                     f"{r['people']['test']:,}"])
    L += [md_table(["kind", "test cutoffs", *[f"{h} wk" for h in HORIZONS], "test people"], rows), "",
          "So the 52-week results rest on about one or two independent years per kind, and the running test "
          "shares its calendar with training. Bootstrap intervals resample people and ignore the shared "
          "calendar, so they are too narrow.", ""]

    L += ["## Errors by method (test, scored once)", "",
          "Mean absolute error of the forecast at each horizon: chess in rating points, strength and running in % "
          "(100 x |log error|). Half-life and range were chosen on train only.", ""]
    for kind, r in results.items():
        L += [f"### {kind}: {KINDS[kind]['name']}", ""]
        hs = [h for h in HORIZONS if h in next(iter(r['res'].values()))["test"]]
        rows = [[name, *[f"{v['test'][h]:.1f}" for h in hs], *[f"{v['train'][h]:.1f}" if h in v['train'] else '-' for h in hs]]
                for name, v in r["res"].items()]
        n_te = r["te"].groupby("h").size()
        n_tr = r["tr"].groupby("h").size()
        L += [md_table(["method", *[f"test {h} wk" for h in hs], *[f"train {h} wk" for h in hs]], rows),
              "", "Cases: test " + ", ".join(f"{h} wk {n_te.get(h, 0):,}" for h in hs) +
              "; train " + ", ".join(f"{h} wk {n_tr.get(h, 0):,}" for h in hs) + ".", "",
              f"Likely minus plain, mean |error| over all test horizons pooled, 95% people-bootstrap interval: "
              f"{r['ci_plain'][0]:+.2f} to {r['ci_plain'][1]:+.2f}; likely minus 'no change (last entry)': "
              f"{r['ci_last'][0]:+.2f} to {r['ci_last'][1]:+.2f} (negative = likely is better).", "",
              "Mean error (forecast - actual; for running + = forecast slower than actual), test:", "",
              md_table(["method", *[f"{h} wk" for h in hs]],
                       [[n, *[f"{v[h]:+.1f}" for h in hs]] for n, v in r["bias"].items()]), ""]
        L += [f"**Choice (train, mean of the per-horizon errors):** start from {ANCHOR_WORDS[r['anchor']]}, half-life "
              f"{fmt_h(r['H'])}. Best half-life for each starting point: " +
              "; ".join(f"{ANCHOR_WORDS[a_]}: {fmt_h(H_)} ({v:.2f})" for a_, (H_, v) in r["best_by_anchor"].items()) +
              ". Half-lives from the chosen start: " +
              ", ".join(f"{fmt_h(H_)}: {v:.2f}" for (a_, H_), v in r["scores"].items() if a_ == r["anchor"]) +
              f"; plain line {r['scores'][('fit', math.inf)]:.2f}.", ""]
        sh = r["share_te"]
        L += ["**How much of the promised change happened** (test; slope of the real change since today on "
              "the plain line's promised change, through 0): " +
              ", ".join(f"{h} wk {v:.0%}" for h, v in sh.items()) +
              f". The likely line keeps " + ", ".join(f"{h} wk {float(damped(h, r['H'])) / h:.0%}" for h in sh) + ".", ""]
        cov = r["cov_te"]
        L += [f"**Range** (normal, sd = {r['k']:.2f} x sqrt(residual var + D(h)^2 var(slope) + "
              f"({r['drift']:.4g} x size)^2 x h), size = {'1 (log scale)' if KINDS[kind]['scale'] == 'log' else 'the starting value'}; formula spread, fitted to the 80% interval score on train). Test coverage:", "",
              md_table(["horizon", "50%", "80%", "95%"],
                       [[f"{h} wk", *[f"{c[lv]:.0%}" for lv in (0.5, 0.8, 0.95)]] for h, c in cov.items()]), ""]
        L += ["Recency weighting (train; half-life of the weights in weeks, 0 = equal): " +
              "; ".join(f"{r_:g}: likely {v['mae']:.2f} ({ANCHOR_WORDS[v['choice'][0]]}, half-life {fmt_h(v['choice'][1])}), plain {v['plain']:.2f}"
                        for r_, v in r["rec"].items()) + ".", "",
              "Window length (train; each on its own cases): " +
              "; ".join(f"{w} wk: likely {v['mae']:.2f} ({ANCHOR_WORDS[v['choice'][0]]}, half-life {fmt_h(v['choice'][1])}), plain {v['plain']:.2f}, last entry {v['last']:.2f}, {v['n']:,} cases"
                        for w, v in r["win"].items()) + ".", ""]
    L += ["## Body weight and body fat", "",
          "No open dataset of repeated body-weight or body-fat logs was available, so their half-life is a judgement "
          "(v0.1.0 config `half_life_weeks_body`, marked DRAFT), and their **likely line and range were not tested**. "
          "Reasoning: for a fixed change in calories, weight changes at a rate that shrinks as the body adapts, "
          "with a time constant of about a year (Hall et al. 2011, Lancet 378:826-837: about half the eventual "
          "change after one year); real diets also drift, so the half-life is a guess at the slow end.", "",
          "## Newcomers: is progress front-loaded?", "",
          "Series that started at most 8 weeks before the cutoff (all people, only those still logging): mean change from "
          "the latest entry (chess points; lifts and running % = 100 x log ratio). Running has no newcomer signal (the "
          "athletes were already training) and no 52-week horizon.", "",
          md_table(["kind", "after 13 wk", "after 26 wk", "after 52 wk", "share of the year's change by 26 wk"],
                   [[kind, *[f"{r['front'][h]['mean_change']:+.1f} ({r['front'][h]['cases']:,})" if h in r['front'] else "-" for h in (13, 26, 52)],
                     f"{r['front'][26]['mean_change'] / r['front'][52]['mean_change']:.0%}" if 52 in r['front'] and 26 in r['front'] and r['front'][52]['mean_change'] else "-"]
                    for kind, r in results.items()]), "",
          "## How the model uses this", "",
          "Model v0.2.0 no longer forecasts from the rolling line: it tracks a plan the person sets (even, faster early or "
          "faster late) and scales it by the share of the planned progress made so far. That prediction is motivational "
          "and untested; this study is the background: short-term pace does not persist, and newcomers' gains come mostly "
          "early, which is why 'faster early' is the realistic plan shape.", ""]
    OUT_MD.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
