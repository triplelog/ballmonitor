"""Download every regular-season MLB pitch (Statcast) and build the next_pitch datasets.

    ballmonitor fetch next_pitch            # download missing days (cached in data/raw/) and rebuild
    ballmonitor fetch next_pitch --offline  # rebuild from data/raw/ only

Writes:
    data/raw/schedule_<season>.json   regular-season game dates (MLB Stats API)
    data/raw/days/<date>.csv.gz       that day's pitches, reduced to the columns in KEEP
    data/pitches/<season>.parquet     all pitches of a season, sorted, with derived columns
                                      (large; gitignored; used by research.py)
    data/pitchers/<id>.csv.gz         one pitcher's history in the compact form model.py reads
    data/pitchers.csv                 index: id, name, throws, pitches per season
    data/batters.csv                  batter id, name, bats and latest rolling stats
    data/backtest.csv                 sampled 2026 pitches for `ballmonitor backtest next_pitch`

Sources (free, no key): Baseball Savant Statcast search CSV (baseballsavant.mlb.com) and the
MLB Stats API (statsapi.mlb.com). Building needs `pip install -e '.[data]'` (pandas, pyarrow).
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SEASONS = [2021, 2022, 2023, 2024, 2025, 2026]
UA = {"User-Agent": "Mozilla/5.0 (ballmonitor data fetch)"}
SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&season={season}&gameType=R&fields=dates,date"
SAVANT = (
    "https://baseballsavant.mlb.com/statcast_search/csv?all=true&hfGT=R%7C&hfSea={season}%7C"
    "&player_type=pitcher&game_date_gt={day}&game_date_lt={day}&type=details"
)
SAVANT_ROW_CAP = 25_000  # Savant silently truncates a search at this many rows
WORKERS = 4  # polite parallelism

KEEP = [
    "game_pk", "game_date", "pitcher", "player_name", "batter", "stand", "p_throws",
    "pitch_type", "balls", "strikes", "outs_when_up", "inning", "inning_topbot",
    "on_1b", "on_2b", "on_3b", "at_bat_number", "pitch_number", "description", "events",
    "type", "zone", "plate_x", "plate_z", "release_speed", "bat_score", "fld_score",
    "n_thruorder_pitcher", "woba_value", "woba_denom", "estimated_woba_using_speedangle",
    "delta_run_exp", "bb_type", "launch_speed", "launch_angle", "home_team", "away_team",
    "pitcher_days_since_prev_game",
]
RUNNER_COLS = {"on_1b", "on_2b", "on_3b"}  # stored as 1/0 flags instead of player ids


def _get(url: str, timeout: int = 180, tries: int = 4) -> bytes:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as res:
                return res.read()
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def season_dates(raw: Path, season: int, offline: bool) -> list[str]:
    path = raw / f"schedule_{season}.json"
    if not path.exists() or (not offline and season == max(SEASONS)):
        if offline:
            raise FileNotFoundError(f"{path} missing; run without --offline first")
        path.write_bytes(_get(SCHEDULE.format(season=season)))
    return [d["date"] for d in json.loads(path.read_text()).get("dates", [])]


def reduce_day(text: str) -> tuple[list[str], list[list[str]]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    rows = []
    for r in reader:
        rows.append([("1" if r.get(c) else "0") if c in RUNNER_COLS else r.get(c, "") for c in KEEP])
    return KEEP, rows


def download_day(raw_days: Path, season: int, day: str) -> tuple[str, int]:
    path = raw_days / f"{day}.csv.gz"
    text = _get(SAVANT.format(season=season, day=day)).decode("utf-8", "replace")
    header, rows = reduce_day(text)
    if len(rows) >= SAVANT_ROW_CAP:
        raise RuntimeError(f"{day}: {len(rows)} rows hit the Savant cap; split the query")
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    tmp.rename(path)
    return day, len(rows)


def download(model_dir: Path, offline: bool = False, log=print) -> None:
    raw = model_dir / "data" / "raw"
    raw_days = raw / "days"
    raw_days.mkdir(parents=True, exist_ok=True)
    todo = []
    for season in SEASONS:
        for day in season_dates(raw, season, offline):
            if not (raw_days / f"{day}.csv.gz").exists():
                todo.append((season, day))
    if offline or not todo:
        if todo:
            log(f"offline: {len(todo)} days not downloaded")
        return
    log(f"downloading {len(todo)} days from Baseball Savant ({WORKERS} at a time)")
    done = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = [pool.submit(download_day, raw_days, s, d) for s, d in todo]
        for fut in as_completed(futures):
            try:
                day, n = fut.result()
                done += 1
                if done % 25 == 0 or done == len(todo):
                    log(f"  {done}/{len(todo)} days (last: {day}, {n} pitches)")
            except Exception as exc:  # keep going; the next run retries missing days
                log(f"  failed: {exc}")


def fetch(model_dir: Path, offline: bool = False) -> list[str]:
    log: list[str] = []
    download(model_dir, offline, log=lambda s: (log.append(s), print(s, flush=True)))
    from ballmonitor.models.next_pitch import build

    log.extend(build.build_all(model_dir))
    return log


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    if "--download-only" in sys.argv:
        download(here, offline=False, log=lambda s: print(s, flush=True))
    else:
        for line in fetch(here, offline="--offline" in sys.argv):
            print(line)
