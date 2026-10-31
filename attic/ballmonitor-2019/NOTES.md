# Ball Monitor (2019): saved pieces

The useful parts of the original `triplelog/ballmonitor` repo (static MLB stats site, last
commit 2019-10-17, `8c8fc0e`), saved before that repo is replaced by this project. Nothing
here is wired into the current site or tests; it is kept to come back to.

Left out: the vendored libraries (d3, dragula, tagify, awesomplete, papaparse, nouislider,
sparkline, popper), `box/2000/` (110 MB of per-team box scores), the team/player pages and the
unfinished southeastern-states map game. The pages expected a local API (`localhost`) that
was never in the repo, so they don't run as-is.

## What's here

| Piece | Files | Idea worth keeping |
|---|---|---|
| Season simulator | `season.html`, `js/season.js`, `js/season_simulator.js`, `js/season_results.js` (2016 results), `js/standings_data.js`, `seasons/2018Data.json`, `css/standings.css` | Each game's runs ~ Weibull(scale = team runs scored x opponent runs allowed / league avg, shape 1.8), stepped day by day through the real schedule. Shape = Pythagorean exponent (Miller 2007). A bankroll/betting layer ran user-supplied strategy functions via Google Caja (shut down 2021). |
| Streak finder | `stats.html`, `js/stats.js`, `js/streak_data.js`, `js/main.js` | Player streaks on a user-written stat formula, filtered by years, age, month, team, opponent. `main.js` has the infix -> Polish formula parser (core/formula.py now does this safely). |
| Box score viewer | `boxscore.html`, `js/boxscore.js`, `js/boxscore_data.js`, `css/boxscore.css`, `box/ATL197309260*` (one 1973 LAN at ATL game), `box/ATL1973gamelogs.json` | Retrosheet event file -> plays / batter box / pitcher box CSVs + linescore with play links. With a win-expectancy table it could become an MLB version of `cfb_replay`. |

## Ideas for the current project

- **`mlb_season_sim` model**: the Weibull season simulator as a normal model. Params: Weibull
  shape, regression of team runs toward league average, home-field runs, simulations, seed.
  Outputs: win totals, division/playoff odds. Backtest: preseason or midseason inputs vs final
  wins. See ROADMAP.md ("Season win totals / playoff odds", "Pythagorean expectation").
- **Streaks**: "longest streak with stat formula > x" as a model or a game, using
  `core/formula.py` for the formula.
- **MLB replay**: Retrosheet plays + win expectancy -> the `cfb_replay` chart/video pipeline.

## Data notice

The box score files were built from Retrosheet event files. Any reuse must carry Retrosheet's
notice: "The information used here was obtained free of charge from and is copyrighted by
Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org."
