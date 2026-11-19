# Progress tracker (`progress_tracker`)

**Question.** Given a goal, a goal date, a plan to get there (even, faster early or faster late,
like a race pacing strategy) and a log of one measure, is the person ahead of or behind the
plan, what will they reach by the goal date at the rate they are keeping, and what do they need
each week from here to still make it?

**Status: draft.** The prediction is a motivational guide, not a tested forecast: there is no
data yet of people's own plans and logs. The background study (RESEARCH.md, `research.py`,
from v0.1.0) found on Lichess, fit20 and Strava logs that a few weeks of pace say little about
the next months, and that newcomers made about 90% of a year's change in the first 26 weeks.
That is why "faster early" is the default plan shape. Logs collected on the site could later
test and improve it.

## Inputs

| input | required | meaning |
|---|---|---|
| `metric` | yes | `chess_rating`, `lift`, `running_pace`, `race_time`, `body_weight`, `body_fat` or `custom` |
| `goal_value`, `goal_date` | yes | the goal (a number, or `m:ss` / `h:mm:ss` for paces and times, as seconds) |
| `shape` | no | `even`, `faster_early` (default) or `faster_late` |
| `start_date`, `start_value` | no | where the plan starts (default: the first entry, and the first entry on or after the start date) |
| `[[entries]]` | no | `date` + `value` |
| `today` | no | default: the last entry's date |
| `scale` | custom only | `log` (% progress) or `linear` (units) |
| `name`, `unit`, `direction` | no | labels only (ahead/behind follows the goal's direction) |

## Method

1. **Scale.** `scale_<kind>`: `log` works in ln(value) (lifts, pace, race times), `linear` in the
   value (ratings, body weight, body fat %). S = start, G = goal on that scale.
2. **Plan.** t = (date − start date) / (goal date − start date), clipped to 0..1. Formulas
   `share_even` = t, `share_faster_early` = 1 − (1 − t)^k, `share_faster_late` = t^k, with
   k = `split_strength`. Formula `planned` = S + share × (G − S).
3. **Adherence f.** For entries after the start date up to today, x = planned − S and
   y = value − S. Weights come from formula `recency_weight` (default equal) and are rescaled
   to sum to n. Formula `adherence` = clamp((Σwxy + λm) / (Σwx² + λm), −max, max), where
   λ = `prior_weight`, m = (planned progress at half-time)², and max = `max_adherence`. This
   is a least-squares ratio of progress made to progress planned, shrunk toward 1 as if λ
   entries had been exactly on plan at half-time. With no entries yet, f = 1.
4. **Predicted result** (formula `predicted`) = S + f × (G − S) on the goal date. If f ≤ 0
   (moving away from the goal), the latest entry is shown instead.
5. **Range** (untested). It needs at least 2 entries. resid var = Σw(y − f x)² / (n − 1) and
   var f = resid var / (Σwx² + λm). Formula `spread` = √(resid var + (G − S)² var f), with
   normal quantiles at `interval_level`.
6. **Tracking.** The latest entry minus the plan on its date. It is reported in units, or in
   % on log scales, as ahead if it lies in the goal's direction.
7. **Re-plan.** From the latest entry to the goal with the same shape. It gives the average
   needed per week, and a week-by-week table from today to the goal date with three columns:
   the plan, the re-plan, and the current track S + f × (planned − S).

8. **Next week's goal.** Worked out on the measure's scale. The base date is the later of the
   latest entry's date and today; "next week" is the base date + 7 days, capped at the goal
   date. step = plan(next) − plan(base); gap = plan(base) − latest value, which is behind
   when it points the goal's way (a stale entry counts as further behind once the plan has
   moved on).
   - **On plan or ahead** (behind by at most `on_track_tolerance` × |step|): the plan's own
     waypoint plan(next), or latest + step if that goes further (never asks to go backwards).
   - **Behind:** formula `next_goal_behind` = latest + step + `catch_up_share` × gap (0.25, a
     judgement). It is capped at the waypoint plan(next), which only binds when
     catch_up_share > 1. It is then raised to at least the re-planned value for next week
     (re-planned from the latest value at the base date to the goal with the same shape: the
     minimum to still reach the goal on time); near the deadline
     that floor wins.
   - **Goal reached or goal date passed:** reported as such instead.

## Assumptions and known weaknesses

- The prediction assumes you keep the same share of your plan. A "faster late" plan therefore
  expects most progress late, and the data suggest that is unrealistic.
- Early in a plan, little progress is planned, so entries carry little information. The prior
  keeps f near 1 then, and f can swing once the prior fades. f is capped at ±`max_adherence`.
- The range only reflects how your entries scatter. Real outcomes vary more (see RESEARCH.md),
  and the range has not been checked against them.
- `split_strength` = 1.6 is a judgement. The study suggests real newcomers are closer to k ≈ 3
  (variant `steep_split`).
- No training inputs are used.

## Variants

- `no_prior`: `prior_weight` = 0 (raw ratio).
- `steep_split`: `split_strength` = 3, close to the newcomer pattern in RESEARCH.md.

## Data

There is no backtest: the model's predictions need people's own plans, which no open dataset
has. `research.py` (background, v0.1.0 study) reads the other models' raw downloads and writes
RESEARCH.md and `data/study.json`. The page's "How real newcomers progressed" table and the
plan hint read `data/study.json`.

Findings of that study, test people scored once:
- A straight line through 8 weeks carried forward missed by 67% after a year for lifts and
  655 rating points for chess, against 13% and 81 for "no change".
- The best damped half-lives were 0–1 week.
- Newcomers (≤ 8 weeks in) changed by +14 / +18 / +20% for lifts and +21 / +32 / +34 points
  for chess after 13 / 26 / 52 weeks.

## Public page

`site.py` builds two views:
- The browser tool `web/static/apps/progress_tracker.js`, a copy of `predict`, checked by
  `tests/test_progress_tracker_app.py` under node.
- The newcomers table.

The log is stored only in the visitor's browser under `bm.log.progress_tracker.v1`:
- `settings.measures[name]` = `{type, unit, direction, scale, shape, start_date, start_value, goal_value, goal_date}`
- `entries` = `[{date, metric, value}]`

Older v1 settings load as they are (`window_weeks` and `target_date` are dropped). The page
supports JSON/CSV export and import, and clearing the log.

## References

- Hall KD et al. (2011). Quantification of the effect of energy imbalance on bodyweight. Lancet 378:826-837.
- Steele J et al. (2022). fit20 training records, OSF jn6ay (CC BY 4.0).
- Afonseca LA, Watanabe RN, Duarte M (2022). BMClab running dataset, PeerJ 10:e13192, figshare 16620238 (CC BY 4.0).
- Lichess open database, database.lichess.org (CC0).

## Changelog

- 0.3.0 (2026-11-19): next week's goal (owner's request): the plan's next step when on plan,
  your own pace when ahead, and a partial catch-up when behind (between the re-plan minimum and
  the plan's waypoint). New params `catch_up_share`, `on_track_tolerance`; formula
  `next_goal_behind`.
- 0.2.0 (2026-11-19): redesign at the owner's request. The model is now a goal plan
  (even / faster early / faster late) with adherence tracking, a predicted result
  (start + f × (goal − start)) and a re-plan. The rolling-line forecast, its damped "likely"
  line, the fitted half-lives and bands, `data/backtest.csv` and `backtest_case` were removed
  (the study stays as background). Status draft.
- 0.1.0 (2026-11-19): rolling straight line + damped "likely" line calibrated walk-forward
  (calibrated).
