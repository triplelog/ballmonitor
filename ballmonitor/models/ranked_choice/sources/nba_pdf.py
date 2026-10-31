"""Parse the NBA award PDFs (voter selections and vote totals) saved in data/raw/nba/pdf/.

Text comes from pypdf's layout mode (after moving any page rotation into the content), which
keeps table columns apart by 2+ spaces. Rows are classified by shape, not by headers (the
headers change every year):

* voter row:  voter | affiliation | n person cells   (a trailing stray number is ignored;
  "Abstained" = an abstention; a voter name split by a double space is re-joined)
* totals row: person | n place counts | total points

Person cells come as `Curry, Stephen -- GS`, `Westbrook, Russell (OKC.)`, `Jokic, Nikola (DEN)`,
`Embiid Joel (PHI)` (2022-23, no comma), `Nurse, Nick (Toronto Raptors)` (coaches) and, in
totals tables, `Joel Embiid, Philadelphia`. People are matched across files by `key()` — the
sorted letters of the name, so word order, accents and stray spaces don't matter.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

logging.getLogger("pypdf").setLevel(logging.ERROR)

CELL_SPLIT = re.compile(r"\s{2,}")
INT = re.compile(r"^\d+$")


def ascii_fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def key(first: str, last: str) -> str:
    return "".join(sorted(re.sub(r"[^a-z]", "", ascii_fold(first + last).lower())))


# the same person spelled differently across seasons
ALIASES = {"michael-malone": "mike-malone", "jose-juan-barea": "jj-barea"}


def slug(name: str) -> str:
    s = re.sub(r"[.'’]", "", ascii_fold(name).lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return ALIASES.get(s, s)


def text_pages(path: Path) -> list[str]:
    import pypdf  # optional dependency (`pip install -e '.[data]'`)

    reader = pypdf.PdfReader(str(path))
    out = []
    for page in reader.pages:
        try:
            if page.get("/Rotate"):
                page.transfer_rotation_to_content()
            out.append(page.extract_text(extraction_mode="layout") or "")
        except Exception:  # noqa: BLE001 - odd pages: plain extraction
            out.append(page.extract_text() or "")
    return out


def person(cell: str, totals: bool = False) -> tuple[str, str, str] | None:
    """Cell -> (first, last, team) or None."""
    cell = re.sub(r"\s+", " ", cell.replace("’", "'").replace("*", "").replace("‐", "-")).strip()
    team = ""
    m = re.match(r"^(.*?)\s*--\s*(.+)$", cell)
    if m:
        cell, team = m.group(1), m.group(2)
    else:
        m = re.match(r"^(.*?)\s*\(([^)]*)\)?\.?$", cell)
        if m:
            cell, team = m.group(1), m.group(2)
    team = re.sub(r"[.\s]", "", team) if len(team) <= 6 else team.strip()
    cell = cell.strip().rstrip(",")
    if not re.search(r"[A-Za-z]", cell) or re.search(r"\d", cell):
        return None
    if "," in cell:
        a, b = (x.strip() for x in cell.split(",", 1))
        if totals and not team:            # "Joel Embiid, Philadelphia"
            parts = a.split()
            if len(parts) < 2:
                return None
            return " ".join(parts[:-1]), parts[-1], b
        return b, a, team                  # "Last, First"
    parts = cell.split()
    if not team or len(parts) < 2:
        return None
    if totals:                                   # "Ja Morant (Memphis)"
        return " ".join(parts[:-1]), parts[-1], team
    return " ".join(parts[1:]), parts[0], team   # "Embiid Joel (PHI)" (2022-23 ballots)


def parse_pdf(path: Path, n: int) -> dict:
    """Ballots and totals from one PDF with n places per ballot.

    {'ballots': [(voter, affiliation, picks or None)], 'totals': [(first, last, team, points,
    first_place_votes)], 'problems': [str]}; picks = [(first, last, team)] best first, None =
    abstained."""
    ballots, totals, problems = [], [], []
    for text in text_pages(path):
        for ln in text.splitlines():
            cells = [c for c in CELL_SPLIT.split(ln.strip()) if c]
            if len(cells) < 2:
                continue
            # totals row: person + n counts + total
            if len(cells) >= n + 2 and all(INT.match(c) for c in cells[-(n + 1):]):
                p = person(" ".join(cells[: len(cells) - n - 1]), totals=True)
                if p:
                    nums = [int(c) for c in cells[-(n + 1):]]
                    totals.append((*p, nums[-1], nums[0]))
                continue
            while cells and INT.match(cells[-1]):   # stray trailing number
                cells = cells[:-1]
            if len(cells) >= 3 and cells[-1].lower().startswith("abstain"):
                ballots.append((cells[0], " ".join(cells[1:-1]), None))
                continue
            if len(cells) < 2 + 1:
                continue
            picks = [person(c) for c in cells[-n:]] if len(cells) >= n + 1 else []
            if picks and all(picks):
                head = cells[:-n]
                if len(head) == 3:                  # "Marc  Berman" split by a double space
                    head = [head[0] + " " + head[1], head[2]]
                if len(head) == 1 and "fan" in head[0].lower():   # the fan vote counted as one ballot
                    head = [head[0], "Fans"]
                if len(head) == 2:
                    ballots.append((head[0], head[1], picks))
                    continue
            if sum(1 for c in cells if person(c)) >= 2 and not re.search(r"\d{4}-\d{2} –|kiamedia", ln):
                problems.append(f"{path.name}: unparsed row: {ln.strip()[:140]}")
    return {"ballots": ballots, "totals": totals, "problems": problems}
