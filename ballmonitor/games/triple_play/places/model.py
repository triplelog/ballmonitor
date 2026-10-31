"""Places pack (cities & states): facts from places/data/*.csv (DATA_SPEC.md) and the categories.

An entity is a metro area or a state/province. A state's facts aggregate everything located
in it (teams by `state_id`, schools, events), so "Has an NFL team" works for both kinds.
Categories that only make sense for one kind (e.g. "Borders Canada", "Lost a team to
relocation") mark the other kind as not clear, so it never appears in those puzzles.
"""

from __future__ import annotations

import csv
import datetime as dt
import random
from collections import defaultdict
from pathlib import Path

from ballmonitor.games.triple_play.categories import Category

DATA = Path(__file__).parent / "data"
BIG4 = ("NFL", "NBA", "MLB", "NHL")
LEAGUES = BIG4 + ("MLS", "WNBA")
LEAGUE_NAME = {"NFL": "an NFL", "NBA": "an NBA", "MLB": "an MLB", "NHL": "an NHL", "MLS": "an MLS", "WNBA": "a WNBA"}
SEASON = 2026
BIRDS = {"Cardinals", "Blue Jays", "Orioles", "Ravens", "Eagles", "Falcons", "Seahawks", "Pelicans", "Hawks",
         "Penguins", "Ducks"}
BIG_CATS = {"Lions", "Tigers", "Jaguars", "Bengals", "Panthers"}
COLORS = ("Red", "White", "Blue", "Black", "Brown", "Gold")
REGION_NAMES = {"Minnesota", "Texas", "Arizona", "Colorado", "Utah", "Carolina", "Tennessee", "New England",
                "Florida", "Golden State", "Indiana", "New Jersey", "Tampa Bay"}


# campus cities in college_towns.csv that are big cities rather than college towns
NOT_COLLEGE_TOWNS = {"louisville", "syracuse"}

# places a fan could fairly argue either way for a circle: never used in puzzles with it
DEBATABLE = {
    "pacific": {"seattle", "vancouver"},            # Puget Sound / Strait of Georgia, not open ocean
    "great_lakes": {"detroit"},                     # Detroit River + Lake St. Clair
    "atlantic": {"connecticut", "quebec"},          # Long Island Sound / Gulf of St. Lawrence
    "borders_canada": {"ohio", "pennsylvania"},     # only a water boundary in Lake Erie
}


def _rows(name):
    path = DATA / f"{name}.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _i(x, default=0):
    try:
        return int(str(x).strip()[:4])
    except (TypeError, ValueError):
        return default


def load() -> dict[str, dict]:
    E: dict[str, dict] = {}
    for r in _rows("entities"):
        E[r["id"]] = {"id": r["id"], "name": r["name"], "kind": r["kind"], "state": r.get("state", ""),
                      "country": r.get("country", "USA"), "teams": [], "stints": [], "titles": [],
                      "colleges": set(), "events": set(), "geo": {}}

    for r in _rows("college_towns"):      # campus towns of power-conference schools (no pro team needed)
        E[r["id"]] = {"id": r["id"], "name": r["name"], "kind": "metro", "state": r["state_id"],
                      "country": r.get("country") or "USA", "teams": [], "stints": [], "titles": [],
                      "colleges": set(), "events": set(), "geo": {},
                      "college_town": r["id"] not in NOT_COLLEGE_TOWNS}

    def owners(metro_id, state_id):
        return [e for e in (E.get(metro_id), E.get(state_id)) if e]

    for r in _rows("teams"):
        stint = {"league": r["league"], "team": r["team"], "nickname": r.get("nickname") or r["team"].split()[-1],
                 "first": _i(r["first_season_in_metro"]), "active": r.get("active", "Y") == "Y",
                 "last": _i(r.get("last_season_in_metro"), SEASON), "metro": r["metro_id"], "state": r["state_id"]}
        for e in owners(r["metro_id"], r["state_id"]):
            e["stints"].append(stint)
            if stint["active"]:
                e["teams"].append(stint)
    for r in _rows("titles"):
        for e in owners(r["metro_id"], r["state_id"]):
            e["titles"].append((r["league"], _i(r["season"])))
    for r in _rows("colleges"):
        for e in owners(r.get("metro_id", ""), r["state_id"]):
            e["colleges"].add(r["conference"])
    for r in _rows("events"):
        for e in owners(r.get("metro_id", ""), r["state_id"]):
            e["events"].add(r["event"])
    for e in E.values():
        e.setdefault("ncaa", [])
    for r in _rows("college_titles"):
        for e in owners(r.get("metro_id", ""), r["state_id"]):
            e["ncaa"].append((r["sport"], _i(r["year"])))
    for r in _rows("geo") + _rows("geo_college"):
        if r["id"] in E:
            E[r["id"]]["geo"] = {k: v for k, v in r.items() if k != "id"}

    for e in E.values():
        t = e["teams"]
        e["leagues"] = {s["league"] for s in t}
        e["big4"] = [s for s in t if s["league"] in BIG4]
        firsts = [s["first"] for s in e["stints"] if s["league"] in BIG4 and s["first"]]
        e["first_big4"] = min(firsts) if firsts else None
        e["first_by_league"] = {}
        for s in e["stints"]:
            if s["first"]:
                e["first_by_league"][s["league"]] = min(s["first"], e["first_by_league"].get(s["league"], 9999))
        e["big4_titles"] = [t for t in e["titles"] if t[0] in BIG4]
        e["lost"] = [s for s in e["stints"] if s["league"] in BIG4 and not s["active"] and s["last"] >= 1951]
        state_name = E[e["state"]]["name"].replace(" State", "") if e["state"] in E else ""
        e["sub"] = "State" if e["kind"] == "state" and e["country"] == "USA" else \
            "Province" if e["kind"] == "state" else \
            (f"{'City' if e.get('college_town') else 'Metro'} · {state_name}" if state_name else "Metro area")
        # prominence for weighting (all places are recognisable; busier markets a bit more often)
        e["fame"] = 20 + 3 * len(t) + 2 * len(e["big4"]) + min(len(e["big4_titles"]), 20) + min(len(e["ncaa"]), 10)
        if e.get("college_town"):
            e["fame"] += 12 + 2 * min(len(e["ncaa"]), 8)   # so campus towns show up as often as pro markets
    return E


# ---- categories -------------------------------------------------------------------------

def C(id_, label, rule, kind, test, clear=lambda e: True, fact=lambda e: "", close=None, near=lambda e: 0.0):
    return Category(id_, label, rule, kind, test, clear=clear, near=near, fact=fact, close=close)


def _teams_fact(e, leagues=LEAGUES):
    names = [s["nickname"] for s in e["teams"] if s["league"] in leagues]
    return ", ".join(names[:4]) + (f" +{len(names) - 4}" if len(names) > 4 else "") if names else "none"


def _titles_in(e, lo, hi, leagues=BIG4):
    return [t for t in e["titles"] if t[0] in leagues and lo <= t[1] <= hi]


def build() -> list[Category]:
    cats: list[Category] = []
    for lg in LEAGUES:
        cats.append(C(f"has_{lg.lower()}", f"Has {LEAGUE_NAME[lg]} team", f"Has {LEAGUE_NAME[lg]} team in the {SEASON} season.",
                      "league", lambda e, lg=lg: lg in e["leagues"],
                      clear=(lambda e: not (lg == "MLB" and e["id"] == "sacramento")),
                      fact=lambda e, lg=lg: f"{lg}: {_teams_fact(e, (lg,))}"))
    cats += [
        C("all4", "Teams in all four major leagues", "Has a current NFL, NBA, MLB and NHL team.", "count",
          lambda e: set(BIG4) <= e["leagues"], fact=lambda e: f"leagues: {', '.join(sorted(e['leagues'] & set(BIG4))) or 'none'}",
          close=lambda e: 0.8 if len(e["leagues"] & set(BIG4)) == 3 else 0.0),
        C("two_same", "Two teams in the same major league", "Has at least two current teams in one of the NFL, NBA, MLB or NHL.",
          "count", lambda e: any(sum(s["league"] == lg for s in e["big4"]) >= 2 for lg in BIG4),
          fact=lambda e: f"{len(e['big4'])} major-league teams"),
        C("one_team", "Exactly one major-league team", "Has exactly one current NFL, NBA, MLB or NHL team.", "count",
          lambda e: len(e["big4"]) == 1, fact=lambda e: f"{len(e['big4'])} major-league teams ({_teams_fact(e, BIG4)})"),
        C("no_big4", "No major-league team", "Has no current NFL, NBA, MLB or NHL team.", "count",
          lambda e: not e["big4"], fact=lambda e: f"{len(e['big4'])} major-league teams"),
        C("five_plus", "5+ major-league teams", "Has at least five current NFL, NBA, MLB and NHL teams combined.", "count",
          lambda e: len(e["big4"]) >= 5, fact=lambda e: f"{len(e['big4'])} major-league teams",
          close=lambda e: 0.8 if len(e["big4"]) in (4, 5) else 0.0),
    ]
    for lo, hi, lab in ((2020, SEASON, "2020s"), (2010, 2019, "2010s"), (2000, 2009, "2000s"), (1990, 1999, "1990s")):
        cats.append(C(f"title_{lab}", f"Major-league title in the {lab}",
                      f"A team based there won the Super Bowl/NFL title, NBA Finals, World Series or Stanley Cup in the {lab}.",
                      "title", lambda e, lo=lo, hi=hi: bool(_titles_in(e, lo, hi)),
                      fact=lambda e, lo=lo, hi=hi: ("won: " + ", ".join(f"{l} {y}" for l, y in sorted(_titles_in(e, lo, hi), key=lambda t: t[1])[:3]))
                      if _titles_in(e, lo, hi) else f"no title {lo}-{min(hi, SEASON)}"))
    trophy = {"NFL": ("super_bowl", "Won a Super Bowl", "Won a Super Bowl (1967 on).", 1967),
              "MLB": ("world_series", "Won a World Series", "Won a World Series.", 1903),
              "NBA": ("nba_title", "Won an NBA title", "Won an NBA (or BAA) championship.", 1947),
              "NHL": ("stanley_cup", "Won a Stanley Cup", "Won a Stanley Cup (NHL era, 1918 on).", 1918),
              "MLS": ("mls_cup", "Won an MLS Cup", "Won an MLS Cup.", 1996),
              "WNBA": ("wnba_title", "Won a WNBA title", "Won a WNBA championship.", 1997)}
    for lg, (id_, label, rule, since) in trophy.items():
        cats.append(C(id_, label, rule, "title", lambda e, lg=lg, since=since: any(l == lg and y >= since for l, y in e["titles"]),
                      fact=lambda e, lg=lg, since=since: (lambda n: f"{lg} titles: {n}")(sum(l == lg and y >= since for l, y in e["titles"]))))
    cats += [
        C("never_title", "Never won a major-league title", "Has had an NFL, NBA, MLB or NHL team but none has won its league's title there.",
          "title", lambda e: not e["big4_titles"], clear=lambda e: bool(e["stints"] and any(s["league"] in BIG4 for s in e["stints"])),
          fact=lambda e: f"major titles: {len(e['big4_titles'])}"),
        C("ten_titles", "10+ major-league titles", "Teams based there have won at least 10 NFL/NBA/MLB/NHL titles combined.",
          "title", lambda e: len(e["big4_titles"]) >= 10, fact=lambda e: f"major titles: {len(e['big4_titles'])}",
          close=lambda e: 0.8 if 7 <= len(e["big4_titles"]) <= 12 else 0.0),
        C("first_pre1920", "Major-league team before 1920", "Its first NFL, NBA, MLB or NHL team (any franchise, past or present) started before 1920.",
          "history", lambda e: bool(e["first_big4"]) and e["first_big4"] < 1920, fact=lambda e: f"first major team: {e['first_big4'] or 'never'}"),
        C("first_post1990", "First major-league team after 1990", "Its first NFL, NBA, MLB or NHL team arrived in 1991 or later.",
          "history", lambda e: bool(e["first_big4"]) and e["first_big4"] > 1990, clear=lambda e: bool(e["first_big4"]),
          fact=lambda e: f"first major team: {e['first_big4'] or 'never'}"),
        C("nfl_post1990", "Got its NFL team after 1990", "Its first NFL team arrived in 1991 or later.",
          "history", lambda e: e["first_by_league"].get("NFL", 0) > 1990, clear=lambda e: "NFL" in e["first_by_league"],
          fact=lambda e: f"first NFL season: {e['first_by_league'].get('NFL', 'never')}"),
        C("mlb_pre1920", "MLB team before 1920", "Had an MLB team (any franchise) before 1920.",
          "history", lambda e: 0 < e["first_by_league"].get("MLB", 9999) < 1920,
          fact=lambda e: f"first MLB season: {e['first_by_league'].get('MLB', 'never')}"),
        C("lost_team", "Lost a team to relocation", "A metro that saw an NFL, NBA, MLB or NHL team move away or fold (1951 or later).",
          "history", lambda e: bool(e["lost"]), clear=lambda e: e["kind"] == "metro",
          fact=lambda e: ("lost: " + ", ".join(s["team"] for s in e["lost"][:2])) if e["lost"] else "never lost a team"),
        C("bird", "Has a team named after a bird", "A current NFL/NBA/MLB/NHL team is named after a bird (Cardinals, Blue Jays, Orioles, Ravens, Eagles, Falcons, Seahawks, Pelicans, Hawks, Penguins, Ducks).",
          "names", lambda e: any(s["nickname"] in BIRDS for s in e["big4"]),
          fact=lambda e: ", ".join(s["nickname"] for s in e["big4"] if s["nickname"] in BIRDS) or "no bird"),
        C("big_cat", "Has a team named after a big cat", "A current NFL/NBA/MLB/NHL team is named after a big cat (Lions, Tigers, Jaguars, Bengals, Panthers).",
          "names", lambda e: any(s["nickname"] in BIG_CATS for s in e["big4"]),
          fact=lambda e: ", ".join(s["nickname"] for s in e["big4"] if s["nickname"] in BIG_CATS) or "no big cat"),
        C("color_name", "Has a team with a color in its name", "A current NFL/NBA/MLB/NHL nickname contains a color: red, white, blue, black, brown or gold (Red Sox, Blue Jays, Blackhawks, Golden Knights...).",
          "names", lambda e: any(any(c in s["nickname"] for c in COLORS) for s in e["big4"]),
          fact=lambda e: ", ".join(s["nickname"] for s in e["big4"] if any(c in s["nickname"] for c in COLORS)) or "no color"),
        C("no_s", "Has a team name not ending in S", "A current NFL/NBA/MLB/NHL nickname doesn't end in the letter s (Heat, Magic, Jazz, Thunder, Lightning, Avalanche, Wild, Kraken, Red Sox...).",
          "names", lambda e: any(not s["nickname"].lower().endswith("s") for s in e["big4"]),
          fact=lambda e: ", ".join(s["nickname"] for s in e["big4"] if not s["nickname"].lower().endswith("s")) or "all end in s"),
        C("region_name", "Has a team named for a state or region", "A current NFL/NBA/MLB/NHL team carries a state, province or region name instead of a city (Minnesota, Texas, Carolina, New England, Golden State, Tampa Bay...).",
          "names", lambda e: any(s["team"].replace(s["nickname"], "").strip() in REGION_NAMES for s in e["big4"]),
          fact=lambda e: ", ".join(s["team"] for s in e["big4"] if s["team"].replace(s["nickname"], "").strip() in REGION_NAMES) or "city names only"),
        C("super_bowl_host", "Hosted a Super Bowl", "A Super Bowl (I-LX) was played there.", "events",
          lambda e: "super_bowl" in e["events"], fact=lambda e: "hosted a Super Bowl" if "super_bowl" in e["events"] else "never hosted"),
        C("olympics", "Hosted the Olympics", "Hosted a Summer or Winter Olympics (1904-2010; LA 2028 not yet).", "events",
          lambda e: bool({"olympics_summer", "olympics_winter"} & e["events"]),
          fact=lambda e: "hosted the Olympics" if {"olympics_summer", "olympics_winter"} & e["events"] else "no Olympics"),
        C("world_cup", "2026 World Cup host", "Hosts matches at the 2026 FIFA World Cup.", "events",
          lambda e: "world_cup_2026" in e["events"], fact=lambda e: "2026 World Cup host" if "world_cup_2026" in e["events"] else "not a host"),
    ]
    for conf in ("SEC", "Big Ten", "ACC", "Big 12"):
        cats.append(C(f"conf_{conf.lower().replace(' ', '')}", f"Has {'an' if conf[0] in 'AS' else 'a'} {conf} school",
                      f"A {conf} member (2026-27) has its campus there.", "college",
                      lambda e, conf=conf: conf in e["colleges"],
                      fact=lambda e, conf=conf: f"{conf}: yes" if conf in e["colleges"] else f"no {conf} school"))
    def ncaa_years(e, sports):
        return sorted(y for x, y in e["ncaa"] if x in sports)

    cats += [
        C("cfp_title", "College football national title (1998-)",
          "A school there won the BCS or College Football Playoff national title (1998 season on).", "college",
          lambda e: bool(ncaa_years(e, {"football"})),
          fact=lambda e: (lambda ys: "football title: " + (", ".join(map(str, ys[-3:])) if ys else "none"))(ncaa_years(e, {"football"}))),
        C("ncaa_bb", "NCAA basketball title (men's or women's)",
          "A school there won the NCAA Division I men's or women's basketball tournament.", "college",
          lambda e: bool(ncaa_years(e, {"mbb", "wbb"})),
          fact=lambda e: (lambda m, w: "basketball titles: " + (", ".join([f"men {y}" for y in m[-2:]] + [f"women {y}" for y in w[-2:]]) or "none"))(
              ncaa_years(e, {"mbb"}), ncaa_years(e, {"wbb"}))),
    ]
    g = lambda k: (lambda e: e["geo"].get(k) == "Y")  # noqa: E731
    cats += [
        C("atlantic", "On the Atlantic coast", "Has an Atlantic Ocean coastline.", "geo", g("coast_atlantic"), fact=lambda e: "Atlantic coast" if g("coast_atlantic")(e) else "not Atlantic"),
        C("pacific", "On the Pacific coast", "Has a Pacific Ocean coastline.", "geo", g("coast_pacific"), fact=lambda e: "Pacific coast" if g("coast_pacific")(e) else "not Pacific"),
        C("gulf", "On the Gulf coast", "Has a Gulf coastline (Gulf of Mexico/America).", "geo", g("coast_gulf"), fact=lambda e: "Gulf coast" if g("coast_gulf")(e) else "not on the Gulf"),
        C("great_lakes", "On the Great Lakes", "Touches one of the five Great Lakes.", "geo", g("great_lakes"), fact=lambda e: "Great Lakes" if g("great_lakes")(e) else "no Great Lake"),
        C("borders_canada", "Borders Canada", "A U.S. state that shares a border with Canada.", "geo", g("borders_canada"),
          clear=lambda e: e["kind"] == "state" and e["country"] == "USA", fact=lambda e: "borders Canada" if g("borders_canada")(e) else "no Canada border"),
        C("capital", "Is a capital city", "The city is its state's or province's capital, or the national capital (Washington, Ottawa). Cities only.", "geo",
          g("capital"), clear=lambda e: e["kind"] == "metro", fact=lambda e: "capital" if g("capital")(e) else "not a capital"),
        C("canada", "In Canada", "In Canada.", "geo", lambda e: e["country"] == "CAN", fact=lambda e: "Canada" if e["country"] == "CAN" else "U.S."),
        C("is_state", "Is a state or province", "The card is a U.S. state or a Canadian province (not a metro area).", "type",
          lambda e: e["kind"] == "state", fact=lambda e: e["sub"]),
    ]
    return cats


def _apply_debatable(cats: list[Category]) -> list[Category]:
    for c in cats:
        bad = DEBATABLE.get(c.id)
        if bad:
            c.clear = (lambda base, bad: (lambda e: base(e) and e["id"] not in bad))(c.clear, bad)
    return cats


CATEGORIES = {c.id: c for c in _apply_debatable(build())}
KINDS = ("league", "count", "title", "history", "names", "events", "college", "geo", "type")


def maker(entities: dict[str, dict]):
    """(day, level, recent, yesterday) -> puzzle for the places pack (plugs into generate.generate)."""
    from ballmonitor.games.triple_play import generate as G

    by_kind: dict[str, list[Category]] = defaultdict(list)
    for c in CATEGORIES.values():
        by_kind[c.kind].append(c)
    members = {cid: {e["id"] for e in entities.values() if c.test(e) and c.clear(e)} for cid, c in CATEGORIES.items()}
    base = list(entities.values())

    def pick(rng: random.Random):
        kinds = rng.sample([k for k in KINDS if k != "type"], 3)
        if rng.random() < 0.07:
            kinds[rng.randrange(3)] = "type"
        return [rng.choice(by_kind[k]) for k in kinds]

    def ok(cats):
        for a, b in [(0, 1), (0, 2), (1, 2)]:
            sa, sb = members[cats[a].id], members[cats[b].id]
            if not sa or not sb:
                return False
            inter = len(sa & sb)
            if inter / min(len(sa), len(sb)) > 0.85 or inter / len(sa | sb) > 0.55:
                return False
        return True

    def make(day: dt.date, level, recent, yesterday):
        rng = random.Random(f"triple-play-places-{day.isoformat()}")
        puzzle = G.build_puzzle(rng, base, pick, ok, "medium", recent, yesterday,
                                card_extra=lambda e: {"sub": e["sub"]}, beta=0.0, choose="random")
        if not puzzle:
            raise RuntimeError(f"no valid places puzzle for {day}")
        puzzle["pack"] = "places"
        return puzzle
    return make
