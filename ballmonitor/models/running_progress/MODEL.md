# Running progress (`running_progress`)

**Question:** Given a runner's training log up to today, what will their average pace and
weekly distance be in the four weeks before a chosen future date, and will they still be
training?

**Status:** calibrated (fitted on 2019, tested on other athletes in Jan to early Mar 2020;
see [RESEARCH.md](RESEARCH.md)). Public page at /running_progress/: an in-browser training log and forecast (`site.py`,
`web/static/apps/running_progress.js`, checked against `model.py` by `tests/test_running_progress_app.py`).

The owner's aim: predict running progress from current ability and training consistency,
then refine it with logs people enter on the site. This version is the baseline for that:
a few explainable features, every coefficient in `config.toml`, bands from real errors.

## Inputs

| input | meaning | example |
|---|---|---|
| `today` | day the forecast is made (entries on/after it are ignored); default: the day after the last log entry | `2019-12-03` |
| `weeks_ahead` or `target_date` | target date, 4-26 weeks after today; the forecast is for the 4 weeks ending on it | `13` |
| `[[log]]` | dated entries, daily or weekly: `date`, `km` or `miles`, `time` (h:mm:ss) or `minutes` | see `examples/` |
| `weekly_km` + `weekly_minutes` | alternative to `log`: weekly totals, oldest first, the last = the 7 days before today | `[30, 0, 42.5]` |
| `hemisphere` or `country` | `north`/`south`, or a country (southern temperate countries shift the season 6 months) | `"United States"` |
| `gender`, `age_group` | optional, displayed only (they did not improve the fit) | `"M"`, `"35 - 54"` |

Examples: `default` and `patchy_rebuilder` are real anonymised athletes (ids 269 and 227)
of the BMClab dataset on 2019-12-03; `placeholder_daily_miles` is an **invented runner**
(placeholder) showing a daily log in miles with a target date.

## Method

1. **Weekly totals** (`features.py`). The log is summed into 7-day weeks counted back from
   today (week 0 = the 7 days before today), from the week of the first entry, at most
   `lookback_weeks` (26) back; weeks without entries are rest weeks (0 km). A week whose
   average pace is outside [`min_pace_min_per_km`, `max_pace_min_per_km`] (3:00-15:00/km)
   or over `max_week_km` (300) is treated as missing.
2. **Windows.** recent = last `recent_weeks` (4), base = last `base_weeks` (12),
   long = all (<= 26). Pace = total time / total distance (s/km). Km/week = total km /
   non-missing weeks. The model refuses a log with fewer than `min_run_weeks` (3) run
   weeks in the base window.
3. **Features.** `lp_base = ln(base pace)`, `tr_recent = ln(recent pace / base pace)` (0 if
   no recent run), `tr_long = ln(base pace / long pace)`, `share` = run weeks / weeks in
   the base window, `since` = weeks since the last run week, `lk_base = ln(base km/wk +
   km_offset)`, `ktr_recent`, `ktr_long` the same trends for km.
4. **Season.** `season` = mean of `season_<pace|km>_mMM` over the months of the 4 target
   weeks minus the mean over the 12 base weeks (southern hemisphere: month + 6).
5. **Pace** (primary). Location `L = pace_location` =
   lp_base + a + b_r tr_recent + b_l tr_long + b_s season + b_rel (lp_base - ln ref_pace);
   scale `S = pace_scale` = exp(c + c_h ln(h/4) + c_share share + c_rel rel + c_tr |tr_recent|);
   quantile at level tau: `pace_quantile` = exp(L + S z_tau), z_tau = `pace_z_p025` ...
   `pace_z_p975` (the empirical quantiles of the standardised train errors; asymmetric:
   slowing down a lot is more common than speeding up a lot). Median = 50%, bands 50/80/95%
   = 25-75 / 10-90 / 2.5-97.5%.
6. **Weekly km**, given still training: the same structure with `km_location`, `km_scale`,
   `km_quantile` = max(exp(L + S z) - km_offset, 0).
7. **Still training** (at least one run in the 4 target weeks): `p_running` =
   logistic(run_a + run_share share + run_since since + run_level krel + run_h ln(h/4)).
8. **Implied marathon (literature, not validated here):** `tanda_marathon` =
   42.195 (17.1 + 140 exp(-0.0053 K) + 0.55 P) seconds, K = mean weekly km and P = mean
   pace (s/km) over `tanda_weeks` (8) weeks: today from the log, at the target from the
   median km and pace. The note warns outside the paper's 2:47-3:36 range.

Fitted values (RESEARCH.md): the median moves 23% of the way from the 12-week to the 4-week
pace and 67% of the way back towards the 26-week pace; slow runners drift a little faster
and fast ones a little slower; the bands widen with the horizon (about h^0.11) and with an
irregular log, a slow base pace or a recent change of pace.

## Results (out of sample: new athletes, target windows 2020-01-01 to 2020-03-10)

| pace forecast | MAPE % | in 50% | in 80% | in 95% | pinball x100 |
|---|---|---|---|---|---|
| model (default) | 5.70 | 0.541 | 0.834 | 0.961 | 1.755 |
| 12-week pace stays (`persistence`) | 6.27 | 0.536 | 0.827 | 0.960 | 1.965 |
| 4-week pace stays (`last_month`) | 6.84 | 0.538 | 0.833 | 0.962 | 2.146 |

The model beats both naive baselines: 9% lower MAPE and 11% lower pinball loss than
"the 12-week pace stays". Weekly km: median absolute error 32% vs 35% for persistence, and
the persistence median is biased (-9.6%: it misses the January build-up). Still training:
Brier 0.064 vs 0.073 for a horizon-only rate. On 2,000 cases in `data/backtest.csv` run
through `model.py`, `ballmonitor backtest running_progress` gives pace MAPE 6.2% and band
coverage 0.52 / 0.82 / 0.95. In 2020 after March (lockdowns) the gains are similar (MAPE
6.18 vs 6.66). Full tables, by horizon, consistency, gender, age and period: RESEARCH.md.

## Assumptions and known weaknesses

- **Few independent periods.** The fit sees one year (2019); the honest test spans only
  about 2.5 non-overlapping 4-week windows (Jan to early Mar 2020). Errors at other times
  of year, and for other populations, are not measured out of time. 2020 after March is
  COVID-distorted and reported separately.
- **Bands a little wide in the test period** (54/83/96% coverage for 50/80/95%), more so
  for women (59/87/98%); women and 55+ ran ~0.6-1.3% slower than the median.
- **Average pace is not fitness.** It mixes easy runs, workouts and races; more easy volume
  makes it slower. Without heart rate or races the model cannot separate the two.
- **Population:** Strava users who ran a World Marathon Major (76% men, mostly 35-54,
  US/UK); keen, mostly regular runners. Beginners or casual runners may differ.
- **Logging = running:** a runner who stops logging looks like one who stopped running.
- **Weekly resolution:** consistency is measured in weeks, not days.
- The long window is shorter for early-2019 cutoffs (12-26 weeks), as for users with short
  logs; logs under 12 weeks are accepted with a warning (the fit never saw them).
- Seasonal curves are one year of one population; the km curve's spring peak did not
  happen in 2020 (cancelled marathons), where the season terms hurt km forecasts.
- **Tanda times are not validated** (no race results in the data); only 35% of test cases
  fall in the paper's 2:47-3:36 range, and Tanda & Knechtle (2013) found a 28-minute
  standard error on recreational runners.
- Banister fitness-fatigue terms and gender/age were tried and add almost nothing
  (RESEARCH.md, negative results).

## Variants

- `persistence`: 12-week pace and km stay the same, horizon-only bands (baseline).
- `last_month`: the last 4 weeks' pace stays, horizon-only bands (baseline).
- `no_season`: the default refitted without the seasonal terms.

All three are generated by `research.py` (fitted on the same train cases). They change
only the pace and km parameters; the still-training model stays the default.

## Data and reproduction

- Source: Afonseca LA, Watanabe RN, Duarte M (2022), BMClab "A public dataset on
  long-distance running training in 2019 and 2020", Figshare doi:10.6084/m9.figshare.16620238.v5,
  CC BY 4.0 (paper: PeerJ 10:e13192, doi:10.7717/peerj.13192). 36,412 athletes, weekly
  totals for 104 weeks from 2019-01-01 (31 December of each year is not in the weekly bins).
- `python -m ballmonitor.models.running_progress.download` fetches the two weekly parquet
  files (~59 MB) into `data/raw/` (gitignored; resumable, md5-checked, file list from the
  Figshare API). The daily files were not needed.
- `python -m ballmonitor.models.running_progress.research --write-config` (numpy, scipy,
  pandas, pyarrow; ~15 min) builds ~1.2 million cases, fits everything on train athletes'
  2019 targets, writes the fitted values into `config.toml` and the variants, writes
  `data/fit.json`, `data/backtest.csv` and the generated `RESEARCH.md`, and checks that
  `model.py` reproduces the research code on the backtest rows.

## Backtest data

`data/backtest.csv`: 2,000 test-athlete cases (1,200 pre2020, 500 covid, 300 new19), one
row each. Columns: `case`, `split` (pre2020 / covid / new19), `athlete` (BMClab id),
`gender`, `age_group`, `country`, `hemisphere`, `today` (cutoff date), `weeks_ahead`,
`weekly_km` and `weekly_minutes` (space-separated weekly totals before the cutoff, oldest
first, up to 26), `actual_running` (1 if any run in the 4 target weeks), `actual_pace`
(s/km over the 4 target weeks, blank if no run), `actual_km` (mean km/week). Everything
in the inputs is known at the cutoff. `score()` reports pace `abs_pct_error`, `bias`,
`in_50/80/95`, `km_in_80` (only when still training) and `brier_running`,
`log_loss_running`; `backtest_group` = split.

## References

- Afonseca LA, Watanabe RN, Duarte M (2022). A worldwide comparison of long-distance
  running training in 2019 and 2020: associated effects of the COVID-19 pandemic.
  PeerJ 10:e13192. doi:10.7717/peerj.13192. Data: doi:10.6084/m9.figshare.16620238.v5.
- Tanda G (2011). Prediction of marathon performance time on the basis of training
  indices. J Hum Sport Exerc 6(3):511-520. doi:10.4100/jhse.2011.63.05.
- Tanda G, Knechtle B (2013). Marathon performance in relation to body fat percentage
  and training indices in recreational male runners. Open Access J Sports Med 4:141-149.
  doi:10.2147/OAJSM.S44945.
- Banister EW, Calvert TW, Savage MV, Bach T (1975). A systems model of training for
  athletic performance. Aust J Sports Med 7:57-61. Calvert TW, Banister EW, Savage MV,
  Bach T (1976). A systems model of the effects of training on physical performance.
  IEEE Trans Syst Man Cybern SMC-6:94-102.
- Koenker R, Bassett G (1978). Regression quantiles. Econometrica 46:33-50.

## Changelog

- 0.1.1 — public page: `site_*` params for its example tables; `[web] public = true`. No change
  to predictions.

- 0.1.0 — initial version: location-scale forecasts of 4-week pace and weekly km, logistic
  still-training model, empirical bands; fitted on BMClab 2019, tested Jan-Mar 2020.
