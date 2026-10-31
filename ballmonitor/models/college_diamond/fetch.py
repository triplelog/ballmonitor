"""Download NCAA D-I baseball and softball results and build college_diamond's data files.

    ballmonitor fetch college_diamond            # download what is missing, then rebuild
    ballmonitor fetch college_diamond --offline  # rebuild from data/raw/ only

Sources (public, no key; every response cached under data/raw/, which is gitignored):
- NCAA.com scoreboard GraphQL (the request www.ncaa.com/scoreboard/<sport>/d1/... makes):
  https://sdataprod.ncaa.com/?meta=GetContests_web&extensions=<persisted query>
  &variables={"sportCode": "MBA"|"WSB", "division": 1, "seasonYear": season-1,
  "contestDate": "MM/DD/YYYY"}; one request per sport per day Feb 1 - Jun 30, 4 threads,
  retries. Gives home/away, scores (often missing: softball 2015 and 2024, conference-
  tournament games listed vs "TBA"), extra innings, NCAA-championship rows with round and
  seeds. Its conference field is the team's CURRENT conference, not the season's.
- boydsworld.com: every D-I baseball game per season with the site ("@neutral" or the home
  team); one request per season. Primary baseball source (complete, has neutral sites).
- WarrenNolan.com: season RPI tables (conference, records, final RPI rank; baseball
  2021-2026, softball 2023-2025) and, for softball 2023-2025, every team's schedule page
  (results, site, innings); 2 threads with pauses.

Built files (documented in MODEL.md "Method / 1. Data"):
  data/games_<sport>.csv     season,date,game_type(R/C/N),home,away,home_score,away_score,
                             neutral,innings,conf_game,round   (D-I vs D-I games only)
  data/teams_<sport>.csv     season,team,name,conference,source (warrennolan | inferred)
  data/coverage.json         per sport-season counts, selection date, record checks
  data/ncaa_tournaments.json NCAA fields: regional, seed, host, national seed, AQ, stage
  data/conference_formats.json  merged conference tournament formats (with sources)
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GQL = "https://sdataprod.ncaa.com/"
QUERY_HASH = "4bcb5e6432fa9da365c0c19af01b1f9015cc7eb5c21e7af2dba308784a166df7"
UA = {"User-Agent": "Mozilla/5.0 (ballmonitor college_diamond research; polite, cached)"}
SPORT_CODE = {"baseball": "MBA", "softball": "WSB"}
SEASONS = [2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]  # 2020 cancelled
WINDOW = ((2, 1), (6, 30))


def _get(url: str, tries: int = 5) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2.0 * (i + 1))
    raise RuntimeError("unreachable")


def _day_url(sport: str, day: dt.date) -> str:
    variables = {"sportCode": SPORT_CODE[sport], "division": 1, "seasonYear": day.year - 1,
                 "contestDate": day.strftime("%m/%d/%Y")}
    q = {"meta": "GetContests_web",
         "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": QUERY_HASH}}, separators=(",", ":")),
         "variables": json.dumps(variables, separators=(",", ":"))}
    return GQL + "?" + urllib.parse.urlencode(q)


def _trim(contest: dict) -> dict:
    return {
        "id": contest.get("contestId"),
        "date": contest.get("startDate"),
        "state": contest.get("gameState"),
        "final": contest.get("finalMessage"),
        "period": contest.get("currentPeriod"),
        "champ": bool(contest.get("isChampionship")),
        "round": contest.get("roundDescription") or "",
        "teams": [{"id": t.get("seoname"), "name": t.get("nameShort"), "home": t.get("isHome"),
                   "score": t.get("score"), "conf": t.get("conferenceSeo"), "seed": t.get("seed"),
                   "win": t.get("isWinner")} for t in contest.get("teams", [])],
    }


def download_day(raw: Path, sport: str, day: dt.date, offline: bool) -> list[dict] | None:
    path = raw / "ncaa" / sport / f"{day.isoformat()}.json"
    if path.exists():
        return json.loads(path.read_text())
    if offline:
        return None
    try:
        data = json.loads(_get(_day_url(sport, day)))
    except Exception as exc:  # leave uncached; a later run retries
        print(f"  warning: {sport} {day}: {exc}")
        return None
    rows = [_trim(c) for c in (data.get("data") or {}).get("contests") or []]
    path.parent.mkdir(parents=True, exist_ok=True)
    # Do not cache days that are today or later (scores may still change).
    if day < dt.date.today():
        path.write_text(json.dumps(rows, separators=(",", ":")))
    return rows


def season_days(season: int) -> list[dt.date]:
    (m0, d0), (m1, d1) = WINDOW
    start, end = dt.date(season, m0, d0), dt.date(season, m1, d1)
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def download(raw: Path, offline: bool, sports=("baseball", "softball"), seasons=SEASONS,
             workers: int = 4) -> dict[tuple[str, int], dict[str, list[dict]]]:
    out: dict[tuple[str, int], dict[str, list[dict]]] = {}
    for sport in sports:
        for season in seasons:
            days = season_days(season)
            with ThreadPoolExecutor(workers) as ex:
                res = list(ex.map(lambda d: download_day(raw, sport, d, offline), days))
            out[(sport, season)] = {d.isoformat(): r for d, r in zip(days, res) if r}
            n = sum(len(r) for r in out[(sport, season)].values())
            print(f"  {sport} {season}: {len(out[(sport, season)])} days, {n} contests")
    return out


# --- Warren Nolan end-of-season RPI tables (conference, records) --------------------
# https://www.warrennolan.com/<sport>/<season>/rpi-live : one page per sport-season with
# every D-I team's conference, conference record, D-I record, home/road/neutral records
# and final RPI rank. Available for baseball 2021+ and softball 2023-2025 (older pages are
# empty; the softball 2026 page had been reset to a 5-game table when fetched). Used to (a) anchor season-by-season conference membership and (b) verify the
# game data's coverage. Cached in data/raw/warrennolan/.
WN_URL = "https://www.warrennolan.com/{sport}/{season}/rpi-live"
WN_SEASONS = {"baseball": [2021, 2022, 2023, 2024, 2025, 2026], "softball": [2023, 2024, 2025]}
WN_CONF = {"American Athletic": "American", "Colonial Athletic": "Coastal Athletic",
           "Northeast": "NEC", "The Summit League": "Summit League"}


def _wn_record(text: str) -> tuple[int, int, int]:
    parts = [int(x) for x in re.findall(r"\d+", text)]
    parts += [0] * (3 - len(parts))
    return parts[0], parts[1], parts[2]


def warren_nolan(raw: Path, sport: str, season: int, offline: bool) -> list[dict]:
    path = raw / "warrennolan" / f"{sport}_{season}.html"
    if not path.exists():
        if offline:
            return []
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_get(WN_URL.format(sport=sport, season=season)))
        time.sleep(1.0)
    html = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8", errors="ignore"), flags=re.S)
    out = []
    for row in html.split("<tr")[1:]:
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        name_m = re.search(rf'href="/{sport}/{season}/schedule/([^"]+)"[^>]*>([^<]+)</a>', row)
        conf_m = re.search(r'font-weight:normal;">([^<]+?) \((\d+-\d+(?:-\d+)?)\)', row)
        if not cells or not cells[0].isdigit() or not name_m or not conf_m:
            continue
        # Columns after the team: Record, RPI?, SOS, NC Rec, NC RPI, NC SOS, H, R, N, Q1-Q4.
        recs = [c for c in cells[2:] if re.fullmatch(r"\d+-\d+(?:-\d+)?", c)]
        if len(recs) < 5:
            continue
        conf = conf_m.group(1).strip()
        out.append({"rpi_rank": int(cells[0]), "wn_slug": name_m.group(1), "name": name_m.group(2).strip(),
                    "conference": WN_CONF.get(conf, conf), "conf_record": _wn_record(conf_m.group(2)),
                    "record": _wn_record(recs[0]), "home": _wn_record(recs[2]),
                    "road": _wn_record(recs[3]), "neutral": _wn_record(recs[4])})
    return out


# --- Warren Nolan team schedules (softball 2023-2025 game results) ------------------
# NCAA.com's softball scoreboard lacks scores for many 2023-2025 games (e.g. ~70% of
# 2024), so for those seasons every D-I team's schedule page is read instead:
# https://www.warrennolan.com/softball/<season>/schedule/<slug> (date, home/away/neutral
# marker, opponent, score, innings). ~310 pages per season, 2 threads, cached gzipped in
# data/raw/warrennolan/schedules/<season>/<slug>.html.gz.
WN_SCHEDULE = "https://www.warrennolan.com/{sport}/{season}/schedule/{slug}"
WN_SCHEDULE_SEASONS = {"softball": [2023, 2024, 2025]}
MONTHS = {"FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JAN": 1}


def wn_schedule_page(raw: Path, sport: str, season: int, slug: str, offline: bool) -> str | None:
    import gzip
    path = raw / "warrennolan" / "schedules" / sport / str(season) / f"{slug}.html.gz"
    if path.exists():
        return gzip.decompress(path.read_bytes()).decode("utf-8", errors="ignore")
    if offline:
        return None
    try:
        body = _get(WN_SCHEDULE.format(sport=sport, season=season, slug=slug))
    except Exception as exc:
        print(f"  warning: WN schedule {sport} {season} {slug}: {exc}")
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(body))
    time.sleep(0.5)
    return body.decode("utf-8", errors="ignore")


def parse_wn_schedule(html: str, sport: str, season: int) -> list[dict]:
    """Completed games on one team's page: date, opponent slug (None if not D-I), site
    ('home' | 'away' | 'neutral'), own/opp score, innings (0 = regulation)."""
    out = []
    for block in html.split('<li class="team-schedule"')[1:]:
        mon = re.search(r'game-date--month">(\w+)', block)
        day = re.search(r'game-date--day">(\d+)', block)
        loc = re.search(r'team-schedule__location">\s*([A-Z]*)\s*<', block)
        res = re.search(r'team-schedule__result--(win|loss|tie)[^>]*>[WLT]</span>(?:&nbsp;)*\s*(\d+)\s*-\s*(\d+)'
                        r'(?:\s*<br><span[^>]*>\((\d+) Innings\))?', block)
        if not (mon and day and res) or mon.group(1) not in MONTHS:
            continue
        opp = re.search(rf'href="/{sport}/{season}/schedule/([^"]+)"', block)
        site = {"VS": "neutral", "AT": "away"}.get(loc.group(1) if loc else "", "home")
        out.append({"date": dt.date(season, MONTHS[mon.group(1)], int(day.group(1))).isoformat(),
                    "opp": opp.group(1) if opp else None, "site": site,
                    "us": int(res.group(2)), "them": int(res.group(3)),
                    "innings": int(res.group(4)) if res.group(4) else 0})
    return out


def wn_schedules(raw: Path, sport: str, season: int, slugs: list[str], offline: bool) -> dict[str, list[dict]]:
    with ThreadPoolExecutor(2) as ex:
        pages = list(ex.map(lambda sl: wn_schedule_page(raw, sport, season, sl, offline), slugs))
    return {sl: parse_wn_schedule(h, sport, season) for sl, h in zip(slugs, pages) if h}


# --- boydsworld.com baseball scores (neutral-site flags) ----------------------------
# http://www.boydsworld.com/cgi/scores.pl?team1=all&firstyear=Y&team2=all&lastyear=Y&format=HTML
# lists every D-I baseball game with its site ("@neutral" or the home team). One request
# per season, cached in data/raw/boydsworld/<season>.html. Only the site is used: each
# NCAA game is matched by date + score + team-name similarity.
BOYDS_URL = ("http://www.boydsworld.com/cgi/scores.pl?team1=all&firstyear={y}&team2=all"
             "&lastyear={y}&format=HTML&submit=Fetch")


def boydsworld(raw: Path, season: int, offline: bool) -> list[dict]:
    path = raw / "boydsworld" / f"{season}.html"
    if not path.exists():
        if offline:
            return []
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_get(BOYDS_URL.format(y=season)))
        time.sleep(2.0)
    out = []
    html = path.read_text(encoding="latin-1")
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S | re.I):
        c = [re.sub(r"<[^>]+>", "", x).replace("&nbsp;", "").replace("&amp;", "&").strip()
             for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
        c = [x for x in c if x != ""]
        if len(c) < 6 or not re.fullmatch(r"\d+/\d+/\d{4}", c[0]):
            continue
        m, d, y = (int(x) for x in c[0].split("/"))
        try:
            s1, s2 = int(c[2]), int(c[4])
        except ValueError:
            continue
        out.append({"date": dt.date(y, m, d).isoformat(), "t1": c[1], "s1": s1, "t2": c[3], "s2": s2,
                    "site": c[5].lstrip("@")})
    return out


ABBREV = {"st": "state", "ky": "kentucky", "tenn": "tennessee", "la": "louisiana", "ill": "illinois",
          "mich": "michigan", "conn": "connecticut", "ark": "arkansas", "ala": "alabama",
          "colo": "colorado", "ind": "indiana", "mo": "missouri", "fla": "florida", "caro": "carolina",
          "ga": "georgia", "miss": "mississippi", "so": "southern", "ariz": "arizona", "wash": "washington",
          "ore": "oregon", "cal": "california", "n": "north", "s": "south", "e": "east", "w": "west",
          "va": "virginia", "neb": "nebraska", "okla": "oklahoma", "tex": "texas", "mass": "massachusetts",
          "univ": "", "university": "", "college": "", "of": "", "the": "", "u": ""}


def name_tokens(name: str) -> frozenset[str]:
    s = name.lower().replace("&", " and ").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [ABBREV.get(t, t) for t in s.split()]
    return frozenset(t for t in toks if t)


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --- build -------------------------------------------------------------------------
CONF_SLUG = {
    "acc": "ACC", "america-east": "America East", "american": "American", "asun": "ASUN",
    "atlantic-10": "Atlantic 10", "big-12": "Big 12", "big-east": "Big East", "big-sky": "Big Sky",
    "big-south": "Big South", "big-ten": "Big Ten", "big-west": "Big West", "caa": "Coastal Athletic",
    "cusa": "Conference USA", "horizon": "Horizon League", "ivy-league": "Ivy League", "metro": "MAAC",
    "mac": "Mid-American", "meac": "MEAC", "mvc": "Missouri Valley", "mountain-west": "Mountain West",
    "nec": "NEC", "ovc": "Ohio Valley", "pac-12": "Pac-12", "patriot": "Patriot League", "sec": "SEC",
    "socon": "Southern", "southland": "Southland", "swac": "SWAC", "summit-league": "Summit League",
    "sun-belt": "Sun Belt", "wcc": "West Coast", "uac-": "Western Athletic", "di-independent": "Independent",
}
NCAA_ROUNDS = {"Regionals", "Super Regionals", "World Series", "World Series Finals"}
MIN_DI_GAMES = 15          # a team with fewer games vs D-I teams in the file is not D-I
MIN_CONF_GAMES = 9         # plurality games needed to infer a conference
# Days before Selection Monday (baseball) / Sunday (softball) searched for conference
# tournaments; regionals start 4 (baseball) / 5 (softball) days after selection.
TOURNEY_LOOKBACK = 21
SELECTION_OFFSET = {"baseball": 4, "softball": 5}


def _parse_day(rows: list[dict]) -> list[dict]:
    out = []
    for g in rows:
        if g.get("state") != "F" or len(g.get("teams", [])) != 2:
            continue
        a, b = g["teams"]
        if a.get("home") == b.get("home"):
            continue
        home, away = (a, b) if a.get("home") else (b, a)
        try:
            hs, as_ = int(home["score"]), int(away["score"])
        except (TypeError, ValueError):
            continue
        if not home.get("id") or not away.get("id"):
            continue
        m = re.search(r"\((\d+)\)", g.get("period") or "")
        mm, dd, yy = (int(x) for x in g["date"].split("/"))
        out.append({"id": g["id"], "date": dt.date(yy, mm, dd).isoformat(), "home": home["id"],
                    "away": away["id"], "hn": home["name"], "an": away["name"], "hs": hs, "as": as_,
                    "hc": home.get("conf"), "ac": away.get("conf"), "round": g.get("round") or "",
                    "champ": bool(g.get("champ")), "innings": int(m.group(1)) if m else 0,
                    "seeds": (home.get("seed"), away.get("seed"))})
    return out


def _di_teams(games: list[dict]) -> set[str]:
    teams = {g["home"] for g in games} | {g["away"] for g in games}
    for _ in range(4):
        cnt = Counter()
        for g in games:
            if g["home"] in teams and g["away"] in teams:
                cnt[g["home"]] += 1
                cnt[g["away"]] += 1
        teams = {t for t in teams if cnt[t] >= MIN_DI_GAMES}
    return teams


def _match_names(src: list[tuple[str, frozenset[str], tuple[int, int]]],
                 dst: dict[str, tuple[frozenset[str], tuple[int, int]]],
                 aliases: dict[str, str]) -> dict[str, str]:
    """Greedy global matching of (key, name tokens, W-L record) to destination ids:
    score = token Jaccard - 0.15 * |record difference| (games); aliases win outright."""
    out: dict[str, str] = {}
    used: set[str] = set()
    for key, _, _ in src:
        if key in aliases and aliases[key] in dst:
            out[key] = aliases[key]
            used.add(aliases[key])
    cands = []
    for key, toks, rec in src:
        if key in out:
            continue
        for i, (dt_toks, drec) in dst.items():
            sim = similarity(toks, dt_toks)
            diff = abs(rec[0] - drec[0]) + abs(rec[1] - drec[1])
            if sim == 0 and diff > 1:
                continue
            cands.append((sim - 0.15 * diff, key, i))
    for score, key, i in sorted(cands, reverse=True):
        if key in out or i in used or score < -0.5:
            continue
        out[key] = i
        used.add(i)
    return out


# Hand aliases where NCAA short names and other sources share no words.
WN_ALIASES = {"USC": "southern-california", "FAU": "fla-atlantic", "UNCG": "unc-greensboro",
              "UTA": "texas-arlington", "Connecticut": "uconn", "UMass": "massachusetts",
              "Albany": "albany-ny", "Charleston": "col-of-charleston", "Saint-Marys-College": "st-marys-ca",
              "South-Carolina-Upstate": "usc-upstate", "Little-Rock": "ualr", "Tennessee-Martin": "ut-martin",
              "Incarnate-Word": "uiw", "Northern-Illinois": "northern-ill", "Central-Connecticut": "central-conn-st",
              "Southern": "southern-u", "Ole-Miss": "ole-miss", "Omaha": "neb-omaha", "Louisiana": "la-lafayette",
              "Queens": "queens-nc", "Northern-Iowa": "northern-iowa", "Saint-Johns": "st-johns-ny",
              "Fairleigh-Dickinson": "fdu", "IUPUI": "iu-indy", "IU-Indianapolis": "iu-indy",
              "Cal-State-Bakersfield": "bakersfield", "Maryland-Eastern-Shore": "umes",
              "Mississippi-Valley-State": "mississippi-val", "Saint-Thomas": "st-thomas-mn"}


def _season_ncaa(raw: Path, sport: str, season: int, offline: bool) -> list[dict]:
    seen, out = set(), []
    for day in season_days(season):
        rows = download_day(raw, sport, day, offline)
        for g in _parse_day(rows or []):
            if g["id"] not in seen:
                seen.add(g["id"])
                out.append(g)
    return out


def _all_names(raw: Path, sport: str, season: int, min_rows: int = 1) -> dict[str, str]:
    """Every team id -> NCAA short name on the season's scoreboards (scored or not)."""
    out, n = {}, Counter()
    for day in season_days(season):
        for g in download_day(raw, sport, day, True) or []:
            for t in g.get("teams", []):
                if t.get("id") and t["id"] != "tba":
                    out[t["id"]] = t.get("name") or t["id"]
                    n[t["id"]] += 1
    return {i: v for i, v in out.items() if n[i] >= min_rows}


def _records(games: list[dict], teams: set[str]) -> dict[str, tuple[int, int]]:
    rec: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for g in games:
        if g["home"] in teams and g["away"] in teams and g["hs"] != g["as"]:
            w, l = (g["home"], g["away"]) if g["hs"] > g["as"] else (g["away"], g["home"])
            rec[w][0] += 1
            rec[l][1] += 1
    return {k: (v[0], v[1]) for k, v in rec.items()}


def _baseball_from_boyds(raw: Path, season: int, ncaa: list[dict], offline: bool,
                         all_names: dict[str, str]) -> tuple[list[dict], dict]:
    """Boydsworld games re-keyed to NCAA team ids. Name map learned from games that match
    an NCAA game uniquely on (date, winner score, loser score)."""
    boyds = boydsworld(raw, season, offline)
    key = defaultdict(list)
    for g in ncaa:
        if g["hs"] == g["as"]:
            continue
        w, l, ws, ls = ((g["home"], g["away"], g["hs"], g["as"]) if g["hs"] > g["as"]
                        else (g["away"], g["home"], g["as"], g["hs"]))
        key[(g["date"], ws, ls)].append((w, l, g))
    votes: dict[str, Counter] = defaultdict(Counter)
    names = {}
    for g in ncaa:
        names[g["home"]], names[g["away"]] = g["hn"], g["an"]
    for b in boyds:
        if b["s1"] == b["s2"]:
            continue
        w, l, ws, ls = ((b["t1"], b["t2"], b["s1"], b["s2"]) if b["s1"] > b["s2"]
                        else (b["t2"], b["t1"], b["s2"], b["s1"]))
        cands = key.get((b["date"], ws, ls), [])
        if len(cands) == 1:
            votes[w][cands[0][0]] += 1
            votes[l][cands[0][1]] += 1
        elif len(cands) > 1:  # break ties by name similarity
            best = max(cands, key=lambda c: similarity(name_tokens(w), name_tokens(names[c[0]]))
                       + similarity(name_tokens(l), name_tokens(names[c[1]])))
            votes[w][best[0]] += 0.5
            votes[l][best[1]] += 0.5
    bmap = {}
    for bname, c in votes.items():
        (top, n), total = c.most_common(1)[0], sum(c.values())
        if n >= 3 and n >= 0.6 * total:
            bmap[bname] = top
    # Names with no matched NCAA game (their NCAA rows lack scores, or the team was not on
    # the NCAA D-I scoreboard, e.g. reclassifying programs): best unused NCAA name with
    # token similarity >= 0.5, else a slug of the boydsworld name.
    counts = Counter([b["t1"] for b in boyds] + [b["t2"] for b in boyds])
    used = set(bmap.values())
    pool = {i: name_tokens(n) | name_tokens(i.replace("-", " ")) for i, n in all_names.items() if i not in used}
    for bname, n in counts.most_common():
        if bname in bmap or n < 10:
            continue
        bt = name_tokens(bname)
        best = max(pool, key=lambda i: similarity(bt, pool[i]), default=None)
        if best is not None and similarity(bt, pool[best]) >= 0.5:
            bmap[bname] = best
            pool.pop(best)
        else:
            bmap[bname] = re.sub(r"[^a-z0-9]+", "-", bname.lower()).strip("-")
        names.setdefault(bmap[bname], all_names.get(bmap[bname], bname))
    # innings / NCAA round from the matched NCAA game
    out, unmapped = [], Counter()
    for b in boyds:
        t1, t2 = bmap.get(b["t1"]), bmap.get(b["t2"])
        if not t1 or not t2 or t1 == t2:
            unmapped[b["t1"] if not t1 else b["t2"]] += 1
            continue
        site = b["site"]
        if site == "neutral":
            home, away, hs, as_, neutral = t1, t2, b["s1"], b["s2"], True
        elif bmap.get(site) == t2 or (site not in bmap and similarity(name_tokens(site), name_tokens(b["t2"])) >
                                       similarity(name_tokens(site), name_tokens(b["t1"]))):
            home, away, hs, as_, neutral = t2, t1, b["s2"], b["s1"], False
        else:
            home, away, hs, as_, neutral = t1, t2, b["s1"], b["s2"], False
        if site != "neutral" and bmap.get(site) not in (t1, t2) and site not in (b["t1"], b["t2"]):
            # site names a third team or a city: treat as neutral
            neutral = similarity(name_tokens(site), name_tokens(b["t1"])) == 0 and \
                similarity(name_tokens(site), name_tokens(b["t2"])) == 0
        ws, ls = max(hs, as_), min(hs, as_)
        m = [c for c in key.get((b["date"], ws, ls), []) if {c[0], c[1]} == {home, away}]
        ng = m[0][2] if m else None
        out.append({"date": b["date"], "home": home, "away": away, "hs": hs, "as": as_,
                    "neutral": neutral, "innings": ng["innings"] if ng else 0,
                    "round": ng["round"] if ng else "", "champ": ng["champ"] if ng else False,
                    "hn": names.get(home, home), "an": names.get(away, away),
                    "hc": ng["hc"] if ng else None, "ac": ng["ac"] if ng else None})
    info = {"boyds_games": len(boyds), "boyds_kept": len(out), "boyds_names_mapped": len(bmap),
            "unmapped_names_top": unmapped.most_common(8),
            "ncaa_scored_games": len(ncaa), "matched_to_ncaa": sum(1 for g in out if g["hc"] is not None)}
    return out, info


def _champ_rows(raw: Path, sport: str, season: int) -> dict[tuple[str, frozenset], str]:
    """(date, {team ids}) -> round for every NCAA-championship row, scored or not."""
    out = {}
    for day in season_days(season):
        for g in download_day(raw, sport, day, True) or []:
            ids = [t.get("id") for t in g.get("teams", [])]
            if g.get("champ") and len(ids) == 2 and all(ids):
                out[(day.isoformat(), frozenset(ids))] = g.get("round") or "NCAA"
    return out


def _regional_start(raw: Path, sport: str, season: int) -> str:
    per_day = Counter(d for d, _ in _champ_rows(raw, sport, season))
    return min(d for d, n in per_day.items() if n >= 10)


def _softball_selection(raw: Path, season: int) -> dt.date:
    """Selection Sunday = 5 days before the first Friday of regionals (first day with 10+
    championship rows; a few mis-dated rows appear earlier in some seasons)."""
    first = _regional_start(raw, "softball", season)
    day = dt.date.fromisoformat(first)
    while day.weekday() != 4:
        day += dt.timedelta(days=1)
    return day - dt.timedelta(days=SELECTION_OFFSET["softball"])


def _softball_from_wn(raw: Path, season: int, offline: bool) -> tuple[list[dict], dict]:
    wn = warren_nolan(raw, "softball", season, offline)
    names = _all_names(raw, "softball", season, min_rows=15)
    m = _match_names([(w["wn_slug"], name_tokens(w["name"]) | name_tokens(w["wn_slug"].replace("-", " ")), (0, 0))
                      for w in wn],
                     {i: (name_tokens(n) | name_tokens(i.replace("-", " ")), (0, 0)) for i, n in names.items()},
                     WN_ALIASES)
    pages = wn_schedules(raw, "softball", season, [w["wn_slug"] for w in wn], offline)
    champ = _champ_rows(raw, "softball", season)
    out = []
    for slug, rows in pages.items():
        a = m.get(slug)
        if not a:
            continue
        for r in rows:
            if not r["opp"] or r["opp"] not in m:
                continue
            if r["opp"] in pages and r["opp"] < slug:
                continue  # each game is taken once, from the alphabetically first page
            b = m[r["opp"]]
            if r["site"] == "away":
                home, away, hs, as_ = b, a, r["them"], r["us"]
            else:
                home, away, hs, as_ = a, b, r["us"], r["them"]
            rnd = champ.get((r["date"], frozenset((a, b))))
            out.append({"date": r["date"], "home": home, "away": away, "hs": hs, "as": as_,
                        "neutral": r["site"] == "neutral", "innings": r["innings"], "round": rnd or "",
                        "champ": rnd is not None, "hn": names.get(home, home), "an": names.get(away, away),
                        "hc": None, "ac": None})
    return out, {"wn_schedule_pages": len(pages), "wn_names_mapped": len(m), "source": "warrennolan schedules"}


def _infer_conferences(games: list[dict], di: set[str], start: dict[str, str], fixed: set[str],
                       selection: dt.date) -> dict[str, str]:
    """Plurality of opponents' conferences in weekend (Thu-Sun) games from March 1 to
    selection, iterated; teams in `fixed` keep their label (Warren Nolan seasons)."""
    labels = {t: start.get(t, "Independent") for t in di}
    lo = dt.date(selection.year, 3, 1).isoformat()
    hi = selection.isoformat()
    opp: dict[str, list[str]] = defaultdict(list)
    for g in games:
        if g["home"] in di and g["away"] in di and lo <= g["date"] < hi and \
                dt.date.fromisoformat(g["date"]).weekday() >= 3:
            opp[g["home"]].append(g["away"])
            opp[g["away"]].append(g["home"])
    for _ in range(6):
        changed = 0
        new = dict(labels)
        for t in di:
            if t in fixed:
                continue
            c = Counter(labels[o] for o in opp[t] if labels[o] != "Independent")
            top = c.most_common(2)
            if top and top[0][1] >= MIN_CONF_GAMES and (len(top) == 1 or top[0][1] >= 1.5 * top[1][1]):
                lab = top[0][0]
            else:
                lab = "Independent"
            if lab != labels[t]:
                changed += 1
            new[t] = lab
        labels = new
        if not changed:
            break
    return labels


def _tourney_start(conf_games: list[dict], selection: dt.date, n_teams: int) -> str:
    """First date of the conference tournament (or the selection date if none found).

    In the regular season a team plays one conference opponent per weekend series; in a
    tournament teams meet a different conference opponent on consecutive days. The first
    day d (within TOURNEY_LOOKBACK days of selection) on which some team plays a different
    conference opponent than on d-1 marks the tournament; its start is the first day of
    the run of game days containing d-1 (at most 3 days earlier). A best-of-3 title
    series (e.g. Ivy League) is found as a weekend where only one pair plays."""
    lo = selection - dt.timedelta(days=TOURNEY_LOOKBACK)
    win = [g for g in conf_games if lo.isoformat() <= g["date"] < selection.isoformat()]
    by_day: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for g in win:
        by_day[g["date"]][g["home"]].add(g["away"])
        by_day[g["date"]][g["away"]].add(g["home"])
    days = sorted(by_day)
    switch = None
    for d in days:
        prev = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        if prev in by_day and any(t in by_day[prev] and opps - by_day[prev][t] for t, opps in by_day[d].items()):
            switch = prev
            break
    if switch is None:
        # title series: last game days on which only one pair played
        pairs_by_day = {d: {frozenset((g["home"], g["away"])) for g in win if g["date"] == d} for d in days}
        tail = []
        for d in reversed(days):
            if len(pairs_by_day[d]) == 1 and (not tail or pairs_by_day[d] == pairs_by_day[tail[-1]]):
                tail.append(d)
            else:
                break
        busy = [d for d in days if len(pairs_by_day[d]) >= max(2, n_teams // 3)]
        if tail and busy and busy[-1] < tail[-1]:
            return tail[-1]
        return selection.isoformat()
    start = dt.date.fromisoformat(switch)
    floor = start - dt.timedelta(days=3)
    while start - dt.timedelta(days=1) >= floor and (start - dt.timedelta(days=1)).isoformat() in by_day:
        start -= dt.timedelta(days=1)
    return start.isoformat()


def build_season(raw: Path, sport: str, season: int, offline: bool, history: dict,
                 wn_by_season: dict[int, list[dict]]) -> tuple[list, list[dict], dict]:
    from ballmonitor.models.college_diamond.data import Game
    ncaa = _season_ncaa(raw, sport, season, offline)
    info: dict = {"ncaa_scored_games": len(ncaa)}
    if sport == "baseball":
        games, binfo = _baseball_from_boyds(raw, season, ncaa, offline, _all_names(raw, sport, season))
        info.update(binfo)
        sel = dt.date.fromisoformat(history["seasons"][str(season)]["selection_date"])
    elif season in WN_SCHEDULE_SEASONS.get(sport, []):
        games, winfo = _softball_from_wn(raw, season, offline)
        info.update(winfo)
        sel = _softball_selection(raw, season)
    else:
        games = [dict(g, neutral=False) for g in ncaa]
        sel = _softball_selection(raw, season)
    di = _di_teams(games)
    games = [g for g in games if g["home"] in di and g["away"] in di]
    names = {}
    for g in games:
        names[g["home"]], names[g["away"]] = g["hn"], g["an"]
    recs = _records(games, di)
    # --- conference membership
    start = {}
    for g in ncaa:
        for t, c in ((g["home"], g["hc"]), (g["away"], g["ac"])):
            if t in di and c in CONF_SLUG:
                start[t] = CONF_SLUG[c]
    fixed: set[str] = set()
    src = {}
    if season in wn_by_season:
        wn = wn_by_season[season]
        m = _match_names([(w["wn_slug"], name_tokens(w["name"]) | name_tokens(w["wn_slug"].replace("-", " ")),
                           w["record"][:2]) for w in wn],
                         {i: (name_tokens(names[i]) | name_tokens(i.replace("-", " ")), recs.get(i, (0, 0)))
                          for i in di}, WN_ALIASES)
        diffs = []
        for w in wn:
            i = m.get(w["wn_slug"])
            if i:
                start[i] = w["conference"]
                fixed.add(i)
                src[i] = "warrennolan"
                r = recs.get(i, (0, 0))
                diffs.append(abs(r[0] - w["record"][0]) + abs(r[1] - w["record"][1]))
        info["wn_teams"] = len(wn)
        info["wn_matched"] = len(diffs)
        info["record_diff_vs_wn"] = {"exact": sum(d == 0 for d in diffs), "within_2": sum(d <= 2 for d in diffs),
                                     "n": len(diffs), "median": sorted(diffs)[len(diffs) // 2] if diffs else None}
    else:
        near = min(wn_by_season, key=lambda y: abs(y - season)) if wn_by_season else None
        if near is not None:
            info["membership_anchor"] = near
            anchor = wn_by_season[near]
            prev_names = {w["wn_slug"]: w for w in anchor}
            m = _match_names([(w["wn_slug"], name_tokens(w["name"]) | name_tokens(w["wn_slug"].replace("-", " ")),
                               (0, 0)) for w in anchor],
                             {i: (name_tokens(names[i]) | name_tokens(i.replace("-", " ")), (0, 0)) for i in di},
                             WN_ALIASES)
            for slug, i in m.items():
                if similarity(name_tokens(prev_names[slug]["name"]) | name_tokens(slug.replace("-", " ")),
                              name_tokens(names[i]) | name_tokens(i.replace("-", " "))) > 0 or slug in WN_ALIASES:
                    start[i] = prev_names[slug]["conference"]
    labels = _infer_conferences(games, di, start, fixed, sel)
    changed = sum(1 for t in di if t not in fixed and labels[t] != start.get(t))
    info["membership_inferred_changes"] = changed
    # --- game types
    by_conf: dict[str, list[dict]] = defaultdict(list)
    for g in games:
        if labels[g["home"]] == labels[g["away"]] != "Independent" and g["date"] < sel.isoformat():
            by_conf[labels[g["home"]]].append(g)
    size = Counter(labels.values())
    t_start = {c: _tourney_start(gs, sel, size[c]) for c, gs in by_conf.items()}
    out = []
    for g in sorted(games, key=lambda g: g["date"]):
        same = labels[g["home"]] == labels[g["away"]] != "Independent"
        if g["champ"] or (sport == "baseball" and g["date"] > sel.isoformat()):
            gt = "N"
        elif g["date"] > sel.isoformat():
            continue  # softball NISC / other post-selection events
        elif same and g["date"] >= t_start[labels[g["home"]]]:
            gt = "C"
        else:
            gt = "R"
        out.append(Game(season, g["date"], gt, g["home"], g["away"], g["hs"], g["as"],
                        bool(g["neutral"]) or gt == "C" and False, g["innings"], gt == "R" and same,
                        g["round"] if gt == "N" else ""))
    teams = [{"season": season, "team": t, "name": names.get(t, t), "conference": labels[t],
              "source": src.get(t, "inferred")} for t in sorted(di)]
    info.update({"selection": sel.isoformat(), "di_teams": len(di), "games": len(out),
                 "game_types": dict(Counter(g.game_type for g in out)),
                 "conf_tourney_start": dict(sorted(t_start.items()))})
    gp = Counter()
    for g in out:
        if g.game_type != "N":
            gp[g.home] += 1
            gp[g.away] += 1
    vals = sorted(gp[t] for t in di) or [0]
    info["games_per_team_pre_ncaa"] = {"min": vals[0], "p10": vals[len(vals) // 10],
                                       "median": vals[len(vals) // 2], "max": vals[-1]}
    return out, teams, info


ROUND_ORDER = ["Regionals", "Super Regionals", "World Series", "World Series Finals"]


def _tournament_from_rows(raw: Path, sport: str, season: int, di: set[str]) -> dict:
    """Field structure from NCAA-championship scoreboard rows (scored or not): regionals =
    connected groups of teams meeting in 'Regionals' games; supers/WCWS/finals by round.
    Seeds: softball rows carry the national seed (1-16) of seeded teams."""
    rows = []
    for day in season_days(season):
        for g in download_day(raw, sport, day, True) or []:
            ids = [t.get("id") for t in g.get("teams", [])]
            if g.get("champ") and len(ids) == 2 and all(i in di for i in ids):
                rows.append((day.isoformat(), g.get("round") or "", g))
    start = (dt.date.fromisoformat(_regional_start(raw, sport, season)) - dt.timedelta(days=1)).isoformat()
    rows = [r for r in rows if r[0] >= start]
    ws_first = min((d for d, r, _ in rows if r.startswith("World Series")), default="9999")
    rounds: dict[str, list] = defaultdict(list)
    for d, r, g in rows:
        if r == "Finals":
            r = "Super Regionals" if d < ws_first else "World Series Finals"
        rounds[r].append(g)
    parent: dict[str, str] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x
    seeds: dict[str, Counter] = defaultdict(Counter)
    home_n = Counter()
    for g in rounds["Regionals"]:
        a, b = (t["id"] for t in g["teams"])
        parent[find(a)] = find(b)
        for t in g["teams"]:
            if t.get("seed"):
                seeds[t["id"]][t["seed"]] += 1
            if t.get("home"):
                home_n[t["id"]] += 1
    groups: dict[str, list[str]] = defaultdict(list)
    for t in list(parent):
        groups[find(t)].append(t)
    regionals = [sorted(v) for v in groups.values()]

    def teams_in(r):
        return {t["id"] for g in rounds[r] for t in g["teams"]}
    supers, ws, fin = teams_in("Super Regionals"), teams_in("World Series"), teams_in("World Series Finals")
    champion = None
    if rounds["World Series Finals"]:
        wins = Counter(t["id"] for g in rounds["World Series Finals"] for t in g["teams"] if t.get("win"))
        champion = wins.most_common(1)[0][0] if wins else None
    out_regs = []
    nat = {t: c.most_common(1)[0][0] for t, c in seeds.items()}
    seeded = [[t for t in teams if t in nat and 1 <= nat[t] <= 16] for teams in regionals]
    exact = all(len(x) == 1 for x in seeded) and len({nat[x[0]] for x in seeded}) == len(regionals)
    # 2026 softball rows carry group seeds (1-4 = the 16 hosts in four groups, 5-8 = seeds
    # 17-32): host = the regional's team with the lowest seed value <= 4.
    grouped = not exact and all(any(nat.get(t, 99) <= 4 for t in teams) for teams in regionals)
    for teams, sd in zip(regionals, seeded):
        if exact:
            host = sd[0]
        elif grouped:
            host = min(teams, key=lambda t: nat.get(t, 99))
        else:
            host = max(teams, key=lambda t: home_n[t])
        out_regs.append({"teams": teams, "host": host, "winner": next((t for t in teams if t in supers), None),
                         "national_seed": {host: nat[host]} if exact else
                         {host: 4 * (nat[host] - 1) + 1} if grouped else {}})
    return {"regionals": out_regs, "super_teams": sorted(supers), "ws_teams": sorted(ws),
            "finalists": sorted(fin), "champion": champion, "hosts_exact": exact or grouped}


def build_tournaments(data: Path, raw: Path) -> dict:
    """data/ncaa_tournaments.json: per sport/season the field keyed by team id with
    regional number, regional seed (1-4), host flag, national seed, automatic bid, and how
    far each team advanced. Baseball: ncaa_history_baseball.json (Wikipedia brackets)
    mapped to ids; softball: NCAA scoreboard rows (regional seeds 2-4 unknown -> null)."""
    from ballmonitor.models.college_diamond.data import load_games, load_teams
    load_games.cache_clear()
    load_teams.cache_clear()
    out: dict = {}
    for sport in ("baseball", "softball"):
        if not (data / f"games_{sport}.csv").exists():
            continue
        teams = load_teams(sport)
        games = load_games(sport)
        hist_path = data / f"ncaa_history_{sport}.json"
        hist = json.loads(hist_path.read_text()) if hist_path.exists() else {"seasons": {}}
        out[sport] = {}
        for season in SEASONS:
            if season not in teams:
                continue
            T = teams[season]
            n_teams = {g.home for g in games if g.season == season and g.game_type == "N"} | \
                      {g.away for g in games if g.season == season and g.game_type == "N"}
            rec = {"field": {}, "national_seeds": [], "n_national_seeds": 16, "source": ""}
            H = hist["seasons"].get(str(season))
            if sport == "baseball" and H:
                names = {n for r in H["regionals"] for n in r["teams"].values()}
                cand = n_teams or set(T)
                m = _match_names([(n, name_tokens(n), (0, 0)) for n in names],
                                 {i: (name_tokens(T[i]["name"]) | name_tokens(i.replace("-", " ")), (0, 0))
                                  for i in cand if i in T}, HIST_ALIASES)
                ns = [m.get(n) for n in H["national_seeds"]]
                rec["national_seeds"] = ns
                rec["n_national_seeds"] = len(ns)
                aq = {}
                for conf, n in H.get("automatic_qualifiers", {}).items():
                    if m.get(n):
                        aq[m[n]] = conf
                supers = {n for sr in H["super_regionals"] for n in sr["teams"]}
                for k, r in enumerate(H["regionals"]):
                    for seed, n in r["teams"].items():
                        i = m.get(n)
                        rec["field"][i] = {"regional": k, "seed": int(seed), "host": n == r["host"],
                                           "national_seed": ns.index(i) + 1 if i in ns else None,
                                           "auto_bid": i in aq,
                                           "reached": 1 + (n in supers) + (n in H["cws_teams"]) +
                                           (n in H["finalists"]) + (n == H["champion"])}
                rec["source"] = "ncaa_history_baseball.json (Wikipedia brackets)"
            else:
                tr = _tournament_from_rows(raw, sport, season, set(T))
                for k, r in enumerate(tr["regionals"]):
                    for t in r["teams"]:
                        rec["field"][t] = {"regional": k, "seed": 1 if t == r["host"] else None,
                                           "host": t == r["host"], "national_seed": r["national_seed"].get(t),
                                           "auto_bid": None,
                                           "reached": 1 + (t in tr["super_teams"]) + (t in tr["ws_teams"]) +
                                           (t in tr["finalists"]) + (t == tr["champion"])}
                hosts = [r["host"] for r in tr["regionals"]]
                ns = sorted(hosts, key=lambda h: rec["field"][h]["national_seed"] or 99)
                rec["national_seeds"] = ns
                rec["national_seeds_ordered"] = tr["hosts_exact"]
                rec["hosts_approximate"] = not tr["hosts_exact"]
                rec["source"] = "NCAA.com scoreboard championship rows"
            rec["field_size"] = len(rec["field"])
            rec["unmatched_field_teams"] = [t for t in rec["field"] if t is None or t not in T]
            out[sport][str(season)] = rec
    (data / "ncaa_tournaments.json").write_text(json.dumps(out, indent=1))
    return out


FORMAT_FILES = {  # research notes (helpers' reports, with per-entry sources) -> merged file
    "baseball": ["baseball_A_power_conferences.md", "baseball_D_northeast_conferences.md",
                 "baseball_BC_other_conferences.json"],
    "softball": ["softball_power_conferences.md", "softball_other_conferences.json"],
}
FORMAT_KEYS = {"American Conference": "American", "AAC": "American", "CAA": "Coastal Athletic",
               "CUSA": "Conference USA", "Horizon": "Horizon League", "MAC": "Mid-American",
               "MVC": "Missouri Valley", "MWC": "Mountain West", "Northeast": "NEC", "OVC": "Ohio Valley",
               "Patriot": "Patriot League", "SoCon": "Southern", "Summit": "Summit League",
               "WCC": "West Coast", "WAC": "Western Athletic", "Ivy": "Ivy League", "A-10": "Atlantic 10",
               "Atlantic Sun": "ASUN"}


def _read_format_file(path: Path) -> dict:
    txt = path.read_text()
    if path.suffix == ".json":
        d = json.loads(txt)
        return d.get("seasons", d)
    msg = json.loads(txt).get("message", txt)
    blocks = re.findall(r"```json\s*(.*?)```", msg, re.S)
    d = json.loads(blocks[0]) if blocks else {}
    return d.get("seasons", d)


def build_formats(data: Path) -> dict:
    """data/conference_formats.json: sport -> season -> conference -> format entry.
    Researched entries keep their source/verified flag. A conference present in a season's
    team list without a researched entry gets the nearest season's entry for it (marked
    'DRAFT carried from YYYY') or, if none, a generic 'DRAFT' approximation."""
    teams_by = {}
    for sport in ("baseball", "softball"):
        path = data / f"teams_{sport}.csv"
        if path.exists():
            with open(path, newline="") as fh:
                for r in csv.DictReader(fh):
                    teams_by.setdefault(sport, {}).setdefault(int(r["season"]), Counter())[r["conference"]] += 1
    out: dict = {"_about": (
        "Conference tournament formats by sport/season/conference, merged from the research notes "
        "in data/format_research/ (each entry cites its source; verified=false entries were carried "
        "from a neighbouring season by the researcher). Entries with 'DRAFT' in notes were filled "
        "by fetch.py (carried or generic) because no researched entry existed. Formats: single_elim, "
        "double_elim, pods (groups play double-elim or round robin, winners to single elim), "
        "pool_play, series (best-of-3 between top 2), none (regular-season champion gets the bid).")}
    for sport, files in FORMAT_FILES.items():
        merged: dict[str, dict] = defaultdict(dict)
        for name in files:
            path = data / "format_research" / name
            if not path.exists():
                continue
            for season, confs in _read_format_file(path).items():
                if not str(season).isdigit():
                    continue
                for conf, e in confs.items():
                    merged[str(season)][FORMAT_KEYS.get(conf, conf)] = dict(e)
        for season, counts in sorted(teams_by.get(sport, {}).items()):
            for conf, n in counts.items():
                if conf == "Independent" or conf in merged[str(season)]:
                    continue
                near = sorted((abs(int(y) - season), y) for y in merged if conf in merged[y] and y != str(season))
                if near:
                    e = dict(merged[near[0][1]][conf])
                    e["verified"] = False
                    e["notes"] = f"DRAFT carried from {near[0][1]} by fetch.py (no researched entry). " + e.get("notes", "")
                else:
                    k = min(n, 8 if n >= 8 else max(n - 2, 4))
                    e = {"teams": k, "format": "double_elim", "byes": 0, "final": "if_necessary",
                         "auto_bid": "tournament", "description": f"Generic: top {k} teams, double elimination.",
                         "source": "none", "verified": False,
                         "notes": "DRAFT generic approximation by fetch.py; format not researched."}
                merged[str(season)][conf] = e
        out[sport] = {y: dict(sorted(v.items())) for y, v in sorted(merged.items())}
    (data / "conference_formats.json").write_text(json.dumps(out, indent=1))
    return out


HIST_ALIASES: dict[str, str] = {}


def build(model_dir: Path, offline: bool, sports=("baseball", "softball")) -> dict:
    from ballmonitor.models.college_diamond.data import write_games
    raw = model_dir / "data" / "raw"
    data = model_dir / "data"
    cov_path = data / "coverage.json"
    coverage = json.loads(cov_path.read_text()) if cov_path.exists() else {}
    for sport in sports:
        hist_path = data / f"ncaa_history_{sport}.json"
        history = json.loads(hist_path.read_text()) if hist_path.exists() else {"seasons": {}}
        wn_by = {y: warren_nolan(raw, sport, y, offline) for y in WN_SEASONS[sport]}
        wn_by = {y: v for y, v in wn_by.items() if v}
        all_games, all_teams = [], []
        for season in SEASONS:
            games, teams, info = build_season(raw, sport, season, offline, history, wn_by)
            all_games += games
            all_teams += teams
            coverage[f"{sport} {season}"] = info
            print(f"  {sport} {season}: {info['di_teams']} D-I teams, {info['games']} games "
                  f"{info['game_types']} per-team median {info['games_per_team_pre_ncaa']['median']}"
                  + (f", WN record match {info['record_diff_vs_wn']}" if "record_diff_vs_wn" in info else ""))
        write_games(data / f"games_{sport}.csv", all_games)
        with open(data / f"teams_{sport}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["season", "team", "name", "conference", "source"])
            w.writeheader()
            w.writerows(all_teams)
    (data / "coverage.json").write_text(json.dumps(coverage, indent=1, default=str))
    build_tournaments(data, raw)
    build_formats(data)
    return coverage


def fetch(model_dir: Path, offline: bool = False):
    """`ballmonitor fetch college_diamond [--offline]`: download what is missing (NCAA.com
    days, boydsworld seasons, Warren Nolan tables/schedules; all cached in data/raw/),
    then rebuild every file in data/. Yields summary lines."""
    raw = model_dir / "data" / "raw"
    if not offline:
        download(raw, offline=False)
    coverage = build(model_dir, offline=offline)
    for key, info in coverage.items():
        yield (f"{key}: {info['di_teams']} D-I teams, {info['games']} games, "
               f"per-team median {info['games_per_team_pre_ncaa']['median']}")
    yield f"wrote {model_dir / 'data'} (games_*.csv, teams_*.csv, coverage.json, ncaa_tournaments.json, " \
          "conference_formats.json)"


if __name__ == "__main__":
    import sys
    for line in fetch(Path(__file__).resolve().parent, offline="--offline" in sys.argv):
        print(line)
