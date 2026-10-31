"""Simple Riegel variants vs the current model.  Writes RESEARCH_SIMPLE.md (generated).

    python ballmonitor/models/race_time/research_simple.py

Data: data/backtest.csv (built by pipeline.py; see RESEARCH.md) — 5,000 runners, each
predicted from up to 3 earlier races; runners split train/test by id hash. Everything
below is fitted on train runners and scored once on test runners.

Riegel from one race:  T = t * (D / d) ** b
Methods
  A  b = 1.06, most recent race
  B  b = 1.06, race closest in (log) distance
  C  b = 1.06, weighted geometric mean over all races,
       w_i = exp(-|ln(D/d_i)| / lam) * 0.5 ** (years_before_target_i / half_life)
  D  C + personal exponent: least-squares slope of ln t on ln d over the runner's
       races (needs >= 2 distances), shrunk to 1.06 with k pseudo-races
  E  C with b = b0 + b_f * female + b_a * (age-40)/10 + b_a2 * ((age-40)/10)^2
  F  E + ability (ln of the race's Riegel-equivalent 5K minutes) + direction (up/down)
  G  F with the personal exponent of D shrunk toward F's exponent
  M  the current model (config defaults)
E/F coefficients come from ordinary least squares on train races:
  ln(T / t_i) = c + b * x_i + sum_k beta_k * z_k * x_i,  x_i = ln(D / d_i)
(c absorbs average form change; it is used in prediction too).
"""

from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

MODEL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODEL_DIR.parent.parent.parent))
from ballmonitor.core import registry  # noqa: E402
from ballmonitor.core.units import parse_distance, parse_time  # noqa: E402

B0 = 1.06
BOOT = 1000
FIVE_K = 5000.0


def load():
    rows = []
    with open(MODEL_DIR / "data" / "backtest.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            races = []
            for i in (1, 2, 3):
                if r[f"race{i}_distance"]:
                    races.append({"d": parse_distance(r[f"race{i}_distance"]), "t": parse_time(r[f"race{i}_time"]),
                                  "date": date.fromisoformat(r[f"race{i}_date"])})
            rows.append({"raw": r, "split": r["split"], "scenario": r["scenario"], "event": r["event_id"],
                         "female": r["gender"] == "F", "age": float(r["age"]) if r["age"] else 40.0,
                         "D": parse_distance(r["target"]), "T": parse_time(r["actual_time"]),
                         "date": date.fromisoformat(r["target_date"]), "races": races})
    for row in rows:
        for rc in row["races"]:
            rc["x"] = math.log(row["D"] / rc["d"])
            rc["yrs"] = (row["date"] - rc["date"]).days / 365.25
            rc["ability"] = math.log(rc["t"] * (FIVE_K / rc["d"]) ** B0 / 60.0)
    return rows


def weights(row, lam, half):
    return np.array([math.exp(-abs(rc["x"]) / lam) * 0.5 ** (rc["yrs"] / half) for rc in row["races"]])


def combine(row, exps, lam, half, c=0.0):
    w = weights(row, lam, half)
    logs = np.array([math.log(rc["t"]) + b * rc["x"] + c for rc, b in zip(row["races"], exps)])
    return float(math.exp((w * logs).sum() / w.sum()))


def personal_slope(row, half):
    ds = {rc["d"] for rc in row["races"]}
    if len(ds) < 2:
        return None, 0
    x = np.array([math.log(rc["d"]) for rc in row["races"]])
    y = np.array([math.log(rc["t"]) for rc in row["races"]])
    w = np.array([0.5 ** (rc["yrs"] / half) for rc in row["races"]])
    xm, ym = (w * x).sum() / w.sum(), (w * y).sum() / w.sum()
    slope = (w * (x - xm) * (y - ym)).sum() / (w * (x - xm) ** 2).sum()
    return float(slope), len(ds)


def features(row, rc, with_ability):
    a = (row["age"] - 40.0) / 10.0
    z = [1.0 if row["female"] else 0.0, a, a * a]
    if with_ability:
        z += [rc["ability"] - 3.3, 1.0 if rc["x"] > 0 else 0.0]  # 3.3 ~ ln(27 min)
    return z


def fit_exponent_model(train, with_ability):
    X, y = [], []
    for row in train:
        for rc in row["races"]:
            z = features(row, rc, with_ability)
            X.append([1.0, rc["x"]] + [zi * rc["x"] for zi in z])
            y.append(math.log(row["T"] / rc["t"]))
    beta = np.linalg.lstsq(np.array(X), np.array(y), rcond=None)[0]
    return beta  # c, b0, betas...


def exps_from(beta, row, with_ability):
    out = []
    for rc in row["races"]:
        z = features(row, rc, with_ability)
        out.append(float(beta[1] + sum(bk * zk for bk, zk in zip(beta[2:], z))))
    return out


def shrink_personal(row, prior_exps, k, half):
    s, n = personal_slope(row, half)
    if s is None:
        return prior_exps
    return [(n * s + k * p) / (n + k) for p in prior_exps]


def ape(pred, row):
    return abs(pred - row["T"]) / row["T"]


def score(preds, rows):
    e = np.array([ape(p, r) for p, r in zip(preds, rows)])
    le = np.array([math.log(p / r["T"]) for p, r in zip(preds, rows)])
    return {"mape": float(e.mean() * 100), "medape": float(np.median(e) * 100), "bias": float(le.mean() * 100)}


def grid_best(rows, fn, grid):
    best = None
    for g in grid:
        m = np.mean([ape(fn(r, *g), r) for r in rows])
        if best is None or m < best[0]:
            best = (m, g)
    return best[1]


def boot_diff(a, b, rows):
    """Paired MAPE difference a - b (pp) with a 95% interval resampling target events."""
    by_ev = defaultdict(list)
    for i, r in enumerate(rows):
        by_ev[r["event"]].append(i)
    evs = list(by_ev)
    d = np.array([ape(pa, r) - ape(pb, r) for pa, pb, r in zip(a, b, rows)]) * 100
    rng = np.random.default_rng(0)
    bs = []
    for _ in range(BOOT):
        idx = [i for e in rng.choice(evs, len(evs)) for i in by_ev[e]]
        bs.append(d[idx].mean())
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def current_model_preds(rows):
    model = registry.load_model("race_time", overrides={"method": "curve"})  # v0.4.0 method
    out = []
    for r in rows:
        inputs, _ = model.backtest_case(r["raw"])
        out.append(model.predict(inputs).outcomes[0].estimate)
    return out


def main() -> None:
    rows = load()
    train = [r for r in rows if r["split"] == "train"]
    test = [r for r in rows if r["split"] == "test"]
    cross_train = [r for r in train if r["scenario"] == "cross_distance"]

    lam_grid = [(lam, h) for lam in (0.25, 0.5, 1.0, 2.0, 1e9) for h in (0.25, 0.5, 1.0, 2.0, 1e9)]
    lam, half = grid_best(train, lambda r, l, h: combine(r, [B0] * len(r["races"]), l, h), lam_grid)
    k_grid = [(k,) for k in (0.5, 1, 2, 4, 8, 16, 1e9)]
    k_d = grid_best(cross_train, lambda r, k: combine(r, shrink_personal(r, [B0] * len(r["races"]), k, half), lam, half),
                    k_grid)[0]
    beta_e = fit_exponent_model(cross_train, False)
    beta_f = fit_exponent_model(cross_train, True)
    k_g = grid_best(cross_train, lambda r, k: combine(
        r, shrink_personal(r, exps_from(beta_f, r, True), k, half), lam, half, beta_f[0]), k_grid)[0]

    methods = {
        "A  Riegel 1.06, most recent race": lambda r: (lambda rc: rc["t"] * (r["D"] / rc["d"]) ** B0)(
            max(r["races"], key=lambda rc: rc["date"])),
        "B  Riegel 1.06, closest distance": lambda r: (lambda rc: rc["t"] * (r["D"] / rc["d"]) ** B0)(
            min(r["races"], key=lambda rc: (abs(rc["x"]), -rc["date"].toordinal()))),
        "C  Riegel 1.06, weighted average of all races": lambda r: combine(r, [B0] * len(r["races"]), lam, half),
        "D  C + personal exponent (shrunk to 1.06)": lambda r: combine(
            r, shrink_personal(r, [B0] * len(r["races"]), k_d, half), lam, half),
        "E  C + age/gender exponent": lambda r: combine(r, exps_from(beta_e, r, False), lam, half, beta_e[0]),
        "F  E + ability and direction": lambda r: combine(r, exps_from(beta_f, r, True), lam, half, beta_f[0]),
        "G  F + personal exponent": lambda r: combine(
            r, shrink_personal(r, exps_from(beta_f, r, True), k_g, half), lam, half, beta_f[0]),
    }
    preds = {name: [fn(r) for r in test] for name, fn in methods.items()}
    preds["M  current model (v0.4.0 defaults)"] = current_model_preds(test)

    L = ["# race_time: simple Riegel variants vs the current model", "",
         "_Generated by `research_simple.py` — do not edit by hand._", "",
         f"Fitted on {len(train)} train runners ({len(cross_train)} cross-distance), scored once on "
         f"{len(test)} test runners (one target race each). Intervals resample target events "
         f"({len({r['event'] for r in test})} events in test).", "",
         f"Fitted: race weights lam = {lam:g}, half-life = {half:g} years; personal-exponent "
         f"shrinkage k = {k_d:g} (D) / {k_g:g} (G) pseudo-races.", "",
         "Age/gender exponent (E): b = {:.4f} {:+.4f}·female {:+.4f}·(age−40)/10 {:+.4f}·((age−40)/10)²; "
         "form term c = {:+.4f}.".format(beta_e[1], *beta_e[2:5], beta_e[0]), "",
         "F adds {:+.4f}·(ability − 3.3) {:+.4f}·[predicting up in distance] to the exponent "
         "(ability = ln of the race's Riegel-1.06 5K equivalent in minutes; + = slower runners "
         "fade more); b0 {:.4f}, female {:+.4f}, age {:+.4f}, age² {:+.4f}, c {:+.4f}.".format(
             beta_f[5], beta_f[6], beta_f[1], beta_f[2], beta_f[3], beta_f[4], beta_f[0]), ""]
    for scen, title in ((None, "All test runners"), ("cross_distance", "Predicting a different distance"),
                        ("same_distance", "Predicting the same distance again")):
        idx = [i for i, r in enumerate(test) if scen is None or r["scenario"] == scen]
        rs = [test[i] for i in idx]
        L += [f"## {title} ({len(rs)})", "",
              "| method | MAPE | median APE | bias (mean log error) | Δ MAPE vs A [95%] | Δ MAPE vs current model [95%] |",
              "|---|---:|---:|---:|---:|---:|"]
        a_p = [preds["A  Riegel 1.06, most recent race"][i] for i in idx]
        m_p = [preds["M  current model (v0.4.0 defaults)"][i] for i in idx]
        for name, ps in preds.items():
            p = [ps[i] for i in idx]
            s = score(p, rs)
            da = "—" if name.startswith("A ") else "{:+.2f} [{:+.2f}, {:+.2f}]".format(*boot_diff(p, a_p, rs))
            dm = "—" if name.startswith("M ") else "{:+.2f} [{:+.2f}, {:+.2f}]".format(*boot_diff(p, m_p, rs))
            L.append(f"| {name} | {s['mape']:.2f}% | {s['medape']:.2f}% | {s['bias']:+.2f}% | {da} | {dm} |")
        L.append("")
    L += ["## Caveats", "",
          "- One state (Ohio), uncertified courses, unobserved effort and weather (see RESEARCH.md).",
          "- Bias = mean of ln(predicted / actual) × 100 (+ = too slow).",
          ""]
    (MODEL_DIR / "RESEARCH_SIMPLE.md").write_text("\n".join(L))
    print("wrote RESEARCH_SIMPLE.md")


if __name__ == "__main__":
    main()
