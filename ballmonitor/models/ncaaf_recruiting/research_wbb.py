"""Women's basketball: does the offer model rank recruiting classes better than the
ratings consensus?  Writes RESEARCH_WBB.md (generated, never hand-edit).

    python ballmonitor/models/ncaaf_recruiting/research_wbb.py

Data
  data/recruits/wbb_espn_classes.csv   ESPN classes 2012-2025 (top 300 by rank): ESPN grade
      and rank, commitment, and the other schools still on each recruit's list (finalists,
      not full offer lists; built by fetch.py `build_wbb_espn`).
  ballmonitor/models/dad/data/team_ratings.csv   per-season schedule-adjusted margin
      ratings for every D-I women's team, seasons 2016-2026 (ESPN game results).
ESPN is the main women's recruiting service, so its grades stand in for the consensus.

Class metrics (per program and class y; programs with no ranked commits get 0):
  offer      the offer model (Plackett-Luce on commit-vs-listed-school battles), current
             basketball defaults
  offer+     the same with the committed school counted (bball_commit_weight = 3), so
             recruits listing no other school are not scored 0
  grade      top-heavy ESPN-grade class score: sum of exp(k z) with decay 0.5, z = normal
             score of the within-class grade percentile; k chosen on development classes
  commits    number of ranked commits

Outcome: the program's rating in season y+1 (the class's freshman season), and the mean of
seasons y+1 and y+2. Programs: those with >= 1 ranked commit in class y. Development classes
2016-2020 (k only), test classes 2021-2025; simple metrics are also shown over all years.
"""

from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import norm, rankdata, spearmanr

MODEL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODEL_DIR))
from src.elo_engine import EloEngine  # noqa: E402
from src.models import RankingMethod, Recruit  # noqa: E402

import tomllib  # noqa: E402

CLASSES = list(range(2016, 2026))
DEV = list(range(2016, 2021))
TEST = list(range(2021, 2026))
LISTS_ERA = list(range(2016, 2022))  # classes where ESPN school lists are reasonably common
STEEP = [0.5, 1.0, 1.5, 2.0, 3.0]
BOOT = 2000


def load():
    recs = defaultdict(list)
    with open(MODEL_DIR / "data" / "recruits" / "wbb_espn_classes.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r["committed_team"]:
                continue
            y = int(r["year"])
            recs[y].append({
                "id": r["espn_id"], "name": r["name"], "team": r["committed_team"],
                "grade": float(r["grade"]) if r["grade"] else math.nan,
                "others": [t for t in r["other_schools"].split("|") if t],
            })
    rating = defaultdict(dict)
    dad = MODEL_DIR.parent / "dad" / "data" / "team_ratings.csv"
    with open(dad, newline="") as fh:
        for r in csv.DictReader(fh):
            if r["league"] == "wbb":
                rating[int(r["season"])][r["team"]] = float(r["rating"])
    return recs, rating


def params():
    p = tomllib.loads((MODEL_DIR / "config.toml").read_text())["params"]
    return {k: p[k]["value"] for k in ("bball_l2_reg", "bball_quality_power", "rotation_decay", "cornerstone_weight")}


def offer_scores(recs: list[dict], y: int, commit_weight: float) -> dict[str, float]:
    p = params()
    eng = EloEngine(method=RankingMethod.PLACKETT_LUCE, l2_reg=p["bball_l2_reg"],
                    quality_power=p["bball_quality_power"], rank_decay=p["rotation_decay"],
                    cornerstone_weight=p["cornerstone_weight"], commit_weight=commit_weight)
    rs = [Recruit(url=r["id"], year=y, name=r["name"], position="", hometown="", stars=0,
                  committed_team=r["team"], offers=list(r["others"])) for r in recs]
    res = eng.run(y, rs)
    return {t.name: t.total_score for t in res.teams if t.commits_count > 0}


def grade_scores(recs: list[dict], k: float) -> dict[str, float]:
    g = np.array([r["grade"] for r in recs])
    g = np.where(np.isnan(g), np.nanmin(g), g)
    z = norm.ppf((rankdata(g) - 0.5) / len(g))
    by = defaultdict(list)
    for r, zz in zip(recs, z):
        by[r["team"]].append(math.exp(k * zz))
    return {t: sum(v * 0.5 ** i for i, v in enumerate(sorted(vs, reverse=True))) for t, vs in by.items()}


def commit_counts(recs):
    c = defaultdict(float)
    for r in recs:
        c[r["team"]] += 1
    return c


def evaluate(metric: dict[int, dict[str, float]], rating, years, target: str):
    """Mean within-year Spearman with the target, and with the residual after the prior
    season's rating; programs with >= 1 ranked commit."""
    rho, res, n = [], [], 0
    for y in years:
        teams = [t for t in metric[y] if t in rating.get(y + 1, {}) and t in rating.get(y, {})]
        if target == "t2":
            teams = [t for t in teams if t in rating.get(y + 2, {})]
        if len(teams) < 15:
            continue
        tg = np.array([rating[y + 1][t] if target == "t1" else (rating[y + 1][t] + rating[y + 2][t]) / 2
                       for t in teams])
        x = np.array([metric[y][t] for t in teams])
        pr = np.array([rating[y][t] for t in teams])
        b = np.polyfit(pr, tg, 1)
        rho.append(spearmanr(x, tg).statistic)
        res.append(spearmanr(x, tg - np.polyval(b, pr)).statistic)
        n += len(teams)
    return (float(np.mean(rho)) if rho else math.nan, float(np.mean(res)) if res else math.nan,
            len(rho), n)


def paired_gap(a: dict, b: dict, rating, years):
    """Per-year residual-rho difference a - b, mean and bootstrap 95% interval over years."""
    diffs = []
    for y in years:
        ra = evaluate({y: a[y]}, rating, [y], "t1")
        rb = evaluate({y: b[y]}, rating, [y], "t1")
        if not math.isnan(ra[0]) and not math.isnan(rb[0]):
            diffs.append((ra[0] - rb[0], ra[1] - rb[1]))
    d = np.array(diffs)
    rng = np.random.default_rng(0)
    boots = np.array([d[rng.integers(0, len(d), len(d))].mean(axis=0) for _ in range(BOOT)])
    lo, hi = np.percentile(boots, [2.5, 97.5], axis=0)
    wins = int((d[:, 0] > 0).sum())
    return d.mean(axis=0), lo, hi, wins, len(d)


def main() -> None:
    recs, rating = load()
    years = [y for y in CLASSES if y in recs]
    coverage = {y: (len(recs[y]), sum(1 for r in recs[y] if r["others"])) for y in years}
    offer = {y: offer_scores(recs[y], y, 0.0) for y in years}
    offer_c = {y: offer_scores(recs[y], y, 3.0) for y in years}
    commits = {y: commit_counts(recs[y]) for y in years}
    dev_k = {k: evaluate({y: grade_scores(recs[y], k) for y in DEV}, rating, DEV, "t1")[1] for k in STEEP}
    k_best = max(dev_k, key=dev_k.get)
    grade = {y: grade_scores(recs[y], k_best) for y in years}
    metrics = {"offer model (current defaults)": offer, "offer model + committed school": offer_c,
               f"ESPN-grade class score (k={k_best})": grade, "number of ranked commits": commits}

    L = ["# Women's basketball: offer model vs ratings consensus", "",
         "_Generated by `research_wbb.py` — do not edit by hand._", "",
         "Outcome: schedule-adjusted margin rating (points per game vs an average D-I team; "
         "`ballmonitor/models/dad/data/team_ratings.csv`). Programs with ≥1 ranked commit in the "
         "class. ‘residual’ = Spearman with the target after removing what the prior season's "
         "rating predicts (what the class adds beyond last season).", "",
         "## Data coverage", "",
         "| class | committed recruits (ESPN top 300) | listing ≥1 other school | offer-model score 0 |",
         "|---|---:|---:|---:|"]
    for y in years:
        n, w = coverage[y]
        L.append(f"| {y} | {n} | {w} ({w / n:.0%}) | {n - w} ({(n - w) / n:.0%}) |")
    L += ["", "ESPN lists other schools (finalists, not full offer lists) for only a minority of "
          "recruits, and almost none after 2021, so the offer model has ~35–80 ‘battles’ per "
          "class (MBB: ~250+ recruits with offer lists per class). On3 women's data with offer "
          "lists starts with the 2025 class (one completed season), too little to test.", "",
          f"Grade-score steepness k chosen on development classes {DEV[0]}-{DEV[-1]}: " +
          ", ".join(f"k={k} {v:+.3f}" for k, v in dev_k.items()) + f" → k={k_best}.", ""]

    for title, yrs in ((f"Test classes {TEST[0]}-{TEST[-1]}", TEST),
                       (f"All classes {years[0]}-{years[-1]}", years),
                       (f"Classes with school lists ({LISTS_ERA[0]}-{LISTS_ERA[-1]})", LISTS_ERA)):
        L += [f"## {title}", "",
              "| class metric | ρ next season | residual ρ | ρ next two seasons | residual ρ (two) | class years |",
              "|---|---:|---:|---:|---:|---:|"]
        for name, m in metrics.items():
            a = evaluate(m, rating, yrs, "t1")
            b = evaluate(m, rating, yrs, "t2")
            L.append(f"| {name} | {a[0]:.3f} | {a[1]:+.3f} | {b[0]:.3f} | {b[1]:+.3f} | {a[2]} |")
        L.append("")

    gap = paired_gap(offer, grade, rating, years)
    gap_c = paired_gap(offer_c, grade, rating, years)
    L += ["## Offer model minus ESPN-grade score (per class year, all classes)", "",
          "| offer version | Δρ next season [95%] | Δ residual ρ [95%] | years offer model ahead |",
          "|---|---:|---:|---:|"]
    for name, (m, lo, hi, wins, n) in (("current defaults", gap), ("+ committed school", gap_c)):
        L.append(f"| {name} | {m[0]:+.3f} [{lo[0]:+.3f}, {hi[0]:+.3f}] | {m[1]:+.3f} "
                 f"[{lo[1]:+.3f}, {hi[1]:+.3f}] | {wins} of {n} |")
    L += ["", "## Caveats", "",
          "- ESPN's school lists are finalists as listed today (some hindsight), present for a "
          "minority of recruits.",
          "- Ratings are full-season margin ratings from ESPN results (not possession-adjusted).",
          "- Intervals resample class years (rows within a year share a season).",
          "- Only ESPN's top 300 per class; lower-ranked signees are not counted.",
          ""]
    (MODEL_DIR / "RESEARCH_WBB.md").write_text("\n".join(L))
    print("wrote RESEARCH_WBB.md")


if __name__ == "__main__":
    main()
