# Roadmap

## Planned

- `mlb_season_sim`: Weibull run-scoring season simulator -> win totals and playoff odds
  (from the 2019 Ball Monitor season simulator; see attic/ballmonitor-2019/NOTES.md).
- `ncaab_seeding`: NCAA tournament seed-line probabilities (a stub is archived in
  `../modelstuff/archived_models/`).
- `race_elevation`: elevation and altitude adjustment feeding `race_time` (stub archived in
  `../modelstuff/archived_models/`).

## Ideas (simple models that fit the same pattern)

**Sports**
- Game win probability from a point spread or Elo difference (the building block for several models above; consider making it a shared helper).
- Elo ratings for any league from results only, with tunable K-factor and home advantage.
- Season win totals / playoff odds by simulating the remaining schedule (NFL, NBA, MLB).
- Pythagorean expectation (runs/points scored vs. allowed -> expected win %), exponent tunable.
- NCAA bracket advancement odds per round (pairs with `ncaab_seeding`).
- Fourth-down go/punt/kick win-probability comparison.
- Fantasy player projections with regression to the mean (weight on prior vs. this season).
- Probability a lead holds (win probability from margin + time remaining).
- Player streaks on a custom stat formula (2019 Ball Monitor streak finder).
- MLB game replay from Retrosheet plays + win expectancy (like `cfb_replay`).

**Running / fitness**
- Marathon "wall" risk from training volume (weekly mileage, long-run length).
- Heat & humidity adjustment for race times (dew point based).
- Age-grading: performance vs. age/sex standards; predicted decline with age.
- Training load -> injury-risk flag (acute:chronic workload ratio, thresholds tunable).
