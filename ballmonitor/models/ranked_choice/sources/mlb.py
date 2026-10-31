"""BBWAA individual award ballots (MVP, Cy Young, Rookie of the Year, Manager of the
Year; AL and NL) from bbwaa.com, 2012 onward.

Discovery: bbwaa.com's WordPress sitemaps (`post-sitemap.xml`, `page-sitemap.xml`) list
the results posts (`/24-al-cy/`, `/24-nl-mgr/`, ...) and the separate MVP ballot pages
(`/24-al-mvp-ballots/`). Cy Young / ROY / Manager posts carry both the results table and
the ballot table; MVP results come from the post and ballots from the `-ballots` page.

Ballot cells usually give surnames only; they are mapped to the full names in the
results table of the same contest (see `sources/mlb.md`). Stdlib only.
"""
from __future__ import annotations

import csv
import difflib
import gzip
import html
import io
import re
import time
import unicodedata
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://bbwaa.com"
USER_AGENT = "ballmonitor-ranked-choice/0.1 (personal, non-commercial research)"
DELAY = 2.0  # seconds between requests (contract: >= 1.5)
FIRST_SEASON = 2012  # first season with individual ballots published

AWARDS = {  # slug code -> (award name, points by place)
    "mvp": ("MVP", [14, 9, 8, 7, 6, 5, 4, 3, 2, 1]),
    "cy": ("Cy Young", [7, 4, 3, 2, 1]),
    "roy": ("Rookie of the Year", [5, 3, 1]),
    "mgr": ("Manager of the Year", [5, 3, 1]),
}
AWARD_SLUG = {"mvp": "mvp", "cy": "cy-young", "roy": "roy", "mgr": "moy"}
SLUG_CODE = {"mvp": "mvp", "cy": "cy", "roy": "roy", "rookie": "roy", "mgr": "mgr", "nmgr": "mgr"}

# Results posts whose slug does not follow the `YY-lg-award` pattern.
SLUG_OVERRIDES = {
    (2023, "al", "roy"): "orioles-gunnar-henderson-unanimously-wins-al-jackie-robinson-rookie-of-the-year",
}

# Club nickname (as printed in BBWAA results tables) -> abbreviation.
TEAM_ABBR = {
    "angels": "LAA", "astros": "HOU", "athletics": "ATH", "a's": "ATH", "blue jays": "TOR",
    "braves": "ATL", "brewers": "MIL", "cardinals": "STL", "cubs": "CHC",
    "diamondbacks": "ARI", "d-backs": "ARI", "dbacks": "ARI", "dodgers": "LAD",
    "giants": "SF", "guardians": "CLE", "indians": "CLE", "mariners": "SEA",
    "marlins": "MIA", "mets": "NYM", "nationals": "WSH", "orioles": "BAL", "padres": "SD",
    "phillies": "PHI", "pirates": "PIT", "rangers": "TEX", "rays": "TB", "red sox": "BOS",
    "reds": "CIN", "rockies": "COL", "royals": "KC", "tigers": "DET", "twins": "MIN",
    "white sox": "CWS", "yankees": "NYY",
}

FUZZY_MIN = 0.75  # min difflib ratio to accept a misspelled surname (every use is logged)

# Typos in BBWAA results tables (display name as printed -> correct name).
NAME_FIXES = {
    "Jordan Pachecho": "Jordan Pacheco",  # 2012 NL ROY results table; ballots say "Pacheco"
    "Jordan Zimmerman": "Jordan Zimmermann",  # 2013 NL Cy Young results table
    "Travis d'Arnau": "Travis d'Arnaud",  # 2014 NL ROY results table
    "Kolton Wong": "Kolten Wong",  # results-table misspelling
}

# Points by ballot length; the length is read from each ballot table and the scoring
# sentence on the page is checked against it.
POINTS_BY_PLACES = {
    10: [14, 9, 8, 7, 6, 5, 4, 3, 2, 1],
    5: [7, 4, 3, 2, 1],
    3: [5, 3, 1],
}
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "fourteen": 14}

CONTEST_COLS = ["contest_id", "source", "sport", "league", "award", "season", "week", "date",
                "title", "n_places", "points", "n_ballots", "published", "url"]
BALLOT_COLS = ["contest_id", "voter", "affiliation", "rank", "candidate_id", "candidate", "team"]


# ---------------------------------------------------------------- fetching

class _Fetcher:
    def __init__(self, raw: Path, offline: bool, log):
        self.raw, self.offline, self.log = raw, offline, log
        self.last = 0.0
        self.blocked: list[str] = []

    def get(self, slug: str, fname: str, refresh: bool = False) -> str | None:
        path = self.raw / fname
        if path.exists() and not refresh:
            return path.read_text(encoding="utf-8")
        if self.offline:
            return path.read_text(encoding="utf-8") if path.exists() else None
        wait = DELAY - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        url = f"{BASE}/{slug}" if slug.endswith(".xml") else f"{BASE}/{slug}/"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            self.log(f"  HTTP {e.code} for {url} — not retried")
            self.blocked.append(f"{url} HTTP {e.code}")
            return path.read_text(encoding="utf-8") if path.exists() else None
        except urllib.error.URLError as e:
            self.log(f"  failed {url}: {e.reason}")
            return path.read_text(encoding="utf-8") if path.exists() else None
        finally:
            self.last = time.monotonic()
        path.write_text(text, encoding="utf-8")
        self.log(f"  fetched {url}")
        return text


def _discover(fetcher: _Fetcher) -> dict:
    """{(season, league, code): {"post": slug, "ballots": slug}} from the sitemaps."""
    found: dict = {}
    pat = re.compile(r"https://bbwaa\.com/((?:20)?(\d{2})-(al|nl)-(mvp|cy|roy|rookie|mgr|nmgr)(-ballots)?)/")
    for sm in ("post-sitemap.xml", "page-sitemap.xml"):
        text = fetcher.get(sm, sm, refresh=True) or ""
        for m in pat.finditer(text):
            slug, yy, lg, code, bal = m.groups()
            season = 2000 + int(yy)
            key = (season, lg, SLUG_CODE[code])
            found.setdefault(key, {})["ballots" if bal else "post"] = slug
    for key, slug in SLUG_OVERRIDES.items():
        found.setdefault(key, {})["post"] = slug
    return {k: v for k, v in found.items() if k[0] >= FIRST_SEASON}


# ---------------------------------------------------------------- parsing

class _Tables(HTMLParser):
    """Collect every <table> as a list of rows of cell texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.stack: list[list[list[str]]] = []
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append([])
        elif tag == "tr" and self.stack:
            self.stack[-1].append([])
        elif tag in ("td", "th") and self.stack:
            if not self.stack[-1]:
                self.stack[-1].append([])
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.stack:
            # U+0092 is a mis-decoded cp1252 apostrophe on some old pages
            text = "".join(self.cell).replace("\x92", "'")
            self.stack[-1][-1].append(" ".join(text.split()))
            self.cell = None
        elif tag == "table" and self.stack:
            self.tables.append([r for r in self.stack.pop() if r])

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def _tables(text: str):
    p = _Tables()
    p.feed(text)
    return p.tables


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9' -]", " ", s.replace(".", " ").replace("-", " "))
    return " ".join(s.split())


SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def _slug(name: str) -> str:
    # join initials: "A.J. Hinch" / "A. J. Hinch" -> "aj-hinch"
    name = re.sub(r"\b([A-Za-z])\.\s*(?=[A-Za-z]\.)", r"\1", name)
    return re.sub(r"[^a-z0-9]+", "-", _norm(name).replace("'", "")).strip("-")


def _surname(name: str) -> str:
    toks = [t for t in _norm(name).split() if t not in SUFFIXES]
    return toks[-1] if toks else ""


PLACE_RE = re.compile(r"^(\d+(st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|"
                      r"eighth|ninth|tenth)\b", re.I)


def _header_index(row):
    for i, c in enumerate(row):
        if re.match(r"^(1st|first)\b", c.strip(), re.I):
            return i
    return None


def _n_places(row, first):
    n = 0
    for c in row[first:]:
        if not PLACE_RE.match(c.strip()):
            break
        n += 1
    return n


def _parse_results(tables):
    """Results table rows: (name, team_nickname, [count per place], points)."""
    for t in tables:
        if not t:
            continue
        hi = next((i for i, r in enumerate(t[:3]) if _header_index(r) is not None), None)
        if hi is None:
            continue
        head = [c.lower() for c in t[hi]]
        if "points" not in head and "pts" not in head:
            continue
        first = _header_index(t[hi])
        if any(h in head for h in ("affiliation", "name")) and first >= 2:
            continue  # a ballot table
        pcol = head.index("points") if "points" in head else head.index("pts")
        if pcol - first != _n_places(t[hi], first):
            continue
        out = []
        for r in t[hi + 1:]:
            if len(r) <= pcol or not r[first - 1].strip():
                continue
            label = r[first - 1]
            if "," in label:
                name, team = (x.strip() for x in label.rsplit(",", 1))
            else:
                name, team = label.strip(), ""
            counts = [int(c) if c.strip().isdigit() else 0 for c in r[first:pcol]]
            pts = r[pcol].strip().replace(",", "")
            if not pts.isdigit():
                continue
            name = re.sub(r",\s*(Jr\.?|Sr\.?|II|III)$", r" \1", name)
            out.append((NAME_FIXES.get(name, name), team, counts, int(pts)))
        if out:
            return out
    return None


def _parse_ballots(tables):
    """Ballot table rows: (voter, outlet, chapter, [names by place])."""
    for t in tables:
        hi = next((i for i, r in enumerate(t[:3]) if _header_index(r) is not None), None)
        if hi is None:
            continue
        head = [c.lower() for c in t[hi]]
        first = _header_index(t[hi])
        if first < 2 or "points" in head:
            continue
        ncol = next((i for i, h in enumerate(head[:first]) if h.startswith("name") or h == "voter"), 0)
        acol = next((i for i, h in enumerate(head[:first]) if h.startswith("affil")), None)
        ccol = next((i for i, h in enumerate(head[:first]) if h.startswith("chap")), None)
        nplaces = _n_places(t[hi], first)
        out = []
        for r in t[hi + 1:]:
            if len(r) <= first or not r[ncol].strip():
                continue
            picks = [c.strip() for c in r[first:first + nplaces]]
            out.append((r[ncol].strip(),
                        r[acol].strip() if acol is not None and acol < len(r) else "",
                        r[ccol].strip() if ccol is not None and ccol < len(r) else "",
                        picks))
        if out:
            return out
    return None


def _team_abbr(nick: str, season: int) -> str:
    """'Yankees' / 'Houston Astros' / 'Tigers/Padres' -> 'NYY' / 'HOU' / 'DET/SD'."""
    out = []
    for part in (p.strip() for p in nick.split("/")):
        low = part.lower()
        key = next((k for k in sorted(TEAM_ABBR, key=len, reverse=True)
                    if low == k or low.endswith(" " + k)), None)
        abbr = TEAM_ABBR[key] if key else part
        if abbr == "ATH" and season <= 2024:
            abbr = "OAK"  # Oakland until the 2025 move
        out.append(abbr)
    return "/".join(out)


def _date(text: str, season: int) -> str:
    m = re.search(r'article:published_time" content="(\d{4})-(\d\d-\d\d)', text)
    if m and int(m.group(1)) == season:
        return f"{m.group(1)}-{m.group(2)}"
    months = {"October": 10, "November": 11, "December": 12}
    m = re.search(r"(October|November|December) (\d{1,2}), %d" % season, text)
    if m:
        return f"{season}-{months[m.group(1)]:02d}-{int(m.group(2)):02d}"
    return ""


class _Matcher:
    """Map a ballot cell (usually a surname) to a results-table candidate."""

    def __init__(self, results):
        self.cands = [r[0] for r in results]
        self.full = {_norm(n): n for n in self.cands}
        self.by_sur: dict[str, list[str]] = {}
        for n in self.cands:
            self.by_sur.setdefault(_surname(n), []).append(n)
            toks = [t for t in _norm(n).split() if t not in SUFFIXES]
            if len(toks) > 2:  # multi-word surnames: "De La Cruz", "Kiner-Falefa"
                for k in range(1, len(toks) - 1):
                    self.by_sur.setdefault(" ".join(toks[k:]), []).append(n)

    def match(self, cell: str) -> list[str]:
        self.how = "exact"
        c = _norm(re.sub(r"\(.*?\)|\*", "", cell))
        if not c:
            return []
        if c in self.full:
            return [self.full[c]]
        if c in self.by_sur:
            return self.by_sur[c]
        toks = [t for t in c.split() if t not in SUFFIXES]
        if toks and " ".join(toks) in self.by_sur:
            return self.by_sur[" ".join(toks)]
        # "J. Upton" / "Justin Upton" / first name + surname variants
        if len(toks) >= 2:
            sur = toks[-1]
            hits = [n for n in self.by_sur.get(sur, []) if _norm(n).startswith(toks[0][0])]
            if hits:
                return hits
            for k in range(1, len(toks)):
                hits = self.by_sur.get(" ".join(toks[k:]))
                if hits:
                    hits2 = [n for n in hits if _norm(n).startswith(toks[0][0])]
                    return hits2 or hits
        self.how = "fuzzy"
        # spacing differences ("La Roche" vs LaRoche)
        cs = c.replace(" ", "").replace("'", "")
        hits = [n for n in self.cands if _surname(n).replace("'", "") == cs
                or _norm(n).replace(" ", "").replace("'", "").endswith(cs)]
        if len(hits) == 1:
            return hits
        # initials ("PCA" = Pete Crow-Armstrong): only for all-caps cells
        raw = re.sub(r"[^A-Za-z]", "", cell)
        if raw.isupper() and 2 <= len(raw) <= 4:
            hits = [n for n in self.cands
                    if "".join(t[0] for t in _norm(n).split() if t not in SUFFIXES) == raw.lower()]
            if len(hits) == 1:
                return hits
        # misspellings ("Grienke", "Velander"): closest surname, unique and similar enough
        sur = toks[-1] if toks else c
        scored = sorted(((difflib.SequenceMatcher(None, sur, _surname(n)).ratio(), n)
                         for n in self.cands), reverse=True)
        if scored and scored[0][0] >= FUZZY_MIN and (len(scored) == 1 or scored[1][0] < scored[0][0]):
            return [scored[0][1]]
        return []


def _build_contest(season, lg, code, post_text, ballot_text, urls, log, issues):
    award, points = AWARDS[code]
    cid = f"mlb-{season}-{lg}-{AWARD_SLUG[code]}"
    results = _parse_results(_tables(post_text)) if post_text else None
    if not results and ballot_text:
        results = _parse_results(_tables(ballot_text))
    btab = None
    for t in (ballot_text, post_text):
        if t and btab is None:
            btab = _parse_ballots(_tables(t))
    if not btab:
        issues.append(f"{cid}: no ballot table found")
        return None, []
    if not results:
        issues.append(f"{cid}: no results table found — candidate names left as printed")
    nplaces = len(btab[0][3])
    if nplaces != len(points):
        issues.append(f"{cid}: note — ballot has {nplaces} places (usual {len(points)} for {award})")
    points = POINTS_BY_PLACES[nplaces]
    m = re.search(r"(\w+|\d+) points? for first", re.sub(r"<[^>]+>", " ", post_text or ballot_text))
    if m:
        first = NUM_WORDS.get(m.group(1).lower(), int(m.group(1)) if m.group(1).isdigit() else None)
        if first != points[0]:
            issues.append(f"{cid}: page says {m.group(1)} points for first, using {points[0]}")
    else:
        issues.append(f"{cid}: note — no scoring sentence found on page")
    matcher = _Matcher(results) if results else None
    team_of = {r[0]: _team_abbr(r[1], season) for r in results} if results else {}
    counts = {r[0]: r[2] for r in results} if results else {}

    # first pass: resolve unambiguous cells; collect ambiguous ones
    resolved = []  # per ballot: list of (rank, name or list-of-options, raw)
    for voter, outlet, chapter, picks in btab:
        row = []
        for i, cell in enumerate(picks[:nplaces]):
            if not cell.strip():
                continue
            opts = matcher.match(cell) if matcher else [cell.strip()]
            if opts and matcher.how == "fuzzy":
                issues.append(f"{cid}: note — '{cell}' ({voter}) read as {opts[0]}")
            if not opts:
                issues.append(f"{cid}: '{cell}' on {voter}'s ballot not in results list — kept as printed")
                opts = [cell.strip()]
            row.append([i + 1, opts, cell])
        resolved.append(row)
    # second pass: ambiguous surnames — use the published per-place counts
    if counts:
        used = {n: [0] * nplaces for n in counts}
        for row in resolved:
            for rank, opts, _ in row:
                if len(opts) == 1 and opts[0] in used:
                    used[opts[0]][rank - 1] += 1
        for row in resolved:
            for item in row:
                rank, opts, raw = item
                if len(opts) > 1:
                    room = [n for n in opts if counts[n][rank - 1:rank] and
                            used[n][rank - 1] < counts[n][rank - 1]]
                    if len(room) == 1:
                        item[1] = room
                        used[room[0]][rank - 1] += 1
                        issues.append(f"{cid}: ambiguous '{raw}' at #{rank} resolved to "
                                      f"{room[0]} from the published place counts")
                    else:
                        issues.append(f"{cid}: ambiguous '{raw}' at #{rank} (options {opts}) "
                                      f"— could not resolve, using {opts[0]}")
                        item[1] = [opts[0]]
    rows = []
    for (voter, outlet, chapter, _), row in zip(btab, resolved):
        aff = outlet
        if chapter:
            aff = f"{outlet} ({chapter})" if outlet else chapter
        for rank, opts, _ in row:
            name = opts[0]
            rows.append({"contest_id": cid, "voter": voter, "affiliation": aff, "rank": rank,
                         "candidate_id": _slug(name), "candidate": name,
                         "team": team_of.get(name, "")})
    published = ""
    if results:
        published = ";".join(f"{_slug(n)}:{p}:{c[0] if c else 0}" for n, _, c, p in results)
    contest = {
        "contest_id": cid, "source": "mlb", "sport": "baseball", "league": lg.upper(),
        "award": award, "season": str(season), "week": "", "date": _date(post_text or ballot_text, season),
        "title": f"{season} {lg.upper()} {award}", "n_places": nplaces,
        "points": ",".join(map(str, points)), "n_ballots": len(btab), "published": published,
        "url": " ".join(urls),
        "_counts": {_slug(n): c for n, _, c, _ in results} if results else {},
    }
    return contest, rows


def _validate(contest, rows, issues):
    if not contest["published"]:
        return None
    pts = [int(x) for x in contest["points"].split(",")]
    tot: dict[str, int] = {}
    fp: dict[str, int] = {}
    for r in rows:
        tot[r["candidate_id"]] = tot.get(r["candidate_id"], 0) + pts[r["rank"] - 1]
        if r["rank"] == 1:
            fp[r["candidate_id"]] = fp.get(r["candidate_id"], 0) + 1
    pub = {}
    for item in contest["published"].split(";"):
        cid, p, f = item.rsplit(":", 2)
        pub[cid] = (int(p), int(f))
    ok = True
    # where do the differences come from? compare per-place counts with the results table
    cnt: dict[str, list[int]] = {}
    for r in rows:
        cnt.setdefault(r["candidate_id"], [0] * len(pts))[r["rank"] - 1] += 1
    for cid, c in contest["_counts"].items():
        own = sum(a * b for a, b in zip(c, pts))
        if own != pub[cid][0]:
            issues.append(f"{contest['contest_id']}: SOURCE published points for {cid} ({pub[cid][0]}) "
                          f"disagree with its own published place counts ({own})")
        if cnt.get(cid, [0] * len(pts)) != (c + [0] * len(pts))[:len(pts)]:
            issues.append(f"{contest['contest_id']}: SOURCE place counts for {cid}: ballots "
                          f"{cnt.get(cid)} vs results table {c}")
    for cid in set(pub) | set(tot):
        a = (tot.get(cid, 0), fp.get(cid, 0))
        b = pub.get(cid, (0, 0))
        if a != b:
            ok = False
            issues.append(f"{contest['contest_id']}: MISMATCH {cid} recomputed {a[0]} pts/"
                          f"{a[1]} firsts vs published {b[0]}/{b[1]}")
    return ok


def _write_gz(path: Path, cols, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(buf.getvalue().encode("utf-8"))


def fetch(model_dir: Path, offline: bool = False, log=print) -> list[str]:
    model_dir = Path(model_dir)
    raw = model_dir / "data" / "raw" / "mlb"
    out = model_dir / "data" / "ballots"
    raw.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    fetcher = _Fetcher(raw, offline, log)
    found = _discover(fetcher)
    contests, ballots, issues = [], [], []
    n_ok = n_val = 0
    for (season, lg, code) in sorted(found):
        slugs = found[(season, lg, code)]
        post = fetcher.get(slugs["post"], slugs["post"] + ".html") if "post" in slugs else None
        bal = fetcher.get(slugs["ballots"], slugs["ballots"] + ".html") if "ballots" in slugs else None
        urls = [f"{BASE}/{s}/" for k, s in sorted(slugs.items()) if k in ("post", "ballots")]
        if post is None and bal is None:
            issues.append(f"{season} {lg} {code}: no page available")
            continue
        contest, rows = _build_contest(season, lg, code, post, bal, urls, log, issues)
        if contest is None:
            continue
        ok = _validate(contest, rows, issues)
        if ok is not None:
            n_val += 1
            n_ok += ok
        contests.append(contest)
        ballots.extend(rows)
    for (s, lg) in sorted({(k[0], k[1]) for k in found}):
        for code in AWARDS:
            if (s, lg, code) not in found:
                issues.append(f"{s} {lg} {code}: no page found in sitemap")
    issues.extend(f"blocked/failed: {b}" for b in fetcher.blocked)
    bpath, cpath = out / "mlb.csv.gz", out / "mlb_contests.csv.gz"
    for c in contests:
        c.pop("_counts", None)
    # one display name per candidate_id: prefer the accented form, then the latest spelling
    names: dict[str, str] = {}
    for r in ballots:
        cur = names.get(r["candidate_id"])
        if cur is None or (r["candidate"] != cur and (r["candidate"].isascii() <= cur.isascii())):
            names[r["candidate_id"]] = r["candidate"]
    for r in ballots:
        r["candidate"] = names[r["candidate_id"]]
    _write_gz(bpath, BALLOT_COLS, ballots)
    _write_gz(cpath, CONTEST_COLS, contests)
    for i in issues:
        log("  " + i)
    log(f"mlb: {len(contests)} contests, "
        f"{sum(int(c['n_ballots']) for c in contests)} ballots, {len(ballots)} rows; "
        f"validated {n_ok}/{n_val} contests with published totals")
    return [str(bpath), str(cpath)]
