"""MBB: seed program strength with recent on-court results before fitting the offer model.
Writes RESEARCH_MBB_SEED.md (generated, never hand-edit).

    python ballmonitor/models/ncaaf_recruiting/research_mbb_seed.py

Idea: with ~300 ranked MBB recruits a year there are few offer "battles", so Plackett-Luce
program strengths barely separate and a recruit's score is mostly an offer count. Here
each program's strength starts at a prior mean from its on-court results instead of 0:

    mu(program) = seed_beta * mean adj. EM over seasons y-2 and y-1 / 10

(seasons that ended before the class's junior-year offers; programs without barttorvik
data start at the D-I minimum). Also tested: counting the committed school's strength
in the recruit score (`commit_weight`), and scoring by the strongest school instead of
the sum (`aggregate`).

Walk-forward: every setting is chosen on development classes 2014-2019 only (objective:
mean within-class Spearman of recruit score vs freshman BPM among linked recruits);
results are reported on test classes 2020-2025, which played no part in any choice.
"""

from __future__ import annotations

import itertools
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

MODEL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODEL_DIR))
import research_mbb as R  # noqa: E402
from src.elo_engine import EloEngine  # noqa: E402
from src.mbb_names import to_bart  # noqa: E402
from src.models import RankingMethod  # noqa: E402

DEV = list(range(2014, 2020))
TEST = list(range(2020, 2026))
DRAFT_CLASSES = range(2014, 2022)  # draft outcome known
GRID = {
    "seed_beta": [0.0, 0.5, 1.0, 2.0, 3.0],
    "l2": [0.05, 0.5, 2.0, 8.0],
    "commit_weight": [0.0, 1.0, 3.0],
    "aggregate": ["sum", "max"],
    "quality_power": [0.6, 1.0],
}
CURRENT = {"seed_beta": 0.0, "l2": 0.05, "commit_weight": 0.0, "aggregate": "sum", "quality_power": 0.6}


class Data:
    def __init__(self):
        self.em = R.load_team_seasons()
        self.bart_names = set().union(*self.em.values())
        self.ratings = R.load_ratings()
        players = R.load_players()
        self.consensus = R.load_consensus()
        self._b: dict[str, str] = {}
        linked = R.link_players(self.ratings, players, self.bart_names)
        self.linked = {}
        for rec in linked:
            if "first" in rec:
                rec["out"] = R.career_outcomes(rec)
                self.linked[rec["url"]] = rec
        self.recruits = {y: R.recruits(y) for y in DEV + TEST}
        self.min_em = min(v for s in self.em.values() for v in s.values())

    def bart(self, school: str) -> str:
        if school not in self._b:
            self._b[school] = to_bart(school, self.bart_names) or ""
        return self._b[school]

    def seed_em(self, y: int, school: str) -> float:
        b = self.bart(school)
        vals = [self.em[s][b] for s in (y - 2, y - 1) if s in self.em and b in self.em[s]]
        return float(np.mean(vals)) if vals else self.min_em


def run(d: Data, y: int, cfg: dict):
    recs = d.recruits[y]
    prior = {}
    if cfg["seed_beta"]:
        teams = {t for r in recs for t in r.all_teams}
        prior = {t: cfg["seed_beta"] * d.seed_em(y, t) / 10.0 for t in teams}
    eng = EloEngine(method=RankingMethod.PLACKETT_LUCE, l2_reg=cfg["l2"],
                    quality_power=cfg["quality_power"], rank_decay=R.DRAFT_DEFAULTS["rotation_decay"],
                    cornerstone_weight=R.DRAFT_DEFAULTS["cornerstone_weight"],
                    prior_gamma=prior, commit_weight=cfg["commit_weight"], aggregate=cfg["aggregate"])
    return eng.run(y, recs)


def recruit_scores(d: Data, y: int, cfg: dict) -> dict[str, float]:
    res = run(d, y, cfg)
    return {r.url: r.score for r in res.recruits if r.committed_team}


def player_rho(d: Data, scores_by_year: dict, years, outcome: str, partial: bool = False) -> float:
    vals = []
    for y in years:
        rs = [d.linked[u] for u in scores_by_year[y] if u in d.linked]
        rs = [r for r in rs if not math.isnan(r["out"][outcome]) and not math.isnan(r["industry_rating"])]
        if len(rs) < 20:
            continue
        x = np.array([scores_by_year[y][r["url"]] for r in rs])
        z = np.array([r["industry_rating"] for r in rs])
        t = np.array([r["out"][outcome] for r in rs])
        if outcome == "draft_pick":
            t = -t  # earlier pick = better
        vals.append(R._partial(x, t, z) if partial else R._spearman(x, t))
    return float(np.mean(vals)) if vals else math.nan


def benchmark_scores(d: Data, y: int, kind: str) -> dict[str, float]:
    out = {}
    by_url = {r["url"]: r for r in d.ratings if r["year"] == y}
    for r in d.recruits[y]:
        if not r.committed_team:
            continue
        info = by_url.get(r.url)
        if kind == "industry":
            out[r.url] = info["industry_rating"] if info and not math.isnan(info["industry_rating"]) else 0.0
        elif kind == "stars":
            out[r.url] = float(info["stars"]) if info else 0.0
        elif kind == "commit_seed":  # prestige of the school he chose, no offer data at all
            out[r.url] = d.seed_em(y, r.committed_team)
        elif kind == "best_offer_seed":  # best on-court program among all his schools
            out[r.url] = max(d.seed_em(y, t) for t in r.all_teams)
    return out


def team_rho(d: Data, y: int, cfg: dict) -> tuple[float, float]:
    """Class score vs adj. EM in season y+1 among programs with commits; and the same vs
    the residual after prior-season adj. EM and ln(consensus rank)."""
    if y + 1 not in d.em:
        return math.nan, math.nan
    s = defaultdict(float)
    for t in run(d, y, cfg).teams:
        if t.commits_count > 0 and d.bart(t.name):
            s[d.bart(t.name)] += t.total_score
    tg = {t: d.em[y + 1][t] for t in s if t in d.em[y + 1]}
    teams = sorted(tg)
    cons = {d.bart(t): rk for t, rk in d.consensus.get(y, {}).items() if d.bart(t)}
    resid = R.residualise2(tg, d.em.get(y, {}), cons, teams) if d.em.get(y) and cons else None
    a = R.rho(s, tg, teams, 0.0)
    b = R.rho(s, resid, teams, 0.0) if resid else math.nan
    return a, b


def main() -> None:
    d = Data()
    keys = list(GRID)
    configs = [dict(zip(keys, v)) for v in itertools.product(*GRID.values())]

    # 1. choose on development classes
    dev_obj = {}
    for cfg in configs:
        sc = {y: recruit_scores(d, y, cfg) for y in DEV}
        dev_obj[tuple(cfg.values())] = player_rho(d, sc, DEV, "fr_bpm")
    best_key = max(dev_obj, key=dev_obj.get)
    best = dict(zip(keys, best_key))
    seed_only = dict(best, seed_beta=best["seed_beta"] or 2.0, l2=1000.0)  # offers can't move the seed
    variants = {
        "current model (v0.5.0)": CURRENT,
        "current + seed only (same scoring)": dict(CURRENT, seed_beta=best["seed_beta"] or 2.0,
                                                   l2=best["l2"]),
        "best on dev classes": best,
        "best, seed frozen (offers ignored)": seed_only,
    }

    outcomes = [("fr_bpm", "freshman BPM"), ("fr_pts", "freshman pts/g"), ("fr_min_pct", "freshman Min%"),
                ("best_bpm", "best-season BPM"), ("draft_pick", "NBA draft")]
    test_scores = {name: {y: recruit_scores(d, y, cfg) for y in TEST} for name, cfg in variants.items()}
    draft_years = [y for y in DRAFT_CLASSES]
    draft_scores = {name: {y: recruit_scores(d, y, cfg) for y in draft_years} for name, cfg in variants.items()}
    for kind, label in (("industry", "industry rating"), ("stars", "stars"),
                        ("commit_seed", "committed school's on-court seed"),
                        ("best_offer_seed", "best offering school's seed")):
        test_scores[label] = {y: benchmark_scores(d, y, kind) for y in TEST}
        draft_scores[label] = {y: benchmark_scores(d, y, kind) for y in draft_years}

    L = ["# MBB: seeding the offer model with on-court results", "",
         "_Generated by `research_mbb_seed.py` — do not edit by hand._", "",
         "Program strengths start at `seed_beta × mean adj. EM (seasons y−2, y−1) / 10` instead of 0, "
         "then the offer battles move them (shrinkage `l2`). Also tested: counting the committed "
         "school (`commit_weight`) and scoring by the strongest school (`aggregate = max`).", "",
         f"Grid: {len(configs)} settings, chosen on development classes {DEV[0]}-{DEV[-1]} by mean "
         f"within-class Spearman ρ with freshman BPM. Test classes {TEST[0]}-{TEST[-1]} "
         f"({len(TEST)} independent class years) played no part in any choice; NBA draft uses "
         f"classes {draft_years[0]}-{draft_years[-1]}, which overlap the development years (flagged).", "",
         f"Development optimum: `{best}` (dev ρ {dev_obj[best_key]:.3f}; current model "
         f"{dev_obj[tuple(CURRENT.values())]:.3f}).", ""]

    # top dev settings
    top = sorted(dev_obj.items(), key=lambda kv: -kv[1])[:8]
    L += ["Top development settings:", "", "| " + " | ".join(keys) + " | dev ρ |",
          "|" + "---|" * (len(keys) + 1)]
    for k, v in top:
        L.append("| " + " | ".join(str(x) for x in k) + f" | {v:.3f} |")
    L.append("")
    by_beta = defaultdict(float)
    for k, v in dev_obj.items():
        by_beta[k[0]] = max(by_beta[k[0]], v)
    L += ["Best development ρ for each seed strength: " +
          ", ".join(f"β={b}: {v:.3f}" for b, v in sorted(by_beta.items())), ""]

    L += ["## Recruit level (test classes)", "",
          "Mean within-class Spearman ρ between the recruit score and the outcome, among recruits "
          "linked to barttorvik (see RESEARCH_MBB.md). ‘partial’ = ρ after controlling for the "
          "industry rating (does the score add information beyond it?).", "",
          "| score | " + " | ".join(lbl for _, lbl in outcomes) + " | partial: fr BPM | partial: draft |",
          "|---|" + "---:|" * (len(outcomes) + 2)]
    for name in test_scores:
        cells = []
        for key, _ in outcomes:
            src, yrs = (draft_scores[name], draft_years) if key == "draft_pick" else (test_scores[name], TEST)
            cells.append(f"{player_rho(d, src, yrs, key):+.3f}")
        if name == "industry rating":
            p1 = p2 = "—"
        else:
            p1 = f"{player_rho(d, test_scores[name], TEST, 'fr_bpm', partial=True):+.3f}"
            p2 = f"{player_rho(d, draft_scores[name], draft_years, 'draft_pick', partial=True):+.3f}"
        L.append(f"| {name} | " + " | ".join(cells) + f" | {p1} | {p2} |")
    L.append("")

    L += ["## Team level (test classes)", "",
          "Mean within-year ρ between the class score and adj. EM in the freshman season (programs "
          "with ≥1 commit), and with the residual after prior-season adj. EM and ln(consensus rank) "
          "(what the class score adds beyond both).", "",
          "| model | ρ next-season adj. EM | ρ residual (beyond prior + consensus) |", "|---|---:|---:|"]
    for name, cfg in variants.items():
        rs = [team_rho(d, y, cfg) for y in TEST]
        a = np.nanmean([x[0] for x in rs])
        b = np.nanmean([x[1] for x in rs])
        L.append(f"| {name} | {a:.3f} | {b:+.3f} |")
    L.append("")

    # 4. Freshman BPM rewards team quality (a player on a strong team posts a higher BPM),
    # so re-choose on outcomes that depend more on the player himself.
    L += ["## Choosing on player-driven outcomes instead", "",
          "Freshman BPM is partly a *team* statistic: the committed school's seed alone (no player "
          "information) has ρ ≈ 0.37 with freshman BPM but ≈ 0.05 with points and minutes. So the "
          "grid is re-run choosing on each player-driven outcome (development classes; draft: "
          "2014-2018 dev, 2019-2021 test).", "",
          "| chosen on | dev-best setting | test ρ: current | test ρ: dev-best | partial (beyond industry): current | partial: dev-best | industry rating ρ |",
          "|---|---|---:|---:|---:|---:|---:|"]
    cache: dict = {}

    def sc(cfg, years):
        k = tuple(cfg.values())
        if k not in cache:
            cache[k] = {y: recruit_scores(d, y, cfg) for y in range(DEV[0], TEST[-1] + 1)}
        return {y: cache[k][y] for y in years}

    for key, label in (("fr_pts", "freshman pts/g"), ("fr_min_pct", "freshman Min%"), ("draft_pick", "NBA draft")):
        dev_y = DEV if key != "draft_pick" else list(range(2014, 2019))
        test_y = TEST if key != "draft_pick" else [2019, 2020, 2021]
        pick = max(configs, key=lambda c: player_rho(d, sc(c, dev_y), dev_y, key))
        ind = {y: benchmark_scores(d, y, "industry") for y in test_y}
        L.append(f"| {label} | `{pick}` | {player_rho(d, sc(CURRENT, test_y), test_y, key):+.3f} | "
                 f"{player_rho(d, sc(pick, test_y), test_y, key):+.3f} | "
                 f"{player_rho(d, sc(CURRENT, test_y), test_y, key, partial=True):+.3f} | "
                 f"{player_rho(d, sc(pick, test_y), test_y, key, partial=True):+.3f} | "
                 f"{player_rho(d, ind, test_y, key):+.3f} |")
    L.append("")

    zero = sum(1 for y in TEST for r in d.recruits[y] if r.committed_team and len(r.all_teams) <= 1)
    tot = sum(1 for y in TEST for r in d.recruits[y] if r.committed_team)
    L += ["## Notes", "",
          f"- {zero} of {tot} test-class commits list no other school; the original score gives them 0 "
          "(e.g. Anthony Edwards, #1 in 2019). A committed-school term (`commit_weight` > 0) or a seed "
          "fixes that.",
          "- Seeds use only seasons that ended before the class's junior-year offers.",
          "- Linked recruits only (players who reached D-I). Intervals are not shown; with 6 test "
          "years, differences under ~0.02 ρ should be treated as noise.",
          ""]
    (MODEL_DIR / "RESEARCH_MBB_SEED.md").write_text("\n".join(L))
    print("wrote RESEARCH_MBB_SEED.md; dev best", best, round(dev_obj[best_key], 3))


if __name__ == "__main__":
    main()
