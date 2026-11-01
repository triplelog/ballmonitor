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

Everything else (simulation count, seed, all weights) is a parameter — see
`ballmonitor params ncaaf_bowls`.

## Method

1. **Rest-of-season Monte Carlo** (`simulations` runs, `random.Random(random_seed)`).
   Each listed remaining game is decided with config formula **`win_probability`**:
   `normal_cdf((rating_diff + home * home_field_points) / margin_sd)`, where
   `home` is +1 / 0 / −1. The same formula decides title, CFP and bowl games.
2. **FCS opponents** are all rated `fcs_opponent_rating` (default: the pooled FCS rating
   from the results-only fit, −21.7). Ratings come from `ratings_source` (`fpi` or `results`).
3. **Conference title games** for all ten conferences (incl. the 2026 Pac-12): top two by conference win
   %, conference wins, overall win %, then rating; two-way head-to-head tiebreak.
4. **CFP resume score** (committee proxy):
   `resume_win_pct_weight·win% − resume_loss_penalty_scale·losses^resume_loss_penalty_exponent
   + resume_power_weight·rating + resume_conf_champ_bonus·[champ] + resume_p4_champ_bonus·[P4 champ]
   + resume_power4_bonus·[P4 or Notre Dame]`.
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

- One fixed rating per team for the whole run; no injuries or in-season updating after
  the snapshot. Re-fetch to update.
- The committee ranking is a hand-weighted resume score (DRAFT weights). Compared with
  ESPN's own FPI simulation it under-rates multi-loss SEC teams (e.g. Texas, Kentucky,
  Ole Miss) — see Validation.
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

ESPN publishes its own FPI-based season simulation. Run with the same FPI ratings and
3,000 simulations, this model's per-team figures across all 138 teams differ from ESPN's
by (mean absolute difference): projected wins **0.035**, conference-title probability
**1.1 pts**, P(6+ wins) **0.7 pts**, CFP probability **3.1 pts** (the CFP gap comes from
the committee proxy, the others confirm the schedule, records and simulation). This is a
consistency check, not a test of predictive accuracy.

## Variants

None yet. Try e.g. `--set margin_sd=16` or
`--set 'formulas.win_probability=normal_cdf(rating_diff / margin_sd)'` (no home field).

## Backtest

There is no `data/backtest.csv`, so `ballmonitor backtest ncaaf_bowls` is unavailable and
the model is `draft`. A standalone check exists: `python cli.py backtest 2023` (or
`Backtester(2023)`) runs the engine on a week-11 2023 snapshot of 44 teams
(`data/historical/2023/`) and scores the actual bowl of 42 of them. With 500 sims
(v0.4.0, 2024-25 bowl lineup in `data/historical/bowls_2024_lineup.json`): top-1 26.2%,
top-3 52.4%, top-5 71.4%, multinomial Brier 0.989 (v0.3.0: 23.8% / 54.8% / 76.2%, 0.997).
Caveats: one season and a small team subset (not independent evidence); it applies the
2026 12-team CFP rules and the 2024-25 tie-ins to 2023 (which used a 4-team CFP), so
NY6/CFP slots are structurally mis-specified; selection weights were tuned on data that
includes 2023. A future `backtest.csv` would need one row per team-season with the
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
