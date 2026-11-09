"""Build the Lineup puzzle files.

    python -m ballmonitor.games.lineup.build                          # 2026-11-09 .. 2027-12-31
    python -m ballmonitor.games.lineup.build --start 2026-11-09 --end 2027-03-31
    python -m ballmonitor.games.lineup.build --keep-through 2026-12-01   # leave published days alone

Needs the Lahman CSVs Triple Play unpacks (games/triple_play/data/raw/lahman_csv/; see its
README) and numpy (`pip install -e '.[data]'`). About 3 s per day (every order of every
puzzle is scored). Output: web/puzzles/daily/index.json + one JSON per month, committed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from ballmonitor.games.lineup import chain, generate, players

OUT = Path(__file__).parent / "web" / "puzzles" / "daily"
FIRST_DAY = dt.date(2026, 11, 9)


def write(puzzles: list[dict], source: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    months: dict[str, list] = {}
    for p in puzzles:
        months.setdefault(p["date"][:7], []).append(p)
    for month, ps in months.items():
        (OUT / f"{month}.json").write_text(json.dumps(ps, separators=(",", ":")), encoding="utf-8")
    index = {"source": source, "built": dt.date.today().isoformat(),
             "puzzles": [{"date": p["date"], "number": p["number"]} for p in puzzles]}
    (OUT / "index.json").write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", type=dt.date.fromisoformat, default=FIRST_DAY)
    ap.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2027, 12, 31))
    ap.add_argument("--keep-through", type=dt.date.fromisoformat,
                    help="keep the already-published puzzles up to this date unchanged")
    args = ap.parse_args(argv)
    from ballmonitor.games.triple_play import facts

    fame = {pid: p["fame"] for pid, p in facts.load().items()}
    seasons = players.load()
    puzzles = generate.generate(seasons, fame, args.start, args.end, chain.load_rules())
    if args.keep_through:
        old = {}
        for f in OUT.glob("????-??.json"):
            old.update({p["date"]: p for p in json.loads(f.read_text(encoding="utf-8"))})
        keep = args.keep_through.isoformat()
        puzzles = [old[p["date"]] if p["date"] <= keep and p["date"] in old else p for p in puzzles]
    last = max(s["year"] for s in seasons)
    write(puzzles, f"Lahman Baseball Database (seasons {players.MIN_YEAR}-{last})")
    gaps = sorted(p["best"]["runs"] - p["worst"]["runs"] for p in puzzles)
    print(f"wrote {len(puzzles)} puzzles to {OUT}; best-minus-worst runs per game: "
          f"min {gaps[0]:.3f}, median {gaps[len(gaps) // 2]:.3f}, max {gaps[-1]:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
