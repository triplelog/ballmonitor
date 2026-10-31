# DAD (Deviations Above Default) (`dad`)

**Question:** How many per-game standard deviations better than a chosen default team (bubble, champion, average, replacement) is a team, and how many wins above that default did its schedule produce?

**Status:** calibrated (v0.7.0) — the primary output (DAD per game, a strength measure) is tested walk-forward on ~187k real games in [RESEARCH_STRENGTH.md](RESEARCH_STRENGTH.md) and backtested on `data/backtest.csv` (summary below). College baseball and softball constants are untested judgement values.

## In one paragraph

DAD v0.6.0 answered two different questions with one number. v0.7.0 separates them:

* **Strength — "how good is this team?"** (primary, predictive). Each game says something about the team's rating: *adjusted performance* = margin + opponent rating − home edge. Average those, pull the average toward the league mean with a few phantom games against an average team (`prior_games_*`), and you have the **strength rating** (points/goals/runs per game against an average team, neutral field). Compare it with the default team: **strength vs default** = rating − default's rating; **DAD per game** = that gap divided by σ, the per-game margin SD ("the team is 1.4 game-to-game standard deviations better than a bubble team"); **win chance vs default** = how often it would beat the default team on a neutral field.
* **Résumé — "what did it accomplish?"** (descriptive). **Total DAD** = Σ over games of (margin − default team's expected spread) / σ: how far beyond the default team's expected result each game went, added up. **WAD** (wins above default) = Σ (result − chance the default team would have won that game), with win = 1, draw = ½, loss = 0 — "wins above bubble".

The v0.6.0 probit DAD is still available: variant `v06_probit` (`dad_scale = "probit"`, `wad_mode = "strength"`).

## Inputs

| input | meaning | example |
|---|---|---|
| `team` | Name of the primary team to evaluate | `"Arsenal"`, `"Everton"`, `"Houston"`, `"Los Angeles Dodgers"`, `"Tennessee Volunteers"` |
| `sport` | `basketball` (aliases mbb, ncaab, cbb, nba), `wbb` (ncaaw), `football` (cfb, ncaaf, nfl), `soccer` (epl, ucl, laliga, seriea, bundesliga, mls), `mlb` (baseball), `college_baseball` (ncaa_baseball), `softball` (college_softball). Anything else (e.g. hockey) is rejected. | `"soccer"`, `"epl"`, `"basketball"` |
| `baseline` | Preset (`bubble`, `champion`, `top_4_seed`, `average`, `replacement`; soccer also `europa`) or a custom rating number. Aliases such as `top4`, `ucl`, `national_seed`, `division_champ`, `wildcard`, `relegation_bubble`, `omaha` work in every sport; unknown names are an error. Default: param `default_baseline`. | `"champion"`, `"top4"`, `"relegation_bubble"`, or `0.85` |
| `games` | List of game dicts with `{opponent, opponent_rating, margin, location, ...}` | See `examples/soccer_arsenal_2024.toml`, `examples/soccer_everton_relegation_2024.toml` |
| `as_of` | Optional `YYYY-MM-DD` reference date for recency weights (default: latest game date). Only matters when a `half_life_days_*` param is above 0. | `"2025-02-01"` |
| `teams` | Optional multi-team mode: list of `{name, games}` to rank a whole conference or league | See `examples/multi_team.toml`, `examples/mlb_al_east_race.toml` |

Each game in `games` accepts:
* `opponent`: opponent name (string)
* `opponent_rating`: opponent net efficiency or power rating (float, e.g. net goals/match in soccer, net points in basketball, net runs/game in baseball)
* `opponent_rating` is required; `margin` (or `team_score` + `opponent_score`) is required.
* `margin`: actual margin of victory (+2 for a 2-goal win, 0 for a draw, -1 for a 1-goal loss). Alternatively, provide `team_score` and `opponent_score`.
* `location`: `"home"`, `"away"` (or `"road"`), or `"neutral"` (default neutral)
* `weight`: optional explicit game weight (overrides auto-detection)
* `xg_for` / `xg_against`: optional expected goals generated and conceded (e.g. `2.45` vs `0.80`). Alternatively `xg_margin` / `xgd`. When provided, DAD also computes **xDAD** (Total DAD with the xG margin in place of the goal margin) and **Finishing/Goalkeeping Luck** = Total DAD − xDAD.
* `date`: optional calendar date string (`YYYY-MM-DD`) for automatic detection of weekend series, midweek games, and tournaments, and for recency weights
* `notes`: optional text context for tournament keywords (e.g. `"UEFA Champions League"`, `"North London Derby"`)

## Method

All formulas are in `config.toml` (`ballmonitor params dad`).

1. **Default team's rating** $R_{\text{default}}$ from the chosen preset or a number (same scale as the opponent ratings):
   * **Professional Soccer (EPL / La Liga / UCL):**
     * Title Contender Standard (`"champion"`): $+1.53$ net goals/match ($\approx 86\text{–}90$ pts).
     * Champions League Top-4 Cutline (`"top4"` / `"ucl"`): $+0.58$ net goals/match ($\approx 68\text{–}72$ pts).
     * European Places Cutline (`"europa"`): $+0.31$ net goals/match ($\approx 60\text{–}63$ pts).
     * Mid-Table 10th Place Median (`"average"` / `"midtable"`): $0.00$ net goals/match ($\approx 48\text{–}50$ pts).
     * Relegation Survival Bubble (`"relegation_bubble"` / `"bubble"`): $-0.63$ net goals/match ($\approx 35\text{–}37$ pts 17th place safety line).
     * Replacement Level Promoted Club (`"replacement"`): $-1.13$ net goals/match ($\approx 18\text{–}22$ pts).
   * All presets except college baseball/softball are the **median full-season least-squares rating of the team at a fixed rank** (RESEARCH.md, "Baseline presets implied by the data"), on the same scale as `data/team_ratings.csv`:
   * **Men's Basketball:** Bubble #45 (+11.8), 4-Seed #16 (+16.8), Champion #2 (+23.9), Average (0.0), Replacement #300 (-9.3 pts/game).
   * **Football (FBS):** 12-team-playoff Bubble #12 (+20.4), Top-4 #4 (+28.6), Champion #2 (+30.7), Average (0.0), Replacement #120 (-16.3). NFL ratings are on a narrower scale — pass a numeric `baseline` for NFL.
   * **Women's Basketball (WBB):** Bubble #45 (+15.9), 4-Seed #16 (+23.6), Champion #2 (+39.7), Average (0.0), Replacement #300 (-13.4 pts/game).
   * **MLB Baseball:** Wild Card Bubble #12 (+0.25), Division Champion #6 (+0.68), World Series Champion #2 (+1.27), Average (0.0), Replacement #30 (-1.08 runs/game).
   * **Soccer (Big-5 pooled):** Champion #1 (+1.53), Top-4 #4 (+0.58), Europa #6 (+0.31), Average (0.0), Relegation bubble #17 (-0.63), Replacement #20 (-1.13 goals/match).
   * **College baseball / softball:** unchanged judgement values (no complete public game data to estimate them).
   * **College Baseball:** NCAA Regional Bubble (+1.20), National Seed (+3.50), Omaha Champion (+5.00), Average (0.0), Replacement (-2.50 runs/game).
   * **College Softball:** NCAA Regional Bubble (+1.40), National Seed (+3.60), WCWS Champion (+5.80), Average (0.0), Replacement (-2.80 runs/game).
2. **Default team's expected spread** in each game (formula `expected_spread`): $s_i = R_{\text{default}} - R_{\text{opp},i} + \text{HCA}_i$ (HCA = + home edge at home, − away, 0 neutral).
3. **Game performance** (formula `game_performance`): the margin $m_i$, with an optional cap `margin_cap_sd`·σ and win bonus `win_bonus_sd`·σ (both off: the study found neither helps).
4. **Game DAD** (formula `game_dad`): $\text{DAD}_i = w_i\,(m_i - s_i)/\sigma$, i.e. how many per-game margin SDs the game beat what the default team would be expected to do there. σ per sport: `basketball_margin_sd` 10.6, `wbb_margin_sd` 11.2, `football_margin_sd` 13.8, `soccer_margin_sd` 1.6, `mlb_margin_sd` 4.4 (college baseball 6.0 and softball 5.0 are DRAFT). $w_i$ = game weight (step 8).
5. **Strength rating** (formulas `recency_weight`, `strength_rating`): adjusted performance $a_i = m_i + R_{\text{opp},i} - \text{HCA}_i$; $S = \sum r_i a_i / (\sum r_i + k)$ with $k$ = `prior_games_<family>` (basketball 1, football 2, MLB 32, soccer 4, college baseball 6, softball 3) phantom games against an average (0-rated) team, and recency weight $r_i = 0.5^{\text{days ago}/h}$ (`half_life_days_<family>`; 0 = off, the default). Stakes weights do not enter $S$.
6. **DAD per game** (primary, formula `strength_dad`): $(S - R_{\text{default}})/\sigma$. Also reported: **strength vs default** $S - R_{\text{default}}$ in points/goals/runs, and **win chance vs default** = P(win) + ½P(draw) for a team favoured by that much on a neutral field (normal CDF Φ(Δ/σ) in basketball/football, Skellam in soccer, Pythagorean in baseball/softball).
7. **WAD** (formula `game_wad`): $w_i\,(\text{result}_i - p_i)$, result = 1 / `soccer_draw_point_value` / 0, $p_i$ = chance the default team wins game $i$ (+ ½ draw) given $s_i$, from the same win-chance functions. Summed = wins above default.
8. **Game weights** (résumé only), auto-detected by [`matchups.py`](matchups.py): soccer European cups 1.35, derbies 1.20, domestic cups 1.10; college baseball/softball postseason 1.50, conference 1.30, weekend 1.25, midweek 0.75; MLB in-division 1.15; or an explicit `weight`.
9. **Totals**: Total DAD = Σ DAD_i, Total WAD = Σ WAD_i. xDAD uses the xG margin in step 4; `xg_blend` mixes the xG margin into the scored margin.
10. **Multi-team mode** ranks teams by DAD per game (strength); `v06_probit` ranks by total probit DAD as before.

**Legacy scale (`dad_scale = "probit"`, variant `v06_probit`).** Game DAD = $w\,\text{clamp}\big((P_{\text{actual}} - P_{\text{default}})/\sqrt{P_{\text{default}}(1-P_{\text{default}})}, \pm\texttt{game\_dad\_cap}\big)$ (formula `game_dad_probit`), where $P$ maps a margin or spread to "win strength" (normal CDF with key-number steps in football, Skellam in soccer, Pythagorean in baseball); primary output = the total. With `wad_mode = "strength"`, WAD = $w(P_{\text{actual}} - P_{\text{default}})$ (formula `game_wad_strength`).

## Parameters

See `config.toml` or `ballmonitor params dad`. Main knobs: `dad_scale`, `wad_mode`, `default_baseline`, `prior_games_*`, `half_life_days_*`, `margin_cap_sd`, `win_bonus_sd`, the per-sport σ (`*_margin_sd`), home edges, baseline presets, game weights; probit scale only: `game_dad_cap`, `football_key_number_bump`, `min_prob_clamp`/`max_prob_clamp` (also bound win chances).

## Data & Fetching

`ballmonitor fetch dad` (stdlib only, network) downloads real results and rebuilds:

* `data/games_<league>.csv` — one row per game: `league, season, date (UTC), season_type (2 regular, 3 postseason), home, away, home_score, away_score, neutral`. Leagues: `mbb`, `wbb` (NCAA D-I, 2015-16 to 2025-26), `nba` (2016–2019, 2022–2026), `cfb` (FBS-vs-FBS, 2015–2025 excl. 2020), `nfl` (2015–2025), `mlb` (2015–2026 excl. 2020) from ESPN's public scoreboard API (`site.api.espn.com/apis/site/v2/sports/<path>/scoreboard?dates=YYYYMMDD`); `epl`, `laliga`, `bundesliga`, `seriea`, `ligue1` (2015-16 to 2025-26) from football-data.co.uk. Season = year a basketball/soccer season ends, or a football/MLB season starts. College files keep only games between teams with ≥15 (basketball) / ≥8 (FBS) games, which drops non-D-I / FCS opponents.
* `data/backtest.csv` — not built by fetch: written by `python -m ballmonitor.models.dad.research_strength` from the games files (see Backtest below).
* `data/team_ratings.csv` — end-of-regular-season least-squares margin ratings (`ratings.py`) per league-season, plus record and raw margin. Use these as `opponent_rating`. They are hindsight values: fine for describing a finished season, not for forecasting.
* `examples/*.toml` except the college baseball / softball ones are **generated from this data** (real schedules, scores, venues; opponent ratings from `team_ratings.csv`).
* Raw per-day caches live in `data/raw/` (gitignored). `--offline` rebuilds from the cache, or only verifies the built CSVs if there is no cache.

College baseball and softball are not fetched: ESPN's scoreboards carry only part of D-I. Their examples remain **placeholders** and their constants remain judgement values.

## Evaluation

### Strength: which per-game measure? ([RESEARCH_STRENGTH.md](RESEARCH_STRENGTH.md))

`python -m ballmonitor.models.dad.research_strength` (needs numpy: `pip install -e '.[data]'`; research only, the model is stdlib). Every candidate per-game measure was put inside the same opponent-adjusted least-squares rating: raw margin, capped margin, c·tanh(m/c), sign·c·log(1+|m|/c), margin + win bonus, cap + bonus, each with ridge shrinkage 0.1–256 phantom games and recency half-lives off/240/120/60/30 days, plus the v0.6.0 probit DAD (with and without the 2σ cap) and the new WAD. **Game level, walk-forward:** ratings from games before date t predict every game on date t (margin RMSE; log loss and Brier of the result, draw = ½), each predictor mapped to outcomes with coefficients fitted on earlier seasons of the same league only. All choices made on development seasons (≤ 2020); results below are test seasons (2021+), 95% intervals bootstrapping whole league-seasons.

| family (test league-seasons, games) | DAD v0.7.0 RMSE ratio | DAD v0.6.0 RMSE ratio | log loss v0.7.0 / adj. margin / v0.6.0 |
|---|---:|---:|---:|
| basketball (17, 55,187) | 0.998 [0.997, 0.999] | 1.028 [1.019, 1.038] | 0.5318 / 0.5324 / 0.5404 |
| football (10, 3,778) | 0.998 [0.997, 0.998] | 1.024 [1.017, 1.028] | 0.5880 / 0.5889 / 0.6000 |
| baseball (6, 13,165) | 1.000 [0.999, 1.000] | 1.001 [1.000, 1.001] | 0.6801 / 0.6804 / 0.6810 |
| soccer (30, 9,264) | 0.998 [0.998, 0.999] | 1.005 [1.003, 1.007] | 0.6338 / 0.6344 / 0.6367 |

RMSE ratio = relative to the plain adjusted-margin rating (ridge 1), which is what v0.6.0 lost to. **First half → second half** (the RESEARCH.md design, computed by `DadModel.predict`; RMSE of second-half schedule-adjusted margin relative to first-half adjusted margin): DAD v0.7.0 0.998 / 0.999 / 1.000 / 0.999 (basketball / football / baseball / soccer) vs DAD v0.6.0 1.082 / 1.037 / 0.990 / 1.013 (baseball and soccer intervals include 1).

* **No transform beat the raw margin.** Caps, tanh/log compression and win bonuses all scored within ±0.1% of the raw margin or worse on development seasons (the best caps were the widest ones tried), so DAD now uses the margin as is. The v0.6.0 probit compressed blowouts and lost 2–3% RMSE in basketball and football; in low-scoring baseball and soccer the probit is nearly linear and the gap is small.
* **Shrinkage matters more than the transform** and is tuned per family with the rating taken at face value: basketball 1, football 2, MLB 32, soccer 4 phantom average games, roughly (σ / spread of team ratings)². Pro leagues with closer teams want more on development seasons (NBA 8, NFL 4; variant `pro_leagues`, not confirmed by the one-season backtest).
* **Recency** (half-life 30–240 days) gained less than the 0.1% threshold everywhere, so it is off by default (`half_life_days_*`).
* **DAD v0.7.0 vs the plain adjusted margin:** a hair better (0.2%) — it is essentially the same rating, expressed against a chosen default team.
* **WAD is not a strength measure**: per game it predicts future games 1–7% worse than the adjusted margin (it ignores margins by design) — use it as a résumé.

### Backtest (`ballmonitor backtest dad`)

`data/backtest.csv` (written by research_strength.py): the latest season of each of the 11 leagues (2025 or 2026), 1,052 team-seasons. Each row is one team's **first half** (games before the league's median game date, opponent ratings fitted on first-half games only, no later information), and `actual` is its **second-half schedule-adjusted margin per game** (margin + opponent's first-half rating − first-half home edge), expressed like DAD per game: (actual − baseline rating)/σ with the average baseline. Columns: `league, season, sport, team, baseline, split_date, n_first, n_second, actual_adj_margin, games` where `games` = `opponent_rating:margin:h|a|n:YYYYMMDD` items separated by `;`.

| league | team-seasons | MAE DAD/game (σ) | MAE strength | MAE unshrunk adj. margin | MAE raw margin |
|---|---:|---:|---:|---:|---:|
| NCAA men (2026) | 365 | 0.346 | 3.67 | 3.82 | 4.33 |
| NCAA women (2026) | 363 | 0.323 | 3.61 | 3.80 | 5.10 |
| NBA (2026) | 30 | 0.360 | 3.81 | 3.78 | 3.78 |
| FBS (2025) | 136 | 0.461 | 6.36 | 6.52 | 6.93 |
| NFL (2025) | 32 | 0.361 | 4.98 | 5.14 | 5.59 |
| MLB (2026) | 30 | 0.114 | 0.50 | 0.52 | 0.54 |
| Big-5 soccer (2026) | 96 | 0.19–0.27 | 0.31–0.44 | 0.39–0.49 | 0.41–0.51 |

MAE in points/goals/runs per game except the σ column (the `all cases` line of the CLI mixes units). One season per league: small samples outside college basketball/football; the multi-season evidence is RESEARCH_STRENGTH.md. Score metrics apply to `dad_scale = "margin"`; on the probit scale the σ errors are not comparable (RESEARCH_STRENGTH.md compares the scales through fitted linear maps instead).

### v0.6.0 study ([RESEARCH.md](RESEARCH.md))

`python -m ballmonitor.models.dad.research` still regenerates the v0.6.0 study (σ / home edges / totals / presets / the 2σ cap of the probit scale). Its finding — the probit DAD never beat a plain adjusted-margin rating (1.01–1.07× RMSE) because compressing big wins throws information away — is what v0.7.0 fixes. Sport constants and presets estimated there are unchanged.

## Assumptions and Known Weaknesses

* Opponent ratings are inputs. The model trusts them; for forecasting, use ratings known at the time (data/team_ratings.csv holds end-of-season, hindsight values).
* The strength rating is a one-team calculation given opponent ratings, not a joint fit. It matched a joint least-squares fit in the study (slightly better, in fact), but opponent ratings built from different data can shift it.
* One σ, home edge and shrinkage per sport family: NBA and NCAA share basketball's (NBA σ is really 12.4, home edge 2.7, best shrinkage 8), NFL and FBS share football's. Use variant `pro_leagues` or `--set` for pro leagues.
* Gains over a plain adjusted-margin rating are small (≈0.2%); the real improvement is over v0.6.0 DAD (2–3% RMSE in basketball/football, ~0.5% in soccer, ~0.1% in MLB). Game margins are mostly noise, so all candidates are close.
* Win chance vs default assumes normally distributed margins (Skellam/Pythagorean in soccer/baseball) with σ = per-game noise; it ignores uncertainty in the team's own rating, so it is a little over-confident for teams with few games.
* WAD and Total DAD are descriptive. A team with a soft schedule can have a high WAD and a modest DAD per game, and vice versa; that is intended.
* College baseball / softball: σ, shrinkage, presets and run environments are judgement values (no complete public game data); their examples are placeholders.
* MLB home edge (0.14 runs) is measured on recorded margins, which are shrunk because home teams leading after 8½ innings do not bat.
* Conference lists in `matchups.py` follow the 2024-25 realignment; soccer derbies match exact club names (after dropping FC/AFC).
* The 0.1% adoption rule for transforms and recency was written after seeing that all development-season differences were tiny; no test-season result was used for any choice.

## Variants

* `v06_probit` — DAD exactly as in v0.6.0: probit win-strength z-score per game with the 2σ cap, primary = total DAD; WAD margin-based.
* `pro_leagues` — for NBA / NFL inputs only: more shrinkage (`prior_games_basketball = 8`, `prior_games_football = 4`), the per-league game-level optima on development seasons. Unconfirmed by the one-season backtest (NBA 2026 worse, 3.99 vs 3.81 pts MAE on 30 teams; NFL 2025 equal).
* `champion_baseline` — compares against the national champion / title contender standard.
* `replacement_level` — compares against replacement level (WAR-style surplus).
* `wide_sd` — margin SDs 1.5× the measured noise. With `dad_scale = "margin"` this only rescales σ (DAD values shrink by 1/1.5; rankings unchanged); its original purpose (less probit compression) applies with `v06_probit`.

## References

* James, B. (1982). *The Bill James Baseball Abstract.* Ballantine Books.
* Smyth, D. (2006). *BaseRuns and Pythagenpat estimators.* Retrosheet.
* Massey, K. (1997). *Statistical models applied to the rating of sports teams.* Bluefield College.
* Stern, H. S. (1991). On the probability of winning a football game. *The American Statistician*, 45(3), 179-183.
* Skellam, J. G. (1946). The frequency distribution of the difference between two Poisson variates. *Journal of the Royal Statistical Society*, 109(3), 296.
* Dixon, M. J., & Coles, S. G. (1997). Modelling association football scores and inefficiencies in the football betting market. *Journal of the Royal Statistical Society: Series C (Applied Statistics)*, 46(2), 265-280.

## Changelog

* **0.7.0** — DAD split into strength and résumé, after a new study ([RESEARCH_STRENGTH.md](RESEARCH_STRENGTH.md), `research_strength.py`: game-level walk-forward over 118 league-seasons plus the first-half → second-half test; tunables chosen on ≤ 2020, reported on 2021+). New default `dad_scale = "margin"`: game DAD = (margin − default's expected spread)/σ (formula `game_dad`, replaces the probit z-score now in `game_dad_probit`); new primary output **DAD per game** = (strength − default rating)/σ, where strength = opponent-adjusted margin per game shrunk by `prior_games_*` phantom average games (formulas `strength_rating`, `strength_dad`, `recency_weight`); new outputs strength vs default, win chance vs default, strength rating. WAD is now result-based (`wad_mode = "result"`: result − chance the default team wins, formula `game_wad`; v0.6.0 version in `game_wad_strength`). New params `dad_scale`, `wad_mode`, `margin_cap_sd` (100 = off), `win_bonus_sd` (0), `soccer_margin_sd` 1.6, `mlb_margin_sd` 4.4, `college_baseball_margin_sd` 6.0 / `softball_margin_sd` 5.0 (DRAFT), `prior_games_*` (basketball 1, football 2, baseball 32, soccer 4; college baseball 6 / softball 3 DRAFT), `half_life_days_*` (0), new formula `game_performance`, optional input `as_of`. Multi-team mode ranks by DAD per game. `game_dad_cap` applies only to the probit scale. New variants `v06_probit` (old behaviour) and `pro_leagues`. New `data/backtest.csv`, `backtest_case`, `score`, `backtest_group`; status → calibrated. Website extras: same keys; `dad_per_game` is now the shrunk strength in σ (not total/games: that is `dad_per_game_raw`), `total_dad` is on the margin scale, `total_wad` is result-based, leaderboard sorted by `dad_per_game`; new keys `strength_rating`, `strength_vs_default`, `strength_dad`, `win_prob_vs_default`, `dad_per_game_raw`, `adjusted_margin_raw`, `margin_per_game`, `sigma`, `prior_games`, `half_life_days`, `baseline_rating`, `dad_scale`; game records add `performance`, `adjusted`, `recency_weight`, `p_default_result`, `result`.
* **0.6.0** — Real data: `fetch.py` now downloads ~187k real games (ESPN scoreboards for NCAA men's/women's basketball, FBS, NFL, NBA, MLB; football-data.co.uk for the Big-5 soccer leagues) into `data/games_<league>.csv` and builds `data/team_ratings.csv` with `ratings.py` (least-squares margin ratings). Replaced the sportsdataverse standings CSVs (WBB file was conference-only). Eight examples regenerated as real seasons (Florida 2024-25, 2025 Final Four, South Carolina WBB 2023-24, Ohio State 2024, Dodgers 2024, 2024 AL East, Arsenal and Everton 2023-24); the soccer examples no longer carry invented xG. New `research.py` → RESEARCH.md walk-forward study (5,855 test team-seasons). From it: new param `game_dad_cap = 2` (per-game cap in `game_dad`); `basketball_margin_sd` 11.0→10.6, `wbb_margin_sd` 12.5→11.2, `home_advantage_wbb` 3.0→2.9, `home_advantage_football` 2.5→2.1, `home_advantage_baseball` 0.30→0.14, `mlb_total_runs` 8.8→9.1, `soccer_total_goals` 2.70→2.75; MBB/WBB/MLB/soccer baseline presets re-estimated as rank-based medians on the per-game margin scale (e.g. MBB champion 30.0→23.9, 4-seed 21.0→16.8); football gets its own FBS presets (`football_*_rating`) instead of borrowing basketball's. New variant `wide_sd`.

* **0.5.0** — Football key-number adjustment made monotone (cumulative steps, new param `football_key_number_bump`; previously win strength dropped just past ±3.5 and ±7.5). Removed unused params `soccer_margin_sd`, `baseball_margin_sd`, `college_baseball_margin_sd`, `softball_margin_sd` (those sports use Skellam / Pythagorean). Sports and baselines now resolve through explicit alias tables: unknown sports (e.g. hockey, which silently got basketball baselines with soccer maths) and unknown baselines are errors instead of falling back to defaults, and `default_baseline = "top_4_seed"` now works in every sport. Missing `margin`/`opponent_rating`, bad `location` and non-numeric values raise clear errors (a missing margin used to count as a 0-margin draw). Fixed false soccer derbies ("Leicester City" vs "Manchester United" was a Manchester Derby) and college conference false positives ("West Virginia" → ACC, "Iowa State" → Big Ten, "South Florida" → SEC). Removed `data/backtest.csv`, whose `actual_dad` targets were hard-coded invented numbers, and `backtest_case`. Example inputs labelled as placeholders.
* **0.4.0** — Added comprehensive professional soccer (EPL / European football) support with Skellam distribution, draw point normalization, Expected Goals (xG) integration, Expected DAD (xDAD), Finishing/Goalkeeping Luck metric, derby auto-detection, and 2024 Premier League standings fetcher.
* **0.3.0** — Added Women's College Basketball (WBB / NCAAW) and College Softball support, including conference and rotation auto-detection, calendar date parsing, and full 2024 standings datasets from `sportsdataverse`.
* **0.2.0** — Added MLB and College Baseball (NCAA Baseball) support with Pythagorean win expectancy, empirical run environments, and data fetching for 2024 MLB and NCAA baseball standings.
* **0.1.0** — Initial implementation of Phase 1 DAD with probit/z-scale standardized deviations, multi-sport support (basketball, football, soccer, baseball), and multi-team leaderboard ranking.
