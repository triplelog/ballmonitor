"""Study: do other ways of scoring a recruit or adding up a class rank football programs
better than the default?  Writes RESEARCH_VARIANTS.md (never hand-edit it).

    python -m ballmonitor.models.ncaaf_recruiting.research_variants

Same data, target, metric and walk-forward rule as research.py (which studied rank_decay,
quality_power, l2_reg and prestige_years; they are not repeated here): Spearman rank
correlation within a class year between the class score and the program's mean SRS over
seasons Y..Y+3, classes 2012-2022; for test class Y a setting is chosen on classes
<= Y-4 only. Program strengths (the Plackett-Luce fit) are the default ones in every
variant; only the recruit score or the class sum changes, one idea at a time.

The ideas are scored here, in this file, and are NOT options of the model: none of them
was adopted (see the report), so the engine was left alone.

Unit scores (v0.8.0): the offense / defense breakdown is checked separately against each
program's opponent-adjusted points scored and allowed over seasons Y..Y+3, for several
`unit_rank_decay` settings (1 = the undiscounted sums used before v0.8.0).
"""

from __future__ import annotations

import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

MODEL_DIR = Path(__file__).resolve().parent
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

import research as R  # noqa: E402
from src.elo_engine import _solve_plackett_luce_cached  # noqa: E402
from src.position_model import PositionalRankingEngine  # noqa: E402

DEFAULTS = R.DEFAULTS_V030  # rank_decay 0.95, quality_power 0.5, l2_reg 0.5 (the config defaults)
STAR_REFERENCE = 3.0  # star blend: score x (stars / 3) ^ star_power
LINE_POSITIONS = ("OL", "OT", "IOL", "DE", "DT", "DL", "EDGE")  # labels in the legacy and On3 files
# One idea per family; the first setting of each is the default behaviour.
FAMILIES = {
    "commit_weight": {
        "what": "also count the committed school's strength (x weight) in the recruit's score, so a "
                "recruit who lists no other school no longer scores 0",
        "values": [0.0, 0.25, 0.5, 1.0, 2.0]},
    "top_offers": {
        "what": "count only the recruit's strongest N other offers (drops courtesy offers from weak "
                "programs and the reward for a long list); 0 = all",
        "values": [0, 1, 3, 5, 8, 12]},
    "star_power": {
        "what": "multiply the recruit's score by (stars / 3) ^ power (blends the services' stars in)",
        "values": [0.0, 0.5, 1.0, 2.0, 3.0]},
    "qb_weight": {
        "what": "multiply quarterbacks' scores (position scarcity)",
        "values": [1.0, 0.5, 1.5, 2.0, 3.0]},
    "line_weight": {
        "what": "multiply offensive and defensive linemen's scores",
        "values": [1.0, 0.5, 0.75, 1.5, 2.0]},
    "top_commits": {
        "what": "count only the class's best N commits (class size beyond N ignored); 0 = all",
        "values": [0, 10, 15, 20, 25]},
    "average_blend": {
        "what": "class score = sum ^ (1 - w) x mean recruit score ^ w (w = 1 ranks by average "
                "quality, ignoring class size)",
        "values": [0.0, 0.25, 0.5, 0.75, 1.0]},
}
UNIT_DECAYS = [1.0, 0.98, 0.95, 0.9, 0.85]  # unit_rank_decay settings; 1 = undiscounted (pre-v0.8.0)
POINTS_RIDGE = 0.01  # offense/defense points rating: tiny ridge for identifiability
LOG: list[str] = []


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    LOG.append(line)
    print(line, flush=True)


def fit_class(year: int):
    """Default program strengths for one class: (valid recruits, team index, exp(gamma))."""
    rs = [r for r in R.recruits(year) if r.committed_team and r.committed_team != "0" and r.all_teams]
    teams = sorted({t for r in rs for t in r.all_teams})
    tid = {t: i for i, t in enumerate(teams)}
    multi = [r for r in rs if r.is_multi_offer]
    gamma = _solve_plackett_luce_cached(
        len(teams), tuple(tid[r.committed_team] for r in multi),
        tuple(tuple(tid[t] for t in r.all_teams) for r in multi), float(DEFAULTS["l2_reg"]), None)
    return rs, tid, np.exp(gamma)


def class_scores(fit, commit_weight=0.0, top_offers=0, star_power=0.0, qb_weight=1.0,
                 line_weight=1.0, top_commits=0, average_blend=0.0) -> dict[str, float]:
    rs, tid, strength = fit
    by_team: dict[str, list[float]] = defaultdict(list)
    for r in rs:
        lost = sorted((strength[tid[t]] for t in r.all_teams if t != r.committed_team), reverse=True)
        if top_offers:
            lost = lost[:top_offers]
        total = sum(lost) + commit_weight * strength[tid[r.committed_team]]
        q = total ** DEFAULTS["quality_power"] if total > 0 else 0.0
        if star_power:
            q *= (max(r.stars, 1) / STAR_REFERENCE) ** star_power
        if r.position == "QB":
            q *= qb_weight
        elif r.position in LINE_POSITIONS:
            q *= line_weight
        by_team[r.committed_team].append(q)
    out = {}
    for t, qs in by_team.items():
        qs.sort(reverse=True)
        if top_commits:
            qs = qs[:top_commits]
        total = sum(q * DEFAULTS["rank_decay"] ** i for i, q in enumerate(qs))
        if average_blend and total > 0:
            total = total ** (1 - average_blend) * float(np.mean(qs)) ** average_blend
        out[t] = total
    return out


def win_pct_targets(games: dict, teams_by_year: dict) -> dict[int, dict[str, float]]:
    """Share of games won over seasons Y..Y+3 (all games in the FBS scoreboard file)."""
    won: dict[int, Counter] = defaultdict(Counter)
    played: dict[int, Counter] = defaultdict(Counter)
    for season, gs in games.items():
        for home, away, hp, ap, _ in gs:
            played[season][home] += 1
            played[season][away] += 1
            won[season][home if hp > ap else away] += 1
    out = {}
    for y, teams in teams_by_year.items():
        seasons = range(y, y + R.WINDOW)
        out[y] = {t: sum(won[s][t] for s in seasons) / max(1, sum(played[s][t] for s in seasons)) for t in teams}
    return out


def points_ratings(games: list, fbs: set[str]) -> dict[str, tuple[float, float]]:
    """Least-squares points rating per season: points = mean + off[attacker] - def[defender]
    + home edge. Returns (offense, defense) per FBS team, both centred on the FBS mean and
    both "higher = better" (defense = points per game kept off the board vs average).
    Non-FBS opponents share one pooled 'FCS' offense and defense."""
    teams = sorted(fbs) + ["FCS"]
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    rows, y = [], []
    for home, away, hp, ap, neutral in games:
        h, a = idx.get(home, idx["FCS"]), idx.get(away, idx["FCS"])
        if h == a:
            continue
        for att, dfn, pts, side in ((h, a, hp, 1.0), (a, h, ap, -1.0)):
            x = np.zeros(2 * n + 2)
            x[att], x[n + dfn], x[-2], x[-1] = 1.0, -1.0, 1.0, 0.0 if neutral else side
            rows.append(x)
            y.append(pts)
    X, Y = np.array(rows), np.array(y, dtype=float)
    beta = np.linalg.solve(X.T @ X + POINTS_RIDGE * np.eye(X.shape[1]), X.T @ Y)
    off, dfn = beta[:n - 1], beta[n:2 * n - 1]
    return {t: (float(off[i] - off.mean()), float(dfn[i] - dfn.mean())) for t, i in idx.items() if t != "FCS"}


def unit_study(games: dict, years: list[int], tests: list[int], teams_by_year: dict) -> dict:
    """Spearman rho of the offense (defense) unit score with the program's mean offense
    (defense) points rating over seasons Y..Y+3, per unit_rank_decay setting; plus the
    overall class score as a reference and a balance check (log offense/defense unit score
    vs offense minus defense rating)."""
    fbs = R.fbs_sets(games)
    pr = {s: points_ratings(games[s], fbs[s]) for s in sorted(games)}
    results = {y: R.model_result(y, DEFAULTS) for y in years}
    tgt, teams_of = {}, {}
    for y in years:
        teams = [t for t in teams_by_year[y] if all(t in pr[s] for s in range(y, y + R.WINDOW))]
        teams_of[y] = teams
        tgt[y] = {k: {t: float(np.mean([pr[s][t][k] for s in range(y, y + R.WINDOW)])) for t in teams}
                  for k in (0, 1)}
    out = {"runs": {}, "n_rows": sum(len(teams_of[y]) for y in tests)}

    def spear(x, yv):
        return float(R.spearmanr(x, yv).statistic)

    for d in UNIT_DECAYS:
        off, dfn, bal = {}, {}, {}
        for y in years:
            u = {t.name: t for t in PositionalRankingEngine(rank_decay=d).evaluate(results[y]).teams}
            teams = teams_of[y]
            off[y] = spear([u[t].offense_score if t in u else -1.0 for t in teams], [tgt[y][0][t] for t in teams])
            dfn[y] = spear([u[t].defense_score if t in u else -1.0 for t in teams], [tgt[y][1][t] for t in teams])
            both = [t for t in teams if t in u and u[t].offense_score > 0 and u[t].defense_score > 0]
            bal[y] = spear([math.log(u[t].offense_score / u[t].defense_score) for t in both],
                           [tgt[y][0][t] - tgt[y][1][t] for t in both])
        out["runs"][d] = {"off": off, "def": dfn, "bal": bal,
                          "both": {y: (off[y] + dfn[y]) / 2 for y in years}}
    ref_off, ref_def = {}, {}
    for y in years:
        s = {t.name: t.total_score for t in results[y].teams if t.commits_count > 0}
        teams = teams_of[y]
        ref_off[y] = spear([s.get(t, -1.0) for t in teams], [tgt[y][0][t] for t in teams])
        ref_def[y] = spear([s.get(t, -1.0) for t in teams], [tgt[y][1][t] for t in teams])
    out["overall"] = {"off": ref_off, "def": ref_def}
    chosen, wf = {}, {}
    for y in tests:
        train = [t for t in years if t <= y - R.LAG]
        chosen[y] = max(UNIT_DECAYS, key=lambda d: R._m(out["runs"][d]["both"], train))
        wf[y] = out["runs"][chosen[y]]["both"][y]
    old = out["runs"][1.0]["both"]
    shared = out["runs"][DEFAULTS["rank_decay"]]["both"]
    out.update(chosen=chosen, wf=wf)
    for name, series in (("wf", wf), ("shared", shared)):
        diff = [series[y] - old[y] for y in tests]
        out[name + "_diff"] = float(np.mean(diff))
        out[name + "_se"] = float(np.std(diff, ddof=1) / math.sqrt(len(diff)))
        out[name + "_better"] = sum(x > 0 for x in diff)
    log(f"unit scores: walk-forward {R._m(wf, tests):.3f}, shared decay {R._m(shared, tests):.3f}, "
        f"undiscounted {R._m(old, tests):.3f}")
    return out


def main() -> None:
    t0 = time.time()
    games = R.load_games()
    targets, ratings = R.build_targets(games)
    years = sorted(targets)
    consensus = R.load_consensus()
    teams_by_year = {}
    for y in years:
        commits = Counter(r.committed_team for r in R.recruits(y) if r.committed_team)
        teams_by_year[y] = sorted(t for t in targets[y] if commits[t] > 0)
    wins = win_pct_targets(games, teams_by_year)
    fits = {y: fit_class(y) for y in years}
    log(f"fitted default program strengths for classes {years[0]}-{years[-1]}")

    dev = [y for y in years if y <= R.DEV_LAST]
    hold = [y for y in years if y > R.DEV_LAST]
    tests = [y for y in years if len([t for t in years if t <= y - R.LAG]) >= R.MIN_TRAIN]

    def evaluate(scores_of) -> dict:
        rho, resid, win = {}, {}, {}
        for y in years:
            s, teams = scores_of(y), teams_by_year[y]
            missing = min(s.values()) - 1.0
            rho[y] = R.rho(s, targets[y], teams, missing)
            win[y] = R.rho(s, wins[y], teams, missing)
            prior = ratings.get(y - 1)
            if prior:
                resid[y] = R.rho(s, R.residualise(targets[y], prior, teams), teams, missing)
        return {"rho": rho, "resid": resid, "win": win}

    base = evaluate(lambda y: class_scores(fits[y]))
    bench = {
        "On3 industry consensus": evaluate(lambda y: {t: -r for t, r in consensus[y].items()}),
        "mean commit stars": evaluate(lambda y: R.star_average(y)),
    }
    families = {}
    for name, fam in FAMILIES.items():
        runs = {v: evaluate(lambda y, v=v: class_scores(fits[y], **{name: v})) for v in fam["values"]}
        chosen, wf = {}, {}
        for y in tests:
            train = [t for t in years if t <= y - R.LAG]
            chosen[y] = max(fam["values"], key=lambda v: R._m(runs[v]["rho"], train))
            wf[y] = runs[chosen[y]]["rho"][y]
        diff = [wf[y] - base["rho"][y] for y in tests]
        families[name] = {"runs": runs, "chosen": chosen, "wf": wf,
                          "diff": float(np.mean(diff)),
                          "se": float(np.std(diff, ddof=1) / math.sqrt(len(diff))),
                          "better": sum(d > 0 for d in diff)}
        log(f"{name}: walk-forward {R._m(wf, tests):.3f} vs default {R._m(base['rho'], tests):.3f}")
    units = unit_study(games, years, tests, teams_by_year)
    log(f"finished in {time.time() - t0:.0f}s")
    (MODEL_DIR / "RESEARCH_VARIANTS.md").write_text(
        render(years, dev, hold, tests, teams_by_year, base, bench, families, units))


def render_units(years, dev, hold, tests, u) -> list[str]:
    m = R._m
    shared = DEFAULTS["rank_decay"]
    lines = [
        "## Unit scores: rank decay on offense and defense",
        "",
        "**Question.** The class score discounts a class's k-th best recruit by rank_decay^(k-1);",
        "before v0.8.0 the offense / defense / run / pass unit scores were plain sums, so a big class",
        "of middling defenders could out-rank a small class of top ones on Defense while trailing",
        "overall. Does discounting each side of the ball the same way rank units better?",
        "",
        "**Method.** Outcome per program and class Y: mean over seasons Y..Y+3 of an opponent-adjusted",
        "points rating fitted on the same FBS scores as the SRS (points = mean + offense of the team",
        "with the ball − defense of the other + home edge; both higher = better). Spearman ρ within",
        "a class year between the offense unit score and the offense rating, and between the defense",
        "unit score and the defense rating. Walk-forward: for test class Y the setting with the best",
        f"mean of the two on classes ≤ Y−{R.LAG} is used. Test classes {tests[0]}–{tests[-1]}: **{len(tests)} class years**",
        f"({u['n_rows']} program-classes, overlapping targets, about {len(tests) / R.WINDOW:.1f} non-overlapping periods).",
        "\"Balance\" is ρ between log(offense unit / defense unit) and offense minus defense rating:",
        "whether a class tilted to one side predicts a team better on that side. Run / pass units",
        "cannot be checked: the scores file has points only, no rushing or passing splits.",
        "",
        f"| unit_rank_decay | offense ρ dev {dev[0]}–{dev[-1]} | offense ρ holdout | defense ρ dev | defense ρ holdout | "
        f"mean of both (test {tests[0]}–{tests[-1]}) | balance (test) |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for d, e in u["runs"].items():
        label = f"{d:g}" + (" (undiscounted, before v0.8.0)" if d == 1.0 else "") + (
            " (= rank_decay)" if d == shared else "")
        lines.append(f"| {label} | {m(e['off'], dev):.3f} | {m(e['off'], hold):.3f} | {m(e['def'], dev):.3f} | "
                     f"{m(e['def'], hold):.3f} | {m(e['both'], tests):.3f} | {m(e['bal'], tests):.3f} |")
    o = u["overall"]
    lines += [
        f"| overall class score (reference) | {m(o['off'], dev):.3f} | {m(o['off'], hold):.3f} | "
        f"{m(o['def'], dev):.3f} | {m(o['def'], hold):.3f} | "
        f"{m({y: (o['off'][y] + o['def'][y]) / 2 for y in years}, tests):.3f} | – |",
        "",
        f"Walk-forward choice: {', '.join(f'{v:g}' for v in u['chosen'].values())}; minus undiscounted "
        f"{u['wf_diff']:+.3f} ± {u['wf_se']:.3f} ({u['wf_better']}/{len(tests)} years better). "
        f"Decay {shared:g} (shared with rank_decay) minus undiscounted {u['shared_diff']:+.3f} ± "
        f"{u['shared_se']:.3f} ({u['shared_better']}/{len(tests)} years better).",
        "",
        "**Verdict.** "
        + (f"Discounting beats plain sums in every test year, by {u['shared_diff']:+.3f} ρ at {shared:g} "
           f"(below the {R.ADOPT_MARGIN} tuning margin) and {u['wf_diff']:+.3f} with the walk-forward pick. "
           "But the overall class score ranks both units better than any unit score, and the balance "
           "column is about zero with or without decay: the unit split says next to nothing about which "
           "side of the ball a team will be better on, so stronger decay helps mostly by making the unit "
           "scores more like the overall score. So the choice rests on consistency, not on the larger "
           f"walk-forward gain: v0.8.0 adds `unit_rank_decay` = {shared:g}, the same discount as the class "
           "score, and keeps the plain sums as variant "
           "`undiscounted_units`."
           if u["shared_diff"] >= 0 else
           "Discounting is worse than plain sums here; the undiscounted sums stay the default.")
        ,
        "",
    ]
    return lines


def render(years, dev, hold, tests, teams_by_year, base, bench, families, units) -> str:
    m = R._m
    n_rows = sum(len(teams_by_year[y]) for y in tests)
    lines = [
        "# RESEARCH — other ways to score a recruit and add up a class (football)",
        "",
        "_Generated by `python -m ballmonitor.models.ncaaf_recruiting.research_variants`; do not edit by hand._",
        "",
        "**Question.** RESEARCH.md found the model's four tuning numbers (rank decay, quality power,",
        "prior strength, pooled class years) flat. Do *structural* changes help: crediting the",
        "committed school, dropping courtesy offers, blending in stars, weighting positions, or",
        "handling class size differently?",
        "",
        "**Method.** As in RESEARCH.md: Spearman ρ within a class year between the class score and the",
        f"program's mean SRS over seasons Y..Y+3, classes {years[0]}–{years[-1]}. For test class Y a family's",
        f"setting is chosen on classes ≤ Y−{R.LAG} only. Test classes {tests[0]}–{tests[-1]}: **{len(tests)} class years**",
        f"({n_rows} program-classes; overlapping four-season targets, about {len(tests) / R.WINDOW:.1f} non-overlapping",
        "periods). \"After prior\" is ρ with the part of the target a line on the previous season's SRS",
        "does not explain. Wins = ρ with the share of games won in the same four seasons.",
        "",
        "## Reference rankings",
        "",
        f"| ranking | dev {dev[0]}–{dev[-1]} | holdout {hold[0]}–{hold[-1]} | test {tests[0]}–{tests[-1]} | after prior (test) | wins (test) |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    def ref(label, e):
        return (f"| {label} | {m(e['rho'], dev):.3f} | {m(e['rho'], hold):.3f} | {m(e['rho'], tests):.3f} | "
                f"{m(e['resid'], tests):.3f} | {m(e['win'], tests):.3f} |")
    lines.append(ref("**offer model, defaults**", base))
    lines += [ref(k, v) for k, v in bench.items()]
    lines += [
        "",
        "## Walk-forward result per idea",
        "",
        "Difference = the idea (setting chosen on earlier classes) minus the default, mean over the",
        "test class years ± one standard error of the paired yearly differences.",
        "",
        "| idea | walk-forward ρ | default ρ | difference | ± se | years better | settings chosen |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for name, f in families.items():
        picks = ", ".join(f"{v:g}" for v in f["chosen"].values())
        lines.append(f"| `{name}` | {m(f['wf'], tests):.3f} | {m(base['rho'], tests):.3f} | {f['diff']:+.3f} | "
                     f"{f['se']:.3f} | {f['better']}/{len(tests)} | {picks} |")
    best = max(families.values(), key=lambda f: f["diff"])
    lines += [
        "",
        f"**Verdict.** The largest walk-forward gain is {best['diff']:+.3f} ρ; research.py's adoption margin is "
        f"{R.ADOPT_MARGIN} ρ and the default-vs-consensus gap is "
        f"{m(bench['On3 industry consensus']['rho'], tests) - m(base['rho'], tests):.3f}. "
        + ("No idea clears the margin, so none was adopted and none was added to the model."
           if best["diff"] < R.ADOPT_MARGIN else "At least one idea clears the margin; see the tables."),
        "",
        "## Every setting",
        "",
    ]
    for name, f in families.items():
        lines += [
            f"### `{name}`",
            "",
            f"What it does: {FAMILIES[name]['what']}. Default: {FAMILIES[name]['values'][0]:g}.",
            "",
            "| setting | dev | holdout | test | after prior (test) | wins (test) |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
        for v, e in f["runs"].items():
            lines.append(f"| {v:g} | {m(e['rho'], dev):.3f} | {m(e['rho'], hold):.3f} | {m(e['rho'], tests):.3f} | "
                         f"{m(e['resid'], tests):.3f} | {m(e['win'], tests):.3f} |")
        lines.append("")
    lines += render_units(years, dev, hold, tests, units)
    lines += [
        "## Not testable with the data in this repo",
        "",
        "- **Offer timing, visits, how serious an offer was.** The recruit files hold one flat list of",
        "  schools per recruit. On3's API has commit dates, visit counts and an interest flag, but the",
        "  raw responses were only kept for the 2027 class, which has no results yet.",
        "- **Late / unfinished classes (2027).** There are no dated snapshots of earlier classes, so a",
        "  rule for a class that is still signing cannot be checked against how it ended.",
        "- **Transfer portal.** No portal data in the repo. Needed: every transfer with player, old and",
        "  new school, date, and a rating or prior playing time (On3 and 247Sports publish portal",
        "  lists from 2019 on), to count talent leaving and arriving per program and season.",
        "- **Attrition.** No rosters or enrollment data: which signees were still on the team each year.",
        "",
        "## Caveats",
        "",
        f"- {len(tests)} test class years with overlapping targets: differences of a few thousandths of ρ are noise.",
        "- Program strengths are the default fit in every variant (the offer network is not refitted).",
        "- Stars are Rivals stars in the 2012–2021 files (1 = unrated) and On3 consensus stars after;",
        f"  position labels differ between the two sources (linemen = {', '.join(LINE_POSITIONS)}).",
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
