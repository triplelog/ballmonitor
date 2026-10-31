"""Empirical uncertainty bands for the weighted Riegel method.  Writes RESEARCH_BANDS.md.

    python -m ballmonitor.models.race_time.research_bands      # needs numpy + scipy

Data: data/backtest.csv (built by pipeline.py; see RESEARCH.md) — 5,000 independent Ohio
runners, each predicted from up to 3 races run strictly before the target; split
train/test by a hash of the runner id. Everything is fitted on TRAIN runners only and
scored once on TEST runners. RESEARCH_BANDS.md is generated — never edit it by hand.

1. Exponent: Riegel b for the weighted Riegel point (race weights from config.toml,
   chosen in research_simple.py), per gender and pooled, minimising train MAPE. Kept per
   gender only if it improves the median's calibration by gender x direction on train.
2. Bands: linear quantile regression (pinball loss, solved as a linear programme) of the
   log error e = ln(actual / point) at 2.5/10/25/50/75/90/97.5% on
       gap   = weighted mean |ln(D / d_i)|  (same weights as the point)
       years = years since the most recent race, capped at 3
       1 / races, races capped at 3
   A gap-only quantile model is fitted too, for comparison.
3. Test: the model itself (config.toml defaults, end to end) — coverage of the 50/80/95%
   bands overall and by gap, target distance, scenario, gender, races and recency; MAPE
   and bias of the median; interval scores. Same for v0.4.0 (method = curve), with
   event-bootstrap intervals for the differences.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linprog

from ballmonitor.core import registry
from ballmonitor.models.race_time.bands import (
    BAND_FEATURES,
    MEDIAN_INDEX,
    QUANTILE_KEYS,
    QUANTILE_LEVELS,
    Race,
    interval_at,
    param_name,
    weighted_riegel,
)

MODEL_DIR = Path(__file__).resolve().parent
BACKTEST = MODEL_DIR / "data" / "backtest.csv"
OUT_MD = MODEL_DIR / "RESEARCH_BANDS.md"
OUT_JSON = MODEL_DIR / "data" / "bands_fit.json"
EXP_GRID = [round(1.00 + 0.01 * i, 2) for i in range(13)]  # 1.00 .. 1.12
YEARS_CAP = 3.0
RACES_CAP = 3
BOOT = 1000
SEED = 20261026
LEVELS = (0.5, 0.8, 0.95)


# ── data ────────────────────────────────────────────────────────────────────

def load_cases() -> list[dict[str, Any]]:
    model = registry.load_model("race_time")
    cases = []
    with open(BACKTEST, newline="") as fh:
        for row in csv.DictReader(fh):
            inputs, actual = model.backtest_case(row)
            prep = model.prepare(inputs)
            races = [Race(r["distance"], r["time"], prep.years_before(r)) for r in prep.races]
            D = prep.target
            cases.append({
                "row": row, "inputs": inputs, "split": row["split"], "scenario": row["scenario"],
                "event": row["event_id"], "gender": row["gender"], "D": D, "T": actual,
                "races": races, "target": row["target"],
                "years": min(r.years_before for r in races),
                "up": D > max(r.distance for r in races) * 1.01,
                "down": D < min(r.distance for r in races) / 1.01,
            })
    return cases


def point_and_gap(case: dict[str, Any], b: float, p: Any) -> tuple[float, float]:
    wr = weighted_riegel(case["races"], case["D"], b, p)
    return wr.point, wr.gap


# ── fitting ─────────────────────────────────────────────────────────────────

def mape_for(cases, b, p) -> float:
    return float(np.mean([abs(point_and_gap(c, b, p)[0] / c["T"] - 1) for c in cases]) * 100)


def best_exponent(cases, p) -> tuple[float, float]:
    scores = [(mape_for(cases, b, p), b) for b in EXP_GRID]
    m, b = min(scores)
    return b, m


def features(case, gap) -> list[float]:
    return [1.0, gap, min(case["years"], YEARS_CAP), 1.0 / min(len(case["races"]), RACES_CAP)]


def quantile_regression(X: np.ndarray, y: np.ndarray, tau: float) -> np.ndarray:
    """Minimise the pinball loss sum(tau * u + (1 - tau) * v), X beta + u - v = y."""
    n, k = X.shape
    c = np.concatenate([np.zeros(k), tau * np.ones(n), (1 - tau) * np.ones(n)])
    A = np.hstack([X, np.eye(n), -np.eye(n)])
    res = linprog(c, A_eq=A, b_eq=y, bounds=[(None, None)] * k + [(0, None)] * (2 * n),
                  method="highs")
    if not res.success:
        raise RuntimeError(res.message)
    return res.x[:k]


# ── scoring ─────────────────────────────────────────────────────────────────

def _predict_chunk(args):
    overrides, inputs_list = args
    model = registry.load_model("race_time", overrides=overrides)
    out = []
    for inputs in inputs_list:
        pred = model.predict(inputs)
        out.append(pred.extras["_target_quantiles_sec"])
    return out


def model_quantiles(cases, overrides, pool) -> list[list[float]]:
    chunks = [cases[i::8] for i in range(8)]
    results = list(pool.map(_predict_chunk, [(overrides, [c["inputs"] for c in ch]) for ch in chunks]))
    out: list[Any] = [None] * len(cases)
    for i, res in enumerate(results):
        for j, q in enumerate(res):
            out[i + 8 * j] = q
    return out


def interval_score(lo: float, hi: float, y: float, level: float) -> float:
    """Interval score in log-% units (lower = better; minimised by the true quantiles)."""
    a = 1 - level
    l, u, v = math.log(lo), math.log(hi), math.log(y)
    return 100 * ((u - l) + 2 / a * max(0.0, l - v) + 2 / a * max(0.0, v - u))


def case_metrics(q: list[float], y: float) -> dict[str, float]:
    med = q[MEDIAN_INDEX]
    m = {"ape": abs(med / y - 1) * 100, "log_err": math.log(med / y) * 100,
         "below": float(y < med)}
    for lv in LEVELS:
        lo, hi = interval_at(q, lv)
        m[f"in{int(lv * 100)}"] = float(lo <= y <= hi)
        m[f"is{int(lv * 100)}"] = interval_score(lo, hi, y, lv)
        m[f"w{int(lv * 100)}"] = (hi / lo - 1) * 100
    return m


def summarise(ms: list[dict[str, float]]) -> dict[str, float]:
    keys = ms[0].keys()
    s = {k: float(np.mean([m[k] for m in ms])) for k in keys}
    s["medape"] = float(np.median([m["ape"] for m in ms]))
    s["n"] = len(ms)
    return s


def boot_diff(a: list[float], b: list[float], events: list[str]) -> tuple[float, float, float]:
    by = defaultdict(list)
    for i, e in enumerate(events):
        by[e].append(i)
    evs = list(by)
    d = np.array(a) - np.array(b)
    rng = np.random.default_rng(SEED)
    bs = []
    for _ in range(BOOT):
        idx = [i for e in rng.choice(evs, len(evs)) for i in by[e]]
        bs.append(d[idx].mean())
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def gap_bucket(g: float) -> str:
    for hi, name in ((0.01, "0 (same distance)"), (0.5, "0-0.5"), (1.0, "0.5-1.0"),
                     (1.5, "1.0-1.5")):
        if g < hi:
            return name
    return "1.5+"


def years_bucket(y: float) -> str:
    return "< 0.5 y" if y < 0.5 else "0.5-1.5 y" if y < 1.5 else "1.5-3 y"


# ── report ──────────────────────────────────────────────────────────────────

def fmt_cov(s: dict[str, float]) -> str:
    return (f"| {s['n']} | {s['in50'] * 100:.1f}% | {s['in80'] * 100:.1f}% | {s['in95'] * 100:.1f}% "
            f"| {s['below'] * 100:.1f}% | {s['ape']:.2f}% | {s['log_err']:+.2f}% |")


def cov_table(title: str, keys: list[str], groups: dict[str, list[dict[str, float]]]) -> list[str]:
    L = [f"### {title}", "",
         "| group | n | 50% band | 80% band | 95% band | actual below median | MAPE | bias |",
         "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k in keys:
        if groups.get(k):
            L.append(f"| {k} " + fmt_cov(summarise(groups[k])))
    return L + [""]


def main() -> None:
    cases = load_cases()
    train = [c for c in cases if c["split"] == "train"]
    test = [c for c in cases if c["split"] == "test"]
    model = registry.load_model("race_time")
    p = model.params
    L: list[str] = ["# race_time: empirical uncertainty bands (weighted Riegel)", "",
                    "_Generated by `research_bands.py` — do not edit by hand._", ""]
    L += [f"Data: `data/backtest.csv` — {len(train)} train runners and {len(test)} test runners "
          f"(one target race each, inputs strictly before the target; {len({c['event'] for c in test})} "
          "distinct target events in test). Everything below is fitted on train and scored once "
          "on test. Race weights: `race_weight_distance_scale` = "
          f"{p.race_weight_distance_scale:g}, `race_weight_half_life_years` = "
          f"{p.race_weight_half_life_years:g} (chosen on train in RESEARCH_SIMPLE.md).", ""]

    # 1. exponent
    fem = [c for c in train if c["gender"] == "F"]
    men = [c for c in train if c["gender"] == "M"]
    b_all, m_all = best_exponent(train, p)
    b_f, m_f = best_exponent(fem, p)
    b_m, m_m = best_exponent(men, p)
    b_of = {"F": b_f, "M": b_m}
    L += ["## 1. Riegel exponent (train)", "",
          "Grid 1.00–1.12 (step 0.01), minimising train MAPE of the weighted Riegel point.", "",
          "| runners | n | best b | train MAPE at best b | train MAPE at 1.06 |", "|---|---:|---:|---:|---:|",
          f"| all (gender not used) | {len(train)} | {b_all:.2f} | {m_all:.3f}% | {mape_for(train, 1.06, p):.3f}% |",
          f"| women | {len(fem)} | {b_f:.2f} | {m_f:.3f}% | {mape_for(fem, 1.06, p):.3f}% |",
          f"| men | {len(men)} | {b_m:.2f} | {m_m:.3f}% | {mape_for(men, 1.06, p):.3f}% |", ""]

    def cells(bfun) -> dict[str, float]:
        out = {}
        for g in ("F", "M"):
            for d in ("up", "down"):
                sel = [c for c in train if c["gender"] == g and c[d]]
                out[f"{g} {d}"] = float(np.median([math.log(c["T"] / point_and_gap(c, bfun(c), p)[0])
                                                   for c in sel]) * 100)
        return out

    rows_cal = {"b = 1.06 for all": cells(lambda c: 1.06),
                f"b = {b_all:.2f} for all": cells(lambda c: b_all),
                f"b = {b_f:.2f} women / {b_m:.2f} men": cells(lambda c: b_of[c["gender"]])}
    L += ["Median log error ln(actual / point) × 100 by gender × direction (train; "
          "\"up\" = target longer than every input race, \"down\" = shorter; + = point too fast):", "",
          "| exponent | " + " | ".join(next(iter(rows_cal.values()))) + " | RMS |",
          "|---|" + "---:|" * 5]
    rms = {}
    for name, cl in rows_cal.items():
        rms[name] = math.sqrt(np.mean([v * v for v in cl.values()]))
        L.append(f"| {name} | " + " | ".join(f"{v:+.2f}%" for v in cl.values()) + f" | {rms[name]:.2f} |")
    r_pool, r_gender = list(rms.values())[1:]
    helps = r_gender < r_pool and (m_f * len(fem) + m_m * len(men)) / len(train) <= m_all
    L += ["", (f"Decision: the gender-specific exponent is simple (one offset per gender), lowers "
               f"train MAPE ({(m_f * len(fem) + m_m * len(men)) / len(train):.3f}% vs {m_all:.3f}%) and "
               f"cuts the gender × direction median errors (RMS {r_gender:.2f} vs {r_pool:.2f}), so it is "
               f"the default (`riegel_exponent` = {b_all:.2f} when gender is not given, offsets "
               f"{b_m - b_all:+.2f} men / {b_f - b_all:+.2f} women)." if helps else
               "Decision: the gender-specific exponent does NOT improve train calibration; "
               "set both offsets to 0."), ""]

    # 2. quantile regression on train
    def design(cs, gender_exp=True):
        X, y = [], []
        for c in cs:
            b = b_of[c["gender"]] if gender_exp and c["gender"] in b_of else b_all
            pt, gap = point_and_gap(c, b, p)
            X.append(features(c, gap))
            y.append(math.log(c["T"] / pt))
        return np.array(X), np.array(y)

    Xtr, ytr = design(train)
    coef = {k: quantile_regression(Xtr, ytr, t) for k, t in zip(QUANTILE_KEYS, QUANTILE_LEVELS)}
    coef_gap = {k: quantile_regression(Xtr[:, :2], ytr, t) for k, t in zip(QUANTILE_KEYS, QUANTILE_LEVELS)}
    L += ["## 2. Quantile model (train)", "",
          "q(level) = base + gap·b_gap + years·b_years + b_races / races, in ln(actual / point); "
          "gap = weighted mean |ln(D/d)|, years = years since the most recent race (cap "
          f"{YEARS_CAP:g}), races = number of races (cap {RACES_CAP}).", "",
          "| quantile | base | gap | years | 1/races | gap-only model: base | gap |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for k, t in zip(QUANTILE_KEYS, QUANTILE_LEVELS):
        c4, c2 = coef[k], coef_gap[k]
        L.append(f"| {t * 100:g}% | {c4[0]:+.4f} | {c4[1]:+.4f} | {c4[2]:+.4f} | {c4[3]:+.4f} "
                 f"| {c2[0]:+.4f} | {c2[1]:+.4f} |")
    L += ["", "Reading it: a single race (1/races = 1) mostly lowers the 2.5% quantile (more chance "
          "of running much faster than predicted — the one race may have been a jog); old races "
          "raise the upper quantiles (more chance of being slower); extrapolating in distance "
          "widens both tails. The median row is the bias correction (formula `median_time`).", ""]

    # config check
    cfg_diff = max(abs(p[param_name(k, f)] - coef[k][i]) for k in QUANTILE_KEYS
                   for i, f in enumerate(BAND_FEATURES))
    exp_ok = (abs(p.riegel_exponent - b_all) < 1e-9 and abs(p.exponent_offset_male - (b_m - b_all)) < 1e-9
              and abs(p.exponent_offset_female - (b_f - b_all)) < 1e-9)
    L += [f"config.toml check: largest |config − fitted| band coefficient = {cfg_diff:.5f} "
          f"(values are stored rounded to 4 decimals); exponents match fit: {'yes' if exp_ok else 'NO'}.", ""]
    L += ["<details><summary>config.toml block (fitted values)</summary>", "", "```toml"]
    for k in QUANTILE_KEYS:
        for i, f in enumerate(BAND_FEATURES):
            L.append(f"band_{k}_{f} = {coef[k][i]:.4f}")
    L += ["```", "", "</details>", ""]

    # 3. test, end to end through the model
    with ProcessPoolExecutor() as pool:
        q_new = model_quantiles(test, {}, pool)
        q_old = model_quantiles(test, {"method": "curve"}, pool)
        q_train = model_quantiles(train, {}, pool)
    # gap-only alternative, computed directly
    Xte, yte = design(test)
    pts = [math.exp(math.log(c["T"]) - e) for c, e in zip(test, yte)]
    q_gaponly = []
    for x, pt in zip(Xte, pts):
        lq = sorted(float(coef_gap[k] @ x[:2]) for k in QUANTILE_KEYS)
        q_gaponly.append([pt * math.exp(v) for v in lq])

    m_new = [case_metrics(q, c["T"]) for q, c in zip(q_new, test)]
    m_old = [case_metrics(q, c["T"]) for q, c in zip(q_old, test)]
    m_gap = [case_metrics(q, c["T"]) for q, c in zip(q_gaponly, test)]
    m_tr = [case_metrics(q, c["T"]) for q, c in zip(q_train, train)]
    s_new, s_old, s_gap, s_tr = map(summarise, (m_new, m_old, m_gap, m_tr))

    L += [f"## 3. Test results ({len(test):,} runners never used for fitting)", "",
          "| method | MAPE | median APE | bias (mean ln(pred/actual)) | actual below median "
          "| 50% cov | 80% cov | 95% cov | IS50 | IS80 | IS95 | avg 80% width |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, s in (("**v0.5.0 weighted Riegel + empirical bands**", s_new),
                    ("v0.5.0 point, gap-only bands", s_gap),
                    ("v0.4.0 curve + normal sigma (`method = curve`)", s_old),
                    ("(v0.5.0 on train, in-sample)", s_tr)):
        L.append(f"| {name} | {s['ape']:.2f}% | {s['medape']:.2f}% | {s['log_err']:+.2f}% | "
                 f"{s['below'] * 100:.1f}% | {s['in50'] * 100:.1f}% | {s['in80'] * 100:.1f}% | "
                 f"{s['in95'] * 100:.1f}% | {s['is50']:.1f} | {s['is80']:.1f} | {s['is95']:.1f} | "
                 f"{s['w80']:.1f}% |")
    ev = [c["event"] for c in test]
    d_mape = boot_diff([m["ape"] for m in m_new], [m["ape"] for m in m_old], ev)
    d_is80 = boot_diff([m["is80"] for m in m_new], [m["is80"] for m in m_old], ev)
    d_is95 = boot_diff([m["is95"] for m in m_new], [m["is95"] for m in m_old], ev)
    d_is50 = boot_diff([m["is50"] for m in m_new], [m["is50"] for m in m_old], ev)
    L += ["", "Interval score (IS) in log-% units: width + (2 / (1 − level)) × miss; lower is better "
          "and it is minimised by the true quantiles. 80% width = hi / lo − 1.", "",
          "Differences v0.5.0 − v0.4.0 on test (95% intervals resample whole target events):", "",
          f"- MAPE {d_mape[0]:+.2f} pp [{d_mape[1]:+.2f}, {d_mape[2]:+.2f}]",
          f"- IS50 {d_is50[0]:+.2f} [{d_is50[1]:+.2f}, {d_is50[2]:+.2f}]; "
          f"IS80 {d_is80[0]:+.2f} [{d_is80[1]:+.2f}, {d_is80[2]:+.2f}]; "
          f"IS95 {d_is95[0]:+.2f} [{d_is95[1]:+.2f}, {d_is95[2]:+.2f}]", ""]

    def grouped(fn, ms):
        g = defaultdict(list)
        for c, m, q in zip(test, ms, q_new):
            g[fn(c)].append(m)
        return g

    test_gap = {id(c): point_and_gap(c, b_of.get(c["gender"], b_all), p)[1] for c in test}
    order_gap = ["0 (same distance)", "0-0.5", "0.5-1.0", "1.0-1.5", "1.5+"]
    order_d = ["mile", "5k", "8k", "10k", "15k", "10mi", "half", "marathon"]
    L += ["### Coverage by group (v0.5.0, test)", ""]
    L += cov_table("By gap (weighted mean |ln(D/d)|; 0.69 = a factor of 2 in distance)", order_gap,
                   grouped(lambda c: gap_bucket(test_gap[id(c)]), m_new))
    L += cov_table("By target distance", order_d, grouped(lambda c: c["target"], m_new))
    L += cov_table("By scenario", ["cross_distance", "same_distance"], grouped(lambda c: c["scenario"], m_new))
    L += cov_table("By gender", ["F", "M"], grouped(lambda c: c["gender"], m_new))
    L += cov_table("By number of races", ["1", "2", "3"], grouped(lambda c: str(len(c["races"])), m_new))
    L += cov_table("By years since the most recent race", ["< 0.5 y", "0.5-1.5 y", "1.5-3 y"],
                   grouped(lambda c: years_bucket(c["years"]), m_new))
    L += cov_table("v0.4.0 curve by gap, for comparison", order_gap,
                   grouped(lambda c: gap_bucket(test_gap[id(c)]), m_old))

    L += ["## Caveats", "",
          "- One state (Ohio), RunSignup-timed and uncertified courses, effort and weather unobserved "
          "(see RESEARCH.md); bands describe recreational road racers like these.",
          "- Training inputs were at most 3 races and at most 3 years old, hence the caps; beyond "
          "the data (e.g. mile → marathon, gap > 2) the bands are linear extrapolations.",
          "- Runners in the same target event share course and weather, so the 2,440 test cases are "
          "not fully independent (bootstrap resamples events).",
          "- The course/weather multipliers (DRAFT) scale the bands but were not part of this fit.", ""]
    OUT_MD.write_text("\n".join(L))
    OUT_JSON.write_text(json.dumps({
        "exponent": {"all": b_all, "F": b_f, "M": b_m},
        "quantile_levels": list(QUANTILE_LEVELS),
        "features": list(BAND_FEATURES),
        "coefficients": {k: [round(float(v), 6) for v in coef[k]] for k in QUANTILE_KEYS},
        "gap_only_coefficients": {k: [round(float(v), 6) for v in coef_gap[k]] for k in QUANTILE_KEYS},
        "test": {"v0.5.0": s_new, "v0.4.0": s_old, "gap_only": s_gap},
        "train_in_sample": s_tr,
    }, indent=2))
    print("wrote", OUT_MD.name, "and", OUT_JSON.relative_to(MODEL_DIR))
    print("\n".join(L[next(i for i, x in enumerate(L) if x.startswith("## 3.")):][:12]))
    for k in QUANTILE_KEYS:
        print(k, " ".join(f"{v:.4f}" for v in coef[k]))
    print("exponents", b_all, b_f, b_m, "config diff", cfg_diff)


if __name__ == "__main__":
    main()
