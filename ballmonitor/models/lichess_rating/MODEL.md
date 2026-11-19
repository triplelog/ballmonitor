# Lichess rating progress (`lichess_rating`)

**Question.** What will this player's Lichess rating be on a chosen future date, and how
likely are they to reach a given rating?

## Inputs

All of these are on a Lichess profile's stats page for one speed (or the rating graph).

| input | meaning | default |
|---|---|---|
| `speed` | blitz, bullet, rapid or classical (fitted on blitz; see weaknesses) | `"blitz"` |
| `rating` | current rating in that speed | required |
| `target_date` + `as_of`, or `horizon_days` | the date to predict (as_of defaults to today) | required |
| `games_total` | rated games played in that speed so far | required |
| `games_last_28_days`, `games_last_91_days` | recent rated games in that speed | 91 → same as 28 |
| `days_since_last_game` | days since the last rated game in that speed | 0 if games in the last 28 days |
| `peak_rating` | highest rating reached | today's rating |
| `rating_91_days_ago` | rating about three months ago | today's rating |
| `score_last_91_days` | points scored in those games (win 1, draw ½) | half the games |
| `opponents_avg_last_91_days` | mean opponent rating in those games | today's rating |
| `keep_playing` | `true` = assume at least one more rated game | `false` |
| `goal_rating` | optional: chance of being at or above it on the target date | — |

## Method

A Lichess rating only changes when you play rated games, so the prediction is a mixture
of two fitted parts (`dist.py`, coefficients in `config.toml`, fitted by `research.py`):

1. **Features** (`dist.features`): `activity` = ln(1 + games in the last 28 days);
   `experience` = ln(1 + games so far, capped at `cap_games`); `below_peak` = (peak −
   rating)/100, capped at `cap_below_peak`; `trend` = (rating − rating 91 days ago)/100,
   ±`cap_trend`; `level` = (rating − 1500)/100; `form` = (recent performance − rating)/100,
   ±`cap_form`, where performance = mean opponent rating + 400 × (2 × score rate − 1);
   `idle` = ln(1 + days since the last game); `log_horizon` = ln(days ahead / 91).
2. **Keeps playing** — formula `p_active`: a logistic regression on activity, idle,
   experience and log_horizon gives p, the chance of at least one more rated game in that
   speed before the target date. With probability 1 − p the rating stays where it is.
   `keep_playing = true` sets p = 1.
3. **Change if playing** — for each level 2.5, 10, 25, 50, 75, 90 and 97.5%, a linear
   quantile regression `change_<level>_intercept + Σ change_<level>_<feature> × feature`
   (all horizons in one fit, with log_horizon as a feature). The quantiles are sorted (in
   case they cross), and `band_scale` stretches them around the median. Between the
   quantiles the distribution is linear; beyond the outer ones it has exponential tails
   through the outer two quantiles of each side.
4. **Mixture** — the rating on the target date = today's rating + change, where change
   is 0 with probability 1 − p and from step 3 with probability p. Reported: the median and
   the `interval_level` range, all seven percentiles, the chance of playing again, of being
   higher than today, of reaching the next two multiples of `milestone_step`, and of being
   at or above `goal_rating`.

## Assumptions and known weaknesses

- **Era and pool.** Fitted on Lichess 2014–2016 (tested to 2017-08). Today's pool is much larger, and Lichess's
  rating settings (and the default for new accounts) have changed since, so
  the bands may be off for today's players. A check against recent players would need
  recent monthly files (~30 GB each) or the API (slow, see `download.py` notes); not done yet.
- **Speeds.** Fitted on blitz only. Bullet and classical are scored with the blitz fit in
  RESEARCH.md. Lichess had no rapid category until 2018, so rapid is untested.
- **Practice is only past activity.** The model uses how much you have played, not what
  you plan to play. RESEARCH.md §4 shows how the change relates to games played *after* the
  cutoff (hindsight, association only — improving players may simply play more).
- **Experience is undercounted** in the data for accounts that started before 2014.
- Not modelled: cheating bans and rating refunds, new accounts made by experienced players,
  the provisional period's high rating deviation (only through experience), puzzles,
  study or over-the-board play.
- The quantile regressions are linear; very unusual inputs (rating 2900, 50,000 games)
  are outside the fitted range.

## Variants

- `wide_bands` — `band_scale` 1.25 (untested; for today's more varied pool).

## Data and backtest

`download.py` streams every monthly file of the Lichess open database
(database.lichess.org, CC0) for 2014-01 to 2017-08 through `curl | zstd | grep` (nothing
large is saved) and keeps per-player daily totals for a fixed 1-in-4 sample of players
(crc32 of the name). The game's speed is matched to the rating chain it continues
(old headers mislabel tournament games). `pipeline.py` builds cases: for each player,
speed and monthly cutoff where the player played in the previous 91 days, the features
from days before the cutoff and the rating 30, 91, 182 and 365 days later. `research.py`
fits on half the players (by hash) with targets before 2016-04-01 and tests on the other
half with cutoffs from 2016-04-01, writes RESEARCH.md, `data/fit.json` and
`data/backtest.csv`, and with `--write-config` copies the fit into config.toml.

`data/backtest.csv` (random test cases, one row each):

| column | meaning |
|---|---|
| `cutoff_date`, `horizon_days`, `speed` | when the prediction is made, days ahead, speed |
| `rating`, `games_total`, `games_28`, `games_91`, `days_since_last`, `peak`, `rating_91_ago`, `score_91`, `opp_mean_91` | the inputs, known at the cutoff |
| `actual_rating` | the rating on cutoff + horizon (last post-game rating on or before it) |
| `played_after` | 1 if the player played that speed again before the target |

`ballmonitor backtest lichess_rating` scores the median and the interval by speed × horizon.

**Results** (RESEARCH.md; test players, cutoffs 2016-04 – 2017-08, blitz, 60,000 random
test cases across speeds). Mean pinball = average quantile loss over the 7 levels.

| horizon | model pinball | "rating stays, typical spread" | model 50 / 80 / 95% band coverage |
|---|---:|---:|---|
| 30 days | 8.01 | 9.01 | 69 / 84 / 95% |
| 91 days | 11.46 | 12.37 | 65 / 82 / 94% |
| 182 days | 14.64 | 15.50 | 60 / 79 / 93% |
| 365 days | 18.66 | 18.84 | 56 / 74 / 91% |

- The model's gain over "no change" is in the **ranges**, not the median: ratings mostly
  hover, so the median's absolute error is about the same as "no change" (33.4 vs 32.8
  points over all horizons; worse at 365 days, 54.8 vs 50.9).
- The 50% band covers more than 50% because many players stop playing (no change at all),
  a point mass that any range around today's rating contains.
- **Chance of playing again:** Brier 0.139 vs 0.261 for a per-horizon rate; well calibrated
  above 40%, a little low below (predicted 6% → 10% played).
- **Experienced players (500+ games) are predicted too high:** median bias +21.7 points.
  Part of it is pool drift: whole quarters move together by ±20–40 points (RESEARCH.md
  §2b). The fit includes an effect for each quarter and the model uses the median one,
  which cut the bias from +26.5. The rest seems to be deflation of established players
  while the pool grew fast in 2016–2017.
- Bullet and classical scored with the blitz fit also beat both baselines (pinball
  10.00 vs 10.82 and 10.69 vs 11.43).
- **Practice (hindsight):** players who went on to play 15 games a week gained a median of
  29 points more than those who played 3 a week; 30 a week, 42 more (association only).
- `ballmonitor backtest lichess_rating` (the 4,000 committed test cases through
  model.py): 80% range coverage 82.5%, mean absolute error 32.2 points.

## References

- Lichess open database, https://database.lichess.org/ (CC0).
- Glickman, M. E. (2012). *Example of the Glicko-2 system* (the rating system Lichess uses).
- Koenker, R., & Bassett, G. (1978). Regression quantiles. *Econometrica* 46(1), 33–50.

## Changelog

- 0.1.0 — First version: keeps-playing logistic + pooled quantile regression (with
  quarter effects, typical quarter used), fitted on
  Lichess blitz 2014-01 – 2016-03, tested walk-forward on other players from 2016-04 to 2017-08.
