"""Public page: every football program's recruiting class, one class year at a time: overall rank,
rank within its conference, the industry (star-rating) consensus rank, and offense / defense /
run / pass unit ranks; and a page per FBS program (/ncaaf_recruiting/team/<team>/) with its class
rank in every year.

Football only (basketball is research-only, see config.toml [web]). Built at site-build time
from the committed recruit files; the page only displays these numbers.
"""

from __future__ import annotations

import csv
import datetime as dt
import json

from ballmonitor.core import registry
from ballmonitor.core import views as V

from .model import available_years, class_status
from .src.position_model import PositionalRankingEngine

# ESPN team names (ncaaf_bowls/data/teams.json, which holds the 2026 conferences) that the
# recruit files spell differently.
ALIASES = {"Hawaii": "Hawai'i", "Middle Tennessee": "Middle Tennessee State", "Pittsburgh": "Pitt",
           "Sam Houston": "Sam Houston State", "UConn": "Connecticut", "UMass": "Massachusetts"}
# the quick-filter buttons above a class table: these conferences first, then the rest by name
CONF_ORDER = ("SEC", "Big Ten", "Big 12", "ACC")


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def conferences() -> dict[str, str]:
    """Program -> its 2026 FBS conference (recruit-file spelling); empty if the bowls data is missing."""
    try:
        teams = json.loads((registry.model_dir("ncaaf_bowls") / "data" / "teams.json").read_text())
    except (KeyError, OSError):
        return {}
    return {ALIASES.get(t["name"], t["name"]): t["conf"] for t in teams}


def consensus(data_dir, year: int) -> dict[str, int]:
    """Program -> On3 industry consensus class rank (built from the services' star ratings)."""
    path = data_dir / "benchmarks" / "consensus_team_rankings.csv"
    if not path.exists():
        return {}
    with path.open(newline="") as fh:
        return {ALIASES.get(r["team"], r["team"]): int(r["rank"])
                for r in csv.DictReader(fh) if r["sport"] == "ncaaf" and int(r["year"]) == year}


def on3_slugs(data_dir) -> dict[str, str]:
    """Program -> On3's team slug (fetch.merge_slugs), for links to its class page there."""
    path = data_dir / "reference" / "on3_team_slugs.csv"
    if not path.exists():
        return {}
    with path.open(newline="") as fh:
        return {ALIASES.get(r["team"], r["team"]): r["slug"] for r in csv.DictReader(fh) if r["sport"] == "ncaaf"}


def on3_class_url(slug: str | None, year: int) -> str | None:
    return f"https://www.on3.com/college/{slug}/football/{year}/industry-comparison-commits/" if slug else None


def _conf_buttons(rows: list[dict]) -> list[str]:
    present = {r["conf"] for r in rows if r["conf"]}
    return [c for c in CONF_ORDER if c in present] + sorted(present - set(CONF_ORDER))


def _year_views(model, year: int, conf_of: dict[str, str]) -> tuple[list[dict], dict]:
    run = model.rank_class("ncaaf", year)
    res, status = run["result"], run["status"]
    in_progress = status.get("status") == "in_progress"
    units = PositionalRankingEngine().evaluate(res).by_name
    industry = consensus(model.dir / "data", year)
    slugs = on3_slugs(model.dir / "data")

    teams = [t for t in res.teams if t.commits_count > 0]  # offered recruits but signed none: skip
    stars: dict[str, int] = {}
    for r in res.recruits:
        if r.committed_team and r.stars >= 4:
            stars[r.committed_team] = stars.get(r.committed_team, 0) + 1

    # rank within conference by class score (FBS programs only)
    conf_rank: dict[str, int] = {}
    for conf in set(conf_of.values()) - {"Independent"}:
        members = sorted((t for t in teams if conf_of.get(t.name) == conf), key=lambda t: t.rank)
        conf_rank.update({t.name: i for i, t in enumerate(members, 1)})

    overall, sides = [], []
    for t in teams:
        u = units.get(t.name.lower())
        overall.append({
            "rank": t.rank,
            "team": t.name,
            "conf": conf_of.get(t.name, ""),
            "conf_rank": conf_rank.get(t.name),
            "industry": industry.get(t.name),
            "industry_url": on3_class_url(slugs.get(t.name), year) if industry.get(t.name) else None,
            "commits": t.commits_count,
            "blue": stars.get(t.name, 0),
            "score": round(float(t.total_score), 1),
        })
        sides.append({
            "rank": t.rank,
            "team": t.name,
            "off": u.offense_rank if u else None,
            "def": u.defense_rank if u else None,
            "run_o": u.run_offense_rank if u else None,
            "pass_o": u.pass_offense_rank if u else None,
            "run_d": u.run_defense_rank if u else None,
            "pass_d": u.pass_defense_rank if u else None,
        })

    label = f"{year} class" + (" (still signing)" if in_progress else "")

    def rank(key: str, name: str) -> dict:
        return V.col(key, name, "int", low_first=True)

    overall_table = V.table(
        f"programs_{year}", f"{year} class rankings",
        [rank("rank", "Rank"), V.col("team", "Team", link="team"), V.col("conf", "Conference"),
         rank("conf_rank", "Rank in conf."), V.col("industry", "Industry rank", "int", low_first=True, url="industry_url"),
         V.col("commits", "Commits", "int"), V.col("blue", "4-5 star commits", "int"),
         V.col("score", "Class score", "number", decimals=1, bar=True)],
        overall,
        subtitle=("Commitments so far (this class is still signing). " if in_progress else "")
        + "Our rank is based on scholarship offers; Industry rank is the recruiting services' star-rating consensus. "
          "Filter by conference or click any team to see its year-by-year history.",
        note="Conferences reflect 2026 FBS alignment (blank for FCS and other schools), even for earlier classes. "
             "Class score totals a school's commits, best first, with each extra commit counting a little less.",
        search=True, page_size=25, quick_filters=("conf", _conf_buttons(overall)),
        show_title=False)   # the class dropdown right above says which year (owner, 2026-11-23)
    sides_table = V.table(
        f"units_{year}", f"{year} class by side of the ball",
        [rank("rank", "Overall"), V.col("team", "Team", link="team"), rank("off", "Offense"), rank("def", "Defense"),
         rank("run_o", "Run offense"), rank("pass_o", "Pass offense"), rank("run_d", "Run defense"),
         rank("pass_d", "Pass defense")],
        sides,
        subtitle="How each class stacks up on offense, defense, and the run and pass games.",
        note="Each recruit contributes to the units tied to his position—quarterbacks and receivers mostly to the "
             "passing game, running backs and linemen to both, and so on—using the same diminishing-weight sum as the overall class score.",
        search=True, page_size=25)
    top = sorted(teams, key=lambda t: t.rank)
    leaders = [t.name for t in top[:3]]
    counts: dict[str, int] = {}
    for t in top[:25]:
        if conf_of.get(t.name) and conf_of[t.name] != "Independent":
            counts[conf_of[t.name]] = counts.get(conf_of[t.name], 0) + 1
    by_conf = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    intro = (f"No. 1: {leaders[0]}, then {leaders[1]} and {leaders[2]}. Top-25 classes: "
             + ", ".join(f"{c} {n}" for c, n in by_conf[:4]) + ".")
    return [overall_table, sides_table], {"label": label, "status": status, "leaders": leaders,
                                           "in_progress": in_progress, "intro": intro, "rows": overall}


def _team_option(name: str, conf: str, history: list[tuple[int, dict, bool]]) -> dict:
    """One program's classes, newest first: our rank, its rank in the conference, the industry
    rank and how far apart the two are, as a table and a line chart (No. 1 at the top)."""
    rows = []
    for year, r, in_progress in history:
        gap = r["industry"] - r["rank"] if r["industry"] else None
        rows.append({"year": f"{year}" + (" (still signing)" if in_progress else ""), "rank": r["rank"],
                     "conf_rank": r["conf_rank"], "industry": r["industry"], "industry_url": r.get("industry_url"),
                     "gap": gap, "commits": r["commits"],
                     "blue": r["blue"]})
    table = V.table(
        f"classes_{V.slug(name)}", "Class rank by year",
        [V.col("year", "Class"), V.col("rank", "Rank", "int", low_first=True),
         V.col("conf_rank", "Rank in conf.", "int", low_first=True),
         V.col("industry", "Industry rank", "int", low_first=True, url="industry_url"),
         V.col("gap", "Ours vs. industry", "signed", decimals=0), V.col("commits", "Commits", "int"),
         V.col("blue", "4-5 star commits", "int")],
        rows,
        subtitle="Ours vs. industry: how many places higher we rank the class than the star-rating consensus does; "
                 "negative means lower.",
        note="Conference ranks use 2026 conference alignment across every year.")
    old = sorted(history)   # oldest first, for the chart
    ours = [(y, r["rank"]) for y, r, _ in old]
    industry = [(y, r["industry"]) for y, r, _ in old if r["industry"]]
    worst = max([rk for _, rk in ours] + [rk for _, rk in industry])
    chart = V.line(
        f"trend_{V.slug(name)}", "Class rank over the years",
        [V.series("Our rank", ours)] + ([V.series("Industry rank", industry)] if industry else []),
        x_label="Class", y_label="Rank (No. 1 at the top)", y_fmt="int", y_min=1, y_max=max(worst, 10), y_reverse=True,
        x_ticks=[(y, str(y)) for y, _ in ours if y % 2 == old[-1][0] % 2])
    newest_year, newest, newest_open = history[0]
    best = min(history, key=lambda h: (h[1]["rank"], -h[0]))
    avg = sum(r["rank"] for _, r, _ in history) / len(history)
    intro = (f"{name}{f' ({conf})' if conf else ''}: No. {newest['rank']} in {newest_year}"
             + (" so far" if newest_open else "")
             + f"; best class No. {best[1]['rank']} ({best[0]}); average rank {avg:.0f} over {len(history)} classes.")
    return V.option(name, [chart, table], intro=intro)


def page(model) -> dict:
    data = model.dir / "data"
    years = sorted(available_years(data, "ncaaf"), reverse=True)
    conf_of = conferences()
    options, fetched, infos = [], "", {}
    history: dict[str, list[tuple[int, dict, bool]]] = {}   # FBS program -> its classes, newest first
    for year in years:
        group, info = _year_views(model, year, conf_of)
        infos[year] = info
        for r in info["rows"]:
            if r["conf"]:
                history.setdefault(r["team"], []).append((year, r, info["in_progress"]))
        options.append(V.option(info["label"], group, intro=info["intro"]))
        if info["status"].get("status") == "in_progress" and info["status"].get("fetched"):
            fetched = fetched or info["status"]["fetched"]

    newest = years[0]
    status = class_status(data, "ncaaf", newest)
    if status.get("status") == "in_progress" and fetched:
        updated = f"{newest} class as of {_day(fetched)}"   # short: it's a chip on the home card
    else:
        updated = f"Classes {years[-1]}-{newest}, final"

    lead = infos[newest]["leaders"]
    headline = (f"{lead[0]} has the No. 1 {newest} class"
                + (" so far" if infos[newest]["in_progress"] else "")
                + f"; {lead[1]} and {lead[2]} are next.")

    by_year = V.picker(
        "by_year", "Recruiting classes by year", "Class", options, find=False,
        subtitle="Choose a class year to see overall, conference, and industry rankings, plus offense and defense breakdowns."
                 + (f" The {newest} class is still signing; {years[1]} and earlier are final."
                    if status.get("status") == "in_progress" else ""))

    team_picker = V.picker(
        "team", "Team by team", "Team",
        [_team_option(name, conf_of.get(name, ""), h) for name, h in sorted(history.items())],
        subtitle="See how one FBS program's classes have ranked over time compared to the industry consensus.",
        default=sorted(history).index(lead[0]) if lead[0] in history else 0)

    return V.page(
        title="College football recruiting rankings",
        summary=f"Every college football recruiting class from {years[-1]} to {newest}, ranked overall, by conference, "
                "and by offense and defense.",
        fill={"first_year": years[-1], "last_year": newest},
        sport="College football",
        order=1,
        updated=updated,
        headline=headline,
        how=("Instead of relying on star ratings, we look at which coaches wanted each player. A recruit's score is "
             "based on the schools that offered him a scholarship and didn't land him—the more offers, and the "
             "stronger those programs, the higher his value. Program strength is solved across every recruiting "
             "battle in the class at the same time. Offer lists come from On3 (and can be incomplete for lower-rated "
             "players). We show On3's consensus industry rank alongside ours for comparison. These cover high school "
             "recruiting classes only, not transfer portal additions."),
        views=[by_year, team_picker],
    )
