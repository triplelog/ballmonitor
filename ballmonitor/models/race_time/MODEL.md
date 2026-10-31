# Race time prediction (`race_time`)

**Question:** What finish time will this runner achieve at any target distance, and how wide is the realistic range around it?

**Status:** calibrated (v0.5.0). **In one sentence:** your races, Riegel's formula, a weighted average, and bands measured from 2,560 real runners' errors.

Why bands are the point: on 5,000 linked Ohio road racers every reasonable method — plain Riegel, personal exponents, a fitted curve, age/gender adjustments — lands within ~0.3 pp of 9.6% mean error, and ~94% of what is left is the runner's own day-to-day variation (RESEARCH_SIMPLE.md). No formula can predict that, but it can be *measured*: the 50/80/95% bands below are the actual spread of errors of 2,560 train runners, checked on 2,440 others (test coverage 51.7% / 81.1% / 95.7%; RESEARCH_BANDS.md).

## Inputs

| input | meaning | example |
|---|---|---|
| `races` | list of `{distance, time, year, date, name, elevation_gain, elevation_loss, altitude, temp_f, dew_point_f, humidity_pct, gpx_path}`; `distance` and `time` are required | `5k` in `21:15` (82°F, 70% humidity) |
| `target` | distance to predict | `"marathon"`, `"10k"`, `"half"`, or meters |
| `age` | runner's age (only used by the curve method's optional demographic priors; age had no meaningful effect on the exponent, RESEARCH_SIMPLE.md) | `42` |
| `gender` | `"M"` or `"F"` (optional): selects the Riegel exponent (1.09 / 1.06; 1.07 if omitted) | `"M"` |
| `target_year` | target race year, for race recency (weights and the band's years-since-last-race) | `2026` |
| `target_date` | exact target date (optional; with race `date`s, elapsed time is measured in days) | `2026-04-26` |
| `target_elevation_gain` | total climbing on the target course | `"600ft"`, `"180m"`, or meters |
| `target_elevation_loss` | total descending on the target course | `"600ft"`, `"180m"`, or meters |
| `target_altitude` | average altitude above sea level of target course | `"5280ft"`, `"1600m"`, or meters |
| `target_temp_f` | expected race-day temperature (°F) | `76.0` |
| `target_humidity_pct` | expected race-day relative humidity (%) | `65.0` |
| `target_dew_point_f` | expected race-day dew point (°F) | `60.0` |
| `target_gpx_path` | path to a `.gpx` course file (relative paths are tried in the working directory, then the model directory) | `"data/sample_course.gpx"` |

A race `date` (`2025-04-26`, TOML date or string) is optional; without it the race counts as run at the start of its `year`. Distances accept named strings (`mile`, `5k`, `8k`, `10k`, `10mi`, `half`, `marathon`, `50k`) or meters. Times accept `h:mm:ss`, `m:ss`, or total seconds.


## Method (default: `method = "weighted_riegel"`)

Plain language: every race you enter is turned into a prediction for the target distance with Riegel's formula. Those predictions are averaged, trusting races close to the target distance and recent races more. Then the range is drawn from how wrong this exact procedure was for thousands of real runners in a similar situation (how far you extrapolate, how old your newest race is, how many races you gave).

1. **Environmental normalization of your races** (unchanged, DRAFT coefficients): a race run hot, at altitude or on a hilly course is converted to a flat, sea-level neutral time, $T_\text{neutral} = T_\text{observed} / (\text{elevation} \times \text{altitude} \times \text{weather})$ (see step 6).

2. **Exponent** (formula `exponent`): $b$ = `riegel_exponent` (1.07) + `exponent_offset_male` (+0.02) for men or `exponent_offset_female` (−0.01) for women → **1.09 men, 1.06 women, 1.07 if gender is not given**. Chosen on train runners by minimising MAPE per gender (RESEARCH_BANDS.md §1). It is kept because it is one number per gender and it fixes a real bias: with one exponent, men's "up in distance" predictions were too fast and "down" too slow by ~1.5–2.4% (median), with the gender exponent all four gender × direction medians are within 0.75% (train).

3. **Project each race** (formula `predict`): $T_i = t_i \, (D / d_i)^b$ for target distance $D$.

4. **Weight each race** (formula `race_weight`): $w_i = e^{-|\ln(D/d_i)| / \lambda} \cdot 0.5^{y_i / h}$ with $\lambda$ = `race_weight_distance_scale` = 1 (a race at half or double the target distance keeps 50% weight, a 5K for a marathon 12%) and $h$ = `race_weight_half_life_years` = 1 ($y_i$ = years before the target: from `date`/`target_date` when given, else whole years before `target_year`, else before the latest race; no dates at all → every race counts as current). Both were chosen on train in RESEARCH_SIMPLE.md (method C).

5. **Combine** (`race_combination` = geometric): point $= \exp(\sum w_i \ln T_i / \sum w_i)$.

6. **Bands** (formulas `band_log_quantile`, `median_time`, `band_time`): for each quantile level $\tau \in$ {2.5, 10, 25, 50, 75, 90, 97.5}%, the fitted quantile of the log error $\ln(\text{actual}/\text{point})$ is
   $$q_\tau = \text{base}_\tau + b^{gap}_\tau \cdot \text{gap} + b^{years}_\tau \cdot \text{years} + b^{races}_\tau / \text{races}$$
   - gap = $\sum w_i |\ln(D/d_i)| / \sum w_i$ (0 = all races at the target distance; 0.69 = a factor of 2), years = years since your most recent race (capped at `band_max_years` = 3), races = number of races (capped at `band_max_races` = 3) — the range of the training data.
   - The 28 coefficients are params `band_<p025|p10|p25|p50|p75|p90|p975>_<base|gap|years|races>`, fitted by linear quantile regression on train (RESEARCH_BANDS.md §2).
   - **Median** = point × $e^{q_{50}}$ (corrects the small bias: e.g. −1.3% for one recent race at the target distance, +2.4% for three races two years old). Every other quantile = median × $e^{\text{band\_scale} \cdot (q_\tau - q_{50})}$; `band_scale` (1) widens or narrows all bands. Quantiles are sorted so bands never cross.
   - The **primary interval** uses `interval_level` (0.8 = the 10–90% band); other levels are interpolated between the seven quantiles in normal-z space.
   - What the fit says: one race leaves a much fatter *fast* tail (at the target distance the 2.5% quantile is 23% below the median with one race vs 14% with three — a single race is often a jog or fun run); old races fatten the *slow* tail (97.5% quantile +8 pp per year); distance extrapolation widens both, the slow side more. Around the median, a recent half → half with one race has an 80% band of −11% / +13% (95%: −23% / +28%); with three recent halves −9% / +11%; a single 5K → marathon −16% / +25% (95%: −37% / +48%).
   - If you override formula `predict`, its result is used as the median directly (the fitted shift belongs to the default formula); the bands keep their fitted widths.

7. **Target course conditions** (unchanged, DRAFT): elevation (formula `elevation_multiplier`, floored at `min_elevation_multiplier`), altitude (`altitude_multiplier`) and heat/cold (`weather_penalty_pct`) multiply the median and every band (formula `course_adjusted_time`). These coefficients come from the literature/judgement and were not part of any calibration; see the curve-method appendix for their definitions.

8. **Every distance**: the same steps at any distance give the chart curve (60 log-spaced points, 800 m – 50 km) and the benchmark table (flat, no course adjustment).

## Output

Outcomes: target median (`interval` = `interval_level` band, 80% by default), "Target 50% range" and "Target 95% range" (median, range in the note), "Flat/neutral equivalent" (only with course conditions), pace per mile and per km, and a "Common distances (flat)" group (Mile, 5K, 10K, Half marathon, Marathon: median + 80% interval, 50%/95% ranges in the note).

`extras` (the chart contract; both methods produce these keys):

| key | content |
|---|---|
| `method` | `"weighted_riegel"` or `"curve"` |
| `exponent` | Riegel exponent used (curve: the blended slope beta1) |
| `races_used` | per race: `distance`, `distance_label`, `time_sec` (neutral), `time_str`, `date`, `year`, `weight` (share, sums to 1), `implied_target_sec` |
| `band_levels` | `[0.5, 0.8, 0.95]` |
| `curve_points` | 60 points 800 m – 50 km: `distance`, `distance_label`, `p025_sec` … `p975_sec`, `pace_mile_sec`, `pace_km_sec` (median), and for compatibility `estimate_sec` (= p50), `lo_50_sec`, `hi_50_sec`, `lo_80_sec`, `hi_80_sec`, `lo_95_sec`, `hi_95_sec` |
| `benchmarks` | Mile, 5K, 8K, 10K, 15K, 10 Mile, Half Marathon, Marathon, 50K: `label`, `distance_meters`, `common`, `p025_sec` … `p975_sec`, `estimate_sec`, `estimate_str`, `interval_str` (80%), `range50_str`, `range95_str`, `pace_per_mile_sec`, `pace_per_mile_str`, `pace_per_km_str` |
| `runner_points` | your races (neutral and raw times) for plotting |
| `target_distance_m`, `target_label`, `gap` | target; `gap` = weighted mean \|ln(D/d)\| (curve: doublings to the nearest race) |
| `target_multiplier`, `target_elevation_gain_m`, `target_altitude_m`, `target_temp_f` | course conditions (multiplier 1 / zeros / null when none) |

The curve method adds its own intermediates (`beta1`, `shrinkage_weight`, `sigma_pct`, …).

## Assumptions and known weaknesses

- Riegel's power law with one exponent per gender; no personal exponent (fitting one from 2–3 races is mostly noise: the fitted shrinkage was 16 pseudo-races, RESEARCH_SIMPLE.md).
- The bands describe recreational Ohio road racers 2018–2025 on RunSignup-timed (often uncertified) courses, with effort and weather unobserved. An elite or very consistent runner will usually land in a narrower range than shown; someone returning from injury in a wider one.
- Training cases had at most 3 races, at most 3 years old (hence the caps). Gaps above ~2 (e.g. mile → marathon) are linear extrapolations of the band model (55 test cases with gap ≥ 1.5: coverage 42/80/95%).
- **Mile targets** are the weak spot (43 test cases: MAPE 15%, medians ~6% too slow, 50% band covers 35%). 10K and half targets are slightly over-covered (80% band covers 88–89%).
- Course and weather multipliers are DRAFT literature/judgement values and were not calibrated; they scale the bands but add no extra uncertainty.

## Parameters

Run `ballmonitor params race_time` for every parameter with its description, range and source. Default method: `riegel_exponent` 1.07, `exponent_offset_male` +0.02, `exponent_offset_female` −0.01, `race_weight_distance_scale` 1, `race_weight_half_life_years` 1, `race_combination` geometric, 28 `band_*` coefficients, `band_max_years` 3, `band_max_races` 3, `band_scale` 1, `interval_level` 0.8. Parameters whose description starts with "(curve method)" only affect `method = "curve"`. Environmental coefficients marked "DRAFT … verify" are judgement values.

## Variants

- `curve_v04` — the v0.4.0 method (`method = "curve"`), for comparison. Test: MAPE 9.63%, coverage 59/82/92%.
- `pure_riegel` — Riegel 1.06 for everyone, all races weighted (almost) equally; same bands.
- `no_gender_exponent` — one exponent (1.07) for men and women.
- `trust_fit`, `static_no_drift` — curve-method variants (aggressive personal slope; no fitness transfer / time-based sigma).

## Backtest

**Data.** `download.py` downloads (cached in `data/raw/`, gitignored, ~60 MB) every finisher of every standard-distance road event (mile, 5K, 8K, 10K, 15K, 10 mi, half, marathon) in Ohio RunSignup races dated 2018–2025: 8,196 events, 1.04 M result rows. Trail, virtual/DIY, untimed, walk-only, relay, kids, challenge/combo and similar events are excluded by name, and the event's distance field must match a standard distance within 2%. `pipeline.py` then

1. keeps finishes with a name, gender, age 10–90, the runner's own city and state, and pace 3:45–16:00 per mile; drops events with fewer than 15 such finishers and events whose result list duplicates another event's (722 k finishes in 4,098 events remain);
2. links runners by first + last name, gender, home city + state and birth year (event year − age, ±1); a linked cluster with two finishes in one event or on one day is a name collision and is dropped (116 k linked runners);
3. builds **walk-forward** cases: the target is predicted from the runner's ≤3 most recent finishes run *strictly before* the target date (≤3 years earlier); one case per runner; a reproducible hash sample of 3,000 `cross_distance` (no input at the target distance) and 2,000 `same_distance` runners is written;
4. assigns each runner to `train` or `test` by a hash of their id, and fits `demographic_priors.json` on train runners only.

Columns of `data/backtest.csv`:

| column | meaning |
|---|---|
| `case_id`, `scenario`, `split`, `entity_id` | row id; `cross_distance` / `same_distance`; `train` / `test`; linked runner id |
| `gender`, `age` | runner gender and age at the target race |
| `race{1,2,3}_distance`, `_time`, `_date`, `_year` | input races (blank if absent), all strictly before the target date |
| `target`, `target_date`, `target_year`, `actual_time`, `event_id` | target distance, its date, the real finish time, and the RunSignup event id |

`ballmonitor backtest race_time` reports each scenario × split. The full study is `python -m ballmonitor.models.race_time.research` → `RESEARCH.md`: diagnosis, settings chosen on train only (coordinate descent; a setting moves only if train MAPE improves by ≥ 0.03 pp), sigma components fit on train, and test results with bootstraps that resample whole target events.

`ballmonitor backtest race_time` reports each scenario × split, including the share of actual times inside the 50% / 80% / 95% bands (`in_50`, `in_80`, `in_95`). The band study is `python -m ballmonitor.models.race_time.research_bands` → `RESEARCH_BANDS.md` (needs numpy + scipy); the v0.4.0 curve study is `research.py` → `RESEARCH.md`; simple Riegel variants `research_simple.py` → `RESEARCH_SIMPLE.md`.

**Results on the 2,440 test runners (out-of-sample, RESEARCH_BANDS.md):**

| method | MAPE | median APE | actual below median | 50% band | 80% band | 95% band | IS80 | IS95 |
|---|---|---|---|---|---|---|---|---|
| **v0.5.0 weighted Riegel + empirical bands** | **9.55%** | 6.28% | 48.4% | **51.7%** | **81.1%** | **95.7%** | 51.7 | 84.6 |
| v0.4.0 curve + normal sigma | 9.63% | 6.28% | 47.1% | 59.4% | 81.9% | 91.9% | 52.4 | 90.5 |

v0.5.0 − v0.4.0 (95% event bootstrap): MAPE −0.08 pp [−0.19, +0.03] (a tie, as expected); interval score 50% −0.66 [−1.06, −0.29], 80% −0.68 [−1.42, +0.03], 95% −5.89 [−9.90, −2.05]. The v0.4.0 normal bands were too wide in the middle and too narrow in the tails; the empirical bands are close to nominal overall and within a few points in every gap, scenario, gender, race-count and recency group (exceptions: mile, 15K and 10 mi targets, small samples; see RESEARCH_BANDS.md).

<details><summary>v0.4.0 results and history</summary>

| settings | MAPE | median APE | mean error | 80% coverage | 80% interval score |
|---|---|---|---|---|---|
| pure Riegel 1.06, v0.3.0 sigma | 9.7% | 6.3% | −54 s | 46% | 64.4 |
| v0.3.0 defaults | 9.8% | 6.4% | +38 s | 46% | 65.3 |
| pure Riegel 1.06, sigma fit on train | 9.7% | 6.3% | −54 s | 81% | 52.0 |
| **v0.4.0 defaults** | **9.6%** | **6.3%** | −64 s | **82%** | 52.4 |

Test MAPE differences (95% event-bootstrap): v0.4.0 − pure Riegel −0.06 pp [−0.14, +0.02] (not significant); v0.4.0 − v0.3.0 −0.22 pp [−0.38, −0.05]. Cross-distance test cases: MAPE 10.0% (pure Riegel 10.2%), coverage 82%; same-distance: 9.0% (9.0%), 81%. Test 80% coverage is 79–91% in every target year, gap bucket and target distance except 10 mi / 15K / mile (75–77%, small samples); mile targets (43 test cases) are the weak spot (MAPE 17%, predictions ~9% too slow).

**What the old "slow bias" was.** The v0.3.0 review's +787 s mean error came from a different dataset (135 cases, year-only RunSignup top-150 lists, target = the runner's longest race of the year): the median implied exponent there was 1.052 (≈ Riegel) but the mean was 1.013, pulled by a tail of very slow input 5Ks (fun runs) next to a raced half/marathon, and errors in seconds are dominated by marathon targets. On the new walk-forward data v0.3.0 is biased slow only for half/marathon targets and "up" predictions (median +3.6% / +4.5%), from the steep cohort prior plus curvature 0.015 — fixed by the prior/curvature change, not a fudge factor. The far bigger defect was the uncertainty: a 2% base sigma against a real race-to-race spread of ~6–7% median APE.

**Limits.** One state; RunSignup-timed, uncertified courses (some events are long/short — that error is included, as a user would face it); effort unobserved; rare name-collision links possible; runners within one target event share course and weather (hence the event bootstrap). Test cases are independent runners, but the 2,440 test cases come from fewer distinct target events.

### Simple Riegel variants (`research_simple.py` → RESEARCH_SIMPLE.md)

Same train/test runners. Test MAPE: Riegel 1.06 from the most recent race 9.95%; from the
closest distance 10.03%; **weighted average of all the runner's races 9.69%**; plus a
personal exponent fitted to the runner's races 9.71% (the fitted shrinkage, 16
pseudo-races, means a runner's own slope is mostly noise); plus an age/gender exponent
9.68% (women b ≈ 0.038 lower, age ≈ no effect; removes the bias: +0.06% vs −1.27%);
current model 9.63%. All within ~0.3 pp; the only clear gain over plain Riegel is using
every race (−0.26 pp [−0.39, −0.12]). About 6% of the remaining error variance is shared
by runners in the same race (course/weather); the rest is the runner's own day-to-day
variation, which no input here captures. No defaults changed.

</details>

## Appendix: the curve method (`method = "curve"`, v0.4.0)

1. **Data (for calibration only, not used at prediction time):** see *Backtest* — dated RunSignup results, runners linked by name + gender + home city/state + birth year (±1).

2. **Environmental Normalization (Past Races):**
   - If an input race was run in hot/humid conditions, at altitude, or with significant elevation change, it is normalized to a flat, sea-level neutral time before curve fitting:
     $$T_{\text{neutral}} = \frac{T_{\text{observed}}}{\text{ElevationFactor} \times \text{AltitudeFactor} \times \text{WeatherFactor}}$$
   - Prevents hot or mountainous races from artificially depressing the runner's estimated fitness profile.

3. **Prior slope** (`default_exponent`, `use_demographic_priors`):
   - Default (v0.4.0): the prior slope is $\beta_{1,\text{pop}}$ = `default_exponent` = 1.057 for everyone, curvature $\beta_2$ = `marathon_curvature` = 0.005 on $(\ln D/5000)^2$.
   - Optional (`use_demographic_priors = true`): a gender × age cohort slope from `data/demographic_priors.json` (median per-runner pair slope over races within 120 days, train-split runners only, cohorts shrunk toward the global median with weight n/(n+25)); age unknown but gender known → 35–49 cohort. These pair slopes (~1.07–1.10) are steeper than what actually predicts the next race, and turning them off improved train MAPE 10.44% → 10.21% (RESEARCH.md), so they are off by default.

4. **Hierarchical Empirical Bayes Shrinkage:**
   - **1 Race Input:** Anchors the speed level $\alpha$, inheriting the demographic prior slope $\beta_{1, \text{pop}}$ and curvature $\beta_{2, \text{pop}}$.
   - **2 Distinct Races:** Computes the runner's observed speed-endurance slope $\beta_{1, \text{obs}}$ and applies James-Stein / Empirical Bayes shrinkage:
     $$w = \frac{\text{doublings}}{\text{doublings} + \text{shrinkage\_prior\_strength}} \cdot \text{fit\_weight}$$
     $$\beta_1 = w \cdot \beta_{1, \text{obs}} + (1 - w) \cdot \beta_{1, \text{pop}}$$
   - **2+ distinct distances** (any number of races): $\beta_{1,\text{obs}}$ is the recency-weighted least-squares slope of $\ln T - \beta_2 x^2$ on $x = \ln(D/5000)$, clamped to [`min_exponent`, `max_exponent`]; "doublings" is the span $\log_2(D_\max/D_\min)$. The same shrinkage weight applies whether there are 2 or 10 races.
   - **Off-day weighting** (`off_day_tolerance_pct`, 2+ races): each race is converted to a 5K equivalent with the prior slope; a race $X$% slower than the runner's best equivalent gets its weight multiplied by $e^{-X/\text{off\_day\_tolerance\_pct}}$ (32 → a race 10% slower keeps 73% weight; 0 = off). Recreational results include jogs, pacing duties and bad days.
   - The level $\alpha$ is the recency-weighted mean of each race's implied $\alpha$ given the blended slope; the target time comes from formula `predict_time`. If you override formula `predict` (e.g. classic Riegel `t * (D / d) ** 1.06`), every race is projected with it and the projections are recency-weighted instead.

5. **Temporal Fitness Evolution & Delta Transfer:**
   - *Recency Weighting:* each race gets weight $e^{-\Delta y / (\text{fitness\_half\_life\_months}/12)}$ ($\Delta y$ = years before the target: from `date`/`target_date` in fractional years when given, else whole years before `target_year`, default the latest race), times `stale_weight_factor` if older than `max_stale_years`.
   - *Temporal uncertainty:* $\sigma_{\text{temporal}}$ = weight-averaged $\Delta y \cdot$ `annual_fitness_drift_pct`.
   - *Cross-Distance Delta Transfer:* When a runner logs a historical target race (e.g. Marathon in 2024 at 3:30) and companion race (e.g. 5K in 2024 at 22:00), and subsequently runs a significantly faster 5K in 2026 (e.g. 19:30):
     $$\Delta_{\text{fitness}} = \frac{v_{\text{recent}} - v_{\text{old}}}{v_{\text{old}}}$$
     $$\Delta_{\text{transferred}} = \eta \cdot \Delta_{\text{fitness}}$$ (formula `transfer_improvement`)
     where $\eta$ = `transfer_short_to_long` (companion shorter than target) or `transfer_long_to_short`. The old target-distance race time is divided by $1 + \Delta_{\text{transferred}}$. A past race counts as "at the target distance" if it is within `same_distance_tolerance_doublings` of it.

6. **Target Environmental Projection (Elevation, Weather, Altitude & GPX):**
   - Course time scales from neutral flat time using validated physiological models:
     - **Elevation Grade** (formula `elevation_multiplier`, floored at `min_elevation_multiplier`): average up-grade = gain / distance, down-grade = loss / distance; uphill costs `uphill_cost_pct_per_grade_pct` (3.3%) per 1% grade, downhill credits `downhill_credit_ratio` (55%) of that (Minetti et al. 2002).
     - **Altitude** (formula `altitude_multiplier`): `altitude_cost_pct_per_1000m` (3.2%) per 1,000 m above `altitude_threshold_m` (1,000 m) (Péronnet et al. 1991, Bassett & Howley 1997).
     - **Thermal Strain** (formula `weather_penalty_pct`): `heat_penalty_per_deg` (0.06%) per °F of $(T + DP - 100)$, times $(D/5000)^{\text{weather\_dist\_exponent}}$; cold adds `cold_penalty_per_deg` (0.03%) per °F below 32°F. Dew point comes from `dew_point_f`, else from `humidity_pct` (Magnus formula), else is assumed to be `assumed_dew_point_ratio` × T.
     - Input races are divided by the same combined multiplier to get a neutral time before fitting; the target is multiplied by it (formula `course_adjusted_time`).
     - **GPX Parsing:** Automatically extracts cumulative elevation gain, loss, distance, and altitude profile directly from GPX track files.

7. **Probabilistic Uncertainty Funnel (Gaussian Process Envelope):**
   - Uncertainty naturally pinches tight near observed race distances and funnels outward when extrapolating into unobserved regimes:
     $$\text{gap}(D) = \min_{d \in \text{anchors}} |\log_2(D / d)|$$
     $$\sigma_{\text{pct}}(D) = \sqrt{\text{base\_uncertainty\_pct}^2 + (\text{gap} \cdot \text{extrapolation\_uncertainty\_pct})^2 + \sigma_{\text{temporal}}^2}$$
   - Defaults (fit on train runners by minimising the 80% interval score, RESEARCH.md): base 9.5%, 5.0% per doubling, 6.0% per year. A 5K → half prediction from a recent race (2.1 doublings) therefore has $\sigma \approx 14\%$, i.e. an 80% range of roughly ±18%. That is the honest spread for recreational runners; the errors are heavier-tailed than a normal, so the 50% range over-covers (~59%) and the 95% range under-covers (~92%).
   - Formula `sigma_pct` is used for the target and for every benchmark distance. Confidence bounds are log-normal at `interval_level` (default 80%, $z \approx 1.282$):
     $$[\text{lo}, \text{hi}] = \left[ T \cdot e^{-z \cdot \sigma / 100}, \; T \cdot e^{+z \cdot \sigma / 100} \right]$$

## References

- Riegel, P. S. (1981). Athletic records and human endurance. *American Scientist*, 69(3), 285–290.
- Minetti, A. E., et al. (2002). Energy cost of walking and running at extreme uphill and downhill gradients. *J Appl Physiol*, 93(3), 1039–1046.
- Péronnet, F., et al. (1991). Modeling endurance running performance at altitude. *J Appl Physiol*.
- Bassett, D. R., & Howley, E. T. (1997). Limiting factors for maximum oxygen uptake. *Med Sci Sports Exerc*.
- Montain, S. J., et al. (2007). Impact of heat and hydration on marathon performance. *Med Sci Sports Exerc*.
- Cameron, D. (1998). Dave Cameron's race time predictor tables. *Runner's World*.
- Daniels, J., & Gilbert, J. (1979). Oxygen Power: Performance Tables for Distance Runners.


## Changelog

- 0.5.0 — New default method `weighted_riegel`: Riegel projections of every race (exponent 1.09 men / 1.06 women / 1.07 unknown, fitted on train), combined by a weighted geometric mean (distance scale 1, half-life 1 year, from RESEARCH_SIMPLE.md), with empirical 50/80/95% bands from a linear quantile regression of the log error on distance gap, years since the last race and 1/races (2,560 train runners; `research_bands.py` → RESEARCH_BANDS.md). Test: MAPE 9.63% → 9.55% (tie), coverage 59/82/92% → 52/81/96%. New params `method`, `riegel_exponent`, `exponent_offset_male`, `exponent_offset_female`, `race_weight_distance_scale`, `race_weight_half_life_years`, `race_combination`, 28 `band_*` coefficients, `band_max_years`, `band_max_races`, `band_scale`; new formulas `exponent`, `race_weight`, `band_log_quantile`, `median_time`, `band_time`. The v0.4.0 method stays available (`method = "curve"`, variant `curve_v04`); `trust_fit` / `static_no_drift` now select it; `pure_riegel` and new `no_gender_exponent` are weighted-Riegel variants. New output contract: 7 quantiles for every curve point and benchmark (60 points 800 m – 50 km; 15K added to benchmarks), target 50%/95% ranges, "Common distances" outcomes, `races_used`; the backtest reports 50/80/95% band coverage. `research.py` / `research_simple.py` pin `method = "curve"` for their v0.4.0 comparisons.
- 0.4.0 (later addition, no default changes) — `research_simple.py` → RESEARCH_SIMPLE.md: simple Riegel variants (weighted races, personal exponent, age/gender exponent).

- 0.4.0 — New backtest data: dated, all-finisher RunSignup results for Ohio 2018–2025 (`download.py`, `pipeline.py` rewritten), runners linked by their own city/state, strictly walk-forward cases (inputs before the target date), 5,000 independent runners split train/test by hash. New `research.py` → `RESEARCH.md`. Defaults changed on the train split and confirmed on test: `use_demographic_priors` true → false, `marathon_curvature` 0.015 → 0.005, new `off_day_tolerance_pct` = 32 (down-weights races much slower than the runner's best), `base_uncertainty_pct` 2.0 → 9.5, `extrapolation_uncertainty_pct` 3.5 → 5.0, `annual_fitness_drift_pct` 3.0 → 6.0 (ranges widened to allow these). Test 80% coverage 46% → 82%, MAPE 9.8% → 9.6%. `demographic_priors.json` rebuilt from train runners (median pair slope). Races accept an optional `date` and the target an optional `target_date` (fractional-year recency). `pure_riegel` now also disables off-day weighting. Backtest groups are scenario × split. Status → calibrated.
- 0.3.0 — Bug fixes: the cohort prior slopes in `demographic_priors.json` were silently replaced by `default_exponent` for every runner (a hard-coded `!= 1.06` check), so all cohorts used 1.054; they are now used, with the new `use_demographic_priors` switch (off in `pure_riegel`). `marathon_curvature` is now always the curvature. 3+ distance fits ignored `fit_weight` and `shrinkage_prior_strength` (hard-coded `max(fit_weight, 0.85)` and `/(span + 1)`) — all multi-distance fits now use the same documented shrinkage. Two distances with a repeated distance mis-assigned weights; the slope is now a recency-weighted least-squares fit. Benchmarks now use the `sigma_pct` / `predict_time` / `predict` formulas; `elevation_multiplier`, `altitude_multiplier` and `transfer_improvement` formulas are now actually used, plus a new `weather_penalty_pct` formula. Hard-coded numbers moved to params (`min_elevation_multiplier`, `weather_dist_exponent`, `assumed_dew_point_ratio`, `stale_weight_factor`, `same_distance_tolerance_doublings`); unused `ideal_temp_f` removed. Unverified sources marked DRAFT. Bad inputs now raise clear `ValueError`s. Backtest data rebuilt: removed answer leakage (an input race at the target distance, often the same finish recorded twice) and mis-classified / duplicated RunSignup results (177 → 135 cases). `demographic_priors.json` rebuilt on the cleaned data (slopes +0.001 to +0.005) and `default_exponent` 1.054 → 1.057 to match its global mean. Status set to `draft` until defaults are tuned.
- 0.2.0 — Log-quadratic curve, demographic priors, fitness transfer, environmental adjustments, GPX parsing.
