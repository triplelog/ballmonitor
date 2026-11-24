"""Download / rebuild the ncaaf_recruiting data that research.py and the model read.

    ballmonitor fetch ncaaf_recruiting            # download what is missing, then rebuild
    ballmonitor fetch ncaaf_recruiting --offline  # rebuild from data/raw/ only
    ballmonitor fetch ncaaf_recruiting --scheduled  # the light daily CI update of the
                                                    # 2027 football class (scheduled_update)

Writes (built, documented CSVs; raw JSON is cached in data/raw/, which is gitignored):
    data/recruits/football2027done.csv      2027 football class (in progress: includes
                                            uncommitted recruits with an empty school)
    data/recruits/recruits_mbb_{2014..2023,2026,2027}.csv, recruits_wbb_2027.csv
                                            (MBB 2024-2025 are older ingest_class.py files)
    data/recruits/mbb_recruit_ratings.csv   every On3-ranked MBB recruit 2014-2027 with
                                            industry rating / rank, stars, commit, status
    data/outcomes/mbb_team_seasons.csv      barttorvik adj. efficiencies, seasons 2014-2026
    data/outcomes/mbb_player_seasons.csv    barttorvik player seasons 2014-2026
    data/recruits/recruits_wbb_2024.csv     ESPN 2024 file with mascots stripped from
                                            school names (it still has no offer lists)
    data/recruits/manifest.csv              one row per recruit file: source, status,
                                            rows, commits, share of commits with offers
    data/outcomes/fbs_games.csv             every completed game involving an FBS team,
                                            2012-2025 (season, week, teams, points, neutral)
    data/benchmarks/consensus_team_rankings.csv
                                            On3 industry-consensus team class rankings
                                            (averages On3, 247Sports, Rivals and ESPN)
    data/reference/on3_team_slugs.csv       program -> On3's team slug (the page links each
                                            industry rank to that class's page on on3.com)

Sources (free, no key):
    On3 recruit database API   https://api.on3.com/public/rdb/v1/  (players/industry-
                               comparision, player/{key}/team-targets, team-ranking/...)
    ESPN scoreboard API        https://site.api.espn.com/apis/site/v2/sports/football/
                               college-football/scoreboard  (groups=80 = FBS)
    barttorvik.com             getadvstats.php?year=Y&csv=1 (players), Y_team_results.csv
                               (teams); one request per season file, cached in data/raw/

Recruit files use the same row format as the older files:
    url, year, NAME, position, hometown, stars, committed_school, offer_1, offer_2, ...
"offers" are every school On3 lists as a target other than the committed one (status
"Offered" for almost all), exactly as ingest_class.py built the 2022-2026 files.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from ballmonitor.models.ncaaf_recruiting.src.data_loader import normalize_team, standardize_team_name

UA = {"User-Agent": "Mozilla/5.0"}  # ESPN refuses some custom agent strings
ON3 = "https://api.on3.com/public/rdb/v1"
ESPN = (
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
    "?dates={season}&seasontype={st}&week={wk}&groups=80&limit=500"
)
SPORT_KEYS = {"ncaaf": 1, "mbb": 2, "wbb": 5}
SPORT_SLUGS = {"ncaaf": "football", "mbb": "basketball", "wbb": "womens-basketball"}
# Classes downloaded from On3 by this script (older files were built by ingest_class.py
# or earlier scrapes and are left as they are; MBB 2024-2025 are kept as built then).
MBB_HISTORY = range(2014, 2024)  # MBB classes added in v0.5.0 (On3 has MBB back to 2014)
CLASSES = [("ncaaf", 2027), *(("mbb", y) for y in MBB_HISTORY), ("mbb", 2026), ("mbb", 2027),
           ("wbb", 2027)]
# MBB recruit ratings table (industry rating, rank, stars, commit, offer count) for the
# basketball research study; every MBB class On3 has.
MBB_RATING_YEARS = range(2014, 2028)
# Barttorvik seasons (year = spring year: 2020 = the 2019-20 season). 2026 = 2025-26 is
# the last completed season; 2014 is the prior season of the 2014 class.
BART_SEASONS = range(2014, 2027)
BART = "https://barttorvik.com"
COMMIT_STATUSES = ("Enrolled", "Signed", "Committed")  # first found wins (most final first)
# Classes still being recruited when fetched (signing day not yet passed).
IN_PROGRESS = {("ncaaf", 2027), ("mbb", 2027), ("wbb", 2027)}
SCORE_SEASONS = range(2012, 2026)  # completed seasons (the 2026 season is in progress)
RANKING_YEARS = {"ncaaf": range(2012, 2028), "mbb": range(2014, 2028), "wbb": range(2025, 2028)}
WORKERS = 6

# ESPN `location` -> name used in the recruit files (after normalize_team).
ESPN_ALIASES = {
    "Miami": "Miami (FL)",
    "Hawai'i": "Hawai'i",
    "UMass": "Massachusetts",
    "App State": "Appalachian State",
    "Southern Mississippi": "Southern Miss",
    "UL Monroe": "Louisiana-Monroe",
    "Louisiana Monroe": "Louisiana-Monroe",
    "UTSA": "UTSA",
    "Sam Houston": "Sam Houston State",
    "Sam Houston State": "Sam Houston State",
    "San José State": "San Jose State",
    "Florida International": "FIU",
    "Florida Atlantic": "Florida Atlantic",
    "Middle Tennessee": "Middle Tennessee State",
    "Kennesaw State": "Kennesaw State",
}


def _get(url: str, timeout: int = 40, tries: int = 4):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return None
            if attempt == tries - 1:
                raise
        except Exception:
            if attempt == tries - 1:
                raise
        time.sleep(1.5 * (attempt + 1))
    return None


def _cached_text(path: Path, url: str, offline: bool) -> str | None:
    """Return a raw text file (CSV) from the data/raw cache, downloading it unless offline."""
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if offline:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=120) as res:
        text = res.read().decode("utf-8", errors="replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    time.sleep(1.0)  # one request per season file, politely spaced
    return text


def _cached(path: Path, url: str, offline: bool):
    """Return JSON from data/raw cache, downloading it first unless offline."""
    if path.exists():
        return json.loads(path.read_text())
    if offline:
        return None
    data = _get(url)
    if data is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    return data


# --------------------------------------------------------------------------- recruits

def _on3_team(team: dict | None) -> str:
    team = team or {}
    return normalize_team(standardize_team_name(team.get("name", ""), team.get("slug", "")))


def _stars(ratings: list) -> int:
    for r in ratings or []:
        if r.get("type") == "Consensus" and r.get("stars") is not None:
            return int(r["stars"])
    stars = [int(r["stars"]) for r in ratings or [] if r.get("stars") is not None]
    return max(stars) if stars else 0


def _targets(raw: Path, key: int, offline: bool) -> list:
    items = []
    first = _cached(raw / "targets" / f"{key}_1.json", f"{ON3}/player/{key}/team-targets", offline)
    if not first:
        return items
    items.extend(first.get("list", []))
    pages = (first.get("pagination") or {}).get("pageCount", 1) or 1
    for page in range(2, pages + 1):
        more = _cached(raw / "targets" / f"{key}_{page}.json",
                       f"{ON3}/player/{key}/team-targets?page={page}", offline)
        if more:
            items.extend(more.get("list", []))
    return items


def _players(raw: Path, sport: str, year: int, offline: bool) -> list:
    players, page, pages = [], 1, 1
    while page <= pages:
        url = f"{ON3}/players/industry-comparision?sportKey={SPORT_KEYS[sport]}&year={year}&page={page}"
        data = _cached(raw / "players" / f"{sport}_{year}_p{page}.json", url, offline)
        if not data:
            break
        pages = (data.get("pagination") or {}).get("pageCount", 1) or 1
        players.extend(data.get("list", []))
        page += 1
    # On3 pages can overlap (the ranking shifts between page requests): keep each
    # player once.
    seen, unique = set(), []
    for p in players:
        key = (p.get("person") or {}).get("key")
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def _all_targets(raw: Path, players: list, offline: bool) -> dict:
    keys = [p["person"]["key"] for p in players if (p.get("person") or {}).get("key")]
    with ThreadPoolExecutor(WORKERS) as pool:
        return dict(zip(keys, pool.map(lambda k: _targets(raw, k, offline), keys)))


def _commit_and_offers(items: list) -> tuple[str, str, list[str]]:
    """(committed school, its On3 status, other schools) from a team-targets list.
    Enrolled beats Signed beats Committed (a signee who was released and enrolled
    elsewhere shows both)."""
    commits: dict[str, str] = {}
    offers: list[str] = []
    for it in items:
        name = _on3_team(it.get("team"))
        if not name:
            continue
        status = it.get("status")
        if status in COMMIT_STATUSES:
            commits.setdefault(status, name)
        elif name not in offers:
            offers.append(name)
    committed, status = "", ""
    for st in COMMIT_STATUSES:
        if st in commits:
            committed, status = commits[st], st
            break
    # schools with a commit status other than the chosen one count as competing offers
    for st, name in commits.items():
        if name != committed and name not in offers:
            offers.append(name)
    return committed, status, [t for t in offers if t != committed]


def build_class(model_dir: Path, sport: str, year: int, offline: bool) -> str:
    raw = model_dir / "data" / "raw" / "on3"
    players = _players(raw, sport, year, offline)
    if not players:
        return f"{sport} {year}: no On3 player list (skipped)"
    targets = _all_targets(raw, players, offline)

    rows = []
    for p in players:
        person = p.get("person") or {}
        key = person.get("key")
        if not key:
            continue
        committed, _, offers = _commit_and_offers(targets.get(key, []))
        rows.append([
            f"https://www.on3.com/db/{person.get('slug', '')}/", year,
            str(person.get("name", "")).strip().upper(), person.get("positionAbbreviation") or "",
            person.get("homeTownName") or "", _stars(p.get("ratings")), committed, *offers,
        ])
    rows.sort(key=lambda r: (-r[5], r[2]))
    out = _recruit_path(model_dir, sport, year)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return f"{sport} {year}: {len(rows)} recruits -> {out.relative_to(model_dir)}"


def _rating(ratings: list, kind: str) -> dict:
    for r in ratings or []:
        if r.get("type") == kind:
            return r
    return {}


def build_mbb_ratings(model_dir: Path, offline: bool) -> str:
    """data/recruits/mbb_recruit_ratings.csv: one row per On3-listed MBB recruit with the
    industry (consensus of On3/247/ESPN/Rivals) rating, national rank and stars, the
    committed school and how many other schools On3 lists. Read by research_mbb.py."""
    raw = model_dir / "data" / "raw" / "on3"
    rows = []
    for year in MBB_RATING_YEARS:
        players = _players(raw, "mbb", year, offline)
        targets = _all_targets(raw, players, offline)
        for p in players:
            person = p.get("person") or {}
            key = person.get("key")
            if not key:
                continue
            ind = _rating(p.get("ratings"), "Industry") or _rating(p.get("ratings"), "Consensus")
            committed, status, offers = _commit_and_offers(targets.get(key, []))
            rows.append([
                year, key, f"https://www.on3.com/db/{person.get('slug', '')}/",
                str(person.get("name", "")).strip(), person.get("positionAbbreviation") or "",
                person.get("height") or "", person.get("homeTownName") or "",
                "" if ind.get("rating") is None else round(float(ind["rating"]), 3),
                "" if ind.get("overallRank") is None else int(ind["overallRank"]),
                _stars(p.get("ratings")), committed, status, len(offers),
            ])
    out = model_dir / "data" / "recruits" / "mbb_recruit_ratings.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["year", "on3_key", "url", "name", "position", "height_in", "hometown",
                    "industry_rating", "industry_rank", "stars", "committed_school",
                    "commit_status", "n_other_schools"])
        w.writerows(rows)
    return f"mbb ratings: {len(rows)} recruits {MBB_RATING_YEARS.start}-{MBB_RATING_YEARS.stop - 1} -> {out.relative_to(model_dir)}"


# Barttorvik player-season CSV (getadvstats.php?csv=1): no header, 67 columns. Mapping
# verified against known players (2019: Zion Williamson Duke Fr 22.6 pts, 8.9 reb, 30.0
# min/g, pick 1; Ja Morant Murray St. 24.5 pts, 9.9 ast, pick 2; 2021: Cade Cunningham
# Oklahoma St. 20.1 pts). Only the columns used are kept.
BART_PLAYER_COLS = {
    0: "name", 1: "team", 2: "conf", 3: "gp", 4: "min_pct", 5: "ortg", 6: "usage",
    8: "ts_pct", 25: "class", 26: "height", 28: "porpag", 31: "season", 32: "player_id",
    33: "hometown", 34: "rec_rating", 45: "draft_pick", 50: "bpm", 51: "obpm", 52: "dbpm",
    54: "min_per_game", 59: "reb", 60: "ast", 63: "pts", 64: "role", 66: "dob",
}


def build_bart_players(model_dir: Path, offline: bool) -> str:
    raw = model_dir / "data" / "raw" / "barttorvik"
    rows = []
    for season in BART_SEASONS:
        text = _cached_text(raw / f"players_{season}.csv",
                            f"{BART}/getadvstats.php?year={season}&csv=1", offline)
        if not text:
            continue
        for r in csv.reader(text.splitlines()):
            if len(r) < 67:
                continue
            rows.append([r[i].strip() for i in BART_PLAYER_COLS])
    out = model_dir / "data" / "outcomes" / "mbb_player_seasons.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(list(BART_PLAYER_COLS.values()))
        w.writerows(rows)
    return f"barttorvik players: {len(rows)} player-seasons {BART_SEASONS.start}-{BART_SEASONS.stop - 1} -> {out.relative_to(model_dir)}"


def build_bart_teams(model_dir: Path, offline: bool) -> str:
    """data/outcomes/mbb_team_seasons.csv: barttorvik adjusted efficiencies per D-I team
    (end-of-season file {season}_team_results.csv). adj_em = adj_oe - adj_de (points per
    100 possessions vs an average D-I team)."""
    raw = model_dir / "data" / "raw" / "barttorvik"
    rows = []
    for season in BART_SEASONS:
        text = _cached_text(raw / f"teams_{season}.csv", f"{BART}/{season}_team_results.csv", offline)
        if not text:
            continue
        for r in csv.DictReader(text.splitlines()):
            try:
                oe, de = float(r["adjoe"]), float(r["adjde"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append([season, r["team"].strip(), r["conf"].strip(), r["record"].strip(),
                         round(oe, 2), round(de, 2), round(oe - de, 2), round(float(r["barthag"]), 4)])
    out = model_dir / "data" / "outcomes" / "mbb_team_seasons.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["season", "team", "conf", "record", "adj_oe", "adj_de", "adj_em", "barthag"])
        w.writerows(rows)
    return f"barttorvik teams: {len(rows)} team-seasons -> {out.relative_to(model_dir)}"


def _recruit_path(model_dir: Path, sport: str, year: int) -> Path:
    name = f"football{year}done.csv" if sport == "ncaaf" else f"recruits_{sport}_{year}.csv"
    return model_dir / "data" / "recruits" / name


def clean_wbb_2024(model_dir: Path) -> str:
    """Strip mascots from the ESPN WBB 2024 school names ("South Carolina Gamecocks")."""
    path = _recruit_path(model_dir, "wbb", 2024)
    if not path.exists():
        return "wbb 2024: file missing"
    known = set()
    for f in (model_dir / "data" / "recruits").glob("recruits_*_*.csv"):
        if f != path:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for row in csv.reader(fh):
                    known.update(normalize_team(t) for t in row[6:] if t.strip())
    known.update({"Miami (FL)", "UConn", "NC State", "Ole Miss", "USC", "LSU", "UCF", "BYU", "TCU", "SMU",
                  "Loyola Chicago"})  # cleaned names that would otherwise lose a word on a rerun

    def clean(name: str) -> str:
        name = name.strip()
        if not name or name in known:
            return name
        special = {"Miami Hurricanes": "Miami (FL)", "UConn Huskies": "Connecticut",
                   "USC Trojans": "USC", "Ole Miss Rebels": "Ole Miss"}
        if name in special:
            return special[name]
        words = name.split()
        for cut in range(len(words) - 1, 0, -1):  # longest known prefix wins
            prefix = " ".join(words[:cut])
            if normalize_team(prefix) in known:
                return normalize_team(prefix)
        return " ".join(words[:-1]) if len(words) > 1 else name

    with open(path, encoding="utf-8", errors="replace") as fh:
        rows = list(csv.reader(fh))
    changed = 0
    for row in rows:
        for i in range(6, len(row)):
            new = clean(row[i])
            changed += new != row[i]
            row[i] = new
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return f"wbb 2024: {changed} school names de-mascotted (file still has no offer lists)"


def write_manifest(model_dir: Path) -> str:
    rec = model_dir / "data" / "recruits"
    entries = []
    for sport in ("ncaaf", "mbb", "wbb"):
        pattern = "football*done.csv" if sport == "ncaaf" else f"recruits_{sport}_*.csv"
        for f in sorted(rec.glob(pattern)):
            digits = f.stem.replace("football", "").replace("done", "").rsplit("_", 1)[-1]
            if not digits.isdigit():
                continue
            year = int(digits)
            with open(f, encoding="utf-8", errors="replace") as fh:
                rows = [r for r in csv.reader(fh) if len(r) >= 7]
            commits = [r for r in rows if r[6].strip() not in ("", "0")]
            with_offers = sum(1 for r in commits if any(t.strip() not in ("", "0", r[6]) for t in r[7:]))
            if sport == "wbb" and year == 2024:
                source = "ESPN recruiting API (commit + finalists only, no offer lists)"
            elif sport == "ncaaf" and year <= 2021:
                source = "Rivals/On3 profile scrape (legacy)"
            else:
                source = "On3 recruit database API"
            status = "in_progress" if (sport, year) in IN_PROGRESS else "complete"
            fetched = ""
            if (sport, year) in CLASSES:
                fetched = date.fromtimestamp(f.stat().st_mtime).isoformat()
            entries.append([sport, year, f.name, source, status, fetched, len(rows), len(commits),
                            round(with_offers / len(commits), 3) if commits else 0.0])
    out = rec / "manifest.csv"
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sport", "year", "file", "source", "status", "fetched", "rows", "commits", "offer_coverage"])
        w.writerows(entries)
    return f"manifest: {len(entries)} recruit files -> {out.relative_to(model_dir)}"


# ------------------------------------------------------------------- outcomes / benchmarks

def espn_name(location: str) -> str:
    return normalize_team(ESPN_ALIASES.get(location, location))


def build_games(model_dir: Path, offline: bool) -> str:
    raw = model_dir / "data" / "raw" / "espn_fbs"
    rows, seen = [], set()
    for season in SCORE_SEASONS:
        for st, weeks in ((2, range(1, 18)), (3, range(1, 2))):
            for wk in weeks:
                data = _cached(raw / f"{season}_{st}_{wk}.json", ESPN.format(season=season, st=st, wk=wk), offline)
                for ev in (data or {}).get("events", []):
                    if not ev.get("competitions"):
                        continue
                    comp = ev["competitions"][0]
                    if not comp["status"]["type"].get("completed") or ev["id"] in seen:
                        continue
                    teams = {c["homeAway"]: c for c in comp["competitors"]}
                    if set(teams) != {"home", "away"}:
                        continue
                    try:
                        hp, ap = int(float(teams["home"]["score"])), int(float(teams["away"]["score"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    seen.add(ev["id"])
                    rows.append([season, st, wk, ev["id"], ev.get("date", "")[:10],
                                 espn_name(teams["home"]["team"]["location"]),
                                 espn_name(teams["away"]["team"]["location"]),
                                 hp, ap, int(bool(comp.get("neutralSite")))])
    out = model_dir / "data" / "outcomes" / "fbs_games.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["season", "season_type", "week", "game_id", "date", "home", "away",
                    "home_points", "away_points", "neutral"])
        w.writerows(rows)
    return f"games: {len(rows)} completed FBS games {SCORE_SEASONS.start}-{SCORE_SEASONS.stop - 1} -> {out.relative_to(model_dir)}"


SLUGS = Path("data") / "reference" / "on3_team_slugs.csv"   # program -> On3's team slug (links to its class page)


def merge_slugs(model_dir: Path, sport: str, items: list) -> None:
    """Add On3's team slugs (organization.slug, e.g. "georgia-bulldogs") from ranking items to
    data/reference/on3_team_slugs.csv: the public page links each industry rank to
    on3.com/college/<slug>/football/<year>/industry-comparison-commits/."""
    path = model_dir / SLUGS
    slugs = {}
    if path.exists():
        with open(path, newline="") as fh:
            slugs = {(r["sport"], r["team"]): r["slug"] for r in csv.DictReader(fh)}
    for it in items:
        org = it.get("organization") or {}
        if org.get("slug"):
            slugs[(sport, _on3_team(org))] = org["slug"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sport", "team", "slug"])
        w.writerows([k[0], k[1], v] for k, v in sorted(slugs.items()))


def build_rankings(model_dir: Path, offline: bool) -> str:
    raw = model_dir / "data" / "raw" / "on3_team_rankings"
    rows = []
    for sport, years in RANKING_YEARS.items():
        for year in years:
            items, page, pages = [], 1, 1
            while page <= pages:
                url = f"{ON3}/team-ranking/{SPORT_SLUGS[sport]}-{year}/consensus-team-rankings?page={page}"
                data = _cached(raw / f"{sport}_{year}_p{page}.json", url, offline)
                if not data:
                    break
                pages = (data.get("pagination") or {}).get("pageCount", 0) or 0
                items.extend(data.get("list", []))
                page += 1
            merge_slugs(model_dir, sport, items)
            for it in items:
                rank = it.get("overallConsensusRank")
                if rank is None:
                    continue
                rows.append([sport, year, int(rank), _on3_team(it.get("organization")),
                             round(float(it.get("appliedTotalConsensusRating") or 0.0), 3),
                             it.get("commits") or 0,
                             it.get("consensusFiveStars") or 0, it.get("consensusFourStars") or 0])
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    out = model_dir / "data" / "benchmarks" / "consensus_team_rankings.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sport", "year", "rank", "team", "consensus_points", "commits", "five_stars", "four_stars"])
        w.writerows(rows)
    return f"rankings: {len(rows)} consensus team-class rows -> {out.relative_to(model_dir)}"


ESPN_WBB = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/womens-college-basketball"
WBB_ESPN_YEARS = range(2012, 2026)
WBB_ESPN_TOP = 300  # ESPN lists recruits in rank order; keep the top 300 per class


def build_wbb_espn(model_dir: Path, offline: bool) -> str:
    """ESPN women's basketball recruiting classes (grade, rank, commitment and the schools
    still on each recruit's list -- finalists, not full offer lists) ->
    data/recruits/wbb_espn_classes.csv. Team names are ESPN display names, matching
    ballmonitor/models/dad/data/team_ratings.csv."""
    raw = model_dir / "data" / "raw" / "espn_wbb"
    team_name: dict[str, str] = {}

    def team(ref: str) -> str:
        tid = ref.split("/teams/")[1].split("?")[0]
        if tid not in team_name:
            d = _cached(raw / "teams" / f"{tid}.json", ref.replace("http://", "https://"), offline) or {}
            team_name[tid] = d.get("displayName", "")
        return team_name[tid]

    rows = []
    for y in WBB_ESPN_YEARS:
        refs, page = [], 1
        while len(refs) < WBB_ESPN_TOP:
            idx = _cached(raw / "index" / f"{y}_p{page}.json",
                          f"{ESPN_WBB}/recruiting/{y}/athletes?limit=100&page={page}", offline)
            if not idx or not idx.get("items"):
                break
            refs += [it["$ref"].replace("http://", "https://") for it in idx["items"]]
            if page >= idx.get("pageCount", 1):
                break
            page += 1
        refs = refs[:WBB_ESPN_TOP]

        def one(ref: str):
            rid = ref.split("/recruits/")[1].split("?")[0]
            return _cached(raw / "recruits" / f"{rid}.json", ref, offline)

        with ThreadPoolExecutor(WORKERS) as pool:
            recs = [r for r in pool.map(one, refs) if r]
        for r in recs:
            ath = r.get("athlete") or {}
            rank = next((a.get("value") for a in r.get("attributes", []) if a.get("name") == "rank"), None)
            committed, listed = "", []
            for sch in r.get("schools", []):
                name = team(sch["team"]["$ref"]) if sch.get("team") else ""
                if not name:
                    continue
                if sch["status"]["description"] in ("Signed", "Verbal", "Enrolled", "Committed"):
                    committed = name
                elif name not in listed:
                    listed.append(name)
            rows.append([y, ath.get("id", ""), ath.get("fullName", ""), r.get("grade") or "",
                         rank if rank is not None else "", committed, "|".join(t for t in listed if t != committed)])
    out = model_dir / "data" / "recruits" / "wbb_espn_classes.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["year", "espn_id", "name", "grade", "rank", "committed_team", "other_schools"])
        w.writerows(rows)
    return f"wbb ESPN classes {WBB_ESPN_YEARS[0]}-{WBB_ESPN_YEARS[-1]}: {len(rows)} recruits -> {out.relative_to(model_dir)}"


# ------------------------------------------------------------- scheduled (daily) update
#
# `update-and-build` (the daily CI build) calls fetch(..., scheduled=True). CI has no
# data/raw/ cache, so instead of the full rebuild above it refreshes only the class being
# signed (football 2027, the one the public page shows as in progress) and its On3
# consensus team ranks, politely: the player list pages (new recruits, stars), the
# consensus ranking pages (a program whose commit count moved has a commit, decommit or
# flip), then team-targets only for new recruits, recruits whose program's count moved,
# uncommitted recruits when some count rose, and the stalest of the rest, so each offer
# list is re-read about every `refresh_days` days. Recruits not re-read keep the offers of
# the newer of the committed CSV and data/raw/scheduled/ (kept between CI runs by
# actions/cache). Options: config.toml [fetch.scheduled].

SCHEDULED_CLASS = ("ncaaf", 2027)
SCHEDULED_DEFAULTS = {
    "max_requests": 600,    # hard cap on On3 requests per run (list + ranking + target pages)
    "refresh_days": 14,     # every offer list re-read about this often
    "delay_seconds": 0.5,   # pause before each request (sequential, one at a time)
    "min_keep": 0.9,        # refuse to write a list shorter than this share of the old one
    "max_failures": 5,      # consecutive failed target requests before giving up for the run
}


def scheduled_options(model_dir: Path) -> dict:
    import tomllib

    try:
        cfg = tomllib.loads((Path(model_dir) / "config.toml").read_text())
    except (OSError, ValueError):
        cfg = {}
    opts = dict(SCHEDULED_DEFAULTS)
    opts.update((cfg.get("fetch") or {}).get("scheduled") or {})
    return opts


class RequestCap(Exception):
    """The run used its On3 request budget."""


class PoliteGetter:
    """Sequential GETs with a pause before each request, retries with backoff and a hard
    cap on the number of requests. `opener(url)` returns parsed JSON or None (404) and
    raises on other failures; tests pass a fake one."""

    def __init__(self, max_requests: int, delay: float = 0.0, opener=None, tries: int = 3,
                 sleep=time.sleep):
        self.max_requests, self.delay, self.tries, self.sleep = max_requests, delay, tries, sleep
        self.opener = opener or self._open
        self.used = 0

    @staticmethod
    def _open(url: str):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return None
            raise

    def __call__(self, url: str):
        for attempt in range(self.tries):
            if self.used >= self.max_requests:
                raise RequestCap(url)
            self.used += 1
            if self.delay:
                self.sleep(self.delay * (2 ** attempt))  # 1x, then 2x, 4x on retries
            try:
                return self.opener(url)
            except Exception:
                if attempt == self.tries - 1:
                    raise
        return None


def _key_from_url(url: str) -> int | None:
    tail = url.rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _read_class_csv(path: Path) -> dict[int, dict]:
    """On3 key -> {committed, offers} from a built recruit file (football{year}done.csv)."""
    out: dict[int, dict] = {}
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            key = _key_from_url(row[0]) if row else None
            if key is not None and len(row) >= 7:
                out[key] = {"committed": row[6], "offers": [t for t in row[7:] if t]}
    return out


def _manifest_rows(model_dir: Path) -> list[dict]:
    path = model_dir / "data" / "recruits" / "manifest.csv"
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def known_records(csv_rows: dict[int, dict], csv_date: str, state: dict) -> dict[int, dict]:
    """Each recruit's latest known commit + offers with the day they were read: the
    committed CSV (as of the manifest's fetched date) unless data/raw/scheduled/ has a read
    from that day or later."""
    known = {k: {**v, "date": csv_date} for k, v in csv_rows.items()}
    for k, rec in (state.get("recruits") or {}).items():
        k = int(k)
        if k not in known or rec.get("date", "") >= known[k]["date"]:
            known[k] = rec
    return known


def select_targets(list_keys: list[int], known: dict[int, dict], changed_teams: set[str],
                   commits_rose: bool, today: str, refresh_days: int) -> list[tuple[int, str]]:
    """Recruits whose team-targets to re-read, most needed first, as (key, reason). Keys
    already read today are skipped (several CI runs a day cost no more than one). The
    request cap is applied by the caller, so the order matters: new recruits, then
    recruits committed to a program whose commit count moved, then (if some count rose)
    uncommitted recruits, then the stalest of the rest up to a daily quota of
    len(list) / refresh_days (ties in a random-looking order that changes daily)."""
    import zlib

    picked: list[tuple[int, str]] = []
    seen: set[int] = set()

    def add(key: int, reason: str) -> None:
        if key not in seen:
            seen.add(key)
            picked.append((key, reason))

    fresh = [k for k in list_keys if k in known and known[k].get("date") != today]
    for k in list_keys:
        if k not in known:
            add(k, "new")
    for k in fresh:
        if known[k].get("committed") in changed_teams:
            add(k, "program's commit count moved")
    if commits_rose:
        for k in fresh:
            if not known[k].get("committed"):
                add(k, "uncommitted")
    read_today = sum(1 for k in list_keys if k in known and known[k].get("date") == today)
    quota = -(-len(list_keys) // max(1, refresh_days)) - read_today - len(picked)
    rest = sorted((k for k in fresh if k not in seen),
                  key=lambda k: (known[k].get("date", ""), zlib.crc32(f"{k}:{today}".encode())))
    for k in rest[:max(0, quota)]:
        add(k, "rotation")
    return picked


def _save_raw(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _write_csv_atomic(path: Path, rows: list, header: list | None = None) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if header:
            w.writerow(header)
        w.writerows(rows)
    tmp.replace(path)


def _scheduled_rankings(model_dir: Path, sport: str, year: int, get) -> tuple[list | None, str]:
    """Fresh On3 consensus team ranks for one class -> rows for consensus_team_rankings.csv."""
    items, page, pages = [], 1, 1
    while page <= pages:
        data = get(f"{ON3}/team-ranking/{SPORT_SLUGS[sport]}-{year}/consensus-team-rankings?page={page}")
        if not data:
            break
        pages = (data.get("pagination") or {}).get("pageCount", 0) or 0
        items.extend(data.get("list", []))
        _save_raw(model_dir / "data" / "raw" / "on3_team_rankings" / f"{sport}_{year}_p{page}.json", data)
        page += 1
    merge_slugs(model_dir, sport, items)
    rows = [[sport, year, int(it["overallConsensusRank"]), _on3_team(it.get("organization")),
             round(float(it.get("appliedTotalConsensusRating") or 0.0), 3), it.get("commits") or 0,
             it.get("consensusFiveStars") or 0, it.get("consensusFourStars") or 0]
            for it in items if it.get("overallConsensusRank") is not None]
    return (rows or None), f"{page - 1} ranking pages"


def scheduled_update(model_dir: Path, get=None, today: str | None = None) -> list[str]:
    """The light daily update of the in-progress football class (see the comment above).
    Never leaves a half-written or shrunken file: if On3's player list fails, every built
    file stays as it was."""
    model_dir = Path(model_dir)
    sport, year = SCHEDULED_CLASS
    opts = scheduled_options(model_dir)
    today = today or date.today().isoformat()
    get = get or PoliteGetter(int(opts["max_requests"]), float(opts["delay_seconds"]))
    state_path = model_dir / "data" / "raw" / "scheduled" / f"on3_{sport}_{year}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    out_path = _recruit_path(model_dir, sport, year)
    manifest = _manifest_rows(model_dir)
    mrow = next((r for r in manifest if r["sport"] == sport and r["year"] == str(year)), None)
    csv_date = (mrow or {}).get("fetched", "") or ""
    lines = [f"{sport} {year}: scheduled update ({'warm' if state else 'cold'} cache, "
             f"committed file as of {csv_date or 'unknown'})"]

    # 1. the player list (every page, fresh). Any failure: keep everything as it is.
    players, pages_read, page, pages = [], [], 1, 1
    try:
        while page <= pages:
            data = get(f"{ON3}/players/industry-comparision?sportKey={SPORT_KEYS[sport]}&year={year}&page={page}")
            if not data or not data.get("list"):
                raise ValueError(f"empty player list page {page}")
            pages = (data.get("pagination") or {}).get("pageCount", 1) or 1
            players.extend(data["list"])
            pages_read.append(data)
            page += 1
    except Exception as exc:  # incl. RequestCap
        return lines + [f"  On3 player list failed ({exc!r}); kept the committed files"]
    seen, unique = set(), []
    for p in players:
        key = (p.get("person") or {}).get("key")
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    players = unique
    csv_rows = _read_class_csv(out_path)
    raw = model_dir / "data" / "raw" / "on3"
    if len(players) < float(opts["min_keep"]) * len(csv_rows):
        return lines + [f"  On3 lists {len(players)} recruits vs {len(csv_rows)} in the file; kept the committed files"]
    lines.append(f"  player list: {pages} pages, {len(players)} recruits")
    for pg, data in enumerate(pages_read, 1):
        _save_raw(raw / "players" / f"{sport}_{year}_p{pg}.json", data)

    # 2. consensus team ranks: which programs' commit counts moved since the last read.
    bench = model_dir / "data" / "benchmarks" / "consensus_team_rankings.csv"
    old_counts = {}
    if bench.exists():
        with open(bench, newline="") as fh:
            old_counts = {r["team"]: int(r["commits"]) for r in csv.DictReader(fh)
                          if r["sport"] == sport and r["year"] == str(year)}
    if state.get("team_commits_date", "") >= csv_date and state.get("team_commits"):
        old_counts = state["team_commits"]
    changed, rose = set(), False
    try:
        rank_rows, msg = _scheduled_rankings(model_dir, sport, year, get)
    except Exception as exc:
        rank_rows, msg = None, f"failed ({exc!r})"
    if rank_rows:
        new_counts = {r[3]: int(r[5]) for r in rank_rows}
        for team in set(old_counts) | set(new_counts):
            if old_counts.get(team, 0) != new_counts.get(team, 0):
                changed.add(team)
                rose = rose or new_counts.get(team, 0) > old_counts.get(team, 0)
        with open(bench, newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            keep = [r for r in reader if not (r[0] == sport and r[1] == str(year))]
        merged = keep + [[str(x) for x in r] for r in rank_rows]
        merged.sort(key=lambda r: (r[0], int(r[1]), int(r[2])))
        _write_csv_atomic(bench, merged, header)
        state["team_commits"], state["team_commits_date"] = new_counts, today
        lines.append(f"  consensus ranks: {len(rank_rows)} programs ({msg}), "
                     f"{len(changed)} with a different commit count")
    else:
        lines.append(f"  consensus ranks: none read ({msg}); kept the old ones")

    # 3. team-targets for the recruits most in need, within the request cap.
    known = known_records(csv_rows, csv_date, state)
    list_keys = [p["person"]["key"] for p in players]
    todo = select_targets(list_keys, known, changed, rose, today, int(opts["refresh_days"]))
    recs = state.setdefault("recruits", {})
    done, failures, reasons = 0, 0, {}
    for key, reason in todo:
        try:
            first = get(f"{ON3}/player/{key}/team-targets")
            items = list((first or {}).get("list", []))
            got = [first]
            tpages = ((first or {}).get("pagination") or {}).get("pageCount") or 1
            for pg in range(2, tpages + 1):
                got.append(get(f"{ON3}/player/{key}/team-targets?page={pg}"))
                items.extend((got[-1] or {}).get("list", []))
        except RequestCap:
            lines.append(f"  request cap ({opts['max_requests']}) reached")
            break
        except Exception:
            failures += 1
            if failures >= int(opts["max_failures"]):
                lines.append(f"  {failures} target requests failed in a row; stopped")
                break
            continue
        failures = 0
        if first is None:
            continue
        for pg, data in enumerate(got, 1):  # refresh the full fetch's raw cache too
            if data is not None:
                _save_raw(raw / "targets" / f"{key}_{pg}.json", data)
        committed, _, offers = _commit_and_offers(items)
        known[key] = recs[str(key)] = {"committed": committed, "offers": offers, "date": today}
        done += 1
        reasons[reason] = reasons.get(reason, 0) + 1
    lines.append(f"  team-targets re-read for {done} of {len(todo)} picked recruits "
                 f"({', '.join(f'{n} {r}' for r, n in reasons.items()) or 'none'})")

    # 4. rebuild the class file from the list + latest known offers; manifest row.
    rows = []
    for p in players:
        person = p["person"]
        rec = known.get(person["key"], {"committed": "", "offers": []})
        rows.append([
            f"https://www.on3.com/db/{person.get('slug', '')}/", year,
            str(person.get("name", "")).strip().upper(), person.get("positionAbbreviation") or "",
            person.get("homeTownName") or "", _stars(p.get("ratings")), rec["committed"], *rec["offers"],
        ])
    rows.sort(key=lambda r: (-r[5], r[2]))
    _write_csv_atomic(out_path, rows)
    commits = [r for r in rows if r[6]]
    with_offers = sum(1 for r in commits if r[7:])
    if mrow is not None:
        mrow.update(fetched=today, rows=str(len(rows)), commits=str(len(commits)),
                    offer_coverage=str(round(with_offers / len(commits), 3) if commits else 0.0))
        _write_csv_atomic(model_dir / "data" / "recruits" / "manifest.csv",
                          [list(r.values()) for r in manifest], list(manifest[0].keys()))
    missing = sum(1 for p in players if p["person"]["key"] not in known)
    lines.append(f"  {len(rows)} recruits, {len(commits)} commits -> {out_path.relative_to(model_dir)}"
                 + (f" ({missing} new recruits without offers yet)" if missing else ""))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state))
    used = getattr(get, "used", None)
    if used is not None:
        lines.append(f"  On3 requests this run: {used}")
    return lines


def fetch(model_dir: Path, offline: bool = False, scheduled: bool = False) -> list[str]:
    """Full rebuild (`ballmonitor fetch ncaaf_recruiting`), or with scheduled=True (what
    `update-and-build` passes) the light daily update of the in-progress football class."""
    model_dir = Path(model_dir)
    if scheduled and not offline:
        return scheduled_update(model_dir)
    lines = []
    for sport, year in CLASSES:
        lines.append(build_class(model_dir, sport, year, offline))
    lines.append(clean_wbb_2024(model_dir))
    lines.append(write_manifest(model_dir))
    lines.append(build_games(model_dir, offline))
    lines.append(build_rankings(model_dir, offline))
    lines.append(build_mbb_ratings(model_dir, offline))
    lines.append(build_bart_players(model_dir, offline))
    lines.append(build_bart_teams(model_dir, offline))
    lines.append(build_wbb_espn(model_dir, offline))
    return lines


if __name__ == "__main__":
    import sys

    for line in fetch(Path(__file__).resolve().parent, offline="--offline" in sys.argv):
        print(line, flush=True)
