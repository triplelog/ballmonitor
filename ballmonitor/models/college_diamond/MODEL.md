# College baseball & softball projections (`college_diamond`)

**Question:** From a date in an NCAA Division I baseball or softball season, how will a
team finish, will it make the 64-team NCAA tournament (and as what seed), and how far
will it go?

**Status:** calibrated: tuned on 2015-2019 (softball 2017-2019) and backtested walk-forward
on 2021-2026 at three snapshot dates per season against benchmarks (data/backtest.csv,
summary below, details in RESEARCH.md). Caveats: only 6 independent test seasons per
sport, softball data gaps (below), 28 conference-seasons with carried-over formats.

## Inputs

| input | meaning | example |
|---|---|---|
| `sport` | `"baseball"` or `"softball"` | `"baseball"` |
| `season` | 2015-2019, 2021-2026 (2020 was cancelled; softball 2015-2016 have poor data) | `2026` |
| `as_of` | `"YYYY-MM-DD"` or `"selection"` (selection eve). Games before this date are results; the rest of the schedule is simulated. Dates after selection are moved back to selection eve (no in-tournament updating). | `"2026-05-01"` |
| `team` | team to report on (NCAA.com name or id, e.g. `"Georgia Tech"`, `"mississippi-st"`); optional | `"Georgia Tech"` |
| `top` | how many title contenders / bubble teams to list (default 8) | `8` |

All examples are **historical snapshots of real seasons** (the seasons are complete); the
"remaining schedule" is the one that was actually played.

## Output

The first (primary) outcome is **P(team makes the NCAA field)**. Then: automatic bid,
host, national seed, expected seed line, P(win regional), P(reach Omaha / Oklahoma City),
P(reach the finals), P(national title); projected final wins incl. postseason, regular-
season and conference wins (mean + 80% range), P(conference regular-season title, ties
count), P(conference tournament title), median RPI rank at selection, the rating; then
the **title contenders** and the **bubble** (teams with 15-85% bid chances that are not
likely automatic qualifiers). The last step says what actually happened. `extras.teams`
holds every team's probabilities (used by tests and the backtest).

## Method

### 1. Data (fetch.py → data/)
- **Games** (`games_<sport>.csv`, D-I vs D-I only): baseball from boydsworld.com season
  lists (complete; marks neutral sites) keyed to NCAA.com team ids by matching games on
  date and score; softball from the NCAA.com scoreboard (GraphQL `GetContests_web`, one
  request per day) for 2015-2022 and 2026, and from Warren Nolan team schedule pages for
  2023-2025 (NCAA.com lacks scores for most 2024 softball games). Columns: `season, date,
  game_type (R regular / C conference tournament / N NCAA), home, away, home_score,
  away_score, neutral, innings (extra/short innings when known), conf_game, round`.
- **Conference membership** (`teams_<sport>.csv`): Warren Nolan's season RPI tables
  (baseball 2021-2026, softball 2023-2025); other seasons start from the nearest such season
  and re-assign each team to the conference whose members it played most on weekends
  from March 1 (plurality of 9+ games, iterated). NCAA.com's own conference field is the
  *current* conference, so it is used only as a fallback.
- **Game types:** N = NCAA championship games. C = intra-conference games from the first
  day a team plays a different conference opponent than the day before (tournament
  pattern) within 21 days of selection, or a final title series. Check: the winner of
  each conference's last C game equals the recorded automatic qualifier in 273 of 314
  baseball conference-seasons (misses are mostly 'last game of the day' ordering and
  weather-shortened events).
- **NCAA fields** (`ncaa_tournaments.json`): baseball from `ncaa_history_baseball.json`
  (Wikipedia brackets: national seeds, hosts, regional seeds 1-4, automatic qualifiers,
  results); softball from NCAA.com championship rows (hosts and national seeds from the
  rows' seed field; regional seeds 2-4 unknown).
- **Conference tournament formats** (`conference_formats.json`): merged from the research
  notes in `data/format_research/` (each entry has a source URL and `verified` flag).
  Baseball 337 conference-seasons (322 verified, 15 carried from a neighbouring season),
  softball 350 (337 verified, 13 carried). A conference with no researched entry would get
  a 'DRAFT' carried/generic format (none needed at present).
- Coverage: built baseball records equal Warren Nolan's final D-I records exactly for
  93-100% of teams (2021-2026; all within 2 games for 98%+); softball 2023-2025 100%.
  Softball 2016-2022/2026 (NCAA.com) median 43-52 games per team; 2015 is unusable.
  Details in RESEARCH.md section 1 and `data/coverage.json`.

### 2. Team strength (ratings.py)
Weighted ridge regression on transformed run margins, solved by Gauss-Seidel (stdlib):

    T(m) = sign(m) * min(|m|, cap) ** power                    (margin_cap, margin_power)
    T(home - away) ~ r_home - r_away + H * (not neutral) [+ k * (m_home - m_away)]
    minimise  sum w_g (T - pred)^2 + ridge * sum (r_t - prior_t)^2 [+ midweek_ridge * sum (m_t - beta r_t)^2]

- `w_g = 0.5 ** (age / half_life_days)` (× `midweek_weight` for midweek games);
  `prior_t = prior_carry × last season's final rating` (centred; built 3 seasons deep).
- Midweek split (off by default): k = 1 for Mon-Thu games that are not part of a series
  (a Thursday game opening a Thu-Sat series is a weekend game); m_t is the team's midweek
  offset. Postseason games always use the weekend rating r_t.
- Win probability: formula `win_probability = logistic(scale * diff)`, diff = rating
  difference + home edge, scale = `<sport>_win_scale` fitted by maximum likelihood on
  walk-forward predictions of the development seasons.
- Tuned values (RESEARCH.md section 2): baseball cap 10, power 0.7, ridge 8, half-life 120
  days, prior carry 1.0; softball no cap, power 0.7, ridge 8, half-life 60, prior carry 1.0.
  **The weekend/midweek split did not help** (test log loss +0.0003 baseball, +0.0001
  softball; weekend games unchanged, postseason within ±0.0004), nor did down-weighting midweek
  games. Margin compression, ridge shrinkage and especially the preseason prior did help
  (baseball test log loss 0.6279 → 0.6181; softball 0.5694 → 0.5535).

### 3. Rest of the regular season (sim.py)
Each simulation draws every team's rating once: r_t + N(0, `rating_sd`), formula
`rating_sd = rating_uncertainty * resid_sd / sqrt(games + ridge)`. Every remaining
regular-season game is then played with `win_probability`.

### 4. Conference standings and tournaments
Standings by conference win % (head-to-head among tied teams, then a coin flip; ties for
first all count as regular-season champions). The top `teams` seeds play the conference's
format: `single_elim` (standard bracket; staggered byes when `byes` exceeds the bracket's
natural byes, e.g. SEC/ACC 16-team), `double_elim` (generic loss-count double
elimination; `byes` = seeds skipping a single-elimination opening round; `final` single
or if-necessary), `pods`/`pool_play` (snake-seeded groups, double elimination or round
robin, group winners to single elimination or a best-of-3 final), `series` (top two,
best of 3) or `none`. Tournament games are neutral (option `conf_tourney_home`). The
automatic bid goes to the champion, or to the regular-season champion where `auto_bid =
regular_season`. Tournaments that were complete before `as_of` keep their real champion
(baseball: the recorded automatic qualifier).

### 5. Selection, hosts, seeds
RPI (rpi.py) is recomputed from all D-I results in each simulation: `RPI = 0.25 WP + 0.50
OWP + 0.25 OOWP`; baseball WP weights road wins / home losses 1.3 and home wins / road
losses 0.7 (since 2013), softball unweighted. Ours matches Warren Nolan's final RPI ranks
within ~1-3 places on average in the top 64. Committee proxy:

    selection_score = -sel_rpi * ln(RPI rank) - sel_rating * ln(rating rank) + sel_wpct * win%
    host_score      = -host_rpi * ln(RPI rank) - host_rating * ln(rating rank) + host_wpct * win%

plus logistic noise × `committee_noise` per simulation. The `64 - #AQ` best selection
scores among non-automatic teams with D-I win % ≥ `min_at_large_win_pct` (and RPI top
200) are the at-large teams; the 16 best host scores in the field host and are the
national seeds (8 in baseball 2015-2017: the top 8); the rest of the field is ordered by
selection score into seed lines 2, 3, 4. Coefficients come from logistic fits on the
development seasons; adding our rating or win % did not improve out-of-sample fit, so the
defaults use RPI only (`sel_rating` etc. = 0; variant `rating_eye_test`).

### 6. Bracket
Regional k (host = national seed k) gets the k-th worst 2 seed, the k-th best 3 seed and
the k-th worst 4 seed (S-curve: 1 gets #32, #33, #64 overall); then teams are swapped
within a seed line so conference-mates are not in the same regional. **Geography is not
modelled** (the committee places most 2-4 seeds by travel). Regionals: 4-team double
elimination, host at home. Super regionals: winner of regional k vs regional 17-k, best of
3 at the higher national seed. World Series: bracket 1 = slots {1, 16, 8, 9, 4, 13, 5, 12},
bracket 2 = {2, 15, 7, 10, 3, 14, 6, 11}, each 4-team double elimination, bracket winners
play a best-of-3 final, all neutral (the WCWS crossover into the other side's losers'
bracket is not modelled). The same pairing is used for baseball 2015-2017, when only 8
teams were seeded and the unseeded regionals' pairings were set by the committee.

## Rules researched (sources in data files)

- **Baseball field:** 64 teams; 31 automatic bids 2015-2019 and 2022, 30 in 2021 (no Ivy),
  2023-2024 (MEAC dropped baseball), 29 in 2025-2026 (no Pac-12 bid). 16 four-team double-
  elimination regionals hosted by the top 16; 8 national seeds 2015-2017, 16 since 2018
  (NCAA, Oct 2017). Supers best of 3 (1 v 16 ... 8 v 9); MCWS two 4-team double-elimination
  brackets, best-of-3 finals. Selection criteria: RPI, D-I record, nonconference record/RPI,
  road record, quadrant results (from 2024), last-15, head-to-head, common opponents,
  regional advisory input; KPI added as a resource 2024, DSR on team sheets 2026.
  Conference-mates kept apart. Sources: NCAA 2024-25 and 2025-26 baseball pre-championship
  manuals, NCAA.com (2017-10-06), ABCA (2013 RPI change), Wikipedia tournament pages
  (`data/ncaa_history_baseball.json` `_sources`).
- **Softball field:** 64 teams (32 AQ + 32 at-large through 2024; 31 + 33 in 2025-2026),
  16 national seeds who host regionals (2026: first year seeds 17-32 were also placed),
  supers 1 v 16 ..., WCWS two 4-team double-elimination brackets with crossover,
  if-necessary bracket finals, best-of-3 championship series (unchanged 2015-2026). RPI
  25/50/25 with an unpublished bonus/penalty (top-50 wins / losses to 225+, top-75 / 227+
  from 2025-26); no site weighting. Sources: NCAA softball pre-championship manuals
  2018-19 ... 2025-26 and committee annual reports (`format_research/softball_other_conferences.json`
  `rules_notes`).
- **Conference tournaments:** every conference-season with its source in
  `conference_formats.json`. Notable: Pac-12 baseball had no tournament through 2021 (first
  in 2022); Big West baseball none 2015-2024; WCC softball none in the whole window;
  Mountain West softball none through 2022; Ivy title series; many 2021 COVID changes.
  Uncertain entries are `verified: false` (carried from a neighbouring season).

## Assumptions and known weaknesses

- Ratings are one number per team; pitching rotations, injuries and midseason form are
  not modelled. Data show no usable weekend/midweek difference beyond that number.
- The committee proxy is RPI order plus noise. Pure RPI order picks all but ~4 of ~34
  baseball at-large teams per year (24 misses in 205, 2021-2026) and all but ~2 in softball
  (14 in 198); real committees also use quadrants, head-to-head and the eye test.
  The NCAA's RPI bonus/penalty is not reproduced.
- Probabilities may be slightly overconfident: in the test seasons games were a little
  less predictable than in development (fitted win scale for weekend games 0.58 vs 0.63 in
  baseball, 0.74 vs 0.76 in softball). Baseball champions often come from deep in the
  field (2022 Ole Miss, 2026 Oklahoma had <1% title chances on selection eve).
- No geography in regional placement, so regional opponents (and hence advancement
  probabilities of 2-4 seeds) are approximate.
- Remaining schedules are the games actually played (cancellations known in hindsight);
  in-progress conference tournaments are simulated from scratch; ineligible
  (reclassifying) teams can win bids in the simulation.
- Softball: 2015-2016 data incomplete; 2016-2022 and 2026 rely on the NCAA scoreboard,
  which misses some conference-tournament games (listed with TBA opponents), so some
  softball conference tournaments are not detected and their completed champions are
  unknown at selection eve. Softball regional seeds 2-4 are unknown (no seed-line check).
- Sport-specific parameters are separate (`baseball_*`, `softball_*`); shared ones apply
  to both.
- Runtime: one simulation set per (sport, season, as_of, parameters) is cached in memory,
  so per-team runs and the backtest reuse it. ~3-5 s for 500 simulations.

## Variants

- `midweek_split` — per-team midweek offset on (both sports).
- `no_prior` — no preseason prior (much worse early in the season).
- `exact_ratings` — no rating-uncertainty draw.
- `rating_eye_test` — committee proxy also rewards our rating.

## Backtest data

`data/backtest.csv` (written by `python -m ballmonitor.models.college_diamond.research
backtest`): one row per sport, season, snapshot (`04-01`, `05-01`, `selection`) and D-I
team: `sport, season, snapshot, as_of, split (dev/test), team, conference,
rpi_rank_at_snapshot, made_field, host, stage_reached (0 no bid ... 5 champion), seed,
final_wins, final_losses, p_bid, p_host, p_title, proj_wins`. `ballmonitor backtest
college_diamond` re-runs the model for every row (one simulation per snapshot, cached) and
scores P(bid) (`brier`, `log_loss`), P(host) (`brier_host`), the 6-class stage
(`log_loss_stage`) and final wins (`abs_error`, `in_80`), grouped by sport/snapshot/split.
Results and benchmarks: RESEARCH.md section 4 (summarised below).

Test seasons 2021-2026 (6 per sport; every D-I team, ~300 per season-snapshot):

| sport | snapshot | P(bid) Brier: model / RPI-now / chalk / base | P(bid) log loss: model / RPI-now | P(host) Brier: model / RPI-now | stage log loss: model / RPI bucket | final wins MAE (80% cover) | seed-line MAE |
|---|---|---|---|---|---|---|---|
| baseball | 04-01 | 0.092 / 0.121 / 0.152 / 0.167 | 0.300 / 0.602 | 0.025 / 0.036 | 0.455 / 0.529 | 3.14 (0.82) | 0.436 |
| baseball | 05-01 | 0.078 / 0.098 / 0.136 / 0.167 | 0.257 / 0.486 | 0.020 / 0.023 | 0.406 / 0.485 | 1.93 (0.84) | 0.365 |
| baseball | selection | 0.018 / 0.080 / 0.106 / 0.167 | 0.059 / 0.393 | 0.013 / 0.013 | 0.207 / 0.426 | 0.31 (0.98) | 0.269 |
| softball | 04-01 | 0.068 / 0.090 / 0.105 / 0.166 | 0.228 / 0.440 | 0.011 / 0.019 | 0.337 / 0.457 | 2.42 (0.81) | - |
| softball | 05-01 | 0.059 / 0.080 / 0.096 / 0.166 | 0.197 / 0.396 | 0.007 / 0.008 | 0.304 / 0.428 | 1.34 (0.86) | - |
| softball | selection | 0.038 / 0.077 / 0.090 / 0.166 | 0.171 / 0.372 | 0.006 / 0.006 | 0.276 / 0.403 | 0.41 (0.96) | - |

- The model beats every benchmark at April 1 and May 1. On selection eve, against a
  benchmark that knows the automatic qualifiers (RPI logistic + AQ), it ties in baseball
  (Brier 0.018 vs 0.017, log loss 0.059 vs 0.056) and wins in softball (0.038 vs 0.051).
  Hosts on selection eve are no better than RPI order (the committee follows RPI).
- P(bid) is well calibrated in baseball (e.g. 0.29 predicted -> 0.28 observed, 0.88 ->
  0.87); softball's extremes are slightly off (0.99 -> 0.97, partly missing conference-
  tournament data on selection eve).
- Final-win 80% ranges cover 81-86% before selection; seed-line error ~0.3-0.4 lines.
- Benchmarks: RPI-now = RPI-only logistic models on the snapshot's RPI (ignores automatic
  bids, so it is weak for small-conference champions before selection); stage benchmark =
  dev-season stage frequencies by RPI bucket; chalk = rating-only deterministic field.
- Caveats: only 6 independent test seasons per sport; development seasons (in-sample for
  the tuned parts) are reported separately in RESEARCH.md and look similar.

## References

- NCAA D-I Baseball and Softball Pre-Championship Manuals (ncaaorg.s3.amazonaws.com), 2018-19 to 2025-26.
- Wikipedia: "<year> NCAA Division I baseball tournament", "<year> ... softball tournament", conference tournament pages (per-entry URLs in the data files).
- NCAA.com scoreboard; boydsworld.com college baseball scores; WarrenNolan.com RPI and schedules.
- Massey (1997) / SRS least-squares ratings; NCAA RPI documentation (ABCA 2013).

## Changelog

- 0.1.0 — initial version: data pipeline, strength study, committee proxy, season and
  postseason simulation, backtest.
