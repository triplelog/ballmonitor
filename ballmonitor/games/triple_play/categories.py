"""The baseball categories: each a yes/no rule on a player's facts (facts.py).

Every category has
  test(p)   -> bool    is the player in the circle (the published rule)
  clear(p)  -> bool    False for borderline players a fan couldn't be expected to know
                       (3 games for a team, 60 games at a position); they are never used
                       in a puzzle that has this category
  near(p)   -> float   0-1, how close a non-member comes (for the "outside" near miss)
  close(p)  -> float   0-1, how close to the line from either side: barely in (405 HR for
                       "400 career home runs", 60 games for a team) or barely out; hard days
                       favour close calls, easy days clear-cut players
  fact(p)   -> str     the short line shown on the answer card
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ballmonitor.games.triple_play.facts import FRANCHISES


@dataclass
class Category:
    id: str
    label: str
    rule: str
    kind: str            # team | position | career | season | award | bio
    test: Callable
    clear: Callable = lambda p: True
    near: Callable = lambda p: 0.0
    fact: Callable = lambda p: ""
    hitters: bool | None = None   # True = hitters only, False = pitchers only, None = anyone
    close: Callable = None        # 0-1, how close to the line from either side (hard puzzles favour it)

    def __post_init__(self):
        if self.close is None:
            self.close = self.near


def _fmt(n) -> str:
    return f"{int(n):,}"


def _ramp(v, lo, hi) -> float:
    """0 at lo, 1 just below hi (hi = the threshold)."""
    return 0.0 if v < lo or v >= hi else (v - lo) / (hi - lo)


def team(fid: str, name: str) -> Category:
    return Category(
        f"team_{fid.lower()}", f"Played for the {name}",
        f"Played at least one regular-season game for the {name} franchise (earlier names count).",
        "team", lambda p: p["franch"].get(fid, 0) > 0,
        clear=lambda p: p["franch"].get(fid, 0) == 0 or p["franch"].get(fid, 0) >= 30,
        close=lambda p: (lambda g: 1.0 if 30 <= g < 80 else 0.5 if 80 <= g < 200 else 0.0)(p["franch"].get(fid, 0)),
        fact=lambda p: f"{name}: {_fmt(p['franch'].get(fid, 0))} G" if p["franch"].get(fid, 0) else f"never a {name[:-1] if name.endswith('s') else name}")


POS_SHORT = {"c": "catcher", "1b": "1B", "2b": "2B", "3b": "3B", "ss": "shortstop", "of": "outfield", "p": "pitcher"}


def position(key: str, label: str, hitters: bool = True) -> Category:
    def g(p):
        return p["pos"].get(key, 0)

    def test(p):
        return g(p) >= 100 or (g(p) >= 20 and g(p) * 3 >= p["g"])

    return Category(
        f"pos_{key}", label,
        "At least 100 games at the position, or at least a third of his games (min. 20).",
        "position", test, clear=lambda p: test(p) or g(p) < 10,
        close=lambda p: 1.0 if test(p) and g(p) < 100 else 0.6 if 100 <= g(p) < 250 else 0.0,
        fact=lambda p: f"{POS_SHORT[key]}: {_fmt(g(p))} G", hitters=hitters)


def career(id_, label, rule, get, thr, near_lo, fmt=_fmt, hitters=None, extra=lambda p: True, short="") -> Category:
    band = thr - near_lo

    def close(p):
        if not extra(p):
            return 0.0
        v = get(p)
        return max(0.0, 1 - (v - thr) / band) if v >= thr else _ramp(v, near_lo, thr)

    return Category(id_, label, rule, "career", lambda p: extra(p) and get(p) >= thr,
                    clear=lambda p: True, near=lambda p: _ramp(get(p), near_lo, thr) if extra(p) else 0.0, close=close,
                    fact=lambda p: f"{short}: {fmt(get(p))}",
                    hitters=hitters)


SEASON_SHORT = {"hr": "HR", "h": "hits", "ba_q": "avg", "rbi": "RBI", "sb": "SB", "w": "wins", "so": "K", "sv": "saves", "era_q": "ERA"}


def season(id_, label, rule, key, thr, near_lo, fmt=_fmt, hitters=None, lower_better=False) -> Category:
    if lower_better:
        def test(p):
            return 0 < p["season_max"].get(key, 0) < thr
        near = lambda p: _ramp(-p["season_max"].get(key, 99), -near_lo, -thr) if p["season_max"].get(key) else 0.0  # noqa: E731
    else:
        def test(p):
            return p["season_max"].get(key, 0) >= thr
        near = lambda p: _ramp(p["season_max"].get(key, 0), near_lo, thr)  # noqa: E731
    band = abs(thr - near_lo)

    def close(p):
        v = p["season_max"].get(key, 0)
        if not v:
            return 0.0
        if test(p):
            return max(0.0, 1 - abs(v - thr) / band)
        return near(p)

    return Category(id_, label, rule, "season", test, near=near, close=close,
                    fact=lambda p: f"best season {SEASON_SHORT[key]}: {fmt(p['season_max'].get(key, 0))}"
                    if p["season_max"].get(key) else f"best season {SEASON_SHORT[key]}: -", hitters=hitters)


def _ba(x):
    return f"{x:.3f}".lstrip("0")


def build() -> list[Category]:
    cats = [team(fid, name) for fid, name in FRANCHISES.items()]
    cats += [position("c", "Played catcher"), position("1b", "Played first base"),
             position("2b", "Played second base"), position("3b", "Played third base"),
             position("ss", "Played shortstop"), position("of", "Played outfield"),
             position("p", "Pitched in 100+ games", hitters=False)]
    cats[-1].test = lambda p: p["pos"].get("p", 0) >= 100
    cats[-1].clear = lambda p: p["pos"].get("p", 0) >= 100 or p["pos"].get("p", 0) < 10
    cats[-1].rule = "At least 100 games as a pitcher."
    cats[-1].fact = lambda p: f"pitched: {_fmt(p['pos'].get('p', 0))} G"

    hb = lambda k: (lambda p: p["bat"][k])  # noqa: E731
    pb = lambda k: (lambda p: p["pit"][k])  # noqa: E731
    cats += [
        career("hr500", "500 career home runs", "At least 500 regular-season home runs.", hb("HR"), 500, 430, hitters=True, short="career HR"),
        career("hr400", "400 career home runs", "At least 400 regular-season home runs.", hb("HR"), 400, 340, hitters=True, short="career HR"),
        career("h3000", "3,000 career hits", "At least 3,000 regular-season hits.", hb("H"), 3000, 2600, hitters=True, short="career hits"),
        career("ba300", ".300 career batting average", "Career average of .300 or better (min. 3,000 at-bats).",
               lambda p: p["ba"], 0.300, 0.288, fmt=_ba, hitters=True, extra=lambda p: p["bat"]["AB"] >= 3000, short="career avg"),
        career("sb400", "400 career stolen bases", "At least 400 regular-season stolen bases.", hb("SB"), 400, 330, hitters=True, short="career SB"),
        career("rbi1500", "1,500 career RBI", "At least 1,500 regular-season runs batted in.", hb("RBI"), 1500, 1350, hitters=True, short="career RBI"),
        career("w300", "300 career wins", "At least 300 regular-season wins.", pb("W"), 300, 250, hitters=False, short="career wins"),
        career("w200", "200 career wins", "At least 200 regular-season wins.", pb("W"), 200, 170, hitters=False, short="career wins"),
        career("so3000", "3,000 career strikeouts (pitching)", "At least 3,000 strikeouts as a pitcher.", pb("SO"), 3000, 2600, hitters=False, short="career K"),
        career("sv300", "300 career saves", "At least 300 regular-season saves.", pb("SV"), 300, 240, hitters=False, short="career saves"),
        season("s_hr50", "50-homer season", "Hit at least 50 home runs in one regular season.", "hr", 50, 44, hitters=True),
        season("s_hr40", "40-homer season", "Hit at least 40 home runs in one regular season.", "hr", 40, 35, hitters=True),
        season("s_h200", "200-hit season", "At least 200 hits in one regular season.", "h", 200, 188, hitters=True),
        season("s_ba350", ".350 season", "Batted .350 or better in a season with enough plate appearances to qualify (3.1 per team game).",
               "ba_q", 0.350, 0.338, fmt=_ba, hitters=True),
        season("s_rbi130", "130-RBI season", "At least 130 runs batted in in one regular season.", "rbi", 130, 120, hitters=True),
        season("s_sb50", "50-steal season", "At least 50 stolen bases in one regular season.", "sb", 50, 42, hitters=True),
        Category("s_3030", "30-30 season", "At least 30 home runs and 30 stolen bases in the same season.", "season",
                 lambda p: bool(p["season_max"].get("thirty_thirty")), fact=lambda p: "had a 30-30 season" if p["season_max"].get("thirty_thirty") else "no 30-30 season",
                 hitters=True),
        season("s_w20", "20-win season", "Won at least 20 games in one regular season.", "w", 20, 18, hitters=False),
        season("s_so300", "300-strikeout season", "Struck out at least 300 batters in one season.", "so", 300, 265, hitters=False),
        season("s_sv40", "40-save season", "Saved at least 40 games in one season.", "sv", 40, 35, hitters=False),
        season("s_era2", "Sub-2.00 ERA season", "ERA under 2.00 in a season with at least 1 inning per team game.",
               "era_q", 2.0, 2.25, fmt=lambda x: f"{x:.2f}", hitters=False, lower_better=True),
    ]
    aw = lambda k: (lambda p: p["awards"][k] > 0)  # noqa: E731
    one = lambda k: (lambda p: 0.5 if p["awards"][k] == 1 else 0.0)  # noqa: E731
    awf = lambda k, n: (lambda p: f"{n}: {p['awards'][k]}×" if p["awards"][k] else f"no {n}")  # noqa: E731
    cats += [
        Category("mvp", "Won an MVP", "Won a regular-season Most Valuable Player award.", "award", aw("mvp"), close=one("mvp"), fact=awf("mvp", "MVP")),
        Category("cy", "Won a Cy Young", "Won a Cy Young Award.", "award", aw("cy"), close=one("cy"), fact=awf("cy", "Cy Young"), hitters=False),
        Category("roy", "Rookie of the Year", "Won a Rookie of the Year award.", "award", aw("roy"), close=one("roy"), fact=awf("roy", "ROY")),
        Category("gg", "Won a Gold Glove", "Won at least one Gold Glove.", "award", aw("gg"), close=one("gg"), fact=awf("gg", "Gold Gloves")),
        Category("silver", "Won a Silver Slugger", "Won at least one Silver Slugger.", "award", aw("ss"), close=one("ss"), fact=awf("ss", "Silver Sluggers"), hitters=True),
        Category("as10", "10+ All-Star selections", "Named to at least 10 MLB All-Star teams (seasons with two games count once).", "award",
                 lambda p: p["n_allstar"] >= 10, near=lambda p: _ramp(p["n_allstar"], 7, 10),
                 close=lambda p: 0.7 if 10 <= p["n_allstar"] <= 11 else _ramp(p["n_allstar"], 7, 10), fact=lambda p: f"All-Star: {p['n_allstar']}×"),
        Category("hof", "Hall of Famer", "Inducted into the Hall of Fame as a player.", "award", lambda p: p["hof"],
                 near=lambda p: 0.8 if p["hof_ballot"] and not p["hof"] else 0.0,
                 fact=lambda p: "Hall of Famer" if p["hof"] else "not in the Hall"),
        Category("ws", "Won a World Series", "Played for a World Series champion during its title season (1903 on).", "award",
                 lambda p: bool(p["ws_titles"]),
                 clear=lambda p: not p["ws_titles"] or any(g >= 20 for _, g in p["ws_titles"]),
                 close=lambda p: 0.6 if p["ws_titles"] and max(g for _, g in p["ws_titles"]) < 60 else 0.0,
                 fact=lambda p: ("won the WS: " + ", ".join(str(y) for y, _ in p["ws_titles"][:4])) if p["ws_titles"] else "no WS title"),
    ]
    cats += [
        Category("born_intl", "Born outside the U.S.", "Born outside the United States (players born in Puerto Rico, a U.S. territory, are never used with this circle).", "bio",
                 lambda p: p["birth_country"] not in ("USA", ""), clear=lambda p: p["birth_country"] not in ("", "P.R."),
                 fact=lambda p: f"born in {p['birth_country'] if p['birth_country'] != 'USA' else p['birth_state']}"),
        Category("born_dr", "Born in the Dominican Republic", "Birth country is the Dominican Republic.", "bio",
                 lambda p: p["birth_country"] == "D.R.", clear=lambda p: p["birth_country"] != "",
                 fact=lambda p: f"born in {p['birth_country'] if p['birth_country'] != 'USA' else p['birth_state']}"),
        Category("born_ca", "Born in California", "Born in California.", "bio",
                 lambda p: p["birth_country"] == "USA" and p["birth_state"] == "CA", clear=lambda p: p["birth_country"] != "",
                 fact=lambda p: f"born in {p['birth_state'] if p['birth_country'] == 'USA' else p['birth_country']}"),
        Category("lefty_bat", "Batted left-handed", "Listed as batting left-handed (switch-hitters don't count).", "bio",
                 lambda p: p["bats"] == "L", clear=lambda p: p["bats"] in ("L", "R", "B"),
                 close=lambda p: 0.7 if p["bats"] == "B" else 0.0,
                 fact=lambda p: {"L": "bats left", "R": "bats right", "B": "switch-hitter"}.get(p["bats"], "?"), hitters=True),
        Category("switch", "Switch-hitter", "Listed as a switch-hitter.", "bio", lambda p: p["bats"] == "B",
                 clear=lambda p: p["bats"] in ("L", "R", "B"),
                 fact=lambda p: {"L": "bats left", "R": "bats right", "B": "switch-hitter"}.get(p["bats"], "?"), hitters=True),
        Category("lefty_throw", "Threw left-handed", "Listed as throwing left-handed.", "bio", lambda p: p["throws"] == "L",
                 clear=lambda p: p["throws"] in ("L", "R"), fact=lambda p: f"throws {'left' if p['throws'] == 'L' else 'right'}"),
        Category("seasons20", "Played 20+ seasons", "Appeared in the majors in at least 20 different seasons.", "bio",
                 lambda p: p["seasons"] >= 20, near=lambda p: _ramp(p["seasons"], 17, 20),
                 close=lambda p: 0.7 if 20 <= p["seasons"] <= 21 else _ramp(p["seasons"], 17, 20), fact=lambda p: f"{p['seasons']} seasons"),
        Category("franch5", "Played for 5+ franchises", "Appeared for at least 5 different franchises.", "bio",
                 lambda p: p["n_franch"] >= 5, near=lambda p: 0.7 if p["n_franch"] == 4 else 0.0,
                 close=lambda p: 0.7 if p["n_franch"] in (4, 5) else 0.0,
                 fact=lambda p: f"{p['n_franch']} franchises"),
        Category("pre1970", "Debuted before 1970", "First major-league game before 1970.", "bio",
                 lambda p: p["first"] < 1970, near=lambda p: _ramp(-p["first"], -1975, -1969),
                 close=lambda p: max(0.0, 1 - abs(p["first"] - 1969.5) / 5),
                 fact=lambda p: f"debut {p['first']}"),
        Category("post2000", "Debuted in 2000 or later", "First major-league game in 2000 or later.", "bio",
                 lambda p: p["first"] >= 2000, near=lambda p: _ramp(p["first"], 1995, 2000),
                 close=lambda p: max(0.0, 1 - abs(p["first"] - 1999.5) / 5), fact=lambda p: f"debut {p['first']}"),
    ]
    return cats


CATEGORIES = {c.id: c for c in build()}
