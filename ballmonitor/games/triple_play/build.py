"""Build the Triple Play puzzle files.

    python -m ballmonitor.games.triple_play.build                       # from data/raw/lahman_csv
    python -m ballmonitor.games.triple_play.build --lahman ~/Downloads/lahman_1871-2025_csv.zip
    python -m ballmonitor.games.triple_play.build --start 2026-11-09 --end 2027-12-31

--lahman accepts SABR's comma-delimited zip (sabr.org/lahman-database, download it in a
browser) or the CRAN `Lahman_*.tar.gz` (needs `pip install rdata`); its tables are unpacked
into data/raw/lahman_csv/. Output: web/puzzles/baseball/index.json + one file per month.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import tarfile
import zipfile
from pathlib import Path

from ballmonitor.games.triple_play import facts, generate

HERE = Path(__file__).parent
OUT = HERE / "web" / "puzzles"
TABLES = ["People", "Batting", "Pitching", "Fielding", "Appearances", "AwardsPlayers", "AllstarFull",
          "HallOfFame", "Teams", "TeamsFranchises", "SeriesPost"]
FIRST_DAY = dt.date(2026, 11, 23)  # puzzle #1. 2026-11-23 (owner): the puzzles made by older rules
# (Nov 9-22 baseball, the cities & states Mondays) were removed and the numbering restarted


def unpack(src: Path) -> None:
    facts.RAW.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".zip":
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                stem = Path(info.filename).stem
                if stem in TABLES and info.filename.endswith(".csv"):
                    (facts.RAW / f"{stem}.csv").write_bytes(z.read(info))
    else:  # CRAN tarball with .RData tables
        import rdata  # optional: pip install rdata

        with tarfile.open(src) as t:
            for name in TABLES:
                member = t.extractfile(f"Lahman/data/{name}.RData")
                df = rdata.read_rda(io.BytesIO(member.read()))[name]
                df.to_csv(facts.RAW / f"{name}.csv", index=False)
    missing = [t for t in TABLES if not (facts.RAW / f"{t}.csv").exists()]
    if missing:
        raise SystemExit(f"missing tables after unpacking: {missing}")


def write(pack: str, puzzles: list[dict], source: str) -> None:
    out = OUT / pack
    out.mkdir(parents=True, exist_ok=True)
    months: dict[str, list] = {}
    for p in puzzles:
        months.setdefault(p["date"][:7], []).append(p)
    for month, ps in months.items():
        (out / f"{month}.json").write_text(json.dumps(ps, separators=(",", ":")), encoding="utf-8")
    index = {"source": source, "built": dt.date.today().isoformat(),
             "puzzles": [{"date": p["date"], "number": p["number"], "level": p["level"], "pack": p["pack"]}
                         for p in puzzles]}
    (out / "index.json").write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lahman", type=Path, help="SABR CSV zip or CRAN Lahman tarball to unpack first")
    ap.add_argument("--start", type=dt.date.fromisoformat, default=FIRST_DAY)
    ap.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2027, 12, 31))
    ap.add_argument("--keep-through", type=dt.date.fromisoformat,
                    help="keep the already-published puzzles up to this date unchanged")
    args = ap.parse_args(argv)
    if args.lahman:
        unpack(args.lahman)
    players = facts.load()
    last = max(p["last"] for p in players.values())
    fixed = {}
    if args.keep_through:
        keep = args.keep_through.isoformat()
        for f in (OUT / "daily").glob("????-??.json"):
            fixed.update({p["date"]: p for p in json.loads(f.read_text(encoding="utf-8")) if p["date"] <= keep})
        print(f"keeping {len(fixed)} published puzzles through {keep}")
    # published puzzles are used as they are, and later days are checked against them for repeats
    puzzles = generate.generate(players, args.start, args.end,
                                fixed=fixed)
    write("daily", puzzles, f"Lahman Baseball Database (stats through {last})")
    print(f"wrote {len(puzzles)} puzzles to {OUT / 'daily'} (stats through {last})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
