"""Build college_towns.csv, geo_college.csv and college_titles.csv; point colleges.csv at the towns.

    python -m ballmonitor.games.triple_play.places.collect_colleges [--offline]

Same fetching rules as collect_other.py (only /wiki/ pages, one at a time with a pause,
honest User-Agent, cached in data/raw/). Judgement calls are in data/NOTES_COLLEGE.md.

What is parsed vs. hand-entered:
- college towns: the list of schools (and their campus city/state) comes from colleges()
  in collect_other.py, i.e. the parsed conference member tables. The town each campus with
  no metro belongs to (id, fan name) is hand-entered in TOWNS; every such school must be
  in exactly one town, or the build stops. Notre Dame (football Independent) is added.
- geo_college: flags are hand-entered (no college town is on an ocean/Gulf coast or a Great
  Lake); capitals are checked against the parsed *List of capitals in the United States*.
- titles: champions are parsed from the BCS / CFP title-game tables, the men's tournament
  "titles by school" table, the women's tournament champions table and the College World
  Series results table. School -> campus metro/town/state is hand-entered (CAMPUS) for
  schools outside the four conferences; every parsed champion must be mapped.
"""
from __future__ import annotations

import argparse
import csv
import re

from ballmonitor.games.triple_play.places.collect_other import (
    DATA, capitals, clean, colleges, grid, page, table_after, url, write, GEO_PAGES)

TODAY_YEAR = 2026

# town id -> (name as fans say it, state id, city name used for the capital check, short names)
TOWNS = {
    "tuscaloosa": ("Tuscaloosa", "alabama", "Tuscaloosa", ["Alabama"]),
    "auburn": ("Auburn", "alabama", "Auburn", ["Auburn"]),
    "fayetteville": ("Fayetteville", "arkansas", "Fayetteville", ["Arkansas"]),
    "gainesville": ("Gainesville", "florida", "Gainesville", ["Florida"]),
    "tallahassee": ("Tallahassee", "florida", "Tallahassee", ["Florida State"]),
    "athens": ("Athens", "georgia", "Athens", ["Georgia"]),
    "lexington": ("Lexington", "kentucky", "Lexington", ["Kentucky"]),
    "louisville": ("Louisville", "kentucky", "Louisville", ["Louisville"]),
    "baton_rouge": ("Baton Rouge", "louisiana", "Baton Rouge", ["LSU"]),
    "oxford": ("Oxford", "mississippi", "Oxford", ["Ole Miss"]),
    "starkville": ("Starkville", "mississippi", "Starkville", ["Mississippi State"]),
    "columbia_mo": ("Columbia, MO", "missouri", "Columbia", ["Missouri"]),
    "columbia_sc": ("Columbia, SC", "south_carolina", "Columbia", ["South Carolina"]),
    "clemson": ("Clemson", "south_carolina", "Clemson", ["Clemson"]),
    "knoxville": ("Knoxville", "tennessee", "Knoxville", ["Tennessee"]),
    "college_station": ("College Station", "texas", "College Station", ["Texas A&M"]),
    "waco": ("Waco", "texas", "Waco", ["Baylor"]),
    "lubbock": ("Lubbock", "texas", "Lubbock", ["Texas Tech"]),
    "champaign": ("Champaign", "illinois", "Champaign", ["Illinois"]),
    "bloomington": ("Bloomington", "indiana", "Bloomington", ["Indiana"]),
    "west_lafayette": ("West Lafayette", "indiana", "West Lafayette", ["Purdue"]),
    "south_bend": ("South Bend", "indiana", "South Bend", ["Notre Dame"]),
    "iowa_city": ("Iowa City", "iowa", "Iowa City", ["Iowa"]),
    "ames": ("Ames", "iowa", "Ames", ["Iowa State"]),
    "ann_arbor": ("Ann Arbor", "michigan", "Ann Arbor", ["Michigan"]),
    "east_lansing": ("East Lansing", "michigan", "East Lansing", ["Michigan State"]),
    "lincoln": ("Lincoln", "nebraska", "Lincoln", ["Nebraska"]),
    "eugene": ("Eugene", "oregon", "Eugene", ["Oregon"]),
    "state_college": ("State College", "pennsylvania", "State College", ["Penn State"]),
    "madison": ("Madison", "wisconsin", "Madison", ["Wisconsin"]),
    "winston_salem": ("Winston-Salem", "north_carolina", "Winston-Salem", ["Wake Forest"]),
    "charlottesville": ("Charlottesville", "virginia", "Charlottesville", ["Virginia"]),
    "blacksburg": ("Blacksburg", "virginia", "Blacksburg", ["Virginia Tech"]),
    "syracuse": ("Syracuse", "new_york_state", "Syracuse", ["Syracuse"]),
    "tucson": ("Tucson", "arizona", "Tucson", ["Arizona"]),
    "provo": ("Provo", "utah", "Provo", ["BYU"]),
    "boulder": ("Boulder", "colorado", "Boulder", ["Colorado"]),
    "lawrence": ("Lawrence", "kansas", "Lawrence", ["Kansas"]),
    "manhattan_ks": ("Manhattan, KS", "kansas", "Manhattan", ["Kansas State"]),
    "stillwater": ("Stillwater", "oklahoma", "Stillwater", ["Oklahoma State"]),
    "morgantown": ("Morgantown", "west_virginia", "Morgantown", ["West Virginia"]),
}

# Near-misses worth recording in coast_note (none of these counts as a coast/Great Lake).
TOWN_COAST_NOTES = {
    "tallahassee": "about 20 miles inland from the Gulf (Apalachee Bay); Leon County has no coastline",
    "gainesville": "inland, midway between the Atlantic and the Gulf",
    "baton_rouge": "on the Mississippi River, about 80 miles from the Gulf",
    "south_bend": "about 15 miles from Lake Michigan; St. Joseph County does not touch the lake",
    "syracuse": "about 30 miles from Lake Ontario; Onondaga Lake is not a Great Lake",
    "madison": "on Lakes Mendota and Monona (not Great Lakes)",
    "east_lansing": "inland Michigan",
    "ann_arbor": "inland Michigan; about 35 miles from Lake Erie",
}
TOWN_CAPITAL_NOTES = {
    "east_lansing": "East Lansing is a separate city next to Lansing (the capital); not counted as the capital",
}

NOTRE_DAME = {"school": "University of Notre Dame", "short_name": "Notre Dame", "conference": "Independent",
              "campus_city": "Notre Dame", "metro_id": "south_bend", "state_id": "indiana",
              "source": url("Notre_Dame_Fighting_Irish_football")}


def town_rows(college_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Fill blank metro_ids with the town id; return (colleges rows, town rows)."""
    by_short = {s: tid for tid, (_, _, _, shorts) in TOWNS.items() for s in shorts}
    seen = set()
    out = []
    for r in college_rows:
        r = dict(r)
        if not r["metro_id"]:
            tid = by_short.get(r["short_name"])
            if not tid:
                raise SystemExit(f"{r['short_name']}: campus not in a metro and not in TOWNS")
            if TOWNS[tid][1] != r["state_id"]:
                raise SystemExit(f"{r['short_name']}: state {r['state_id']} != town {tid}")
            r["metro_id"] = tid
            seen.add(r["short_name"])
        elif r["short_name"] in by_short:
            raise SystemExit(f"{r['short_name']} is already in metro {r['metro_id']}; remove it from TOWNS")
        out.append(r)
    if not any(r["conference"] == "Independent" for r in out):
        out.append(dict(NOTRE_DAME))
    unused = set(by_short) - seen
    if unused:
        raise SystemExit(f"TOWNS lists schools not parsed with a blank metro: {sorted(unused)}")
    src = {r["metro_id"]: r["source"] for r in out if r["metro_id"] in TOWNS and r["conference"] != "Independent"}
    towns = []
    for tid, (name, sid, _, shorts) in sorted(TOWNS.items()):
        schools = sorted({r["school"] for r in out if r["metro_id"] == tid})
        towns.append({"id": tid, "name": name, "state_id": sid, "country": "USA",
                      "schools": "; ".join(schools), "source": src[tid] + (
                          " " + NOTRE_DAME["source"] if tid == "south_bend" else "")})
    return out, towns


def geo_rows(offline: bool) -> list[dict]:
    caps = capitals(offline)
    src = " ".join(url(t) for t in GEO_PAGES.values() if t != GEO_PAGES["borders_canada"]) + " " + url(
        "List_of_capitals_in_the_United_States")
    rows = []
    for tid, (name, sid, city, _) in sorted(TOWNS.items()):
        state = sid.replace("_state", "").replace("_", " ").title()
        is_cap = caps[sid] == city
        note = (f"{city} is the capital of {state}" if is_cap else f"capital of {state} is {caps[sid]}")
        if tid in TOWN_CAPITAL_NOTES:
            note += "; " + TOWN_CAPITAL_NOTES[tid]
        rows.append({"id": tid, "coast_atlantic": "N", "coast_pacific": "N", "coast_gulf": "N",
                     "great_lakes": "N", "borders_canada": "", "capital": "Y" if is_cap else "N",
                     "capital_note": note, "coast_note": TOWN_COAST_NOTES.get(tid, ""), "source": src})
    return rows


# ---------------------------------------------------------------------------- titles

# Champion name as printed on the pages -> short_name in colleges.csv (aliases).
ALIASES = {"Miami (FL)": "Miami", "Pittsburgh": "Pitt"}

# Champions that are not SEC/Big Ten/ACC/Big 12/Notre Dame (2026-27): (metro_id or "", state_id).
# Hand-entered campus locations (judgement; see NOTES_COLLEGE.md).
CAMPUS = {
    "UConn": ("", "connecticut"),                     # Storrs
    "CCNY": ("new_york", "new_york_state"),           # Manhattan, New York City
    "Georgetown": ("washington", ""),                 # Washington, D.C.: not a state (as titles.csv)
    "Holy Cross": ("", "massachusetts"),              # Worcester (own MSA)
    "La Salle": ("philadelphia", "pennsylvania"),
    "Villanova": ("philadelphia", "pennsylvania"),     # Villanova, PA (Philadelphia MSA)
    "Loyola Chicago": ("chicago", "illinois"),
    "Marquette": ("milwaukee", "wisconsin"),
    "San Francisco": ("bay_area", "california"),
    "UNLV": ("las_vegas", "nevada"),
    "UTEP": ("", "texas"),                            # El Paso (champion as Texas Western, 1966)
    "Wyoming": ("", "wyoming"),                       # Laramie
    "Oregon State": ("", "oregon"),                   # Corvallis
    "Louisiana Tech": ("", "louisiana"),              # Ruston
    "Old Dominion": ("", "virginia"),                 # Norfolk (no listed metro)
    "Cal State Fullerton": ("los_angeles", "california"),  # Orange County, LA metro per DATA_SPEC
    "Pepperdine": ("los_angeles", "california"),      # Malibu
    "Rice": ("houston", "texas"),
    "Fresno State": ("", "california"),
    "Wichita State": ("", "kansas"),
    "Coastal Carolina": ("", "south_carolina"),       # Conway
}


def _team(cell: str) -> str:
    """'1 Miami (FL)' / 'USC *' / 'Texas (2)' / 'UConn (1, 1–0)' -> school name."""
    s = re.sub(r"^\d+\s+", "", cell.strip())
    s = s.replace("*", "").replace("^", "").strip()
    s = re.sub(r"\s*\((\d+|\d+,\s*[\d–-]+)\)$", "", s)
    return s.strip()


def champions(offline: bool) -> tuple[list[tuple], list[str]]:
    """[(sport, year, school, source)], notes on skipped/vacated years."""
    out, notes = [], []
    # football: BCS (1998-2013 seasons), CFP (2014-)
    for title in ("BCS_National_Championship_Game", "College_Football_Playoff_National_Championship"):
        t = table_after(page(title, offline), "Game results", "Season")
        for r in grid(t)[1:]:
            if not r[0].isdigit() or not r[3].strip():
                continue
            year = int(r[0])
            if "*" in r[3]:
                notes.append(f"football {year}: {_team(r[3])} title vacated (BCS) - no row")
                continue
            out.append(("football", year, _team(r[3]), url(title)))
    # men's basketball: titles by school (no year-by-year table on the page)
    title = "NCAA_Division_I_men's_basketball_tournament"
    t = table_after(page(title, offline), "Titles by school", "Team")
    for r in grid(t)[1:]:
        for y in re.findall(r"\d{4}\s*\*?", r[2]):
            if "*" in y:
                notes.append(f"mbb {y[:4]}: {r[0]} title vacated (NCAA) - no row")
                continue
            out.append(("mbb", int(y[:4]), r[0], url(title)))
    # women's basketball
    title = "NCAA_Division_I_women's_basketball_tournament"
    t = table_after(page(title, offline), "champions", "Year")
    for r in grid(t)[1:]:
        if not r[0][:4].isdigit() or not r[1].strip():
            continue
        if "cancel" in r[1].lower():
            notes.append(f"wbb {r[0][:4]}: {r[1]}")
            continue
        out.append(("wbb", int(r[0][:4]), _team(r[1]), url(title)))
    # baseball
    title = "College_World_Series"
    t = table_after(page(title, offline), "Results", "Year")
    for r in grid(t)[1:]:
        if not r[0][:4].isdigit() or not r[1].strip():
            continue
        if "cancel" in r[1].lower():
            notes.append(f"baseball {r[0][:4]}: {r[1]}")
            continue
        out.append(("baseball", int(r[0][:4]), _team(r[1]), url(title)))
    return out, notes


RANGES = {"football": (1998, 2025), "mbb": (1939, 2026), "wbb": (1982, 2026), "baseball": (1947, 2026)}


def title_rows(offline: bool, college_rows: list[dict]) -> tuple[list[dict], list[str]]:
    loc = {r["short_name"]: (r["metro_id"], r["state_id"]) for r in college_rows}
    champs, notes = champions(offline)
    rows = []
    for sport, year, school, src in champs:
        lo, hi = RANGES[sport]
        if not lo <= year <= hi:
            continue
        key = ALIASES.get(school, school)
        if key in loc:
            metro, sid = loc[key]
        elif key in CAMPUS:
            metro, sid = CAMPUS[key]
        else:
            raise SystemExit(f"{sport} {year}: unmapped champion {school!r} - add it to CAMPUS")
        rows.append({"sport": sport, "year": year, "school": school, "metro_id": metro, "state_id": sid,
                     "source": src})
    rows.sort(key=lambda r: (list(RANGES).index(r["sport"]), r["year"]))
    # one champion per sport-year; every gap must be explained by a note
    for sport, (lo, hi) in RANGES.items():
        years = [r["year"] for r in rows if r["sport"] == sport]
        dup = {y for y in years if years.count(y) > 1}
        if dup:
            raise SystemExit(f"{sport}: more than one champion in {sorted(dup)}")
        explained = {int(n.split()[1][:4]) for n in notes if n.startswith(sport + " ")}
        if sport == "mbb":
            explained.add(2020)  # the men's page lists titles by school only; 2020 was canceled
        missing = set(range(lo, hi + 1)) - set(years) - explained
        if missing:
            raise SystemExit(f"{sport}: no champion parsed for {sorted(missing)}")
    if not any(n.startswith("mbb 2020") for n in notes):
        notes.append("mbb 2020: tournament canceled (COVID-19 pandemic)")
    return rows, notes


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="use only cached pages in data/raw/")
    a = ap.parse_args(argv)
    cols, towns = town_rows(colleges(a.offline))
    write("colleges", ["school", "short_name", "conference", "campus_city", "metro_id", "state_id", "source"], cols)
    write("college_towns", ["id", "name", "state_id", "country", "schools", "source"], towns)
    write("geo_college", ["id", "coast_atlantic", "coast_pacific", "coast_gulf", "great_lakes", "borders_canada",
                          "capital", "capital_note", "coast_note", "source"], geo_rows(a.offline))
    titles, notes = title_rows(a.offline, cols)
    write("college_titles", ["sport", "year", "school", "metro_id", "state_id", "source"], titles)
    for n in notes:
        print("  " + n)


if __name__ == "__main__":
    main()
