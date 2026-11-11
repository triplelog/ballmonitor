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
    log(f"finished in {time.time() - t0:.0f}s")
    (MODEL_DIR / "RESEARCH_VARIANTS.md").write_text(
        render(years, dev, hold, tests, teams_by_year, base, bench, families))


def render(years, dev, hold, tests, teams_by_year, base, bench, families) -> str:
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
