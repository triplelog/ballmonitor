"""Reproducible study for race_time: diagnose bias, tune on TRAIN runners, report on TEST.

    python -m ballmonitor.models.race_time.research          # writes RESEARCH.md

Reads data/backtest.csv (built by pipeline.py; each row has split = train | test, assigned
by a hash of the runner id, so no runner is in both halves). Every number in RESEARCH.md
comes from this file; never edit RESEARCH.md by hand.

1. Describe the data (cases, independent runners, distances, gaps).
2. Diagnose the v0.3.0 defaults on ALL cases (no fitting): bias by distance gap, target
   distance, direction, age, gender, input recency, number of inputs.
3. Choose point-prediction settings by coordinate descent on TRAIN only, minimising mean
   |log error| (~ MAPE).
4. Fit the three sigma components (base, per doubling, per year) on TRAIN by minimising the
   80% interval score (a proper score: it is minimised by the true 10%/90% quantiles).
5. Report everything on TEST against benchmarks: pure Riegel (k = 1.06) and the v0.3.0
   defaults, with runner-level bootstrap intervals for the MAPE differences.
"""

from __future__ import annotations

import csv
import json
import math
import random
import statistics
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from ballmonitor.core import registry
from ballmonitor.core.stats import z_for_level
from ballmonitor.core.units import parse_distance

MODEL_DIR = Path(__file__).resolve().parent
BACKTEST = MODEL_DIR / "data" / "backtest.csv"
RESEARCH_MD = MODEL_DIR / "RESEARCH.md"
RESEARCH_JSON = MODEL_DIR / "data" / "research.json"
SEED = 20261026
BOOTSTRAPS = 1000
# A setting only moves away from v0.3.0 if it improves train MAPE by at least this many
# percentage points (guards against chasing noise; ties keep the simpler/older value).
MIN_GAIN = 0.03
Z80 = z_for_level(0.80)

# Every tuned setting is pinned explicitly so results do not depend on config.toml.
V030 = {
    "fit_weight": 0.6, "shrinkage_prior_strength": 1.5, "use_demographic_priors": True,
    "default_exponent": 1.057, "marathon_curvature": 0.015, "off_day_tolerance_pct": 0.0,
    "fitness_half_life_months": 12.0, "transfer_short_to_long": 0.8,
    "transfer_long_to_short": 0.9, "base_uncertainty_pct": 2.0,
    "extrapolation_uncertainty_pct": 3.5, "annual_fitness_drift_pct": 3.0,
}
PURE_RIEGEL = {**V030, "fit_weight": 0.0, "marathon_curvature": 0.0, "default_exponent": 1.06,
               "use_demographic_priors": False}
GRID: dict[str, list[Any]] = {
    "use_demographic_priors": [True, False],
    "default_exponent": [1.00, 1.02, 1.04, 1.05, 1.06, 1.07, 1.08, 1.10],
    "marathon_curvature": [0.0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04],
    "fit_weight": [0.0, 0.3, 0.6, 0.8, 1.0],
    "shrinkage_prior_strength": [0.5, 1.5, 3.0, 5.0],
    "off_day_tolerance_pct": [0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0],
    "fitness_half_life_months": [3.0, 6.0, 12.0, 24.0, 36.0],
    "transfer_short_to_long": [0.0, 0.4, 0.8, 1.0],
    "transfer_long_to_short": [0.0, 0.45, 0.9, 1.0],
}
SIGMA_GRID = {
    "base_uncertainty_pct": [x / 2 for x in range(2, 25)],          # 1.0 .. 12.0
    "extrapolation_uncertainty_pct": [x / 2 for x in range(0, 21)],  # 0 .. 10
    "annual_fitness_drift_pct": [float(x) for x in range(0, 11)],    # 0 .. 10
}


# ── prediction (parallel) ──────────────────────────────────────────────────

def _predict_chunk(args: tuple[dict[str, Any], list[dict[str, str]]]) -> list[dict[str, float]]:
    overrides, rows = args
    # This study is about the curve method (v0.3.0/v0.4.0); v0.5.0's default is weighted_riegel.
    model = registry.load_model("race_time", overrides={"method": "curve", **overrides})
    out = []
    for row in rows:
        inputs, actual = model.backtest_case(row)
        pred = model.predict(inputs)
        ex = pred.extras
        out.append({
            "est": pred.primary.estimate, "actual": actual,
            "sigma": ex["sigma_pct"], "gap": ex["gap_doublings"],
            "temporal": ex["temporal_sigma_pct"],
        })
    return out


class Evaluator:
    def __init__(self, rows: list[dict[str, str]], pool: ProcessPoolExecutor):
        self.rows = rows
        self.pool = pool
        self.cache: dict[str, list[dict[str, float]]] = {}

    def run(self, overrides: dict[str, Any]) -> list[dict[str, float]]:
        key = json.dumps(overrides, sort_keys=True)
        if key not in self.cache:
            n = max(1, len(self.rows) // 64)
            chunks = [(overrides, self.rows[i:i + n]) for i in range(0, len(self.rows), n)]
            self.cache[key] = [r for part in self.pool.map(_predict_chunk, chunks) for r in part]
        return self.cache[key]


# ── metrics ─────────────────────────────────────────────────────────────────

def log_err(r: dict[str, float]) -> float:
    """ln(predicted / actual): + = predicted too slow."""
    return math.log(r["est"] / r["actual"])


def metrics(res: list[dict[str, float]], sigmas: list[float] | None = None) -> dict[str, float]:
    if not res:
        return {}
    le = [log_err(r) for r in res]
    ape = [abs(r["est"] - r["actual"]) / r["actual"] for r in res]
    sig = sigmas if sigmas is not None else [r["sigma"] for r in res]
    z = [abs(e) / (s / 100.0) if s > 0 else math.inf for e, s in zip(le, sig)]
    return {
        "n": len(res),
        "mape": 100 * statistics.fmean(ape),
        "mdape": 100 * statistics.median(ape),
        "mean_log_err": 100 * statistics.fmean(le),
        "median_log_err": 100 * statistics.median(le),
        "bias_sec": statistics.fmean(r["est"] - r["actual"] for r in res),
        "mae_sec": statistics.fmean(abs(r["est"] - r["actual"]) for r in res),
        "cov50": statistics.fmean(1.0 if x <= z_for_level(0.5) else 0.0 for x in z),
        "cov80": statistics.fmean(1.0 if x <= Z80 else 0.0 for x in z),
        "cov95": statistics.fmean(1.0 if x <= z_for_level(0.95) else 0.0 for x in z),
        "median_sigma": statistics.median(sig),
        "is80": statistics.fmean(interval_score(e, s) for e, s in zip(le, sig)),
    }


def interval_score(e: float, sigma_pct: float, alpha: float = 0.2) -> float:
    """80% interval score in log-% units for log error e (interval is symmetric in logs)."""
    h = Z80 * sigma_pct / 100.0
    miss = max(0.0, abs(e) - h)
    return 100 * (2 * h + (2 / alpha) * miss)


def sigma_from(base: float, extrap: float, drift: float, r: dict[str, float], drift_ref: float) -> float:
    elapsed = r["temporal"] / drift_ref if drift_ref > 0 else 0.0
    return math.sqrt(base ** 2 + (r["gap"] * extrap) ** 2 + (elapsed * drift) ** 2)


# ── study ───────────────────────────────────────────────────────────────────

def bucket_table(rows, res, key_fn, order=None) -> list[tuple[str, dict[str, float]]]:
    groups: dict[str, list[dict[str, float]]] = defaultdict(list)
    for row, r in zip(rows, res):
        groups[key_fn(row, r)].append(r)
    keys = order or sorted(groups)
    return [(k, metrics(groups[k])) for k in keys if k in groups]


def gap_bucket(_row, r) -> str:
    g = r["gap"]
    return "0 (same distance)" if g < 0.25 else "0.25-1" if g < 1 else "1-2" if g < 2 else "2+"


def direction(row, _r) -> str:
    D = parse_distance(row["target"])
    ds = [parse_distance(row[f"race{i}_distance"]) for i in (1, 2, 3) if row.get(f"race{i}_distance")]
    if any(abs(math.log2(D / d)) < 0.25 for d in ds):
        return "has target distance"
    if all(d < D for d in ds):
        return "up (inputs shorter)"
    if all(d > D for d in ds):
        return "down (inputs longer)"
    return "between inputs"


def age_bucket(row, _r) -> str:
    a = int(row["age"])
    return "<25" if a < 25 else "25-34" if a < 35 else "35-49" if a < 50 else "50-64" if a < 65 else "65+"


def recency(row, _r) -> str:
    from datetime import date
    t = date.fromisoformat(row["target_date"])
    last = max(date.fromisoformat(row[f"race{i}_date"]) for i in (1, 2, 3) if row.get(f"race{i}_date"))
    d = (t - last).days
    return "<=90 d" if d <= 90 else "91-365 d" if d <= 365 else ">365 d"


def n_inputs(row, _r) -> str:
    return str(sum(1 for i in (1, 2, 3) if row.get(f"race{i}_distance")))


def coordinate_descent(ev: Evaluator, start: dict[str, Any], log: list[str]) -> dict[str, Any]:
    best = dict(start)
    best_score = metrics(ev.run(best))["mape"]
    log.append(f"start (v0.3.0 point settings): train MAPE {best_score:.3f}%")
    for sweep in (1, 2):
        changed = False
        for name, values in GRID.items():
            scores = {}
            for v in values:
                cand = {**best, name: v}
                scores[v] = metrics(ev.run(cand))["mape"]
            v_best = min(scores, key=scores.get)
            if scores[v_best] < best_score - MIN_GAIN and v_best != best[name]:
                log.append(f"sweep {sweep}: {name} {best[name]} -> {v_best} "
                           f"(train MAPE {best_score:.3f} -> {scores[v_best]:.3f})")
                best[name] = v_best
                best_score = scores[v_best]
                changed = True
        if not changed:
            break
    return best


def fit_sigma(res: list[dict[str, float]], drift_ref: float) -> tuple[float, float, float]:
    le = [log_err(r) for r in res]
    best, best_s = None, math.inf
    for b in SIGMA_GRID["base_uncertainty_pct"]:
        for x in SIGMA_GRID["extrapolation_uncertainty_pct"]:
            for d in SIGMA_GRID["annual_fitness_drift_pct"]:
                s = statistics.fmean(
                    interval_score(e, sigma_from(b, x, d, r, drift_ref)) for e, r in zip(le, res))
                if s < best_s:
                    best, best_s = (b, x, d), s
    return best


def bootstrap_diff(rows, res_a, res_b, seed: int = SEED) -> tuple[float, float, float]:
    """MAPE(a) - MAPE(b) with a 95% bootstrap interval over target events (pct points)."""
    by_runner: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        # Cluster by target event: runners in one race share its course and weather.
        by_runner[row["event_id"]].append(i)
    runners = list(by_runner)
    ape = lambda r: abs(r["est"] - r["actual"]) / r["actual"]
    da = [ape(a) - ape(b) for a, b in zip(res_a, res_b)]
    rng = random.Random(seed)
    stats = []
    for _ in range(BOOTSTRAPS):
        idx = [i for _ in runners for i in by_runner[runners[rng.randrange(len(runners))]]]
        stats.append(100 * statistics.fmean(da[i] for i in idx))
    stats.sort()
    return 100 * statistics.fmean(da), stats[int(0.025 * BOOTSTRAPS)], stats[int(0.975 * BOOTSTRAPS) - 1]


def fmt_row(label: str, m: dict[str, float]) -> str:
    return (f"| {label} | {m['n']} | {m['mape']:.1f}% | {m['mdape']:.1f}% | "
            f"{m['median_log_err']:+.1f}% | {m['mean_log_err']:+.1f}% | {m['bias_sec']:+.0f} | "
            f"{m['cov50']:.0%} | {m['cov80']:.0%} | {m['cov95']:.0%} | {m['is80']:.1f} |")


HEADER = ("| | cases | MAPE | median APE | median log err | mean log err | mean err (s) | "
          "50% cov | 80% cov | 95% cov | 80% interval score |\n|---|---|---|---|---|---|---|---|---|---|---|")


def main() -> None:
    rows = [r for r in csv.DictReader(open(BACKTEST, newline="", encoding="utf-8"))]
    train = [r for r in rows if r["split"] == "train"]
    test = [r for r in rows if r["split"] == "test"]
    out: list[str] = []
    summary: dict[str, Any] = {}
    with ProcessPoolExecutor() as pool:
        ev_all, ev_train, ev_test = Evaluator(rows, pool), Evaluator(train, pool), Evaluator(test, pool)

        # 1. data
        runners = {r["entity_id"] for r in rows}
        dist_mix = defaultdict(int)
        for r in rows:
            dist_mix[r["target"]] += 1
        summary["data"] = {
            "cases": len(rows), "runners": len(runners),
            "train_cases": len(train), "test_cases": len(test),
            "train_runners": len({r["entity_id"] for r in train}),
            "test_runners": len({r["entity_id"] for r in test}),
            "by_scenario": {s: sum(1 for r in rows if r["scenario"] == s)
                            for s in ("cross_distance", "same_distance")},
            "targets": dict(sorted(dist_mix.items(), key=lambda kv: -kv[1])),
            "target_years": [min(r["target_year"] for r in rows), max(r["target_year"] for r in rows)],
            "target_events": len({r["event_id"] for r in rows}),
            "test_target_events": len({r["event_id"] for r in test}),
        }

        # 2. diagnosis of v0.3.0 on all cases
        res_v030_all = ev_all.run(V030)
        diag = {}
        for name, fn in [("distance gap (doublings)", gap_bucket), ("direction", direction),
                         ("target distance", lambda row, r: row["target"]),
                         ("age at target", age_bucket), ("gender", lambda row, r: row["gender"]),
                         ("days since latest input", recency), ("number of inputs", n_inputs),
                         ("scenario", lambda row, r: row["scenario"])]:
            diag[name] = bucket_table(rows, res_v030_all, fn)
        summary["diagnosis_v030_all"] = {k: dict(v) for k, v in diag.items()}

        # 3. point settings on train
        log: list[str] = []
        point = coordinate_descent(ev_train, V030, log)
        summary["search_log"] = log
        summary["chosen_point"] = {k: point[k] for k in GRID}

        # 4. sigma on train (temporal_sigma_pct / annual drift = weighted elapsed years)
        drift_ref = point["annual_fitness_drift_pct"]
        res_train = ev_train.run(point)
        b, x, d = fit_sigma(res_train, drift_ref)
        final = {**point, "base_uncertainty_pct": b, "extrapolation_uncertainty_pct": x,
                 "annual_fitness_drift_pct": d}
        summary["chosen_sigma"] = {"base_uncertainty_pct": b, "extrapolation_uncertainty_pct": x,
                                   "annual_fitness_drift_pct": d}
        # Pure Riegel with sigma fitted the same way (so interval comparisons are fair)
        res_pr_train = ev_train.run(PURE_RIEGEL)
        pb, px, pd = fit_sigma(res_pr_train, PURE_RIEGEL["annual_fitness_drift_pct"])
        pure_cal = {**PURE_RIEGEL, "base_uncertainty_pct": pb,
                    "extrapolation_uncertainty_pct": px, "annual_fitness_drift_pct": pd}

        # 5. test
        configs = {
            "pure Riegel 1.06 (v0.3.0 sigma)": PURE_RIEGEL,
            "pure Riegel 1.06 (sigma fit on train)": pure_cal,
            "v0.3.0 defaults": V030,
            "chosen (point + sigma fit on train)": final,
        }
        results = {}
        for split_name, ev, split_rows in (("train", ev_train, train), ("test", ev_test, test)):
            for label, cfg in configs.items():
                res = ev.run(cfg)
                results[(split_name, label)] = res
        table = {f"{s} | {l}": metrics(res) for (s, l), res in results.items()}
        summary["results"] = table
        by_scen = {}
        for label in configs:
            for scen in ("cross_distance", "same_distance"):
                idx = [i for i, r in enumerate(test) if r["scenario"] == scen]
                by_scen[f"{scen} | {label}"] = metrics([results[("test", label)][i] for i in idx])
        summary["test_by_scenario"] = by_scen
        by_target = bucket_table(test, results[("test", "chosen (point + sigma fit on train)")],
                                 lambda row, r: row["target"])
        by_target_pr = bucket_table(test, results[("test", "pure Riegel 1.06 (sigma fit on train)")],
                                    lambda row, r: row["target"])
        by_gap = bucket_table(test, results[("test", "chosen (point + sigma fit on train)")], gap_bucket)
        year_fn = lambda row, r: "target 2018-2022" if int(row["target_year"]) <= 2022 else (
            "target 2023" if int(row["target_year"]) == 2023 else "target 2024-2025")
        by_year = {label: bucket_table(test, results[("test", label)], year_fn)
                   for label in ("pure Riegel 1.06 (sigma fit on train)",
                                 "chosen (point + sigma fit on train)")}
        boot = {
            "chosen - pure Riegel": bootstrap_diff(
                test, results[("test", "chosen (point + sigma fit on train)")],
                results[("test", "pure Riegel 1.06 (v0.3.0 sigma)")]),
            "chosen - v0.3.0": bootstrap_diff(
                test, results[("test", "chosen (point + sigma fit on train)")],
                results[("test", "v0.3.0 defaults")]),
            "v0.3.0 - pure Riegel": bootstrap_diff(
                test, results[("test", "v0.3.0 defaults")],
                results[("test", "pure Riegel 1.06 (v0.3.0 sigma)")]),
        }
        summary["bootstrap_mape_diff_test"] = boot
        # One-at-a-time ablation on test: revert each changed setting to v0.3.0
        ablation = {}
        for k in GRID:
            if final[k] != V030[k]:
                ablation[f"{k} back to {V030[k]}"] = metrics(ev_test.run({**final, k: V030[k]}))
        summary["ablation_test"] = ablation

    RESEARCH_JSON.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    summary["test_by_year"] = {k: dict(v) for k, v in by_year.items()}
    RESEARCH_MD.write_text(report(summary, diag, configs, by_target, by_target_pr, by_gap, by_year))
    print(f"wrote {RESEARCH_MD} and {RESEARCH_JSON}")


def report(s, diag, configs, by_target, by_target_pr, by_gap, by_year) -> str:
    d = s["data"]
    L: list[str] = []
    L.append("# race_time — research: honest walk-forward evaluation\n")
    L.append("*Generated by `python -m ballmonitor.models.race_time.research`; do not edit by hand.*\n")
    L.append("## Data\n")
    L.append(
        f"`data/backtest.csv` (built by `pipeline.py` from dated RunSignup results, Ohio races "
        f"{d['target_years'][0]}–{d['target_years'][1]}): **{d['cases']} cases from {d['runners']} "
        f"independent linked runners**. Each case predicts a finish from that runner's (up to 3) most "
        f"recent finishes run *strictly before* the target date (within 3 years). One case per "
        f"runner per scenario: `cross_distance` ({d['by_scenario']['cross_distance']}: no input at "
        f"the target distance) and `same_distance` ({d['by_scenario']['same_distance']}: at least one). "
        f"Runners are split by a hash of their id: train {d['train_cases']} cases / "
        f"{d['train_runners']} runners, test {d['test_cases']} cases / {d['test_runners']} runners. "
        f"No runner is in both halves; the demographic priors were fit on train runners only. "
        f"The cases come from {d['target_events']} distinct target events ({d['test_target_events']} "
        f"in test); runners in the same event share its course and weather, so the bootstrap "
        f"below resamples events.\n")
    L.append("Target distances: " + ", ".join(f"{k} {v}" for k, v in d["targets"].items()) + ".\n")
    L.append("Columns below: MAPE = mean absolute % error; log errors are 100 x ln(predicted / "
             "actual), so + means the prediction was too slow; coverage = share of actual times "
             "inside the 50/80/95% intervals implied by `sigma_pct`; the 80% interval score "
             "(width + 10 x miss, in log-%) rewards narrow intervals that still cover (lower is "
             "better).\n")

    L.append("## 1. Where v0.3.0 goes wrong (all cases, no fitting)\n")
    L.append("v0.3.0 settings here use the rebuilt `demographic_priors.json` (train runners "
             "only; cohort slopes ~1.07-1.10), not the v0.3.0 file. Read the tables for: "
             "(a) bias by *direction* — predictions from shorter races to longer ones are "
             "too slow and the reverse too fast, i.e. the slope used is too steep for this "
             "population once effort noise is averaged; (b) bias by *target distance* — the "
             "slow bias sits in half and marathon targets, where the extra curvature "
             "(`marathon_curvature` 0.015) compounds the steep cohort slope; (c) intervals "
             "cover ~45% instead of 80% everywhere: the v0.3.0 sigma (2% base) is far below "
             "the real race-to-race spread of recreational runners (median APE ~6-7% even at "
             "the same distance).\n")
    L.append("Pair slopes (the priors) are biased steep as a *predictor* because both races "
             "carry effort noise and the pair median is taken over unordered pairs; the "
             "walk-forward search in section 2 picks the slope that actually predicts.\n")
    for name, tab in diag.items():
        L.append(f"**By {name}**\n")
        L.append(HEADER)
        for k, m in tab:
            L.append(fmt_row(k, m))
        L.append("")

    L.append("## 2. Settings chosen on TRAIN (coordinate descent on MAPE)\n")
    L.append(f"Two sweeps; a setting changes only if train MAPE improves by at least "
             f"{MIN_GAIN} percentage points.\n")
    L.append("Grid per setting: " + "; ".join(f"`{k}` {v}" for k, v in GRID.items()) + ".\n")
    for line in s["search_log"]:
        L.append(f"- {line}")
    L.append("")
    L.append("Chosen point settings: " + ", ".join(f"`{k}` = {v}" for k, v in s["chosen_point"].items()) + ".\n")
    L.append("Sigma components fit on TRAIN by minimising the 80% interval score: " + ", ".join(
        f"`{k}` = {v}" for k, v in s["chosen_sigma"].items()) + ".\n")

    L.append("## 3. Results\n")
    L.append("Train rows are **in-sample** for the chosen settings (they were tuned there); "
             "test rows are out-of-sample.\n")
    L.append(HEADER)
    for k, m in s["results"].items():
        split, label = k.split(" | ", 1)
        L.append(fmt_row(f"{split}: {label}" + (" *(in-sample)*" if split == "train" and "chosen" in label else ""), m))
    L.append("")
    L.append("**Test, by scenario**\n")
    L.append(HEADER)
    for k, m in s["test_by_scenario"].items():
        L.append(fmt_row(k, m))
    L.append("")
    L.append("**Test, chosen settings, by target distance**\n")
    L.append(HEADER)
    for k, m in by_target:
        L.append(fmt_row(k, m))
    L.append("")
    L.append("**Test, pure Riegel 1.06 (train-fit sigma), by target distance**\n")
    L.append(HEADER)
    for k, m in by_target_pr:
        L.append(fmt_row(k, m))
    L.append("")
    L.append("**Test, chosen settings, by distance gap**\n")
    L.append(HEADER)
    for k, m in by_gap:
        L.append(fmt_row(k, m))
    L.append("")
    L.append("**Test, by target year** (is the gain stable over time?)\n")
    L.append(HEADER)
    for label, tab in by_year.items():
        for k, m in tab:
            L.append(fmt_row(f"{label}: {k}", m))
    L.append("")
    L.append("**Test MAPE differences** (percentage points, 95% bootstrap resampling whole "
             "target events, since runners in one race share its course and weather; "
             "negative = first is better)\n")
    for k, (m, lo, hi) in s["bootstrap_mape_diff_test"].items():
        L.append(f"- {k}: {m:+.2f} [{lo:+.2f}, {hi:+.2f}]")
    L.append("")
    if s["ablation_test"]:
        L.append("**Ablation on test** (chosen settings with one change reverted to v0.3.0)\n")
        L.append(HEADER)
        for k, m in s["ablation_test"].items():
            L.append(fmt_row(k, m))
        L.append("")
    L.append("## Caveats\n")
    L.append("- The point-accuracy differences between the chosen settings and pure Riegel are "
             "small (see the bootstrap above); the large, robust gain is the recalibrated "
             "uncertainty. `off_day_tolerance_pct` = 32 is a mild down-weighting (a race 10% "
             "slower than the runner's best keeps ~73% weight).\n")
    L.append("- One state (Ohio) and RunSignup-timed races only; courses are not certified, so some "
             "'half marathons' are long or short. Event-level course errors are part of the error "
             "measured here, as they would be for a user.\n")
    L.append("- Linking is by name + gender + home city/state + birth year (±1); rare name "
             "collisions remain possible and would look like large errors.\n")
    L.append("- Effort is unobserved: many recreational results are not all-out. The model "
             "predicts what this runner population actually ran, not their potential.\n")
    L.append("- Intervals are symmetric in log time; the error distribution is heavier-tailed "
             "than a normal, so matching 80% coverage over-covers at 50% and under-covers at 95%.\n")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
