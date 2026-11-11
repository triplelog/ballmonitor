# NCAAF Bowl & Playoff Simulator (`ncaaf_bowls`)

**Question:** For each FBS team, what are the chances of bowl eligibility, a 12-team
CFP berth, and specific postseason bowl destinations?

> **Data.** Current season, from ESPN's public APIs via `ballmonitor fetch ncaaf_bowls`
> (`fetch.py`). The snapshot time, season and counts are in `data/meta.json` and printed
> with every run. Rebuild before using the model; games after the snapshot are simulated.

## Data

| file | contents | source |
|---|---|---|
| `teams.json` | 138 FBS teams: 2026 conference, record and conference record to date, rating (FPI), last season's bowl, legacy-Pac-12 flag, location/brand/APR | ESPN conferences, scoreboard, FPI; `team_profiles.csv` |
| `schedule.json` | **every** remaining regular-season game of every FBS team, incl. FCS opponents (`fcs_*`) and Army–Navy; conference title games excluded (simulated) | ESPN scoreboard, weeks 1–15 |
| `results.json` | every completed game with scores (records in `teams.json` are built from these and match ESPN's team records exactly) | ESPN scoreboard |
| `ratings_fpi.csv` | ESPN Football Power Index: expected margin vs an average FBS team, neutral field | ESPN `powerindex` |
| `ratings_results.csv` | results-only rating: ridge least squares on this season's margins (capped at `rating_margin_cap`, shrinkage `rating_ridge`, home field `home_field_points`); FCS teams pooled | built by `fetch.py` |
| `bowls.json` | 2026-27 lineup: 6 CFP bowls (quarterfinals Fiesta, Cotton, Peach, Rose; semifinals Orange, Sugar) and 35 FBS bowls with their tie-in slots; each bowl cites its `source` | see References |
| `team_profiles.csv` | hand-maintained campus city/state/lat/lon, brand (1–10, judgement) and APR | carried from the previous data; the four 2026 FBS newcomers added with real campus coordinates |
| `meta.json` | season, snapshot time, sources, counts, pooled FCS rating | `fetch.py` |

Every team has 12 regular-season games (San José State 13 — Hawai'i trip exemption).
The 2026 Pac-12 ends with a **flex week**: ESPN lists "TBD" opponents until six days
before, so `fetch.py` uses the league's published projected pairings (Boise State at Utah
State, Oregon State at Washington State, San Diego State at Fresno State, Texas State at
Colorado State; non-conference games) and marks them `flex_projected`.

**APR values are unverified** (carried from the old data; blank → 980 for the newcomers);
they only break ties among 5–7 teams when there aren't enough 6-win teams.

## Inputs

| input | meaning | example |
|---|---|---|
| `team` | FBS team name or id from `data/teams.json` (case-insensitive). Unknown names raise an error. | `"Ohio State"`, `"boise_state"` |

| `home_rating`, `away_rating`, `site` | single-game mode instead of `team`: two ratings and `site` = `home` or `neutral` (optional `home`, `away` names) → the `win_probability` formula alone. This is what `data/backtest.csv` scores. | `10.6`, `4.5`, `"home"` |

Everything else (simulation count, seed, all weights) is a parameter — see
`ballmonitor params ncaaf_bowls`.

## Method

1. **Rest-of-season Monte Carlo** (`simulations` runs, `random.Random(random_seed)`).
   Each listed remaining game is decided with config formula **`win_probability`**:
   `normal_cdf((rating_diff + home * home_field_points) / margin_sd)`, where
   `home` is +1 / 0 / −1. The same formula decides title, CFP and bowl games.
   **Rating uncertainty:** at the start of each simulated season every team's rating gets
   its own error drawn from Normal(0, `rating_uncertainty_points`), kept for all its games
   that season (regular season, title game, playoff, bowl). Inside the simulation the
   formula's `margin_sd` is replaced by config formula **`simulated_game_sd`**
   (`sqrt(margin_sd² − 2·rating_uncertainty_points²)`), so a single game seen from the
   published ratings still has SD `margin_sd`. The committee, tie-breaks and bowl picks use
   the published rating.
2. **FCS opponents** are all rated `fcs_opponent_rating` (default: the pooled FCS rating
   from the results-only fit, −21.7). Ratings come from `ratings_source` (`fpi` or `results`).
3. **Conference title games** for all ten conferences (incl. the 2026 Pac-12): top two by conference win
   %, conference wins, overall win %, then rating; two-way head-to-head tiebreak.
4. **CFP resume score** (committee proxy):
   `resume_win_pct_weight·win% − resume_loss_penalty_scale·losses^resume_loss_penalty_exponent
   + resume_power_weight·rating + resume_conf_champ_bonus·[champ] + resume_p4_champ_bonus·[P4 champ]
   + resume_power4_bonus·[P4 or Notre Dame] + resume_noise_points·Gumbel noise`.
   The weights are a Plackett-Luce fit to the committee's final top 25 of 2016-2025; the
   noise is the committee's unpredictability under that fit (RESEARCH.md part 3).
5. **12-team CFP (2026-27 protocol).** Automatic bids for the ACC, Big Ten, Big 12 and
   SEC champions and the highest-ranked champion of the American, CUSA, MAC, Mountain
   West, Pac-12 and Sun Belt; seven at-large bids. **Straight seeding** by the resume
   ranking — the top four get byes whether or not they won a title. First round on campus
   (5v12, 6v11, 7v10, 8v9); seeds 1–4 are placed in seed order in the nearest remaining
   quarterfinal bowl (Fiesta, Cotton, Peach, Rose); semifinals Orange (1/8/9 vs 4/5/12
   side) and Sugar; final.
6. **Bowl selection** (`selection.py`, driven by the slots in `bowls.json`). Teams with ≥
   `bowl_eligible_wins` (then teams one win short, by APR, if slots remain) fill:
   (a) contracted single-conference slots, conference by conference (power conferences
   first) in each conference's pick `order`; (b) pooled slots shared by several
   conferences, in bowl-prestige order; (c) any slot still open, from all remaining teams.
   Rules: Notre Dame may take ACC slots (`notre_dame_acc_win_tolerance`); Big Ten slots use
   `big_ten_max_conf_win_skip` and anti-repeat; SEC slots anti-repeat; under the 2026
   **Pac-12 legacy agreement** the 12 pre-2024 Pac-12 schools fill the "Pac-12 legacy"
   slots (Alamo, Las Vegas, Holiday, Sun, Poinsettia, Independence) and not their current
   conference's, while the new Pac-12 members have the Poinsettia (champion) and Hawai'i
   slots plus the Group-of-6 pools. Bowls pick by a utility of
   wins, rating, brand, proximity, drive-in bonus, repeat and rematch penalties (`bowl_*`
   params) plus Gumbel noise scaled by `bowl_temperature`.
7. **Aggregation.** Per team: CFP / bye / conference title / title / eligibility /
   postseason-win probabilities, mean record (includes the title game when played), and
   bowl appearance probabilities. A CFP team can appear in a quarterfinal *and* a
   semifinal bowl, so bowl appearance probabilities are **not mutually exclusive**.

## Assumptions & known weaknesses

- A team's rating is the snapshot's, off by one drawn error per simulated season; ratings
  do not learn from simulated results, and there are no injuries. Re-fetch to update.
- The committee ranking is a fitted resume score with no head-to-head, schedule-strength or
  "eye test" terms. It matches the committee's final top 12 better than the 0.4.3 weights
  (RESEARCH.md part 3) but did **not** give better playoff-field odds in the two 12-team
  seasons (part 4); ESPN's own published odds scored better than this model in both.
- **Bowls and playoff games are predicted worse than regular-season games**: in
  `data/backtest.csv` the favourite won 60% of 400 postseason games against 73% in the
  regular season (opt-outs, coaching changes, a month off). "Wins it" figures for bowls are
  therefore overconfident; no postseason discount is modelled yet.
- Not validated: which bowl a team goes to, and seeding.
- Bowl pick orders beyond the published tie-ins are approximations: within a conference,
  slots without a known `order` go by bowl prestige; several 2026 second slots
  ("ESPN Group-of-6 pool") and the Xbox Bowl are flagged in their `source` as DRAFT /
  approximation. Bowl `prestige` and `payout` are judgement / unverified.
- A few constants remain inline in `selection.py` (regional affinity bonuses of 4–5
  utility points for specific bowls/states, the brand factor `0.8 + 0.04·prestige`,
  the ×10 proximity scale and ×2 Gumbel scale).
- Brand, repeat and drive-in weights were tuned on 2014–2023 bowl history, which
  includes the 2023 backtest season (in-sample).
- Season rollover is manual: set `"season"` in `data/meta.json`, then fetch (bowls.json
  and the CFP rules must be reviewed each year).

## Validation against ESPN (2026-10-26 snapshot)

_Measured with the 0.4.3 parameters; not rerun for 0.5.0 (the committee weights changed)._

ESPN publishes its own FPI-based season simulation. Run with the same FPI ratings and
3,000 simulations, this model's per-team figures across all 138 teams differ from ESPN's
by (mean absolute difference): projected wins **0.035**, conference-title probability
**1.1 pts**, P(6+ wins) **0.7 pts**, CFP probability **3.1 pts** (the CFP gap comes from
the committee proxy, the others confirm the schedule, records and simulation). This is a
consistency check, not a test of predictive accuracy.

## Variants

- `fixed_ratings`: no rating uncertainty (every game independent, as in 0.4.3).
- `committee_v043`: the hand-set committee weights of 0.4.3, no committee noise.

`ballmonitor run ncaaf_bowls --variant committee_v043 --example ohio_state` (`compare` stops
when two runs list different bowls for the team; `compare --backtest` works). Also try
`--set margin_sd=16` or `--set 'formulas.win_probability=normal_cdf(rating_diff / margin_sd)'`
(no home field).

## Backtest

Status stays `draft`: the single-game engine, the spread of season records and the committee
ranking are now tested on real seasons, but the headline playoff odds were only checked on two
seasons (no gain shown) and bowl destinations not at all. Full tables: **RESEARCH.md**
(generated by `research.py` from ESPN data 2016-2025, `research_data.py`; walk-forward).

**`data/backtest.csv`** (`ballmonitor backtest ncaaf_bowls`): 6,699 games between two
FBS teams, 10 seasons 2016-2025, week 3 on, with the FPI ESPN published before the game.
Columns: `season`, `week`, `kind` (regular season / title game / postseason; reported as
groups), `home`, `away`, `home_rating`, `away_rating` (FPI after the previous week), `site`
(`home` / `neutral`), `winner` (`home` / `away`). It scores the `win_probability` formula
(single-game mode). Defaults (home field 2.5, SD 14): Brier 0.1806 per game (the CLI
prints the two-outcome sum, twice that), log loss 0.5348, favourite won
72.2%; well calibrated in every probability band.

| what was tested (RESEARCH.md part) | sample | result | decision |
|---|---|---|---|
| home field and margin SD (1) | 6,699 games, 10 seasons; walk-forward on 7 | refit (2.1-2.5, 14.2-15.0) beats 2.5 / 14 in 4 of 7 seasons, by < 0.002 log loss | kept 2.5 / 14 |
| results-only rating, FPI blends (1) | 5,826 games, 10 seasons | 15% results share: log loss −0.0002, better in 6 of 10 seasons; more is worse | kept FPI alone |
| margin SD growing with weeks ahead (1) | same games from older ratings | from week 8 on the best SD is 14.5-15.1 at 1-4 weeks ahead | not added |
| rating uncertainty (2) | 12,992 team-dates, 9 seasons; walk-forward on 6 | squared miss of remaining wins was 1.39x the predicted spread, now ~1.0x; log score better in 6 of 6 test seasons | **promoted, 5 points** |
| committee weights (3) | final top 25, 10 seasons; walk-forward on 7 | committee top-12 teams matched: 77 of 84 (0.4.3: 66), at least as good every season | **promoted** |
| committee noise (3) | same; nested walk-forward on 5 | squared error of top-12 membership 8.0 → 7.4, top-4 10.0 → 6.5; better in 3 of 5 seasons | **promoted, 3.7** (modest) |
| all of it inside the season simulator (4) | 2024 and 2025, 4 dates each | playoff field squared error 39.00 → 39.14 (rating uncertainty alone 38.79), log loss 134.6 → 130.8; conference champions 59.77 → 58.74; ESPN 37.26 / 58.04 | no end-to-end gain shown for the weights |

**Older bowl-destination check** (before 0.5.0, not rerun). A standalone check exists: `python cli.py backtest 2023` (or
`Backtester(2023)`) runs the engine on a week-11 2023 snapshot of 44 teams
(`data/historical/2023/`) and scores the actual bowl of 42 of them. With 500 sims
(v0.4.0, 2024-25 bowl lineup in `data/historical/bowls_2024_lineup.json`): top-1 26.2%,
top-3 52.4%, top-5 71.4%, multinomial Brier 0.989 (v0.3.0: 23.8% / 54.8% / 76.2%, 0.997).
Caveats: one season and a small team subset (not independent evidence); it applies the
2026 12-team CFP rules and the 2024-25 tie-ins to 2023 (which used a 4-team CFP), so
NY6/CFP slots are structurally mis-specified; selection weights were tuned on data that
includes 2023. A bowl-destination backtest would need one row per team-season with the
pre-bowl snapshot inputs and the actual bowl id.

## CLI usage (standalone)

From `ballmonitor/models/ncaaf_bowls/`: `python cli.py team Texas`, `python cli.py cfp`,
`python cli.py team Michigan --win-out`, `python cli.py backtest 2023`. See `BOWLS.md`.

## References

- ESPN APIs: site.api.espn.com (scoreboard, teams) and sports.core.api.espn.com
  (conferences, powerindex/FPI).
- CFP 2026-27 format and bowl rotation: collegefootballplayoff.com, "CFP Selection
  Committee Prepares for 2026-27 Season" (2026-08-06); National Football Post,
  "CFP Format 2026-27" (2026-10-23).
- 2026-27 bowl tie-ins (2025 affiliations retained): Yahoo Sports / FanSided, "College
  football bowl tie-ins for 2026-27…"; Pac-12 legacy order and new-member bowls: Press
  Democrat (2026-08-16); Cactus Bowl: azfamily.com (2026-06-03); GameAbove Sports Bowl
  cancelled: clickondetroit.com (2026-02-10); Puerto Rico Bowl: Wikipedia.
- Pac-12 2026 flex week: pac-12.com (2026-02-09).
- NCAA FBS bowl eligibility rules (6 wins; APR for 5–7 teams).
- Conference bowl agreements (Big Ten, SEC, ACC/Notre Dame, Big 12) — DRAFT, verify.

## Changelog

- 0.5.0 (site) — "Who to root for this week" on every team's page and "This week's biggest games" on
  the main page (`site.py`). `BowlEngine.run(track_games=...)` tallies, for each of the next week's
  FBS games (`site.this_week`), the home team's wins and each team's playoff bids and conference titles
  in those seasons (`GameTally`); a team's chance if each side wins is read from the same simulated
  seasons. A team's table uses its playoff chance (its conference-title chance when the playoff is out
  of reach, `site_root_min_chance`); someone else's game is listed only if it moves that chance by
  `site_root_min_swing` and by `site_root_z` = 3.5 standard errors of the simulation (about 8,000
  team-game pairs are checked a week). `site_simulations` 5,000 → 20,000 so smaller swings clear the
  noise (page build about 33 s). Conference championship games are not in the schedule (they are
  simulated), so championship week has no tracked games yet. Model defaults unchanged.
- 0.5.0 — **First accuracy study on real past seasons** (RESEARCH.md; ESPN 2016-2025).
  New `rating_uncertainty_points` = 5 (was effectively 0) with formula `simulated_game_sd`:
  each simulated season draws one rating error per team, which widens the range of records
  to match what happened. Committee weights refitted to the real final rankings:
  `resume_win_pct_weight` 65 → 67, `resume_loss_penalty_scale` 3.5 → 1.4,
  `resume_conf_champ_bonus` 8 → 0, `resume_p4_champ_bonus` 3 → 4.5, `resume_power4_bonus`
  4 → 14; new `resume_noise_points` = 3.7. `home_field_points` and `margin_sd` tested and
  kept. Added `data/backtest.csv` (6,699 games), single-game mode, `backtest_case`,
  variants `fixed_ratings` and `committee_v043`, `research.py` / `research_data.py`.
  Multi-loss power-conference teams move up, unbeaten or one-loss Group-of-6 teams down.

- 0.4.3 — Site page: a headline, a one-line answer on each team page, a playoff bubble watch
  (`site_bubble_cuts`) and a projected 12-team bracket (the 12 likeliest playoff teams by
  expected seed, favorites advancing, win chances from `win_probability`). No change to predictions.
- 0.4.2 — The engine also tallies how far each team gets in the playoff (quarterfinal,
  semifinal, final) and its distribution of records before the bowls, incl. any conference
  title game (`TeamSummary.p_cfp_*`, `record_dist`), for the site's team pages; the site adds a page per team and per bowl. No
  change to predictions.
- 0.4.1 — `site.py`: the public page (every FBS team's playoff, title and bowl odds, title
  chances, bowl matchups) from one `site_simulations` run of `engine()`, the season engine
  now shared by `predict()`. No change to predictions.
- 0.4.0 — **Real current-season data.** New `fetch.py` builds teams, the complete
  remaining schedule (incl. FCS opponents and the Pac-12 flex week), results and ratings
  from ESPN; records match ESPN exactly. Default ratings are ESPN FPI (`ratings_source`),
  with a results-only alternative; removed the synthetic SP+/Elo files and the 2024
  snapshot builders. Removed schedule padding (`regular_season_games`,
  `filler_opponent_rating`); added `fcs_opponent_rating`, `rating_margin_cap`,
  `rating_ridge`. CFP updated to the 2026 protocol (straight seeding, P4 champions + best
  Group-of-6 champion, 2026 bowl rotation). `bowls.json` rebuilt for 2026-27 (35 FBS
  bowls; LA and GameAbove bowls gone; Poinsettia, Puerto Rico, Cactus added) with
  data-driven tie-in slots, and `selection.py` rewritten to fill them (incl. the 2026
  Pac-12 legacy agreement). The 2023 backtest now uses its own bowl lineup and rebuilds
  every engine component from the historical data.

- 0.3.0 — Config formula `win_probability` now drives every game (was only printed);
  all `SimConfig` weights exposed as params; added schedule padding
  (`regular_season_games`, `filler_opponent_rating`) because the sample schedule left
  most teams with 8–11 games; unknown teams raise instead of silently using Georgia;
  `simulations` comes only from the param (examples no longer override it, removed the
  hidden 2000 cap); status `calibrated` → `draft` (no backtest.csv); documented the 2024
  data vintage and synthetic alternative ratings; removed unused `fcs_wins_allowed`.
- 0.2.0 — Initial ballmonitor integration.
