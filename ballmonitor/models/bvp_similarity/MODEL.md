# Batter vs. Pitcher Similarity Matchup (`bvp_similarity`)

**Question:** What is the expected performance (xwOBA, K%, BB%) when this batter faces this pitcher?

**Status:** calibrated. Walk-forward study in `research.py` → `RESEARCH.md`: league rates measured
from earlier seasons, tuning on 2025 matchups (tables from 2021–2024), report on 2026 matchups
(tables from 2021–2025). See "Backtest results".

## The Sabermetric Problem

Batter vs. pitcher (BvP) samples are tiny (a few to ~20 PA), so the observed BvP line is mostly
noise. This model starts from each player's regressed talent, combines them with Log5 and a
platoon split, and then adds small, backtested adjustments from direct BvP history, matchups
between similar pitchers and similar batters, and a count-by-count micro-simulation. The honest
headline from the study: the regressed Log5 baseline does almost all the work; the extra pieces
improve it only slightly.

## Inputs

| input | meaning | example |
|---|---|---|
| `pitcher` | Pitcher full name (accents optional) or MLB ID; required. Must have 150+ pitches in 2021–2025 | `"Tarik Skubal"` or `669373` |
| `batter` | Batter full name (accents optional) or MLB ID; required. Must have 40+ PA in 2021–2025 | `"Aaron Judge"` or `592450` |
| `pa` | Optional: number of PAs the xwOBA range is for (default `interval_pa` = 3) | `4` |
| `k_pitchers` | Optional override for pitcher peer pool size | `8` |
| `k_batters` | Optional override for batter peer pool size | `12` |

## Method

### 1. Feature Representation

Every pitcher is represented by a 23-dimensional profile $\mathbf{v}_P$:
- **Repertoire Mix**: Four-seam (`pct_ff`), sinker (`pct_si`), cutter (`pct_fc`), slider (`pct_sl`), sweeper (`pct_st`), curveball (`pct_cu`), changeup (`pct_ch`), splitter (`pct_fs`).
- **Velocity**: Fastball average speed (`velo_fb`), breaking ball average speed (`velo_br`), and offspeed velocity separation (`velo_diff`).
- **Command & Inducement**: Zone % (`zone_pct`), chase rate outside the zone (`chase_pct`), swinging-strike whiff % (`whiff_pct`), called strikes + whiffs (`csw_pct`).
- **Count Strategy**: First-pitch (0-0) strike % (`f_strike_pct`), 0-0 zone % (`f_zone_pct`), 2-strike zone % (`ahead_zone_pct`), behind-in-count fastball % (`behind_fb_pct`).
- **Outcomes & Batted Ball Quality**: Hard hit rate (`hard_hit_pct`), strikeout rate (`k_pct`), walk rate (`bb_pct`), and expected wOBA allowed (`xwoba`).

(`gb_pct`, `ahead_whiff_pct`, `behind_zone_pct` and the batter's in-zone swing rate `z_swing_pct` are
also built but are not similarity features; `behind_zone_pct` and `z_swing_pct` feed the micro-simulation.)

Every batter is represented by a 16-dimensional profile $\mathbf{u}_B$:
- **Plate Discipline**: Chase rate (`chase_pct`), in-zone contact % (`z_contact_pct`), overall whiff % (`whiff_pct`), strikeout rate (`k_pct`), walk rate (`bb_pct`).
- **Count Aggression & Protection**: First-pitch swing % (`f_swing_pct`), 2-strike chase expansion (`chase_2s_pct`), 2-strike whiff rate (`whiff_2s_pct`).
- **Pitch Family Whiff Vulnerability**: Whiff % on fastballs (`whiff_fb`), breaking pitches (`whiff_br`), offspeed pitches (`whiff_os`), and high-velocity fastballs $\ge 95\text{ mph}$ (`whiff_hi`).
- **Batted Ball Quality**: Hard hit % (`hard_hit_pct`), ground ball % (`gb_pct`), fly ball % (`fb_pct`), and overall xwOBA (`xwoba`).

### 2. Talent Baseline: regressed platoon Log5

Each rate is regressed with formula `regress` = $(x n + \text{prior}\, n_0)/(n + n_0)$: first the
player's overall rate toward the league average (`league_*`), then his platoon split (batter vs the
pitcher's hand, pitcher vs the batter's side) toward that regressed overall rate. $n_0$ is
`regress_xwoba_pa` (800), `regress_k_pa` (400) or `regress_bb_pa` (200; walks have no split in the
tables, so only the overall rate is regressed). The batter and pitcher rates are combined with
formula `log5`:
$$p_{\text{matchup}} = \frac{p_B p_P / p_L}{p_B p_P / p_L + (1 - p_B)(1 - p_P)/(1 - p_L)}$$
Without the regression (v0.2) a 40-PA batter's raw rates went straight into Log5; on 2026 the raw
Log5 was no better than league average on K/BB and worse on xwOBA (RESEARCH.md).

### 3. Multidimensional Similarity Engine

Pitchers and batters are clustered using standardized Euclidean distance within their respective throwing/batting hands:
$$D(P, P_i) = \sqrt{\sum_{k} w_k \left(\frac{x_{P,k} - x_{P_i,k}}{\sigma_k}\right)^2}$$
(all feature weights $w_k = 1$ in the shipped model.)
Pairwise peer weights are computed using a Gaussian similarity kernel:
$$S(P, P_i) = \exp\left(-0.5 \left(\frac{D(P, P_i)}{\tau}\right)^2\right)$$
where $\tau$ is the median non-zero distance.

### 4. Cross-Archetype Matchup Pooling

The model identifies all historical matchups where a peer from the top-$K$ pitcher pool faced a peer from the top-$M$ batter pool. Each historical plate appearance is weighted by the product of both player similarities:
$$w_{i, j} = S(P, P_i) \cdot S(B, B_j)$$
$$\hat{y}_{\text{archetype}} = \frac{\sum_{i, j} w_{i, j} \cdot y_{i, j}}{\sum_{i, j} w_{i, j} \cdot N_{i, j}}$$

### 5. Direct BvP history and shrinkage blend

Direct 2021–2025 history of this pair gets weight `bvp_weight` = $n/(n + N_0)$, $N_0$ =
`bvp_shrinkage_n0` (250); the archetype pool gets `archetype_weight` =
$\min(w_{\max}, (1 - w_{\text{direct}})\,\text{eff}/(\text{eff} + M_0))$ with $w_{\max}$ =
`max_archetype_weight` (0.10) and $M_0$ = `archetype_shrinkage_m0` (350); the baseline gets the
rest (formula `blend_estimate`). The same weights are used for xwOBA, K% and BB%.

### 6. Count micro-simulation (absorbing Markov chain)

A PA is a chain over counts $(b, s)$, absorbing in K, BB or ball in play. Counts fall in four
groups: `first` (0-0), `even` (1-0, 0-1, 1-1), `behind` (2-0, 3-0, 2-1, 3-1), `two` (two strikes).
For each pitch in group $g$:

- zone rate $z$ = the pitcher's own rate for the group (`f_zone_pct`, `zone_pct`, `behind_zone_pct`,
  `ahead_zone_pct`);
- in-zone swing = `ms_<g>_zone_swing` × batter aggressiveness (0-0: `f_swing_pct` / `league_f_swing_pct`;
  else `z_swing_pct` / `league_z_swing_pct`);
- out-of-zone swing = `ms_<g>_chase` × chase factor, chase factor = log5(batter chase, pitcher
  chase, `league_chase_pct`) / `league_chase_pct`;
- whiff per swing = `ms_<g>_whiff` × whiff factor (same Log5 ratio with `league_whiff_pct`);
- contact is foul with `ms_foul_share`, else a ball in play; two-strike fouls keep the count;
- a taken in-zone pitch is a called strike with `ms_<g>_cs_zone`, a taken out-of-zone pitch with
  `ms_<g>_cs_out`; otherwise a ball.

All `ms_*` and `league_*` rates are measured league averages from 2021–2025 pitches (RESEARCH.md
section 1). v0.2 made every take a called strike with probability $z$ regardless of location and
used hand-set constants; that produced P(K) 34.9% and P(BB) 3.0% on 2026 against 22.4% / 8.5%
observed. The rebuilt chain gives 20.6% / 10.5% PA-weighted — still biased (too few Ks, too many
walks), which is why it gets no weight for K% and BB%.

Micro-sim xwOBA = P(BB) × `woba_bb_weight` + P(BIP) × xwOBA per BIP + `ms_xwoba_offset` (−0.021,
the 2025 mean residual), where xwOBA per BIP = (batter xwOBA − 0.69 × BB%) / (1 − K% − BB%) clipped
to `ms_bip_xwoba_min`–`ms_bip_xwoba_max` (0.28–0.55; the old 0.46 cap pulled elite hitters down).

### 7. Final blend and clamps

Formula `final_microsim_blend` = $(1 - w)\,\text{blend} + w\,\text{micro-sim}$ with
$w$ = `microsim_weight` (0.2) for xwOBA and `microsim_weight_rates` (0) for K% and BB%. Results are
clamped to `xwoba_min`–`xwoba_max`, `k_pct_min`–`k_pct_max`, `bb_pct_min`–`bb_pct_max`.

### 8. xwOBA range

The 80% range (`interval_level`) is for the xwOBA **observed over `pa` plate appearances**, not
for true talent: half-width = formula `interval_half_width` =
$z\sqrt{\texttt{interval\_talent\_sd}^2 + \texttt{per\_pa\_xwoba\_sd}^2 / \text{pa}}$, floored at 0.
Both terms (0.15 and 0.25) were fitted on 2025 so that each PA bucket covers about 80%. They are
coverage-fitting constants: one PA's xwOBA is lumpy (0 for every strikeout), so the raw per-PA SD
(0.37) over-covers single PAs.

## Backtest results (RESEARCH.md; 2026, out of sample)

20,000 uniformly sampled 2026 pitcher-batter pairs (40,645 PA, 626 pitchers, 515 batters).
The values were chosen on 20,000 pairs from 2025 with tables from 2021–2024. There is one tuning
season and one test season. Pairs share players, so the intervals below resample pitchers.
Metrics are per PA and PA-weighted.

| model | log loss K/BB/other | K log loss | BB log loss | xwOBA MSE | mean K% | mean BB% |
|---|---|---|---|---|---|---|
| league average | 0.79963 | 0.53171 | 0.29054 | 0.06725 | 22.8% | 8.2% |
| raw Log5 (v0.2 baseline) | 0.79802 | 0.53157 | 0.28989 | 0.06738 | 23.1% | 8.1% |
| regressed Log5 | 0.78560 | 0.52182 | 0.28744 | 0.06638 | 22.7% | 8.0% |
| v0.2.1 defaults | 0.79453 | 0.52843 | 0.29059 | 0.06663 | 26.7% | 6.6% |
| **v0.3.0 (shipped)** | **0.78535** | **0.52175** | **0.28725** | **0.06632** | 22.7% | 8.0% |
| observed | | | | | 22.4% | 8.5% |

- v0.3.0 beats v0.2.1 by 0.0089 log loss per PA (90% interval 0.0077–0.0102) and by 0.00025 in
  xwOBA MSE (0.00008–0.00044). Most of the gain comes from regressing the player rates.
- Compared with regressed Log5 alone, the archetype pool, direct BvP and micro-sim add only
  0.00025 log loss (0.00010–0.00040) and 0.00005 xwOBA MSE (0.00001–0.00010). That is real but small.
- The range covers 80.0% of 2026 pairs (v0.2.1's ±0.045 covered 11.0%). By PA it covers 80.5% (1 PA),
  78.0% (2), 79.6% (3–4), 86.7% (5–7) and 91.4% (8+), so it is too wide for long histories.
- The older 1,000-case case-MAE table (v0.2.1 docs) is not comparable: its actuals over 1–14 PA
  were mostly noise, and it was partly in-sample.

`ballmonitor backtest bvp_similarity` scores the shipped 2,000-case `data/backtest.csv` (a different
random sample of 2026 pairs) case by case. It reports xwOBA MAE / bias / 80% coverage and per-PA
K/BB/other log loss and Brier score. Use `--variant log5_only` and `--variant league_average` for
the benchmarks.

## Backtest data

`data/backtest.csv` is built by `build.py` from the 2026 season, and all model tables use 2021–2025 only.
It is a uniform random sample (seed 42) of 2,000 pitcher-batter pairs whose players have profiles.
Columns: `pitcher, pitcher_name, batter, batter_name` (MLB ids and names), `pa` (2026 PAs in the
pair), `observed_xwoba` (summed xwOBA value / PA), `observed_k_pct`, `observed_bb_pct`,
`k, bb, h, hr` (counts), `delta_re` (summed run expectancy change). `research.py` builds its own
folds (20,000 pairs each) under `data/raw/folds/` (gitignored), and writes `data/research.json`.

## Assumptions and known weaknesses

- The micro-simulation is still biased at the league level (20.6% K / 10.5% BB vs 22.4% / 8.5%):
  it assumes the same whiff rate in and out of the zone and ignores HBP and sequencing. It
  therefore gets no weight for K% and BB%, and only 0.2 for xwOBA. Its K/BB numbers are still shown
  for interest.
- The archetype pool and direct BvP history add little beyond the regressed baseline; a cap of 0.1
  was best on 2025. The similarity weights and pool sizes (`k_pitchers`, `k_batters`) were not tuned.
- Profiles are 2021–2025 career aggregates with no recency weighting or aging, and the regression
  ignores that, so arsenal or skill changes are slow to show.
- Walks have no platoon split. The range is a normal approximation fitted for coverage, and it
  over-covers pairs with 5+ PA.
- Pitcher peers share the pitcher's throwing hand. Batter peers share the batter's side (switch
  hitters are compared with all batters).
- Results come from one tuning season and one test season.

## Data

`ballmonitor fetch bvp_similarity` needs `pip install -e '.[data]'` and scikit-learn. It builds the
tables from `next_pitch`'s pitch parquet files (`next_pitch/data/pitches/*.parquet`), so run
`ballmonitor fetch next_pitch` first. Outputs: `data/pitchers.parquet|csv`, `data/batters.parquet|csv`,
`data/matchups.parquet`, `data/backtest.csv`, `data/meta.json`. The v0.3.0 build counts only
PA-ending batted balls as balls in play: Aaron Judge has 1,807 BIP in 3,071 PA and 60.7% hard-hit
(the old build counted fouls: 3,510 "BIP", 36.2%).

## Variants

- `log5_only`: benchmark, regressed Log5 baseline alone.
- `league_average`: benchmark, league rates for every matchup.
- `pure_baseline`: regressed Log5 with direct BvP shrunk hard (N0 = 5000) and pool/micro-sim off.
- `no_microsim`: micro-sim off for xwOBA too.
- `high_microsim`: micro-sim weight 0.5 for all three (worse on 2025).
- `trust_archetype`: archetype cap 0.70, `archetype_shrinkage_m0 = 150` (not supported by 2025: caps above 0.2 lost).
- `trust_direct_bvp`: `bvp_shrinkage_n0 = 30` (worse on 2025).

## References

- Tango, T., Lichtman, M., & Dolphin, A. (2006). *The Book: Playing the Percentages in Baseball*. Potomac Books.
- Silver, N. (2003). *PECOTA: Player Empirical Comparison and Optimization Test Algorithm*. Baseball Prospectus.
- Carleton, R. A. (2013). *The Sample Size Spectrum*. Baseball Prospectus.

## Changelog

- 0.3.0 — Model change, chosen walk-forward (tune 2025, test 2026; RESEARCH.md).
  - Data rebuilt with the batted-ball fix (BIP no longer includes fouls).
  - Player rates are now regressed to league, and splits to the player's overall rate, before
    Log5 (new params `regress_*_pa`, formula `regress`).
  - Micro-sim rewritten. Takes are called strikes by location (v0.2 used the zone rate for every
    take). It has four count groups of measured league rates (`ms_<group>_*`) and Log5
    chase/whiff matchup factors, and a new batter feature, `z_swing_pct`.
  - Blend values were re-chosen: N0 120→250, archetype cap 0.5→0.1, micro-sim weight 0.3→0.2
    for xwOBA and 0 for K/BB (new `microsim_weight_rates`), BIP clip max 0.46→0.55, offset
    0.021→−0.021.
  - League params are now measured from 2021–2025 only.
  - The range is now for the xwOBA observed over `pa` PAs (new input `pa` and params
    `interval_pa`, `per_pa_xwoba_sd`, `interval_talent_sd`, `interval_level`; formula
    `interval_half_width`). It replaces `interval_half_width` = 0.045. Coverage on 2026 is
    80.0%, was 11.0%.
  - The backtest also scores K/BB per PA (custom `score()`) and uses a uniform random sample of
    2,000 pairs. Added the `log5_only` and `league_average` benchmark variants.
- 0.2.1 — No change to results (backtest identical). Micro-simulation constants, the walk wOBA
  weight, the 0.021 offset, the BIP xwOBA clip and the final plausibility clamps moved from
  model.py into params (sources marked DRAFT); K%/BB% now use the `final_microsim_blend` formula;
  swing/whiff rates are clipped to [0, 1]. Unknown names raise a ValueError with suggestions and
  match without accents; pitcher and batter are required (they silently defaulted to Skubal/Judge).
  Similar-player rows show similarity as a number, not a probability, and fit in 78 columns.
  `interval_half_width` source corrected (it covers 19% of backtest matchups, not 80%). Docs fixed
  (feature lists, micro-sim method, backtest columns, weaknesses). `features.py`: balls in play no
  longer include fouls (applies to the next data build).
- 0.2.0 — Integrated count-conditioned pitch-by-pitch Markov micro-simulation; added 0-0 strike rates, 2-strike chase expansion, and behind-in-count fastball dependencies.
- 0.1.0 — Initial implementation with 19 pitcher features, 13 batter features, k-NN similarity, archetype sample pooling, and Empirical Bayes shrinkage.
