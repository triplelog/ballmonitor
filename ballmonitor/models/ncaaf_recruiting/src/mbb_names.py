"""Match men's basketball school and player names across On3 and barttorvik.

On3 school names (after `normalize_team`) are mostly short names ("Ohio State",
"Miami (FL)") but some are full legal names ("Gonzaga University", "The University of
Texas at Arlington"). Barttorvik uses "Ohio St.", "Miami FL", "UT Arlington".
`to_bart(name, known)` returns the barttorvik spelling (or "" if none is found);
`player_key(name)` normalises a player name for matching.
"""

from __future__ import annotations

import re
import unicodedata

# On3 (normalised) -> barttorvik. Only names the generic rules below cannot derive.
BART_ALIASES = {
    "Miami (FL)": "Miami FL",
    "Miami (OH)": "Miami OH",
    "NC State": "N.C. State",
    "Ole Miss": "Mississippi",
    "Pitt": "Pittsburgh",
    "Connecticut": "Connecticut",
    "UConn": "Connecticut",
    "Hawai'i": "Hawaii",
    "USF": "South Florida",
    "Loyola (Chi)": "Loyola Chicago",
    "Loyola (MD)": "Loyola MD",
    "Middle Tennessee State": "Middle Tennessee",
    "Louisiana-Monroe": "Louisiana Monroe",
    "Illinois-Chicago": "Illinois Chicago",
    "Wisconsin-Milwaukee": "Milwaukee",
    "Wisconsin-Green Bay": "Green Bay",
    "Arkansas-Little Rock": "Little Rock",
    "Arkansas-Pine Bluff": "Arkansas Pine Bluff",
    "Missouri-Kansas City": "UMKC",
    "Kansas City": "UMKC",
    "Pennsylvania": "Penn",
    "College of Charleston": "Charleston",
    "The University of Texas at Arlington": "UT Arlington",
    "Texas-Arlington": "UT Arlington",
    "Texas A & M University-Corpus Christi": "Texas A&M Corpus Chris",
    "Texas A&M-Corpus Christi": "Texas A&M Corpus Chris",
    "University of Nebraska at Omaha": "Nebraska Omaha",
    "Omaha": "Nebraska Omaha",
    "University of Maryland-Baltimore County": "UMBC",
    "University of Massachusetts-Lowell": "UMass Lowell",
    "Massachusetts-Lowell": "UMass Lowell",
    "UMass": "Massachusetts",
    "California State University-Long Beach": "Long Beach St.",
    "Long Beach State": "Long Beach St.",
    "California State University-Fullerton": "Cal St. Fullerton",
    "Cal State Fullerton": "Cal St. Fullerton",
    "California State University-Northridge": "Cal St. Northridge",
    "Cal State Northridge": "Cal St. Northridge",
    "California State University-Bakersfield": "Cal St. Bakersfield",
    "Cal State Bakersfield": "Cal St. Bakersfield",
    "California Baptist University": "Cal Baptist",
    "California Baptist": "Cal Baptist",
    "Saint Mary's College of California": "Saint Mary's",
    "Saint Mary's (CA)": "Saint Mary's",
    "St. Mary's": "Saint Mary's",
    "Saint Joseph's University": "Saint Joseph's",
    "St. Joseph's": "Saint Joseph's",
    "Saint Louis University": "Saint Louis",
    "St. Louis": "Saint Louis",
    "Saint Peter's University": "Saint Peter's",
    "St. Peter's": "Saint Peter's",
    "St. John's (NY)": "St. John's",
    "University of San Francisco": "San Francisco",
    "University of San Diego": "San Diego",
    "Manhattan College": "Manhattan",
    "Boston University": "Boston University",
    "Boston College": "Boston College",
    "Utah Tech": "Utah Tech",
    "Dixie State": "Utah Tech",
    "Southern Miss": "Southern Miss",
    "Southern Mississippi": "Southern Miss",
    "Sam Houston": "Sam Houston St.",
    "Sam Houston State": "Sam Houston St.",
    "Houston Baptist": "Houston Christian",
    "IUPUI": "IU Indy",
    "Purdue-Fort Wayne": "Purdue Fort Wayne",
    "Fort Wayne": "Purdue Fort Wayne",
    "Tennessee-Martin": "Tennessee Martin",
    "UT Martin": "Tennessee Martin",
    "Texas-Rio Grande Valley": "UT Rio Grande Valley",
    "UTRGV": "UT Rio Grande Valley",
    "Texas-San Antonio": "UTSA",
    "Texas-El Paso": "UTEP",
    "Alabama-Birmingham": "UAB",
    "Central Florida": "UCF",
    "Virginia Commonwealth": "VCU",
    "Brigham Young": "BYU",
    "Southern California": "USC",
    "Southern Methodist": "SMU",
    "Texas Christian": "TCU",
    "Louisiana State": "LSU",
    "Nevada-Las Vegas": "UNLV",
    "Detroit": "Detroit Mercy",
    "Gardner-Webb": "Gardner Webb",
    "Bethune-Cookman": "Bethune Cookman",
    "Mount St. Mary's University": "Mount St. Mary's",
    "SIUE": "SIU Edwardsville",
    "Southern Illinois-Edwardsville": "SIU Edwardsville",
    "Florida International": "FIU",
    "Queens University of Charlotte": "Queens",
    "Queens (NC)": "Queens",
    "Long Island University": "LIU",
    "LIU Brooklyn": "LIU",
    "St. Francis (PA)": "Saint Francis",
    "St. Francis (NY)": "St. Francis NY",
    "William and Mary": "William & Mary",
    "Saint Bonaventure": "St. Bonaventure",
    "Stephen F Austin": "Stephen F. Austin",
    "SFA": "Stephen F. Austin",
    "App State": "Appalachian St.",
    "Seattle University": "Seattle",
    "UNC-Wilmington": "UNC Wilmington",
    "UNC-Greensboro": "UNC Greensboro",
    "UNC-Asheville": "UNC Asheville",
    "North Carolina-Wilmington": "UNC Wilmington",
    "North Carolina-Greensboro": "UNC Greensboro",
    "North Carolina-Asheville": "UNC Asheville",
    "University of California-Santa Barbara": "UC Santa Barbara",
    "University of California-Irvine": "UC Irvine",
    "University of California-Davis": "UC Davis",
    "University of California-Riverside": "UC Riverside",
    "University of California-San Diego": "UC San Diego",
    "California-Santa Barbara": "UC Santa Barbara",
    "California-Irvine": "UC Irvine",
    "California-Davis": "UC Davis",
    "California-Riverside": "UC Riverside",
    "Indiana University - Indianapolis": "IU Indy",
    "New Jersey Institute of Technology": "NJIT",
    "Loyola Maryland": "Loyola MD",
    "University of North Carolina Wilmington": "UNC Wilmington",
    "University of North Carolina Asheville": "UNC Asheville",
    "The University of Texas Rio Grande Valley": "UT Rio Grande Valley",
    "Long Island": "LIU",
    "University of South Carolina-Upstate": "USC Upstate",
    "Central Connecticut State": "Central Connecticut",
    "Saint Francis (PA)": "Saint Francis",
    "Virginia Military Institute": "VMI",
    "St. Francis College": "St. Francis NY",
}

_DROP = ("The University of ", "University of ", " University", " College")
# Non-D-I schools whose names would otherwise collapse onto a D-I team by the rules
# below ("Notre Dame College" is not Notre Dame).
NOT_DI = {"Notre Dame College", "University of Charleston", "Jacksonville College",
          "St. Thomas University", "University of Saint Mary", "St. Joseph's College",
          "Rollins College"}


def _candidates(name: str) -> list[str]:
    name = name.strip()
    out = [BART_ALIASES.get(name, ""), name]
    stripped = name
    for d in _DROP:
        stripped = stripped.replace(d, "")
    out.append(stripped.strip())
    for base in list(out):
        if base.endswith(" State"):
            out.append(base[: -len(" State")] + " St.")
        out.append(base.replace("State University", "St.").replace(" State", " St."))
        out.append(base.replace("-", " "))
    return [c for c in out if c]


def to_bart(name: str, known: set[str]) -> str:
    """Barttorvik spelling of an On3 school name, or "" when none of the candidate
    spellings is a barttorvik D-I team in `known`."""
    if name.strip() in NOT_DI:
        return ""
    for c in _candidates(name):
        if c in known:
            return c
    return ""


SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
# First-name variants seen across recruiting sites and box scores (both directions).
NICKNAMES = {
    "nick": "nicholas", "nic": "nicholas", "mike": "michael", "matt": "matthew",
    "chris": "christopher", "cam": "cameron", "josh": "joshua", "jon": "jonathan",
    "john": "jonathan", "will": "william", "bill": "william", "billy": "william",
    "dan": "daniel", "danny": "daniel", "dave": "david", "tony": "anthony",
    "alex": "alexander", "zach": "zachary", "zack": "zachary", "tom": "thomas",
    "tommy": "thomas", "jim": "james", "jimmy": "james", "jake": "jacob",
    "joe": "joseph", "joey": "joseph", "ben": "benjamin", "sam": "samuel",
    "andy": "andrew", "drew": "andrew", "ed": "edward", "eddie": "edward",
    "greg": "gregory", "jeff": "jeffrey", "rob": "robert", "bob": "robert",
    "bobby": "robert", "steve": "steven", "stephen": "steven", "tj": "tj",
    "cj": "cj", "jj": "jj", "aj": "aj", "dj": "dj", "rj": "rj", "kj": "kj",
    "pj": "pj", "nate": "nathan", "nathaniel": "nathan", "fred": "frederick",
    "freddie": "frederick", "ken": "kenneth", "kenny": "kenneth", "ty": "tyler",
    "trey": "trey", "tre": "trey", "zeke": "ezekiel", "max": "maxwell",
    "jay": "jay", "manny": "emmanuel", "elijah": "elijah", "eli": "elijah",
}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def player_tokens(name: str) -> list[str]:
    s = _ascii(name).lower().replace("'", "").replace("’", "").replace(".", "")
    s = re.sub(r"[^a-z\s-]", " ", s).replace("-", " ")
    toks = [t for t in s.split() if t]
    while len(toks) > 2 and toks[-1] in SUFFIXES:
        toks.pop()
    if len(toks) == 2 and toks[-1] in SUFFIXES:
        toks.pop()
    return toks


def player_key(name: str) -> str:
    """'D'Angelo Russell Jr.' -> 'dangelo russell'; first name mapped to a canonical form."""
    toks = player_tokens(name)
    if not toks:
        return ""
    first = NICKNAMES.get(toks[0], toks[0])
    return " ".join([first, *toks[1:]])


def last_name(name: str) -> str:
    toks = player_tokens(name)
    return toks[-1] if toks else ""
