"""Study: do men's basketball recruiting signals (the offer model, industry ratings,
stars, offer counts) predict team strength and individual college production?
Writes RESEARCH_MBB.md (never hand-edit it).

    ballmonitor fetch ncaaf_recruiting                         # On3 + barttorvik data
    python -m ballmonitor.models.ncaaf_recruiting.research_mbb [--reuse-grid]

Every number in RESEARCH_MBB.md is produced by this file.

Data (all built by fetch.py)
    data/recruits/recruits_mbb_{year}.csv   offer files the model reads (2014-2027)
    data/recruits/mbb_recruit_ratings.csv   On3 industry rating / rank / stars / commit
    data/outcomes/mbb_team_seasons.csv      barttorvik adjusted efficiency margin (adj_em)
    data/outcomes/mbb_player_seasons.csv    barttorvik player seasons (pts, Min%, BPM ...)
    data/benchmarks/consensus_team_rankings.csv  On3 consensus team class ranks

Part A -- team level
    Class Y (high-school seniors of spring Y) plays its freshman season Y+1 (barttorvik
    "year" Y+1 = the (Y)-(Y+1) season). Targets: adj_em in season Y+1, and the mean of
    seasons Y+1 and Y+2. Programs: barttorvik D-I teams that signed >= 1 recruit in the
    class file. Metric: Spearman rho within a class year; class years are the unit.
    Walk-forward: for test class Y the model's parameters are chosen on classes whose
    target was complete when class Y signed (<= Y-1 for the one-season target, <= Y-2
    for the two-season target), with >= MIN_TRAIN training classes.
    Defaults: the grid point best on development classes <= DEV_LAST replaces the draft
    defaults only if it beats them there by ADOPT_MARGIN; later classes are holdout.

Part B -- player level
    Each recruit is linked to barttorvik player-seasons by normalised name + school +
    first season (src/mbb_names.py); the barttorvik player id then gives the career.
    Signals are converted to within-class percentiles before pooling class years, and
    Spearman rho is reported with recruit-level bootstrap 95% intervals.
"""

from __future__ import annotations

import csv
import difflib
import itertools
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import rankdata, spearmanr

MODEL_DIR = Path(__file__).resolve().parent
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from src.data_loader import NON_COLLEGE, DataLoader, normalize_team  # noqa: E402
from src.elo_engine import EloEngine  # noqa: E402
from src.mbb_names import last_name, player_key, to_bart  # noqa: E402
from src.models import RankingMethod  # noqa: E402

DATA = MODEL_DIR / "data"
CLASS_YEARS = list(range(2014, 2026))  # classes with a completed freshman season (<= 2026)
LAST_SEASON = 2026  # 2025-26, the last completed season
MIN_TRAIN = 3
DEV_LAST = 2019  # defaults chosen on classes <= this
PORTAL_FROM = 2021  # first class whose freshman season (2021-22) had the one-time transfer rule
COVID_SEASON = 2021  # 2020-21: shortened season, freshman year of the 2020 class
ADOPT_MARGIN = 0.01
CAREER_LAST_CLASS = 2021  # career / draft outcomes only for classes with >= 5 seasons since
ROTATION_MIN_PCT = 15.0  # a season counts for "best BPM" with Min% >= this
UNDRAFTED = 61  # draft-pick value given to undrafted players
N_BOOT = 2000
SEED = 20261026
GRID = {
    "rotation_decay": [0.5, 0.65, 0.75, 0.85, 0.95, 1.0],
    "bball_quality_power": [0.25, 0.4, 0.6, 0.8, 1.0],
    "bball_l2_reg": [0.01, 0.05, 0.2, 1.0],
    "cornerstone_weight": [0.0, 0.25, 0.5],
}
DRAFT_DEFAULTS = {"rotation_decay": 0.75, "bball_quality_power": 0.6, "bball_l2_reg": 0.05,
                  "cornerstone_weight": 0.25}
LOG: list[str] = []


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    LOG.append(line)
    print(line, flush=True)


def _f(x: str) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return math.nan


# --------------------------------------------------------------------------- loading

def load_team_seasons() -> dict[int, dict[str, float]]:
    em: dict[int, dict[str, float]] = defaultdict(dict)
    with open(DATA / "outcomes" / "mbb_team_seasons.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            em[int(r["season"])][r["team"]] = float(r["adj_em"])
    return dict(em)


def load_ratings() -> list[dict]:
    with open(DATA / "recruits" / "mbb_recruit_ratings.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["year"] = int(r["year"])
        r["industry_rating"] = _f(r["industry_rating"])
        r["industry_rank"] = _f(r["industry_rank"])
        r["stars"] = int(r["stars"] or 0)
        r["n_other_schools"] = int(r["n_other_schools"] or 0)
        r["school"] = normalize_team(r["committed_school"]) if r["committed_school"] else ""
    return rows


def load_players() -> list[dict]:
    with open(DATA / "outcomes" / "mbb_player_seasons.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["season"] = int(r["season"])
        for k in ("gp", "min_pct", "pts", "bpm", "porpag", "draft_pick"):
            r[k] = _f(r[k])
        r["key"] = player_key(r["name"])
        r["last"] = last_name(r["name"])
    return rows


def load_consensus() -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = defaultdict(dict)
    with open(DATA / "benchmarks" / "consensus_team_rankings.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["sport"] == "mbb":
                out[int(r["year"])].setdefault(normalize_team(r["team"]), int(r["rank"]))
    return dict(out)


_RECRUITS: dict[int, list] = {}


def recruits(year: int) -> list:
    if year not in _RECRUITS:
        _RECRUITS[year] = DataLoader(DATA).load_recruits(year, sport="mbb")
    return _RECRUITS[year]


def run_model(year: int, theta: dict):
    engine = EloEngine(
        method=RankingMethod.PLACKETT_LUCE, l2_reg=theta["bball_l2_reg"],
        quality_power=theta["bball_quality_power"], rank_decay=theta["rotation_decay"],
        cornerstone_weight=theta["cornerstone_weight"],
    )
    return engine.run(year, recruits(year))


def same_recruit(r: dict, p: dict) -> bool:
    """Barttorvik gives a recruit rating only to players it lists as ranked recruits
    (its scale differs from On3's, so only its presence is used): a ranked recruit
    with the same name/surname confirms a link that school or hometown cannot."""
    return _f(p.get("rec_rating", "")) > 0


def hometown(s: str) -> str:
    return s.split(",")[0].strip().lower() if s else ""


# --------------------------------------------------------------------------- stats

def rho(pred: dict, target: dict, teams: list, missing: float) -> float:
    x = [pred.get(t, missing) for t in teams]
    y = [target[t] for t in teams]
    return float(spearmanr(x, y).statistic)


def residualise(target: dict, prior: dict, teams: list) -> dict:
    x = np.array([prior.get(t, min(prior.values())) for t in teams])
    y = np.array([target[t] for t in teams])
    b = np.polyfit(x, y, 1)
    return {t: float(v) for t, v in zip(teams, y - np.polyval(b, x))}


def residualise2(target: dict, prior: dict, cons: dict, teams: list) -> dict:
    """Target minus its least-squares fit on prior-season EM and ln(consensus rank)
    (unranked programs get the worst rank + 1)."""
    worst = max(cons.values(), default=0) + 1
    x1 = np.array([prior.get(t, min(prior.values())) for t in teams])
    x2 = np.log(np.array([cons.get(t, worst) for t in teams], dtype=float))
    y = np.array([target[t] for t in teams])
    A = np.column_stack([np.ones_like(x1), x1, x2])
    beta = np.linalg.lstsq(A, y, rcond=None)[0]
    return {t: float(v) for t, v in zip(teams, y - A @ beta)}


def _mean(d: dict, ys) -> float:
    v = [d[y] for y in ys if y in d and not math.isnan(d[y])]
    return float(np.mean(v)) if v else math.nan


def _se(d: dict, ys) -> float:
    v = [d[y] for y in ys if y in d and not math.isnan(d[y])]
    return float(np.std(v, ddof=1) / math.sqrt(len(v))) if len(v) > 1 else math.nan


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx, ry = rankdata(x), rankdata(y)
    if np.std(rx) == 0 or np.std(ry) == 0:
        return math.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def _partial(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> float:
    """Partial Spearman of x and y given z (ranks, linear residuals)."""
    rx, ry, rz = rankdata(x), rankdata(y), rankdata(z)
    A = np.column_stack([np.ones_like(rz), rz])
    ex = rx - A @ np.linalg.lstsq(A, rx, rcond=None)[0]
    ey = ry - A @ np.linalg.lstsq(A, ry, rcond=None)[0]
    if np.std(ex) == 0 or np.std(ey) == 0:
        return math.nan
    return float(np.corrcoef(ex, ey)[0, 1])


def _r2_gain(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> float:
    """Increase in R^2 of rank(y) when rank(x) is added to rank(z)."""
    rx, ry, rz = rankdata(x), rankdata(y), rankdata(z)

    def r2(cols):
        A = np.column_stack([np.ones_like(ry), *cols])
        e = ry - A @ np.linalg.lstsq(A, ry, rcond=None)[0]
        return 1 - float(e @ e) / float(((ry - ry.mean()) ** 2).sum())
    return r2([rz, rx]) - r2([rz])


def boot(fn, arrays: list[np.ndarray], rng: np.random.Generator) -> tuple[float, float, float]:
    est = fn(*arrays)
    n = len(arrays[0])
    vals = []
    for _ in range(N_BOOT):
        i = rng.integers(0, n, n)
        v = fn(*(a[i] for a in arrays))
        if not math.isnan(v):
            vals.append(v)
    lo, hi = np.percentile(vals, [2.5, 97.5]) if vals else (math.nan, math.nan)
    return est, float(lo), float(hi)


def pct_within(values: list[float], groups: list[int]) -> np.ndarray:
    """Percentile rank (0-1) of each value within its class year (ties averaged)."""
    out = np.full(len(values), math.nan)
    by = defaultdict(list)
    for i, g in enumerate(groups):
        by[g].append(i)
    for idx in by.values():
        v = np.array([values[i] for i in idx], dtype=float)
        ok = ~np.isnan(v)
        if ok.sum() == 0:
            continue
        r = rankdata(v[ok]) / ok.sum()
        out[np.array(idx)[ok]] = r
    return out


# --------------------------------------------------------------------------- part A

def team_study(em, ratings, consensus, bart_names) -> dict:
    tb = {}  # On3 school -> bart name
    def bart(school: str) -> str:
        if school not in tb:
            tb[school] = to_bart(school, bart_names)
        return tb[school]

    # name match rate (commits)
    commit_names = Counter(r["school"] for r in ratings if r["school"] and r["year"] in CLASS_YEARS)
    matched = sum(n for s, n in commit_names.items() if bart(s))
    unmatched_schools = sorted(((s, n) for s, n in commit_names.items() if not bart(s)), key=lambda kv: -kv[1])

    years = [y for y in CLASS_YEARS if y + 1 in em]
    t1, t2, teams1, teams2, prior = {}, {}, {}, {}, {}
    for y in years:
        commits = Counter(bart(r.committed_team) for r in recruits(y) if r.committed_team)
        signed = {t for t, n in commits.items() if t and n > 0}
        t1[y] = {t: em[y + 1][t] for t in signed if t in em[y + 1]}
        teams1[y] = sorted(t1[y])
        if y + 2 in em:
            t2[y] = {t: (em[y + 1][t] + em[y + 2][t]) / 2 for t in signed if t in em[y + 1] and t in em[y + 2]}
            teams2[y] = sorted(t2[y])
        prior[y] = em.get(y, {})
    targets = {"t1": (t1, teams1, 1), "t2": (t2, teams2, 2)}

    # benchmarks
    by_class_school = defaultdict(list)
    for r in ratings:
        if r["school"]:
            by_class_school[(r["year"], bart(r["school"]))].append(r)
    bench_preds = {}
    for y in years:
        rs = {t: v for (yy, t), v in by_class_school.items() if yy == y and t}
        rated = {t: [x["industry_rating"] for x in v if not math.isnan(x["industry_rating"])] for t, v in rs.items()}
        bench_preds[y] = {
            "rating_sum": {t: float(sum(v)) for t, v in rated.items() if v},
            "rating_mean": {t: float(np.mean(v)) for t, v in rated.items() if v},
            "stars_mean": {t: float(np.mean([x["stars"] for x in v])) for t, v in rs.items()},
            "consensus": {bart(t): -rk for t, rk in consensus.get(y, {}).items() if bart(t)},
            "prior_em": prior[y],
        }
    cons_rank = {y: {bart(t): rk for t, rk in consensus.get(y, {}).items() if bart(t)} for y in years}
    resid2 = {tk: {y: residualise2(tg[y], prior[y], cons_rank[y], tm[y]) for y in tg
                   if prior[y] and cons_rank[y]} for tk, (tg, tm, _) in targets.items()}
    bench, bench_resid, bench_resid2 = {}, {}, {}
    for tk, (tg, tm, _) in targets.items():
        bench[tk], bench_resid[tk], bench_resid2[tk] = defaultdict(dict), defaultdict(dict), defaultdict(dict)
        for y in tg:
            resid = residualise(tg[y], prior[y], tm[y]) if prior[y] else None
            for name, p in bench_preds[y].items():
                if not p or len([t for t in tm[y] if t in p]) < 10:
                    continue
                miss = min(p.values()) - 1.0
                bench[tk][name][y] = rho(p, tg[y], tm[y], miss)
                if resid is not None and name != "prior_em":
                    bench_resid[tk][name][y] = rho(p, resid, tm[y], miss)
                if y in resid2[tk] and name not in ("prior_em", "consensus"):
                    bench_resid2[tk][name][y] = rho(p, resid2[tk][y], tm[y], miss)

    # model grid
    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*GRID.values())]
    combos.sort(key=lambda c: c["bball_l2_reg"])
    cache = DATA / "research" / "mbb_grid.json"
    grid, grid_resid = {}, {}
    if "--reuse-grid" in sys.argv and cache.exists():
        for item in json.loads(cache.read_text()):
            k = tuple(item["key"])
            grid[k] = {tk: {int(y): v for y, v in d.items()} for tk, d in item["rho"].items()}
            grid_resid[k] = {tk: {int(y): v for y, v in d.items()} for tk, d in item["resid"].items()}
        log(f"reused {len(grid)} grid points")
    else:
        for i, theta in enumerate(combos):
            k = tuple(theta[x] for x in keys)
            grid[k] = {tk: {} for tk in targets}
            grid_resid[k] = {tk: {} for tk in targets}
            for y in years:
                s = defaultdict(float)
                for t in run_model(y, theta).teams:
                    if t.commits_count > 0 and bart(t.name):
                        s[bart(t.name)] += t.total_score
                for tk, (tg, tm, _) in targets.items():
                    if y not in tg:
                        continue
                    grid[k][tk][y] = rho(s, tg[y], tm[y], 0.0)
                    if prior[y]:
                        grid_resid[k][tk][y] = rho(s, residualise(tg[y], prior[y], tm[y]), tm[y], 0.0)
            if (i + 1) % 60 == 0:
                log(f"grid {i + 1}/{len(combos)}")
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps([{"key": list(k), "rho": grid[k], "resid": grid_resid[k]} for k in grid]))

    draft = tuple(DRAFT_DEFAULTS[x] for x in keys)

    def model_resid2(tk, theta, y):
        s = defaultdict(float)
        for t in run_model(y, theta).teams:
            if t.commits_count > 0 and bart(t.name):
                s[bart(t.name)] += t.total_score
        tm = targets[tk][1][y]
        return rho(s, resid2[tk][y], tm, 0.0)
    out = {"years": years, "targets": {}, "match": {"commits": sum(commit_names.values()), "matched": matched,
                                                    "unmatched": unmatched_schools[:25]}}
    for tk, (tg, tm, lag) in targets.items():
        ys = sorted(tg)
        tests = [y for y in ys if len([t for t in ys if t <= y - lag]) >= MIN_TRAIN]
        def m_on(k, sub):
            return _mean(grid[k][tk], sub)
        wf, wf_resid, chosen = {}, {}, {}
        for y in tests:
            train = [t for t in ys if t <= y - lag]
            best = max(grid, key=lambda k: m_on(k, train))
            chosen[y] = dict(zip(keys, best))
            wf[y] = grid[best][tk][y]
            wf_resid[y] = grid_resid[best][tk].get(y, math.nan)
        dev = [y for y in ys if y <= DEV_LAST]
        hold = [y for y in ys if y > DEV_LAST]
        dev_best = max(grid, key=lambda k: m_on(k, dev))
        hindsight = max(grid, key=lambda k: m_on(k, tests))
        sens = {}
        for ki, kname in enumerate(keys):
            sens[kname] = {}
            for v in GRID[kname]:
                kk = list(draft)
                kk[ki] = v
                sens[kname][v] = (m_on(tuple(kk), dev), m_on(tuple(kk), hold))
        draft_resid2 = {y: model_resid2(tk, DRAFT_DEFAULTS, y) for y in ys if y in resid2[tk]}
        out["targets"][tk] = {
            "bench_resid2": {k: dict(v) for k, v in bench_resid2[tk].items()}, "draft_resid2": draft_resid2,
            "years": ys, "tests": tests, "dev": dev, "holdout": hold, "lag": lag,
            "n_teams": {y: len(tm[y]) for y in ys},
            "bench": {k: dict(v) for k, v in bench[tk].items()},
            "bench_resid": {k: dict(v) for k, v in bench_resid[tk].items()},
            "wf": wf, "wf_resid": wf_resid, "chosen": chosen,
            "draft": grid[draft][tk], "draft_resid": grid_resid[draft][tk],
            "dev_best": dict(zip(keys, dev_best)), "dev_best_rho": grid[dev_best][tk],
            "dev_gain": m_on(dev_best, dev) - m_on(draft, dev),
            "hindsight": dict(zip(keys, hindsight)), "hindsight_rho": grid[hindsight][tk],
            "sensitivity": sens,
        }
    return out


# --------------------------------------------------------------------------- part B

def link_players(ratings, players, bart_names) -> list[dict]:
    """Attach the first barttorvik season (and player id) to every recruit with a class
    year in CLASS_YEARS. Stages, in order (first hit wins):
      exact   season Y+1, same school, same normalised name
      fuzzy   season Y+1, same school, same last name, first names similar (>= 0.75)
      surname season Y+1, same school, the only freshman with that last name, and
              barttorvik lists him as a ranked recruit (legal name vs nickname)
      moved   season Y+1, other school, same normalised name, class Fr, same hometown
              city or barttorvik lists him as a ranked recruit
      late    season Y+2, same name, Fr/So, same school or (hometown / rating agrees)
    """
    by_season_team = defaultdict(list)
    by_season_key = defaultdict(list)
    by_key = defaultdict(list)
    by_id = defaultdict(list)
    for p in players:
        if p["player_id"]:
            by_id[p["player_id"]].append(p)
        by_season_team[(p["season"], p["team"])].append(p)
        by_season_key[(p["season"], p["key"])].append(p)
        by_key[p["key"]].append(p)
    out = []
    for r in ratings:
        y = r["year"]
        if y not in CLASS_YEARS:
            continue
        rec = dict(r)
        rec["bart_school"] = to_bart(r["school"], bart_names) if r["school"] else ""
        key, last, town = player_key(r["name"]), last_name(r["name"]), hometown(r["hometown"])
        hit, stage = None, ""
        team = rec["bart_school"]
        if team:
            cands = [p for p in by_season_team.get((y + 1, team), []) if p["key"] == key]
            if cands:
                hit, stage = cands[0], "exact"
            else:
                first = key.split()[0] if key else ""
                cands = [p for p in by_season_team.get((y + 1, team), [])
                         if p["last"] == last and difflib.SequenceMatcher(None, p["key"].split()[0], first).ratio() >= 0.75]
                if len(cands) == 1:
                    hit, stage = cands[0], "fuzzy"
        if hit is None and team:
            # legal name vs nickname (Edrice / Bam Adebayo): the only freshman with this
            # surname on the team, confirmed by barttorvik listing him as a ranked recruit
            cands = [p for p in by_season_team.get((y + 1, team), [])
                     if p["last"] == last and p["class"] == "Fr"]
            if len(cands) == 1 and same_recruit(r, cands[0]):
                hit, stage = cands[0], "surname"

        def confirmed(p):  # another school or season: hometown or recruit rating must agree
            return (town and hometown(p["hometown"]) == town) or same_recruit(r, p)
        if hit is None:
            cands = [p for p in by_season_key.get((y + 1, key), []) if p["class"] == "Fr" and confirmed(p)]
            if len(cands) == 1:
                hit, stage = cands[0], "moved"
        if hit is None:
            cands = [p for p in by_season_key.get((y + 2, key), [])
                     if p["class"] in ("Fr", "So") and (p["team"] == team or confirmed(p))]
            if len(cands) == 1:
                hit, stage = cands[0], "late"
        rec["stage"] = stage
        if hit is not None:
            pid = hit["player_id"]
            career = sorted((p for p in by_id[pid] if p["season"] >= hit["season"]),
                            key=lambda p: p["season"]) if pid else [hit]
            rec["first"] = hit
            rec["career"] = career
            rec["hometown_agrees"] = bool(town) and hometown(hit["hometown"]) == town
        else:
            # why unmatched
            if not r["school"]:
                why = "no commitment listed"
            elif r["school"] in NON_COLLEGE:
                why = "turned pro (On3 lists G League / Overtime Elite / pro)"
            elif not team:
                why = "committed outside D-I / unknown school"
            else:
                later = [p for p in by_key.get(key, []) if p["season"] > y + 2
                         and (p["team"] == team or (town and hometown(p["hometown"]) == town))]
                anyy = [p for p in by_key.get(key, []) if p["season"] >= y + 1]
                if later:
                    why = "first D-I season after Y+2 (prep/JUCO/redshirt)"
                elif anyy:
                    why = "name found, school/hometown differ (ambiguous)"
                else:
                    why = "not in D-I data (pro, G League, overseas, not enrolled, name mismatch)"
            rec["why"] = why
        out.append(rec)
    return out


def career_outcomes(rec: dict) -> dict:
    c = rec["career"]
    first = rec["first"]
    rot = [p["bpm"] for p in c if p["min_pct"] >= ROTATION_MIN_PCT and not math.isnan(p["bpm"])]
    picks = [p["draft_pick"] for p in c if not math.isnan(p["draft_pick"])]
    return {
        "fr_min_pct": first["min_pct"], "fr_pts": first["pts"], "fr_bpm": first["bpm"],
        "fr_porpag": first["porpag"],
        "seasons": float(len({p["season"] for p in c})),
        "best_bpm": max(rot) if rot else math.nan,
        "career_pts": float(sum((p["pts"] if not math.isnan(p["pts"]) else 0.0) * (p["gp"] if not math.isnan(p["gp"]) else 0.0) for p in c)),
        "draft_pick": min(picks) if picks else float(UNDRAFTED),
    }


def player_study(ratings, players, bart_names, theta) -> dict:
    linked = link_players(ratings, players, bart_names)
    # model per-recruit score (offer quality) for each class, by On3 url
    score_by_url = {}
    for y in CLASS_YEARS:
        res = run_model(y, theta)
        for r in res.recruits:
            if r.committed_team:
                score_by_url[r.url] = r.score
    for rec in linked:
        rec["model_score"] = score_by_url.get(rec["url"], math.nan)

    # match rates by star tier
    tiers = defaultdict(lambda: Counter())
    whys = Counter()
    stages = Counter()
    for rec in linked:
        tier = f"{rec['stars']}-star" if rec["stars"] >= 3 else "<=2-star/unrated"
        tiers[tier]["n"] += 1
        tiers[tier]["matched"] += "first" in rec
        if "first" in rec:
            stages[rec["stage"]] += 1
        else:
            whys[rec["why"]] += 1
    by_year = {y: (sum(1 for r in linked if r["year"] == y and "first" in r), sum(1 for r in linked if r["year"] == y))
               for y in CLASS_YEARS}
    agree = [r["hometown_agrees"] for r in linked if "first" in r and r["hometown"]]
    # top-ranked unmatched recruits (hand-check list)
    unmatched_top = sorted((r for r in linked if "first" not in r and not math.isnan(r["industry_rank"])),
                           key=lambda r: (r["industry_rank"], r["year"]))[:30]
    # sample of matches to hand-check: top recruit per class + fuzzy/moved/late stages
    sample = []
    for y in CLASS_YEARS:
        top = [r for r in linked if r["year"] == y and "first" in r]
        top.sort(key=lambda r: r["industry_rank"] if not math.isnan(r["industry_rank"]) else 1e9)
        if top:
            sample.append(top[0])
    for st in ("fuzzy", "moved", "late"):
        sample += [r for r in linked if r.get("stage") == st][:4]

    matched = [r for r in linked if "first" in r]
    for r in matched:
        r["out"] = career_outcomes(r)

    signals = {
        "stars": lambda r: float(r["stars"]),
        "industry_rating": lambda r: r["industry_rating"],
        "n_offers": lambda r: float(r["n_other_schools"]),
        "model_score": lambda r: r["model_score"],
    }
    outcomes = {
        "fr_min_pct": ("freshman Min%", False),
        "fr_pts": ("freshman pts/g", False),
        "fr_bpm": ("freshman BPM", False),
        "fr_porpag": ("freshman PORPAG", False),
        "seasons": ("D-I seasons played", True),
        "best_bpm": (f"best-season BPM (Min% >= {ROTATION_MIN_PCT:g})", True),
        "career_pts": ("career points", True),
        "draft_pick": ("NBA draft (pick, undrafted = 61; sign flipped)", True),
    }
    rng = np.random.default_rng(SEED)
    table, partial, gain = {}, {}, {}
    pcts = {}
    for sname, f in signals.items():
        pcts[sname] = pct_within([f(r) for r in matched], [r["year"] for r in matched])
    years_arr = np.array([r["year"] for r in matched])
    for oname, (_, career) in outcomes.items():
        y_all = np.array([r["out"][oname] for r in matched], dtype=float)
        if oname == "draft_pick":
            y_all = -y_all
        mask = ~np.isnan(y_all)
        if career:
            mask &= years_arr <= CAREER_LAST_CLASS
        table[oname], partial[oname], gain[oname] = {}, {}, {}
        for sname in signals:
            x = pcts[sname]
            m = mask & ~np.isnan(x)
            table[oname][sname] = (*boot(_spearman, [x[m], y_all[m]], rng), int(m.sum()))
            if sname in ("model_score", "n_offers", "stars"):
                z = pcts["industry_rating"]
                m2 = m & ~np.isnan(z)
                partial[oname][sname] = (*boot(_partial, [x[m2], y_all[m2], z[m2]], rng), int(m2.sum()))
                gain[oname][sname] = _r2_gain(x[m2], y_all[m2], z[m2])
    # draft as a yes/no outcome: share drafted by industry-rating tier
    era = {}
    for label, cond in (("pre-portal classes 2014-2020", lambda y: y < PORTAL_FROM),
                        (f"portal era classes {PORTAL_FROM}-{CLASS_YEARS[-1]}", lambda y: y >= PORTAL_FROM)):
        era[label] = {}
        for oname in ("fr_min_pct", "fr_bpm"):
            y_all = np.array([r["out"][oname] for r in matched], dtype=float)
            for sname in ("industry_rating", "model_score"):
                x = pcts[sname]
                m = ~np.isnan(y_all) & ~np.isnan(x) & np.array([cond(int(v)) for v in years_arr])
                era[label][f"{oname}|{sname}"] = (*boot(_spearman, [x[m], y_all[m]], rng), int(m.sum()))
    # correlation between the signals themselves
    sig_corr = {}
    allm = [r for r in linked]
    ap = {s: pct_within([f(r) for r in allm], [r["year"] for r in allm]) for s, f in signals.items()}
    for a, b in itertools.combinations(signals, 2):
        m = ~np.isnan(ap[a]) & ~np.isnan(ap[b])
        sig_corr[f"{a} ~ {b}"] = _spearman(ap[a][m], ap[b][m])

    def brief(r):
        f = r.get("first")
        return {
            "year": r["year"], "name": r["name"], "rank": r["industry_rank"], "stars": r["stars"],
            "school": r["school"], "hometown": r["hometown"], "stage": r.get("stage", ""),
            "why": r.get("why", ""),
            "bart": None if f is None else {k: f[k] for k in ("name", "team", "season", "class", "hometown", "pts", "min_pct")},
        }
    return {
        "n_recruits": len(linked), "n_matched": len(matched), "tiers": {k: dict(v) for k, v in tiers.items()},
        "whys": dict(whys), "stages": dict(stages), "by_year": by_year,
        "hometown_agree": (sum(agree), len(agree)),
        "unmatched_top": [brief(r) for r in unmatched_top], "sample": [brief(r) for r in sample],
        "signals": list(signals), "outcomes": {k: v[0] for k, v in outcomes.items()},
        "career_outcomes": [k for k, v in outcomes.items() if v[1]],
        "table": table, "partial": partial, "gain": gain, "era": era, "sig_corr": sig_corr,
    }


# --------------------------------------------------------------------------- main

def main() -> None:
    t0 = time.time()
    em = load_team_seasons()
    bart_names = set().union(*em.values())
    ratings = load_ratings()
    players = load_players()
    consensus = load_consensus()
    log(f"{len(ratings)} On3 MBB recruits, {len(players)} barttorvik player-seasons, "
        f"{sum(len(v) for v in em.values())} team-seasons")
    team = team_study(em, ratings, consensus, bart_names)
    t2 = team["targets"]["t2"]
    adopt = t2["dev_gain"] >= ADOPT_MARGIN
    final = t2["dev_best"] if adopt else DRAFT_DEFAULTS
    log(f"team study done; dev-best (2-season target) {t2['dev_best']} gain {t2['dev_gain']:+.3f} -> "
        f"{'adopt' if adopt else 'keep draft defaults'}")
    player = player_study(ratings, players, bart_names, final)
    log(f"player study done: {player['n_matched']}/{player['n_recruits']} recruits linked")
    results = {"team": team, "player": player, "adopt": adopt, "final": final}
    log(f"finished in {time.time() - t0:.0f}s")
    out = DATA / "research"
    out.mkdir(exist_ok=True)
    (out / "mbb_results.json").write_text(json.dumps(results, indent=1, default=str))
    (MODEL_DIR / "RESEARCH_MBB.md").write_text(render(results))


# --------------------------------------------------------------------------- report

BENCH_LABELS = {
    "consensus": "On3 consensus team rank",
    "rating_sum": "sum of commits' industry ratings",
    "rating_mean": "mean industry rating of commits",
    "stars_mean": "mean commit stars",
    "prior_em": "prior-season adj. EM (not recruiting)",
}


def _ci(t) -> str:
    est, lo, hi = t[0], t[1], t[2]
    return f"{est:+.2f} [{lo:+.2f}, {hi:+.2f}]"


def _gap(d: dict) -> tuple[float, float]:
    diff = [d["bench"]["consensus"][y] - d["wf"][y] for y in d["tests"] if y in d["bench"]["consensus"]]
    return float(np.mean(diff)), float(np.std(diff, ddof=1) / math.sqrt(len(diff)))


def summary(r: dict) -> list[str]:
    """Headline numbers (all computed above); wording is fixed, numbers are not."""
    t1, t2 = r["team"]["targets"]["t1"], r["team"]["targets"]["t2"]
    p = r["player"]
    cons1 = t1["bench"]["consensus"]
    out = [
        f"- **Team level (target 1, {len(t1['tests'])} walk-forward class years):** offer model mean ρ "
        f"{_mean(t1['wf'], t1['tests']):.3f}",
        f"  vs On3 consensus {_mean(cons1, t1['tests']):.3f}, sum of industry ratings "
        f"{_mean(t1['bench']['rating_sum'], t1['tests']):.3f}, prior-season EM {_mean(t1['bench']['prior_em'], t1['tests']):.3f}.",
        f"  The model beat the consensus in {sum(1 for y in t1['tests'] if t1['wf'][y] > cons1.get(y, 9))}/"
        f"{len(t1['tests'])} years (target 2: {sum(1 for y in t2['tests'] if t2['wf'][y] > t2['bench']['consensus'].get(y, 9))}/{len(t2['tests'])}).",
        "  Paired consensus − model gap per test year: "
        + "; ".join(f"{tk.upper()} {g:+.3f} ± {e:.3f} (se)" for tk, (g, e) in
                    ((k, _gap(r["team"]["targets"][k])) for k in ("t1", "t2"))) + ".",
        f"  Beyond prior EM and the consensus it adds ρ {_mean(t1['draft_resid2'], t1['tests']):+.3f} (T1) / "
        f"{_mean(t2['draft_resid2'], t2['tests']):+.3f} (T2).",
        f"- **Parameters:** the dev-best grid point gains {t2['dev_gain']:+.3f} ρ on 2014–{DEV_LAST} "
        f"(needs {ADOPT_MARGIN}); " + ("adopted." if r["adopt"] else "draft defaults kept; the surface is flat."),
    ]
    tab, part = p["table"], p["partial"]
    # "seasons played" falls with every signal (good players leave early), so it has no "best"
    best = {o: max(p["signals"], key=lambda s_: tab[o][s_][0]) for o in p["outcomes"] if o != "seasons"}
    n_best = Counter(best.values()).most_common(1)[0]
    out += [
        f"- **Player level ({p['n_matched']}/{p['n_recruits']} recruits linked):** the best signal is "
        f"`{n_best[0]}` for {n_best[1]}/{len(best)} outcomes (seasons played excluded)",
        f"  (freshman BPM ρ {tab['fr_bpm']['industry_rating'][0]:+.2f} vs model_score "
        f"{tab['fr_bpm']['model_score'][0]:+.2f}; draft {tab['draft_pick']['industry_rating'][0]:+.2f} vs "
        f"{tab['draft_pick']['model_score'][0]:+.2f}).",
        "  Partial ρ of model_score given the industry rating: "
        + ", ".join(f"{o} {part[o]['model_score'][0]:+.2f}" for o in ("fr_min_pct", "fr_bpm", "best_bpm", "draft_pick"))
        + ".",
    ]
    return out


def render(r: dict) -> str:
    team, player = r["team"], r["player"]
    tt = team["targets"]
    t1, t2 = tt["t1"], tt["t2"]
    mt = team["match"]
    L = [
        "# RESEARCH (MBB) — men's basketball recruiting vs team and player outcomes",
        "",
        "_Generated by `python -m ballmonitor.models.ncaaf_recruiting.research_mbb`; "
        "do not edit by hand._",
        "",
        "**Questions.** (A) Within a class year, does the offer-based class score rank",
        "programs like their later strength, compared with industry ratings, stars,",
        "the On3 consensus team rank and last season's strength? (B) Which recruit",
        "signal best predicts what a player does in college, and does the offer-based",
        "recruit score add anything beyond the industry rating?",
        "",
        "**Data.** On3 recruit database, MBB classes "
        f"{CLASS_YEARS[0]}–{CLASS_YEARS[-1]} ({player['n_recruits']} On3-ranked",
        "recruits with offer lists and industry ratings). Barttorvik adjusted",
        "efficiency margin (adj. EM, points per 100 possessions vs an average D-I team)",
        f"and player seasons {CLASS_YEARS[0] + 1}–{LAST_SEASON} (season = spring year).",
        f"School names: {mt['matched']}/{mt['commits']} commits "
        f"({mt['matched'] / mt['commits']:.1%}) map to a barttorvik D-I team; the rest",
        "are non-D-I or unknown schools: "
        + ", ".join(f"{s} ({n})" for s, n in mt["unmatched"][:10]) + ".",
        "",
        "## Summary",
        "",
        *summary(r),
        "",
        "## A. Team level",
        "",
        "Target 1: adj. EM in the freshman season Y+1. Target 2: mean adj. EM of seasons",
        "Y+1 and Y+2. Programs: D-I teams with at least one On3-ranked commit in class Y",
        f"(about {int(np.median(list(t1['n_teams'].values())))} a year). Spearman ρ within each class year; means over class",
        "years (± one standard error across years).",
        "",
        f"Walk-forward: model parameters for test class Y are chosen on classes ≤ Y−1",
        f"(target 1) or ≤ Y−2 (target 2), at least {MIN_TRAIN} classes. Test classes:",
        f"target 1 {t1['tests'][0]}–{t1['tests'][-1]} (**{len(t1['tests'])} independent class years**), "
        f"target 2 {t2['tests'][0]}–{t2['tests'][-1]}",
        f"(**{len(t2['tests'])}**, consecutive 2-season targets share a season).",
        "",
    ]
    for tk, title in (("t1", "Target 1 — freshman-season adj. EM"), ("t2", "Target 2 — mean adj. EM, seasons Y+1..Y+2")):
        d = tt[tk]
        tests = d["tests"]
        wf = d["wf"]
        def beat(x):
            return sum(1 for y in tests if y in x and wf[y] > x[y])
        L += [f"### {title}", "",
              "| ranking | mean ρ (tests) | ± se | years model wins | ρ after prior EM |",
              "|---|---:|---:|---:|---:|",
              f"| **offer model, walk-forward params** | **{_mean(wf, tests):.3f}** | {_se(wf, tests):.3f} | – | "
              f"{_mean(d['wf_resid'], tests):.3f} |",
              f"| offer model, v0.4.0 draft defaults | {_mean(d['draft'], tests):.3f} | {_se(d['draft'], tests):.3f} | "
              f"{beat(d['draft'])}/{len(tests)} | {_mean(d['draft_resid'], tests):.3f} |"]
        for k, label in BENCH_LABELS.items():
            b = d["bench"].get(k, {})
            if not b:
                continue
            yrs = [y for y in tests if y in b]
            note = "" if len(yrs) == len(tests) else f" ({len(yrs)} yrs)"
            L.append(f"| {label}{note} | {_mean(b, yrs):.3f} | {_se(b, yrs):.3f} | {beat(b)}/{len(yrs)} | "
                     + ("–" if k == "prior_em" else f"{_mean(d['bench_resid'].get(k, {}), yrs):.3f}") + " |")
        L += [f"| _hindsight best grid point (not a forecast)_ | _{_mean(d['hindsight_rho'], tests):.3f}_ | | | |", ""]
        r2 = d["bench_resid2"]
        L += ["Beyond the consensus: mean ρ (test years) with the part of the target not explained",
              "by prior-season EM and ln(consensus rank): offer model (draft defaults) "
              f"{_mean(d['draft_resid2'], tests):+.3f}, "
              + ", ".join(f"{BENCH_LABELS[k]} {_mean(r2[k], tests):+.3f}" for k in ("rating_sum", "rating_mean", "stars_mean") if k in r2)
              + ".", ""]
        L += ["| class | teams | model (WF) | params (decay, power, l2, cornerstone) | consensus | rating sum | stars | prior EM |",
              "|---|---:|---:|---|---:|---:|---:|---:|"]
        for y in d["years"]:
            c = d["chosen"].get(y)
            ctext = (f"{c['rotation_decay']}, {c['bball_quality_power']}, {c['bball_l2_reg']}, {c['cornerstone_weight']}"
                     if c else "(training only)")
            mv = f"{wf[y]:.3f}" if y in wf else f"_{d['draft'][y]:.3f} (draft, in-sample)_"
            cells = [f"{d['bench'].get(k, {}).get(y, math.nan):.3f}".replace("nan", "–")
                     for k in ("consensus", "rating_sum", "stars_mean", "prior_em")]
            L.append(f"| {y} | {d['n_teams'][y]} | {mv} | {ctext} | " + " | ".join(cells) + " |")
        L.append("")
    # defaults
    dev, hold = t2["dev"], t2["holdout"]
    L += [
        "### Defaults (decided on development classes only)",
        "",
        f"Rule: on target 2 and classes {dev[0]}–{dev[-1]}, the best grid point",
        f"`{t2['dev_best']}`",
        f"beats the v0.4.0 draft defaults by {t2['dev_gain']:+.3f} ρ; it is adopted only if the gain is",
        f"≥ {ADOPT_MARGIN}. " + ("**Adopted.**" if r["adopt"] else "**Not adopted; the draft defaults are kept.**"),
        f"Holdout classes {hold[0]}–{hold[-1]} (target 2) / {t1['holdout'][0]}–{t1['holdout'][-1]} (target 1) did not influence the choice.",
        "",
        "| ranking | dev ρ (T2) | holdout ρ (T2) | dev ρ (T1) | holdout ρ (T1) |",
        "|---|---:|---:|---:|---:|",
        f"| offer model, dev-best | {_mean(t2['dev_best_rho'], dev):.3f} | {_mean(t2['dev_best_rho'], hold):.3f} | "
        f"{_mean(t1['dev_best_rho'], t1['dev']):.3f} (own dev-best) | {_mean(t1['dev_best_rho'], t1['holdout']):.3f} |",
        f"| offer model, draft defaults | {_mean(t2['draft'], dev):.3f} | {_mean(t2['draft'], hold):.3f} | "
        f"{_mean(t1['draft'], t1['dev']):.3f} | {_mean(t1['draft'], t1['holdout']):.3f} |",
    ]
    for k, label in BENCH_LABELS.items():
        b2, b1 = t2["bench"].get(k, {}), t1["bench"].get(k, {})
        L.append(f"| {label} | {_mean(b2, dev):.3f} | {_mean(b2, hold):.3f} | {_mean(b1, t1['dev']):.3f} | "
                 f"{_mean(b1, t1['holdout']):.3f} |".replace("nan", "–"))
    L += ["", "Sensitivity (target 2, dev / holdout mean ρ, one parameter changed from the draft defaults):", ""]
    for k, vals in t2["sensitivity"].items():
        L.append(f"- `{k}`: " + "; ".join(f"{v} → {a:.3f} / {b:.3f}" for v, (a, b) in vals.items()))
    # part B
    p = player
    L += [
        "",
        "## B. Player level",
        "",
        "### Linking recruits to barttorvik",
        "",
        f"{p['n_matched']} of {p['n_recruits']} recruits ({p['n_matched'] / p['n_recruits']:.1%}) were linked to a",
        "first D-I season. Stages (first hit wins): exact = season Y+1, same school, same",
        "normalised name (accents, punctuation, Jr./II/III and common nicknames removed);",
        "fuzzy = same school and last name, similar first name; surname = the only",
        "freshman with that last name on the team, listed by barttorvik as a ranked",
        "recruit (Edrice 'Bam' Adebayo); moved = other school, same name, freshman, same",
        "hometown or ranked by barttorvik; late = season Y+2, freshman/sophomore.",
        "",
        "| stage | recruits |", "|---|---:|",
        *[f"| {k} | {v} |" for k, v in sorted(p["stages"].items(), key=lambda kv: -kv[1])],
        "",
        f"Check: the barttorvik hometown city agrees with On3's for "
        f"{p['hometown_agree'][0]}/{p['hometown_agree'][1]} linked recruits "
        f"({p['hometown_agree'][0] / max(1, p['hometown_agree'][1]):.1%}). A hand check of disagreements found",
        "neighbouring towns, prep-school towns and foreign birthplaces (Bellaire vs",
        "Houston TX, Wayne PA vs Accra), not wrong people; every 'surname' link and the",
        "'moved'/'late' samples below were checked by hand against the players' careers.",
        "",
        "| tier | recruits | linked | rate |", "|---|---:|---:|---:|",
    ]
    for tier in sorted(p["tiers"], key=lambda t: t, reverse=True):
        c = p["tiers"][tier]
        L.append(f"| {tier} | {c['n']} | {c['matched']} | {c['matched'] / c['n']:.1%} |")
    L += ["", "| class | linked / recruits |", "|---|---:|"]
    for y, (a, b) in sorted(p["by_year"].items(), key=lambda kv: int(kv[0])):
        L.append(f"| {y} | {a} / {b} |")
    L += ["", "Why recruits were not linked:", "", "| reason | recruits |", "|---|---:|",
          *[f"| {k} | {v} |" for k, v in sorted(p["whys"].items(), key=lambda kv: -kv[1])], "",
          "Highest-ranked unlinked recruits (for hand checks):", "",
          "| class | rank | name | On3 school | reason |", "|---|---:|---|---|---|"]
    for u in p["unmatched_top"][:20]:
        L.append(f"| {u['year']} | {int(u['rank'])} | {u['name']} | {u['school'] or '–'} | {u['why']} |")
    L += ["", "Sample of links (top recruit of each class, plus non-exact stages):", "",
          "| class | On3 name | On3 school | stage | barttorvik name, team, season | pts | Min% |",
          "|---|---|---|---|---|---:|---:|"]
    for s in p["sample"]:
        b = s["bart"]
        L.append(f"| {s['year']} | {s['name']} | {s['school']} | {s['stage']} | {b['name']}, {b['team']}, "
                 f"{b['season']} ({b['class']}) | {b['pts']:.1f} | {b['min_pct']:.1f} |")
    L += [
        "",
        "### Which signal predicts college production?",
        "",
        "Spearman ρ [bootstrap 95% interval] between a recruit signal and an outcome, over",
        "linked recruits. Signals are within-class percentiles (so class years with",
        "different On3 coverage pool fairly). n = recruits used. Freshman outcomes: all",
        f"classes; career and draft outcomes: classes ≤ {CAREER_LAST_CLASS} (≥ 5 seasons since).",
        "`model_score` = the offer model's per-recruit score (summed prestige of the",
        "schools the recruit turned down, ^ bball_quality_power); `n_offers` = schools",
        "On3 lists besides the commit.",
        "",
        "| outcome | n | stars | industry rating | n_offers | model_score |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for o, label in p["outcomes"].items():
        row = p["table"][o]
        n = row["industry_rating"][3]
        L.append(f"| {label} | {n} | " + " | ".join(_ci(row[s]) for s in p["signals"]) + " |")
    L += [
        "",
        "### Does the offer-based score add information beyond the industry rating?",
        "",
        "Partial Spearman ρ of each signal with the outcome after removing the industry",
        "rating (both ranked, linear residuals), [bootstrap 95%], and the gain in R² of",
        "rank(outcome) from adding the signal to rank(industry rating).",
        "",
        "| outcome | model_score partial ρ | ΔR² | n_offers partial ρ | ΔR² | stars partial ρ | ΔR² |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for o, label in p["outcomes"].items():
        pr, g = p["partial"][o], p["gain"][o]
        L.append(f"| {label} | {_ci(pr['model_score'])} | {g['model_score']:.3f} | {_ci(pr['n_offers'])} | "
                 f"{g['n_offers']:.3f} | {_ci(pr['stars'])} | {g['stars']:.3f} |")
    L += ["", "Signals are strongly related to each other (Spearman of within-class percentiles, all recruits):", ""]
    L += [", ".join(f"{k} {v:.2f}" for k, v in p["sig_corr"].items()) + ".", ""]
    L += ["By era (freshman outcomes):", "", "| era | outcome | industry rating | model_score |", "|---|---|---:|---:|"]
    for era, d in p["era"].items():
        for o in ("fr_min_pct", "fr_bpm"):
            L.append(f"| {era} | {p['outcomes'][o]} | {_ci(d[o + '|industry_rating'])} | "
                     f"{_ci(d[o + '|model_score'])} |")
    L += [
        "",
        "## Caveats",
        "",
        f"- Team level: {len(t1['tests'])} (target 1) / {len(t2['tests'])} (target 2) walk-forward test years; a few",
        "  hundredths of ρ are within noise (see ± se). One class is a small part of a",
        "  13-man roster, so most of the team-level signal is program inertia (compare the",
        "  prior-EM row and the 'after prior EM' column).",
        f"- Transfer-portal era: from the {PORTAL_FROM} class on, players can transfer without",
        "  sitting out and rosters turn over quickly, so a high-school class is a smaller",
        "  share of next season's team. The 2020-21 season (freshman year of the 2020",
        "  class) was shortened by COVID and gave every player an extra year of eligibility.",
        "- On3's historical data are as On3 lists them today: offer lists may have been",
        "  completed after the fact, and the committed school is the one the player",
        "  enrolled at (Enrolled > Signed > Committed), which was not always known at",
        "  signing. Industry ratings for old classes are final ratings. Mild hindsight.",
        "- The On3 consensus team ranks for classes before On3 existed (pre-2021) were",
        "  compiled by On3 from the services' final ratings: a mild hindsight risk.",
        "- NBA draft picks come from barttorvik's per-player draft column (picks 1–60,",
        "  repeated on every season of a drafted player).",
        "- Only On3-ranked recruits (~140–410 a class; 2021 is thin) are in the files;",
        "  programs that sign unranked players look empty.",
        "- Player outcomes exist only for recruits who played D-I basketball; those who went",
        "  straight to the G League, overseas or the NBA are missing (often top recruits), so",
        "  draft and production correlations are conditional on reaching D-I.",
        "- Barttorvik BPM is a box-score estimate; low-minute seasons are noisy (best-season",
        f"  BPM uses only seasons with Min% ≥ {ROTATION_MIN_PCT:g}).",
        "- Bootstrap intervals resample recruits and ignore clustering by class year and",
        "  team, so they are somewhat too narrow.",
        "",
        "## Run log",
        "",
        "```",
        *LOG,
        "```",
        "",
    ]
    return "\n".join(L)


if __name__ == "__main__":
    main()
