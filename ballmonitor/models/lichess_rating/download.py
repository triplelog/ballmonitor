"""Stream the Lichess open database into per-player daily totals (cached in data/raw/).

    python -m ballmonitor.models.lichess_rating.download                     # 2014-01 .. 2017-12
    (the committed study used 2014-01 .. 2017-08: a 2017 month takes ~12-15 min at ~14 MB/s)
    python -m ballmonitor.models.lichess_rating.download --months 2019-01:2019-06
    python -m ballmonitor.models.lichess_rating.download --sample 4          # 1 player in 4

Source: https://database.lichess.org/ (every rated standard game, one .pgn.zst per month,
CC0). A recent month is ~30 GB compressed, so nothing is saved: each month is streamed
through `curl | zstd -dc | grep` (needs curl, zstd and grep on the PATH) and only the
header lines are parsed. For a fixed sample of players (crc32 of the lower-cased name
mod --sample == 0, so the same players are kept in every month) each (player, speed, UTC
day) becomes one row:

    player, speed, date, games, score, opp_sum, rating_first, rating_last

games = rated games that day, score = wins + draws/2, opp_sum = sum of opponents' pre-game
ratings, rating_first = pre-game rating in the day's first game, rating_last = post-game
rating after the day's last game (pre-game rating + RatingDiff).

Speed = the rating the game was played for. Neither header says it reliably for old
games: in 2014 a tournament's games are labelled with the tournament's speed, and the
time-control cut-offs have changed (a 60+3 game, blitz by today's rule, was rated as
bullet). So the speed is first estimated from TimeControl with today's cut-offs
(seconds = base + 40 x increment: ultrabullet < 30, bullet < 180, blitz < 480, rapid
< 1500, else classical; "-" = correspondence; before the month's first "Rated Rapid" /
"Rated UltraBullet" event those go to classical / bullet), then checked against the
player's rating chains: if the pre-game rating does not continue the estimated speed's
chain (its last post-game rating) but exactly continues one other speed's chain, the
game belongs to that speed. Chains carry over between months (chains_YYYY-MM.json.gz),
so months must be processed in order; a month without the previous month's chains
starts from empty chains.

Output: data/raw/lichess_days/days_YYYY-MM.csv.gz plus a line per month in manifest.jsonl
(games read, rows kept). Finished months are skipped on re-runs; a month is written to a
.tmp file first, so an interrupted month is redone. Nothing here is used at prediction time.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import subprocess
import time
import zlib
from pathlib import Path

URL = "https://database.lichess.org/standard/lichess_db_standard_rated_{month}.pgn.zst"
RAW_DIR = Path(__file__).resolve().parent / "data" / "raw" / "lichess_days"
DEFAULT_MONTHS = "2014-01:2017-12"
DEFAULT_SAMPLE = 4
HEADER_RE = r'^\[(Event|White|Black|UTCDate|WhiteElo|BlackElo|WhiteRatingDiff|BlackRatingDiff|Result|TimeControl) "'
COLUMNS = ["player", "speed", "date", "games", "score", "opp_sum", "rating_first", "rating_last"]


def months_between(spec: str) -> list[str]:
    """'2013-01:2013-03' -> ['2013-01', '2013-02', '2013-03']."""
    start, _, end = spec.partition(":")
    end = end or start
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def keep(name: str, sample: int) -> bool:
    return zlib.crc32(name.lower().encode()) % sample == 0


def _int(text: str | None) -> int | None:
    try:
        return int(text) if text not in (None, "", "?") else None
    except ValueError:
        return None


SPEED_LIMITS = [(30, "ultrabullet"), (180, "bullet"), (480, "blitz"), (1500, "rapid")]


def speed_of(time_control: str, has_rapid: bool = True, has_ultrabullet: bool = True) -> str:
    """Lichess rating category of a game from its TimeControl ('180+2', '-')."""
    if not time_control or time_control == "-":
        return "correspondence"
    base, _, inc = time_control.partition("+")
    seconds = int(base) + 40 * int(inc or 0)
    for limit, name in SPEED_LIMITS:
        if seconds < limit:
            if name == "ultrabullet" and not has_ultrabullet:
                return "bullet"
            if name == "rapid" and not has_rapid:
                return "classical"
            return name
    return "classical"


def pick_speed(guess: str, pre: int, chains: dict[str, int]) -> str:
    """Speed whose rating chain this game continues (see the module docstring)."""
    if chains.get(guess, pre) == pre:
        return guess
    matches = [speed for speed, last in chains.items() if last == pre]
    return matches[0] if len(matches) == 1 else guess


def parse_stream(lines, sample: int, chains: dict[str, dict[str, int]] | None = None
                 ) -> tuple[dict, int]:
    """Aggregate header lines (in file order) into {(player, speed, date): [games, ...]}.

    `chains` ({player: {speed: last post-game rating}}) is updated in place.
    """
    days: dict[tuple[str, str, str], list] = {}
    chains = {} if chains is None else chains
    n_games = 0
    game: dict[str, str] = {}
    has = {"rapid": False, "ultrabullet": False}

    def flush() -> None:
        nonlocal n_games
        if "Event" not in game:
            return
        n_games += 1
        words = game["Event"].split()
        label = words[1].lower() if len(words) > 1 else ""
        if label in has:
            has[label] = True
        try:
            guess = speed_of(game.get("TimeControl", ""), has["rapid"], has["ultrabullet"])
        except ValueError:
            return
        date = game.get("UTCDate", "").replace(".", "-")
        result = game.get("Result", "*")
        if result not in ("1-0", "0-1", "1/2-1/2"):
            return
        w_score = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[result]
        for side, other, score in (("White", "Black", w_score), ("Black", "White", 1 - w_score)):
            name = game.get(side)
            if not name or not keep(name, sample):
                continue
            pre = _int(game.get(side + "Elo"))
            opp = _int(game.get(other + "Elo"))
            if pre is None or opp is None:
                continue
            diff = _int((game.get(side + "RatingDiff") or "").lstrip("+")) or 0
            player_chains = chains.setdefault(name, {})
            speed = pick_speed(guess, pre, player_chains)
            player_chains[speed] = pre + diff
            key = (name, speed, date)
            row = days.get(key)
            if row is None:
                days[key] = [1, score, opp, pre, pre + diff]
            else:
                row[0] += 1
                row[1] += score
                row[2] += opp
                row[4] = pre + diff

    for line in lines:
        # line looks like: [Tag "value"]
        tag, _, rest = line[1:].partition(" ")
        if tag == "Event":
            flush()
            game = {}
        game[tag] = rest[1:rest.rfind('"')]
    flush()
    return days, n_games


def previous_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def load_chains(month: str) -> dict[str, dict[str, int]]:
    path = RAW_DIR / f"chains_{month}.json.gz"
    if not path.exists():
        return {}
    with gzip.open(path, "rt") as fh:
        return json.load(fh)


def fetch_month(month: str, sample: int) -> dict:
    out = RAW_DIR / f"days_{month}.csv.gz"
    tmp = out.with_suffix(".tmp")
    cmd = (
        f"set -o pipefail; curl -sfL --retry 5 --retry-delay 30 '{URL.format(month=month)}' "
        f"| zstd -dc | LC_ALL=C grep -E '{HEADER_RE}'"
    )
    t0 = time.time()
    proc = subprocess.Popen(["bash", "-c", cmd], stdout=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", bufsize=1 << 20)
    chains = load_chains(previous_month(month))
    days, n_games = parse_stream(proc.stdout, sample, chains)
    if proc.wait() != 0:
        raise RuntimeError(f"{month}: download pipeline failed (exit {proc.returncode})")
    with gzip.open(tmp, "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for (name, speed, date), (g, s, opp, first, last) in sorted(days.items()):
            w.writerow([name, speed, date, g, s, opp, first, last])
    with gzip.open(RAW_DIR / f"chains_{month}.json.gz", "wt") as fh:
        json.dump(chains, fh)
    tmp.replace(out)
    info = {"month": month, "games": n_games, "rows": len(days), "sample": sample,
            "seconds": round(time.time() - t0)}
    with open(RAW_DIR / "manifest.jsonl", "a") as fh:
        fh.write(json.dumps(info) + "\n")
    return info


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--months", default=DEFAULT_MONTHS, help="YYYY-MM:YYYY-MM (inclusive)")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE, help="keep 1 player in N")
    args = ap.parse_args(argv)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for month in months_between(args.months):
        if (RAW_DIR / f"days_{month}.csv.gz").exists():
            continue
        info = fetch_month(month, args.sample)
        print(json.dumps(info), flush=True)


if __name__ == "__main__":
    main()
