# Open WAR (`open_war`)

**Question:** How many wins above a replacement player was each big-leaguer worth, season by season?

**Status:** draft. It is a sanity-checked approximation of published WAR, with no backtest. Home Turf
(`ballmonitor/games/home_turf`) uses its seasons as each player's battle strength.

## Inputs

| input | meaning | example |
|---|---|---|
| `player` | Lahman playerID | `"ruthba01"` |

Examples: `default` (Babe Ruth), `maddux`, `bonds` (try `--set use_park_factors=false`).

## Method (per player-season, stints combined)

1. **Batting runs.** Formula `linear_weights` (singles 0.47, doubles 0.78, triples 1.07, HR 1.40,
   BB+HBP 0.31, SB 0.2, CS −0.41), plus outs (AB − H + SH + SF + CS) times the league-year's out
   value, minus the league's runs per plate appearance times the player's PA. The league is the same
   league and year.
   - **Run environment** (`use_run_environment`): the out value (formula `out_value` = (league runs
     − league linear-weight runs) / league outs, about −0.1) makes the league's linear-weight runs
     equal the runs it scored. Every era's runs then add up, and getting on base is valued by its
     era.
   - **Park.** Adjusted with Lahman's batting park factor when `use_park_factors`.
2. **Position runs.** The sum over positions of `pos_<position>` runs per 162 games times games
   there (FanGraphs' adjustments: C +12.5 … DH −17.5).
3. **Replacement.** `batting_replacement_runs` per 600 PA (18.75). For pitchers:
   (league RA9 × pitching park factor − RA9) × IP/9 + `pitching_replacement_runs_per_9` (0.894) × IP/9.
4. **Wins.** Runs divided by formula `runs_per_win` = 1.5 × league runs per team-game + 3 (about 10).
5. Players who were mostly pitchers in a season get no batting value (`pitcher_batting = false`).

The two replacement levels are solved in RESEARCH.md: 2000–2024 seasons average 570 batting and 430
pitching WAR per 30 teams. That is the 1,000-win level Baseball-Reference and FanGraphs adopted
together in 2013.

## Assumptions and known weaknesses

- No fielding runs. A player's defense counts only through his position.
- Pitchers are judged on runs allowed. Park factors are applied, but not his fielders' defense.
- **Hit values don't change by era.** The out value follows each era's run environment, but the
  positive events keep fixed values. Seasons with no fielding credit run low: Ruth 1921 is 10.5
  here (Baseball-Reference 12.6), Mays 1965 9.0 (11.2). Bonds 2001 (11.9) and Cobb 1911 (10.0)
  match closely. Career leaders: Cy Young, Ruth, Walter Johnson, Cobb, Bonds, Mays (RESEARCH.md).
- **Caught stealing is missing** before the 1910s–20s in Lahman (counted as 0).

## Data

`fetch.py` (by hand, `ballmonitor fetch open_war`) computes every season from the Lahman CSVs
(Triple Play's raw folder) and writes `data/seasons.csv` (118,000 player-seasons, 1871–2025, about
8.5 MB). That file is not in git (owner's choice, 2026-11-22). `predict` computes from the Lahman CSVs
directly, so the model runs only where they are. It is kept off the site build (`[web] public =
false`), and its tests skip elsewhere (`[local] requires`). Home Turf's build reads `seasons.csv`.

## References

- Tango, Lichtman & Dolphin, *The Book* (2007): linear weights.
- FanGraphs and Baseball-Reference WAR documentation: positional adjustments, the unified
  replacement level (2013).
- Lahman Baseball Database (SABR), CC BY-SA 3.0.

## Changelog

- 0.2.0 (2026-11-22): outs valued by each league-year's run environment (`use_run_environment`,
  formula `out_value`). Before, outs counted zero and on-base skill was undervalued (Ruth 1921 9.8 →
  10.5, Bonds 2001 11.1 → 11.9). Replacement levels re-solved (batting 18.44 runs per 600 PA).
- 0.1.0 (2026-11-22): first version.
