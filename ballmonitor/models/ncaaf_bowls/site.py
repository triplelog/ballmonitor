"""Public page: every FBS team's playoff, title and bowl odds from one season simulation.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views ncaaf_bowls`); the page
only displays these numbers.
"""

from __future__ import annotations

import datetime as dt
import json

from ballmonitor.core import views as V


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def page(model) -> dict:
    data = model.dir / "data"
    meta = json.loads((data / "meta.json").read_text())
    teams = {t["id"]: t for t in json.loads((data / "teams.json").read_text())}
    bowl_names = {b["id"]: b.get("espn_name") or b["name"] for b in json.loads((data / "bowls.json").read_text())}
    bowl_info = {b["id"]: b for b in json.loads((data / "bowls.json").read_text())}

    sims = int(model.params.site_simulations)
    res = model.engine(sims).run(num_sims=sims)
    summaries = sorted(res.team_summaries.values(), key=lambda s: (-s.p_cfp, -s.national_champ_prob, s.team_name))

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
            "bye": s.p_cfp_bye,
            "conf_title": s.p_conf_champ,
            "title": s.national_champ_prob,
            "bowl_eligible": s.p_eligible,
            "bowl": bowl_names.get(bowl_id, "") if bowl_p >= 0.05 else "",
            "bowl_p": bowl_p if bowl_p >= 0.05 else None,
        })

    every_team = V.table(
        "teams", "Every FBS team",
        [V.col("team", "Team"), V.col("conf", "Conf"), V.col("record", "Record"),
         V.col("wins", "Proj. wins", "number"),
         V.col("cfp", "Playoff", "pct", bar=True), V.col("conf_title", "Conf. title", "pct"),
         V.col("title", "National title", "pct", decimals=1), V.col("bowl", "Most likely bowl")],
        rows, subtitle="Chances for the rest of the 2026 season. Click a column to sort; search for your team.",
        search=True, page_size=25,
        note=f"Projected wins: wins so far plus expected wins in the rest of the regular season. Based on {sims:,} simulated seasons.")

    contenders = [s for s in summaries if s.national_champ_prob >= 0.005]
    contenders.sort(key=lambda s: -s.national_champ_prob)
    title_bars = V.bar(
        "title_odds", "Who wins the national title?",
        [{"label": s.team_name, "sub": s.conf, "value": s.national_champ_prob} for s in contenders[:16]],
        fmt="pct", decimals=1, subtitle="The teams with the best chance to win the College Football Playoff.")

    bowl_rows = []
    for b in res.bowl_summaries.values():
        if not b.top_matchups:
            continue
        a, c, prob = b.top_matchups[0]
        info = bowl_info.get(b.bowl_id, {})
        bowl_rows.append({
            "bowl": bowl_names.get(b.bowl_id, b.bowl_name),
            "where": f"{b.city}, {b.state}",
            "kind": "Playoff" if b.is_cfp else "Bowl",
            "matchup": f"{a} vs {c}",
            "p": prob,
            "teams": ", ".join(name for name, _ in b.top_teams[:3]),
            "prestige": info.get("prestige", 0),
        })
    bowl_rows.sort(key=lambda r: (r["kind"] != "Playoff", -r["prestige"], r["bowl"]))
    bowls = V.table(
        "bowls", "Bowl projections",
        [V.col("bowl", "Game"), V.col("where", "Where"), V.col("matchup", "Most likely matchup"),
         V.col("p", "Chance", "pct"), V.col("teams", "Most likely teams")],
        [{k: v for k, v in r.items() if k != "prestige"} for r in bowl_rows],
        subtitle="Playoff games first. Matchup chances are low because so many pairings are possible.",
        search=True, page_size=20)

    return V.page(
        title="College football playoff & bowl odds",
        summary="Every FBS team's chances to make the 12-team playoff, win the national title and land in each bowl.",
        sport="College football",
        order=1,
        updated=f"Games through {_day(meta['last_completed_game'])}",
        how=("We play out the rest of the season thousands of times using ESPN's team ratings (FPI) and "
             "the real remaining schedule, then pick the conference champions, the 12-team playoff and every "
             "bowl the way the committees do. A team's chance is how often that happened."),
        views=[every_team, title_bars, bowls],
    )
