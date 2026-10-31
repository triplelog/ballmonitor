"""PHWA individual NHL award ballots (Hart, Norris, Calder, Selke, Lady Byng).

Since 2018 the Professional Hockey Writers' Association publishes every voter's ballot.
Each season's thephwa.com post links one Google Drive file per award. Drive's robots.txt
allows only the `/file/...` viewer pages, which hold the file *name* but not its content
(direct download `/uc`, `drive.usercontent.google.com` and the viewer's image endpoints
are disallowed), so this module

1. fetches the PHWA posts (cached) and resolves each award's Drive link
   (bit.ly redirects followed by one HEAD request; `/open?id=` rewritten to `/file/d/`),
2. fetches the allowed Drive `/file/d/<id>/view` page once to record the file name/type,
3. parses manually downloaded copies placed in `data/raw/nhl/manual/` as
   `<season>_<award>.<ext>` (e.g. `2024-25_hart.pdf`; ext pdf | csv | xlsx | txt) or
   `<drive id>.<ext>`, and
4. rebuilds `data/ballots/nhl.csv.gz` + `nhl_contests.csv.gz` from the cache only.

See sources/nhl.md for the expected file names, links and the parsing rules.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from html import unescape
from pathlib import Path
from xml.etree import ElementTree

SOURCE = "nhl"
UA = "ballmonitor-ranked-choice/0.1 (personal, non-commercial research)"
DELAY = 1.5
SITEMAP = "https://www.thephwa.com/wp-sitemap-posts-post-1.xml"

# Known ballot posts (season -> URL). The sitemap is also scanned for newer ones.
POSTS = {
    "2017-18": "https://www.thephwa.com/2018/06/21/nhl-awards-ballots-from-phwa-members/",
    "2018-19": "https://www.thephwa.com/2019/06/20/2019-nhl-awards-ballots-from-phwa-members/",
    "2019-20": "https://www.thephwa.com/2020/09/22/2019-nhl-awards-ballots-from-phwa-members-2/",
    "2020-21": "https://www.thephwa.com/2021/06/30/phwa-reveals-2021-nhl-awards-ballots/",
    "2021-22": "https://www.thephwa.com/2022/06/22/phwa-publishes-2022-nhl-awards-ballots/",
    "2022-23": "https://www.thephwa.com/2023/06/27/phwa-reveals-2023-nhl-awards-ballots/",
    "2023-24": "https://www.thephwa.com/2024/06/29/phwa-reveals-2024-nhl-awards-ballots/",
    "2024-25": "https://www.thephwa.com/2025/06/02/phwa-reveals-2025-nhl-awards-ballots/",
    "2025-26": "https://www.thephwa.com/2026/06/12/phwa-reveals-2025-26-nhl-awards-ballots/",
}

# award key -> (display name, regex on the link text / bit.ly slug, n_places, points)
AWARDS = {
    "hart": ("Hart Trophy", r"\bhart\b", 5, (10, 7, 5, 3, 1)),
    "norris": ("Norris Trophy", r"\bnorris\b", 5, (10, 7, 5, 3, 1)),
    "calder": ("Calder Trophy", r"\bcalder\b", 5, (10, 7, 5, 3, 1)),
    "selke": ("Selke Trophy", r"\bselke\b", 5, (10, 7, 5, 3, 1)),
    "lady_byng": ("Lady Byng Trophy", r"\bbyng\b", 5, (10, 7, 5, 3, 1)),
}
# Linked in the posts but out of scope (not one ranked league-wide list).
SKIPPED = {
    "masterton": r"\bmasterton\b|\bphwa mast\b",
    "all_star": r"all-star|\bphwa as(c|lw|rw|d|g)\b",
    "all_rookie": r"all-rookie|\bphwa rook",
}
EXTS = ("csv", "xlsx", "pdf", "txt")

ORDINALS = {
    "1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3,
    "4th": 4, "fourth": 4, "5th": 5, "fifth": 5,
}
TEAMS = {
    "ANA", "ARI", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ", "DAL", "DET", "EDM",
    "FLA", "LAK", "LA", "MIN", "MTL", "NSH", "NJD", "NJ", "NYI", "NYR", "OTT", "PHI",
    "PIT", "SJS", "SJ", "SEA", "STL", "TBL", "TB", "TOR", "UTA", "UTAH", "VAN", "VGK",
    "VEG", "WSH", "WPG", "PHX", "ATL",
}

BALLOT_COLS = ["contest_id", "voter", "affiliation", "rank", "candidate_id", "candidate", "team"]
CONTEST_COLS = ["contest_id", "source", "sport", "league", "award", "season", "week", "date",
                "title", "n_places", "points", "n_ballots", "published", "url"]


# --------------------------------------------------------------------------- network

class _Net:
    def __init__(self, log):
        self.last = 0.0
        self.log = log

    def _wait(self):
        dt = time.time() - self.last
        if dt < DELAY:
            time.sleep(DELAY - dt)
        self.last = time.time()

    def get(self, url: str) -> str:
        self._wait()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")

    def redirect_target(self, url: str) -> str:
        """One HEAD request without following the redirect (bit.ly allows all robots)."""
        self._wait()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
        try:
            with opener.open(req, timeout=60) as r:
                return r.headers.get("Location", "") or ""
        except urllib.error.HTTPError as e:
            return e.headers.get("Location", "") or ""


# --------------------------------------------------------------------------- helpers

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9' -]", " ", s.replace(".", " ").replace("-", " "))
    return " ".join(s.split())


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(name).replace("'", "")).strip("-")


def _clean(s) -> str:
    return " ".join(str(s if s is not None else "").replace("\xa0", " ").split())


def _drive_id(href: str) -> str:
    m = re.search(r"/file/d/([A-Za-z0-9_-]{10,})", href) or \
        re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", href)
    return m.group(1) if m else ""


def _drive_view(fid: str) -> str:
    return f"https://drive.google.com/file/d/{fid}/view"


def _post_date(url: str) -> str:
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    return "-".join(m.groups()) if m else ""


def _season_from_post(url: str) -> str:
    m = re.search(r"(\d{4})-(\d{2})-nhl-awards", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    y = int(re.search(r"/(\d{4})/", url).group(1))
    return f"{y - 1}-{str(y)[2:]}"


def _post_links(html: str) -> tuple[list[tuple[str, str]], str]:
    i = html.find("entry-content")
    body = html[i:html.find("</article", i)] if i >= 0 else html
    out = []
    for m in re.finditer(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        href = unescape(m.group(1))
        text = _clean(unescape(re.sub(r"<[^>]+>", " ", m.group(2))))
        if "drive.google" in href or "bit.ly" in href:
            out.append((href, text))
    return out, body


def _reveal_date(body_text: str, label_pat: str, season: str, fallback: str) -> str:
    months = {m: i + 1 for i, m in enumerate(
        "january february march april may june july august september october november december".split())}
    m = re.search(label_pat + r"[^–—\-]*[–—\-]\s*revealed\s+([A-Za-z]+)\s+(\d{1,2})",
                  body_text, re.I)
    if m and m.group(1).lower() in months:
        year = int(season[:4]) + 1
        return f"{year}-{months[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    return fallback


# --------------------------------------------------------------------------- crawl

def _crawl(raw: Path, offline: bool, log) -> dict:
    """Return {season: {"url", "date", "awards": {key: {...}}, "skipped": [...]}}."""
    net = _Net(log)
    posts_dir = raw / "posts"
    drive_dir = raw / "drive"
    posts_dir.mkdir(parents=True, exist_ok=True)
    drive_dir.mkdir(parents=True, exist_ok=True)
    links_path = raw / "links.json"
    links = json.loads(links_path.read_text()) if links_path.exists() else {}

    posts = dict(POSTS)
    if not offline:
        try:
            sm = net.get(SITEMAP)
            (raw / "sitemap.xml").write_text(sm, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log(f"nhl: sitemap unavailable ({e})")
            sm = ""
    else:
        p = raw / "sitemap.xml"
        sm = p.read_text(encoding="utf-8") if p.exists() else ""
    for loc in re.findall(r"<loc>([^<]+)</loc>", sm):
        if re.search(r"nhl-awards-ballots", loc) and "conn-smythe" not in loc:
            season = _season_from_post(loc)
            posts.setdefault(season, loc)

    out = {}
    for season, url in sorted(posts.items()):
        path = posts_dir / f"{season}.html"
        html = path.read_text(encoding="utf-8") if path.exists() else None
        need = html is None or (not offline and "revealed" in html and _incomplete(html))
        if need and not offline:
            try:
                html = net.get(url)
                path.write_text(html, encoding="utf-8")
                log(f"nhl: fetched post {season}")
            except Exception as e:  # noqa: BLE001
                log(f"nhl: could not fetch {url} ({e})")
        if html is None:
            log(f"nhl: no cached post for {season} (run online)")
            continue
        found, body = _post_links(html)
        body_text = _clean(unescape(re.sub(r"<[^>]+>", " ", body)))
        info = {"url": url, "date": _post_date(url), "awards": {}, "skipped": []}
        for href, text in found:
            key_text = re.sub(r"[_\d/.?=]", " ", f"{text} {href}".lower())
            skip = next((k for k, pat in SKIPPED.items() if re.search(pat, key_text)), None)
            if skip:
                info["skipped"].append(skip)
                continue
            key = next((k for k, a in AWARDS.items() if re.search(a[1], key_text)), None)
            if key is None or key in info["awards"]:
                continue
            fid = _drive_id(href)
            if not fid and "bit.ly" in href:
                fid = links.get(href, "")
                if not fid and not offline:
                    try:
                        fid = _drive_id(net.redirect_target(href))
                        if fid:
                            links[href] = fid
                    except Exception as e:  # noqa: BLE001
                        log(f"nhl: could not resolve {href} ({e})")
            meta = {"drive_id": fid, "link": href, "file_name": "", "mime": ""}
            if fid:
                vp = drive_dir / f"{fid}.html"
                if not vp.exists() and not offline:
                    try:
                        vp.write_text(net.get(_drive_view(fid)), encoding="utf-8")
                    except Exception as e:  # noqa: BLE001
                        log(f"nhl: drive view page {fid} unavailable ({e})")
                if vp.exists():
                    page = vp.read_text(encoding="utf-8")
                    t = re.search(r"<title>(.*?)</title>", page, re.S)
                    if t:
                        meta["file_name"] = unescape(t.group(1)).replace(" - Google Drive", "").strip()
                    mm = re.search(r'"(application/[a-z.+-]+|text/csv)"', page)
                    meta["mime"] = mm.group(1) if mm else ""
            meta["date"] = _reveal_date(body_text, re.escape(text.split(" Trophy")[0]) if text else key,
                                        season, info["date"])
            info["awards"][key] = meta
        info["skipped"] = sorted(set(info["skipped"]))
        out[season] = info
    links_path.write_text(json.dumps(links, indent=1, sort_keys=True))
    return out


def _incomplete(html: str) -> bool:
    found, _ = _post_links(html)
    return len(found) < 6  # awards still being revealed one by one


# --------------------------------------------------------------------------- parsing

def _xlsx_rows(path: Path) -> list[list[str]]:
    """Minimal stdlib .xlsx reader: first worksheet, shared + inline strings."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n))
        rows = []
        for sheet in sheets[:1]:
            root = ElementTree.fromstring(z.read(sheet))
            for row in root.iter(f"{{{ns['m']}}}row"):
                cells = {}
                for c in row.findall("m:c", ns):
                    ref = re.match(r"([A-Z]+)", c.get("r", "A")).group(1)
                    col = 0
                    for ch in ref:
                        col = col * 26 + ord(ch) - 64
                    v = c.find("m:v", ns)
                    if c.get("t") == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif c.get("t") == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
                    else:
                        val = v.text if v is not None else ""
                    cells[col - 1] = val or ""
                if cells:
                    rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        return rows


def _split_layout(line: str) -> list[tuple[int, str]]:
    """Cells of a layout-preserved text line: runs separated by 2+ spaces, with offsets."""
    return [(m.start(), m.group(0).strip()) for m in re.finditer(r"\S+(?: \S+)*", line)]


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("parsing PDF ballots needs pypdf: pip install -e '.[data]'") from e
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text(extraction_mode="layout"))
        except TypeError:  # old pypdf
            pages.append(page.extract_text())
    return "\f".join(pages)


def _header_kind(cells: list[str]) -> dict | None:
    """Recognise a header row; return column roles by index."""
    low = [_norm(c) for c in cells]
    places = {}
    for i, c in enumerate(low):
        c2 = re.sub(r"\b(place|choice|vote|pick|selection)s?\b", "", c).strip()
        c2 = re.sub(r"^(\d)$", lambda m: {"1": "1st", "2": "2nd", "3": "3rd", "4": "4th",
                                          "5": "5th"}[m.group(1)] if m.group(1) in "12345" else c2, c2)
        if c2 in ORDINALS:
            places.setdefault(ORDINALS[c2], i)
    if len(places) < 3:
        return None
    roles = {"places": places, "voter": [], "affiliation": None, "points": None,
             "player": None, "team": None, "teams_after": {}}
    first_place_col = min(places.values())
    for i, c in enumerate(low):
        if i in places.values():
            continue
        if re.search(r"\b(points|pts|total)\b", c):
            roles["points"] = i
        elif re.search(r"\b(player|candidate|name of player)\b", c):
            roles["player"] = i
        elif re.search(r"\b(outlet|affiliation|media|publication|organization|company|chapter|employer|network|market|city)\b", c):
            roles["affiliation"] = i
        elif re.search(r"\bteam\b", c):
            prev = [p for p, j in places.items() if j < i]
            if prev and i > first_place_col:
                roles["teams_after"][max(prev, key=lambda p: places[p])] = i
            else:
                roles["team"] = i
        elif i < first_place_col and re.search(r"\b(voter|name|first|last|writer|member)\b", c):
            roles["voter"].append(i)
    if roles["points"] is not None or roles["player"] is not None:
        roles["kind"] = "summary"
    else:
        roles["kind"] = "ballot"
        if not roles["voter"]:
            pre = [i for i in range(first_place_col) if i != roles["affiliation"]]
            roles["voter"] = pre[:1]
            if roles["affiliation"] is None and len(pre) > 1:
                roles["affiliation"] = pre[1]
    return roles


def _player(cell: str, team_cell: str = "") -> tuple[str, str]:
    s = _clean(cell)
    team = _clean(team_cell).upper()
    m = re.match(r"^(.*?)\s*[\(\[]\s*([A-Za-z. ]{2,5})\s*[\)\]]$", s) or \
        re.match(r"^(.*?)\s*[,\-–]\s*([A-Za-z.]{2,4})$", s)
    if m and m.group(2).replace(".", "").replace(" ", "").upper() in TEAMS:
        s, team = m.group(1).strip(), m.group(2).replace(".", "").replace(" ", "").upper()
    m = re.match(r"^([A-Za-z'’\- .]+),\s*([A-Za-z'’\- .]+)$", s)  # "Last, First"
    if m:
        s = f"{m.group(2).strip()} {m.group(1).strip()}"
    return s, team


def _rows_to_tables(rows: list[list[str]]) -> tuple[list[dict], list[dict]]:
    """Header-driven extraction from a grid of cells. Returns (ballots, summary)."""
    ballots, summary = [], []
    roles = None
    for cells in rows:
        cells = [_clean(c) for c in cells]
        if not any(cells):
            continue
        h = _header_kind(cells)
        if h:
            roles = h
            continue
        if roles is None:
            continue
        get = lambda i: cells[i] if i is not None and i < len(cells) else ""  # noqa: E731
        if roles["kind"] == "summary":
            name = get(roles["player"]) if roles["player"] is not None else ""
            pts = re.sub(r"[^\d]", "", get(roles["points"]))
            if name and pts:
                nm, tm = _player(name, get(roles["team"]))
                summary.append({"candidate": nm, "team": tm, "points": int(pts),
                                "first": re.sub(r"[^\d]", "", get(roles["places"].get(1))) or "0"})
            continue
        picks = {}
        for rank, i in roles["places"].items():
            if get(i):
                picks[rank] = _player(get(i), get(roles["teams_after"].get(rank, roles["team"])))
        voter = " ".join(get(i) for i in roles["voter"]).strip()
        if voter and picks and not re.search(r"\b(total|points)\b", voter, re.I):
            ballots.append({"voter": voter, "affiliation": get(roles["affiliation"]),
                            "picks": picks})
    return ballots, summary


def _layout_rows(text: str) -> list[list[str]]:
    """Turn layout text into cell rows aligned on the most recent header's columns."""
    rows, starts = [], None
    for line in text.splitlines():
        cells = _split_layout(line)
        if not cells:
            continue
        if _header_kind([c for _, c in cells]):
            starts = [p for p, _ in cells]
            rows.append([c for _, c in cells])
            continue
        if starts is None:
            continue
        if len(cells) == len(starts):  # one cell per column: map in order
            rows.append([c for _, c in cells])
            continue
        row = [""] * len(starts)
        for pos, c in cells:
            # otherwise: the header column whose start is nearest to the cell's start
            j = min(range(len(starts)), key=lambda k: abs(starts[k] - pos))
            row[j] = f"{row[j]} {c}".strip()
        rows.append(row)
    return rows


PICK_CELL = re.compile(r"^[^,\d][^,]*,\s*\S.*$")   # "Nathan MacKinnon, Colorado Avalanche"


def parse_phwa_pdf(path: Path, n_places: int = 5) -> tuple[list[dict], list[str]]:
    """The PHWA's own table (every season 2017-18 on): No. | voter last | voter first |
    affiliation | n_places cells 'Player Name, Team'. Returns (ballots, problems)."""
    from ballmonitor.models.ranked_choice.sources import nba_pdf  # shared pypdf layout reader

    ballots, problems, seen = [], [], set()
    for text in nba_pdf.text_pages(path):
        for ln in text.splitlines():
            cells = [c.strip() for c in re.split(r"\s{2,}", ln.strip()) if c.strip()]
            if not cells or not cells[0].isdigit():
                continue
            no, rest = int(cells[0]), []
            for c in cells[1:]:   # "Jesper Wallstedt," + "Minnesota Wild" split over two cells
                if rest and rest[-1].endswith(","):
                    rest[-1] = f"{rest[-1]} {c}"
                else:
                    rest.append(c)
            # "Evgeni Malkin. Pittsburgh Penguins": a period typed for the comma
            # (only after the first pick: affiliations like "St. Louis Post-Dispatch" keep theirs)
            first = next((i for i, c in enumerate(rest) if PICK_CELL.match(c)), len(rest))
            if len(rest) >= 3 + n_places:   # full row: the last n_places cells are the picks
                first = min(first, len(rest) - n_places)
            rest = rest[:first] + [c if "," in c or ". " not in c else ", ".join(c.rsplit(". ", 1))
                                   for c in rest[first:]]
            picks_at = [i for i, c in enumerate(rest) if PICK_CELL.match(c)]
            if not picks_at:
                continue
            head, raw_picks = rest[: picks_at[0]], rest[picks_at[0]:]
            picks = []
            for c in raw_picks:
                if PICK_CELL.match(c) or len(raw_picks) <= n_places:
                    picks.append(c)          # (a pick missing its comma is resolved below)
                elif picks:                  # "Riley Sheahan, Edmonton" + "Oilers"
                    picks[-1] = f"{picks[-1]} {c}"
            if len(head) < 2 or len(picks) > n_places:
                problems.append(f"{path.name}: row {no}: {ln.strip()[:150]}")
                continue
            voter = f"{head[1]} {head[0]}"
            affiliation = " ".join(head[2:])
            if (no, voter) in seen:
                continue
            seen.add((no, voter))
            ballots.append({"voter": voter, "affiliation": affiliation,
                            "picks": {r: (tuple(x.strip() for x in c.split(",", 1)) if "," in c else (c, None))
                                      for r, c in enumerate(picks, 1)}})
    # "Artemi Panarin Columbus Blue Jackets": split at the longest player name seen elsewhere
    known = {p[0] for b in ballots for p in b["picks"].values() if p[1] is not None}
    teams = {p[1] for b in ballots for p in b["picks"].values() if p[1]}
    for b in ballots:
        for r, (cell, team) in list(b["picks"].items()):
            if team is None:
                name = max((k for k in known if cell.startswith(k + " ")), key=len, default=None)
                team_sfx = max((t for t in teams if cell.endswith(" " + t)), key=len, default=None)
                if name:
                    b["picks"][r] = (name, cell[len(name):].strip())
                elif team_sfx:
                    b["picks"][r] = (cell[: -len(team_sfx)].strip(), team_sfx)
                else:
                    problems.append(f"{path.name}: {b['voter']}: can't split '{cell}'")
                    b["picks"][r] = (cell, "")
    return ballots, problems


def parse_file(path: Path) -> tuple[list[dict], list[dict]]:
    ext = path.suffix.lower().lstrip(".")
    if ext == "pdf":
        ballots, _ = parse_phwa_pdf(path)
        if ballots:
            return ballots, []
    if ext == "csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
    elif ext == "xlsx":
        rows = _xlsx_rows(path)
    elif ext == "pdf":
        rows = _layout_rows(_pdf_text(path))
    else:  # txt: layout text (e.g. copied from a PDF viewer) or tab-separated
        text = path.read_text(encoding="utf-8")
        rows = [l.split("\t") for l in text.splitlines()] if "\t" in text else _layout_rows(text)
    return _rows_to_tables(rows)


# --------------------------------------------------------------------------- build

def _find_manual(manual: Path, season: str, key: str, fid: str) -> Path | None:
    for stem in (f"{season}_{key}", fid):
        if not stem:
            continue
        for ext in EXTS:
            p = manual / f"{stem}.{ext}"
            if p.exists():
                return p
    return None


# the same player spelled differently on some ballots
ALIASES = {"sebastain-aho": "sebastian-aho", "mitchell-marner": "mitch-marner",
           "christopher-tanev": "chris-tanev"}


def _canonical_names(rows: list[dict]) -> None:
    """One id and one display name per player across all contests (most common spelling,
    accented form preferred)."""
    from collections import Counter

    counts: dict[str, Counter] = {}
    for r in rows:
        r["candidate_id"] = ALIASES.get(r["candidate_id"], r["candidate_id"])
        counts.setdefault(r["candidate_id"], Counter())[r["candidate"].replace("’", "'")] += 1
    best = {}
    for cid, c in counts.items():
        accented = [n for n in c if n != unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()]
        best[cid] = max(accented, key=c.get) if accented else max(c, key=c.get)
    for r in rows:
        r["candidate"] = best[r["candidate_id"]]


def _write_gz(path: Path, cols: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def fetch(model_dir: Path, offline: bool = False, log=print) -> list[str]:
    model_dir = Path(model_dir)
    raw = model_dir / "data" / "raw" / SOURCE
    manual = raw / "manual"
    manual.mkdir(parents=True, exist_ok=True)
    seasons = _crawl(raw, offline, log)

    ballots_out, contests_out, missing = [], [], []
    for season, info in sorted(seasons.items()):
        for key, (name, _pat, n_places, pts) in AWARDS.items():
            meta = info["awards"].get(key)
            if not meta:
                log(f"nhl: {season} {key}: no link in the post")
                continue
            path = _find_manual(manual, season, key, meta["drive_id"])
            if path is None:
                missing.append((season, key, meta))
                continue
            try:
                ballots, summary = parse_file(path)
            except Exception as e:  # noqa: BLE001
                log(f"nhl: {season} {key}: could not parse {path.name} ({e})")
                continue
            cid = f"nhl-{season}-{key.replace('_', '-')}"
            totals, firsts, names, teams = {}, {}, {}, {}
            n_ok = 0
            for b in ballots:
                if len(b["picks"]) != n_places:
                    log(f"nhl: {cid}: ballot of {b['voter']!r} has {len(b['picks'])} places")
                for rank, (cand, team) in sorted(b["picks"].items()):
                    cidd = _slug(cand)
                    ballots_out.append({"contest_id": cid, "voter": b["voter"],
                                        "affiliation": b["affiliation"], "rank": rank,
                                        "candidate_id": cidd, "candidate": cand, "team": team})
                    totals[cidd] = totals.get(cidd, 0) + (pts[rank - 1] if rank <= len(pts) else 0)
                    firsts[cidd] = firsts.get(cidd, 0) + (rank == 1)
                    names[cidd] = cand
                n_ok += 1
            published = ""
            if summary:
                published = ";".join(f"{_slug(s['candidate'])}:{s['points']}:{s['first']}"
                                     for s in summary)
                bad = [(s["candidate"], s["points"], totals.get(_slug(s["candidate"]), 0))
                       for s in summary if totals.get(_slug(s["candidate"]), 0) != s["points"]]
                if bad:
                    log(f"nhl: {cid}: MISMATCH recomputed vs published points: {bad[:8]}")
                else:
                    log(f"nhl: {cid}: recomputed points match published totals "
                        f"({len(summary)} players)")
            top = sorted(totals.items(), key=lambda kv: -kv[1])[:3]
            log(f"nhl: {cid}: {n_ok} ballots from {path.name}; top: "
                + ", ".join(f"{names[c]} {p}" for c, p in top))
            contests_out.append({
                "contest_id": cid, "source": SOURCE, "sport": "hockey", "league": "NHL",
                "award": name, "season": season, "week": "", "date": meta.get("date", info["date"]),
                "title": f"{season} {name}", "n_places": n_places,
                "points": ",".join(map(str, pts)), "n_ballots": n_ok, "published": published,
                "url": _drive_view(meta["drive_id"]) if meta["drive_id"] else info["url"],
            })

    with (raw / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["season", "award", "expected_file", "drive_url", "drive_file_name", "have"])
        for season, info in sorted(seasons.items()):
            for key, meta in info["awards"].items():
                have = _find_manual(manual, season, key, meta["drive_id"])
                w.writerow([season, key, f"manual/{season}_{key}.pdf",
                            _drive_view(meta["drive_id"]) if meta["drive_id"] else meta["link"],
                            meta["file_name"], have.name if have else ""])
    if missing:
        log(f"nhl: {len(missing)} award files need a manual download (Drive robots.txt allows "
            f"only the /file viewer page). Open each link in a browser, download, and save as:")
        for season, key, meta in missing:
            fname = meta["file_name"] or "?"
            log(f"  {manual / f'{season}_{key}'}.<pdf|csv|xlsx>   <- "
                f"{_drive_view(meta['drive_id']) if meta['drive_id'] else meta['link']}  [{fname}]")
    skipped = sorted({s for i in seasons.values() for s in i["skipped"]})
    if skipped:
        log(f"nhl: out of scope, not parsed: {', '.join(skipped)} (also Conn Smythe posts)")

    bpath = model_dir / "data" / "ballots" / f"{SOURCE}.csv.gz"
    cpath = model_dir / "data" / "ballots" / f"{SOURCE}_contests.csv.gz"
    _canonical_names(ballots_out)
    _write_gz(bpath, BALLOT_COLS, ballots_out)
    _write_gz(cpath, CONTEST_COLS, contests_out)
    log(f"nhl: wrote {len(contests_out)} contests, {sum(c['n_ballots'] for c in contests_out)} "
        f"ballots, {len(ballots_out)} rows")
    return [str(bpath), str(cpath)]
