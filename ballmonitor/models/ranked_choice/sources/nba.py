"""NBA media-voter ballots for the single-winner regular-season awards.

Discovery (all allowed by robots.txt, fetched with an honest User-Agent, >= 1.5 s apart):

* official.nba.com award pages for 2013-14 .. 2016-17 (slugs found in its wp-sitemap)
* pr.nba.com ``voting-results-<season>-nba-regular-season-awards`` pages, 2017-18 onward
  (found in its sitemap_index -> post-sitemap*.xml)

Every page is cached in ``data/raw/nba/`` and a manifest of the linked award PDFs is
written to ``data/raw/nba/manifest.csv``.

The PDFs themselves live on ``ak-static.cms.nba.com/wp-content/uploads/`` (2013-14:
``www.nba.com/media/``, now 404). ``ak-static.cms.nba.com/robots.txt`` has
``Disallow: /wp-content/uploads/`` for ``User-agent: *``, so this module does NOT download
them: every PDF URL is checked with ``urllib.robotparser`` first and skipped if disallowed.
PDFs present in ``data/raw/nba/pdf/`` (saved by ``tools/download.py nba``, which the user
runs, or by hand) are parsed by ``nba_pdf.py`` and checked against the totals tables.
"""

from __future__ import annotations

import csv
import gzip
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

UA = "ballmonitor-ranked-choice/0.1 (personal, non-commercial research)"
DELAY = 1.5

INDEX_PAGES = {
    "2013-14": "https://official.nba.com/2014-nba-year-annual-award-voting-results/",
    "2014-15": "https://official.nba.com/2015-nba-year-annual-award-voting-results/",
    "2015-16": "https://official.nba.com/2015-16-nba-annual-award-voting-results/",
    "2016-17": "https://official.nba.com/2016-17-nba-annual-award-voting-results/",
    **{
        f"{y}-{(y + 1) % 100:02d}":
            f"https://pr.nba.com/voting-results-{y}-{(y + 1) % 100:02d}-nba-regular-season-awards/"
        for y in range(2017, 2026)
    },
}

# award key -> (display name, filename regex). Order matters: team awards first so that
# e.g. "All-Rookie" is not mistaken for "Rookie of the Year".
AWARDS = [
    ("all-nba", "All-NBA Teams", r"all-nba"),
    ("all-defensive", "All-Defensive Teams", r"all-defensive"),
    ("all-rookie", "All-Rookie Teams", r"all-rookie"),
    ("mvp", "MVP", r"mvp|most-valuable"),
    ("roy", "Rookie of the Year", r"rookie|roy"),
    ("dpoy", "Defensive Player of the Year", r"defensive-player"),
    ("smoy", "Sixth Man of the Year", r"sixth-man"),
    ("mip", "Most Improved Player", r"most-improved"),
    ("coy", "Coach of the Year", r"coach"),
    ("cpoy", "Clutch Player of the Year", r"clutch"),
]
TEAM_AWARDS = {"all-nba", "all-defensive", "all-rookie"}

BALLOT_COLUMNS = ["contest_id", "voter", "affiliation", "rank", "candidate_id",
                  "candidate", "team"]
CONTEST_COLUMNS = ["contest_id", "source", "sport", "league", "award", "season", "week",
                   "date", "title", "n_places", "points", "n_ballots", "published", "url"]
MANIFEST_COLUMNS = ["season", "award", "award_name", "kind", "scope", "robots_allowed",
                    "cached", "index_url", "pdf_url"]

_last_request = [0.0]
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


def _get(url: str) -> bytes:
    wait = DELAY - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    finally:
        _last_request[0] = time.monotonic()


def _robots_allowed(url: str, offline: bool, raw: Path) -> bool | None:
    """True/False from the host's robots.txt (cached in raw/, refreshed when online);
    None if unknown."""
    host = urlparse(url).netloc
    if host not in _robots:
        cache = raw / f"robots_{host}.txt"
        if not offline:
            try:
                cache.write_bytes(_get(f"https://{host}/robots.txt"))
            except urllib.error.URLError:
                pass
        if not cache.exists():
            return None
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(cache.read_text("utf-8", "replace").splitlines())
        _robots[host] = rp
    return _robots[host].can_fetch(UA, url)


def _classify(pdf_url: str) -> tuple[str, str, str]:
    name = pdf_url.rsplit("/", 1)[-1].lower()
    award, award_name = "", ""
    for key, disp, pat in AWARDS:
        if re.search(pat, name):
            award, award_name = key, disp
            break
    if "selection" in name or (name.endswith("-votes.pdf") and "team" not in name):
        kind = "voter_selections"
    elif re.search(r"result|total", name):
        kind = "totals"
    else:
        kind = "unknown"  # some files hold both ballots and totals; check the PDF
    return award, award_name, kind


def _pdf_links(html: str) -> list[str]:
    skip = re.compile(r"Consitution|Constitution|CBA|Bargaining|Officia|Concussion|Undergrad",
                      re.I)
    links = re.findall(r'href="([^"]+\.pdf)"', html)
    return sorted({u for u in links if not skip.search(u) and re.search(r"20\d\d", u)})


def fetch(model_dir: Path, offline: bool = False, log=print) -> list[str]:
    model_dir = Path(model_dir)
    raw = model_dir / "data" / "raw" / "nba"
    pdf_dir = raw / "pdf"
    out_dir = model_dir / "data" / "ballots"
    raw.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for season, url in INDEX_PAGES.items():
        host = "official" if "official.nba.com" in url else "pr"
        page = raw / f"index_{host}_{season}.html"
        # Award pages are final once the season's awards are out; refetch only if missing.
        if not page.exists():
            if offline:
                log(f"nba: {season}: index page not cached (offline) — skipped")
                continue
            try:
                page.write_bytes(_get(url))
                log(f"nba: fetched {url}")
            except urllib.error.URLError as e:
                log(f"nba: {season}: {url} failed: {e}")
                continue
        for pdf in _pdf_links(page.read_text("utf-8", "replace")):
            award, award_name, kind = _classify(pdf)
            if not award:
                continue
            fname = pdf.rsplit("/", 1)[-1]
            cached = (pdf_dir / fname).exists()
            gone = (pdf_dir / (fname + ".404")).exists()  # known-dead link: don't retry
            allowed = _robots_allowed(pdf, offline, raw)
            scope = "out_of_scope_tiered" if award in TEAM_AWARDS else "single_winner"
            if scope == "single_winner" and not cached and not gone and not offline:
                if allowed:
                    try:
                        pdf_dir.mkdir(exist_ok=True)
                        (pdf_dir / fname).write_bytes(_get(pdf))
                        cached = True
                        log(f"nba: fetched {pdf}")
                    except urllib.error.HTTPError as e:
                        log(f"nba: {pdf} failed: {e}")
                        if e.code == 404:
                            (pdf_dir / (fname + ".404")).write_text(f"{e}\n")
                    except urllib.error.URLError as e:
                        log(f"nba: {pdf} failed: {e}")
                else:
                    log(f"nba: robots.txt disallows {pdf} — not fetched")
            manifest.append({
                "season": season, "award": award, "award_name": award_name, "kind": kind,
                "scope": scope, "robots_allowed": "" if allowed is None else str(allowed),
                "cached": str(cached), "index_url": url, "pdf_url": pdf,
            })

    if manifest:  # offline with no network: keep the last manifest if nothing was read
        with open(raw / "manifest.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
            w.writeheader()
            w.writerows(manifest)

    in_scope = [m for m in manifest if m["scope"] == "single_winner"]
    have = [m for m in in_scope if m["cached"] == "True" or (pdf_dir / m["pdf_url"].rsplit("/", 1)[-1]).exists()]
    log(f"nba: {len(in_scope)} single-winner award PDFs listed, {len(have)} downloaded")
    return build(have, pdf_dir, out_dir, log)


POINTS = {"mvp": [10, 7, 5, 3, 1]}
DEFAULT_POINTS = [5, 3, 1]


def build(files: list[dict], pdf_dir: Path, out_dir: Path, log) -> list[str]:
    """Parse downloaded PDFs (see nba_pdf.py) into the contract CSVs, validating against totals."""
    from ballmonitor.models.ranked_choice.sources import nba_pdf

    groups: dict[tuple, list[dict]] = {}
    for m in files:
        groups.setdefault((m["season"], m["award"]), []).append(m)
    rows, contests, n_ok, n_val = [], [], 0, 0
    for (season, award), ms in sorted(groups.items()):
        pts = POINTS.get(award, DEFAULT_POINTS)
        n = len(pts)
        ballots, totals, abstained, seen = [], [], 0, set()
        for m in ms:
            res = nba_pdf.parse_pdf(pdf_dir / m["pdf_url"].rsplit("/", 1)[-1], n)
            for p in res["problems"]:
                log(f"  ! {p}")
            for voter, aff, picks in res["ballots"]:
                if (voter, aff) in seen:
                    continue
                seen.add((voter, aff))
                if picks is None:
                    abstained += 1
                else:
                    ballots.append((voter, aff, picks))
            totals += res["totals"]
        if not ballots:
            log(f"  {season} {award}: totals only, no voter file downloaded yet")
            continue
        # one display name per person. Most reliable first: ballot cells with a comma
        # ("Last, First"), then the totals table, then comma-less ballot cells (2022-23)
        disp: dict[str, tuple[str, str]] = {}
        no_comma = season == "2022-23"
        sources = ([] if no_comma else [p for _, _, picks in ballots for p in picks]) + \
                  [(f, l, t) for f, l, t, *_ in totals] + \
                  ([p for _, _, picks in ballots for p in picks] if no_comma else [])
        for first, last, team in sources:
            disp.setdefault(nba_pdf.key(first, last), (f"{first} {last}", team))
        # totals names that differ from the ballots' ("Cam" vs "Cameron"): same surname + initial
        ballot_keys = {nba_pdf.key(f, l): (f, l) for _, _, picks in ballots for f, l, _ in picks}
        alias = {}
        for first, last, *_ in totals:
            k = nba_pdf.key(first, last)
            if k in ballot_keys:
                continue
            same = [bk for bk, (f, l) in ballot_keys.items()
                    if {nba_pdf.ascii_fold(l).lower(), nba_pdf.ascii_fold(f).lower()} & {nba_pdf.ascii_fold(last).lower(), nba_pdf.ascii_fold(first).lower()}
                    and (f[:1].lower() in (first[:1].lower(), last[:1].lower()))]
            if len(same) == 1:
                alias[k] = same[0]
                disp[k] = disp[same[0]] if same[0] in disp else disp[k]
        score: dict[str, int] = {}
        firsts: dict[str, int] = {}
        cid = f"nba-{season}-{award}"
        for voter, aff, picks in ballots:
            for r, (first, last, team) in enumerate(picks, 1):
                k = nba_pdf.key(first, last)
                name, team0 = disp[k]
                rows.append([cid, voter, aff, r, nba_pdf.slug(name), name, team or team0])
                score[k] = score.get(k, 0) + pts[r - 1]
                firsts[k] = firsts.get(k, 0) + (r == 1)
        published = ""
        if totals:
            n_val += 1
            tot = {alias.get(nba_pdf.key(f, l), nba_pdf.key(f, l)): (p, fp) for f, l, _, p, fp in totals}
            bad = [(disp.get(k, (k,))[0], p, score.get(k, 0)) for k, (p, fp) in tot.items() if score.get(k, 0) != p]
            if bad:
                log(f"  ! {cid}: recomputed points differ from the totals for {len(bad)}: {bad[:4]}")
            else:
                n_ok += 1
            published = ";".join(f"{nba_pdf.slug(disp.get(k, (k,))[0])}:{p}:{fp}"
                                 for k, (p, fp) in sorted(tot.items(), key=lambda kv: -kv[1][0]))
        contests.append({
            "contest_id": cid, "source": "nba", "sport": "basketball", "league": "NBA",
            "award": dict((k, d) for k, d, _ in AWARDS).get(award, award), "season": season, "week": "",
            "date": "", "title": f"{season} NBA {dict((k, d) for k, d, _ in AWARDS).get(award, award)}",
            "n_places": n, "points": ",".join(map(str, pts)), "n_ballots": len(ballots),
            "published": published, "url": ms[0]["index_url"]})
        if abstained:
            log(f"  {cid}: {abstained} abstention(s) left out")
    # the same person keeps one display name in every season (prefer the accented spelling)
    best: dict[str, str] = {}
    for r in rows:
        cur = best.get(r[4])
        if cur is None or (r[5] != nba_pdf.ascii_fold(r[5]) and cur == nba_pdf.ascii_fold(cur)) \
                or ("'" in r[5] and "'" not in cur):
            best[r[4]] = r[5]
    for r in rows:
        r[5] = best[r[4]]
    ballots_path = out_dir / "nba.csv.gz"
    contests_path = out_dir / "nba_contests.csv.gz"
    out_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(ballots_path, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(BALLOT_COLUMNS)
        w.writerows(rows)
    with gzip.open(contests_path, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CONTEST_COLUMNS)
        w.writeheader()
        w.writerows(contests)
    log(f"nba: {len(contests)} contests, {sum(c['n_ballots'] for c in contests)} ballots; "
        f"recomputed points match the totals in {n_ok}/{n_val} contests with a totals table")
    return [str(ballots_path), str(contests_path)]
