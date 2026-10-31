"""Read ballots and contests from data/ballots/<source>.csv.gz (format: sources/CONTRACT.md)."""

from __future__ import annotations

import csv
import gzip
from collections import OrderedDict
from pathlib import Path
from typing import Any

# contest_id prefix -> source file stem
PREFIXES = [("ap-cfb-", "ap_cfb"), ("ap-mbb-", "ap_mbb"), ("ap-wbb-", "ap_wbb"),
            ("mlb-", "mlb"), ("nba-", "nba"), ("nhl-", "nhl")]
SOURCES = [s for _, s in PREFIXES]
WEEK_ORDER = {"pre": -1, "final": 999}

_cache: "OrderedDict[tuple, Any]" = OrderedDict()


def source_of(contest_id: str) -> str:
    for prefix, source in PREFIXES:
        if contest_id.startswith(prefix):
            return source
    raise ValueError(f"unknown contest id '{contest_id}' (expected a prefix like "
                     + ", ".join(p for p, _ in PREFIXES) + ")")


def _open(path: Path):
    return gzip.open(path, "rt", encoding="utf-8", newline="")


def _cached(key, loader):
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    value = loader()
    _cache[key] = value
    while len(_cache) > 64:
        _cache.popitem(last=False)
    return value


def contests(data_dir: Path, source: str) -> list[dict[str, str]]:
    path = data_dir / f"{source}_contests.csv.gz"
    if not path.exists():
        return []
    key = ("contests", str(path), path.stat().st_mtime)
    return _cached(key, lambda: list(csv.DictReader(_open(path))))


def all_contests(data_dir: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for s in SOURCES:
        out += contests(data_dir, s)
    return out


def week_key(row: dict[str, str]) -> tuple:
    w = row.get("week", "")
    wk = WEEK_ORDER.get(w, int(w) if w.isdigit() else 0)
    return (row.get("season", ""), wk, row.get("date", ""))


def resolve(data_dir: Path, contest_id: str) -> dict[str, str]:
    """Find a contest row. `<prefix>latest` (e.g. ap-cfb-latest) = the newest contest."""
    source = source_of(contest_id)
    rows = contests(data_dir, source)
    if not rows:
        raise ValueError(f"no ballot data for source '{source}' - run `ballmonitor fetch ranked_choice`")
    if contest_id.endswith("-latest"):
        return max(rows, key=week_key)
    for r in rows:
        if r["contest_id"] == contest_id:
            return r
    near = [r["contest_id"] for r in rows if r["contest_id"].startswith(contest_id[: len(contest_id) - 3])][:6]
    raise ValueError(f"contest '{contest_id}' not found" + (f"; similar: {', '.join(near)}" if near else ""))


def _index(path: Path) -> dict[str, list[tuple]]:
    """Whole source file grouped by contest (read once per file version; strings interned)."""
    def load():
        groups: dict[str, list[tuple]] = {}
        intern = {}
        with _open(path) as f:
            reader = csv.reader(f)
            header = next(reader)
            col = {k: i for i, k in enumerate(header)}
            keys = ("voter", "affiliation", "rank", "candidate_id", "candidate", "team")
            idx = [col.get(k) for k in keys]
            ci = col["contest_id"]
            for row in reader:
                vals = tuple(intern.setdefault(row[i], row[i]) if i is not None else "" for i in idx)
                groups.setdefault(row[ci], []).append(vals)
        return groups

    return _cached(("index", str(path), path.stat().st_mtime), load)


def ballots_for(data_dir: Path, contest: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
    """([{voter, affiliation, ranking: [candidate_id, ...]}], names, teams) for one contest."""
    path = data_dir / f"{source_of(contest['contest_id'])}.csv.gz"
    voters: dict[tuple, dict[str, Any]] = {}
    names: dict[str, str] = {}
    teams: dict[str, str] = {}
    for voter, affiliation, rank, cid, cand, team in _index(path).get(contest["contest_id"], []):
        v = voters.setdefault((voter, affiliation), {"voter": voter, "affiliation": affiliation, "places": {}})
        v["places"][int(rank)] = cid
        names.setdefault(cid, cand)
        if team:
            teams.setdefault(cid, team)
    out = [{"voter": v["voter"], "affiliation": v["affiliation"],
            "ranking": [v["places"][r] for r in sorted(v["places"])]} for v in voters.values()]
    return out, names, teams


def published(contest: dict[str, str]) -> list[tuple[str, float, int]]:
    out = []
    for part in filter(None, (contest.get("published") or "").split(";")):
        cid, pts, first = (part.split(":") + ["", "", ""])[:3]
        out.append((cid, float(pts or 0), int(first or 0)))
    return out


def points_list(contest: dict[str, str]) -> list[float]:
    return [float(x) for x in (contest.get("points") or "").split(",") if x.strip()]
