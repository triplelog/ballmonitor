"""Public page: the 2026 NCAA baseball and softball tournaments (Selection-eve odds vs what
happened), final 2026 power ratings and how title chances moved during the season.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views college_diamond`); the
page only displays these numbers.
"""

from __future__ import annotations

import datetime as dt

from ballmonitor.core import registry
from ballmonitor.core import views as V
from ballmonitor.models.college_diamond import data as D
from ballmonitor.models.college_diamond.model import selection_date

SEASON = 2026
NAMES = {"baseball": "Baseball", "softball": "Softball"}
WS = {"baseball": "Omaha (College World Series)", "softball": "Oklahoma City (Women's College World Series)"}
WS_SHORT = {"baseball": "Omaha", "softball": "the WCWS"}
STAGE = {1: "Lost in a regional", 2: "Lost in a super regional", 3: "Lost at {ws}",
         4: "Lost in the finals", 5: "Won the title"}
TREND_TEAMS = 6


def _day(d: dt.date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _records(sport: str) -> dict[str, str]:
    w: dict[str, list[int]] = {}
    for g in D.season_games(sport, SEASON):
        for t, m in ((g.home, g.margin), (g.away, -g.margin)):
            r = w.setdefault(t, [0, 0, 0])
            r[0 if m > 0 else 1 if m < 0 else 2] += 1
    return {t: f"{a}-{b}" + (f"-{c}" if c else "") for t, (a, b, c) in w.items()}


def _sport_views(model, trend_model, sport: str) -> tuple[list[dict], dt.date]:
    sel = selection_date(sport, SEASON)
    ex = model.predict({"sport": sport, "season": SEASON, "as_of": "selection"}).extras
    info, odds = ex["team_info"], ex["teams"]
    tour = D.load_tournaments()[sport][str(SEASON)]
    field = tour["field"]
    ws = WS_SHORT[sport]
    # Baseball: exact national seeds 1-16. 2026 softball data only has seed groups
    # (1 = national seeds 1-4, 5 = 5-8, ...), so the page shows the group number.
    exact = sport == "baseball" or not tour.get("hosts_approximate", True) and len(
        {f["national_seed"] for f in field.values() if f.get("national_seed")}) == 16
    seed_label = "National seed" if exact else "Seed group"

    rows = []
    for t, f in field.items():
        s = odds[t]
        rows.append({
            "team": info[t]["name"], "conf": info[t]["conference"],
            "nseed": (f["national_seed"] if exact else (f["national_seed"] - 1) // 4 + 1)
            if f.get("national_seed") else None,
            "super": s["regional"], "ws": s["super"], "title": s["title"],
            "result": STAGE[min(f["reached"], 5)].format(ws=ws),
        })
    rows.sort(key=lambda r: (-r["title"], -r["super"], r["team"]))
    tourney = V.table(
        f"{sport}_tourney", f"2026 NCAA {sport} tournament: the odds vs what happened",
        [V.col("team", "Team"), V.col("conf", "Conference"), V.col("nseed", seed_label, "int"),
         V.col("super", "Reach super regionals", "pct"), V.col("ws", f"Reach {ws}", "pct"),
         V.col("title", "Win the title", "pct", decimals=1, bar=True), V.col("result", "What happened")],
        rows,
        subtitle=(f"The 64 teams in the field, with the chances we gave them on the eve of "
                  f"Selection Day ({_day(sel - dt.timedelta(days=1))}). Click a column to sort; search for a team."),
        search=True, page_size=25,
        note=("The chances also allow for the team possibly missing the field or being placed in a "
              "different regional, since the bracket was not known yet."
              + ("" if exact else " Seed group: 1 = national seeds 1-4, 2 = seeds 5-8, 3 = 9-12, "
                 "4 = 13-16 (the exact order within a group is not in our data).")))

    ratings = model.final_ratings(sport, SEASON)
    records = _records(sport)
    order = sorted(ratings, key=lambda t: -ratings[t])
    power = V.table(
        f"{sport}_ratings", f"Final 2026 {sport} power ratings",
        [V.col("rank", "Rank", "int"), V.col("team", "Team"), V.col("conf", "Conference"),
         V.col("record", "Record"), V.col("rating", "Rating", "signed", decimals=1, bar=True)],
        [{"rank": i, "team": info[t]["name"], "conf": info[t]["conference"], "record": records.get(t, "0-0"),
          "rating": ratings[t]} for i, t in enumerate(order, 1)],
        subtitle=("Every Division I team after the last game of 2026. Rating = how many runs better (or worse) "
                  "than an average Division I team it would be on a neutral field."),
        search=True, page_size=25,
        note="Record counts games against Division I opponents, postseason included.")

    eventual = sorted(field, key=lambda t: (-field[t]["reached"], -odds[t]["title"]))[:TREND_TEAMS]
    dates = []
    for md in trend_model.params.site_trend_dates:
        d = dt.date.fromisoformat(f"{SEASON}-{md}")
        if d < sel:
            dates.append(d)
    points: dict[str, list[tuple[float, float]]] = {t: [] for t in eventual}
    for d in dates:
        tx = trend_model.predict({"sport": sport, "season": SEASON, "as_of": d.isoformat()}).extras["teams"]
        for t in eventual:
            points[t].append((round((d - sel).days / 7), tx[t]["title"]))
    for t in eventual:
        points[t].append((0, odds[t]["title"]))
    trend = V.line(
        f"{sport}_trend", "Title chances over the season",
        [V.series(info[t]["name"], points[t]) for t in eventual],
        x_label="Weeks before Selection Day", y_label="Chance to win the title", x_fmt="int", y_fmt="pct",
        y_min=0,
        subtitle=(f"The {TREND_TEAMS} teams that went furthest in the 2026 tournament. 0 = the eve of "
                  f"Selection Day ({_day(sel - dt.timedelta(days=1))}); "
                  + ", ".join(f"{round((d - sel).days / 7)} = {d:%b} {d.day}" for d in dates) + "."),
        note=f"Earlier dates use {int(trend_model.params.site_trend_simulations):,} simulated seasons, so small wiggles are noise.")
    return [tourney, power, trend], sel


def page(model) -> dict:
    trend_model = registry.load_model(
        "college_diamond", overrides={"simulations": int(model.params.site_trend_simulations)})
    options, last = [], []
    for sport in ("baseball", "softball"):
        vs, sel = _sport_views(model, trend_model, sport)
        options.append(V.option(NAMES[sport], vs))
        last.append(max(g.day for g in D.season_games(sport, SEASON)))
    pick = V.picker("sport", "2026 NCAA baseball & softball", "Sport", options,
                    subtitle="Pick a sport: the tournament odds, the final power ratings and the title race.")
    return V.page(
        title="College baseball & softball: 2026 tournament odds and ratings",
        summary="How likely each team was to reach Omaha or Oklahoma City and win it all, next to what really happened.",
        sport="College baseball & softball",
        updated=f"2026 season, final (games through {_day(max(last))})",
        how=("Every Division I team gets a rating from its scores, adjusted for who it played and where. "
             "We then play out the rest of the season thousands of times: conference tournaments, a "
             "selection committee that leans on the RPI, and the NCAA bracket. A team's chance is how "
             "often it got that far."),
        views=[pick],
    )
