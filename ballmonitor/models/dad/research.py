"""Study: does first-half DAD per game predict a team's second half better than
first-half win% or raw point differential?

    python -m ballmonitor.models.dad.research      # writes RESEARCH.md + data/research.json

Needs `ballmonitor fetch dad` first (data/games_<league>.csv). Every number in RESEARCH.md
is produced by this file; never edit RESEARCH.md by hand.

Design (walk-forward; nothing from the second half is used to build a predictor):
- Each league-season's regular season is split at the date of its median game. "First
  half" = games before that date, "second half" = games on or after it.
- Opponent ratings for DAD (and the adjusted-margin benchmark) are least-squares margin
  ratings (ratings.py) fitted on first-half games only, i.e. known at the split date.
- Predictors, all from the first half: win% (draw = 1/2), raw margin per game, adjusted
  margin (the team's own first-half rating), DAD per game and WAD per game from the
  shipped model (`DadModel.predict`), under several configurations.
- Targets, second half: win%, margin per game, and schedule-adjusted margin per game
  (margin + opponent's first-half rating - home edge; the second-half schedule is often
  much harder or easier, e.g. college conference play).
- Each predictor is mapped to the target by OLS y = a + b*x fitted on all EARLIER
  seasons of the same league, then scored on the season. Seasons <= DEV_LAST are the
  development period: margin SDs / home edges are estimated there and the per-game cap
  is chosen there. Seasons > DEV_LAST are the test period reported as headline numbers.
- Uncertainty: 95% intervals from a bootstrap over league-seasons (teams in the same
  league-season share games, so they are not independent).
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from ballmonitor.core import registry
from ballmonitor.models.dad.ratings import Game, fit_ratings, read_games, team_games

MODEL_DIR = Path(__file__).resolve().parent
DATA = MODEL_DIR / "data"
DEV_LAST = 2020
RIDGE = 1.0          # phantom 0-margin games per team in first-half ratings (fixed a priori)
BOOT = 1000
SEED = 7
LEAGUES = {  # league -> (model sport, label, min games per half, margin unit)
    "mbb": ("basketball", "NCAA men's basketball (D-I)", 8, "pts"),
    "wbb": ("wbb", "NCAA women's basketball (D-I)", 8, "pts"),
    "nba": ("basketball", "NBA", 25, "pts"),
    "cfb": ("football", "College football (FBS)", 4, "pts"),
    "nfl": ("football", "NFL", 6, "pts"),
    "mlb": ("mlb", "MLB", 50, "runs"),
    "epl": ("soccer", "Premier League", 12, "goals"),
    "laliga": ("soccer", "La Liga", 12, "goals"),
    "bundesliga": ("soccer", "Bundesliga", 12, "goals"),
    "seriea": ("soccer", "Serie A", 12, "goals"),
    "ligue1": ("soccer", "Ligue 1", 12, "goals"),
}
SOCCER = ["epl", "laliga", "bundesliga", "seriea", "ligue1"]
LOG: list[str] = []
# v0.5.0 defaults of the constants the study re-estimates (kept here so the "before"
# column stays reproducible after config.toml changes).
V05 = {"basketball_margin_sd": 11.0, "home_advantage_basketball": 3.2, "wbb_margin_sd": 12.5,
       "home_advantage_wbb": 3.0, "football_margin_sd": 13.8, "home_advantage_football": 2.5,
       "home_advantage_baseball": 0.30, "home_advantage_soccer": 0.35,
       "mlb_total_runs": 8.8, "soccer_total_goals": 2.70}
NO_CAP = 100.0
# Since v0.7.0 the model defaults to the margin scale; this study is about the
# v0.6.0 probit DAD, so every model load here pins the legacy scale.
LEGACY = {"dad_scale": "probit", "wad_mode": "strength"}


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    LOG.append(line)
    print(line, flush=True)


# ── data ──────────────────────────────────────────────────────────────────────

def league_seasons() -> dict[tuple[str, int], list[Game]]:
    out = {}
    for lg in LEAGUES:
        f = DATA / f"games_{lg}.csv"
        if not f.exists():
            log(f"missing {f.name}; run `ballmonitor fetch dad`")
            continue
        by = defaultdict(list)
        for g in read_games(f):
            if g.season_type == 2:
                by[g.season].append(g)
        for s, gs in by.items():
            out[(lg, s)] = sorted(gs, key=lambda g: g.date)
    return out


def split(games: list[Game]) -> tuple[list[Game], list[Game], str]:
    cut = games[len(games) // 2].date
    return [g for g in games if g.date < cut], [g for g in games if g.date >= cut], cut


def record(rows) -> tuple[float, float]:
    """(win% with draws = 1/2, margin per game) from team_games rows."""
    w = sum(1.0 if m > 0 else 0.5 if m == 0 else 0.0 for _, _, m, _ in rows)
    return w / len(rows), sum(m for _, _, m, _ in rows) / len(rows)


# ── data-estimated sport constants (development seasons only) ───────────────

def estimate_constants(ls: dict) -> dict[str, dict]:
    """Per league: residual margin SD and home edge from full-season fits, dev seasons."""
    out = {}
    for lg in LEAGUES:
        fits = [fit_ratings(gs) for (l, s), gs in ls.items() if l == lg and s <= DEV_LAST]
        if not fits:
            continue
        n = sum(f.games for f in fits)
        out[lg] = {
            "seasons": len(fits),
            "games": n,
            "residual_sd": math.sqrt(sum(f.residual_sd ** 2 * f.games for f in fits) / n),
            "home_advantage": sum(f.home_advantage * f.games for f in fits) / n,
            "total": statistics.fmean(g.home_score + g.away_score for (l, s), gs in ls.items()
                                      if l == lg and s <= DEV_LAST for g in gs),
        }
    return out


def pooled(consts: dict, leagues: list[str], key: str) -> float:
    rows = [consts[lg] for lg in leagues if lg in consts]
    return sum(r[key] * r["games"] for r in rows) / sum(r["games"] for r in rows)


def data_overrides(consts: dict) -> dict:
    """Config overrides with sport constants estimated on development seasons.

    The model has one SD/home edge per sport, so leagues sharing a sport are pooled
    by games (basketball = NCAA men's only: the presets are college; NBA is reported).
    """
    o = {}
    if "mbb" in consts:
        o["basketball_margin_sd"] = round(consts["mbb"]["residual_sd"], 1)
        o["home_advantage_basketball"] = round(consts["mbb"]["home_advantage"], 1)
    if "wbb" in consts:
        o["wbb_margin_sd"] = round(consts["wbb"]["residual_sd"], 1)
        o["home_advantage_wbb"] = round(consts["wbb"]["home_advantage"], 1)
    if "cfb" in consts or "nfl" in consts:
        o["football_margin_sd"] = round(pooled(consts, ["cfb", "nfl"], "residual_sd"), 1)
        o["home_advantage_football"] = round(pooled(consts, ["cfb", "nfl"], "home_advantage"), 1)
    if "mlb" in consts:
        o["home_advantage_baseball"] = round(consts["mlb"]["home_advantage"], 2)
        o["mlb_total_runs"] = round(consts["mlb"]["total"], 1)
    soc = [lg for lg in SOCCER if lg in consts]
    if soc:
        o["home_advantage_soccer"] = round(pooled(consts, soc, "home_advantage"), 2)
        o["soccer_total_goals"] = round(pooled(consts, soc, "total"), 2)
    return o


# ── data-implied baseline presets ──────────────────────────────────────────────

# league group -> (leagues, {preset: rank}) ; rank 1 = best full-season rating.
PRESET_RANKS = {
    "mbb": (["mbb"], {"champion": 2, "top_4_seed": 16, "bubble": 45, "replacement": 300}),
    "wbb": (["wbb"], {"champion": 2, "top_4_seed": 16, "bubble": 45, "replacement": 300}),
    "cfb": (["cfb"], {"champion": 2, "top_4_seed": 4, "bubble": 12, "replacement": 120}),
    "mlb": (["mlb"], {"champion": 2, "top_4_seed": 6, "bubble": 12, "replacement": 30}),
    "soccer": (SOCCER, {"champion": 1, "top_4_seed": 4, "europa": 6, "bubble": 17,
                        "replacement": 20}),
}


def preset_table(ls: dict) -> dict:
    """Median (over league-seasons) full-season rating of the team at each preset's rank.

    Descriptive definitions of the presets on the same scale as data/team_ratings.csv;
    all seasons are used (a preset is a definition, not a forecast).
    """
    out = {}
    for group, (leagues, ranks) in PRESET_RANKS.items():
        vals = defaultdict(list)
        for (lg, s), gs in ls.items():
            if lg not in leagues:
                continue
            r = sorted(fit_ratings(gs).ratings.values(), reverse=True)
            for name, k in ranks.items():
                if k <= len(r):
                    vals[name].append(r[k - 1])
        out[group] = {name: {"rank": ranks[name], "median": statistics.median(v), "n": len(v)}
                      for name, v in vals.items()}
    return out


# ── team-season table ─────────────────────────────────────────────────────────

def build_cases(ls: dict) -> list[dict]:
    cases = []
    for (lg, season), games in sorted(ls.items()):
        sport, _, min_games, _ = LEAGUES[lg]
        first, second, cut = split(games)
        fit = fit_ratings(first, ridge=RIDGE)
        r, h = fit.ratings, fit.home_advantage
        for team in sorted(r):
            g1, g2 = team_games(first, team), team_games(second, team)
            if len(g1) < min_games or len(g2) < min_games or any(o not in r for _, o, _, _ in g2):
                continue
            w1, m1 = record(g1)
            w2, m2 = record(g2)
            loc_sign = {"home": 1.0, "away": -1.0, "neutral": 0.0}
            adj2 = statistics.fmean(m + r[o] - h * loc_sign[loc] for _, o, m, loc in g2)
            cases.append({
                "league": lg, "season": season, "team": team, "split": cut,
                "n1": len(g1), "n2": len(g2),
                "inputs": {"team": team, "sport": sport, "games": [
                    {"opponent": o, "opponent_rating": r[o], "margin": m, "location": loc}
                    for _, o, m, loc in g1]},
                "x": {"win_pct": w1, "margin_pg": m1, "adj_margin": r[team]},
                "y": {"win_pct": w2, "margin_pg": m2, "adj_margin": adj2},
            })
    return cases


def add_dad(cases: list[dict], name: str, overrides: dict, baseline: str = "average") -> None:
    model = registry.load_model("dad", overrides={**LEGACY, **overrides})
    t = time.time()
    for c in cases:
        res = model.predict({**c["inputs"], "baseline": baseline}).extras
        c["x"][f"dad:{name}"] = res["dad_per_game"]
        c["x"][f"wad:{name}"] = res["total_wad"] / res["games_count"]
    log(f"  DAD config {name!r} ({baseline}) over {len(cases)} team-seasons in {time.time() - t:.0f}s")


# ── evaluation ────────────────────────────────────────────────────────────────

def ols(xs: list[float], ys: list[float]) -> tuple[float, float]:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx > 0 else 0.0
    return my - b * mx, b


def walk_forward(cases: list[dict], predictor: str, target: str) -> dict[tuple, list[float]]:
    """Squared errors per (league, season) for seasons that have at least one earlier season."""
    by = defaultdict(list)
    for c in cases:
        by[(c["league"], c["season"])].append(c)
    out = {}
    for (lg, s), group in by.items():
        train = [c for c in cases if c["league"] == lg and c["season"] < s]
        if not train:
            continue
        a, b = ols([c["x"][predictor] for c in train], [c["y"][target] for c in train])
        out[(lg, s)] = [(a + b * c["x"][predictor] - c["y"][target]) ** 2 for c in group]
    return out


def rmse(errs: dict, keys) -> float:
    sq = [e for k in keys for e in errs.get(k, [])]
    return math.sqrt(sum(sq) / len(sq)) if sq else math.nan


def corr(cases, predictor, target) -> float:
    xs = [c["x"][predictor] for c in cases]
    ys = [c["y"][target] for c in cases]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else math.nan


def boot_ratio(errs_a: dict, errs_b: dict, keys: list, leagues_norm: bool) -> tuple[float, float, float]:
    """RMSE(a)/RMSE(b) and a 95% cluster-bootstrap interval over league-seasons.

    With leagues_norm, each league-season's squared errors are divided by that league's
    benchmark MSE so that leagues on different scales (points, runs, goals) pool fairly.
    """
    norm = {}
    if leagues_norm:
        for lg in {k[0] for k in keys}:
            ks = [k for k in keys if k[0] == lg]
            norm[lg] = rmse(errs_b, ks) ** 2
    def stat(ks):
        sa = sum(sum(errs_a[k]) / norm.get(k[0], 1.0) for k in ks)
        sb = sum(sum(errs_b[k]) / norm.get(k[0], 1.0) for k in ks)
        return math.sqrt(sa / sb) if sb > 0 else math.nan
    rng = random.Random(SEED)
    draws = sorted(stat([rng.choice(keys) for _ in keys]) for _ in range(BOOT))
    return stat(keys), draws[int(0.025 * BOOT)], draws[int(0.975 * BOOT) - 1]


# ── report ────────────────────────────────────────────────────────────────────

def fmt(x: float, d: int = 3) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def main() -> int:
    t0 = time.time()
    ls = league_seasons()
    if not ls:
        return 1
    log(f"{len(ls)} league-seasons loaded")
    consts = estimate_constants(ls)
    over = data_overrides(consts)
    log(f"data-estimated constants (dev seasons): {over}")
    presets = preset_table(ls)
    log(f"data-implied presets: {presets}")
    cases = build_cases(ls)
    log(f"{len(cases)} team-seasons with enough games in both halves")

    shipped = registry.load_model("dad", overrides=LEGACY).params
    configs = {  # name -> (overrides, baseline, description)
        "v0.5": ({"game_dad_cap": NO_CAP, **V05},
                 "average", "v0.5.0 defaults (no per-game cap), average baseline"),
        "data_sd": ({"game_dad_cap": NO_CAP, **over}, "average",
                    "SD / home edge estimated from dev seasons, no cap"),
    }
    caps = [0.5, 1.0, 1.5, 2.0, 3.0]
    for c in caps:
        configs[f"data_sd_cap{c:g}"] = ({"game_dad_cap": c, **over}, "average",
                                        f"data SD + per-game cap ±{c:g}σ")
    wide = {**over, **{k: round(over[k] * 1.5, 1) for k in
                       ("basketball_margin_sd", "wbb_margin_sd", "football_margin_sd") if k in over}}
    configs["data_sd_x1.5"] = ({"game_dad_cap": NO_CAP, **wide}, "average",
                               "margin SDs 1.5x data (less blowout compression), no cap")
    for b in ("bubble", "champion", "replacement"):
        configs[f"v0.5_{b}"] = ({"game_dad_cap": NO_CAP, **V05},
                                b, f"v0.5.0 constants, no cap, {b} baseline (v0.6.0 presets)")
    for name, (o, b, _) in configs.items():
        add_dad(cases, name, o, b)

    dev_keys = sorted({(c["league"], c["season"]) for c in cases if c["season"] <= DEV_LAST})
    test_keys = sorted({(c["league"], c["season"]) for c in cases if c["season"] > DEV_LAST})
    targets = ["win_pct", "margin_pg", "adj_margin"]
    predictors = ["win_pct", "margin_pg", "adj_margin"] + [f"dad:{n}" for n in configs] + \
                 [f"wad:{n}" for n in ("v0.5", "data_sd")]
    errs = {(p, t): walk_forward(cases, p, t) for p in predictors for t in targets}

    # Choose the cap on development seasons (walk-forward within dev), by pooled
    # normalised RMSE across the three targets.
    def dev_score(name):
        tot = 0.0
        for t in targets:
            r, _, _ = boot_ratio(errs[(f"dad:{name}", t)], errs[("margin_pg", t)],
                                 [k for k in dev_keys if k in errs[("margin_pg", t)]], True)
            tot += r
        return tot / len(targets)
    cap_names = ["data_sd"] + [f"data_sd_cap{c:g}" for c in caps]
    dev_scores = {n: dev_score(n) for n in cap_names}
    chosen = min(dev_scores, key=dev_scores.get)
    log(f"dev-period choice: {chosen} ({dev_scores})")
    for b in ("champion", "replacement"):
        o = dict(configs[chosen][0])
        configs[f"chosen_{b}"] = (o, b, f"{configs[chosen][2]}, {b} baseline")
        add_dad(cases, f"chosen_{b}", o, b)
        for t in targets:
            errs[(f"dad:chosen_{b}", t)] = walk_forward(cases, f"dad:chosen_{b}", t)
    # Size of the largest single-game contribution (shows the explosion the cap removes).
    extremes = {}
    for name in ("v0.5", "v0.5_replacement", chosen, "chosen_replacement"):
        o, b, _ = configs[name]
        m = registry.load_model("dad", overrides={**LEGACY, **o})
        worst = 0.0
        for c in cases:
            if c["league"] == "mbb" and c["season"] > DEV_LAST:
                recs = m.predict({**c["inputs"], "baseline": b}).extras["game_records"]
                worst = max(worst, max(abs(g["dad"]) for g in recs))
        extremes[configs[name][2]] = worst

    n_test = sum(1 for c in cases if c["season"] > DEV_LAST)
    n_dev = sum(1 for c in cases if c["season"] <= DEV_LAST)
    results = {"consts": consts, "overrides": over, "chosen": chosen, "dev_scores": dev_scores,
               "n_cases": len(cases), "n_test": n_test, "n_dev": n_dev,
               "league_seasons_test": len(test_keys), "extremes": extremes, "presets": presets}
    write_report(cases, configs, errs, test_keys, dev_keys, results, shipped, time.time() - t0)
    (DATA / "research.json").write_text(json.dumps(results, indent=1, default=str))
    log("wrote RESEARCH.md and data/research.json")
    return 0


def write_report(cases, configs, errs, test_keys, dev_keys, res, shipped, secs) -> None:
    L = []
    w = L.append
    chosen = res["chosen"]
    test_cases = [c for c in cases if c["season"] > DEV_LAST]
    w("# DAD — does first-half DAD predict the second half?")
    w("")
    w("_Generated by `python -m ballmonitor.models.dad.research`. Do not edit by hand._")
    w("")
    w("## Claim tested")
    w("")
    w("Summed over a schedule, DAD is meant to measure how well a team played given who it")
    w("played and where. If that is true, a team's first-half **DAD per game** should")
    w("predict its second half better than its first-half **win%** or **raw point")
    w("differential**. The strongest simple benchmark is the team's first-half")
    w("**adjusted margin** (least-squares margin rating, the same ratings DAD uses for")
    w("opponents), so it is reported too.")
    w("")
    w("## Data and design")
    w("")
    per_league = defaultdict(lambda: [0, 0, set()])
    for c in cases:
        k = per_league[c["league"]]
        k[0 if c["season"] <= DEV_LAST else 1] += 1
        k[2].add(c["season"])
    w("| league | seasons | dev team-seasons | test team-seasons |")
    w("|---|---|---:|---:|")
    for lg, (label) in ((lg, LEAGUES[lg][1]) for lg in LEAGUES):
        if lg in per_league:
            d, t, ss = per_league[lg]
            w(f"| {label} | {min(ss)}–{max(ss)} ({len(ss)}) | {d} | {t} |")
    w(f"| **total** | | **{res['n_dev']}** | **{res['n_test']}** |")
    w("")
    w("Season = the year a basketball/soccer season ends, or a football/MLB season starts.")
    w("Skipped: NBA 2020–21, FBS 2020, MLB 2020 (COVID schedules). Results: ESPN")
    w("scoreboards (US leagues) and football-data.co.uk (soccer), regular season only.")
    w("")
    w("* Split: each league-season at the date of its median regular-season game.")
    w("  First-half opponent ratings use only first-half games (ridge = "
      f"{RIDGE:g} phantom 0-margin game per team, fixed before looking at results).")
    w(f"* Development seasons: <= {DEV_LAST}. Test seasons: > {DEV_LAST} "
      f"({res['league_seasons_test']} league-seasons, **{res['n_test']} team-seasons**).")
    w("  Each predictor is mapped to the target by OLS fitted on all earlier seasons of")
    w("  the same league (walk-forward), so nothing from the scored season is used.")
    w("* Team-seasons in one league-season share games and are not independent; the")
    w("  intervals below bootstrap whole league-seasons.")
    w("* Targets: second-half win% (draw = 1/2), margin per game, and schedule-adjusted")
    w("  margin per game (margin + opponent's first-half rating − home edge).")
    w("")
    w("## Sport constants estimated from data (development seasons)")
    w("")
    w("Residual SD = per-game margin noise around full-season least-squares ratings")
    w("(sqrt(SSR / (games − teams − 1))); home edge from the same fit.")
    w("")
    w("| league | seasons | games | residual SD | home edge | total per game |")
    w("|---|---:|---:|---:|---:|---:|")
    for lg, cst in res["consts"].items():
        w(f"| {LEAGUES[lg][1]} | {cst['seasons']} | {cst['games']} | "
          f"{cst['residual_sd']:.2f} | {cst['home_advantage']:+.2f} | {cst['total']:.2f} |")
    w("")
    w("MLB caveat: a home team leading after 8½ innings does not bat, so recorded home")
    w("margins (and this home edge) are smaller than the home team's true scoring edge.")
    w("DAD scores recorded margins, so the recorded-margin estimate is the consistent one.")
    w("")
    w("Config values implied (sports sharing a param are pooled by games; basketball uses")
    w("NCAA men's only because its presets are college presets):")
    w("")
    w("| param | v0.5.0 | data |")
    w("|---|---:|---:|")
    for k, v in res["overrides"].items():
        w(f"| `{k}` | {V05[k]:g} | {v:g} |")
    w("")
    w("## Baseline presets implied by the data")
    w("")
    w("Median over all league-seasons of the full-season rating of the team at the")
    w("preset's rank (same scale as data/team_ratings.csv). Soccer pools five leagues.")
    w("")
    w("| group | preset | rank | median rating | league-seasons |")
    w("|---|---|---:|---:|---:|")
    for grp, d in res["presets"].items():
        for name, v in d.items():
            w(f"| {grp} | {name} | {v['rank']} | {v['median']:+.2f} | {v['n']} |")
    w("")
    w("## How big can one game get?")
    w("")
    w("Largest single-game |DAD| in the NCAA men's test seasons (first halves):")
    w("")
    w("| configuration | max per-game |DAD| |")
    w("|---|---:|")
    for k, v in res["extremes"].items():
        w(f"| {k} | {v:.2f}σ |")
    w("")
    w("## Choosing the per-game cap (development seasons only)")
    w("")
    w("Score = mean over the three targets of RMSE(DAD) / RMSE(raw margin), pooled over")
    w("leagues after normalising each league by its raw-margin MSE (lower is better).")
    w("")
    w("| configuration | dev score |")
    w("|---|---:|")
    for n, sc in res["dev_scores"].items():
        w(f"| {configs[n][2]} | {sc:.4f}{' ← chosen' if n == chosen else ''} |")
    w("")

    def table(target: str, title: str) -> None:
        w(f"## Test seasons: second-half {title}")
        w("")
        w("Out-of-sample RMSE (walk-forward OLS). Lower is better. Last column pools all")
        w("leagues: RMSE relative to raw margin per game, with a 95% league-season bootstrap.")
        w("")
        lgs = [lg for lg in LEAGUES if any(k[0] == lg for k in test_keys)]
        w("| first-half predictor | " + " | ".join(lg for lg in lgs) + " | pooled vs raw margin |")
        w("|---|" + "---:|" * len(lgs) + "---:|")
        rows = [("win%", "win_pct"), ("raw margin / game", "margin_pg"),
                ("adjusted margin (rating)", "adj_margin"),
                ("DAD/game v0.5.0", "dad:v0.5"), ("WAD/game v0.5.0", "wad:v0.5"),
                ("DAD/game data SD, no cap", "dad:data_sd"),
                (f"DAD/game {configs[chosen][2]}", f"dad:{chosen}"),
                ("DAD/game v0.5.0 consts, bubble baseline*", "dad:v0.5_bubble"),
                ("DAD/game v0.5.0 consts, champion baseline*", "dad:v0.5_champion"),
                ("DAD/game v0.5.0 consts, replacement baseline*", "dad:v0.5_replacement"),
                ("DAD/game chosen cap, champion baseline", "dad:chosen_champion"),
                ("DAD/game chosen cap, replacement baseline", "dad:chosen_replacement"),
                ("DAD/game SDs x1.5, no cap", "dad:data_sd_x1.5")]
        seen = set()
        for label, p in rows:
            if p in seen:
                continue
            seen.add(p)
            e = errs[(p, target)]
            cells = [fmt(rmse(e, [k for k in test_keys if k[0] == lg])) for lg in lgs]
            r, lo, hi = boot_ratio(e, errs[("margin_pg", target)], test_keys, True)
            w(f"| {label} | " + " | ".join(cells) + f" | {r:.3f} [{lo:.3f}, {hi:.3f}] |")
        w("")
        w("\\* Non-average baselines use the v0.6.0 preset ratings.")
        w("")
        w("Correlation with the target (test seasons, all leagues pooled within league, "
          "mean over leagues):")
        w("")
        cs = {}
        for label, p in rows[:4] + [(f"DAD {chosen}", f"dad:{chosen}")]:
            vals = [corr([c for c in test_cases if c["league"] == lg], p, target) for lg in lgs]
            cs[label] = statistics.fmean(vals)
        w(", ".join(f"{k}: {v:.3f}" for k, v in cs.items()) + ".")
        w("")

    table("win_pct", "win%")
    table("margin_pg", "margin per game")
    table("adj_margin", "schedule-adjusted margin per game")

    # Headline numbers for the summary
    def ratio(p, q, t):
        return boot_ratio(errs[(p, t)], errs[(q, t)], test_keys, True)
    w("## Summary")
    w("")
    for t, title in (("win_pct", "win%"), ("margin_pg", "margin"), ("adj_margin", "adjusted margin")):
        a = ratio(f"dad:{chosen}", "win_pct", t)
        b = ratio(f"dad:{chosen}", "margin_pg", t)
        c = ratio(f"dad:{chosen}", "adj_margin", t)
        d = ratio(f"dad:{chosen}", "dad:v0.5", t)
        w(f"* Second-half {title}: DAD ({chosen}) RMSE is {a[0]:.3f}× win% "
          f"[{a[1]:.3f}, {a[2]:.3f}], {b[0]:.3f}× raw margin [{b[1]:.3f}, {b[2]:.3f}], "
          f"{c[0]:.3f}× adjusted margin [{c[1]:.3f}, {c[2]:.3f}], and {d[0]:.3f}× "
          f"v0.5.0 DAD [{d[1]:.3f}, {d[2]:.3f}].")
    w("")
    w("Ratios below 1 mean DAD is better. Intervals that exclude 1 are distinguishable from")
    w("noise at the league-season level.")
    w("")
    w("## Caveats")
    w("")
    w("* In-sample choices: the per-game cap and the SD/home-edge values were chosen on the")
    w(f"  development seasons (<= {DEV_LAST}) only; the list of configurations and the")
    w("  candidate caps were picked by the author before running the study. The ridge")
    w("  value and the median-date split were fixed a priori.")
    w("* All predictors use the same first-half games; the adjusted-margin benchmark uses")
    w("  the same opponent ratings as DAD, so DAD vs adjusted margin isolates DAD's")
    w("  nonlinear margin transform and probit standardisation.")
    w("* Season splits differ by sport: college first halves are mostly non-conference")
    w("  games, so raw second-half targets are partly about schedule strength.")
    w("* College baseball and softball are not tested (no complete public game data).")
    w("* The OLS map is fitted per league; DAD's absolute level depends on the baseline")
    w("  (the average baseline is used here; others shown for comparison).")
    w("")
    w(f"_Runtime {secs:.0f}s._")
    (MODEL_DIR / "RESEARCH.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
