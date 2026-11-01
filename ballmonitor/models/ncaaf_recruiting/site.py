"""Public page: every football program's recruiting class, one class year at a time.

Football only (basketball is research-only, see config.toml [web]). Built at site-build time
from the committed recruit files; the page only displays these numbers.
"""

from __future__ import annotations

import datetime as dt
import re

from ballmonitor.core import views as V

from .model import available_years, class_status

TOP_RECRUITS = 100  # recruits listed per class year
_SUFFIXES = {"II", "III", "IV", "V"}


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _name(raw: str) -> str:
    """'JOHN MCDONALD JR.' -> 'John Mcdonald Jr.' (the files are upper case)."""
    def word(w: str) -> str:
        if w.upper() in _SUFFIXES:
            return w.upper()
        return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), w)
    return " ".join(word(w) for w in raw.split())


def _stars(n: int) -> str:
    return "★" * int(n) if n else ""


def _year_views(model, year: int) -> tuple[list[dict], dict]:
    run = model.rank_class("ncaaf", year)
    res, status = run["result"], run["status"]
    in_progress = status.get("status") == "in_progress"

    by_team: dict[str, list] = {}
    for r in res.recruits:
        if r.committed_team:
            by_team.setdefault(r.committed_team, []).append(r)

    rows = []
    for t in res.teams:
        if t.commits_count <= 0:
            continue  # offered recruits but signed none in the data
        commits = sorted(by_team.get(t.name, []), key=lambda r: -r.score)
        top = commits[0] if commits else None
        rows.append({
            "rank": t.rank,
            "team": t.name,
            "score": round(float(t.total_score), 1),
            "commits": t.commits_count,
            "blue": sum(1 for r in commits if r.stars >= 4),
            "avg": round(float(t.avg_recruit_score), 2),
            "top": f"{_name(top.name)} ({top.position})" if top else "",
        })

    label = f"{year} class" + (" (still signing)" if in_progress else "")
    programs = V.table(
        f"programs_{year}", f"Every program's {year} class",
        [V.col("rank", "Rank", "int"), V.col("team", "Team"),
         V.col("score", "Class score", "number", decimals=1, bar=True),
         V.col("commits", "Commits", "int"), V.col("blue", "4-5 star commits", "int"),
         V.col("avg", "Avg. recruit", "number", decimals=1), V.col("top", "Best recruit")],
        rows,
        subtitle=("Commitments so far; this class is still being signed. " if in_progress else "")
        + "Click a column to sort; search for your team.",
        note="Class score adds up the recruit scores of a school's commits, with each extra commit "
             "counting a little less than the one before, so a few great recruits can beat many average ones.",
        search=True, page_size=25)

    recruits = sorted((r for r in res.recruits if r.committed_team), key=lambda r: -r.score)[:TOP_RECRUITS]
    rec_rows = [{
        "rank": i,
        "name": _name(r.name),
        "pos": r.position,
        "stars": _stars(r.stars),
        "home": r.hometown,
        "school": r.committed_team,
        "offers": r.total_offers,
        "score": round(float(r.score), 2),
    } for i, r in enumerate(recruits, 1)]
    top_recruits = V.table(
        f"recruits_{year}", f"Top {len(rec_rows)} recruits of the {year} class",
        [V.col("rank", "#", "int"), V.col("name", "Player"), V.col("pos", "Pos"), V.col("stars", "Stars"),
         V.col("home", "Hometown"), V.col("school", "Committed to"), V.col("offers", "Offers", "int"),
         V.col("score", "Recruit score", "number", decimals=1, bar=True)],
        rec_rows,
        subtitle="Ranked by how many strong schools offered them and lost out. Stars are the recruiting "
                 "services' rating, shown for comparison.",
        search=True, page_size=25)
    return [programs, top_recruits], {"label": label, "status": status}


def page(model) -> dict:
    data = model.dir / "data"
    years = sorted(available_years(data, "ncaaf"), reverse=True)
    options, fetched = [], ""
    for year in years:
        group, info = _year_views(model, year)
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
        subtitle="Pick a class year to see every program's class and that year's top recruits.")

    return V.page(
        title="College football recruiting rankings",
        summary="Every football program's recruiting class ranked by who it beat for each recruit, "
                f"{years[-1]} to {newest}.",
        sport="College football",
        order=20,
        updated=updated,
        how=("Coaches are the best talent scouts, so a recruit's score comes from the schools that "
             "offered him a scholarship and lost: the more offers, and the stronger those schools, the "
             "higher the score. School strength is worked out from every recruiting battle in the class "
             "at once. Offer lists come from On3 and are incomplete for lower-rated recruits."),
        views=[by_year],
    )
