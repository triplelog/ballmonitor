"""RESEARCH.md for ncaaf_bowls, written from the JSON that research.py saves (data/research/)."""

from __future__ import annotations

from pathlib import Path


def _table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out + [""]


def _games(g: dict) -> list[str]:
    o, f = g["old_all"], g["fit_all"]
    out = [
        "## 1. One game: rating gap to win probability", "",
        f"**Data.** {g['n_games']:,} games between two FBS teams, {g['seasons']} seasons (2016-2025), from "
        "week 3 on, title games, bowls and playoff games included. Each is predicted from the ESPN FPI "
        "published after the previous week's games. Check against hindsight: the snapshot that already "
        f"contains the game picks {g['placebo_same_week']['accuracy']:.1%} of winners, the one before it "
        f"{o['accuracy']:.1%}, in every season alike.", "",
        f"**The 0.4.3 defaults** (home field 2.5, margin SD 14): Brier {o['brier']:.4f}, log loss "
        f"{o['log_loss']:.4f}, favourite won {o['accuracy']:.1%}. Fitted on all ten seasons: home field "
        f"{f['home_field_points']}, SD {f['margin_sd']} (the margin itself misses the rating gap by "
        f"{g['margin_residual_sd']:.1f} points; the SD that gives the best win probabilities is smaller "
        "because margins have fat tails).", "",
        "**Walk-forward** (home field and SD refitted on the seasons before each test season):", "",
    ]
    out += _table(["test season", "games", "fitted home / SD", "log loss, defaults", "log loss, refitted",
                   "Brier, defaults", "Brier, refitted"],
                  [[r["season"], r["old"]["n"], f"{r['fit_home']} / {r['fit_sd']}", f"{r['old']['log_loss']:.4f}",
                    f"{r['fitted']['log_loss']:.4f}", f"{r['old']['brier']:.4f}", f"{r['fitted']['brier']:.4f}"]
                   for r in g["walk_forward"]])
    better = sum(r["fitted"]["log_loss"] < r["old"]["log_loss"] for r in g["walk_forward"])
    out += [f"Refitting wins {better} of {len(g['walk_forward'])} seasons, never by more than 0.002. "
            "**Not promoted: home field 2.5 and SD 14 stay.**", "",
            "Calibration of the defaults (all ten seasons):", ""]
    out += _table(["favourite's chance", "games", "predicted", "won"],
                  [[f"{c['lo']:.0%}-{min(c['hi'], 1):.0%}", c["n"], f"{c['predicted']:.1%}", f"{c['actual']:.1%}"]
                   for c in g["calibration"]])
    out += ["**How far ahead.** The same games predicted from older ratings (defaults):", ""]
    out += _table(["weeks ahead", "games", "Brier", "favourite won", "best SD"],
                  [[h["weeks_ahead"], h["n"], f"{h['brier']:.4f}", f"{h['accuracy']:.1%}", h["best_sd"]]
                   for h in g["horizon"]])
    late = ", ".join(f"{h['weeks_ahead']} wk: {h['best_sd']}" for h in g["horizon_from_week_8"])
    out += [f"Most of that is early-season ratings being rough. From ratings of week 8 or later the best SD "
            f"barely moves ({late}). A margin SD that grows with the weeks ahead was therefore not added; "
            "part 2 handles the real problem (a team's rating being wrong in all its games at once).", "",
            "**Results-only rating and blends.** The model's own results-only rating (fetch.py's fit, on the "
            f"season so far) against FPI, {g['blend']['n']:,} games from week 4 on:", ""]
    out += _table(["FPI share", "Brier", "log loss", "favourite won", "seasons better than FPI alone (of 10)"],
                  [[w["fpi_weight"], f"{w['brier']:.4f}", f"{w['log_loss']:.4f}", f"{w['accuracy']:.1%}",
                    "-" if w["fpi_weight"] == 1 else w["seasons_better_than_fpi"]] for w in g["blend"]["weights"]])
    out += ["A 15% results share moves log loss by 0.0002 and wins 6 seasons of 10; anything more is worse. "
            "**Not promoted: FPI alone stays the default.**", ""]
    return out


def _wins(w: dict) -> list[str]:
    z, wf = w["all_seasons"]["0.0"], w["walk_forward"]
    out = [
        "## 2. The rest of a season: rating uncertainty", "",
        f"**Data.** Every FBS team's remaining regular-season games from {len(w['weeks'])} dates (after weeks "
        f"{w['weeks'][0]}-{w['weeks'][-1]}) in {len(w['seasons'])} seasons (2016-2025 without the shortened "
        f"2020): {z['n']:,} team-dates. Team-dates in one season share games, so the count of independent "
        "seasons is what matters.", "",
        "**Problem.** With every game an independent coin flip from fixed ratings, teams finish further from "
        f"their expected wins than the model allows: the squared miss is {z['spread_ratio']:.2f} times what it "
        "predicts (1.00 = right). A team that is better than its rating is better in all its games.", "",
        "**Change.** `rating_uncertainty_points`: each simulated season shifts every team's rating by its own "
        "Normal(0, s) draw, kept for all its games; the game SD shrinks so one game keeps SD 14 "
        "(formula `simulated_game_sd`). Log score of the actual number of remaining wins (lower is better):", "",
    ]
    out += _table(["after week", "best s", "log score, s = 0", "log score, best s", "spread ratio, s = 0",
                   "spread ratio, best s", f"seasons better (of {len(w['seasons'])})"],
                  [[r["week"], r["best_sigma"], f"{r['zero']['log_score']:.4f}", f"{r['best']['log_score']:.4f}",
                    f"{r['zero']['spread_ratio']:.2f}", f"{r['best']['spread_ratio']:.2f}", r["seasons_better"]]
                   for r in w["by_week"]])
    out += ["**Walk-forward** (s picked on the seasons before the test season; all 11 dates):", ""]
    out += _table(["test season", "s picked", "team-dates", "log score 0 -> s", "spread ratio 0 -> s",
                   "weeks 9-12 only: log score 0 -> s", "bowl-eligibility Brier 0 -> s"],
                  [[r["season"], r["sigma"], r["old"]["n"],
                    f"{r['old']['log_score']:.4f} -> {r['new']['log_score']:.4f}",
                    f"{r['old']['spread_ratio']:.2f} -> {r['new']['spread_ratio']:.2f}",
                    f"{r['old_late']['log_score']:.4f} -> {r['new_late']['log_score']:.4f}",
                    f"{r['old']['elig_brier']:.4f} -> {r['new']['elig_brier']:.4f}"] for r in wf])
    n = len(wf)
    b_all = sum(r["new"]["log_score"] < r["old"]["log_score"] for r in wf)
    b_late = sum(r["new_late"]["log_score"] < r["old_late"]["log_score"] for r in wf)
    b_el = sum(r["new"]["elig_brier"] < r["old"]["elig_brier"] for r in wf)
    out += [f"Better win-total log score in {b_all} of {n} test seasons ({b_late} of {n} for weeks 9-12, where "
            "the gain is small because few games are left). The yes/no bowl-eligibility forecast (teams whose "
            f"eligibility was still open) improves in only {b_el} of {n}: the change fixes how wide the range of "
            "records is, not who is favoured. All-season best s is "
            f"{w['all_seasons_best_sigma']:.0f}; 5 and 6 score within 0.001 of each other, and 5 is the default "
            "(the smaller change). **Promoted: rating_uncertainty_points = 5.**", ""]
    return out


def _committee(c: dict) -> list[str]:
    o, n, f = c["old_test"], c["walk_forward_test"], c["final_fit"]
    k = len(c["test_seasons"])
    out = [
        "## 3. The committee: resume score vs. the real final rankings", "",
        "**Data.** The selection committee's final top 25 of 2016-2025 (10 seasons, 250 ranked teams) against "
        "every FBS team's record on selection day, conference title and the FPI published after the title "
        "games. The 4-team era is used for the ranking only (top 12 = where the 12-team line would fall).", "",
        "**Fit.** Same formula as before; weights fitted as a Plackett-Luce ranking (the committee picks #1 "
        "from all teams, #2 from the rest, ...), in units of one rating point.", "",
        f"**Walk-forward, {k} test seasons 2019-2025** (weights fitted on earlier seasons only):", "",
    ]
    out += _table(["", f"committee top-12 teams in model's top 12 (of {12 * k})", f"top 4 (of {4 * k})",
                   f"top 25 (of {25 * k})", "pairs of ranked teams in the right order",
                   "rank miss, committee's top 12", "top 12 per season"],
                  [[lab, r["top12"], r["top4"], r["top25"], f"{r['pair_order']:.1%}",
                    f"{r['rank_error_top12']:.2f}", r["per_season_top12"]]
                   for lab, r in (("0.4.3 weights", o), ("FPI alone", c["fpi_only_test"]), ("refitted", n))])
    out += ["The refit is at least as good in every test season for the top 12, and one worse over the seven "
            f"seasons for the top 4 ({n['top4']} vs {o['top4']}).", "",
            "Who it changes in the 12-team seasons (weights fitted on earlier seasons):", ""]
    out += _table(["season", "0.4.3 missed", "0.4.3 had instead", "refit missed", "refit had instead"],
                  [[m["season"], ", ".join(m["old_missed"]), ", ".join(m["old_instead"]),
                    ", ".join(m["new_missed"]), ", ".join(m["new_instead"])] for m in c["misses"]])
    out += ["Fitted weights by test season (stable from 2021 on; the loss-penalty term is small and its sign "
            "flips, the win-percentage term does the work):", ""]
    out += _table(["fitted on seasons before", "win %", "loss penalty", "champion", "power champion",
                   "power conference", "noise scale"],
                  [[r["season"], r["winpct"], r["losspow"], r["champ"], r["p4champ"], r["p4"], r["noise_scale"]]
                   for r in c["walk_forward_weights"]])
    cw, ci = c["config_weights"], c["config_all_in_sample"]
    out += [f"**Defaults** = the fit on all ten seasons (win % {f['winpct']}, loss penalty {f['losspow']}, "
            f"champion {f['champ']}, power champion {f['p4champ']}, power conference {f['p4']}), rounded to "
            f"{cw['resume_win_pct_weight']:g} / {cw['resume_loss_penalty_scale']:g} / "
            f"{cw['resume_conf_champ_bonus']:g} / {cw['resume_p4_champ_bonus']:g} / {cw['resume_power4_bonus']:g}. "
            f"In-sample (hindsight, for reference only) they match {ci['top12']} of 120 top-12 teams and "
            f"{ci['top4']} of 40 top-4 teams; the 0.4.3 weights {c['old_all']['top12']} and {c['old_all']['top4']}. "
            "**Promoted.**", "",
            "**Committee noise.** The score never matches the committee exactly, so a fixed ranking is "
            "overconfident. `resume_noise_points` adds Gumbel noise (multiplier x the fit's noise scale). "
            f"Summed squared error of P(in the committee's top 12 / top 4) over all FBS teams, {k} test seasons:", ""]
    out += _table(["multiplier", "top 12", "top 4", "top 12 per season"],
                  [[x["mult"], f"{x['top12_brier_sum']:.2f}", f"{x['top4_brier_sum']:.2f}", x["per_season_top12"]]
                   for x in c["noise"]])
    ne = c["noise_nested"]
    out += [f"Nested test (multiplier picked on the earlier test seasons only, {len(ne)} seasons "
            f"{ne[0]['season']}-{ne[-1]['season']}): top 12 {sum(x['top12_old'] for x in ne):.2f} -> "
            f"{sum(x['top12_new'] for x in ne):.2f} (better in "
            f"{sum(x['top12_new'] < x['top12_old'] for x in ne)} of {len(ne)}), top 4 "
            f"{sum(x['top4_old'] for x in ne):.2f} -> {sum(x['top4_new'] for x in ne):.2f} (better in "
            f"{sum(x['top4_new'] < x['top4_old'] for x in ne)} of {len(ne)}). A modest gain that costs the "
            "seasons the score happened to get exactly right. **Promoted at multiplier "
            f"{f['noise_mult']} x {f['noise_scale']} = {cw['resume_noise_points']:g} points.**", ""]
    return out


def _season(s: dict) -> list[str]:
    out = [
        "## 4. The season simulator on 2024 and 2025", "",
        f"The model's own `SeasonSimulator` ({s['sims']:,} seasons) run from four dates in each of the two "
        "12-team seasons, with the FPI, records and remaining schedule of that date; field = that season's "
        "rule (five best-ranked champions + seven at-large). Scores are squared error summed over every FBS "
        "team (lower is better); `ESPN` is ESPN's own published chance from the same day. **Two seasons: a "
        "check that the changes hold up inside the simulator, not proof on its own.** \"New\" uses weights "
        "fitted on seasons that include 2024 and 2025 (part 3 has the out-of-sample test).", "",
    ]
    out += _table(["season", "after week", "games left", "playoff field: 0.4.3", "new", "ESPN",
                   "conference champions: 0.4.3", "new", "ESPN"],
                  [[r["season"], r["after_week"], r["games_left"],
                    *(f"{r[k]['field']['brier_sum']:.2f}" for k in ("old", "new", "espn")),
                    *(f"{r[k]['champ']['brier_sum']:.2f}" for k in ("old", "new", "espn"))] for r in s["rows"]])
    tot = lambda k, what, m: sum(r[k][what][m] for r in s["rows"])  # noqa: E731
    cols = ("old", "sigma_only", "weights_only", "new", "espn")
    out += _table(["total of the 8 runs", "0.4.3", "0.4.3 + rating uncertainty", "0.4.3 + new weights (no noise)",
                   "new (all three)", "ESPN"],
                  [["playoff field, squared error", *(f"{tot(k, 'field', 'brier_sum'):.2f}" for k in cols)],
                   ["playoff field, log loss", *(f"{tot(k, 'field', 'log_loss_sum'):.1f}" for k in cols)],
                   ["conference champions, squared error", *(f"{tot(k, 'champ', 'brier_sum'):.2f}" for k in cols)],
                   ["conference champions, log loss", *(f"{tot(k, 'champ', 'log_loss_sum'):.1f}" for k in cols)]])
    wins = lambda k: sum(r[k]["field"]["brier_sum"] < r["old"]["field"]["brier_sum"] for r in s["rows"])  # noqa: E731
    out += [f"Playoff-field squared error better than 0.4.3 in: rating uncertainty {wins('sigma_only')} of 8 runs, "
            f"new weights {wins('weights_only')} of 8, all three {wins('new')} of 8. Log loss clips each "
            "probability at 0.5%; simulation noise on a total is about 0.2.", "",
            "**Reading.** Rating uncertainty helps here too (both tables, both scores). The new committee "
            "weights, clearly closer to the committee in part 3, do **not** show up as a better playoff-field "
            "forecast in these two seasons: squared error is level or slightly worse, and only the noise brings "
            "log loss down. With two seasons and a handful of bubble teams deciding it, this neither confirms "
            "nor refutes part 3. The weights were promoted on part 3's seven seasons; the 0.4.3 weights stay "
            "available as variant `committee_v043`.", ""]
    return out


def write_report(path: Path, parts: dict[str, dict | None]) -> None:
    out = [
        "# ncaaf_bowls: accuracy study", "",
        "_Generated by `python -m ballmonitor.models.ncaaf_bowls.research`; do not edit by hand._", "",
        "Real past seasons only (ESPN, 2016-2025; `research_data.py`). Every fitted number is tested "
        "walk-forward: fitted on the seasons before the test season. What is **not** tested here: which bowl "
        "a team goes to (the tie-in and bowl-pick part of the model), seeding, and the playoff games "
        "themselves beyond part 1's single-game check.", "",
        "**Hindsight guard.** ESPN keeps one FPI snapshot per week. The snapshot labelled week N is the one "
        "after week N's games (the title-game week moves only the teams that played; 2023-2025 timestamps "
        "agree), so games of week N are predicted from snapshot N-1. The `last_updated` stamps of 2016-2022 "
        "are stale and are not used; 'week 1' snapshots (recomputed in December in some seasons) are dropped.", "",
    ]
    for name, fn in (("games", _games), ("wins", _wins), ("committee", _committee), ("season", _season)):
        if parts.get(name):
            out += fn(parts[name])
    path.write_text("\n".join(out).rstrip() + "\n")
