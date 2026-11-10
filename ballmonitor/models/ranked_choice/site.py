"""Public page: this season's AP Top 25 polls and every MLB/NBA/NHL award re-counted.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views ranked_choice`); the page
only displays these numbers. Every ranking comes from the model's own predict(); the page only
counts the four methods it shows (Kemeny-Young and the other slower methods are skipped).
"""

from __future__ import annotations

import datetime as dt

from ballmonitor.core import views as V
from ballmonitor.core.config import load_config
from ballmonitor.models.ranked_choice import ballots as data
from ballmonitor.models.ranked_choice import voting as v

# The methods the page shows, in column order. "schulze" always picks the head-to-head
# (Condorcet) winner when there is one, so it is labelled "Head-to-head" for fans. "fptp"
# (first past the post, place by place) shows its ranks with ties kept (extras["ranks"]).
METHODS = ["official", "fptp", "top_two", "schulze", "irv"]
AWARD_SOURCES = ["mlb", "nba", "nhl"]
POLL_SOURCES = [("ap_cfb", "Football"), ("ap_mbb", "Men's basketball")]

HOW_METHODS = ("First past the post: No. 1 is the team with the most first-place votes; then it is "
               "taken off every ballot, each ballot's top remaining team counts as its first-place vote, "
               "and No. 2 is the most of those, and so on (teams level at a step share the place). "
               "Top-two runoff: the two teams with the most first-place votes go head to head and the one "
               "more voters ranked higher takes the place; then it is taken off and the next two meet. "
               "Head-to-head: a team ranks above another if more voters put it higher, the way a "
               "round-robin works. Instant runoff: the team with the fewest first-place votes is "
               "dropped and those ballots move to their next choice, until one team has a majority.")


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _week(c: dict) -> str:
    w = c.get("week", "")
    return {"pre": "Preseason", "final": "Final"}.get(w, f"Week {w}" if w.isdigit() else w)


def _fptp_winner(e: dict) -> str:
    """Most first-place votes; "A / B (tied)" when several share the most."""
    firsts = {c: x["first"] for c, x in e["candidates"].items()}
    best = max(firsts.values())
    top = [e["candidates"][c]["name"] for c in e["orders"]["fptp"] if firsts[c] == best]
    return top[0] if len(top) == 1 else " / ".join(top) + " (tied)"


def _counter(model):
    """The same model, counting only the methods this page shows (keeps the build fast)."""
    cfg = load_config(model.dir, None, {"compare_methods": METHODS, "outlier_count": 0})
    return type(model)(cfg, model.dir)


def _poll_table(model, contest: dict, label: str) -> tuple[dict, dict]:
    e = model.predict({"contest": contest["contest_id"]}).extras
    orders, cands = e["orders"], e["candidates"]
    places = int(e["n_places"])
    pos = {m: {c: i + 1 for i, c in enumerate(orders[m])} for m in METHODS}
    shown = {c for m in METHODS for c in orders[m][:places]}
    fptp = e["ranks"]["fptp"]           # place by place, ties shared
    rows = []
    for c in sorted(shown, key=lambda c: pos["official"][c]):
        off, h2h, irv = pos["official"][c], pos["schulze"][c], pos["irv"][c]
        rows.append({"team": cands[c]["name"], "official": off, "points": cands[c]["official_points"],
                     "first": cands[c]["first"], "fptp": fptp[c], "top2": pos["top_two"][c], "h2h": h2h, "irv": irv,
                     "moved": "Yes" if len({min(off, places + 1), min(h2h, places + 1),
                                            min(irv, places + 1)}) > 1 else ""})
    others = len(rows) - places
    cap = lambda r, k: min(r[k], places + 1)  # noqa: E731
    stats = {"top": rows[0]["team"], "h2h_top": cands[orders["schulze"][0]]["name"],
             "irv_top": cands[orders["irv"][0]]["name"], "fptp_top": _fptp_winner(e),
             "top2_top": cands[orders["top_two"][0]]["name"],
             "h2h_moves": sum(1 for r in rows if cap(r, "h2h") != cap(r, "official")),
             "irv_moves": sum(1 for r in rows if cap(r, "irv") != cap(r, "official"))}
    return V.table(
        f"poll_{contest['contest_id']}", label,
        [V.col("official", "Official rank", "int"), V.col("team", "Team"),
         V.col("points", "Points", "int", hidden=True), V.col("first", "First-place votes", "int"),
         V.col("fptp", "First-past-the-post rank", "int"), V.col("top2", "Top-two runoff rank", "int"),
         V.col("h2h", "Head-to-head rank", "int"), V.col("irv", "Instant-runoff rank", "int"),
         V.col("moved", "Count changes it?")],
        rows,
        subtitle=(f"{e['n_ballots']} voters, released {_day(contest['date'])}. Official rank uses the AP's "
                  f"25-24-...-1 points."),
        note=(f"Ranks past {places} are teams that only made the top {places} under another count. "
              if others > 0 else "") + "\"Count changes it?\" compares head-to-head and instant runoff "
             "with the official rank. " + HOW_METHODS,
        search=True, page_size=25), stats


def _teams(n: int) -> str:
    return "1 team" if n == 1 else f"{n} teams"


def _poll_intro(st: dict) -> str:
    """e.g. "Head-to-head moves 9 teams, instant runoff 6. No. 1 Miami (FL) stays No. 1 both ways." """
    text = f"Head-to-head moves {_teams(st['h2h_moves'])}, instant runoff {_teams(st['irv_moves'])}."
    keeps = [m for m, k in (("head-to-head", "h2h_top"), ("instant runoff", "irv_top")) if st[k] == st["top"]]
    if len(keeps) == 2:
        text += f" No. 1 {st['top']} stays No. 1 both ways."
    else:
        flips = [f"{st[k]} under {m}" for m, k in (("head-to-head", "h2h_top"), ("instant runoff", "irv_top"))
                 if st[k] != st["top"]]
        text += " No. 1 would be " + " and ".join(flips) + f", not {st['top']}."
    if st["fptp_top"] != st["top"]:
        text += f" Most first-place votes: {st['fptp_top']}."
    if st["top2_top"] != st["top"]:
        text += f" A top-two runoff would make {st['top2_top']} No. 1."
    return text


def _polls(model) -> tuple[dict, str]:
    d = model.dir / "data" / "ballots"
    options, newest = [], ""
    stats: dict[str, tuple[str, dict]] = {}
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
            tbl, st = _poll_table(model, r, f"AP Top 25: {label}")
            stats[label] = (f"{sport.lower()}, {_week(r)}", st)
            options.append((r["date"], V.option(label, [tbl], intro=_poll_intro(st))))
        if prior:
            r = prior[-1]
            label = f"{sport} {r['season']}, {_week(r)}"
            tbl, st = _poll_table(model, r, f"AP Top 25: {label}")
            options.append(("", V.option(label, [tbl], intro=_poll_intro(st))))
    # newest poll of either sport first, then the rest of each sport newest first
    first = max(range(len(options)), key=lambda i: options[i][0])
    ordered = [options[first][1]] + [o for i, (_, o) in enumerate(options) if i != first]
    lead_label = ordered[0]["label"]
    which, lead = stats[lead_label]
    if lead["h2h_top"] == lead["top"]:
        headline = (f"This week's AP Top 25 ({which}): a head-to-head count "
                    f"would move {_teams(lead['h2h_moves'])}, but not No. 1 {lead['top']}.")
    else:
        headline = (f"This week's AP Top 25 ({which}): a head-to-head count "
                    f"would move {_teams(lead['h2h_moves'])} and make {lead['h2h_top']} No. 1 instead of "
                    f"{lead['top']}.")
    return V.picker(
        "polls", "This week's AP Top 25, re-counted", "Poll", ordered,
        subtitle=("The same voters' ballots counted five ways. Most of the poll holds up; "
                  "look for the rows marked \"Yes\".")), newest, headline


def _awards(model) -> tuple[dict, dict, str]:
    d = model.dir / "data" / "ballots"
    rows = []
    for source in AWARD_SOURCES:
        for c in data.contests(d, source):
            e = model.predict({"contest": c["contest_id"]}).extras
            name = lambda m: e["candidates"][e["orders"][m][0]]["name"]  # noqa: E731
            off, h2h, irv, fptp, top2 = name("official"), name("schulze"), name("irv"), _fptp_winner(e), name("top_two")
            rows.append({"award": f"{c['league']} {c['award']}", "season": c["season"],
                         "official": off, "fptp": fptp, "top2": top2, "h2h": h2h, "irv": irv,
                         "clear": "Yes" if e["condorcet_winner"] else "No",
                         "voters": e["n_ballots"], "changed": len({off, h2h, irv, fptp, top2}) > 1})
    rows.sort(key=lambda r: (r["season"], r["award"]), reverse=True)
    seasons = sorted({r["season"][:4] for r in rows})
    cols = [V.col("award", "Award"), V.col("season", "Season"), V.col("official", "Official winner"),
            V.col("fptp", "Most first-place votes"), V.col("top2", "Top-two runoff winner"),
            V.col("h2h", "Head-to-head winner"), V.col("irv", "Instant-runoff winner")]
    strip = lambda r, keys: {k: r[k] for k in keys}  # noqa: E731
    changed = [r for r in rows if r["changed"]]
    flips = V.table(
        "award_flips", "Awards a different count would have changed",
        cols, [strip(r, ("award", "season", "official", "fptp", "top2", "h2h", "irv")) for r in changed],
        subtitle=(f"Out of {len(rows)} MLB, NBA and NHL awards with public ballots, these are the ones "
                  f"where the same ballots crown a different winner under another count."),
        note=HOW_METHODS.replace("team", "candidate"))
    every = V.table(
        "awards", "Every award, re-counted",
        cols + [V.col("clear", "Beat everyone head-to-head?"), V.col("voters", "Voters", "int", hidden=True)],
        [strip(r, ("award", "season", "official", "fptp", "top2", "h2h", "irv", "clear", "voters")) for r in rows],
        subtitle=("\"Beat everyone head-to-head?\" is Yes when one candidate was ranked above each rival "
                  "on more ballots than not. When it is No, the voters went in a circle."),
        search=True, page_size=20)
    return flips, every, f"{seasons[0]}-{seasons[-1]}"


def page(model) -> dict:
    m = _counter(model)
    polls, newest, headline = _polls(m)
    flips, every, span = _awards(m)
    return V.page(
        title="Polls and awards, re-counted",
        summary="What the AP Top 25 and the big MLB, NBA and NHL awards would look like if the same ballots were counted another way.",
        sport="Polls & awards",
        headline=headline,
        updated=f"AP polls through {_day(newest)}; award ballots from {span}",
        how=("We take every voter's published ballot and count it five ways: the official points, "
             "first past the post (first-place votes only, place by place), a top-two runoff, head-to-head (who more voters ranked higher in each pair) and instant runoff (drop the "
             "candidate with the fewest first-place votes and move those ballots on, round by round). "
             "Nothing about the ballots changes, only the counting."),
        views=[polls, flips, every],
    )
