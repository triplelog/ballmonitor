"""Public page: every FBS team's playoff, title and bowl odds from one season simulation, with a
page per team (/ncaaf_bowls/team/<team>/) and per bowl (/ncaaf_bowls/bowl/<bowl>/).

Built at site-build time (`ballmonitor build-site`, `ballmonitor views ncaaf_bowls`); the page
only displays these numbers.
"""

from __future__ import annotations

import datetime as dt
import json
import math

from ballmonitor.core import views as V

SHOW_MIN = 0.005      # leave out outcomes rarer than 0.5% (they'd round to "<1%" anyway)
TEAM_BOWLS = 12       # bowl destinations listed on a team's page
BOWL_MATCHUPS = 15    # matchups listed on a bowl's page
BOWL_TEAMS = 12       # teams charted on a bowl's page
ROUND_NAME = {"quarterfinal": "playoff quarterfinal", "semifinal": "playoff semifinal",
              "final": "national championship", "championship": "national championship"}


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _tie_ins(bowl: dict) -> str:
    slots = [" or ".join(s.get("confs") or []) for s in bowl.get("slots") or []]
    slots = [s for s in slots if s]
    return " vs ".join(slots)


def _pct(p: float) -> str:
    return "under 1%" if 0 < p < 0.005 else f"{p:.0%}"


def projected_field(summaries) -> dict[str, int]:
    """team_id -> projected seed: the 12 likeliest playoff teams, ordered by their average seed
    when they make it. One projection used everywhere on the page (bracket, bubble, team pages)."""
    field = sorted(summaries, key=lambda s: -s.p_cfp)[:12]
    avg = {s.team_id: sum(k * p for k, p in s.top_seeds.items()) / s.p_cfp if s.p_cfp > 0 else 99 for s in field}
    return {s.team_id: i for i, s in enumerate(sorted(field, key=lambda s: avg[s.team_id]), 1)}


def _answer(s, team: dict, bowl_names: dict, proj: dict[str, int]) -> str:
    """The one line a fan wants first, e.g. "Georgia (6-1, SEC): 89% to make the playoff,
    projected as the No. 6 seed; projected 10.7-2.2 before the bowls"."""
    head = f"{s.team_name} ({team.get('wins', 0)}-{team.get('losses', 0)}, {s.conf})"
    rec = f"{s.record_mean_wins:.1f}-{s.record_mean_losses:.1f} expected before the bowls"
    if s.p_cfp >= 0.25:
        where = (f", projected as the No. {proj[s.team_id]} seed" if s.team_id in proj
                 else ", just outside the projected 12-team field")
        return f"{head}: {_pct(s.p_cfp)} to make the playoff{where}; {rec}."
    bowl = s.top_bowls[0] if s.top_bowls else None
    if s.p_eligible >= 0.5 and bowl:
        return (f"{head}: {_pct(s.p_eligible)} to be bowl eligible; most likely bowl: "
                f"{bowl_names.get(bowl[0], bowl[1])} ({_pct(bowl[2])}); {rec}.")
    return f"{head}: {_pct(s.p_eligible)} to reach six wins and a bowl; {rec}."


# ── who to root for this week ─────────────────────────────────────────────────

def this_week(schedule: list[dict], today: dt.date | None = None) -> tuple[list[int], str]:
    """Schedule indices of the next week's FBS-vs-FBS games and its dates ("Nov 14-15"): the
    earliest week with a game on or after `today` (the build date). Games of a week that is
    already over but not yet in the fetched results are left out."""
    today = today or dt.date.today()
    fbs = [(i, g) for i, g in enumerate(schedule)
           if not (g["home"].startswith("fcs_") or g["away"].startswith("fcs_")) and g.get("week") is not None]
    upcoming = [g["week"] for _, g in fbs if g.get("date") and dt.date.fromisoformat(g["date"]) >= today]
    if not upcoming:
        return [], ""
    week = min(upcoming)
    games = [i for i, g in fbs if g["week"] == week and dt.date.fromisoformat(g["date"]) >= today]
    days = sorted({dt.date.fromisoformat(schedule[i]["date"]) for i in games})
    first, last = days[0], days[-1]
    when = (f"{first:%b} {first.day}" if first == last else
            f"{first:%b} {first.day}-{last.day}" if first.month == last.month else
            f"{first:%b} {first.day}-{last:%b} {last.day}")
    return games, when


def _game_label(g: dict, names: dict[str, str]) -> str:
    sep = " vs " if g.get("neutral") else " at "
    return f"{names.get(g['away'], g['away'])}{sep}{names.get(g['home'], g['home'])}"


def _swing(tally, hits_if_home: int, hits_total: int, n: int, z: float):
    """(chance if home wins, chance if away wins, swing, shown?) where shown = the swing is bigger
    than `z` standard errors of the simulation (a game a team isn't in can look like it matters
    by chance alone)."""
    split = tally.split(hits_if_home, hits_total, n)
    if split is None:
        return None
    p_home, p_away, n_home, n_away = split
    pooled = hits_total / n
    se = math.sqrt(max(pooled * (1 - pooled), 1e-12) * (1 / n_home + 1 / n_away))
    return p_home, p_away, p_home - p_away, abs(p_home - p_away) >= z * se


def root_for(team_id: str, summary, res, schedule: list[dict], games: list[int], names: dict[str, str],
             p) -> tuple[str, list[dict]]:
    """("playoff" | "conference title" | "", rows): this week's games that move a team's playoff
    chance (or, when that is out of reach, its conference-title chance), biggest first, the
    team's own game always first. Each row: the game, the side to root for, the chance if that
    side wins / loses, and the difference."""
    n = res.total_simulations
    min_chance = float(p.site_root_min_chance)
    if summary.p_cfp >= min_chance:
        what, total, pick = "playoff", round(summary.p_cfp * n), lambda t: t.cfp_if_home
    elif summary.p_conf_champ >= min_chance:
        what, total, pick = "conference title", round(summary.p_conf_champ * n), lambda t: t.conf_if_home
    else:
        return "", []
    rows = []
    for g in games:
        tally = res.game_tallies.get(g)
        if tally is None:
            continue
        sw = _swing(tally, pick(tally)[team_id], total, n, float(p.site_root_z))
        if sw is None:
            continue
        p_home, p_away, diff, clear = sw
        own = team_id in (tally.home, tally.away)
        if not own and not (clear and abs(diff) >= float(p.site_root_min_swing)):
            continue
        home_side = (tally.home == team_id) if own else diff > 0
        side = tally.home if home_side else tally.away
        rows.append({"game": _game_label(schedule[g], names), "root": names.get(side, side),
                     "if_win": p_home if home_side else p_away, "if_lose": p_away if home_side else p_home,
                     "diff": abs(diff), "_own": own})
    rows.sort(key=lambda r: (not r["_own"], -r["diff"]))
    return what, [{k: v for k, v in r.items() if k != "_own"} for r in rows[:int(p.site_root_rows)]]


def root_view(team_id: str, team_name: str, what: str, rows: list[dict], when: str) -> dict:
    return V.table(
        f"root_{team_id}", f"Who to root for this week ({when})",
        [V.col("game", "Game"), V.col("root", "Root for"),
         V.col("if_win", f"{what.capitalize()} chance if they win", "pct"),
         V.col("if_lose", "If they lose", "pct"), V.col("diff", "Difference", "pct", bar=True)],
        rows,
        subtitle=f"{team_name}'s {what} chance depending on how each game this week goes. "
                 f"Their own game comes first; games that barely matter are left out.",
        note=f"From the same simulated seasons: the {what} chance in the seasons where that team won "
             "the game versus the ones where it lost. Differences smaller than the simulation's own "
             "noise are left out.")


def biggest_games(res, schedule: list[dict], games: list[int], names: dict[str, str], summaries,
                  when: str, p) -> dict | None:
    """This week's games ranked by how many playoff places they move: half the sum, over the
    teams whose chance clearly moves, of |chance if home wins - chance if away wins| (the
    total gained by some teams equals the total lost by others)."""
    n = res.total_simulations
    rows = []
    for g in games:
        tally = res.game_tallies.get(g)
        if tally is None:
            continue
        moved = []
        for s in summaries:
            if s.p_cfp <= 0:
                continue
            sw = _swing(tally, tally.cfp_if_home[s.team_id], round(s.p_cfp * n), n, float(p.site_root_z))
            if sw and sw[3] and abs(sw[2]) >= float(p.site_root_min_swing):
                moved.append((abs(sw[2]), s.team_name, sw[2]))
        if not moved:
            continue
        moved.sort(reverse=True)
        stake = sum(m[0] for m in moved) / 2
        p_home = tally.home_wins / n
        fav = tally.home if p_home >= 0.5 else tally.away
        rows.append({"game": _game_label(schedule[g], names), "stake": stake,
                     "fav": f"{names.get(fav, fav)} ({max(p_home, 1 - p_home):.0%})",
                     "teams": ", ".join(name for _, name, _ in moved[:4])})
    if not rows:
        return None
    rows.sort(key=lambda r: -r["stake"])
    return V.table(
        "big_games", f"This week's biggest games ({when})",
        [V.col("game", "Game"), V.col("stake", "Playoff places at stake", "number", decimals=2, bar=True),
         V.col("fav", "Favorite"), V.col("teams", "Whose playoff chances move most")],
        rows[:int(p.site_big_games_rows)],
        subtitle="The games that move the playoff race most, whoever wins. A team's own page shows "
                 "who it should root for.",
        note="Playoff places at stake: how much playoff chance changes hands between the two results, "
             "added up over every team it clearly moves (1.00 = one whole playoff spot).")


def _bubble(summaries, cuts: list[float], teams: dict, proj: dict[str, int]) -> dict:
    names = ["Locks", "Should be in", "On the bubble", "Work to do"]
    rows = []
    for s in summaries:
        tier = next((i for i, c in enumerate(cuts) if s.p_cfp >= c), None)
        if tier is None:
            continue
        t = teams.get(s.team_id, {})
        rows.append({"tier": names[tier], "team": s.team_name, "conf": s.conf,
                     "record": f"{t.get('wins', 0)}-{t.get('losses', 0)}", "cfp": s.p_cfp,
                     "conf_title": s.p_conf_champ, "seed": proj.get(s.team_id), "_t": tier})
    rows.sort(key=lambda r: (r["_t"], -r["cfp"]))
    cut_txt = ", ".join(f"{n}: {lo:.0%}{'+' if i == 0 else f'-{cuts[i - 1]:.0%}'}" for i, (n, lo) in enumerate(zip(names, cuts)))
    return V.table(
        "bubble", "Playoff bubble watch",
        [V.col("tier", "Status"), V.col("team", "Team", link="team"), V.col("conf", "Conf"), V.col("record", "Record"),
         V.col("cfp", "Playoff", "pct", bar=True), V.col("conf_title", "Conf. title", "pct"),
         V.col("seed", "Projected seed", "int", low_first=True)],
        [{k: v for k, v in r.items() if k != "_t"} for r in rows],
        subtitle="Every team with a real shot at the 12-team playoff, grouped by its chance.",
        note=f"Playoff chance: {cut_txt}.")


def _bracket(model, summaries, proj: dict[str, int]) -> list[dict]:
    """The projected field (projected_field) with the favorite advancing in every game (win
    chances from the config formula win_probability)."""
    by_id = {s.team_id: s for s in summaries}
    seeded = {seed: by_id[tid] for tid, seed in proj.items()}

    def win(a, b, home: int) -> float:
        return float(model.params.formula("win_probability", rating_diff=a.rating - b.rating, home=home))

    def label(i: int) -> str:
        return f"No. {i} {seeded[i].team_name}"

    rows = []

    def game(rnd: str, i: int, j: int, home: int, where: str) -> int:
        p = win(seeded[i], seeded[j], home)
        w = i if p >= 0.5 else j
        rows.append({"round": rnd, "matchup": f"{label(i)} vs {label(j)}", "where": where,
                     "fav": seeded[w].team_name, "p": max(p, 1 - p)})
        return w

    first = {i: game("First round", i, 17 - i, 1, f"at {seeded[i].team_name}") for i in (5, 6, 7, 8)}
    qf = {top: game("Quarterfinal", top, first[low], 0, "bowl game") for top, low in ((1, 8), (2, 7), (3, 6), (4, 5))}
    sf1 = game("Semifinal", qf[1], qf[4], 0, "bowl game")
    sf2 = game("Semifinal", qf[2], qf[3], 0, "bowl game")
    champ = game("Championship", sf1, sf2, 0, "national championship")

    seeds_table = V.table(
        "field", "Projected playoff field",
        [V.col("seed", "Seed", "int", low_first=True), V.col("team", "Team", link="team"), V.col("conf", "Conf"),
         V.col("cfp", "Playoff chance", "pct", bar=True), V.col("bye", "Bye chance", "pct")],
        [{"seed": i, "team": s.team_name, "conf": s.conf, "cfp": s.p_cfp, "bye": s.p_cfp_bye} for i, s in seeded.items()],
        subtitle="The 12 teams most likely to make it, in the order they're most likely to be seeded. Seeds 1-4 get a bye.",
        note="The real field also needs the five highest-ranked conference champions, so it can differ.")
    bracket = V.table(
        "bracket", "Projected bracket",
        [V.col("round", "Round"), V.col("matchup", "Game"), V.col("where", "Where"),
         V.col("fav", "Favorite"), V.col("p", "Win chance", "pct", bar=True)],
        rows, subtitle=f"If every favorite wins, {seeded[champ].team_name} takes the title.",
        note="Win chance for one game between the two teams (first-round games at the higher seed).")
    return [seeds_table, bracket]


def _team_option(s, team: dict, bowls: dict, bowl_names: dict, proj: dict[str, int],
                 root: dict | None = None) -> dict:
    intro = _answer(s, team, bowl_names, proj)

    steps = [
        ("Bowl eligible (6+ wins)", s.p_eligible),
        ("Plays a bowl or playoff game", s.p_play_postseason),
        (f"Wins the {s.conf}" if s.conf != "Independent" else "Wins its conference", s.p_conf_champ),
        ("Makes the 12-team playoff", s.p_cfp),
        ("Gets a first-round bye", s.p_cfp_bye),
        ("Reaches the quarterfinals", s.p_cfp_quarterfinal),
        ("Reaches the semifinals", s.p_cfp_semifinal),
        ("Plays for the national title", s.p_cfp_final),
        ("Wins the national title", s.national_champ_prob),
    ]
    if s.conf == "Independent":
        steps.pop(2)
    outcomes = V.bar(f"outcomes_{s.team_id}", "How the season could end",
                     [{"label": label, "value": p} for label, p in steps], fmt="pct", decimals=1)

    wins = V.bar(f"wins_{s.team_id}", "Record before the bowls",
                 [{"label": f"{w}-{lo}", "value": p} for (w, lo), p in s.record_dist.items() if p >= SHOW_MIN],
                 fmt="pct", subtitle="Including a conference title game if they play in one.")
    out = [root, outcomes, wins] if root else [outcomes, wins]

    if s.p_cfp >= SHOW_MIN:
        seeds = [{"label": f"No. {seed} seed", "value": p} for seed, p in sorted(s.top_seeds.items()) if p >= SHOW_MIN]
        if seeds:
            out.append(V.bar(f"seeds_{s.team_id}", "Playoff seed", seeds, fmt="pct",
                             subtitle="Seeds 1-4 get a first-round bye."))

    dest = sorted(s.bowls_detail.values(), key=lambda d: -d.p_appear)
    rows = []
    for d in dest[:TEAM_BOWLS]:
        if d.p_appear < SHOW_MIN:
            break
        b = bowls.get(d.bowl_id, {})
        opp, opp_p, _ = d.opponents[0] if d.opponents else ("", 0.0, 0.0)
        rows.append({
            "bowl": bowl_names.get(d.bowl_id, d.bowl_name),
            "kind": ROUND_NAME.get(b.get("cfp_round") or "", "playoff game") if b.get("is_cfp") else "bowl",
            "p": d.p_appear,
            "win": d.p_win_conditional,
            "opp": opp,
            "opp_p": opp_p,
        })
    if rows:
        out.append(V.table(
            f"bowls_{s.team_id}", "Where they could play",
            [V.col("bowl", "Game", link="bowl"), V.col("kind", "Type"), V.col("p", "Chance", "pct", bar=True),
             V.col("win", "Win chance there", "pct"), V.col("opp", "Most likely opponent"),
             V.col("opp_p", "Opp. chance", "pct")],
            rows, subtitle="Playoff first-round games are on campus, so they aren't listed here.",
            note="Win chance and opponent chance are for when they play in that game."))
    return V.option(s.team_name, out, intro=intro)


def _bowl_option(b, info: dict, name: str, confs: dict) -> dict:
    where = f"{b.city}, {b.state}"
    kind = ROUND_NAME.get(info.get("cfp_round") or "", "playoff game") if b.is_cfp else "bowl"
    tie = _tie_ins(info)
    intro = f"{name}: {kind} in {where}." + (f" Tie-ins: {tie}." if tie and not b.is_cfp else "")
    matchups = V.table(
        f"matchups_{b.bowl_id}", "Most likely matchups",
        [V.col("matchup", "Matchup"), V.col("p", "Chance", "pct", decimals=1, bar=True)],
        [{"matchup": f"{a} vs {c}", "p": p} for a, c, p in b.top_matchups[:BOWL_MATCHUPS]],
        subtitle="So many pairings are possible that even the likeliest one is a long shot.")
    teams = V.bar(
        f"teams_{b.bowl_id}", "Most likely teams",
        [{"label": t, "sub": confs.get(t, ""), "value": p} for t, p in b.top_teams[:BOWL_TEAMS] if p >= SHOW_MIN],
        fmt="pct", subtitle="Chance each team plays in this game.")
    return V.option(name, [teams, matchups], intro=intro)


def page(model) -> dict:
    data = model.dir / "data"
    meta = json.loads((data / "meta.json").read_text())
    teams = {t["id"]: t for t in json.loads((data / "teams.json").read_text())}
    bowls = {b["id"]: b for b in json.loads((data / "bowls.json").read_text())}
    bowl_names = {bid: b.get("espn_name") or b["name"] for bid, b in bowls.items()}

    sims = int(model.params.site_simulations)
    schedule = json.loads((data / "schedule.json").read_text())
    week_games, when = this_week(schedule)
    res = model.engine(sims).run(num_sims=sims, track_games=week_games)
    names = {tid: t["name"] for tid, t in teams.items()}
    summaries = sorted(res.team_summaries.values(), key=lambda s: (-s.p_cfp, -s.national_champ_prob, s.team_name))
    confs = {s.team_name: s.conf for s in summaries}

    rows = []
    for s in summaries:
        t = teams.get(s.team_id, {})
        bowl_id, _, bowl_p = s.top_bowls[0] if s.top_bowls else ("", "", 0.0)
        rows.append({
            "team": s.team_name,
            "conf": s.conf,
            "record": f"{t.get('wins', 0)}-{t.get('losses', 0)}",
            "wins": s.record_mean_wins,
            "cfp": s.p_cfp,
            "conf_title": s.p_conf_champ,
            "title": s.national_champ_prob,
            "bowl": bowl_names.get(bowl_id, "") if bowl_p >= 0.05 else "",
        })
    every_team = V.table(
        "teams", "Every FBS team",
        [V.col("team", "Team", link="team"), V.col("conf", "Conf"), V.col("record", "Record"),
         V.col("wins", "Proj. wins", "number"),
         V.col("cfp", "Playoff", "pct", bar=True), V.col("conf_title", "Conf. title", "pct"),
         V.col("title", "National title", "pct", decimals=1), V.col("bowl", "Most likely bowl", link="bowl")],
        rows, subtitle="Chances for the rest of the 2026 season. Click a team or bowl for its own page; "
                       "click a column to sort.",
        search=True, page_size=25,
        note=f"Projected wins: wins so far plus expected wins in the rest of the season, including a conference "
             f"title game if they play in one. Based on {sims:,} simulated seasons.")

    contenders = sorted((s for s in summaries if s.national_champ_prob >= SHOW_MIN), key=lambda s: -s.national_champ_prob)
    title_bars = V.bar(
        "title_odds", "Who wins the national title?",
        [{"label": s.team_name, "sub": s.conf, "value": s.national_champ_prob} for s in contenders[:16]],
        fmt="pct", decimals=1, subtitle="The teams with the best chance to win the College Football Playoff.")

    proj = projected_field(summaries)
    bubble = _bubble(summaries, [float(c) for c in model.params.site_bubble_cuts], teams, proj)
    field_views = _bracket(model, summaries, proj)
    fav = contenders[:2]
    if len(fav) == 2 and abs(fav[0].national_champ_prob - fav[1].national_champ_prob) < 0.015:
        headline = (f"{fav[0].team_name} and {fav[1].team_name} are the title favorites, about "
                    f"{_pct((fav[0].national_champ_prob + fav[1].national_champ_prob) / 2)} each.")
    else:
        headline = f"{fav[0].team_name} is the title favorite at {_pct(fav[0].national_champ_prob)}."
    locks = sum(1 for s in summaries if s.p_cfp >= float(model.params.site_bubble_cuts[0]))
    headline += f" {locks} teams are {float(model.params.site_bubble_cuts[0]):.0%}+ to make the playoff."

    by_name = sorted(summaries, key=lambda s: s.team_name)

    def root(s):
        what, rows = root_for(s.team_id, s, res, schedule, week_games, names, model.params)
        return root_view(s.team_id, s.team_name, what, rows, when) if rows else None

    big = biggest_games(res, schedule, week_games, names, summaries, when, model.params)
    team_picker = V.picker(
        "team", "Team by team", "Team",
        [_team_option(s, teams.get(s.team_id, {}), bowls, bowl_names, proj, root(s)) for s in by_name],
        subtitle="Every outcome for one team: who to root for this week, playoff path, record and bowl destinations.",
        default=by_name.index(summaries[0]))

    bowl_rows, bowl_opts = [], []
    for b in res.bowl_summaries.values():
        if not b.top_matchups:
            continue
        info = bowls.get(b.bowl_id, {})
        name = bowl_names.get(b.bowl_id, b.bowl_name)
        a, c, prob = b.top_matchups[0]
        bowl_rows.append({
            "bowl": name,
            "where": f"{b.city}, {b.state}",
            "kind": "Playoff" if b.is_cfp else "Bowl",
            "matchup": f"{a} vs {c}",
            "p": prob,
            "teams": ", ".join(t for t, _ in b.top_teams[:3]),
            "_order": (not b.is_cfp, -info.get("prestige", 0), name),
        })
        bowl_opts.append((bowl_rows[-1]["_order"], _bowl_option(b, info, name, confs)))
    bowl_rows.sort(key=lambda r: r["_order"])
    bowl_table = V.table(
        "bowls", "Bowl projections",
        [V.col("bowl", "Game", link="bowl"), V.col("where", "Where"), V.col("matchup", "Most likely matchup"),
         V.col("p", "Chance", "pct"), V.col("teams", "Most likely teams")],
        [{k: v for k, v in r.items() if k != "_order"} for r in bowl_rows],
        subtitle="Playoff games first. Click a game for its own page.", search=True, page_size=20)
    bowl_picker = V.picker(
        "bowl", "Bowl by bowl", "Game", [o for _, o in sorted(bowl_opts, key=lambda t: t[0])],
        subtitle="The likeliest teams and matchups for one game.")

    return V.page(
        title="College football playoff & bowl odds",
        summary="Every FBS team's chances to make the 12-team playoff, win the national title and land in each bowl.",
        sport="College football",
        order=1,
        updated=f"Games through {_day(meta['last_completed_game'])}",
        how=("We play out the rest of the season thousands of times using ESPN's team ratings (FPI) and "
             "the real remaining schedule, then pick the conference champions, the 12-team playoff and every "
             "bowl the way the committees do. A team's chance is how often that happened."),
        headline=headline,
        views=[every_team, bubble, *([big] if big else []), *field_views, title_bars, team_picker, bowl_table,
               bowl_picker],
    )
