# Data tables: big sports CSVs for tabdn table servers

`build.py` downloads public sports data and writes slim CSVs (short plain column names, only
the columns worth filtering on) for the live data tables on ballmonitor.com
(`web/tables.toml`, pages at `#/data/<id>`).

```bash
python -m ballmonitor.data_tables.build                  # all tables
python -m ballmonitor.data_tables.build --only nfl_qb    # nfl_qb | nba | wnba (repeatable)
python -m ballmonitor.data_tables.build --offline        # only what's in raw/ already
```

Downloads are kept gzipped in `raw/` and the CSVs written to `csv/` (both gitignored).

| table | CSV | rows | source | license |
|---|---|---|---|---|
| `nfl_qb` | `qb_games` (`nfl_qb_games.csv`) | every player-game with a pass thrown, 1999 on (~18k) | nflverse weekly player stats | CC BY 4.0: credit nflverse |
| `nba` | `nba_games` (`nba_player_games.csv`) | every player-game played, 1994 on (~869k) | ESPN box scores via the SportsDataverse | collection MIT; the box scores are ESPN's |
| `wnba` | `wnba_games` (`wnba_player_games.csv`) | every player-game played, 2003 on (~108k) | same | same |

Notes:

- **QB:** `rating` is the NFL passer rating worked out from each game's line (`passer_rating`);
  `air_yds` and `cpoe` exist only from 2006 (nflverse's charting) and are blank before. tabc
  stores a blank number as 0, which the column key on the page says.
- **Basketball:** preseason and all-star games and did-not-play rows are left out; `type` is
  regular, play-in or playoffs; `pm` is plus-minus. `result` comes from the two scores: ESPN's
  own winner flag disagrees with them in about 29% of NBA team-games, while the scores match
  the players' points added up in all but 28 of 84,332. WNBA 2002 comes in an older ESPN layout
  with no stats ("--" everywhere), so it is left out; the converter reads that layout anyway
  (`_normalise`: opponent and scores from adding up each game's box score, `home` blank) in case
  a corrected file appears.

## Putting a table on the site

1. Build its `.com`: tabdn's builder page (drop the CSV), or in `tabdn/tabc`:
   `node tools/mkcom.mjs <csv> qb_games.com --blanks-zero` (and `nba_games.com`, `wnba_games.com`).
2. Upload it next to `batting.com` / `pitching.com` on data.tabdn.com
   (`tabdn/tools/deploy/upload-table.sh`).
3. In `web/tables.toml` set `sports = "https://data.tabdn.com/"`, run
   `ballmonitor tables --check`, rebuild and push.
