# Next pitch type (`next_pitch`)

**Question:** What type of pitch will this pitcher throw next, given the count, the batter and the at-bat so far?

**Status:** calibrated. Defaults come from the walk-forward study in [RESEARCH.md](RESEARCH.md)
(tuned on 2024, tested on 2025–2026); see "Results" below.

## Results

Out of sample, 2025–2026, pitchers with ≥2,000 pitches in the season (539k pitches; RESEARCH.md §1).
Log loss is in bits per pitch (lower is better):

| model | top pick right | bits / pitch |
|---|---|---|
| control (`--variant control`): pitcher's historical mix in this count | 37.3% | 2.23 |
| control + recency weighting | 38.9% | 2.08 |
| context tree (`--variant tree_only`) | 40.8% | 1.98 |
| **gradient-boosted correction (default)** | **44.4%** | **1.86** |
| sequence transformer (research only) | 44.6% | 1.86 |
| average of boosted + transformer (research only) | 44.9% | 1.85 |

The shipped default is within 0.012 bits of the best combination without needing a neural network.
Separate per-pitcher learned models were worse than one shared model (+0.09 bits, §1b). On
`data/backtest.csv` (1,500 sampled 2026 pitches, history cut at the game date) the shipped model
scores 42.9% / 1.31 nats (1.90 bits), the tree 38.3% / 1.41 and the control 36.7% / 1.53.

## Quick start

```bash
pip install -e '.[data,ml]'          # pandas/pyarrow to build data, lightgbm for method = "gbm"
ballmonitor fetch next_pitch          # ~1,100 days of Statcast, cached in data/raw/ (~1–2 h the first time)
ballmonitor run next_pitch            # examples/default.toml
ballmonitor run next_pitch --in pitcher="Logan Webb" --in stand=L --in 'sequence="SI:C CH:B"'
ballmonitor run next_pitch --variant control           # the baseline: pitcher's mix in this count
ballmonitor backtest next_pitch --variant tree_only
python -m ballmonitor.models.next_pitch.research       # re-run the study (needs '.[research]')
```

## Inputs

| input | meaning | example |
|---|---|---|
| `pitcher` | name or MLB id (see `data/pitchers.csv`) | `"Tarik Skubal"` |
| `batter` | optional name or id (see `data/batters.csv`); gives side and stats | `"Aaron Judge"` |
| `stand` | batter side `L`/`R` (switch hitters `S` bat opposite the pitcher); default from `batter`, else `R` | `"L"` |
| `sequence` | this at-bat's pitches so far, `TYPE:RESULT` (B ball, C called strike, S swinging strike, F foul; Statcast descriptions like `called_strike` also work). Every pitch needs a result; X (in play) and H (hit by pitch) end the at-bat, so they can't appear here | `"FF:C CH:B FF:F"` |
| `balls`, `strikes` | count; defaults to the count the sequence implies | `1`, `2` |
| `outs`, `bases`, `inning`, `tto`, `score_diff` | situation (`bases` = occupied bases, e.g. `"13"`; `tto` = time through the order; `score_diff` = pitching team minus batting team) | `1`, `"1"`, `4`, `2`, `0` |
| `earlier_in_game` | optional: this pitcher's pitches earlier in the game (same format as `sequence`, X and H allowed) | `"FF:B SL:C ..."` |
| `pitch_count`, `batters_faced`, `days_rest` | optional game context for the boosted model | `54`, `17`, `5` |
| `prev_x`, `prev_z`, `prev_speed`, `prev_zone` | optional location (ft), speed (mph) and Statcast zone of the previous pitch | `0.4`, `3.1`, `96.5`, `3` |
| `bat_woba`, `bat_k`, … | optional overrides of the batter features listed in `data/batters.csv` | `0.360` |
| `as_of` | use only history before this date (for backtests); default = all data | `"2026-06-01"` |

Pitch types are Statcast codes: FF 4-seam, SI sinker, FC cutter, SL slider, ST sweeper, SV slurve,
CU curveball, KC knuckle curve, CH changeup, FS splitter, FO forkball, KN knuckleball, EP eephus,
SC screwball (FA is folded into FF and CS into CU).

## Method

### 1. Pitcher history

Each pitcher's pitches since 2021 are read from `data/pitchers/<id>.csv.gz`. Every pitch gets a
weight from formula `recency_weight`, `0.5 ** (age_days / half_life_days)`, so the current arsenal
dominates. This is the control's weakness: a pitcher who added a sweeper last month still looks
like last year's pitcher if all history counts equally.

### 2. Context tree (`method = "tree"`, and the base of `"gbm"`)

The idea comes from the [Aaronson oracle](https://aaronsonoracle.com/): count what a player did
after each recent pattern and predict the most common continuation. Pitchers have far fewer
"keystrokes" in each pattern than that game needs, so each pattern is smoothed toward a broader
one. Starting from the league mix for the pitcher's hand, the model walks down `chain`
(default: batter side → count → previous pitch type). At each level it applies formula `shrink`:

    p_level(x) = (n(x) + strength · p_parent(x)) / (N + strength)

- `n(x)` is the recency-weighted number of times the pitcher threw type `x` in *this* context
  (e.g. 1-2 count, left-handed batter, previous pitch a fastball).
- `N` is the total over all types in that context.
- `strength_<level>` (in pseudo-pitches) sets how much evidence a context needs before it moves
  away from its parent.

Thin contexts therefore fall back to broader ones, and a pitch never seen in a context keeps a
small probability. The pitches already thrown in this at-bat are added to the history first (as
they would be in a live feed).

### 3. Gradient-boosted correction (`method = "gbm"`, default)

A LightGBM multiclass model, trained on every pitcher's pitches 2022–2025, starts from the
context tree's log-probabilities and learns corrections. It uses:

- the pitcher's own recency-weighted mix in 11 contexts: overall; count; count × side;
  + previous pitch; + its result; + the pitch before; side; previous pitch × result; vs this
  batter; today's game; first pitch after the previous at-bat's last pitch;
- count, outs, runners, inning, score, time through the order, pitch number in the at-bat and
  game, batters faced, days of rest;
- the previous two pitches' types and results, and the previous pitch's location and speed;
- batter stats (recency-weighted, from previous days): wOBA, SLG, K%, BB%, whiff and chase
  rates, and the fastball/breaking/off-speed mix pitchers of this hand throw him.

The model is shared by all pitchers. It is "per pitcher" because everything it reads is that
pitcher's own history. RESEARCH.md §1b shows a separate learned model per pitcher does worse.
The correction is scaled by `gbm_weight`; the base it corrects uses the tree settings it was
trained with (stored in `data/meta.json`), not the `chain`/`strength_*` params, which only
affect `method = "tree"`. The shipped model is the one trained for the 2026 test season
(through 2025), so backtests on 2026 stay out-of-sample.

### 4. Output

One probability per pitch type, most likely first. Types below `min_display_prob` are grouped
as "Other / new pitch". `temperature` can flatten or sharpen the distribution.

## Assumptions and known weaknesses

- Statcast pitch labels are algorithmic and change over time (sweeper/slurve labels; occasional
  reclassification). A relabelled pitch looks new until history builds up.
- Earlier pitches in the same game feed the boosted model only through `earlier_in_game`, and
  only its "today's mix" feature. In the study every earlier pitch updated every table, so live
  use without `earlier_in_game` is slightly less informed than the study.
- When no batter is given, the boosted model uses league-average batter features.
- Rookies and pitchers with few pitches fall back toward the league mix; the study's headline
  numbers are for pitchers with ≥2,000 pitches in a season.
- Pitchers and catchers mix on purpose. Even the best model is wrong on about half of pitches;
  the probabilities, not the top pick, are the useful output.

## Variants

| variant | what it changes |
|---|---|
| `control` | the baseline: pitcher's historical mix in this count, all history equally weighted, no learned correction |
| `tree_only` | context tree alone (stdlib, fully transparent) |
| `no_recency` | context tree with no recency decay |
| `calibrated` | boosted model with `gbm_weight = 0.95`, `temperature = 1.05`: 43.2% top pick on `data/backtest.csv` (log loss and Brier unchanged at 1.31 / 0.679). These two values were chosen by looking at that same backtest, so the gain is in-sample (hindsight) and not out-of-sample evidence; not promoted to the default |

## Data

`ballmonitor fetch next_pitch` downloads every regular-season pitch since 2021 from Baseball
Savant's Statcast search (one request per game day, cached in `data/raw/days/`), plus player
names from the MLB Stats API. It then builds:

| file | contents |
|---|---|
| `data/pitchers/<id>.csv.gz` | one pitcher's pitches: `date, game_pk, ab, pn, balls, strikes, stand, pt, res, outs, runners, tto, batter` |
| `data/pitchers.csv` | pitcher index: id, name, hand, pitches per season (pitchers with ≥100 pitches) |
| `data/batters.csv` | batter id, name, side, last-365-day PA/OPS/wOBA/K%/whiff%/chase%, and the model's recency-weighted `bat_*` features (seen-mix per pitcher hand) |
| `data/meta.json` | data end date, league prior mix by pitcher hand, boosted-model settings |
| `data/gbm_model.txt` | the boosted model (written by `research.py`) |
| `data/pitches/<season>.parquet` | all pitches with derived columns (large, gitignored; for research) |

## Backtest data

`data/backtest.csv`: 60 randomly sampled 2026 pitches from each of the 25 busiest 2026 pitchers.
Each row has only what was known before the pitch.

`pitcher_id, pitcher, as_of, balls, strikes, stand, sequence, earlier_in_game, outs, bases, tto,
inning, score_diff, pitch_count, batters_faced, days_rest, prev_x, prev_z, prev_speed, prev_zone,
batter_id, bat_* (as-of batter features), actual` (the Statcast pitch type thrown).

History is cut at `as_of` (the game date), so earlier pitches in the same game appear only
through `sequence` and `earlier_in_game`. Per-count results are in RESEARCH.md §3.

## References

- Aaronson oracle (Scott Aaronson's predictability game): https://aaronsonoracle.com/
- Baseball Savant Statcast search CSV: https://baseballsavant.mlb.com/statcast_search
- Prediction by partial matching / back-off smoothing, the idea behind the context tree: Cleary & Witten (1984), *Data compression using adaptive coding and partial string matching*.
- Ke et al. (2017), *LightGBM: A highly efficient gradient boosting decision tree*.
- Ganeshapillai & Guttag (2012), *Predicting the next pitch*, MIT Sloan Sports Analytics Conference: earlier work, fastball vs non-fastball only.

## Changelog

- 0.1.2: public site page (`site.py`) and its `site_method`, `site_pitchers` and `site_mix_min_pitches` params; predictions unchanged.
- 0.1.1: input checks only (no change to defaults or results): sequence pitches must have a known
  result code, and X/H can't appear in `sequence`; `outs` must be 0–2 and `tto` at least 1; `chain` is checked
  against the tree levels (it used to fail on `batter`/`game` with an unknown-parameter error); a
  `strength_*` of 0 on an empty context keeps the parent level's mix instead of dividing by zero.
  The `calibrated` variant is now labelled as tuned in-sample on the backtest.
- 0.1.0: first version: context tree (half-life 15 days; chain side → count → previous pitch) + gradient-boosted correction trained 2022–2025; study in RESEARCH.md.
