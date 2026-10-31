"""Matchup classification and auto-detection for college and pro sports."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Major College Baseball, Softball & Basketball Conferences
COLLEGE_CONFERENCES: dict[str, list[str]] = {
    "SEC": [
        "tennessee", "texas a&m", "kentucky", "lsu", "arkansas", "florida", "georgia",
        "vanderbilt", "south carolina", "mississippi state", "ole miss", "alabama",
        "auburn", "missouri", "texas", "oklahoma"
    ],
    "ACC": [
        "north carolina", "florida state", "virginia", "clemson", "wake forest", "duke",
        "nc state", "louisville", "miami", "georgia tech", "virginia tech", "boston college",
        "notre dame", "pittsburgh", "pitt", "stanford", "california", "cal", "smu"
    ],
    "Big 12": [
        "oklahoma state", "tcu", "texas tech", "west virginia", "kansas state", "kansas",
        "baylor", "ucf", "houston", "byu", "cincinnati", "arizona", "arizona state", "utah",
        "iowa state", "west virginia",
        "iowa state"
    ],
    "Big Ten": [
        "indiana", "iowa", "maryland", "michigan", "michigan state", "nebraska",
        "ohio state", "penn state", "purdue", "rutgers", "illinois", "minnesota",
        "northwestern", "usc", "ucla", "washington", "oregon", "wisconsin"
    ],
    "Sun Belt": [
        "coastal carolina", "southern miss", "louisiana", "troy", "georgia southern",
        "texas state", "old dominion", "appalachian state", "app state", "james madison",
        "jmu", "south alabama", "marshall", "georgia state", "ulm", "arkansas state"
    ],
    "Pac-12": [
        "oregon state", "washington state"
    ],
    "American": [
        "east carolina", "ecu", "wichita state", "south florida", "usf", "charlotte",
        "tulane", "florida atlantic", "fau", "memphis", "uab", "rice", "utsa"
    ],
    "Big East": [
        "uconn", "connecticut", "st johns", "st. john's", "xavier", "creighton",
        "georgetown", "seton hall", "villanova", "butler", "marquette", "providence"
    ],
    "Big West": [
        "uc santa barbara", "ucsb", "uc irvine", "uci", "cal poly", "cal state fullerton",
        "long beach state", "dirtbags", "hawaii", "csun", "uc san diego", "uc davis",
        "uc riverside", "csu bakersfield"
    ],
    "WCC": [
        "gonzaga", "san diego", "portland", "saint mary's", "pepperdine", "santa clara",
        "san francisco", "loyola marymount", "lmu", "pacific"
    ],
    "C-USA": [
        "dallas baptist", "dbu", "western kentucky", "wku", "liberty", "louisiana tech",
        "sam houston", "fiu", "middle tennessee", "mtsu", "jacksonville state", "new mexico state"
    ],
}

# MLB Divisions
MLB_DIVISIONS: dict[str, list[str]] = {
    "AL East": ["yankees", "orioles", "red sox", "rays", "blue jays"],
    "AL Central": ["guardians", "royals", "tigers", "twins", "white sox"],
    "AL West": ["astros", "mariners", "rangers", "athletics", "angels"],
    "NL East": ["phillies", "braves", "mets", "nationals", "marlins"],
    "NL Central": ["brewers", "cubs", "cardinals", "reds", "pirates"],
    "NL West": ["dodgers", "padres", "diamondbacks", "d-backs", "giants", "rockies"],
}

# State school token disqualifiers to prevent false positives (e.g. "texas" matching "texas tech")
_DISQUALIFIERS: dict[str, list[str]] = {
    "texas": [r"\btexas\s+tech\b", r"\btexas\s+state\b"],
    "tennessee": [r"\btennessee\s+tech\b", r"\btennessee\s+state\b"],
    "florida": [r"\bflorida\s+state\b", r"\bflorida\s+a&m\b", r"\bflorida\s+atlantic\b", r"\bfau\b", r"\bfgc\b"],
    "georgia": [r"\bgeorgia\s+tech\b", r"\bgeorgia\s+southern\b", r"\bgeorgia\s+state\b"],
    "virginia": [r"\bvirginia\s+tech\b"],
    "louisiana": [r"\blouisiana\s+tech\b", r"\blouisiana\s+monroe\b", r"\bulm\b"],
    "kansas": [r"\bkansas\s+state\b"],
    "michigan": [r"\bmichigan\s+state\b"],
    "oklahoma": [r"\boklahoma\s+state\b"],
    "oregon": [r"\boregon\s+state\b"],
    "washington": [r"\bwashington\s+state\b"],
    "arizona": [r"\barizona\s+state\b"],
    "mississippi": [r"\bmississippi\s+state\b"],
    "appalachian": [r"\bappalachian\s+state\b"],
    "penn": [r"\bpenn\s+state\b"],
}


# A school token preceded by one of these words names a different school
# ("West Virginia" is not "Virginia", "South Florida" is not "Florida") ...
_PREFIX_DISQUALIFIERS = {
    "north", "south", "east", "west", "northern", "southern", "eastern", "western",
    "central", "middle", "little", "northeastern", "northwestern", "southeastern",
    "southwestern", "george", "upper",
}
# ... and so does a token followed by one of these ("Iowa State", "Kentucky" vs "Kentucky
# Christian", "Texas A&M-Corpus Christi").
_SUFFIX_DISQUALIFIERS = {
    "state", "tech", "a&m", "a&t", "southern", "christian", "international", "gulf",
    "atlantic", "baptist", "wesleyan", "upstate", "poly", "central", "martin", "arlington",
    "rio", "corpus", "commerce", "pine", "valley", "(oh)", "oh", "ohio", "monroe",
    "birmingham", "wilmington", "asheville", "greensboro", "charlotte", "city",
}


def _matches_team_token(token: str, full_name: str) -> bool:
    clean_name = full_name.lower().replace(".", "").replace("-", " ")
    for disq in _DISQUALIFIERS.get(token, []):
        if re.search(disq, clean_name, re.IGNORECASE):
            return False
    pattern = r"(?<![\w&])" + re.escape(token) + r"(?![\w&])"
    for m in re.finditer(pattern, clean_name, re.IGNORECASE):
        before = clean_name[: m.start()].split()
        after = clean_name[m.end():].split()
        if before and before[-1] in _PREFIX_DISQUALIFIERS:
            continue
        if after and after[0] in _SUFFIX_DISQUALIFIERS:
            continue
        return True
    return False


def detect_college_conference(team_name: str) -> str | None:
    """Identify which NCAA conference a team belongs to (longest matching school name wins)."""
    best: tuple[int, str] | None = None
    for conf, tokens in COLLEGE_CONFERENCES.items():
        for token in tokens:
            if _matches_team_token(token, team_name) and (best is None or len(token) > best[0]):
                best = (len(token), conf)
    return best[1] if best else None


def detect_mlb_division(team_name: str) -> str | None:
    """Identify which MLB division a team belongs to."""
    clean = team_name.lower().replace(".", "").replace("-", " ")
    for div, tokens in MLB_DIVISIONS.items():
        for token in tokens:
            pattern = r"\b" + re.escape(token) + r"\b"
            if re.search(pattern, clean, re.IGNORECASE):
                return div
    return None


SOCCER_DERBIES: list[tuple[set[str], set[str], str]] = [
    ({"arsenal"}, {"tottenham", "spurs", "tottenham hotspur"}, "North London Derby"),
    ({"manchester city", "man city", "city"}, {"manchester united", "man united", "man utd", "united"}, "Manchester Derby"),
    ({"liverpool"}, {"everton"}, "Merseyside Derby"),
    ({"real madrid"}, {"barcelona", "barca"}, "El Clásico"),
    ({"real madrid"}, {"atletico madrid", "atlético madrid", "atletico"}, "Madrid Derby"),
    ({"bayern munich", "bayern"}, {"borussia dortmund", "dortmund", "bvb"}, "Der Klassiker"),
    ({"inter milan", "inter"}, {"ac milan", "milan"}, "Derby della Madonnina"),
    ({"paris saint-germain", "psg"}, {"marseille", "om"}, "Le Classique"),
    ({"la galaxy", "galaxy"}, {"lafc", "los angeles fc"}, "El Tráfico"),
    ({"seattle sounders", "sounders"}, {"portland timbers", "timbers"}, "Cascadia Derby"),
]


def _club_key(name: str) -> str:
    """Normalise a club name for exact matching: lowercase, drop FC/AFC/CF affixes."""
    words = re.sub(r"[.,]", " ", name.lower()).split()
    words = [w for w in words if w not in ("fc", "afc", "cf")]
    return " ".join(words)


def detect_soccer_derby(team_a: str, team_b: str) -> str | None:
    """Identify if two teams share a famous domestic soccer derby.

    Names are matched exactly (after dropping FC/AFC), so "Leicester City" is not
    "Manchester City" and "Newcastle United" is not "Manchester United".
    """
    a_key = _club_key(team_a)
    b_key = _club_key(team_b)

    for set1, set2, derby_name in SOCCER_DERBIES:
        match_1_a = a_key in set1
        match_2_b = b_key in set2
        match_1_b = b_key in set1
        match_2_a = a_key in set2

        if (match_1_a and match_2_b) or (match_1_b and match_2_a):
            return derby_name
    return None


def parse_date_metadata(date_val: Any, sport: str = "") -> tuple[str | None, bool | None, bool | None]:
    """Parse date into (day_name, is_weekend, is_postseason)."""
    if not date_val:
        return None, None, None

    date_str = str(date_val).strip()
    formats = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%b %d, %Y", "%Y%m%d")
    s = sport.lower()

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str[:10], fmt)
            day_name = dt.strftime("%A")
            is_weekend = dt.weekday() in (4, 5, 6)

            if "wbb" in s or "basket" in s:
                is_postseason = (dt.month == 3 and dt.day >= 12) or (dt.month == 4 and dt.day <= 10)
            elif "softball" in s:
                is_postseason = (dt.month == 5 and dt.day >= 14) or (dt.month == 6)
            else:
                is_postseason = (dt.month == 5 and dt.day >= 20) or (dt.month == 6)

            return day_name, is_weekend, is_postseason
        except ValueError:
            continue

    return None, None, None


def classify_game(
    team_name: str,
    opponent_name: str,
    game: dict[str, Any],
    sport: str,
) -> dict[str, Any]:
    """Automatically detect whether a matchup is conference, weekend, midweek, postseason, European cup, or derby."""
    s = sport.lower()
    is_postseason = False
    is_conference = False
    is_weekend = False
    is_midweek = False
    detected_reason = ""

    # 0. Soccer specific classifications (European Cup, Domestic Cup, Derby)
    if "socc" in s or "epl" in s or "ucl" in s or "laliga" in s or "seriea" in s or "bundes" in s:
        context = f"{game.get('notes', '')} {game.get('event', '')} {game.get('tournament', '')}".lower()
        if any(k in context for k in ("champions league", "ucl", "europa league", "uel", "conference league", "uefa")):
            return {
                "classification": "european_cup",
                "reason": "European Cup fixture",
                "is_postseason": True,
                "is_conference": False,
                "is_weekend": False,
                "is_midweek": False,
            }
        if any(k in context for k in ("fa cup", "carabao cup", "efl cup", "copa del rey", "dfb pokal", "coppa italia", "coupe de france", "us open cup")):
            return {
                "classification": "domestic_cup",
                "reason": "Domestic Cup tie",
                "is_postseason": False,
                "is_conference": False,
                "is_weekend": False,
                "is_midweek": False,
            }
        derby_name = detect_soccer_derby(team_name, opponent_name)
        if derby_name:
            return {
                "classification": "derby",
                "reason": f"{derby_name} rivalry",
                "is_postseason": False,
                "is_conference": True,
                "is_weekend": False,
                "is_midweek": False,
            }
        if "derby" in context or "clasico" in context:
            return {
                "classification": "derby",
                "reason": "derby fixture",
                "is_postseason": False,
                "is_conference": True,
                "is_weekend": False,
                "is_midweek": False,
            }

    # 1. Check explicit fields in the game dict
    g_type = str(game.get("game_type", "")).strip().lower()
    if g_type in ("postseason", "cws", "wcws", "omaha", "regional", "super_regional", "march_madness", "final_four") or game.get("postseason") is True:
        return {
            "classification": "postseason",
            "reason": "explicit postseason",
            "is_postseason": True,
            "is_conference": False,
            "is_weekend": False,
            "is_midweek": False,
        }
    if g_type in ("conference", "conf") or game.get("conference") is True:
        is_conference = True
        detected_reason = "explicit conference"
    elif g_type in ("weekend", "fri", "sat", "sun") or game.get("weekend") is True:
        is_weekend = True
        detected_reason = "explicit weekend"
    elif g_type in ("midweek", "tue", "wed") or game.get("midweek") is True:
        is_midweek = True
        detected_reason = "explicit midweek"

    # 2. Check tournament/event keywords in metadata
    tournament_text = f"{game.get('notes', '')} {game.get('event', '')} {game.get('tournament', '')} {opponent_name}".lower()
    if any(k in tournament_text for k in ("omaha", "cws", "wcws", "women's college world series", "super regional", "ncaa regional", "world series", "march madness", "final four", "elite eight", "sweet 16")):
        is_postseason = True
        detected_reason = "postseason tournament context"

    # 3. Check date metadata
    day_name, date_weekend, date_postseason = parse_date_metadata(game.get("date"), sport)
    if date_postseason:
        is_postseason = True
        detected_reason = f"postseason calendar ({day_name})"
    elif date_weekend and not is_weekend:
        is_weekend = True
        detected_reason = f"weekend calendar ({day_name})"
    elif day_name in ("Monday", "Tuesday", "Wednesday", "Thursday") and not is_midweek:
        is_midweek = True
        detected_reason = f"midweek calendar ({day_name})"

    # 4. Check explicit day field
    if "day" in game and not (is_weekend or is_midweek):
        day_str = str(game["day"]).strip().lower()
        if day_str in ("fri", "friday", "sat", "saturday", "sun", "sunday"):
            is_weekend = True
            detected_reason = f"weekend day ({day_str.title()})"
        elif day_str in ("tue", "tuesday", "wed", "wednesday", "mon", "thu"):
            is_midweek = True
            detected_reason = f"midweek day ({day_str.title()})"

    # 5. Auto-detect conference / division matchup if not postseason
    conf_a = detect_college_conference(team_name)
    conf_b = detect_college_conference(opponent_name)
    if conf_a and conf_b and conf_a == conf_b:
        is_conference = True
        if not is_postseason:
            detected_reason = f"auto-detected {conf_a} matchup"

    # Hierarchy resolution: Postseason > Conference > Weekend > Midweek > Regular
    if is_postseason:
        classification = "postseason"
    elif is_conference:
        classification = "conference"
    elif is_weekend:
        classification = "weekend"
    elif is_midweek:
        classification = "midweek"
    else:
        classification = "regular"

    return {
        "classification": classification,
        "reason": detected_reason or "regular non-conference",
        "is_postseason": is_postseason,
        "is_conference": is_conference,
        "is_weekend": is_weekend,
        "is_midweek": is_midweek,
        "conference": conf_a if (conf_a and conf_a == conf_b) else None,
    }
