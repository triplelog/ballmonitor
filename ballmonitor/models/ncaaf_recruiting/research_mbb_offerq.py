"""MBB: value recruits by the on-court strength of the schools they turned down, and
combine that with industry ratings.  Writes RESEARCH_MBB_OFFERQ.md (generated).

    python ballmonitor/models/ncaaf_recruiting/research_mbb_offerq.py

Recruit offer quality (OQ): an aggregate of the barttorvik adj. EM of the schools in his
offer list *other than the one he chose* (the committed school's own strength is never
used), from the season(s) before his junior-year offers:
    seed  prev = season y-1            two = mean of seasons y-2, y-1
    agg   max | top3 (mean of best 3) | mean | sum_pos (sum of positive EM) |
          soft (5 * log sum exp(EM/5), a smooth max that also rewards depth)
Recruits listing no other school get the class's lowest OQ ("floor") or its median.

Recruit value = exp(k * c), where c is z(industry rating) + w * z(OQ), standardised within
the class (z = normal scores of within-class percentiles; w = inf is OQ alone) — k makes
the value top-heavy. Class strength = sum over commits of value, sorted, times
decay**(i-1).

Team-level evaluation, on two sets of programs: those with >= 1 ranked commit in class y
("committed", where the recruit values matter), and every D-I team (no commits = 0):
  rho      within-year Spearman with adj. EM in season y+1
  resid    Spearman with the residual of season y+1 after prior-season adj. EM and
           ln(consensus rank)  (what the class adds beyond both)
  dRMSE    walk-forward linear model prior + consensus + class strength vs prior +
           consensus (fitted on earlier classes only)
Every setting is chosen on development classes 2014-2019 by mean `resid` over committed
programs; test classes 2020-2025 played no part.
"""

from __future__ import annotations

import itertools
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import norm, rankdata, spearmanr

MODEL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODEL_DIR))
import research_mbb as R  # noqa: E402
import research_mbb_seed as S  # noqa: E402

DEV = list(range(2014, 2020))
TEST = list(range(2020, 2026))
SEEDS = ["prev", "two"]
AGGS = ["max", "top3", "mean", "sum_pos", "soft"]
FILLS = ["floor", "median"]
WEIGHTS = [0.0, 0.25, 0.5, 1.0, 2.0, math.inf]
DECAYS = [0.5, 0.75, 1.0]
STEEP = [0.5, 1.0, 1.5, 2.0, 3.0]


class Study:
    def __init__(self):
        self.d = S.Data()
        d = self.d
        self.rating = {r["url"]: r["industry_rating"] for r in d.ratings}
        self.cons = {y: {d.bart(t): rk for t, rk in d.consensus.get(y, {}).items() if d.bart(t)}
                     for y in DEV + TEST}
        self._oq: dict = {}

    def seed(self, y: int, school: str, kind: str) -> float:
        d = self.d
        b = d.bart(school)
        seasons = (y - 1,) if kind == "prev" else (y - 2, y - 1)
        vals = [d.em[s][b] for s in seasons if s in d.em and b in d.em[s]]
        return float(np.mean(vals)) if vals else d.min_em

    def offer_quality(self, y: int, seed: str, agg: str, fill: str) -> dict[str, float]:
        key = (y, seed, agg, fill)
        if key in self._oq:
            return self._oq[key]
        raw = {}
        for r in self.d.recruits[y]:
            if not r.committed_team:
                continue
            s = sorted((self.seed(y, t, seed) for t in r.all_teams if t != r.committed_team), reverse=True)
            if not s:
                raw[r.url] = None
            elif agg == "max":
                raw[r.url] = s[0]
            elif agg == "top3":
                raw[r.url] = float(np.mean(s[:3]))
            elif agg == "mean":
                raw[r.url] = float(np.mean(s))
            elif agg == "sum_pos":
                raw[r.url] = float(sum(max(0.0, v) for v in s))
            else:
                m = max(s)
                raw[r.url] = m + 5.0 * math.log(sum(math.exp((v - m) / 5.0) for v in s))
        known = [v for v in raw.values() if v is not None]
        filler = (min(known) if fill == "floor" else float(np.median(known))) if known else 0.0
        out = {u: (v if v is not None else filler) for u, v in raw.items()}
        self._oq[key] = out
        return out

    def recruit_value(self, y: int, cfg: dict) -> dict[str, float]:
        recs = [r for r in self.d.recruits[y] if r.committed_team]
        urls = [r.url for r in recs]
        rat = np.array([self.rating.get(u, math.nan) for u in urls])
        rat = np.where(np.isnan(rat), np.nanmin(rat), rat)
        n = len(urls)
        z_rat = norm.ppf((rankdata(rat) - 0.5) / n)
        oq = self.offer_quality(y, cfg["seed"], cfg["agg"], cfg["fill"])
        z_oq = norm.ppf((rankdata([oq[u] for u in urls]) - 0.5) / n)
        w = cfg["w"]
        c = z_oq if math.isinf(w) else z_rat + w * z_oq
        c = c / (c.std() or 1.0)
        return dict(zip(urls, np.exp(cfg["k"] * c)))

    def class_strength(self, y: int, cfg: dict) -> dict[str, float]:
        d = self.d
        val = self.recruit_value(y, cfg)
        by_team = defaultdict(list)
        for r in d.recruits[y]:
            if r.committed_team and d.bart(r.committed_team):
                by_team[d.bart(r.committed_team)].append(val[r.url])
        return {t: sum(v * cfg["decay"] ** i for i, v in enumerate(sorted(vs, reverse=True)))
                for t, vs in by_team.items()}

    def rows(self, y: int):
        em = self.d.em
        return sorted(t for t in em[y + 1] if t in em[y])

    def committed(self, y: int) -> set[str]:
        d = self.d
        return {d.bart(r.committed_team) for r in d.recruits[y] if r.committed_team and d.bart(r.committed_team)}

    def team_eval(self, y: int, strength: dict[str, float], only_committed: bool = True) -> tuple[float, float]:
        em = self.d.em
        teams = self.rows(y)
        if only_committed:
            teams = [t for t in teams if t in self.committed(y)]
        tg = {t: em[y + 1][t] for t in teams}
        resid = R.residualise2(tg, em[y], self.cons[y], teams)
        x = [strength.get(t, 0.0) for t in teams]
        return (float(spearmanr(x, [tg[t] for t in teams]).statistic),
                float(spearmanr(x, [resid[t] for t in teams]).statistic))

    def walk_forward_rmse(self, strengths: dict[int, dict[str, float]] | None):
        """RMSE over test years of prior + ln-consensus (+ class strength) linear model."""
        em = self.d.em
        data = {}
        for y in DEV + TEST:
            teams = self.rows(y)
            worst = max(self.cons[y].values(), default=0) + 1
            X = [[1.0, em[y][t], -math.log(self.cons[y].get(t, worst))]
                 + ([strengths[y].get(t, 0.0)] if strengths else []) for t in teams]
            data[y] = (np.array(X), np.array([em[y + 1][t] for t in teams]))
        err = []
        for y in TEST:
            train = [data[k] for k in data if k <= y - 1]
            Xtr = np.vstack([a for a, _ in train])
            ytr = np.concatenate([b for _, b in train])
            beta = np.linalg.lstsq(Xtr, ytr, rcond=None)[0]
            Xte, yte = data[y]
            err.append((yte - Xte @ beta) ** 2)
        return float(np.sqrt(np.mean(np.concatenate(err))))

    def current_model(self, y: int) -> dict[str, float]:
        d = self.d
        s = defaultdict(float)
        for t in S.run(d, y, S.CURRENT).teams:
            if t.commits_count > 0 and d.bart(t.name):
                s[d.bart(t.name)] += t.total_score
        return s

    def consensus_strength(self, y: int) -> dict[str, float]:
        worst = max(self.cons[y].values(), default=0) + 1
        return {t: -math.log(rk) for t, rk in self.cons[y].items()} | {"__worst__": -math.log(worst)}


def mean(xs):
    xs = [x for x in xs if not math.isnan(x)]
    return float(np.mean(xs)) if xs else math.nan


def player_partials(st: Study, cfg: dict):
    """Recruit-level: OQ (and the combined value) vs player outcomes, and partial rho
    beyond the industry rating, test classes (draft: classes 2019-2021)."""
    d = st.d
    out = {}
    for key, years in (("fr_pts", TEST), ("fr_min_pct", TEST), ("fr_bpm", TEST), ("draft_pick", [2019, 2020, 2021])):
        oq_raw, oq_part = [], []
        for y in years:
            oq = st.offer_quality(y, cfg["seed"], cfg["agg"], cfg["fill"])
            rs = [d.linked[u] for u in oq if u in d.linked]
            rs = [r for r in rs if not math.isnan(r["out"][key]) and not math.isnan(r["industry_rating"])]
            if len(rs) < 20:
                continue
            x = np.array([oq[r["url"]] for r in rs])
            z = np.array([r["industry_rating"] for r in rs])
            t = np.array([r["out"][key] for r in rs]) * (-1 if key == "draft_pick" else 1)
            oq_raw.append(R._spearman(x, t))
            oq_part.append(R._partial(x, t, z))
        out[key] = (mean(oq_raw), mean(oq_part))
    return out


def main() -> None:
    st = Study()
    grid = [dict(seed=s, agg=a, fill=f, w=w, decay=dc, k=k)
            for s, a, f, w, dc, k in itertools.product(SEEDS, AGGS, FILLS, WEIGHTS, DECAYS, STEEP)]
    dev_score = {}
    for cfg in grid:
        dev_score[tuple(cfg.values())] = mean([st.team_eval(y, st.class_strength(y, cfg))[1] for y in DEV])

    def best_where(pred):
        ks = [k for k in dev_score if pred(dict(zip(grid[0].keys(), k)))]
        k = max(ks, key=dev_score.get)
        return dict(zip(grid[0].keys(), k))

    picks = {
        "offer quality only (rivals' strength)": best_where(lambda c: math.isinf(c["w"])),
        "industry rating only (same construction)": best_where(lambda c: c["w"] == 0.0),
        "rating + offer quality (best mix)": best_where(lambda c: not math.isinf(c["w"]) and c["w"] > 0),
    }

    def test_row(strength_fn):
        st_ = {y: strength_fn(y) for y in DEV + TEST}
        rho = mean([st.team_eval(y, st_[y])[0] for y in TEST])
        res = mean([st.team_eval(y, st_[y])[1] for y in TEST])
        res_all = mean([st.team_eval(y, st_[y], only_committed=False)[1] for y in TEST])
        return rho, (res, res_all), st_

    base_rmse = st.walk_forward_rmse(None)
    rows = []
    for name, cfg in picks.items():
        rho, res, strengths = test_row(lambda y, c=cfg: st.class_strength(y, c))
        rows.append((name, cfg, rho, res, st.walk_forward_rmse(strengths) - base_rmse))
    rho, res, strengths = test_row(st.current_model)
    rows.append(("current offer model (v0.6.0 defaults)", None, rho, res, st.walk_forward_rmse(strengths) - base_rmse))

    def cons_rho_y(y):
        teams = [t for t in st.rows(y) if t in st.committed(y)]
        return float(spearmanr([-st.cons[y].get(t, 10_000) for t in teams],
                               [st.d.em[y + 1][t] for t in teams]).statistic)
    cons_rho = mean([cons_rho_y(y) for y in TEST])

    L = ["# MBB: offer quality from rivals' on-court strength, and ratings + offers", "",
         "_Generated by `research_mbb_offerq.py` — do not edit by hand._", "",
         "A recruit's **offer quality** is how strong (barttorvik adj. EM, seasons before his "
         "junior-year offers) the schools he turned down were — the committed school's own "
         "strength is never used. Recruit value = percentile(industry rating) + w × "
         "percentile(offer quality); class strength = decayed sum over commits.", "",
         f"{len(grid)} settings chosen on development classes {DEV[0]}-{DEV[-1]} by the mean "
         "residual ρ (what the class adds beyond prior-season adj. EM and the consensus rank). "
         f"Test classes {TEST[0]}-{TEST[-1]} ({len(TEST)} independent class years, all D-I "
         "teams) played no part in any choice.", "",
         "## Team level (test classes)", "",
         "ρ columns: programs with ≥1 ranked commit; ‘all D-I’ includes programs with none (0). "
         "ΔRMSE: walk-forward prior + consensus + this vs prior + consensus, all D-I teams.", "",
         "| class strength | chosen setting | ρ next-season adj. EM | residual ρ beyond prior + consensus | residual ρ, all D-I | ΔRMSE |",
         "|---|---|---:|---:|---:|---:|"]
    for name, cfg, rho, (res, res_all), d_rmse in rows:
        c = "—" if cfg is None else ", ".join(f"{k}={v}" for k, v in cfg.items())
        L.append(f"| {name} | {c} | {rho:.3f} | {res:+.3f} | {res_all:+.3f} | {d_rmse:+.3f} |")
    L += [f"| On3 consensus rank (reference) | — | {cons_rho:.3f} | (in the baseline) | — | — |", "",
          f"Baseline (prior-season adj. EM + ln consensus rank, walk-forward) RMSE: "
          f"{base_rmse:.2f} adj. EM points. Negative ΔRMSE = the class strength improves it.", ""]

    # sensitivity: best dev residual per aggregator and per weight
    by = defaultdict(float)
    for k, v in dev_score.items():
        c = dict(zip(grid[0].keys(), k))
        by[("agg", c["agg"])] = max(by[("agg", c["agg"])], v)
        by[("w", c["w"])] = max(by[("w", c["w"])], v)
        by[("seed", c["seed"])] = max(by[("seed", c["seed"])], v)
        by[("k", c["k"])] = max(by[("k", c["k"])], v)
    L += ["Best development residual ρ by aggregator: " +
          ", ".join(f"{a} {by[('agg', a)]:+.3f}" for a in AGGS) + ".",
          "By weight on offer quality: " +
          ", ".join(f"w={w} {by[('w', w)]:+.3f}" for w in WEIGHTS) + ".",
          "By seed: " + ", ".join(f"{s} {by[('seed', s)]:+.3f}" for s in SEEDS) + ".",
          "By steepness k: " + ", ".join(f"k={k} {by[('k', k)]:+.3f}" for k in STEEP) + ".", ""]

    oq_cfg = picks["offer quality only (rivals' strength)"]
    pp = player_partials(st, oq_cfg)
    L += ["## Recruit level (test classes)", "",
          f"Offer quality ({oq_cfg['seed']}, {oq_cfg['agg']}, fill={oq_cfg['fill']}) vs player "
          "outcomes among recruits linked to barttorvik; partial = after controlling for the "
          "industry rating.", "",
          "| outcome | ρ | partial ρ beyond industry rating |", "|---|---:|---:|"]
    for key, label in (("fr_pts", "freshman pts/g"), ("fr_min_pct", "freshman Min%"),
                       ("fr_bpm", "freshman BPM"), ("draft_pick", "NBA draft (classes 2019-21)")):
        L.append(f"| {label} | {pp[key][0]:+.3f} | {pp[key][1]:+.3f} |")
    L += ["", "## Caveats", "",
          "- Offer lists are On3's as listed today (some hindsight) and are incomplete; recruits "
          "listing no other school are filled as described.",
          "- With 6 test years, residual-ρ differences under ~0.02 are noise.",
          "- Freshman BPM partly measures the team; points/minutes/draft are more player-driven.",
          ""]
    (MODEL_DIR / "RESEARCH_MBB_OFFERQ.md").write_text("\n".join(L))
    print("wrote RESEARCH_MBB_OFFERQ.md")


if __name__ == "__main__":
    main()
