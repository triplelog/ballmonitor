"""Public page: every FBS team's playoff, title and bowl odds from one season simulation, with a
page per team (#/ncaaf_bowls/team/<team>) and per bowl (#/ncaaf_bowls/bowl/<bowl>).

Built at site-build time (`ballmonitor build-site`, `ballmonitor views ncaaf_bowls`); the page
only displays these numbers.
"""

from __future__ import annotations

import datetime as dt
import json

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


def _team_option(s, team: dict, bowls: dict, bowl_names: dict) -> dict:
    intro = (f"{s.team_name} ({s.conf}) is {team.get('wins', 0)}-{team.get('losses', 0)} and projected to "
             f"go about {s.record_mean_wins:.1f}-{s.record_mean_losses:.1f} before the bowls.")

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
    out = [outcomes, wins]

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
    res = model.engine(sims).run(num_sims=sims)
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

    by_name = sorted(summaries, key=lambda s: s.team_name)
    team_picker = V.picker(
        "team", "Team by team", "Team",
        [_team_option(s, teams.get(s.team_id, {}), bowls, bowl_names) for s in by_name],
        subtitle="Every outcome for one team: playoff path, record and bowl destinations.",
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
        views=[every_team, title_bars, team_picker, bowl_table, bowl_picker],
    )
