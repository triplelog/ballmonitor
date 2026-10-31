"""AP Top 25 individual ballots (college football + men's college basketball).

Source: College Poll Tracker (https://collegepolltracker.com, robots.txt allows all).
One "grid" page per poll week lists every AP voter with their full 1-25 ballot:

    https://collegepolltracker.com/football/grid/<season>/<week>
    https://collegepolltracker.com/basketball/grid/<season>/<week>

<week> is `pre-season`, `week-N` or `final-rankings`; each page carries <option> lists of
all seasons and of the weeks of the selected season. The rankings page
(`/<sport>/<season>/<week>`) carries the published points and first-place votes; it is
fetched for one week per season only, to validate the recomputed 25..1 Borda points.

Politeness (see CONTRACT.md / ap_polls.md): sequential requests, 4 s apart, honest
User-Agent, no browser imitation; any 403/429/5xx stops the run. Every page is cached in
data/raw/ap/<sport>/<season>/<week>.html and never fetched again. Routine updates make
one request per sport to `/<sport>/` (its redirect names the latest week) plus one request
per new week page.

Women's basketball ballots are published by AP itself (apnews.com), whose robots.txt
blocks Claude agents, so they are NOT fetched; see `parse_ap_wbb_page`.
"""
from __future__ import annotations

import csv
import gzip
import html
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = "https://collegepolltracker.com"
USER_AGENT = "ballmonitor-ranked-choice/0.1 (personal, non-commercial research)"
DELAY_S = 4.0
TIMEOUT_S = 60
N_PLACES = 25
POINTS = list(range(N_PLACES, 0, -1))

# site sport slug -> (source/file stem, contest prefix, sport label, title word, first season)
SPORTS = {
    "football": ("ap_cfb", "ap-cfb", "college football", "football", 2014),
    "basketball": ("ap_mbb", "ap-mbb", "men's college basketball", "men's basketball", 2014),
}

_last_request = [0.0]
REQUESTS = [0]


class PoliteStop(RuntimeError):
    """Raised on 403/429/5xx: stop everything and report instead of retrying."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib hook
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get(url: str, log=print) -> tuple[int, str, str]:
    """One polite GET without following redirects -> (status, location, body)."""
    wait = _last_request[0] + DELAY_S - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    REQUESTS[0] += 1
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:
            status, loc, body = r.status, "", r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, loc = e.code, e.headers.get("Location", "") or ""
        body = e.read().decode("utf-8", "replace") if e.fp else ""
    finally:
        _last_request[0] = time.monotonic()
    log(f"  GET {url} -> {status}{' ' + loc if loc else ''}")
    if status in (403, 429) or status >= 500:
        raise PoliteStop(f"{url} answered {status}; stopping (back off, retry another day)")
    return status, loc, body


# ---------------------------------------------------------------- parsing

_OPT_RE = re.compile(r'<option value="([^"]*)"( selected="selected")?>([^<]*)</option>')
_SELECT_RE = re.compile(r'<select name="(\w+)"[^>]*>(.*?)</select>', re.S)
_DATE_RE = re.compile(r"AP Poll \(([A-Z][a-z]{2}) (\d{1,2}), (\d{4})\)")
_CELL_RE = re.compile(r'<div class="gridTeam(?: gi_([^"\s]+))?"[^>]*>(.*?)</div>', re.S)
_TITLE_RE = re.compile(r'title="([^"]*)"')
_VOTER_RE = re.compile(r'<div class="gridPollster">(?:<a [^>]*>)?([^<]*)')
_AFF_RE = re.compile(r'<span class="gridPollsterAffiliation">([^<]*)</span>')
_BAR_RE = re.compile(
    r'href="/\w+/team/([^/"]+)/\d+"[^>]*>[^<]*</a>\s*<span class="teamFirst">(.*?)</span>'
    r'.*?<span class="teamPoints"><b>(\d+)</b>', re.S)


def parse_selects(page: str) -> dict[str, tuple[list[str], str]]:
    """{select name: (option values, selected value)} for year / week."""
    out = {}
    for name, body in _SELECT_RE.findall(page):
        vals, sel = [], ""
        for v, s, _ in _OPT_RE.findall(body):
            vals.append(v)
            if s:
                sel = v
        out[name] = (vals, sel)
    return out


def parse_date(page: str) -> str:
    m = _DATE_RE.search(page)
    if not m:
        return ""
    return datetime.strptime(" ".join(m.groups()), "%b %d %Y").date().isoformat()


def parse_grid(page: str) -> list[dict]:
    """Ballots on a grid page: [{voter, affiliation, picks: [(rank, slug, name), ...]}]."""
    ballots = []
    for chunk in page.split('<div class="gridRow">')[1:]:
        chunk = chunk.split('<div class="gridRowHeader">')[0]
        vm = _VOTER_RE.search(chunk)
        if not vm:
            continue
        am = _AFF_RE.search(chunk)
        picks = []
        for i, (slug, inner) in enumerate(_CELL_RE.findall(chunk), start=1):
            if i > N_PLACES:
                break
            if not slug or slug == "blank":  # empty cell (no pick known for this place)
                continue
            tm = _TITLE_RE.search(inner)
            picks.append((i, slug, html.unescape(tm.group(1)) if tm else slug))
        ballots.append({"voter": html.unescape(vm.group(1)).strip(),
                        "affiliation": html.unescape(am.group(1)).strip() if am else "",
                        "picks": picks})
    return ballots


def parse_rankings(page: str) -> list[tuple[str, int, int]]:
    """Published table (top 25 + others receiving votes) -> [(slug, points, first_place)]."""
    out = []
    for chunk in page.split('<div class="teamBar"')[1:]:  # tied teams have no rank shown
        m = _BAR_RE.search(chunk)
        if not m:
            continue
        slug, first, pts = m.groups()
        fm = re.search(r"\((\d+)\)", first)
        out.append((slug, int(pts), int(fm.group(1)) if fm else 0))
    return out


def parse_ap_wbb_page(html_text: str) -> list[dict]:
    """Parse an AP women's basketball poll-voter page into ballot rows (NOT IMPLEMENTED).

    AP publishes every women's basketball Top 25 ballot on apnews.com (poll voter pages),
    but apnews.com's robots.txt disallows Claude agents, so this project does not fetch
    it. If the user later provides saved pages (manually downloaded), implement this to
    return rows with the CONTRACT.md ballot columns (contest_id `ap-wbb-<YYYY-YY>-wkNN`,
    voter, affiliation, rank, candidate_id, candidate, team="") and source `ap_wbb`.
    """
    raise NotImplementedError("AP women's basketball ballots: apnews.com is not fetched")


# ---------------------------------------------------------------- labels

def season_label(sport: str, season: int) -> str:
    """Football `2025`; basketball site season 2025 is the 2025-26 season."""
    return str(season) if sport == "football" else f"{season}-{(season + 1) % 100:02d}"


def week_label(week: str) -> str:
    if week == "pre-season":
        return "pre"
    if week == "final-rankings":
        return "final"
    m = re.fullmatch(r"week-(\d+)", week)
    if not m:
        raise ValueError(f"unknown week slug {week!r}")
    return m.group(1)


def week_sort(week: str) -> int:
    lab = week_label(week)
    return -1 if lab == "pre" else 999 if lab == "final" else int(lab)


def contest_id(sport: str, season: int, week: str) -> str:
    lab = week_label(week)
    tail = lab if lab in ("pre", "final") else f"wk{int(lab):02d}"
    return f"{SPORTS[sport][1]}-{season_label(sport, season)}-{tail}"


# ---------------------------------------------------------------- download

def _grid_url(sport, season, week):
    return f"{BASE}/{sport}/grid/{season}/{week}"


def _rank_url(sport, season, week):
    return f"{BASE}/{sport}/{season}/{week}"


def _cached_weeks(raw: Path, sport: str, season: int) -> dict[str, Path]:
    d = raw / sport / str(season)
    if not d.is_dir():
        return {}
    return {p.stem: p for p in d.glob("*.html") if not p.stem.startswith("rankings_")}


def _known_weeks(raw: Path, sport: str, season: int) -> set[str]:
    """Union of the week <option>s on every cached grid page of the season."""
    weeks = set()
    for p in _cached_weeks(raw, sport, season).values():
        page = p.read_text(encoding="utf-8")
        weeks.update(parse_selects(page).get("week", ([], ""))[0])
        weeks.add(p.stem)
    return {w for w in weeks if re.fullmatch(r"pre-season|final-rankings|week-\d+", w)}


def _fetch_grid(raw, sport, season, week, log) -> bool:
    status, loc, body = _get(_grid_url(sport, season, week), log)
    if status != 200 or '<div class="gridRow">' not in body:
        log(f"  ! no ballots at {sport} {season} {week} (status {status}); not cached")
        return False
    p = raw / sport / str(season) / f"{week}.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return True


def _built_ids(out_dir: Path, sport: str) -> set[str]:
    """Contest ids already in the built contests CSV. On a machine without the raw cache
    (e.g. the daily CI build) these count as downloaded, so only new weeks are requested."""
    path = out_dir / f"{SPORTS[sport][0]}_contests.csv.gz"
    if not path.exists():
        return set()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return {r["contest_id"] for r in csv.DictReader(f)}


def _download_sport(raw: Path, sport: str, log, have: set[str] = frozenset()) -> None:
    first = SPORTS[sport][4]
    done = lambda season, w: contest_id(sport, season, w) in have  # noqa: E731
    # 1 request: /<sport>/ redirects to the latest released week (its body is that week's
    # rankings page, which we keep for validation).
    status, loc, body = _get(f"{BASE}/{sport}/", log)
    m = re.search(rf"/{sport}/(\d{{4}})/([\w-]+)/?$", loc)
    if not m:
        raise RuntimeError(f"/{sport}/ did not redirect to a week (status {status}, {loc!r})")
    cur_season, cur_week = int(m.group(1)), m.group(2)
    log(f"{sport}: latest released poll is {cur_season} {cur_week}")
    sel = parse_selects(body)
    if (sel.get("year", ([], ""))[1] == str(cur_season)
            and sel.get("week", ([], ""))[1] == cur_week and parse_rankings(body)):
        rp = raw / sport / str(cur_season) / f"rankings_{cur_week}.html"
        if not rp.exists():
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(body, encoding="utf-8")

    for season in range(first, cur_season + 1):
        cached = _cached_weeks(raw, sport, season)
        known = _known_weeks(raw, sport, season)
        if season == cur_season:
            # the latest week's grid page carries the up-to-date week list
            if cur_week not in cached and not done(season, cur_week):
                _fetch_grid(raw, sport, season, cur_week, log)
        elif done(season, "final-rankings"):
            continue  # complete season already built (no raw cache needed)
        elif "final-rankings" not in known:
            # past season never seen complete: its final page lists every week
            if "final-rankings" not in cached:
                _fetch_grid(raw, sport, season, "final-rankings", log)
        known = _known_weeks(raw, sport, season)
        cached = _cached_weeks(raw, sport, season)
        missing = sorted((w for w in known if w not in cached and not done(season, w)), key=week_sort)
        if season == cur_season:
            missing = [w for w in missing if week_sort(w) <= week_sort(cur_week)]
        for w in missing:
            _fetch_grid(raw, sport, season, w, log)
        # validation: one published rankings page per season
        d = raw / sport / str(season)
        if d.is_dir() and not list(d.glob("rankings_*.html")):
            cached = _cached_weeks(raw, sport, season)
            vw = "final-rankings" if "final-rankings" in cached else (
                min(cached, key=week_sort) if cached else None)
            if vw:
                st, _, rb = _get(_rank_url(sport, season, vw), log)
                if st == 200 and parse_rankings(rb):
                    (d / f"rankings_{vw}.html").write_text(rb, encoding="utf-8")


# ---------------------------------------------------------------- build

def _keep_built(bpath: Path, cpath: Path, rebuilt: set[str]) -> tuple[list[list], list[dict]]:
    """Rows and contests of the existing CSVs whose contest was not rebuilt from raw pages."""
    if not (bpath.exists() and cpath.exists()):
        return [], []
    with gzip.open(cpath, "rt", encoding="utf-8", newline="") as f:
        contests = [r for r in csv.DictReader(f) if r["contest_id"] not in rebuilt]
    keep = {c["contest_id"] for c in contests}
    if not keep:
        return [], []
    for c in contests:
        c["n_ballots"] = int(c["n_ballots"])
    with gzip.open(bpath, "rt", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader)
        rows = [r for r in reader if r[0] in keep]
    return rows, contests


def _build_sport(raw: Path, out_dir: Path, sport: str, log) -> list[str]:
    stem, _prefix, sport_name, title_word, first = SPORTS[sport]
    rows, contests = [], []
    n_checked = n_ok = 0
    seasons = sorted(int(p.name) for p in (raw / sport).glob("*")
                     if p.is_dir() and p.name.isdigit() and int(p.name) >= first)
    for season in seasons:
        for week, path in sorted(_cached_weeks(raw, sport, season).items(),
                                 key=lambda kv: week_sort(kv[0])):
            page = path.read_text(encoding="utf-8")
            ballots = parse_grid(page)
            if not ballots:
                log(f"  ! {sport} {season} {week}: cached page has no ballots; skipped")
                continue
            cid = contest_id(sport, season, week)
            pts, fpv = defaultdict(int), defaultdict(int)
            empty = [b["voter"] for b in ballots if not b["picks"]]
            if empty:
                log(f"  ! {cid}: listed voter(s) with no ballot on the site, dropped: {empty}")
                ballots = [b for b in ballots if b["picks"]]
            if not ballots:
                log(f"  ! {cid}: no ballots on the site for this week (gap); no contest row")
                continue
            for b in ballots:
                if len(b["picks"]) != N_PLACES:
                    log(f"  ! {cid}: {b['voter']} has {len(b['picks'])} picks")
                for rank, slug, name in b["picks"]:
                    rows.append([cid, b["voter"], b["affiliation"], rank, slug, name, ""])
                    pts[slug] += POINTS[rank - 1]
                    fpv[slug] += rank == 1
            published = ""
            rp = path.parent / f"rankings_{week}.html"
            if rp.exists():
                pub = parse_rankings(rp.read_text(encoding="utf-8"))
                published = ";".join(f"{s}:{p}:{f}" for s, p, f in pub)
                n_checked += 1
                bad = [(s, p, f, pts.get(s, 0), fpv.get(s, 0)) for s, p, f in pub
                       if p != pts.get(s, 0) or f != fpv.get(s, 0)]
                extra = set(pts) - {s for s, _, _ in pub}
                if bad or extra:
                    log(f"  ! {cid}: published vs recomputed mismatch "
                        f"{bad[:5]} unlisted={sorted(extra)[:5]}")
                else:
                    n_ok += 1
                    log(f"  {cid}: recomputed points/first-place votes match published "
                        f"({len(pub)} teams)")
            lab = week_label(week)
            contests.append({
                "contest_id": cid, "source": stem, "sport": sport_name, "league": "AP",
                "award": "Top 25", "season": season_label(sport, season), "week": lab,
                "date": parse_date(page),
                "title": f"AP Top 25 {title_word} {season_label(sport, season)} "
                         + ({"pre": "preseason", "final": "final"}.get(lab) or f"week {lab}"),
                "n_places": N_PLACES, "points": ",".join(map(str, POINTS)),
                "n_ballots": len(ballots), "published": published,
                "url": _grid_url(sport, season, week)})
    out_dir.mkdir(parents=True, exist_ok=True)
    bpath, cpath = out_dir / f"{stem}.csv.gz", out_dir / f"{stem}_contests.csv.gz"
    kept = _keep_built(bpath, cpath, {c["contest_id"] for c in contests})
    if kept[1]:
        log(f"{stem}: kept {len(kept[1])} contests from the existing CSV (no raw page on this machine)")
        rows = kept[0] + rows
        contests = kept[1] + contests
    with gzip.open(bpath, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["contest_id", "voter", "affiliation", "rank", "candidate_id",
                    "candidate", "team"])
        w.writerows(rows)
    with gzip.open(cpath, "wt", encoding="utf-8", newline="") as f:
        cols = ["contest_id", "source", "sport", "league", "award", "season", "week",
                "date", "title", "n_places", "points", "n_ballots", "published", "url"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(contests)
    log(f"{stem}: {len(contests)} contests, {sum(c['n_ballots'] for c in contests)} ballots, "
        f"{len(rows)} rows; validated {n_ok}/{n_checked} weeks against published points")
    return [str(bpath), str(cpath)]


def fetch(model_dir: Path, offline: bool = False, log=print) -> list[str]:
    """Download new AP grid pages (unless offline) and rebuild the ballot CSVs from cache."""
    model_dir = Path(model_dir)
    raw = model_dir / "data" / "raw" / "ap"
    out_dir = model_dir / "data" / "ballots"
    if not offline:
        REQUESTS[0] = 0
        try:
            for sport in SPORTS:
                _download_sport(raw, sport, log, _built_ids(out_dir, sport))
        except PoliteStop as e:
            log(f"STOPPED: {e}")
        log(f"requests made this run: {REQUESTS[0]}")
    written = []
    for sport in SPORTS:
        written += _build_sport(raw, out_dir, sport, log)
    return written
