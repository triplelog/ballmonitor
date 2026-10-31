"""Study: do offer-based class rankings predict how good a football program becomes, and
how do they compare with the recruiting services?  Writes RESEARCH.md (never hand-edit it).

    python -m ballmonitor.models.ncaaf_recruiting.research          # needs `ballmonitor fetch ncaaf_recruiting`

Every number in RESEARCH.md is produced by this file.

What is predicted
    For class year Y, the target is the program's mean opponent-adjusted scoring margin
    (a simple SRS, computed here from ESPN game scores) over seasons Y..Y+3 -- the four
    seasons that class is on campus. Teams must be FBS in all four seasons. Seasons
    2012-2025 are complete, so classes 2012-2022 have targets (11 class years).

How it is scored
    Spearman rank correlation, within each class year, between a ranking and the target
    (higher = the ranking orders programs more like their later strength). Reported per
    year and averaged over years; years are the independent unit.

Walk-forward
    A class-Y target is only known after season Y+3. To choose the model's tunable
    parameters for test class Y we therefore use only classes <= Y-4 (their targets were
    complete before class Y signed). The first test year with >= 2 training classes is
    2017, so the out-of-sample years are 2017-2022 (6 class years; consecutive targets
    share 3 of their 4 seasons, so they are not independent outcomes either).

Benchmarks (no parameters, so they are out-of-sample in every year)
    consensus  On3 industry-consensus team ranking (blends On3, 247Sports, Rivals, ESPN).
               For classes before On3 existed (pre-2021) On3 rebuilt it from the services'
               final ratings -- a mild hindsight risk, flagged in the report.
    rivals     Rivals team ranking (top 100 only; data/teams/, 2012-2022).
    stars      mean star rating of the program's commits in the model's own recruit file.
    prior_srs  the program's SRS in season Y-1 (not a recruiting measure; shows how much
               of the signal is simply "good programs stay good").
"""

from __future__ import annotations

import csv
import itertools
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

MODEL_DIR = Path(__file__).resolve().parent
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from src.data_loader import DataLoader, normalize_team  # noqa: E402
from src.elo_engine import EloEngine  # noqa: E402
from src.models import RankingMethod  # noqa: E402

DATA = MODEL_DIR / "data"
CLASS_YEARS = list(range(2012, 2023))  # classes with a complete 4-season target
WINDOW = 4  # seasons Y..Y+3
LAG = 4  # a class-Y target is complete before class Y+LAG signs
MIN_TRAIN = 2  # training classes needed before a year is used as a test year
DEV_LAST = 2018  # v0.4.0 defaults are chosen on classes <= this; later classes are holdout
Z80 = 1.2816  # half-width of a central 80% normal range, in sd
ADOPT_MARGIN = 0.01  # dev-period mean rho gain needed to replace the v0.3.0 defaults
MARGIN_CAP = 28  # SRS: cap each game margin (limits blowouts of weak opponents)
SRS_RIDGE = 0.01  # SRS: tiny ridge for identifiability
GRID = {
    "rank_decay": [0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 1.0],
    "quality_power": [0.25, 0.5, 0.75, 1.0],
    "l2_reg": [0.1, 0.5, 2.0],
    "prestige_years": [1, 2, 3],
}
DEFAULTS_V030 = {"rank_decay": 0.95, "quality_power": 0.5, "l2_reg": 0.5, "prestige_years": 1}
LOG: list[str] = []


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    LOG.append(line)
    print(line, flush=True)


# ------------------------------------------------------------------------------ target

def load_games() -> dict[int, list[tuple[str, str, int, int, int]]]:
    games: dict[int, list] = defaultdict(list)
    with open(DATA / "outcomes" / "fbs_games.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            games[int(r["season"])].append(
                (normalize_team(r["home"]), normalize_team(r["away"]),
                 int(r["home_points"]), int(r["away_points"]), int(r["neutral"])))
    return dict(games)


def fbs_sets(games: dict[int, list]) -> dict[int, set[str]]:
    """FBS = teams with >= 6 games in the FBS scoreboard that season (FCS teams play 1-2
    FBS opponents). 2020 (COVID) also admits teams FBS in both 2019 and 2021."""
    counts = {s: Counter(t for g in gs for t in g[:2]) for s, gs in games.items()}
    full = {s: {t for t, n in c.items() if n >= 6} for s, c in counts.items()}
    out = {}
    for s in games:
        both = full.get(s - 1, set()) & full.get(s + 1, set())
        out[s] = full[s] | {t for t in counts[s] if t in both}
    return out


def srs(games: list, fbs: set[str]) -> dict[str, float]:
    """Least-squares margin rating: margin = home_edge*not_neutral + r_home - r_away.
    Non-FBS opponents share one pooled 'FCS' rating. Ratings centred on the FBS mean."""
    teams = sorted(fbs) + ["FCS"]
    idx = {t: i for i, t in enumerate(teams)}
    rows, y = [], []
    for home, away, hp, ap, neutral in games:
        h, a = idx.get(home, idx["FCS"]), idx.get(away, idx["FCS"])
        if h == a:
            continue
        x = np.zeros(len(teams) + 1)
        x[h], x[a], x[-1] = 1.0, -1.0, 0.0 if neutral else 1.0
        rows.append(x)
        y.append(max(-MARGIN_CAP, min(MARGIN_CAP, hp - ap)))
    X, Y = np.array(rows), np.array(y, dtype=float)
    k = X.shape[1]
    beta = np.linalg.solve(X.T @ X + SRS_RIDGE * np.eye(k), X.T @ Y)
    r = beta[:-1]
    mean_fbs = float(np.mean(r[:-1]))
    return {t: float(r[i] - mean_fbs) for t, i in idx.items() if t != "FCS"}


def build_targets(games: dict[int, list]) -> tuple[dict[int, dict[str, float]], dict[int, dict[str, float]]]:
    fbs = fbs_sets(games)
    ratings = {s: srs(games[s], fbs[s]) for s in sorted(games)}
    targets = {}
    for y in CLASSES_WITH_TARGET(ratings):
        seasons = range(y, y + WINDOW)
        common = set.intersection(*(set(ratings[s]) for s in seasons))
        targets[y] = {t: float(np.mean([ratings[s][t] for s in seasons])) for t in common}
    return targets, ratings


def CLASSES_WITH_TARGET(ratings: dict) -> list[int]:  # noqa: N802
    return [y for y in CLASS_YEARS if all(s in ratings for s in range(y, y + WINDOW))]


# ------------------------------------------------------------------------- predictors

_RECRUITS: dict[int, list] = {}


def recruits(year: int) -> list:
    if year not in _RECRUITS:
        _RECRUITS[year] = DataLoader(DATA).load_recruits(year)
    return _RECRUITS[year]


def model_result(year: int, theta: dict):
    engine = EloEngine(
        method=RankingMethod.PLACKETT_LUCE, l2_reg=theta["l2_reg"],
        quality_power=theta["quality_power"], rank_decay=theta["rank_decay"],
    )
    history = []
    for back in range(1, int(theta["prestige_years"])):
        try:
            history.extend(recruits(year - back))
        except FileNotFoundError:
            pass
    return engine.run(year, recruits(year), fit_recruits=recruits(year) + history if history else None)


def model_scores(year: int, theta: dict) -> dict[str, float]:
    return {t.name: t.total_score for t in model_result(year, theta).teams if t.commits_count > 0}


def load_consensus() -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = defaultdict(dict)
    path = DATA / "benchmarks" / "consensus_team_rankings.csv"
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            if r["sport"] == "ncaaf":
                out[int(r["year"])].setdefault(normalize_team(r["team"]), int(r["rank"]))
    return out


def star_average(year: int) -> dict[str, float]:
    stars = defaultdict(list)
    for r in recruits(year):
        if r.committed_team and r.stars > 0:
            stars[r.committed_team].append(r.stars)
    return {t: float(np.mean(v)) for t, v in stars.items()}


def rivals_ranks(year: int) -> dict[str, int]:
    return {t: rk for t, (rk, _) in DataLoader(DATA).load_rivals_rankings(year).items()}


def rho(pred: dict[str, float], target: dict[str, float], teams: list[str], missing: float) -> float:
    x = [pred.get(t, missing) for t in teams]
    y = [target[t] for t in teams]
    return float(spearmanr(x, y).statistic)


def residualise(target: dict[str, float], prior: dict[str, float], teams: list[str]) -> dict[str, float]:
    """Target minus its least-squares fit on prior-season SRS (within the class year)."""
    x = np.array([prior.get(t, min(prior.values())) for t in teams])
    y = np.array([target[t] for t in teams])
    b = np.polyfit(x, y, 1)
    return {t: float(v) for t, v in zip(teams, y - np.polyval(b, x))}


# ------------------------------------------------------------------------------- study

def main() -> None:
    t0 = time.time()
    games = load_games()
    targets, ratings = build_targets(games)
    years = sorted(targets)
    consensus = load_consensus()
    log(f"targets for classes {years[0]}-{years[-1]}; games {sum(len(g) for g in games.values())}")

    teams_by_year, rows_by_year = {}, {}
    for y in years:
        commits = Counter(r.committed_team for r in recruits(y) if r.committed_team)
        teams_by_year[y] = sorted(t for t in targets[y] if commits[t] > 0)

    # benchmarks
    bench: dict[str, dict[int, float]] = defaultdict(dict)
    bench_resid: dict[str, dict[int, float]] = defaultdict(dict)
    for y in years:
        teams = teams_by_year[y]
        prior = ratings.get(y - 1, {})
        resid = residualise(targets[y], prior, teams) if prior else None
        preds = {
            "consensus": {t: -r for t, r in consensus.get(y, {}).items()},
            "rivals": {t: -r for t, r in rivals_ranks(y).items()},
            "stars": star_average(y),
            "prior_srs": prior,
        }
        for name, p in preds.items():
            if not p:
                continue
            missing = min(p.values()) - 1.0
            bench[name][y] = rho(p, targets[y], teams, missing)
            if resid is not None and name != "prior_srs":
                bench_resid[name][y] = rho(p, resid, teams, missing)
        rows_by_year[y] = {"teams": len(teams), "consensus_teams": sum(t in consensus.get(y, {}) for t in teams)}
    log("benchmarks done")

    # model grid (every combination, every class year); cached so the report can be redone
    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*GRID.values())]
    # Group by the settings that change the prestige fit so the fit cache is reused.
    combos.sort(key=lambda c: (c["l2_reg"], c["prestige_years"]))
    cache = DATA / "research" / "grid.json"
    grid_rho: dict[tuple, dict[int, float]] = {}
    grid_resid: dict[tuple, dict[int, float]] = {}
    if "--reuse-grid" in sys.argv and cache.exists():
        raw = json.loads(cache.read_text())
        for item in raw:
            key = tuple(item["key"])
            grid_rho[key] = {int(y): v for y, v in item["rho"].items()}
            grid_resid[key] = {int(y): v for y, v in item["resid"].items()}
        log(f"reused {len(grid_rho)} grid points from {cache.relative_to(MODEL_DIR)}")
    else:
        for i, theta in enumerate(combos):
            key = tuple(theta[k] for k in keys)
            grid_rho[key], grid_resid[key] = {}, {}
            for y in years:
                s = model_scores(y, theta)
                teams = teams_by_year[y]
                grid_rho[key][y] = rho(s, targets[y], teams, 0.0)
                prior = ratings.get(y - 1)
                if prior:
                    grid_resid[key][y] = rho(s, residualise(targets[y], prior, teams), teams, 0.0)
            if (i + 1) % 21 == 0:
                log(f"grid {i + 1}/{len(combos)}")
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps([{"key": list(k), "rho": grid_rho[k], "resid": grid_resid[k]} for k in grid_rho]))

    def mean_on(k, ys):
        return float(np.mean([grid_rho[k][t] for t in ys]))

    # walk-forward choice: for test class Y use only classes <= Y - LAG
    tests = [y for y in years if len([t for t in years if t <= y - LAG]) >= MIN_TRAIN]
    chosen, wf, wf_resid = {}, {}, {}
    for y in tests:
        train = [t for t in years if t <= y - LAG]
        best = max(grid_rho, key=lambda k: mean_on(k, train))
        chosen[y] = dict(zip(keys, best))
        wf[y] = grid_rho[best][y]
        wf_resid[y] = grid_resid[best].get(y, math.nan)
    # v0.4.0 defaults: the same rule applied to the development classes only, so the
    # holdout classes (and data/backtest.csv) never influence any default.
    dev = [y for y in years if y <= DEV_LAST]
    holdout = [y for y in years if y > DEV_LAST]
    dev_best = max(grid_rho, key=lambda k: mean_on(k, dev))
    v030 = tuple(DEFAULTS_V030[k] for k in keys)
    # Adopt the dev-best grid point only if it beats the v0.3.0 defaults on the
    # development classes by a margin; otherwise keep the simpler, older defaults.
    adopt = mean_on(dev_best, dev) - mean_on(v030, dev) >= ADOPT_MARGIN
    final_best = dev_best if adopt else v030
    hindsight = max(grid_rho, key=lambda k: mean_on(k, tests))
    sens = {}
    for k_i, k in enumerate(keys):
        sens[k] = {}
        for v in GRID[k]:
            key = list(final_best)
            key[k_i] = v
            sens[k][v] = (mean_on(tuple(key), dev), mean_on(tuple(key), holdout))
    log(f"defaults chosen on {dev[0]}-{dev[-1]}: {dict(zip(keys, final_best))}")

    # projection: target ~ a + b * ln(rank), fitted on the development classes
    theta = dict(zip(keys, final_best))
    model_rank, cons_rank = {}, {}
    for y in years:
        model_rank[y] = {t.name: t.rank for t in model_result(y, theta).teams}  # as model.py shows it
        worst = max(consensus.get(y, {}).values(), default=0) + 1
        cons_rank[y] = {t: consensus.get(y, {}).get(t, worst) for t in teams_by_year[y]}
    worst_rank = {y: len(model_rank[y]) + 1 for y in years}

    def fit_map(feature):  # feature(y, team) -> x ; OLS on dev, returns (a, b, sd)
        x = np.array([feature(y, t) for y in dev for t in teams_by_year[y]])
        z = np.array([targets[y][t] for y in dev for t in teams_by_year[y]])
        b_, a_ = np.polyfit(x, z, 1)
        sd = float(np.std(z - (a_ + b_ * x), ddof=2))
        return float(a_), float(b_), sd

    def holdout_err(feature, a_, b_, sd=None):
        errs, cover = [], []
        for y in holdout:
            for t in teams_by_year[y]:
                e = a_ + b_ * feature(y, t) - targets[y][t]
                errs.append(e)
                if sd is not None:
                    cover.append(abs(e) <= Z80 * sd)
        out = {"mae": float(np.mean(np.abs(errs))), "bias": float(np.mean(errs)), "n": len(errs)}
        if cover:
            out["in_80"] = float(np.mean(cover))
        return out

    features = {
        "model": lambda y, t: math.log(model_rank[y].get(t, worst_rank[y])),
        "consensus": lambda y, t: math.log(cons_rank[y][t]),
        "stars": lambda y, t: star_average(y).get(t, min(star_average(y).values())),
        "prior_srs": lambda y, t: ratings[y - 1].get(t, min(ratings[y - 1].values())) if y - 1 in ratings else 0.0,
    }
    proj = {}
    for name, f in features.items():
        if name == "prior_srs" and any(y - 1 not in ratings for y in dev):
            continue
        a_, b_, sd = fit_map(f)
        proj[name] = {"a": a_, "b": b_, "sd": sd, **holdout_err(f, a_, b_, sd)}
    mean_target = float(np.mean([targets[y][t] for y in dev for t in teams_by_year[y]]))
    proj["constant"] = {"a": mean_target, "b": 0.0, "sd": math.nan,
                        **holdout_err(lambda y, t: 0.0, mean_target, 0.0)}
    log(f"projection on dev: {proj['model']}")

    # data/backtest.csv: the holdout classes only
    with open(DATA / "backtest.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["year", "team", "future_srs", "consensus_rank", "prior_srs"])
        for y in holdout:
            for t in teams_by_year[y]:
                prior = ratings.get(y - 1, {}).get(t)
                w.writerow([y, t, round(targets[y][t], 2), cons_rank[y][t],
                            "" if prior is None else round(prior, 2)])
    log(f"wrote data/backtest.csv ({sum(len(teams_by_year[y]) for y in holdout)} rows, classes {holdout[0]}-{holdout[-1]})")

    results = {
        "years": years, "tests": tests, "rows": rows_by_year, "dev": dev, "holdout": holdout,
        "bench": bench, "bench_resid": bench_resid,
        "walk_forward": wf, "walk_forward_resid": wf_resid, "chosen": chosen,
        "v030": grid_rho[v030], "v030_resid": grid_resid[v030],
        "final_best": dict(zip(keys, final_best)), "dev_best": dict(zip(keys, dev_best)),
        "dev_best_rho": grid_rho[dev_best], "adopted_dev_best": adopt,
        "final_best_rho": grid_rho[final_best], "final_best_resid": grid_resid[final_best],
        "hindsight": dict(zip(keys, hindsight)), "hindsight_rho": grid_rho[hindsight],
        "sensitivity": sens, "projection": proj,
        "srs_top_2025": sorted(ratings[max(ratings)].items(), key=lambda kv: -kv[1])[:5],
    }
    out = DATA / "research"
    out.mkdir(exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str))
    log(f"finished in {time.time() - t0:.0f}s")
    (MODEL_DIR / "RESEARCH.md").write_text(render(results))


# ------------------------------------------------------------------------------ report

def _m(d: dict, ys: list[int]) -> float:
    v = [d[y] for y in ys if y in d and not math.isnan(d[y])]
    return float(np.mean(v)) if v else math.nan


def _se(d: dict, ys: list[int]) -> float:
    v = [d[y] for y in ys if y in d and not math.isnan(d[y])]
    return float(np.std(v, ddof=1) / math.sqrt(len(v))) if len(v) > 1 else math.nan


def render(r: dict) -> str:
    years, tests = r["years"], r["tests"]
    b, br = r["bench"], r["bench_resid"]
    wf = r["walk_forward"]
    lines = [
        "# RESEARCH — offer-based recruiting rankings vs later team strength",
        "",
        "_Generated by `python -m ballmonitor.models.ncaaf_recruiting.research`; do not edit by hand._",
        "",
        "**Question.** Within a class year, does ranking football programs by the offer-based",
        "class score order them like their on-field strength over the next four seasons,",
        "and does it beat the recruiting services and a star-count average?",
        "",
        "**Target.** Mean opponent-adjusted scoring margin (SRS: least squares on ESPN game",
        f"scores, margins capped at ±{MARGIN_CAP}, home edge fitted, FCS opponents pooled) over",
        "seasons Y..Y+3 for class Y. FBS programs in all four seasons that signed at least one",
        f"recruit in the file. Classes {years[0]}–{years[-1]} ({len(years)} class years).",
        "",
        "**Metric.** Spearman rank correlation within a class year (1 = same order). Means are",
        "over class years, the independent unit; ± is one standard error across years.",
        "",
        "**Walk-forward.** For test class Y the model's parameters are chosen on classes ≤ Y−4",
        f"(targets complete before class Y signed). Test years: {tests[0]}–{tests[-1]}",
        f"(**{len(tests)} independent class years**; their 4-season targets overlap, so the",
        f"effective number of non-overlapping outcome periods is about {len(tests) / WINDOW:.1f}).",
        "",
        "## Out-of-sample results (test years)",
        "",
        "| ranking | mean ρ | ± se | years beaten by model | mean ρ after prior SRS |",
        "|---|---:|---:|---:|---:|",
    ]
    def beat(d):
        return sum(1 for y in tests if y in d and wf[y] > d[y])
    lines.append(f"| **offer model, walk-forward params** | **{_m(wf, tests):.3f}** | {_se(wf, tests):.3f} | – | "
                 f"{_m(r['walk_forward_resid'], tests):.3f} |")
    lines.append(f"| offer model, v0.3.0 defaults | {_m(r['v030'], tests):.3f} | {_se(r['v030'], tests):.3f} | "
                 f"{beat(r['v030'])}/{len(tests)} | {_m(r['v030_resid'], tests):.3f} |")
    names = {"consensus": "On3 industry consensus (247/On3/Rivals/ESPN)",
             "rivals": "Rivals team rank (top 100)", "stars": "mean commit stars",
             "prior_srs": "prior-season SRS (not recruiting)"}
    for k, label in names.items():
        if k in b:
            lines.append(f"| {label} | {_m(b[k], tests):.3f} | {_se(b[k], tests):.3f} | {beat(b[k])}/{len(tests)} | "
                         + ("–" if k not in br else f"{_m(br[k], tests):.3f}") + " |")
    hs = r["hindsight"]
    lines += [
        f"| _hindsight best grid point (not a forecast)_ | _{_m(r['hindsight_rho'], tests):.3f}_ | | | |",
        "",
        "\"After prior SRS\": Spearman with the part of the target not explained by a linear fit",
        "on the program's previous-season SRS — how much a ranking adds beyond program inertia.",
        f"Hindsight best = {hs} (chosen on the test years themselves; shown only as a ceiling).",
        "",
        "## Per class year",
        "",
        "| class | teams | walk-forward model | params chosen (decay, power, l2, years) | consensus | rivals | stars | prior SRS |",
        "|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for y in years:
        c = r["chosen"].get(y)
        ctext = f"{c['rank_decay']}, {c['quality_power']}, {c['l2_reg']}, {c['prestige_years']}" if c else "(training only)"
        mv = f"{wf[y]:.3f}" if y in wf else f"_{r['v030'][y]:.3f} (v0.3.0, in-sample)_"
        cells = [f"{b[k][y]:.3f}" if y in b.get(k, {}) else "–" for k in ("consensus", "rivals", "stars", "prior_srs")]
        lines.append(f"| {y} | {r['rows'][y]['teams']} | {mv} | {ctext} | " + " | ".join(cells) + " |")
    fb = r["final_best"]
    dev, hold = r["dev"], r["holdout"]
    pj = r["projection"]
    lines += [
        "",
        "## Defaults for v0.4.0 (decided on development classes only)",
        "",
        f"The grid point with the best mean ρ on the development classes {dev[0]}–{dev[-1]} is",
        f"`{r['dev_best']}`. It replaces the v0.3.0 defaults only if it is better on those",
        f"classes by at least {ADOPT_MARGIN} ρ. "
        + ("It is, so it was adopted." if r["adopted_dev_best"] else
           "It is not, so the v0.3.0 defaults are kept."),
        f"Defaults: `rank_decay = {fb['rank_decay']}`, `quality_power = {fb['quality_power']}`, "
        f"`l2_reg = {fb['l2_reg']}`, `prestige_years = {fb['prestige_years']}`.",
        f"The holdout classes {hold[0]}–{hold[-1]} ({len(hold)} class years, also `data/backtest.csv`) did not",
        "influence this decision or the projection line below.",
        "",
        "| ranking | dev mean ρ | holdout mean ρ |",
        "|---|---:|---:|",
        f"| offer model, dev-best grid point | {_m(r['dev_best_rho'], dev):.3f} | {_m(r['dev_best_rho'], hold):.3f} |",
        f"| offer model, v0.3.0 defaults | {_m(r['v030'], dev):.3f} | {_m(r['v030'], hold):.3f} |",
    ]
    for k, label in names.items():
        if k in b:
            lines.append(f"| {label} | {_m(b[k], dev):.3f} | {_m(b[k], hold):.3f} |")
    lines += [
        "",
        "Sensitivity (dev / holdout mean ρ when one parameter is changed from the defaults):",
        "",
    ]
    for k, vals in r["sensitivity"].items():
        lines.append(f"- `{k}`: " + "; ".join(f"{v} → {d:.3f} / {h:.3f}" for v, (d, h) in vals.items()))
    m = pj["model"]
    lines += [
        "",
        "## Projected 4-season SRS (the model's `projected_srs` outcome)",
        "",
        "Each ranking is turned into a points-per-game forecast by a straight line fitted on the",
        "development classes (rank-based rankings use ln(rank)); scored on the holdout classes.",
        "",
        "| predictor | fit (dev) | holdout MAE | bias | 80% range coverage |",
        "|---|---|---:|---:|---:|",
    ]
    labels = {"model": "offer model ln(national rank)",  # prior SRS: no 2011 scores for the 2012 fit "consensus": "consensus ln(rank)",
              "stars": "mean commit stars", "prior_srs": "prior-season SRS (not recruiting)",
              "constant": "dev-period mean (no information)"}
    for k, label in labels.items():
        if k in pj:
            q = pj[k]
            fit = f"{q['a']:.2f} {q['b']:+.2f}·x, sd {q['sd']:.2f}" if k != "constant" else f"{q['a']:.2f}"
            cov = f"{q['in_80']:.2f}" if "in_80" in q and k != "constant" else "–"
            lines.append(f"| {label} | {fit} | {q['mae']:.2f} | {q['bias']:+.2f} | {cov} |")
    lines += [
        "",
        "(Prior-season SRS is not fitted here: there are no 2011 game scores for the 2012 class.)",
        "",
        f"The model's line becomes config: `proj_intercept = {m['a']:.2f}`, `proj_slope = {m['b']:.2f}`,",
        f"`projection_sd = {m['sd']:.2f}` ({m['n']} holdout program-classes).",
        "",
        "## Caveats",
        "",
        f"- Only {len(tests)} walk-forward test years and {len(hold)} holdout years, with overlapping",
        "  4-season targets; differences of a few hundredths of ρ are within noise (see ± se).",
        "- The consensus ranking for pre-2021 classes was compiled by On3 after the fact from the",
        "  services' final ratings; Rivals ranks only the top 100 (others get the worst rank).",
        "- 2012–2021 recruit files are legacy Rivals/On3 profile scrapes (~3,500 recruits a year);",
        "  2022+ files hold only On3-ranked recruits (~2,100–3,000), so service academies and other",
        "  programs that sign unranked players look thin, and the rank → SRS line may shift.",
        "- Stars come from the model's recruit files (Rivals stars for legacy years, On3",
        "  consensus stars for 2022+).",
        "- SRS is a simple margin rating, not SP+/FEI; the 2020 season was short (COVID).",
        "- Basketball is not part of this study: men's basketball is evaluated in RESEARCH_MBB.md",
        "  (research_mbb.py); women's basketball is untested.",
        "",
        "## Run log",
        "",
        "```",
        *LOG,
        "```",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
