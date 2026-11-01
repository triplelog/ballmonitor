"""Public page: this season's AP Top 25 polls and every MLB/NBA/NHL award re-counted.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views ranked_choice`); the page
only displays these numbers. Every ranking comes from the model's own predict(); the page only
counts the three methods it shows (Kemeny-Young and the other slower methods are skipped).
"""

from __future__ import annotations

import datetime as dt

from ballmonitor.core import views as V
from ballmonitor.core.config import load_config
from ballmonitor.models.ranked_choice import ballots as data

# The methods the page shows, in column order. "schulze" always picks the head-to-head
# (Condorcet) winner when there is one, so it is labelled "Head-to-head" for fans.
METHODS = ["official", "schulze", "irv"]
AWARD_SOURCES = ["mlb", "nba", "nhl"]
POLL_SOURCES = [("ap_cfb", "Football"), ("ap_mbb", "Men's basketball")]

HOW_METHODS = ("Head-to-head: a team ranks above another if more voters put it higher, the way a "
               "round-robin works. Instant runoff: the team with the fewest first-place votes is "
               "dropped and those ballots move to their next choice, until one team has a majority.")


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _week(c: dict) -> str:
    w = c.get("week", "")
    return {"pre": "Preseason", "final": "Final"}.get(w, f"Week {w}" if w.isdigit() else w)


def _counter(model):
    """The same model, counting only the methods this page shows (keeps the build fast)."""
    cfg = load_config(model.dir, None, {"compare_methods": METHODS, "outlier_count": 0})
    return type(model)(cfg, model.dir)


def _poll_table(model, contest: dict, label: str) -> dict:
    e = model.predict({"contest": contest["contest_id"]}).extras
    orders, cands = e["orders"], e["candidates"]
    places = int(e["n_places"])
    pos = {m: {c: i + 1 for i, c in enumerate(orders[m])} for m in METHODS}
    shown = {c for m in METHODS for c in orders[m][:places]}
    rows = []
    for c in sorted(shown, key=lambda c: pos["official"][c]):
        off, h2h, irv = pos["official"][c], pos["schulze"][c], pos["irv"][c]
        rows.append({"team": cands[c]["name"], "official": off, "points": cands[c]["official_points"],
                     "first": cands[c]["first"], "h2h": h2h, "irv": irv,
                     "moved": "Yes" if len({min(off, places + 1), min(h2h, places + 1),
                                            min(irv, places + 1)}) > 1 else ""})
    others = len(rows) - places
    return V.table(
        f"poll_{contest['contest_id']}", label,
        [V.col("official", "Official rank", "int"), V.col("team", "Team"),
         V.col("points", "Points", "int"), V.col("first", "First-place votes", "int"),
         V.col("h2h", "Head-to-head rank", "int"), V.col("irv", "Instant-runoff rank", "int"),
         V.col("moved", "Count changes it?")],
        rows,
        subtitle=(f"{e['n_ballots']} voters, released {_day(contest['date'])}. Official rank uses the AP's "
                  f"25-24-...-1 points."),
        note=(f"Ranks past {places} are teams that only made the top {places} under another count. "
              if others > 0 else "") + HOW_METHODS,
        search=True, page_size=25)


def _polls(model) -> tuple[dict, str]:
    d = model.dir / "data" / "ballots"
    options, newest = [], ""
    for source, sport in POLL_SOURCES:
        rows = sorted(data.contests(d, source), key=data.week_key)
        if not rows:
            continue
        season = rows[-1]["season"]
        current = [r for r in rows if r["season"] == season]
        prior = [r for r in rows if r["season"] != season and r.get("week") == "final"]
        newest = max(newest, rows[-1]["date"])
        for r in reversed(current):
            label = f"{sport} {season}, {_week(r)}"
            options.append((r["date"], V.option(label, [_poll_table(model, r, f"AP Top 25: {label}")])))
        if prior:
            r = prior[-1]
            label = f"{sport} {r['season']}, {_week(r)}"
            options.append(("", V.option(label, [_poll_table(model, r, f"AP Top 25: {label}")])))
    # newest poll of either sport first, then the rest of each sport newest first
    first = max(range(len(options)), key=lambda i: options[i][0])
    ordered = [options[first][1]] + [o for i, (_, o) in enumerate(options) if i != first]
    return V.picker(
        "polls", "This week's AP Top 25, re-counted", "Poll", ordered,
        subtitle=("The same voters' ballots counted three ways. Most of the poll holds up; "
                  "look for the rows marked \"Yes\".")), newest


def _awards(model) -> tuple[dict, dict, str]:
    d = model.dir / "data" / "ballots"
    rows = []
    for source in AWARD_SOURCES:
        for c in data.contests(d, source):
            e = model.predict({"contest": c["contest_id"]}).extras
            name = lambda m: e["candidates"][e["orders"][m][0]]["name"]  # noqa: E731
            off, h2h, irv = name("official"), name("schulze"), name("irv")
            rows.append({"award": f"{c['league']} {c['award']}", "season": c["season"],
                         "official": off, "h2h": h2h, "irv": irv,
                         "clear": "Yes" if e["condorcet_winner"] else "No",
                         "voters": e["n_ballots"], "changed": len({off, h2h, irv}) > 1})
    rows.sort(key=lambda r: (r["season"], r["award"]), reverse=True)
    seasons = sorted({r["season"][:4] for r in rows})
    cols = [V.col("award", "Award"), V.col("season", "Season"), V.col("official", "Official winner"),
            V.col("h2h", "Head-to-head winner"), V.col("irv", "Instant-runoff winner")]
    strip = lambda r, keys: {k: r[k] for k in keys}  # noqa: E731
    changed = [r for r in rows if r["changed"]]
    flips = V.table(
        "award_flips", "Awards a different count would have changed",
        cols, [strip(r, ("award", "season", "official", "h2h", "irv")) for r in changed],
        subtitle=(f"Out of {len(rows)} MLB, NBA and NHL awards with public ballots, these are the ones "
                  f"where the same ballots crown a different winner under another count."),
        note=HOW_METHODS.replace("team", "candidate"))
    every = V.table(
        "awards", "Every award, re-counted",
        cols + [V.col("clear", "Beat everyone head-to-head?"), V.col("voters", "Voters", "int")],
        [strip(r, ("award", "season", "official", "h2h", "irv", "clear", "voters")) for r in rows],
        subtitle=("\"Beat everyone head-to-head?\" is Yes when one candidate was ranked above each rival "
                  "on more ballots than not. When it is No, the voters went in a circle."),
        search=True, page_size=20)
    return flips, every, f"{seasons[0]}-{seasons[-1]}"


def page(model) -> dict:
    m = _counter(model)
    polls, newest = _polls(m)
    flips, every, span = _awards(m)
    return V.page(
        title="Polls and awards, re-counted",
        summary="What the AP Top 25 and the big MLB, NBA and NHL awards would look like if the same ballots were counted another way.",
        sport="Polls & awards",
        updated=f"AP polls through {_day(newest)}; award ballots from {span}",
        how=("We take every voter's published ballot and count it three ways: the official points, "
             "head-to-head (who more voters ranked higher in each pair) and instant runoff (drop the "
             "candidate with the fewest first-place votes and move those ballots on, round by round). "
             "Nothing about the ballots changes, only the counting."),
        views=[polls, flips, every],
    )
