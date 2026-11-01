"""Public page: next year's predicted top-3 age-group times at real races.

Built at site-build time from data/division_panel.csv (real RunSignup results; division place
times and field sizes only, no runner names). The model's examples are placeholders and are
not used here. Every number comes from model.predict() on one division's earlier editions.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict

from ballmonitor.core import views as V
from ballmonitor.core.units import METERS_PER_MILE, distance_label, format_time, parse_distance

_PREFIX = re.compile(r"^\s*(?:\d{4}\s+|\d+(?:st|nd|rd|th)\s+(?:annual\s+)?)", re.I)
_GENDER = {"M": "Men", "F": "Women"}


def _race_name(raw: str) -> str:
    """Drop edition counters ("16th Annual", "2025 ") so one name covers every year."""
    name = raw.strip().strip("*").strip()
    for _ in range(2):
        name = _PREFIX.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" -*")
    return name if len(name) <= 70 else name[:67].rstrip() + "..."


def _sort_key(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _division_label(gender: str, age_min: int, age_max: int) -> str:
    g = _GENDER.get(gender, gender)
    if age_min <= 0 and age_max >= 90:
        return f"{g} overall"
    if age_max >= 90:
        return f"{g} {age_min}+"
    return f"{g} {age_min}-{age_max}"


def _load(path) -> dict:
    """{(race_id, distance): {"name", "state", "divisions": {division: {meta, editions[]}}}}"""
    races: dict = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (r["race_id"], r["distance"])
            race = races.setdefault(key, {"names": {}, "state": r["state"], "divisions": {}})
            race["names"][int(r["year"])] = r["race_name"]
            div = race["divisions"].setdefault(r["division"], {
                "gender": r["gender"], "age_min": int(r["age_min"]), "age_max": int(r["age_max"]),
                "editions": []})
            times = [float(r[f"t{i}"]) for i in range(1, 6) if r[f"t{i}"]]
            if times:
                div["editions"].append({"year": int(r["year"]), "field_size": int(r["field_size"]),
                                        "times": times})
    return races


def _history(div: dict) -> list[dict]:
    return [{"year": e["year"], "field_size": e["field_size"], "times": e["times"]}
            for e in sorted(div["editions"], key=lambda e: e["year"])]


def page(model) -> dict:
    p = model.params
    races = _load(model.dir / "data" / "division_panel.csv")
    latest_year = max(y for r in races.values() for y in r["names"])
    min_editions = int(p.site_min_editions)
    max_gap = int(p.site_max_years_since)

    picked = []
    for (race_id, dist), race in races.items():
        years = sorted(race["names"])
        if len(years) < min_editions or latest_year - years[-1] > max_gap:
            continue
        if not all(f"{g} Open" in race["divisions"] for g in ("M", "F")):
            continue
        picked.append(((race_id, dist), race, years))

    options, index_rows = [], []
    for (race_id, dist), race, years in picked:
        last = years[-1]
        target_year = last + 1
        meters = parse_distance(dist)
        name = _race_name(race["names"][last])
        dist_lbl = distance_label(meters)
        open_hist = {g: _history(race["divisions"][f"{g} Open"]) for g in ("M", "F")}

        rows, winners = [], {}
        divs = [d for d in race["divisions"].values() if any(e["year"] == last for e in d["editions"])]
        divs.sort(key=lambda d: (d["gender"] != "F", d["age_min"] > 0 or d["age_max"] < 90, d["age_min"]))
        for d in divs:
            inputs = {
                "race_name": name, "distance": dist, "gender": d["gender"],
                "age_min": d["age_min"], "age_max": d["age_max"], "target_year": target_year,
                "overall_awards_count": 0, "history": _history(d),
            }
            is_open = d["age_min"] <= 0 and d["age_max"] >= 90
            if not is_open and d["gender"] in open_hist:
                inputs["open_history"] = open_hist[d["gender"]]
            pred = model.predict(inputs)
            t = pred.extras["final_times"]
            lo, hi = pred.primary.interval
            field = int(pred.inputs["Expected field size"])
            if is_open:
                winners[d["gender"]] = t[0]
            rows.append({
                "division": _division_label(d["gender"], d["age_min"], d["age_max"]),
                "field": field,
                "t1": t[0],
                # A place nobody usually fills (field of 1-2) is left blank rather than guessed.
                "t2": t[1] if field >= 2 else None, "t3": t[2] if field >= 3 else None,
                "range": f"{format_time(lo)} – {format_time(hi)}",
                "pace": t[0] / (meters / METERS_PER_MILE),
            })

        label = f"{name} ({dist_lbl}{', ' + race['state'] if race['state'] else ''})"
        options.append((_sort_key(label), len(years), V.option(label, [V.table(
            f"board_{race_id}_{dist}", f"{name}: {target_year} predictions",
            [V.col("division", "Age group"), V.col("field", "Usual runners", "int"),
             V.col("t1", "1st", "time"), V.col("t2", "2nd", "time"), V.col("t3", "3rd", "time"),
             V.col("range", "1st place likely between"), V.col("pace", "1st place pace / mile", "time")],
            rows,
            subtitle=(f"{dist_lbl}, {len(years)} years of results ({years[0]}-{last}). "
                      f"The times we expect the three fastest runners in each age group to run in {target_year}."),
            note="Usual runners: how many finish in that age group in a typical recent year "
                 "(2nd and 3rd are left blank when that is fewer than 2 or 3). "
                 f"\"Likely between\" should hold {p.interval_level:.0%} of the time."
                 " Times include everyone, so where overall winners get their own awards,"
                 " age-group awards can go a little slower.",
            search=True)])))
        index_rows.append({
            "race": name, "state": race["state"] or "-", "distance": dist_lbl,
            "years": len(years), "last": str(last),
            "women": winners.get("F"), "men": winners.get("M"),
        })

    options.sort(key=lambda o: o[0])
    index_rows.sort(key=lambda r: _sort_key(r["race"]))
    most_years = max(range(len(options)), key=lambda i: options[i][1])
    index = V.table(
        "races", "Every race",
        [V.col("race", "Race"), V.col("state", "State"), V.col("distance", "Distance"),
         V.col("years", "Years of results", "int"), V.col("last", "Latest results"),
         V.col("women", "Women's winner", "time"), V.col("men", "Men's winner", "time")],
        index_rows,
        subtitle="Predicted winning times at the next running of each race. Pick a race above for every age group.",
        search=True, page_size=25)

    picker = V.picker(
        "by_race", "Age-group times by race", "Race", [o for _, _, o in options], default=most_years,
        subtitle="Pick a race to see the times likely to win 1st, 2nd and 3rd in every age group next time.")

    return V.page(
        title="Race age-group award times",
        summary=(f"What it will probably take to win or place in your age group at {len(options)} "
                 "local road races, based on their past results."),
        sport="Running",
        updated=f"Race results through {latest_year}",
        how=("For each age group we look at the top finishing times in earlier years of the same race, "
             "counting recent years and bigger groups more, and adjust for how many runners usually show up. "
             "Small age groups also lean on the race's overall winning times, scaled for age. "
             "The predictions assume a normal day; a hot race or a new course can move them a lot."),
        views=[picker, index],
    )
