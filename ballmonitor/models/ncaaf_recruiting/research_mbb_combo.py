"""MBB: do two recruiting classes beat one, and how much do recruiting rankings add to
last season's team strength?  Writes RESEARCH_MBB_COMBO.md (generated, never hand-edit).

    python ballmonitor/models/ncaaf_recruiting/research_mbb_combo.py

Data (built by fetch.py, see RESEARCH_MBB.md): On3 MBB recruits 2014-2027, On3 consensus
team ranks, barttorvik adjusted efficiency margin (adj. EM) per team-season.

Rows: every D-I team with adj. EM in seasons y (prior) and y+1, for class years y.
  T1 = adj. EM in season y+1 (the class's freshman season)
  T2 = mean adj. EM over seasons y+1 and y+2
Recruiting metrics per team and class (teams without ranked recruits get 0, or the worst
rank + 1 for the consensus):
  consensus   -ln(On3 consensus team rank)
  rating_sum  sum of commits' industry ratings
  stars_sum   sum of commits' stars
  top50       commits ranked in the class top 50
  model       offer-model class score (v0.5.0 basketball defaults)
"Two-year" uses class y and class y-1 (the returning sophomores).

Walk-forward: the linear model for test class y is fitted only on class years whose target
was known before season y+1 started (T1: classes <= y-1; T2: classes <= y-2), and needs
at least MIN_TRAIN_YEARS of them. Scores are pooled over test rows; intervals resample
whole test years (rows within a year share a season).
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

MODEL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODEL_DIR))
import research_mbb as R  # noqa: E402
from src.mbb_names import to_bart  # noqa: E402

MIN_TRAIN_YEARS = 3
BOOT = 2000
METRICS = ["consensus", "rating_sum", "stars_sum", "top50", "model"]
LABELS = {
    "consensus": "On3 consensus rank", "rating_sum": "sum of industry ratings",
    "stars_sum": "sum of stars", "top50": "top-50 recruits", "model": "offer-model score",
}
TOP_N = 50


def build_rows():
    em = R.load_team_seasons()
    bart_names = set().union(*em.values())
    ratings = R.load_ratings()
    consensus = R.load_consensus()
    cache: dict[str, str] = {}

    def bart(school: str) -> str:
        if school not in cache:
            cache[school] = to_bart(school, bart_names) or ""
        return cache[school]

    feats: dict[int, dict[str, dict[str, float]]] = {}
    for y in sorted({r["year"] for r in ratings}):
        f = {m: defaultdict(float) for m in METRICS}
        for r in ratings:
            if r["year"] != y or not r["school"] or not bart(r["school"]):
                continue
            t = bart(r["school"])
            if not math.isnan(r["industry_rating"]):
                f["rating_sum"][t] += r["industry_rating"]
            f["stars_sum"][t] += r["stars"]
            if not math.isnan(r["industry_rank"]) and r["industry_rank"] <= TOP_N:
                f["top50"][t] += 1
        ranks = {bart(t): rk for t, rk in consensus.get(y, {}).items() if bart(t)}
        worst = max(ranks.values(), default=0) + 1
        f["consensus"] = defaultdict(lambda w=worst: -math.log(w), {t: -math.log(rk) for t, rk in ranks.items()})
        for t in R.run_model(y, R.DRAFT_DEFAULTS).teams:
            if t.commits_count > 0 and bart(t.name):
                f["model"][bart(t.name)] += t.total_score
        feats[y] = f

    rows = []
    for y in sorted(feats):
        if y - 1 not in feats or y not in em or y + 1 not in em:
            continue
        for t in em[y + 1]:
            if t not in em[y]:
                continue
            row = {"year": y, "team": t, "prior": em[y][t], "t1": em[y + 1][t],
                   "t2": (em[y + 1][t] + em[y + 2][t]) / 2 if y + 2 in em and t in em[y + 2] else math.nan}
            for m in METRICS:
                row[f"{m}_0"] = feats[y][m][t]
                row[f"{m}_1"] = feats[y - 1][m][t]
            rows.append(row)
    return rows


def design(rows, cols):
    return np.column_stack([np.ones(len(rows))] + [[r[c] for r in rows] for c in cols])


def walk_forward(rows, target, cols):
    """Out-of-sample predictions for every test row (dict keyed by (year, team))."""
    lag = 1 if target == "t1" else 2
    years = sorted({r["year"] for r in rows if not math.isnan(r[target])})
    preds = {}
    for y in years:
        train = [r for r in rows if r["year"] <= y - lag and not math.isnan(r[target])]
        if len({r["year"] for r in train}) < MIN_TRAIN_YEARS:
            continue
        beta = np.linalg.lstsq(design(train, cols), np.array([r[target] for r in train]), rcond=None)[0]
        test = [r for r in rows if r["year"] == y and not math.isnan(r[target])]
        for r, p in zip(test, design(test, cols) @ beta):
            preds[(r["year"], r["team"])] = float(p)
    return preds


def scores(rows, target, preds, subset=None):
    test = [r for r in rows if (r["year"], r["team"]) in preds and (subset is None or subset(r))]
    by_year = defaultdict(list)
    for r in test:
        by_year[r["year"]].append(r)

    def stats(years):
        rs = [r for y in years for r in by_year[y]]
        y_ = np.array([r[target] for r in rs])
        p = np.array([preds[(r["year"], r["team"])] for r in rs])
        rmse = float(np.sqrt(np.mean((y_ - p) ** 2)))
        rho = float(np.mean([spearmanr([preds[(r["year"], r["team"])] for r in by_year[yy]],
                                       [r[target] for r in by_year[yy]]).statistic for yy in years]))
        return rmse, rho
    years = sorted(by_year)
    return years, stats(years), stats


def evaluate(rows, target, models, subset=None):
    out = {}
    base_preds = walk_forward(rows, target, ["prior"])
    years, (base_rmse, _), base_stats = scores(rows, target, base_preds, subset)
    rng = np.random.default_rng(0)
    boot_years = [rng.choice(years, len(years)) for _ in range(BOOT)]
    for name, cols in models.items():
        preds = walk_forward(rows, target, cols)
        yrs, (rmse, rho), stats = scores(rows, target, preds, subset)
        diffs = []
        if cols != ["prior"]:
            for by in boot_years:
                diffs.append(stats(list(by))[0] - base_stats(list(by))[0])
        lo, hi = (np.percentile(diffs, [2.5, 97.5]) if diffs else (math.nan, math.nan))
        n = sum(1 for r in rows if (r["year"], r["team"]) in preds and (subset is None or subset(r)))
        out[name] = {"rmse": rmse, "rho": rho, "d_rmse": rmse - base_rmse, "lo": float(lo), "hi": float(hi),
                     "years": yrs, "n": n}
    return out


def model_set():
    m = {"prior season only": ["prior"]}
    for k in METRICS:
        m[f"{LABELS[k]} (1 yr)"] = [f"{k}_0"]
        m[f"{LABELS[k]} (2 yr)"] = [f"{k}_0", f"{k}_1"]
    for k in METRICS:
        m[f"prior + {LABELS[k]} (1 yr)"] = ["prior", f"{k}_0"]
        m[f"prior + {LABELS[k]} (2 yr)"] = ["prior", f"{k}_0", f"{k}_1"]
    m["prior + all five (1 yr)"] = ["prior"] + [f"{k}_0" for k in METRICS]
    m["prior + all five (2 yr)"] = ["prior"] + [f"{k}_{i}" for k in METRICS for i in (0, 1)]
    m["prior + consensus + top-50 (2 yr)"] = ["prior", "consensus_0", "consensus_1", "top50_0", "top50_1"]
    return m


def recruit_only_rho(rows, target):
    """No fitting: within-year Spearman of the raw metric, 1 year vs a plain 2-year sum."""
    out = {}
    years = sorted({r["year"] for r in rows if not math.isnan(r[target])})
    for k in METRICS:
        one, two = [], []
        for y in years:
            rs = [r for r in rows if r["year"] == y and not math.isnan(r[target])]
            tg = [r[target] for r in rs]
            one.append(spearmanr([r[f"{k}_0"] for r in rs], tg).statistic)
            two.append(spearmanr([r[f"{k}_0"] + r[f"{k}_1"] for r in rs], tg).statistic)
        out[k] = (float(np.mean(one)), float(np.mean(two)), len(years))
    return out


def in_sample_coefs(rows, target, cols):
    rs = [r for r in rows if not math.isnan(r[target])]
    X = design(rs, cols)
    beta = np.linalg.lstsq(X, np.array([r[target] for r in rs]), rcond=None)[0]
    sd = X[:, 1:].std(axis=0)
    return {c: (float(b), float(b * s)) for c, b, s in zip(cols, beta[1:], sd)}


def render(rows) -> str:
    L = ["# MBB recruiting: two-year windows and prior-season + recruiting models",
         "", "_Generated by `research_mbb_combo.py` — do not edit by hand._", "",
         "Outcome: barttorvik adjusted efficiency margin (adj. EM, points per 100 possessions).",
         "T1 = the class's freshman season; T2 = mean of its first two seasons. "
         "Rows: every D-I team with adj. EM in the prior season and the target season(s).",
         f"Rows built: {len(rows)} team-classes, class years {min(r['year'] for r in rows)}-"
         f"{max(r['year'] for r in rows)}.", ""]
    hi_major = lambda r: (r["consensus_0"] > -math.log(60)) or (r["consensus_1"] > -math.log(60))  # noqa: E731

    L += ["## 1. One class vs two classes (recruiting only, no fitting)", "",
          "Mean within-year Spearman ρ between the metric and the target, all D-I teams. "
          "Two-year = class y + class y-1 summed (for the consensus, the sum of −ln rank).", ""]
    for tgt, name in (("t1", "T1 (next season)"), ("t2", "T2 (next two seasons)")):
        rr = recruit_only_rho(rows, tgt)
        n = next(iter(rr.values()))[2]
        L += [f"**{name}** — {n} class years", "", "| metric | class y only | classes y + y−1 | change |",
              "|---|---:|---:|---:|"]
        for k, (a, b, _) in rr.items():
            L.append(f"| {LABELS[k]} | {a:.3f} | {b:.3f} | {b - a:+.3f} |")
        L.append("")

    for title, subset in (("all D-I teams", None),
                          ("programs with a top-60 consensus class in year y or y−1", hi_major)):
        L += [f"## 2. Walk-forward linear models — {title}", "",
              "RMSE in adj. EM points (lower is better), mean within-year ρ, and the RMSE change vs "
              "the prior-season-only model with a 95% interval from resampling test years "
              "(negative = better than prior alone).", ""]
        for tgt, name in (("t1", "T1 (next season)"), ("t2", "T2 (next two seasons)")):
            res = evaluate(rows, tgt, model_set(), subset)
            any_ = next(iter(res.values()))
            L += [f"**{name}** — test classes {any_['years'][0]}-{any_['years'][-1]} "
                  f"({len(any_['years'])} independent class years, {any_['n']} team-classes)", "",
                  "| model | RMSE | ρ | ΔRMSE vs prior | 95% interval |", "|---|---:|---:|---:|---:|"]
            for mname, s in res.items():
                ci = "" if math.isnan(s["lo"]) else f"[{s['lo']:+.2f}, {s['hi']:+.2f}]"
                d = "—" if mname == "prior season only" else f"{s['d_rmse']:+.2f}"
                L.append(f"| {mname} | {s['rmse']:.2f} | {s['rho']:.3f} | {d} | {ci} |")
            L.append("")

    L += ["## 3. Coefficients (in-sample, all class years — for interpretation only)", "",
          "Per standard deviation of each input, adj. EM points.", ""]
    for tgt, name in (("t1", "T1"), ("t2", "T2")):
        cols = ["prior", "consensus_0", "consensus_1", "top50_0", "top50_1"]
        co = in_sample_coefs(rows, tgt, cols)
        L += [f"**{name}**: " + ", ".join(f"{c} {v[1]:+.2f}" for c, v in co.items()), ""]

    L += ["## Caveats", "",
          "- One season ahead is dominated by the prior season (returning players); recruiting is "
          "the increment. Transfer-portal moves (2021+) are not modelled and are a large share of "
          "roster change.",
          "- The 2020-21 COVID season is included; class 2021 has only ~138 ranked recruits.",
          "- On3 consensus ranks before ~2021 are reconstructed today and may carry hindsight.",
          "- Linear models only; intervals resample test years but ignore other dependence.",
          ""]
    return "\n".join(L)


def main() -> None:
    rows = build_rows()
    (MODEL_DIR / "RESEARCH_MBB_COMBO.md").write_text(render(rows))
    print(f"wrote RESEARCH_MBB_COMBO.md ({len(rows)} rows)")


if __name__ == "__main__":
    main()
