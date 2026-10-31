"""Build entities.csv, teams.csv and titles.csv for the Triple Play "places" pack.

Everything is parsed from cached English Wikipedia article pages (see DATA_SPEC.md):

    python -m ballmonitor.games.triple_play.places.collect_teams [--offline]

Politeness: only `https://en.wikipedia.org/wiki/<Title>` pages are requested (never /w/ or
/api/), one at a time with >= 2.5 s between requests, honest User-Agent, and every page is
cached in places/data/raw/ so a rebuild normally makes no requests at all.

Hand-entered facts (where a page can't be parsed reliably) live in the HAND_* tables below;
each carries the URL of the page it was checked against, and most are re-verified against
the cached page text on every run (`require_text`).

Conventions (also in data/NOTES.md):
  * Seasons that span two calendar years: first_season_in_metro = calendar year the first
    season *started*, last_season_in_metro = calendar year the last season *ended*
    (Seattle SuperSonics 1967-2008). Single-year seasons are just the year.
  * Seasons count only in the league named in the row: NFL includes the AFL (the NFL
    incorporated AFL history) but not the AAFC; NBA includes the BAA but not the ABA/NBL;
    NHL excludes the WHA.
  * Title `season` = year the title was won (NBA/NHL: year the season ended). Pre-Super Bowl
    NFL titles use the season year (the 1965 title game was played on 2 Jan 1966).
"""
from __future__ import annotations

import argparse
import csv
import html
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RAW = DATA / "raw"
UA = "ballmonitor-games/0.1 (personal, non-commercial)"
WIKI = "https://en.wikipedia.org/wiki/"
PAUSE_S = 2.5

# Last title season that is complete as of October 2026 (2026 World Series, MLS Cup and
# WNBA Finals not finished when the pages were fetched).
LAST_TITLE = {"NFL": 2026, "NBA": 2026, "NHL": 2026, "MLB": 2025, "MLS": 2025, "WNBA": 2026}
STINT_SINCE = 1950  # former stints are kept when the team was still there in/after this year

PAGES = {
    "nfl": "National Football League",
    "nba": "National Basketball Association",
    "mlb": "Major League Baseball",
    "nhl": "National Hockey League",
    "mls": "Major League Soccer",
    "wnba": "Women's National Basketball Association",
    "nfl_moves": "NFL franchise moves and mergers",
    "nfl_defunct": "List of defunct National Football League franchises",
    "nba_reloc": "List of relocated National Basketball Association teams",
    "nba_defunct": "List of defunct National Basketball Association teams",
    "nhl_reloc": "List of defunct National Hockey League teams",
    "mlb_reloc": "List of defunct and relocated Major League Baseball teams",
    "reloc": "Relocation of major professional sports teams in the United States and Canada",
    "sb": "List of Super Bowl champions",
    "nfl_champs": "List of NFL champions (1920–1969)",
    "nba_champs": "List of NBA champions",
    "ws": "List of World Series champions",
    "cup": "List of Stanley Cup champions",
    "mls_cup": "List of MLS Cup finals",
    "wnba_champs": "List of WNBA champions",
    "states": "List of states and territories of the United States",
    "provinces": "Provinces and territories of Canada",
    "sun": "Connecticut Sun",
    "wings": "Dallas Wings",
    "aces": "Las Vegas Aces",
    "canes": "Carolina Hurricanes",
    "giants": "New York Giants",
    "wizards": "Washington Wizards",
    "skc": "Sporting Kansas City",
}

# --------------------------------------------------------------------------- places
# Metro assignment is a judgement made in DATA_SPEC.md ("one metro per market, named as fans
# say it, suburbs in their metro"). id -> (display name, principal state id, country)
METROS = {
    "new_york": ("New York", "new_york_state", "USA"),
    "los_angeles": ("Los Angeles", "california", "USA"),
    "bay_area": ("Bay Area", "california", "USA"),
    "dallas_fort_worth": ("Dallas–Fort Worth", "texas", "USA"),
    "washington": ("Washington", "", "USA"),  # DC is not a state entity
    "boston": ("Boston", "massachusetts", "USA"),
    "miami": ("Miami", "florida", "USA"),
    "phoenix": ("Phoenix", "arizona", "USA"),
    "minneapolis_st_paul": ("Minneapolis–St. Paul", "minnesota", "USA"),
    "tampa_bay": ("Tampa Bay", "florida", "USA"),
    "raleigh": ("Raleigh", "north_carolina", "USA"),
    "salt_lake_city": ("Salt Lake City", "utah", "USA"),
    "sacramento": ("Sacramento", "california", "USA"),
    "las_vegas": ("Las Vegas", "nevada", "USA"),
    "green_bay": ("Green Bay", "wisconsin", "USA"),
    "buffalo": ("Buffalo", "new_york_state", "USA"),
    "chicago": ("Chicago", "illinois", "USA"),
    "philadelphia": ("Philadelphia", "pennsylvania", "USA"),
    "houston": ("Houston", "texas", "USA"),
    "atlanta": ("Atlanta", "georgia", "USA"),
    "detroit": ("Detroit", "michigan", "USA"),
    "denver": ("Denver", "colorado", "USA"),
    "seattle": ("Seattle", "washington_state", "USA"),
    "cleveland": ("Cleveland", "ohio", "USA"),
    "pittsburgh": ("Pittsburgh", "pennsylvania", "USA"),
    "baltimore": ("Baltimore", "maryland", "USA"),
    "cincinnati": ("Cincinnati", "ohio", "USA"),
    "columbus": ("Columbus", "ohio", "USA"),
    "kansas_city": ("Kansas City", "missouri", "USA"),
    "st_louis": ("St. Louis", "missouri", "USA"),
    "indianapolis": ("Indianapolis", "indiana", "USA"),
    "nashville": ("Nashville", "tennessee", "USA"),
    "memphis": ("Memphis", "tennessee", "USA"),
    "jacksonville": ("Jacksonville", "florida", "USA"),
    "orlando": ("Orlando", "florida", "USA"),
    "charlotte": ("Charlotte", "north_carolina", "USA"),
    "new_orleans": ("New Orleans", "louisiana", "USA"),
    "milwaukee": ("Milwaukee", "wisconsin", "USA"),
    "oklahoma_city": ("Oklahoma City", "oklahoma", "USA"),
    "portland": ("Portland", "oregon", "USA"),
    "san_antonio": ("San Antonio", "texas", "USA"),
    "austin": ("Austin", "texas", "USA"),
    "san_diego": ("San Diego", "california", "USA"),
    "hartford": ("Hartford", "connecticut", "USA"),
    "toronto": ("Toronto", "ontario", "CAN"),
    "montreal": ("Montreal", "quebec", "CAN"),
    "quebec_city": ("Quebec City", "quebec", "CAN"),
    "ottawa": ("Ottawa", "ontario", "CAN"),
    "winnipeg": ("Winnipeg", "manitoba", "CAN"),
    "calgary": ("Calgary", "alberta", "CAN"),
    "edmonton": ("Edmonton", "alberta", "CAN"),
    "vancouver": ("Vancouver", "british_columbia", "CAN"),
}
FORMER_ONLY_METROS = {"hartford", "quebec_city"}

# place name (city, suburb, or the place word in a team name) -> metro id ("" = no metro)
PLACE_METRO = {
    # New York
    "New York": "new_york", "New York City": "new_york", "Brooklyn": "new_york", "Bronx": "new_york",
    "Elmont": "new_york", "East Rutherford": "new_york", "Newark": "new_york", "Harrison": "new_york",
    "New Jersey": "new_york",
    # Los Angeles
    "Los Angeles": "los_angeles", "LA": "los_angeles", "Inglewood": "los_angeles", "Carson": "los_angeles",
    "Anaheim": "los_angeles",
    # Bay Area
    "San Francisco": "bay_area", "Oakland": "bay_area", "San Jose": "bay_area", "Santa Clara": "bay_area",
    "Golden State": "bay_area",
    "Dallas": "dallas_fort_worth", "Arlington": "dallas_fort_worth", "Frisco": "dallas_fort_worth",
    "Texas": "dallas_fort_worth",
    "Washington": "washington", "Landover": "washington", "Capital": "washington", "D.C.": "washington",
    "Boston": "boston", "Foxborough": "boston", "New England": "boston",
    "Miami": "miami", "Miami Gardens": "miami", "Sunrise": "miami", "Fort Lauderdale": "miami",
    "Florida": "miami",
    "Phoenix": "phoenix", "Glendale": "phoenix", "Tempe": "phoenix", "Scottsdale": "phoenix",
    "Arizona": "phoenix",
    "Minneapolis": "minneapolis_st_paul", "Saint Paul": "minneapolis_st_paul", "Minnesota": "minneapolis_st_paul",
    "Tampa": "tampa_bay", "St. Petersburg": "tampa_bay", "Tampa Bay": "tampa_bay",
    "Raleigh": "raleigh",
    "Salt Lake City": "salt_lake_city", "Salt Lake": "salt_lake_city", "Sandy": "salt_lake_city",
    "Utah": "salt_lake_city",
    "Sacramento": "sacramento", "West Sacramento": "sacramento",
    "Las Vegas": "las_vegas", "Paradise": "las_vegas", "Vegas": "las_vegas",
    "Green Bay": "green_bay",
    "Buffalo": "buffalo", "Orchard Park": "buffalo",
    "Chicago": "chicago",
    "Philadelphia": "philadelphia", "Chester": "philadelphia", "Frankford": "philadelphia",
    "Houston": "houston",
    "Atlanta": "atlanta", "Cumberland": "atlanta", "College Park": "atlanta",
    "Detroit": "detroit",
    "Denver": "denver", "Commerce City": "denver", "Colorado": "denver",
    "Seattle": "seattle",
    "Cleveland": "cleveland",
    "Pittsburgh": "pittsburgh",
    "Baltimore": "baltimore",
    "Cincinnati": "cincinnati",
    "Columbus": "columbus",
    "Kansas City": "kansas_city", "Kansas City–Omaha": "kansas_city",
    "St. Louis": "st_louis",
    "Indianapolis": "indianapolis", "Indiana": "indianapolis",
    "Nashville": "nashville", "Tennessee": "nashville",
    "Memphis": "memphis",
    "Jacksonville": "jacksonville",
    "Orlando": "orlando",
    "Charlotte": "charlotte",
    "New Orleans": "new_orleans",
    "Milwaukee": "milwaukee",
    "Oklahoma City": "oklahoma_city",
    "Portland": "portland",
    "San Antonio": "san_antonio",
    "Austin": "austin",
    "San Diego": "san_diego",
    "Hartford": "hartford",
    "Toronto": "toronto",
    "Montreal": "montreal", "Montréal": "montreal",
    "Quebec": "quebec_city", "Quebec City": "quebec_city",
    "Ottawa": "ottawa",
    "Winnipeg": "winnipeg",
    "Calgary": "calgary",
    "Edmonton": "edmonton",
    "Vancouver": "vancouver",
    # places outside every metro of the pack (state only)
    "Akron": "", "Canton": "", "Providence": "", "Rochester": "", "Syracuse": "", "Fort Wayne": "",
    "Tri-Cities": "", "Anderson": "", "Sheboygan": "", "Waterloo": "", "Greensboro": "",
    "Uncasville": "", "Victoria": "",
}
# place -> state id, for places whose state is not the principal state of their metro
PLACE_STATE = {
    "East Rutherford": "new_jersey", "Newark": "new_jersey", "Harrison": "new_jersey", "New Jersey": "new_jersey",
    "Landover": "maryland", "Capital": "maryland", "Washington": "", "D.C.": "",
    "Akron": "ohio", "Canton": "ohio", "Providence": "rhode_island", "Rochester": "new_york_state",
    "Syracuse": "new_york_state", "Fort Wayne": "indiana", "Tri-Cities": "illinois", "Anderson": "indiana",
    "Sheboygan": "wisconsin", "Waterloo": "iowa", "Greensboro": "north_carolina", "Uncasville": "connecticut",
    "Victoria": "british_columbia", "Kansas City, Kansas": "kansas",
}
# full team names whose place word is ambiguous or absent
TEAM_PLACE = {
    "Carolina Panthers": "Charlotte", "Carolina Hurricanes": "Raleigh",
    "California Golden Seals": "Oakland", "Athletics": "West Sacramento",
    "Capital Bullets": "Capital", "Connecticut Sun": "Uncasville",
}
NICKNAME = {
    "Athletics": "Athletics", "Inter Miami CF": "Inter Miami", "FC Dallas": "FC Dallas",
    "FC Cincinnati": "FC Cincinnati", "CF Montréal": "CF Montréal", "Sporting Kansas City": "Sporting KC",
    "Real Salt Lake": "Real Salt Lake", "D.C. United": "D.C. United", "Atlanta United FC": "Atlanta United",
    "Minnesota United FC": "Minnesota United", "New York City FC": "NYCFC", "Los Angeles FC": "LAFC",
    "St. Louis City SC": "St. Louis City", "Austin FC": "Austin FC", "Charlotte FC": "Charlotte FC",
    "Nashville SC": "Nashville SC", "Toronto FC": "Toronto FC", "San Diego FC": "San Diego FC",
    "Orlando City SC": "Orlando City", "Carolina Panthers": "Panthers",
    "Carolina Hurricanes": "Hurricanes", "California Golden Seals": "Golden Seals",
    "Connecticut Sun": "Sun",
}
# display names for the two states whose plain name equals a metro name
STATE_DISPLAY = {"new_york_state": "New York State", "washington_state": "Washington State"}

# --------------------------------------------------------------------------- hand-entered facts
# Each tuple: (league, team, place, first, last-or-None, source page key, text the cached page
# must contain, why). Verified on every run.
HAND_TEAMS = [
    ("WNBA", "Connecticut Sun", "Uncasville", 2003, None, "sun", "Connecticut Sun2003–2026",
     "The 2026 season was played by the Connecticut Sun (Uncasville, CT). The WNBA page's team "
     "table already shows the club as the Houston Comets, which begin play in 2027."),
    ("NHL", "Carolina Hurricanes", "Greensboro", 1997, 1999, "canes",
     "play home games in Greensboro, 90 minutes west of Raleigh, for their first two seasons",
     "Hurricanes played 1997-98 and 1998-99 in Greensboro (no metro in the pack)."),
]
# current-team first season overrides: (league, team) -> (season, source key, required text, why)
HAND_FIRST_SEASON = {
    ("WNBA", "Dallas Wings"): (2016, "wings", "Dallas Wings2016–present", "Detroit 1998-2009, Tulsa 2010-15"),
    ("WNBA", "Las Vegas Aces"): (2018, "aces", "Las Vegas Aces2018–present", "Utah 1997-2002, San Antonio 2003-17"),
    ("NHL", "Carolina Hurricanes"): (1999, "canes", "for their first two seasons after the move",
                                     "first two seasons in Greensboro (see HAND_TEAMS)"),
}
# rows of a league table that are not 2026 teams: (league, team) -> (source key, required text)
EXCLUDE_CURRENT = {
    ("WNBA", "Houston Comets"): ("sun", "Houston Comets2027–present"),
}
# relocation rows to drop: (league, team, first season) -> why
SKIP_STINTS = {
    ("NBA", "Charlotte Hornets", 1988):
        "NBA credits the 1988-2002 Charlotte Hornets history to the current Charlotte Hornets "
        "(NBA team table: founded 1988*); the New Orleans franchise is listed as founded 2002.",
}
# titles whose home venue was in a different state from the team's name/metro default
def title_state_override(league: str, team: str, year: int) -> tuple[str, str] | None:
    if league == "NFL" and team == "New York Giants" and year >= 1977:
        return "new_jersey", "giants"     # Giants Stadium, East Rutherford, from 1976 season
    if league == "NBA" and team == "Washington Bullets" and 1974 <= year <= 1997:
        return "maryland", "wizards"      # Capital Centre, Landover, Dec 1973 - 1997
    if league == "MLS" and team == "Sporting Kansas City" and year >= 2011:
        return "kansas", "skc"            # Sporting Park, Kansas City, Kansas
    return None
STATE_OVERRIDE_TEXT = {
    "giants": "Giants Stadium was home to the Giants from 1976 to 2009",
    "wizards": "move 30 miles (50 km) southwest to the Capital Centre in Landover",
    "skc": "With the opening of the new Sporting Park in Kansas City, Kansas",
}

# --------------------------------------------------------------------------- fetching
_last_request = [0.0]


def cache_path(title: str) -> Path:
    return RAW / (urllib.parse.quote(title.replace(" ", "_"), safe="") + ".html")


def fetch(title: str, offline: bool = False) -> str:
    path = cache_path(title)
    if path.exists():
        return path.read_text(encoding="utf-8")
    if offline:
        raise SystemExit(f"missing cached page (offline): {title}")
    wait = PAUSE_S - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    url = WIKI + urllib.parse.quote(title.replace(" ", "_"), safe="()_,'–")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8")
    _last_request[0] = time.time()
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    print(f"  fetched {url}", file=sys.stderr)
    return body


class Page:
    def __init__(self, key: str, offline: bool):
        self.key, self.title = key, PAGES[key]
        self.html = fetch(self.title, offline)
        m = re.search(r'<link rel="canonical" href="([^"]+)"', self.html)
        self.url = html.unescape(m.group(1)) if m else WIKI + self.title.replace(" ", "_")
        self._tables = None
        self._text = None

    @property
    def tables(self):
        if self._tables is None:
            p = _TableParser()
            p.feed(self.html)
            self._tables = [dict(t, grid=_grid(t["rows"])) for t in p.tables]
        return self._tables

    @property
    def text(self) -> str:
        if self._text is None:
            body = self.html[self.html.find("mw-parser-output"):]
            body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
            body = html.unescape(re.sub(r"<[^>]+>", "", body))
            self._text = re.sub(r"\[\d+\]", "", body)
        return self._text

    def table(self, *headers: str, heading: str | None = None) -> list[dict[str, str]]:
        """First wikitable whose header row contains all `headers`; rows as dicts."""
        for t in self.tables:
            if "wikitable" not in t["cls"] or not t["grid"]:
                continue
            if heading and heading not in t["heading"]:
                continue
            for hi, hrow in enumerate(t["grid"][:3]):
                names = [_norm_header(c["text"]) for c in hrow]
                if all(h in names for h in headers):
                    out = []
                    for row in t["grid"][hi + 1:]:
                        if all(c["th"] for c in row) and len(row) == len(names) and \
                                [_norm_header(c["text"]) for c in row] == names:
                            continue
                        d = {n: "" for n in names}
                        for name, c in zip(names, row):
                            d[name] = d[name] or c["text"]
                        out.append(d)
                    return out
        raise ValueError(f"{self.title}: no table with headers {headers}")

    def require(self, text: str) -> None:
        flat = re.sub(r"\s+", "", self.text)
        if re.sub(r"\s+", "", text) not in flat:
            raise SystemExit(f"hand-entered fact no longer supported by {self.url}: {text!r}")


def _norm_header(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\n", " ")).strip()


class _TableParser(HTMLParser):
    SKIP = {"style", "script", "sup"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack, self.skip, self.heading, self._h = [], [], [], "", None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        hidden = tag == "span" and "display:none" in (a.get("style") or "").replace(" ", "")
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.append(tag)
            return
        if tag in self.SKIP or hidden:
            self.skip.append(tag)
            return
        if tag in ("h2", "h3", "h4") and not self.stack:
            self._h = []
        if tag == "table":
            self.stack.append({"cls": a.get("class", ""), "rows": [], "row": None, "cell": None,
                               "heading": self.heading})
            return
        if not self.stack:
            return
        t = self.stack[-1]
        if tag == "tr":
            t["row"] = []
        elif tag in ("td", "th") and t["row"] is not None:
            span = lambda k: int(re.sub(r"\D", "", a.get(k) or "1") or 1)  # noqa: E731
            t["cell"] = {"th": tag == "th", "text": [], "rs": span("rowspan"), "cs": span("colspan")}
        elif tag == "br" and t["cell"] is not None:
            t["cell"]["text"].append("\n")

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag in ("h2", "h3", "h4") and self._h is not None:
            self.heading, self._h = "".join(self._h).strip(), None
        if not self.stack:
            return
        t = self.stack[-1]
        if tag in ("td", "th") and t["cell"] is not None:
            c = t["cell"]
            c["text"] = re.sub(r"[ \t\xa0‍]+", " ", "".join(c["text"])).strip()
            t["row"].append(c)
            t["cell"] = None
        elif tag == "tr" and t["row"] is not None:
            if t["cell"] is not None:
                self.handle_endtag("td")
            t["rows"].append(t["row"])
            t["row"] = None
        elif tag == "table":
            self.stack.pop()
            self.tables.append({"cls": t["cls"], "rows": t["rows"], "heading": t["heading"]})

    def handle_data(self, d):
        if self.skip:
            return
        if self._h is not None:
            self._h.append(d)
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"]["text"].append(d)


def _grid(rows):
    """Expand rowspan/colspan into rectangular rows of cell dicts."""
    out, pending = [], {}
    for r in rows:
        line, col, i = [], 0, 0
        while i < len(r) or col in pending:
            if col in pending:
                c, left = pending.pop(col)
                if left > 1:
                    pending[col] = (c, left - 1)
                line.append(c)
                col += 1
                continue
            c = r[i]
            i += 1
            for _ in range(c["cs"]):
                if c["rs"] > 1:
                    pending[col] = (c, c["rs"] - 1)
                line.append(c)
                col += 1
        out.append(line)
    return out


# --------------------------------------------------------------------------- helpers
def snake(s: str) -> str:
    s = s.replace("–", " ").replace(".", "").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def state_id(name: str) -> str:
    name = name.strip()
    if name in ("D.C.", "District of Columbia"):
        return ""
    sid = snake(name)
    return {"new_york": "new_york_state", "washington": "washington_state"}.get(sid, sid)


def clean_team(s: str) -> str:
    s = s.split("\n")[0].split(" / ")[0]
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[*†‡§^#¤]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def years(s: str) -> list[int]:
    return [int(y) for y in re.findall(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)", s)]


def place_of_team(team: str) -> str:
    if team in TEAM_PLACE:
        return TEAM_PLACE[team]
    words = team.split()
    for drop in (0, 1):   # "FC Dallas", "Sporting Kansas City", "Real Salt Lake", "Inter Miami"
        rest = words[drop:]
        for n in range(len(rest), 0, -1):
            cand = " ".join(rest[:n])
            if cand in PLACE_METRO:
                return cand
    raise KeyError(f"no place for team {team!r}; add it to PLACE_METRO/TEAM_PLACE")


def metro_state(place: str) -> tuple[str, str]:
    metro = PLACE_METRO[place]
    if place in PLACE_STATE:
        return metro, PLACE_STATE[place]
    return metro, METROS[metro][1] if metro else ""


def venue_place(city_cell: str) -> tuple[str, str]:
    """'East Rutherford, New Jersey' -> (place key, state id)."""
    city, _, st = clean_team(city_cell).partition(",")
    city = city.strip()
    if city not in PLACE_METRO:
        raise KeyError(f"venue city {city!r} not in PLACE_METRO")
    if city == "Kansas City" and "Kansas" == st.strip():
        return city, "kansas"
    return city, state_id(st) if st.strip() else metro_state(city)[1]


def nickname(team: str) -> str:
    if team in NICKNAME:
        return NICKNAME[team]
    place = place_of_team(team)
    words = team.split()
    rest = " ".join(words[len(place.split()):]) if team.startswith(place) else team
    rest = re.sub(r"\b(FC|CF|SC)\b", "", rest).strip()
    return rest or team


# --------------------------------------------------------------------------- current teams
def current_teams(P) -> list[dict]:
    specs = [  # league, page, team col, city col, first-season col
        ("NFL", "nfl", "Team", "City", "First season"),
        ("NBA", "nba", "Team", "Location", "Joined"),
        ("MLB", "mlb", "Team", "City", "Founded"),
        ("NHL", "nhl", "Team", "City", "Joined"),
        ("MLS", "mls", "Club", "Location", "Joined"),
        ("WNBA", "wnba", "Team", "City", "Joined"),
    ]
    out = []
    for league, key, tcol, ccol, fcol in specs:
        page = P[key]
        for r in page.table(tcol, ccol, fcol):
            team = clean_team(r[tcol])
            if not team:
                continue
            if (league, team) in EXCLUDE_CURRENT:
                src, text = EXCLUDE_CURRENT[(league, team)]
                P[src].require(text)
                continue
            place, st = venue_place(r[ccol])
            first = first_season(league, r[fcol], r.get("Joined", ""))
            out.append(dict(league=league, team=team, place=place, state_id=st, first=first,
                            source=page.url))
    for league, team, place, first, last, src, text, _why in HAND_TEAMS:
        P[src].require(text)
        if last is None:
            out.append(dict(league=league, team=team, place=place,
                            state_id=metro_state(place)[1], first=first, source=P[src].url))
    return out


def first_season(league: str, cell: str, joined: str) -> int:
    parts = re.findall(r"(\d{4})\*?\s*(?:\(([^)]+)\))?", cell)
    if league == "NFL":
        for y, tag in parts:
            if tag == "AFL" and int(y) >= 1960:
                return int(y)
        for y, tag in parts:
            if tag == "NFL":
                return int(y)
        return int(parts[0][0])
    if league == "MLB":
        y, tag = parts[0]
        return years(joined)[0] if tag in ("NA", "NABBP") else int(y)
    return int(parts[0][0])


# --------------------------------------------------------------------------- relocations
def chains_from_rows(league: str, rows: list[dict], cur: list[dict], source: str):
    """rows: team, first, last, to, next_first. Returns (arrivals, stints).

    arrivals: {current team name: first season in its current metro}
    stints:   former metro stints (dicts) of every chain, merged by metro.
    """
    by_league = [c for c in cur if c["league"] == league]
    for r in rows:
        r["metro"], r["state"] = metro_state(place_of_team(r["team"]))
    # link r -> successor row
    succ, has_pred = {}, set()
    for i, r in enumerate(rows):
        to_metro = None
        try:
            to_metro = metro_state(place_of_team(r["to"]))[0]
        except KeyError:
            pass
        for j, s in enumerate(rows):
            if j != i and s["first"] == r["next_first"] and (s["team"] == r["to"] or (to_metro is not None and s["metro"] == to_metro and s["metro"] != r["metro"])):
                succ[i] = j
                has_pred.add(j)
                break
    arrivals, stints = {}, []
    for i in range(len(rows)):
        if i in has_pred:
            continue
        chain = [i]
        while chain[-1] in succ:
            chain.append(succ[chain[-1]])
        last = rows[chain[-1]]
        current = None
        for c in by_league:
            if c["team"] == last["to"]:
                current = c
        if current is None:
            try:
                to_metro = metro_state(place_of_team(last["to"]))[0]
                cands = [c for c in by_league if metro_state(c["place"])[0] == to_metro]
                if len(cands) == 1:
                    current = cands[0]
            except KeyError:
                pass
        # group consecutive rows by metro
        groups = []
        for k in chain:
            r = rows[k]
            if groups and groups[-1][-1]["metro"] == r["metro"]:
                groups[-1].append(r)
            else:
                groups.append([r])
        cur_metro = metro_state(current["place"])[0] if current else None
        if current:
            moved_in = [g for g in groups if g[0]["metro"] != cur_metro]
            if moved_in:   # season after the last stint in another metro
                arrivals[current["team"]] = moved_in[-1][-1]["next_first"]
        for g in groups:
            if current and g[0]["metro"] == cur_metro and g is groups[-1]:
                continue
            team, first, lastyr = g[-1]["team"], g[0]["first"], g[-1]["last"]
            if lastyr < STINT_SINCE:
                continue
            if (league, g[0]["team"], first) in SKIP_STINTS:
                continue
            stints.append(dict(league=league, team=team, metro=g[0]["metro"], state=g[0]["state"],
                               first=first, last=lastyr, source=source))
    return arrivals, stints


def nba_relocations(P, cur):
    page = P["nba_reloc"]
    rows = []
    for r in page.table("Team", "Founded", "Moved", "Moved to"):
        if not years(r["Founded"]) or not years(r["Moved"]):
            continue
        f, m = years(r["Founded"])[0], years(r["Moved"])[0]
        rows.append(dict(team=clean_team(r["Team"]), first=f, last=m, next_first=m,
                         to=clean_team(r["Moved to"])))
    return chains_from_rows("NBA", rows, cur, page.url)


def nhl_relocations(P, cur):
    page = P["nhl_reloc"]
    rows = []
    for r in page.table("Team", "First", "Last", "Moved to"):
        f, l = years(r["First"]), years(r["Last"])
        if not f or not l or l[0] < STINT_SINCE:
            continue
        rows.append(dict(team=clean_team(r["Team"]), first=f[0], last=l[0], next_first=l[0],
                         to=clean_team(r["Moved to"].split("\n")[0])))
    return chains_from_rows("NHL", rows, cur, page.url)


def mlb_relocations(P, cur):
    page = P["mlb_reloc"]
    rows = []
    for r in page.table("Team", "League", "First", "Last", "Post-change status"):
        f, l = years(r["First"]), years(r["Last"])
        if not f or not l or l[0] < STINT_SINCE:
            continue
        rows.append(dict(team=clean_team(r["Team"]), first=f[0], last=l[0], next_first=l[0] + 1,
                         to=clean_team(r["Post-change status"])))
    return chains_from_rows("MLB", rows, cur, page.url)


def nfl_relocations(P, cur):
    """Parse 'Team: [back|temporarily] to City [as X] in YEAR' bullets of the moves page."""
    page = P["nfl_moves"]
    seg = page.text.split("In chronological order:")[1].split("Quasi-moves")[0]
    moves, renames = [], {}
    for line in seg.splitlines():
        m = re.match(r"^(?P<team>[^:]+): (?:back |temporarily )?to (?P<city>.+?)"
                     r"(?: as (?:the )?(?P<as>[^()]+?))? in (?P<year>\d{4})(?P<rest>.*)$", line.strip())
        if not m:
            continue
        city = m["city"].split(",")[0].strip()
        late_as = re.match(r" as (?:the )?(.+?)(?= and | \(|$)", m["rest"])
        as_name = (m["as"] or (late_as.group(1) if late_as else "")).strip()
        ren = re.search(r"renamed (?:the |as the )?(.+?) in \d{4}", m["rest"])
        moves.append((int(m["year"]), m["team"].strip(), city, as_name))
        if ren:
            renames[m["team"].strip()] = ren.group(1).strip()
        m2 = re.search(r"and permanently to (?P<city>[^,]+?) in (?P<year>\d{4})", m["rest"])
        if m2:
            moves.append((int(m2["year"]), as_name, m2["city"].strip(), ""))
    by_league = {c["team"]: c for c in cur if c["league"] == "NFL"}
    # franchise state: name -> list of (team name, place, first)
    hist: dict[str, list] = {}
    aliases: dict[str, set] = defaultdict(set)
    for year, team, city, as_name in sorted(moves, key=lambda x: x[0]):
        key = next((k for k, h in hist.items() if h[-1][0] == team), None)
        if key is None:
            place = _try_place(team)
            first = None   # filled from the current team at the end of the chain
            key = team
            hist[key] = [[team, place, first]]
        if as_name:
            new = as_name if len(as_name.split()) > 1 else f"{city} {as_name}"
        else:
            new = f"{city} {team.split()[-1]}"
        hist[key][-1].append(year - 1)
        hist[key].append([new, city if city in PLACE_METRO else _try_place(new), year])
        if team in renames:
            aliases[key].add(renames[team])
    arrivals, stints = {}, []
    for key, h in hist.items():
        names = {h[-1][0]} | aliases[key]
        current = next((by_league[n] for n in names if n in by_league), None)
        if current:
            arrivals[current["team"]] = h[-1][2]
            if h[0][2] is None:
                h[0][2] = current["first"]
        for team, place, first, *end in h[:-1] if current else h:
            if not end or end[0] < STINT_SINCE or first is None:
                continue
            metro, st = metro_state(place)
            stints.append(dict(league="NFL", team=team, metro=metro, state=st, first=first,
                               last=end[0], source=page.url))
    return arrivals, stints


def _try_place(team: str):
    try:
        return place_of_team(team)
    except KeyError:
        return None


def defunct_stints(P):
    out = []
    page = P["nfl_defunct"]
    for r in page.table("Club", "City", "Joined NFL", "Folded"):
        f, l = years(r["Joined NFL"]), years(r["Folded"])
        if not f or not l or l[0] < STINT_SINCE:
            continue
        name = clean_team(r["Club"])
        if "/" in name:   # "New York Bulldogs/Yanks" -> "New York Yanks"
            base, alt = name.split("/", 1)
            name = base.rsplit(" ", 1)[0] + " " + alt if " " not in alt else alt
        place, st = venue_place(r["City"])
        out.append(dict(league="NFL", team=name, metro=metro_state(place)[0], state=st,
                        first=f[0], last=l[0], source=page.url))
    page = P["nba_defunct"]
    for r in page.table("Team", "City", "Years active in NBA"):
        y = years(r["Years active in NBA"])
        if len(y) < 2 or y[1] < STINT_SINCE:
            continue
        place, st = venue_place(r["City"])
        out.append(dict(league="NBA", team=clean_team(r["Team"]), metro=metro_state(place)[0],
                        state=st, first=y[0], last=y[1], source=page.url))
    return out


# --------------------------------------------------------------------------- titles
def titles(P) -> list[dict]:
    out = []

    def add(league, year, team, page, raw):
        team = clean_team(team)
        if year > LAST_TITLE[league]:
            return
        metro, st = metro_state(place_of_team(team))
        ov = title_state_override(league, team, year)
        src = page.url
        if ov:
            st = ov[0]
            P[ov[1]].require(STATE_OVERRIDE_TEXT[ov[1]])
        out.append(dict(league=league, season=year, team=team, metro_id=metro, state_id=st,
                        source=src, _raw=raw))

    pg = P["sb"]
    for r in pg.table("Game", "Date (season)", "Winning team"):
        y = years(r["Date (season)"])
        if y:
            add("NFL", y[0], r["Winning team"], pg, r)
    pg = P["nfl_champs"]
    for r in pg.table("Season", "Champion"):
        add("NFL", years(r["Season"])[0], r["Champion"], pg, r)
    for r in pg.table("Season", "Date", "Winning team"):
        y = years(r["Season"])[0]
        if y <= 1965:
            add("NFL", y, r["Winning team"], pg, r)
    pg = P["nba_champs"]
    for r in pg.table("Year", "Western champion", "Result", "Eastern champion"):
        m = re.match(r"(\d+)\D+(\d+)", r["Result"])
        if not m or m[1] == m[2]:
            continue
        win = r["Western champion"] if int(m[1]) > int(m[2]) else r["Eastern champion"]
        add("NBA", years(r["Year"])[0], win, pg, r)
    pg = P["ws"]
    for r in pg.table("Year", "Winning team", "Series"):
        if "not played" in r["Winning team"] or "Cancelled" in r["Winning team"]:
            continue
        add("MLB", years(r["Year"])[0], r["Winning team"], pg, r)
    pg = P["cup"]
    for r in pg.table("Year", "Winning team", "Games", "Losing team",
                      heading="NHA/NHL vs. PCHA/WCHL/WHL"):
        y = years(r["Year"])[0]
        if y >= 1918 and "(NHL)" in r["Winning team"] and "not awarded" not in r["Winning team"]:
            add("NHL", y, r["Winning team"], pg, r)
    for r in pg.table("Year", "Winning team", "Games", heading="NHL champions"):
        if "cancelled" in r["Winning team"].lower() or not years(r["Year"]):
            continue
        add("NHL", years(r["Year"])[0], r["Winning team"], pg, r)
    pg = P["mls_cup"]
    for r in pg.table("Season", "Date", "Winners"):
        if years(r["Season"]):
            add("MLS", years(r["Season"])[0], r["Winners"], pg, r)
    pg = P["wnba_champs"]
    t = next(t for t in pg.tables if "wikitable" in t["cls"] and t["grid"] and
             t["grid"][0][0]["text"] == "Year" and t["grid"][1][1]["text"] == "Team")
    for row in t["grid"][2:]:
        y, team, res = years(row[0]["text"]), row[1]["text"], row[3]["text"]
        m = re.match(r"(\d+)\D+(\d+)", res)
        if not y or not m:
            continue
        need = 1 if y[0] == 1997 else 2 if y[0] <= 2004 else 3 if y[0] <= 2024 else 4
        if int(m[1]) < need or int(m[1]) <= int(m[2]):   # Finals not finished
            continue
        add("WNBA", y[0], team, pg, {"row": " | ".join(c["text"] for c in row)})
    return out


def franchise_years(P) -> dict[str, Counter]:
    """Independent cross-check: titles per year from each page's 'records by franchise' table."""
    out = {}
    specs = [("MLB", "ws", ("Team", "Wins", "Season(s)"), "Season(s)", "Wins"),
             ("NBA", "nba_champs", ("Team", "Wins", "Year(s) won"), "Year(s) won", "Wins"),
             ("MLS", "mls_cup", ("Team", "Wins", "Most recent win"), None, "Wins"),
             ("WNBA", "wnba_champs", ("Teams", "Win", "Year(s) won"), "Year(s) won", "Win")]
    for league, key, hdr, ycol, wcol in specs:
        c = Counter()
        for r in P[key].table(*hdr):
            if ycol and league != "MLB":   # MLB cell lists appearances, not just wins
                c.update(years(r[ycol])[:int(re.sub(r"\D", "", r[wcol]) or 0)])
            c["_total"] += int(re.sub(r"\D", "", r[wcol]) or 0)
        out[league] = c
    return out


# --------------------------------------------------------------------------- entities
def entities(P, metro_sources: dict[str, str]) -> list[dict]:
    out = []
    for mid in sorted(metro_sources):
        name, st, country = METROS[mid]
        out.append(dict(id=mid, name=name, kind="metro", state=st, country=country,
                        source=metro_sources[mid]))
    pg = P["states"]
    states = [clean_team(r["Flag, name and postal abbreviation"]) for r in
              pg.table("Flag, name and postal abbreviation", "Capital", heading="States")]
    states = [s for s in states if s]
    if len(states) != 50:
        raise SystemExit(f"expected 50 states, parsed {len(states)}")
    for s in states:
        out.append(dict(id=state_id(s), name=STATE_DISPLAY.get(state_id(s), s), kind="state",
                        state=state_id(s), country="USA",
                        source=pg.url))
    pg = P["provinces"]
    provs = [clean_team(r["Name and postal abbreviation"]) for r in
             pg.table("Name and postal abbreviation", "Capital", heading="Provinces")]
    for s in ("Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba"):
        if s not in provs:
            raise SystemExit(f"province {s} not found on {pg.url}")
        out.append(dict(id=state_id(s), name=s, kind="state", state=state_id(s), country="CAN",
                        source=pg.url))
    return out


# --------------------------------------------------------------------------- main
def build(offline: bool = False) -> int:
    class Lazy(dict):
        def __missing__(self, k):
            self[k] = Page(k, offline)
            return self[k]
    P = Lazy()

    cur = current_teams(P)
    arrivals = {}
    stints = []
    for lg, fn in (("NBA", nba_relocations), ("NHL", nhl_relocations), ("MLB", mlb_relocations),
                   ("NFL", nfl_relocations)):
        a, s = fn(P, cur)
        arrivals.update({(lg, k): v for k, v in a.items()})
        stints += s
    stints += defunct_stints(P)
    for league, team, place, first, last, src, text, _why in HAND_TEAMS:
        if last is not None:
            P[src].require(text)
            metro, st = metro_state(place)
            stints.append(dict(league=league, team=team, metro=metro, state=st, first=first,
                               last=last, source=P[src].url))

    team_rows = []
    metro_sources = {}
    for c in cur:
        k = (c["league"], c["team"])
        first = arrivals.get(k, c["first"])
        src = c["source"]
        if k in HAND_FIRST_SEASON:
            first, skey, text, _ = HAND_FIRST_SEASON[k]
            P[skey].require(text)
            src = P[skey].url
        metro = metro_state(c["place"])[0]
        if metro:
            metro_sources.setdefault(metro, c["source"])
        team_rows.append(dict(league=c["league"], team=c["team"], nickname=nickname(c["team"]),
                              metro_id=metro, state_id=c["state_id"], first_season_in_metro=first,
                              active="Y", last_season_in_metro="", source=src))
    for s in stints:
        team_rows.append(dict(league=s["league"], team=s["team"], nickname=nickname(s["team"]),
                              metro_id=s["metro"], state_id=s["state"],
                              first_season_in_metro=s["first"], active="N",
                              last_season_in_metro=s["last"], source=s["source"]))
    for mid in FORMER_ONLY_METROS:
        metro_sources[mid] = P["nhl_reloc"].url
    lg_order = {lg: i for i, lg in enumerate(["NFL", "NBA", "MLB", "NHL", "MLS", "WNBA"])}
    team_rows.sort(key=lambda r: (lg_order[r["league"]], r["active"] == "N", r["team"],
                                  int(r["first_season_in_metro"])))

    title_rows = titles(P)
    title_rows.sort(key=lambda r: (lg_order[r["league"]], r["season"]))
    ent_rows = entities(P, metro_sources)

    # ---- validation
    problems = []
    ids = {e["id"] for e in ent_rows}
    if len(ids) != len(ent_rows):
        problems.append("duplicate entity ids")
    counts = Counter(r["league"] for r in team_rows if r["active"] == "Y")
    expect = {"NFL": 32, "NBA": 30, "MLB": 30, "NHL": 32, "MLS": 30, "WNBA": 15}
    for lg, n in expect.items():
        if counts[lg] != n:
            problems.append(f"{lg}: {counts[lg]} current teams, expected {n}")
    dup = Counter((r["league"], r["team"]) for r in team_rows if r["active"] == "Y")
    problems += [f"current team listed twice: {k}" for k, v in dup.items() if v > 1]
    for r in team_rows + title_rows:
        if r["metro_id"] and r["metro_id"] not in ids:
            problems.append(f"unknown metro {r['metro_id']} in {r}")
        if r["state_id"] and r["state_id"] not in ids:
            problems.append(f"unknown state {r['state_id']} in {r}")
    for r in team_rows:
        if r["active"] == "N" and int(r["last_season_in_metro"]) < int(r["first_season_in_metro"]):
            problems.append(f"bad stint years {r}")
    seen = Counter((r["league"], r["season"]) for r in title_rows)
    problems += [f"two champions for {k}" for k, v in seen.items() if v > 1]
    first_year = {"NFL": 1920, "NBA": 1947, "MLB": 1903, "NHL": 1918, "MLS": 1996, "WNBA": 1997}
    allowed_gaps = {"NFL": {1966}, "MLB": {1904, 1994}, "NHL": {1919, 1925, 2005}}
    for lg, y0 in first_year.items():
        have = {r["season"] for r in title_rows if r["league"] == lg}
        missing = set(range(y0, LAST_TITLE[lg] + 1)) - have - allowed_gaps.get(lg, set())
        if lg == "WNBA":
            missing -= {2026}
        if missing:
            problems.append(f"{lg}: missing title seasons {sorted(missing)}")
    # cross-check against each page's own records-by-franchise table
    for lg, c in franchise_years(P).items():
        n = sum(1 for r in title_rows if r["league"] == lg)
        if c["_total"] != n:
            problems.append(f"{lg}: {n} titles parsed but records table sums to {c['_total']}")
        if lg in ("NBA", "WNBA"):
            have = Counter(r["season"] for r in title_rows if r["league"] == lg)
            listed = Counter({k: v for k, v in c.items() if k != "_total"})
            if listed != have:
                problems.append(f"{lg}: title years differ from records table: "
                                f"{sorted((listed - have).elements())} / {sorted((have - listed).elements())}")

    # ---- write
    DATA.mkdir(parents=True, exist_ok=True)
    write(DATA / "entities.csv", ["id", "name", "kind", "state", "country", "source"], ent_rows)
    write(DATA / "teams.csv", ["league", "team", "nickname", "metro_id", "state_id",
                               "first_season_in_metro", "active", "last_season_in_metro", "source"],
          team_rows)
    write(DATA / "titles.csv", ["league", "season", "team", "metro_id", "state_id", "source"],
          title_rows)

    print(f"entities: {sum(e['kind'] == 'metro' for e in ent_rows)} metros, "
          f"{sum(e['kind'] == 'state' for e in ent_rows)} states/provinces")
    print("current teams:", dict(counts), "| former stints:",
          sum(r["active"] == "N" for r in team_rows))
    print("titles:", dict(Counter(r["league"] for r in title_rows)))
    rng = random.Random(2026)
    print("\nspot check (10 random titles vs the page row):")
    for r in rng.sample(title_rows, 10):
        raw = r["_raw"]
        rawtxt = raw.get("row") or " | ".join(str(v).replace("\n", " ")[:40] for v in list(raw.values())[:5])
        print(f"  {r['league']} {r['season']} {r['team']} -> {r['metro_id'] or '-'} / "
              f"{r['state_id'] or '-'}   [{rawtxt}]")
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print("  -", p)
        return 1
    print("\nall checks passed")
    return 0


def write(path: Path, cols: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="use only cached pages")
    raise SystemExit(build(ap.parse_args().offline))
