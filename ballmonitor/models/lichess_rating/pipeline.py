"""Build walk-forward cases from the daily totals made by download.py.

    python -m ballmonitor.models.lichess_rating.pipeline            # -> data/raw/cases.parquet

A case = (player, speed, cutoff date, horizon). Everything in the features is computed
from days strictly before the cutoff; the target is the player's rating at
cutoff + horizon days (the post-game rating after their last game on or before that
day; a player who stops playing keeps their rating, as on Lichess). The future games
column (`future_games`) is the number of games actually played in (cutoff, target] — it
is hindsight, used only for the "if you play N games a week" scenario study, never as
a forecast input.

Cutoffs: the 1st of every month from 2014-07 (six months of history first) to the last
month whose 30-day target is still inside the downloaded data. A player-speed is a case at
a cutoff only if it played a game in that speed in the 91 days before it.

Needs pandas + pyarrow (the `data` extra). Nothing here is used at prediction time.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_DIR = Path(__file__).resolve().parent
RAW = MODEL_DIR / "data" / "raw"
DAYS_DIR = RAW / "lichess_days"
HORIZONS = (30, 91, 182, 365)
EPOCH = dt.date(2014, 1, 1)
FIRST_CUTOFF = dt.date(2014, 7, 1)
ACTIVE_DAYS = 91  # case only if a game in the 91 days before the cutoff
NEW_RATING = 1500  # Lichess's starting rating


def day_number(d: dt.date) -> int:
    return (d - EPOCH).days


def load_days(speeds: set[str]) -> pd.DataFrame:
    frames = []
    dtypes = {"player": str, "speed": str, "date": str, "games": np.int32, "score": np.float32,
              "opp_sum": np.int64, "rating_first": np.int32, "rating_last": np.int32}
    for path in sorted(DAYS_DIR.glob("days_*.csv.gz")):
        df = pd.read_csv(path, dtype=dtypes)
        df = df[df.speed.isin(speeds)]
        df["day"] = (pd.to_datetime(df.date, format="%Y-%m-%d") - pd.Timestamp(EPOCH)).dt.days.astype(np.int32)
        frames.append(df.drop(columns="date"))
    df = pd.concat(frames, ignore_index=True)
    df["player"] = df.player.astype("category")
    df["speed"] = df.speed.astype("category")
    return df.sort_values(["player", "speed", "day"], kind="stable").reset_index(drop=True)


def month_starts(first: dt.date, last: dt.date) -> list[dt.date]:
    out, d = [], first
    while d <= last:
        out.append(d)
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def player_split(name: str) -> str:
    """Stable train/test split of players (independent of the time split)."""
    return "test" if zlib.crc32(("split:" + name.lower()).encode()) % 2 else "train"


def cases_for(player: str, speed: str, g: pd.DataFrame, cutoffs: list[int], last_day: int) -> list[dict]:
    day = g.day.to_numpy()
    games = g.games.to_numpy()
    first = g.rating_first.to_numpy()
    last = g.rating_last.to_numpy()
    score = g.score.to_numpy()
    opp = g.opp_sum.to_numpy()
    cum_games = np.cumsum(games)
    cum_peak = np.maximum.accumulate(last)
    new_account = bool(first[0] == NEW_RATING and day[0] > 14)  # first seen at 1500, after 2014-01-15
    out = []
    for c in cutoffs:
        i = np.searchsorted(day, c)  # days < c
        if i == 0 or day[i - 1] < c - ACTIVE_DAYS:
            continue
        r0 = int(last[i - 1])
        n_games = int(cum_games[i - 1])

        def window(days_back: int):
            j = np.searchsorted(day, c - days_back)
            return j, int(games[j:i].sum()), int(i - j)

        j28, g28, d28 = window(28)
        j91, g91, d91 = window(91)
        s91, o91 = float(score[j91:i].sum()), float(opp[j91:i].sum())
        k = np.searchsorted(day, c - 91)  # rating 91 days ago: last rating before c-91, else first seen
        r_91 = int(last[k - 1]) if k > 0 else int(first[0])
        base = {
            "player": player, "speed": speed, "cutoff": c,
            "rating": r0, "games_total": n_games,
            "days_since_first": int(c - day[0]), "new_account": new_account,
            "days_since_last": int(c - day[i - 1]),
            "games_28": g28, "days_28": d28, "games_91": g91, "days_91": d91,
            "score_91": s91, "opp_mean_91": o91 / g91 if g91 else np.nan,
            "rating_91_ago": r_91, "peak": int(cum_peak[i - 1]),
        }
        for h in HORIZONS:
            t = c + h
            if t > last_day:
                continue
            m = np.searchsorted(day, t, side="right")  # days <= t
            row = dict(base, horizon=h, target=int(last[m - 1]),
                       future_games=int(cum_games[m - 1] - cum_games[i - 1]),
                       future_days=int(m - i))
            out.append(row)
    return out


def build(speeds: set[str]) -> pd.DataFrame:
    df = load_days(speeds)
    manifest = [json.loads(l) for l in (DAYS_DIR / "manifest.jsonl").read_text().splitlines()]
    months = sorted({m["month"] for m in manifest if (DAYS_DIR / f"days_{m['month']}.csv.gz").exists()})
    y, mo = map(int, months[-1].split("-"))
    last_date = dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1)
    last_day = day_number(last_date)
    cutoffs = [day_number(d) for d in month_starts(FIRST_CUTOFF, last_date - dt.timedelta(days=min(HORIZONS)))]
    rows: list[dict] = []
    for (player, speed), g in df.groupby(["player", "speed"], sort=False, observed=True):
        rows.extend(cases_for(player, speed, g, cutoffs, last_day))
    cases = pd.DataFrame(rows)
    cases["cutoff_date"] = pd.Timestamp(EPOCH) + pd.to_timedelta(cases.cutoff, unit="D")
    cases["split_player"] = cases.player.map(player_split)
    return cases


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--speeds", default="blitz,bullet,classical,rapid")
    args = ap.parse_args(argv)
    cases = build(set(args.speeds.split(",")))
    out = RAW / "cases.parquet"
    cases.to_parquet(out, index=False)
    print(f"{len(cases):,} cases, {cases.player.nunique():,} players -> {out}")


if __name__ == "__main__":
    main()
