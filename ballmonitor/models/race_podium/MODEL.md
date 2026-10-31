# Race podium prediction (`race_podium`)

**Question:** What times will place 1st through 5th in a given race division?

**Status:** calibrated (v0.8) — walk-forward backtested on every finisher of 96 RunSignup races (5,741 out-of-sample division-years from 397 independent race editions, test years 2022–2026). Out of sample, 1st-place MAPE is 9.4% vs 13.6% for the mean of earlier editions and 12.4% for last year's time; 80% intervals cover 83% of 1st-place times and 79% of places 1–5. See *Backtest* and RESEARCH.md.

## Inputs

| input | meaning | example |
|---|---|---|
| `race_name` | Name of the race (display/logging) | `"Cherry Blossom 10 Mile"` |
| `distance` | Race distance (`5k`, `10k`, `10mi`, `half`, `marathon`) | `"10mi"` |
| `gender` | Division gender (`M`, `F`, `X`, or `all`) | `"M"` |
| `age_min` | Minimum age of the bracket | `40` |
| `age_max` | Maximum age of the bracket (e.g. 44 for 5-yr, 49 for 10-yr, 99 for open) | `44` |
| `field_size` | Expected number of finishers in this division (default: the recency-weighted mean of earlier editions if history is given, else `default_field_size`) | `140` |
| `total_field_size` | Optional total race field size across all divisions (used to estimate or smooth division field sizes) | `500` |
| `adjacent_counts` | Optional counts of adjacent brackets (e.g. `{"25-29": 10, "35-39": 15}`) to smooth single-bracket dips | `{"25-29": 10, "35-39": 15}` |
| `bracket_mode` | Optional division breakdown preset to evaluate all categories (`"5-year"`, `"10-year"`, or `"masters"`) | `"5-year"` |
| `results_url` | Web URL to race results (RunSignup API, HTML tables with year dropdowns, or ASCII text) | `"https://runsignup.com/Race/Results/68640"` |
| `max_history_years` | Maximum previous years to auto-discover and ingest from archives/dropdowns | `5` |
| `history` | List of past editions with `year`, `field_size`, `times` (ranks 1–6), and optional weather (`temp_f`, `dew_point_f`, `date`) | `[[history]] ...` |
| `open_history` | Optional earlier editions of the race's open division for the same gender (`year`, `field_size` = gender finishers, `times` or `time` = open winner first). Feeds the cross-division prior; derived automatically from `data_file` / `results_url` | `[[open_history]] ...` |
| `target_year` | Year of the edition being predicted (weights earlier editions by recency; default: last edition + 1, or the year of `target_date`) | `2026` |
| `prior_runners` | Optional list of prior-year runners with `name`, `age`, `time`, `gender` | `[[prior_runners]] ...` |
| `city`, `state` | Race location for automated weather lookup via Open-Meteo | `"Lewisberry"`, `"PA"` |
| `target_date` | Target race date (`YYYY-MM-DD`) for automated forecast retrieval | `"2026-11-03"` |
| `forecast_temp_f` | Explicit race-day temperature override (°F) | `76.0` |
| `forecast_dew_point_f`| Explicit race-day dew point override (°F) | `64.0` |
| `overall_awards_count` | Number of overall top awards excluded from divisions ("no double dipping") | `3` |
| `data_file` | Optional path to historical CSV file with individual finishes | `"data/sample_results.csv"` |

Times accept `h:mm:ss`, `m:ss`, or total seconds. Distances accept standard unit strings.

## Method

1. **Weather normalization of historical editions** (only where an edition's temperature and dew point are given or looked up): times are divided by $1 + \text{penalty}_\%/100$ with formula `weather_penalty`:
   $$\text{penalty}_{\%} = \left(\max(0, T + DP - 100) \cdot c_{\text{heat}} + \max(0, 32 - T) \cdot c_{\text{cold}}\right) \cdot \left(\frac{d}{5000}\right)^{\alpha_{\text{dist}}}$$

2. **Expected field size.** If no `field_size` (or `total_field_size`) is given, $\hat N$ is the mean of earlier division sizes weighted by `recency_decay`$^{\text{years back}}$.

3. **Own-history estimate per place (k = 1..6).** Finishing times in a division are treated as roughly log-normal, so the k-th fastest of N sits at the expected normal order score $z(k, N) = \Phi^{-1}\big((k - a)/(N + 1 - 2a)\big)$ (Blom, $a$ = `order_score_alpha`). Each earlier edition's k-th place log time is moved to the target field with formula `order_score_shift`:
   $$\log t_{k,j} + s\,\big(z(k, \hat N) - z(k, N_j)\big), \quad s = \texttt{time\_spread}$$
   (an edition with fewer than k finishers contributes its slowest place, shifted the same way) and averaged with formula `edition_weight`: $w_j = \texttt{recency\_decay}^{\text{years back}} \cdot N_j / (N_j + \texttt{edition\_weight\_half\_n})$, so an edition with one walker counts little. A bigger field gives a faster winner and tighter gaps.

   **Cross-division prior.** When the race's gender-open history is known (`open_history`, or derived from `data_file` / `results_url`), the open winners are shifted the same way from the open field to place k of this division's field and multiplied by the bracket's age factor (`age_curves.continuous_age_factor` at mid-age; open-ended brackets use `open_ended_age_cap`). The division estimate is shrunk toward it with formula `shrunk_log_time`, the prior counting `prior_weight` editions. Without any division history the prior alone is used; with an `open_baseline_time` only, that time times the age factor; with nothing, a judgement default (`default_open_pace_*`).

4. **Cohort Aging-Up Transitions & Biological Age Curves:**
   - Runners who competed in the prior edition at age $A_{\text{min}} - 1$ turn $A_{\text{min}}$ in the target edition, aging into this bracket.
   - Projected time applies a dynamic, distance- and age-specific decline rate $d(A, D, G)$ derived from empirical age curves (`age_curves.py`):
     $$t_{\text{projected}} = t_{\text{prior}} \cdot \left(1 + \frac{\text{decline}_{\%}}{100}\right)$$
     (or fallback to `annual_aging_decline_pct` if explicitly overridden).
   - With return probability `repeat_runner_prob` ($p_{\text{ret}}$), the probability of winning 1st place is evaluated against the field distribution (formula `aging_win_probability`):
     $$P(\text{aging-up win}) = p_{\text{ret}} \cdot \Phi\left(\frac{t_{\text{field}, 1} - t_{\text{projected}}}{\sigma_{\text{eff}}}\right)$$
   - Top-5 times blend the contender's time with the field distribution, cascading the remaining places.
   - When historical division data is absent, `open_baseline_time` or `open_winning_time` can be supplied to derive calibrated division baselines via `continuous_age_factor(A, D, G)`. For full empirical tables and physiological models across 5K to Marathon, see [RESEARCH_AGE_CURVES.md](RESEARCH_AGE_CURVES.md).

5. **Overall Winner Exclusion ("No Double Dipping"):**
   Under standard USATF/RRCA competition rules, athletes who place in the overall top $K$ (default $K=3$) receive overall awards and are **removed from age-group divisions**:
   - $P_{\text{overall\_exclude}}$ is estimated from results data when given (overall top-3 share by bracket, capped at `max_overall_exclusion_prob`); otherwise it is `overall_exclusion_prob_m40` (M 40–44), `overall_exclusion_prob_m35_45` (M 35–39, 45–49), `overall_exclusion_prob_f35_40` (F 35–39, 40–44), and 0 elsewhere. The division 1st place award shifts to the 2nd fastest division runner with probability $P_{\text{overall\_exclude}}$:
     $$t_{\text{division}, 1} = (1 - P_{\text{overall\_exclude}}) \cdot t_{(1)} + P_{\text{overall\_exclude}} \cdot t_{(2)}$$
     and subsequent positions cascade.

6. **Target weather adjustment:** with a race-day forecast (within 16 days or user-supplied) times are scaled by the target penalty via formula `weather_adjusted_time`; otherwise the mean penalty of the historical editions is applied (0 if their weather is unknown).

7. **Uncertainty & prediction intervals.** Each place gets its own 1-sigma (formula `place_sigma_pct`):
   $$\sigma_k = \sqrt{\big(\sigma_{\text{year}}^2 + \sigma_{\text{field}}^2 \cdot N_{\text{ref}}/\hat N\big)\,\big(1 + 1/W_k\big)}$$
   where $W_k$ is the total weight behind the estimate (edition weights + `prior_weight`). `sigma_year_pct` and `sigma_field_pct` were fitted walk-forward on real races (interval score, then rescaled to 80% training coverage); because those races had no weather inputs they already include ordinary weather variation, so a forecast shifts the times but does not narrow the interval. Intervals are log-normal: $[t_k e^{-z\sigma_k}, t_k e^{z\sigma_k}]$ at `interval_level`.

8. **Multi-Division Awards Boards & Common Breakdowns:**
   A `field_size` above `board_total_field_threshold` (150) is read as the whole race's size and split into divisions. Rather than evaluating a single isolated bracket, the model can predict the entire awards podium across all categories:
   - Presets include `"5-year"` (30 divisions: M & F 0–14 up to 80+), `"10-year"` (14 divisions: Under 20, 20–29 ... 70+), and `"masters"` (10 divisions: Open, Masters 40+, Grand Masters 50+, Senior GM 60+, Veteran 70+).
   - Division field sizes are scaled by distance-specific gender shares and empirical demographic bracket distributions.
   - When historical division data is specific to one bracket or absent, division baselines derive from the open standard scaled by continuous age factors $f(A, D, G)$.
   - Outputs a markdown awards comparison table and groups division winners under grouped outcomes.

9. **Automated Multi-Year Archive & Year Dropdown Discovery:**
   When a `results_url` is provided:
   - The ingester inspects HTML `<select>` dropdowns (`name="year"`, etc.), `<form action="...">` selectors, and `<a>` archive links to automatically locate previous editions (2018–2026).
   - Past editions are ingested, SQLite-cached, and compiled into multi-year historical baselines, inter-year variance $\sigma_{\text{year}}$, and returning runner contender tracking.

## Parameters

Run `ballmonitor params race_podium` for every parameter with units, ranges and sources. Fitted in RESEARCH.md: `time_spread` (0.09), `recency_decay` (0.7), `edition_weight_half_n` (10), `prior_weight` (0.5), `sigma_year_pct` (5.18%), `sigma_field_pct` (2.47% at `sigma_field_ref_n` = 100). Others: `repeat_runner_prob` (0.40), `annual_aging_decline_pct` (used only when overridden — otherwise the age-curve rate), weather penalties (`heat_penalty_per_deg`, `cold_penalty_per_deg`, `weather_dist_exponent`), `overall_awards_count` (3) and the `overall_exclusion_prob_*` priors, `interval_level` (0.80), `min_tail_spread_sec`, fallbacks (`default_gaps_sec`, `default_open_pace_m/f`, `default_open_exponent`, `no_history_sigma_pct`, `default_field_size`, `default_distance_m`, `max_history_years`, `missing_rank_gap_sec`). Values not verified by the study are marked DRAFT in their source.

## Variants

* `high_retention` — `repeat_runner_prob = 0.70` (for local annual club races where top contenders return year after year).
* `low_retention` — `repeat_runner_prob = 0.15` (for destination races or major marathons with high annual turnover).

## Data and placeholders

- `examples/*.toml` and `data/sample_results.csv` are **placeholders**: the race histories, runner names (e.g. "Marcus Vance") and times are invented to illustrate the inputs. `sample_results.csv` is generated by `fetch.py`.
- `data/division_panel.csv` (v0.8) is built by `download_runsignup.py --full`: every finisher (all result pages) of 150 multi-year RunSignup races, cached as gzipped JSON in `data/raw/runsignup_full/` (gitignored), reduced to one row per race × distance × year × division (M/F open, 5-year brackets 15–19 … 70–74, 75+) with true field size, top-5 times and the fastest runner aged `age_min − 1` in the previous year. Cleaning: sub-3:50/mile finishes, duplicate rows, editions under 30 finishers, years with two same-distance events, and result lists filed under two distances are dropped. 96 races have a usable earlier edition.
- `data/runsignup/finishes.csv` is real RunSignup data downloaded by `download_runsignup.py`. It is used through `download_runsignup.clean_finishes`, (top 150 finishers per edition only, so its division sizes are truncated; kept because race_time uses it), which re-classifies distances from event names (the original download read "15K" as 5K and "1/2 Marathon" as a marathon), drops virtual / bike / ultra / relay events and finishes faster than 3:50/mile, and removes duplicated rows and result lists filed under two distances.

## Backtest

`data/backtest.csv` is written by `research.py` (`build_backtest_csv`) from the panel — one row per race × distance × division × year with at least one earlier edition and at least 5 finishers in the target year. Every input column is known before the target race:

| column | meaning |
|---|---|
| `race`, `race_id`, `year` | race and target edition (`year` is passed as `target_year`) |
| `gender`, `age_min`, `age_max`, `distance` | division (age 0–99 = open) |
| `field_size` | blank: the model assumes its expected field (recency-weighted mean of earlier editions) |
| `actual_field_size` | target edition's division finishers — reference only, not read by the model |
| `hist_editions`, `history` | earlier editions as `year:field_size:t1\|t2\|...` joined by `;` |
| `open_history` | earlier gender-open editions as `year:gender_finishers:winner` (blank for open divisions) |
| `prior_fastest_aging_in` | fastest runner aged `age_min − 1` in the previous calendar year's edition |
| `actual_time`, `actual_times` | fastest division time (scored) and places 1–5 |

`backtest_case` turns the overall-award exclusion off, because the target is the fastest division finisher, not the award winner.

**Out-of-sample results** (RESEARCH.md; parameters refitted each test year on earlier years only; 5,741 division-years, 397 independent race editions, 96 races):

| predictor | 1st MAE | 1st MAPE | median APE | 80% cov. 1st | 80% cov. 1–5 |
|---|---|---|---|---|---|
| last edition | 239 s | 12.4% | 8.2% | — | — |
| mean of earlier editions | 244 s | 13.6% | 8.4% | — | — |
| v0.7 model | 231 s | 12.7% | 8.2% | 59.8% | 56.2% |
| **v0.8 model** | **186 s** | **9.4%** | **7.3%** | **83.1%** | **79.4%** |

Ablations: without the cross-division prior MAPE is 10.4%, without the field-size shift 9.6%, without the aging-in step 9.5%. Knowing the target's actual division size (hindsight, e.g. from registrations) lowers MAPE to 9.2%. Coverage is a little high for 1st place in small divisions (86% at expected N < 15) and on long races (87–89%), about right elsewhere.

`ballmonitor backtest race_podium` (final defaults, all 7,202 cases — in-sample): MAE 180 s, MAPE 9.26%, 80% coverage 84.1%.

Caveats: divisions of one race edition are correlated (count race editions, not rows); races are a sample of mostly small/medium US races from RunSignup search; mislabelled events and course changes are left in and dominate the error tail; the age curves used by the prior were fitted on the older top-150 download (overlapping races). The v0.7 figures in the old MODEL.md (MAE 258 s, 49.5% coverage) were on the truncated top-150 data with the target's actual field size; on the new data with the same no-hindsight protocol v0.7 scores as in the table.

## References

* Ely, M. R., Cheuvront, S. N., Roberts, W. O., & Montain, S. J. (2007). Impact of weather on marathon-running performance. *Medicine & Science in Sports & Exercise*, 39(3), 487–493.
* Montain, S. J., Ely, C. R., & Cheuvront, S. N. (2007). Marathon performance in hot, humid weather. *Sports Medicine*, 37(4), 320–323.
* USATF Competition Rules — Rule 245: Age-Group and Overall Awards.
* World Masters Athletics (WMA) Age-Grading Tables.

## Changelog

* 0.8.0 — New data: every finisher of 150 RunSignup races (`download_runsignup.py --full`, `data/division_panel.csv`) instead of the top 150 per edition; duplicated result lists are detected on the raw list. New estimator: per-place order-score field-size shift (`time_spread`, replaces `field_size_exponent` / `spread_decay_exponent` and the `field_scaled_*` formulas), recency- and size-weighted editions (`recency_decay`, `edition_weight_half_n`), shrinkage toward a cross-division prior from the gender-open history (`prior_weight`, new `open_history` input), expected field = recency-weighted mean. Uncertainty replaced by a fitted per-place sigma (`sigma_year_pct`, `sigma_field_pct`, formula `place_sigma_pct`); removed `weather_volatility_pct`, `forecast_weather_sigma_pct`, `field_size_sigma_pct`, `single_edition_sigma_pct`; `no_history_sigma_pct` 2% → 15% (DRAFT). Backtest is now strictly walk-forward without hindsight (blank field_size, exclusion step off): out-of-sample MAPE 12.7% (v0.7) → 9.4%, 80% coverage 60% → 83%. The hard-coded `raw_fs > 150` board cutoff is now `board_total_field_threshold`; other hard-coded defaults moved to `default_field_size`, `default_distance_m`, `max_history_years`, `open_ended_age_cap`, `order_score_alpha`. History editions are no longer padded with synthetic +30 s places.
* 0.7.0 — Backtest replaced: the old `data/backtest.csv` had 16 invented rows (MAE 16 s, 100% coverage); it is now 1,735 real walk-forward rows built from RunSignup data, and RESEARCH.md was regenerated after fixing distance mis-classification and duplicate results in the download (1st-place MAPE 16.2% → 8.8%). RESEARCH.md text no longer overstates results ("over 30%", "calibrated 80% coverage"). Hard-coded numbers moved to params (weather/field/inter-year sigmas, overall-exclusion priors and cap, default gaps and open baseline, missing-rank gap, aging sigma floor); the summary-only history path now uses `default_gaps_sec` (previously its own 25/50/80/115/145 s list). History times are now sorted; `field_size` defaults to the historical mean field instead of 100 (the `from_csv` example scaled a field of 2 up to 120, moving the winner 19%); a 0°F forecast is no longer ignored; the step text uses the effective `overall_awards_count`. Bad inputs (unknown gender, age_min > age_max, field_size < 1, empty history times, prior runners without age/time, missing data_file) raise clear errors. Examples and sample data labelled as placeholders. Unverified sources marked DRAFT.

* 0.6.0 — Added division awards boards with common breakdowns (`5-year`, `10-year`, `masters`), `predict_all_brackets` multi-division runner, and automated previous-year dropdown / archive URL discovery (`discover_race_years` & `ingest_multi_year`).
* 0.5.0 — Added universal URL results ingestion engine (`ingest.py`) with native RunSignup REST API integration, fuzzy semantic HTML table scraping, preformatted ASCII text parsing, and SQLite caching (`data/races.db`).
* 0.4.0 — Added demographic participation smoothing (`participation.py`) with adjacent-bracket kernel smoothing and Empirical Bayes shrinkage to eliminate random Poisson sampling noise in small-to-midsize race divisions.
* 0.3.0 — Added empirical and continuous parametric age curves across distances (5K, 10K, Half Marathon, Marathon) and genders, dynamic local decline rates for aging-in contenders, open baseline synthesis, and age-distance equivalence projections.
* 0.2.0 — Added automated Open-Meteo weather lookups, dew point heat/cold penalties, historical weather variance intervals, and overall winner exclusion ("no double dipping") logic.
* 0.1.0 — Initial calibrated model with field size order statistics, cohort aging transitions, and backtest suite.
