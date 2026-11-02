"""Public page: every football program's recruiting class, one class year at a time: overall rank,
rank within its conference, the industry (star-rating) consensus rank, and offense / defense /
run / pass unit ranks.

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


def _year_views(model, year: int, conf_of: dict[str, str]) -> tuple[list[dict], dict]:
    run = model.rank_class("ncaaf", year)
    res, status = run["result"], run["status"]
    in_progress = status.get("status") == "in_progress"
    units = PositionalRankingEngine().evaluate(res).by_name
    industry = consensus(model.dir / "data", year)

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
        [rank("rank", "Rank"), V.col("team", "Team"), V.col("conf", "Conference"),
         rank("conf_rank", "Rank in conf."), rank("industry", "Industry rank"),
         V.col("commits", "Commits", "int"), V.col("blue", "4-5 star commits", "int"),
         V.col("score", "Class score", "number", decimals=1, bar=True)],
        overall,
        subtitle=("Commitments so far; this class is still being signed. " if in_progress else "")
        + "Rank: our ranking. Industry rank: the recruiting services' consensus, based on star ratings. "
          "Search for a team or a conference.",
        note="Conferences are 2026 FBS conferences (blank for FCS and other schools), also for older classes. "
             "Class score adds up the recruit scores of a school's commits, with each extra commit counting "
             "a little less than the one before.",
        search=True, page_size=25)
    sides_table = V.table(
        f"units_{year}", f"{year} class by side of the ball",
        [rank("rank", "Overall"), V.col("team", "Team"), rank("off", "Offense"), rank("def", "Defense"),
         rank("run_o", "Run offense"), rank("pass_o", "Pass offense"), rank("run_d", "Run defense"),
         rank("pass_d", "Pass defense")],
        sides,
        subtitle="Where each class ranks for offense and defense, and for the running and passing game on each side.",
        note="Each recruit counts toward the units his position plays in: a quarterback or receiver mostly "
             "toward the passing game, a running back or offensive lineman toward both, and so on.",
        search=True, page_size=25)
    return [overall_table, sides_table], {"label": label, "status": status}


def page(model) -> dict:
    data = model.dir / "data"
    years = sorted(available_years(data, "ncaaf"), reverse=True)
    conf_of = conferences()
    options, fetched = [], ""
    for year in years:
        group, info = _year_views(model, year, conf_of)
        options.append(V.option(info["label"], group))
        if info["status"].get("status") == "in_progress" and info["status"].get("fetched"):
            fetched = fetched or info["status"]["fetched"]

    newest = years[0]
    status = class_status(data, "ncaaf", newest)
    if status.get("status") == "in_progress" and fetched:
        updated = f"{newest} commitments as of {_day(fetched)}; {years[1]} and earlier classes are final"
    else:
        updated = f"Classes {years[-1]}-{newest}, final"

    by_year = V.picker(
        "by_year", "Recruiting classes by year", "Class", options,
        subtitle="Pick a class year: every program's overall, conference and industry rank, then its "
                 "offense, defense, run and pass ranks.")

    return V.page(
        title="College football recruiting rankings",
        summary="Every football program's recruiting class ranked overall, within its conference and by "
                f"side of the ball, {years[-1]} to {newest}.",
        fill={"first_year": years[-1], "last_year": newest},
        sport="College football",
        order=20,
        updated=updated,
        how=("Coaches are the best talent scouts, so a recruit's score comes from the schools that "
             "offered him a scholarship and lost: the more offers, and the stronger those schools, the "
             "higher the score. School strength is worked out from every recruiting battle in the class "
             "at once. Offer lists come from On3 and are incomplete for lower-rated recruits. The industry "
             "rank is On3's consensus of the four recruiting services' star ratings, for comparison."),
        views=[by_year],
    )
