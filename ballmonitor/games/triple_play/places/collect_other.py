"""Build colleges.csv, events.csv and geo.csv for the places pack (see DATA_SPEC.md).

    python -m ballmonitor.games.triple_play.places.collect_other [--offline]

Pages come only from https://en.wikipedia.org/wiki/<title> (robots.txt allows /wiki/;
never /w/ or /api/), one request at a time with a pause, an honest User-Agent and no
personal identifiers. Every page is cached in data/raw/ and re-used, so re-running
is free; --offline fails instead of downloading.

What is parsed vs. hand-entered:
- colleges: membership, campus city and state are parsed from each conference's
  "members" table. The metro assignment and short name are hand-entered per school
  (judgement; see NOTES_OTHER.md). An unknown school stops the build.
- events: Super Bowl venues/cities/years, Olympic host list (rowspan-expanded table)
  and each Games' main stadium, and World Cup venues are parsed; the mapping from
  host city to metro/state id is hand-entered and every parsed city must be mapped.
- geo: hand-entered (coast/lake/border/capital flags), checked against the parsed
  US state-capital and Canadian province tables and against the text of the cited
  coast/border pages (a warning is printed if a name isn't mentioned there).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RAW = DATA / "raw"
WIKI = "https://en.wikipedia.org/wiki/"
UA = "ballmonitor-games/0.1 (personal, non-commercial)"
PAUSE_S = 2.5
TODAY = date(2026, 10, 27)  # data cut-off for "has happened"

_last_fetch = 0.0


def url(title: str) -> str:
    return WIKI + urllib.parse.quote(title, safe="(),'_")


def page(title: str, offline: bool = False) -> BeautifulSoup:
    """Return the parsed /wiki/<title> page, downloading it once into data/raw/."""
    global _last_fetch
    path = RAW / (title.replace("/", "_") + ".html")
    if not path.exists():
        if offline:
            raise SystemExit(f"offline and not cached: {title}")
        wait = PAUSE_S - (time.time() - _last_fetch)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url(title), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
        _last_fetch = time.time()
        RAW.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        print(f"  downloaded {title} ({len(body):,} bytes)", file=sys.stderr)
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def clean(s: str) -> str:
    s = re.sub(r"\[[^\]]*\]", "", s)          # footnote markers
    s = re.sub(r"\s+([,)])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    return re.sub(r"\s+", " ", s).strip()


def snake(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def state_id(name: str) -> str:
    """State/province id: snake_case, except the two that clash with metro ids."""
    sid = snake(name)
    return {"new_york": "new_york_state", "washington": "washington_state"}.get(sid, sid)


def grid(table) -> list[list[str]]:
    """Table → rows of cleaned cell text with rowspan/colspan expanded."""
    out: list[list[str]] = []
    pending: dict[int, tuple[int, str]] = {}  # col -> (rows left, text)
    for tr in table.find_all("tr"):
        row: list[str] = []
        cells = tr.find_all(["th", "td"], recursive=False)
        col = 0
        it = iter(cells)
        while True:
            if col in pending:
                left, text = pending[col]
                row.append(text)
                pending[col] = (left - 1, text)
                if left - 1 == 0:
                    del pending[col]
                col += 1
                continue
            c = next(it, None)
            if c is None:
                break
            text = clean(c.get_text(" ", strip=True))
            span = int(c.get("colspan", 1) or 1)
            rs = int(c.get("rowspan", 1) or 1)
            for _ in range(span):
                if rs > 1:
                    pending[col] = (rs - 1, text)
                row.append(text)
                col += 1
        while col in pending:  # trailing spanned cells
            left, text = pending[col]
            row.append(text)
            pending[col] = (left - 1, text)
            if left - 1 == 0:
                del pending[col]
            col += 1
        out.append(row)
    return out


def table_after(soup, heading_text: str, header_first: str):
    """First wikitable whose first header cell starts with `header_first`, under a heading."""
    for t in soup.select("table.wikitable"):
        h = t.find_previous(["h2", "h3", "h4"])
        first = clean(t.find("tr").find(["th", "td"]).get_text(" ", strip=True))
        if h and heading_text.lower() in h.get_text(" ", strip=True).lower() and first.startswith(header_first):
            return t
    raise SystemExit(f"table not found: {heading_text!r} / {header_first!r}")


def write(name: str, fields: list[str], rows: list[dict]) -> None:
    path = DATA / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path.relative_to(HERE)} ({len(rows)} rows)", file=sys.stderr)


# --------------------------------------------------------------------------- colleges

CONFERENCES = {  # conference -> (page title, heading of the members table)
    "SEC": ("Southeastern_Conference", "Current members"),
    "Big Ten": ("Big_Ten_Conference", "Full members"),
    "ACC": ("Atlantic_Coast_Conference", "Full members"),
    "Big 12": ("Big_12_Conference", "Full members"),
}

# Wikipedia article of the institution -> (short name, metro_id or "").
# Hand-entered judgement: a campus gets a metro only if it lies in that metro as fans
# would say it (the city or its core suburbs / the same metropolitan statistical area).
SCHOOLS = {
    # SEC
    "University_of_Alabama": ("Alabama", ""),
    "University_of_Arkansas": ("Arkansas", ""),
    "Auburn_University": ("Auburn", ""),
    "University_of_Florida": ("Florida", ""),
    "University_of_Georgia": ("Georgia", ""),
    "University_of_Kentucky": ("Kentucky", ""),
    "Louisiana_State_University": ("LSU", ""),
    "University_of_Mississippi": ("Ole Miss", ""),
    "Mississippi_State_University": ("Mississippi State", ""),
    "University_of_Missouri": ("Missouri", ""),
    "University_of_Oklahoma": ("Oklahoma", "oklahoma_city"),        # Norman, in the OKC MSA
    "University_of_South_Carolina": ("South Carolina", ""),
    "University_of_Tennessee": ("Tennessee", ""),
    "University_of_Texas_at_Austin": ("Texas", "austin"),
    "Texas_A&M_University": ("Texas A&M", ""),
    "Vanderbilt_University": ("Vanderbilt", "nashville"),
    # Big Ten
    "University_of_Illinois_Urbana-Champaign": ("Illinois", ""),
    "Indiana_University_Bloomington": ("Indiana", ""),
    "University_of_Iowa": ("Iowa", ""),
    "University_of_Maryland,_College_Park": ("Maryland", "washington"),   # College Park, DC suburbs
    "University_of_Michigan": ("Michigan", ""),                           # Ann Arbor: own MSA
    "Michigan_State_University": ("Michigan State", ""),
    "University_of_Minnesota": ("Minnesota", "minneapolis_st_paul"),
    "University_of_Nebraska–Lincoln": ("Nebraska", ""),
    "Northwestern_University": ("Northwestern", "chicago"),             # Evanston borders Chicago
    "Ohio_State_University": ("Ohio State", "columbus"),
    "University_of_Oregon": ("Oregon", ""),
    "Pennsylvania_State_University": ("Penn State", ""),
    "Purdue_University": ("Purdue", ""),
    "Rutgers_University–New_Brunswick": ("Rutgers", "new_york"),        # Middlesex Co., NY MSA
    "University_of_California,_Los_Angeles": ("UCLA", "los_angeles"),
    "University_of_Southern_California": ("USC", "los_angeles"),
    "University_of_Washington": ("Washington", "seattle"),
    "University_of_Wisconsin-Madison": ("Wisconsin", ""),
    # ACC
    "Clemson_University": ("Clemson", ""),
    "Duke_University": ("Duke", "raleigh"),                              # Triangle (see notes)
    "University_of_North_Carolina_at_Chapel_Hill": ("North Carolina", "raleigh"),  # Triangle
    "North_Carolina_State_University": ("NC State", "raleigh"),
    "Wake_Forest_University": ("Wake Forest", ""),
    "University_of_Virginia": ("Virginia", ""),
    "Georgia_Tech": ("Georgia Tech", "atlanta"),
    "Florida_State_University": ("Florida State", ""),
    "University_of_Miami": ("Miami", "miami"),                           # Coral Gables
    "Virginia_Tech": ("Virginia Tech", ""),
    "Boston_College": ("Boston College", "boston"),                      # Chestnut Hill
    "University_of_Pittsburgh": ("Pitt", "pittsburgh"),
    "Syracuse_University": ("Syracuse", ""),
    "University_of_Notre_Dame": ("Notre Dame", ""),
    "University_of_Louisville": ("Louisville", ""),
    "Southern_Methodist_University": ("SMU", "dallas_fort_worth"),
    "University_of_California,_Berkeley": ("California", "bay_area"),
    "Stanford_University": ("Stanford", "bay_area"),
    # Big 12
    "University_of_Arizona": ("Arizona", ""),
    "Arizona_State_University": ("Arizona State", "phoenix"),            # Tempe
    "Baylor_University": ("Baylor", ""),
    "Brigham_Young_University": ("BYU", ""),                             # Provo: own MSA
    "University_of_Central_Florida": ("UCF", "orlando"),
    "University_of_Cincinnati": ("Cincinnati", "cincinnati"),
    "University_of_Colorado_Boulder": ("Colorado", ""),                  # Boulder: own MSA
    "University_of_Houston": ("Houston", "houston"),
    "Iowa_State_University": ("Iowa State", ""),
    "University_of_Kansas": ("Kansas", ""),                              # Lawrence: own MSA
    "Kansas_State_University": ("Kansas State", ""),
    "Oklahoma_State_University": ("Oklahoma State", ""),
    "Texas_Christian_University": ("TCU", "dallas_fort_worth"),
    "Texas_Tech_University": ("Texas Tech", ""),
    "University_of_Utah": ("Utah", "salt_lake_city"),
    "West_Virginia_University": ("West Virginia", ""),
}


def colleges(offline: bool) -> list[dict]:
    rows = []
    for conf, (title, heading) in CONFERENCES.items():
        t = table_after(page(title, offline), heading, "Institution")
        for tr in t.find_all("tr")[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            a = cells[0].find("a")
            key = urllib.parse.unquote(a["href"].rsplit("/", 1)[-1]) if a else ""
            if key not in SCHOOLS:
                raise SystemExit(f"{conf}: unmapped school {key!r} — add it to SCHOOLS")
            short, metro = SCHOOLS[key]
            name = re.sub(r"\s*\([^)]*\)$", "", clean(cells[0].get_text(" ", strip=True)))
            loc = clean(cells[1].get_text(" ", strip=True)).replace(" - ", "–")
            city, state = (x.strip() for x in loc.rsplit(",", 1))
            state = re.sub(r"\s*\(.*\)$", "", state)
            rest = re.search(r"\(([^)]*)\)$", loc)  # "Los Angeles, California (Westwood)"
            if rest:
                city = f"{city} ({rest.group(1)})"
            rows.append({"school": name, "short_name": short, "conference": conf, "campus_city": city,
                         "metro_id": metro, "state_id": state_id(state), "source": url(title)})
    return rows


# --------------------------------------------------------------------------- events

# Host city as printed on the pages -> metro id ("" = not one of the metros).
SB_CITY_METRO = {
    "Los Angeles": "los_angeles", "Pasadena": "los_angeles", "Inglewood": "los_angeles",
    "Miami": "miami", "Miami Gardens": "miami",
    "New Orleans": "new_orleans", "Houston": "houston",
    "Pontiac": "detroit", "Detroit": "detroit",
    "Stanford": "bay_area", "Santa Clara": "bay_area",
    "Tampa": "tampa_bay", "San Diego": "san_diego",
    "Minneapolis": "minneapolis_st_paul", "Atlanta": "atlanta",
    "Tempe": "phoenix", "Glendale": "phoenix",
    "Jacksonville": "jacksonville", "Indianapolis": "indianapolis",
    "Arlington": "dallas_fort_worth", "East Rutherford": "new_york",
    "Paradise": "las_vegas",
}

# (year, season) -> (metro_id, state_id). The year/season list itself is parsed.
OLYMPIC_HOSTS = {
    (1904, "summer"): ("st_louis", "missouri"),
    (1932, "winter"): ("", "new_york_state"),       # Lake Placid
    (1932, "summer"): ("los_angeles", "california"),
    (1960, "winter"): ("", "california"),           # Squaw Valley (now Olympic Valley / Palisades Tahoe)
    (1976, "summer"): ("montreal", "quebec"),
    (1980, "winter"): ("", "new_york_state"),       # Lake Placid
    (1984, "summer"): ("los_angeles", "california"),
    (1988, "winter"): ("calgary", "alberta"),
    (1996, "summer"): ("atlanta", "georgia"),
    (2002, "winter"): ("salt_lake_city", "utah"),
    (2010, "winter"): ("vancouver", "british_columbia"),
}
ORDINAL_SEASON = {"S": "summer", "W": "winter"}

# World Cup host city label (before any parenthesis) -> (metro_id, state_id); None = not US/Canada.
WC_CITY = {
    "Mexico City": None, "Monterrey": None, "Guadalajara": None,
    "New York/New Jersey": ("new_york", "new_jersey"),
    "Dallas": ("dallas_fort_worth", "texas"),
    "Los Angeles": ("los_angeles", "california"),
    "Kansas City": ("kansas_city", "missouri"),       # Arrowhead Stadium, Kansas City, Missouri
    "San Francisco Bay Area": ("bay_area", "california"),
    "Houston": ("houston", "texas"),
    "Philadelphia": ("philadelphia", "pennsylvania"),
    "Atlanta": ("atlanta", "georgia"),
    "Seattle": ("seattle", "washington_state"),
    "Miami": ("miami", "florida"),
    "Boston": ("boston", "massachusetts"),
    "Vancouver": ("vancouver", "british_columbia"),
    "Toronto": ("toronto", "ontario"),
}


def super_bowls(offline: bool) -> list[dict]:
    title = "List_of_Super_Bowl_champions"
    t = table_after(page(title, offline), "Results", "Game")
    rows = []
    for r in grid(t)[1:]:
        game, when, venue, city = r[0], r[1], r[6], r[7]
        venue = re.sub(r"\s*\(\d+\)$", "", venue)
        city = re.sub(r"\s*\(\d+\)$", "", city)
        name, state = (x.strip() for x in city.rsplit(",", 1))
        if name not in SB_CITY_METRO:
            raise SystemExit(f"Super Bowl {game}: unmapped city {city!r}")
        year = int(re.search(r"\b(19|20)\d\d\b", when).group(0))
        rows.append({"event": "super_bowl", "year": year, "metro_id": SB_CITY_METRO[name],
                     "state_id": state_id(state), "venue": venue, "city": name,
                     "edition": game.split()[0], "source": url(title)})
    if len(rows) != 60 or rows[-1]["edition"] != "LX":
        raise SystemExit(f"expected Super Bowls I-LX, got {len(rows)} ending {rows[-1]['edition']}")
    return rows


def olympic_stadium(title: str, offline: bool) -> str:
    ib = page(title, offline).select_one("table.infobox")
    for tr in ib.find_all("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td and clean(th.get_text(" ", strip=True)) in ("Stadium", "Main venue"):
            return clean(td.get_text(" ", strip=True))
    raise SystemExit(f"no stadium in infobox: {title}")


def olympics(offline: bool) -> list[dict]:
    title = "List_of_Olympic_Games_host_cities"
    t = table_after(page(title, offline), "Host cities", "Year")
    g = grid(t)
    h = g[0]
    i_city, i_country, i_open = h.index("City or area"), h.index("Country"), h.index("Opening ceremony")
    i_sw = (h.index("Summer"), h.index("Winter"))
    rows = []
    for r in g[1:]:
        if len(r) <= i_open or r[i_country] not in ("United States", "Canada"):
            continue
        code = next((r[i] for i in i_sw if re.match(r"^[SW]\d{3}\b", r[i])), None)
        if not code:
            continue
        season = ORDINAL_SEASON[code[0]]
        opening = re.search(r"\d{1,2} \w+ (\d{4})", r[i_open])
        year = int(opening.group(1))
        months = "January February March April May June July August September October November December".split()
        d, m = opening.group(0).split()[:2]
        if date(year, months.index(m) + 1, int(d)) > TODAY:
            continue  # not yet held (LA 2028, Utah 2034)
        if (year, season) not in OLYMPIC_HOSTS:
            raise SystemExit(f"unmapped Olympics {year} {season} {r[3]}")
        metro, sid = OLYMPIC_HOSTS[(year, season)]
        games = f"{year}_{season.capitalize()}_Olympics"
        rows.append({"event": f"olympics_{season}", "year": year, "metro_id": metro, "state_id": sid,
                     "venue": olympic_stadium(games, offline), "city": r[i_city], "edition": games.replace("_", " "),
                     "source": url(games)})
    if sorted(OLYMPIC_HOSTS) != sorted((x["year"], x["event"][9:]) for x in rows):
        raise SystemExit("parsed Olympic host list differs from OLYMPIC_HOSTS")
    return rows


def world_cup(offline: bool) -> list[dict]:
    title = "2026_FIFA_World_Cup"
    t = table_after(page(title, offline), "Venues", "City")
    rows = []
    for r in grid(t)[1:]:
        label, stadium = r[0], r[1]
        city = re.sub(r"\s*\(.*$", "", label).strip()
        if city not in WC_CITY:
            raise SystemExit(f"World Cup: unmapped host city {label!r}")
        if WC_CITY[city] is None:
            continue
        metro, sid = WC_CITY[city]
        venue = re.sub(r"\s*[†‡].*$|\s*\(.*$", "", stadium).strip()
        rows.append({"event": "world_cup_2026", "year": 2026, "metro_id": metro, "state_id": sid,
                     "venue": venue, "city": label, "edition": "2026 FIFA World Cup", "source": url(title)})
    if len(rows) != 13:
        raise SystemExit(f"expected 13 US/Canada World Cup venues, got {len(rows)}")
    return rows


# --------------------------------------------------------------------------- geo

US_STATES = """Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia
Hawaii Idaho Illinois Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan
Minnesota Mississippi Missouri Montana Nebraska Nevada New_Hampshire New_Jersey New_Mexico New_York
North_Carolina North_Dakota Ohio Oklahoma Oregon Pennsylvania Rhode_Island South_Carolina South_Dakota
Tennessee Texas Utah Vermont Virginia Washington West_Virginia Wisconsin Wyoming""".split()
PROVINCES = ["Ontario", "Quebec", "British_Columbia", "Alberta", "Manitoba"]

GEO_PAGES = {  # flag -> page whose text must mention every state/province flagged Y
    "coast_atlantic": "East_Coast_of_the_United_States",
    "coast_pacific": "West_Coast_of_the_United_States",
    "coast_gulf": "Gulf_Coast_of_the_United_States",
    "great_lakes": "Great_Lakes_region",
    "borders_canada": "Canada–United_States_border",
}
STATE_FLAGS = {
    "coast_atlantic": {"maine", "new_hampshire", "massachusetts", "rhode_island", "connecticut",
                       "new_york_state", "new_jersey", "delaware", "maryland", "virginia",
                       "north_carolina", "south_carolina", "georgia", "florida"},
    "coast_pacific": {"california", "oregon", "washington_state", "alaska", "hawaii", "british_columbia"},
    "coast_gulf": {"texas", "louisiana", "mississippi", "alabama", "florida"},
    "great_lakes": {"minnesota", "wisconsin", "illinois", "indiana", "michigan", "ohio", "pennsylvania",
                    "new_york_state", "ontario"},
    "borders_canada": {"alaska", "washington_state", "idaho", "montana", "north_dakota", "minnesota",
                       "michigan", "ohio", "pennsylvania", "new_york_state", "vermont", "new_hampshire",
                       "maine"},
}

# metro -> (state_id, flags among A/P/G/L, capital city or "" / "national", coast note)
METROS = {
    "atlanta": ("georgia", "", "Atlanta", ""),
    "austin": ("texas", "", "Austin", ""),
    "baltimore": ("maryland", "", "", "Chesapeake Bay, not open ocean"),
    "bay_area": ("california", "P", "", ""),
    "boston": ("massachusetts", "A", "Boston", "Massachusetts Bay"),
    "buffalo": ("new_york_state", "L", "", "Lake Erie"),
    "calgary": ("alberta", "", "", ""),
    "charlotte": ("north_carolina", "", "", ""),
    "chicago": ("illinois", "L", "", "Lake Michigan"),
    "cincinnati": ("ohio", "", "", ""),
    "cleveland": ("ohio", "L", "", "Lake Erie"),
    "columbus": ("ohio", "", "Columbus", ""),
    "dallas_fort_worth": ("texas", "", "", ""),
    "denver": ("colorado", "", "Denver", ""),
    "detroit": ("michigan", "L", "", "Detroit River/Lake St. Clair link Lakes Huron and Erie; the metro's "
                "St. Clair County fronts Lake Huron (borderline)"),
    "edmonton": ("alberta", "", "Edmonton", ""),
    "green_bay": ("wisconsin", "L", "", "Green Bay is a bay of Lake Michigan"),
    "hartford": ("connecticut", "", "Hartford", "inland; Long Island Sound shoreline only at the far south "
                 "edge of the census metro (lower Connecticut River towns): coast=N, borderline"),
    "houston": ("texas", "G", "", "Galveston Bay/Galveston Island are in the Houston metro"),
    "indianapolis": ("indiana", "", "Indianapolis", ""),
    "jacksonville": ("florida", "A", "", ""),
    "kansas_city": ("missouri", "", "", "metro straddles Missouri/Kansas; neither capital"),
    "las_vegas": ("nevada", "", "", ""),
    "los_angeles": ("california", "P", "", ""),
    "memphis": ("tennessee", "", "", ""),
    "miami": ("florida", "A", "", "Atlantic only; Florida Bay/Everglades edge not counted as Gulf"),
    "milwaukee": ("wisconsin", "L", "", "Lake Michigan"),
    "minneapolis_st_paul": ("minnesota", "", "Saint Paul", ""),
    "montreal": ("quebec", "", "", "St. Lawrence River, not a Great Lake"),
    "nashville": ("tennessee", "", "Nashville", ""),
    "new_orleans": ("louisiana", "G", "", "conventionally a Gulf Coast city; the city sits on the "
                    "Mississippi/Lake Pontchartrain, the metro (Plaquemines, St. Bernard) reaches the Gulf"),
    "new_york": ("new_york_state", "A", "", "Atlantic beaches (Rockaways, Jersey Shore)"),
    "oklahoma_city": ("oklahoma", "", "Oklahoma City", ""),
    "orlando": ("florida", "", "", "inland; the coast (Brevard County) is a separate metro"),
    "ottawa": ("ontario", "", "national", ""),
    "philadelphia": ("pennsylvania", "", "", "Delaware River estuary, no open-ocean coast"),
    "phoenix": ("arizona", "", "Phoenix", ""),
    "pittsburgh": ("pennsylvania", "", "", ""),
    "portland": ("oregon", "", "", "about 80 mi from the Pacific; Salem (capital) is a separate metro"),
    "quebec_city": ("quebec", "", "Quebec City", "St. Lawrence River"),
    "raleigh": ("north_carolina", "", "Raleigh", ""),
    "sacramento": ("california", "", "Sacramento", ""),
    "salt_lake_city": ("utah", "", "Salt Lake City", ""),
    "san_antonio": ("texas", "", "", ""),
    "san_diego": ("california", "P", "", ""),
    "seattle": ("washington_state", "P", "", "on Puget Sound (Pacific inlet), no open-ocean beach; marked "
                "Y as a conventional Pacific-coast city (borderline)"),
    "st_louis": ("missouri", "", "", ""),
    "tampa_bay": ("florida", "G", "", "Pinellas County Gulf beaches"),
    "toronto": ("ontario", "L", "Toronto", "Lake Ontario"),
    "vancouver": ("british_columbia", "P", "", "on the Strait of Georgia (Pacific inlet); marked Y as a "
                  "Pacific port city (borderline); Victoria (BC capital) is not in the metro"),
    "washington": ("", "", "national", "Potomac/Chesapeake, no ocean coast; DC is not a state"),
    "winnipeg": ("manitoba", "", "Winnipeg", ""),
}
CAPITAL_NOTES = {  # extra wording appended to the generated capital_note
    "baltimore": "; Annapolis is in the Baltimore MSA (Anne Arundel County) but is not thought of as "
                 "Baltimore: N, borderline",
}
STATE_NOTES = {  # coast_note for states
    "ohio": "Canada border is the water boundary in Lake Erie",
    "pennsylvania": "Canada border is the water boundary in Lake Erie; Delaware estuary is not open ocean",
    "michigan": "Canada border runs through Lakes Superior/Huron/Erie and the Detroit/St. Marys rivers",
    "minnesota": "Canada border includes Lake Superior and the Northwest Angle",
    "connecticut": "coast is Long Island Sound (counted as Atlantic, as on the East Coast page)",
    "quebec": "Gulf of St. Lawrence/Hudson Bay coasts; not counted as Atlantic (Atlantic Canada excludes "
              "Quebec) - borderline",
    "ontario": "Hudson Bay/James Bay coast (Arctic), not counted",
    "manitoba": "Hudson Bay coast (Arctic), not counted",
    "alaska": "also Arctic coast",
    "florida": "Atlantic and Gulf coasts",
}
FLAG_LETTERS = {"A": "coast_atlantic", "P": "coast_pacific", "G": "coast_gulf", "L": "great_lakes"}


def capitals(offline: bool) -> dict[str, str]:
    caps = {}
    t = table_after(page("List_of_capitals_in_the_United_States", offline), "State capitals", "State")
    for r in grid(t)[1:]:
        if len(r) > 1 and r[0].replace(" ", "_") in US_STATES:
            caps[state_id(r[0])] = r[1]
    t = table_after(page("Provinces_and_territories_of_Canada", offline), "Provinces", "Name")
    for r in grid(t)[2:]:
        if len(r) > 2 and r[0].replace(" ", "_") in PROVINCES:
            caps[state_id(r[0])] = r[2]
    missing = {state_id(s.replace("_", " ")) for s in US_STATES + PROVINCES} - set(caps)
    if missing:
        raise SystemExit(f"capitals not parsed for {sorted(missing)}")
    return caps


def geo(offline: bool) -> list[dict]:
    caps = capitals(offline)
    texts = {k: page(v, offline).get_text(" ") for k, v in GEO_PAGES.items()}
    us_src = " ".join(url(t) for t in GEO_PAGES.values())
    rows = []
    for s in US_STATES + PROVINCES:
        name = s.replace("_", " ")
        sid = state_id(name)
        row = {"id": sid}
        for flag, members in STATE_FLAGS.items():
            row[flag] = "Y" if sid in members else "N"
            if sid in members and s not in PROVINCES and name not in texts[flag]:
                print(f"  warning: {name} not mentioned on {GEO_PAGES[flag]}", file=sys.stderr)
        if s in PROVINCES:
            row["borders_canada"] = ""  # category applies to U.S. states only
        row.update(capital="", capital_note="", coast_note=STATE_NOTES.get(sid, ""), source=us_src + (
            " " + url("Provinces_and_territories_of_Canada") if s in PROVINCES else ""))
        rows.append(row)
    cap_src = url("List_of_capitals_in_the_United_States") + " " + url("Provinces_and_territories_of_Canada")
    for mid, (sid, flags, cap, note) in sorted(METROS.items()):
        row = {"id": mid, **{f: ("Y" if letter in flags else "N") for letter, f in FLAG_LETTERS.items()},
               "borders_canada": ""}
        if cap == "national":
            country = "Canada" if mid == "ottawa" else "the United States"
            row["capital"], row["capital_note"] = "Y", f"national capital of {country}"
        elif cap:
            if caps.get(sid, "").replace("St.", "Saint") != cap:
                raise SystemExit(f"{mid}: {cap!r} is not the parsed capital of {sid} ({caps.get(sid)!r})")
            row["capital"], row["capital_note"] = "Y", f"{cap} is the capital of {sid.replace('_state', '').replace('_', ' ').title()}"
        else:
            row["capital"], row["capital_note"] = "N", (f"capital of {sid.replace('_state', '').replace('_', ' ').title()} is {caps[sid]}" if sid else "")
        row["capital_note"] += CAPITAL_NOTES.get(mid, "")
        row["coast_note"] = note
        row["source"] = " ".join(url(t) for t in GEO_PAGES.values() if t != GEO_PAGES["borders_canada"]) + " " + cap_src
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- main

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="use only cached pages in data/raw/")
    a = ap.parse_args(argv)
    from ballmonitor.games.triple_play.places.collect_colleges import town_rows  # campus towns fill blank metros
    write("colleges", ["school", "short_name", "conference", "campus_city", "metro_id", "state_id", "source"],
          town_rows(colleges(a.offline))[0])
    write("events", ["event", "year", "metro_id", "state_id", "venue", "city", "edition", "source"],
          super_bowls(a.offline) + olympics(a.offline) + world_cup(a.offline))
    write("geo", ["id", "coast_atlantic", "coast_pacific", "coast_gulf", "great_lakes", "borders_canada",
                  "capital", "capital_note", "coast_note", "source"], geo(a.offline))


if __name__ == "__main__":
    main()
