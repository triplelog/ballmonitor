# MLB bullpen usage (`mlb_bullpen`)

**Question:** Which relievers will pitch out of the bullpen in today's game?

Simulates today's game $N$ times (Monte Carlo plate appearances, base-out states and score),
with a starter hook, reliever hooks and the 3-batter minimum. Each time the manager needs a
reliever, an available arm is picked by a softmax over a simple, readable score. The score's
weights were **fitted on every real bullpen call of the 2025 season** (conditional logit).
Since v0.5.0 the simulated frequencies are then **recalibrated and blended with a direct
logistic model** on the same pre-game facts (rest, usage, role, starter length, pool size,
team tendency); all weights fitted on 2025 and tested on the 2026 season.
Since v0.6.0 it also turns the expected usage into **bullpen runs vs average / vs usual**:
each reliever's shrunk runs-per-out rating × his expected outs today (RESEARCH_RUNS.md).

---

## Inputs

| input | meaning |
|---|---|
| `starter_name`, `starter_hand` | today's starter, "R"/"L" |
| `starter_stamina` | expected pitch count (the backtest uses the mean of his last 5 starts); default `starter_stamina_default` |
| `is_home`, `off_day_tomorrow` | booleans (default true / false) |
| `lineup` | opponent batting order handedness, "R" / "L" / "S" |
| `team_recent_relievers`, `team_recent_games` | optional: pool relievers the team used per game over its last games (earlier dates only), and how many games that is |
| `league_recent_relievers` | optional: league average of the same over the last 30 days |
| `[[relievers]]` | the bullpen (see below) |

Each reliever: `name`, `hand`, `pitches_days` = pitches on each of the last 5 days
`[yesterday, 2 days ago, ..., 5 days ago]`, optional `role` (`closer` / `setup` / `middle` /
`long`; missing or `"auto"` = inferred), and optional usage history over his last 30
roster-games: `games` (roster-games), `apps` (relief appearances), `firsts` (times first out
of the pen), `saves`, `holds`, `finishes` (games finished), `outs` (outs in relief).
Run prevention (optional, v0.6.0): `ra_outs` and `ra_runs` = outs recorded and runs scored
while he was on the mound over his earlier relief outings (the backtest uses every earlier
relief outing since 2025 opening day, any team); missing = no history (rating = prior).
Without history a reliever gets the league-average usage term (0) and, unless a role is
given, role `middle`. Roster flags (optional): `active = false` = not on today's active
roster (IL, optioned, DFA): he cannot pitch and gets probability 0; `new_arrival = true` =
joined the active roster today (recalled / activated / acquired). The pool should be today's
active roster (relievers only; rotation starters left out). Without the tendency inputs the
tendency term is 0.

---

## Method

1. **Roles** (`ledger.infer_roles`, only for relievers without a given role): closer = most
   saves in his history if ≥ `closer_min_saves`; setup = next `setup_count` arms by holds
   (≥ `setup_min_holds`); long = ≥ `role_min_apps` outings averaging ≥ `long_min_outs_per_app`
   outs; everyone else middle. The thresholds were chosen by a grid on 2025 calls.
2. **Availability (hard rules)**: unavailable after pitching `max_consecutive_days` days in a
   row, `max_pitches_yesterday`+ pitches yesterday, or `max_pitches_3d`+ over 3 days.
3. **Score of each available reliever** when a call is made:

   score = `role_<role>` + `sit_<situation>_<role>` + usage + `platoon_bonus` × platoon − fatigue

   * middle relievers and the `middle` situation are the reference (0);
   * **situation** (`simulator.classify_situation`, first match): `save` (9th+, lead 1..
     `save_lead_max`), `late_tie` (9th+, tied or down ≤ `close_deficit_max`), `blowout`
     (margin ≥ `blowout_margin`), `fireman` (from `close_game_inning`, close, Leverage Index ≥
     `li_extreme_threshold`), `late_close` (from `close_game_inning`, lead within
     −`close_deficit_max`..`close_lead_max`), `late_other` (from `close_game_inning`, other),
     `early` (by `early_exit_inning`), else `middle`;
   * **usage** = `usage_weight` × ln(rate / `usage_prior_rate`), rate = (apps +
     `usage_prior_games` × `usage_prior_rate`) / (games + `usage_prior_games`): who the manager
     has actually been using lately;
   * **platoon** = 1 if ≥ `platoon_min_batters` of the next 3 batters hit from his side;
   * **fatigue** = config formula `fatigue_penalty` (yesterday, back-to-back, 3 straight days,
     pitches over 3 days, `high_workload_pitches`+ yesterday), × `off_day_tomorrow_discount`
     when tomorrow is an off day.

   P(reliever i) = exp(score_i / `temperature`) / Σ_j exp(score_j / `temperature`).
   With `temperature` = 1 the weights are exactly the fitted logit coefficients.
4. **Game engine**: plate-appearance outcomes with a simple platoon split; pitches per PA ~
   rounded Normal(`pitches_per_pa`, `pitches_per_pa_sd`). Starter hook by pitch count vs
   stamina (`hook_*`, `starter_max_over`), times through the order (`tto_*`), late innings
   (`late_hook_*`), jams (`jam_*`, `blowup_runs`). Relievers: one inning (`reliever_max_outs`),
   sometimes a second (`reliever_extend_prob`), long men longer (`long_*`), mid-inning hooks
   only after 3 batters (`reliever_mid_*`, `reliever_traffic_*`). Hook settings were chosen on a
   home/away-balanced 2025 sample to
   match 2025 relievers per game and starter outs.
5. **Simulated frequencies** over `num_simulations` games (`seed` fixes the result):
   P_sim(appear), P_sim(first out of the pen), expected IP/pitches and P(save) per reliever.
6. **Team tendency** (`tendency.py`): shrunk = (n × `team_recent_relievers` +
   `tendency_prior_games` × `league_recent_relievers`) / (n + `tendency_prior_games`);
   log_ratio = ln(shrunk / `bullpen_baseline_relievers`).
7. **Direct model** (`calibration.py`): P_direct = logistic(Σ `direct_<feature>` × feature)
   over `intercept`, role dummies, usage (same ln-rate as the score), pitched yesterday,
   back-to-back, pitched 2 days ago, pitches over 3 days / 10, high workload yesterday,
   ruled out by the hard rules, starter length ln(stamina / `starter_stamina_default`),
   long × starter length, off day tomorrow, home team, ln(available arms), log_ratio,
   new arrival.
8. **Reported P(appear)** = logistic of config formula `appear_logit`:
   `calib_intercept_<role>` + `calib_slope` × logit P_sim + `tendency_weight` × log_ratio +
   `blend_weight_direct` × logit P_direct (P_sim clipped to [0.5/N, 1 − 0.5/N]). With
   intercepts 0, slope 1 and the two weights 0 it is the simulation as-is
   (`variants/simulation_only.toml`).
9. **Reported P(first)** = softmax over active arms of `first_weight_sim` × ln P_sim(first) +
   `first_weight_direct` × Σ `first_direct_<feature>` × feature (shrunk first-out rate
   ln((firsts + `first_prior_games` × `first_prior_rate`) / (games + `first_prior_games`) /
   `first_prior_rate`), role, rest, workload, hard-rule flag, long / setup × starter length,
   new arrival).
10. The primary outcome is the most likely arm. Arms with `active = false` get 0.
11. **Bullpen runs** (`runs.py`, v0.6.0):
    * rating_i (runs per out) = config formula `reliever_rating` =
      (ra_runs + `runs_prior_outs` × `runs_prior_rate`) / (ra_outs + `runs_prior_outs`);
      no history → `runs_prior_rate`. Shown per arm as "RA9" (= rating × 27) in the note.
    * expected outs xOuts_i = P(appear) × simulated outs per simulated appearance
      (`runs_outs_source` = "reported"; "simulated" = simulated outs per game);
      X = Σ xOuts_i, E = Σ xOuts_i × rating_i.
    * **Bullpen runs vs average** = config formula `bullpen_runs_vs` =
      `runs_scale` × (E − X × baseline) with baseline = `runs_league_rate`: positive = more
      runs than a league-average bullpen pitching the same expected outs.
    * **Bullpen runs vs usual**: same formula, baseline = the pool's ratings weighted by each
      arm's recent relief `outs` (its usual usage mix): today's availability effect alone.
    * **Expected bullpen runs** = X × `runs_league_rate` + vs average; the note shows an
      interval ± `runs_interval_halfwidth` × √X (floored at 0 runs), fitted for
      `runs_interval_level` coverage. The interval is in the note and `extras`, not an
      interval column (that would push the shared table past 78 columns).

---

## Assumptions & known weaknesses

- PA event rates, runner advancement, our offense's run distribution and the Leverage Index
  table are league-average constants in `simulator.py` (game engine, not policy); pitcher and
  batter quality are ignored, so the simulated score path (and thus situations) is generic.
- The choice model is fitted on situations at the moment of each real call; the simulation
  only reproduces those situations approximately.
- Injuries, "unavailable today" news, openers announced late and September call-ups are not
  known to the model beyond the active roster it is given.
- Usage history ignores *why* a reliever was used (a closer on a bad team gets few saves);
  roles are inferred from saves/holds and can lag a mid-season role change by a few weeks.
- Doubleheader game 2 sees game 1's pitches in the "yesterday" slot (approximation).
- Teams differ (committee bullpens, openers); only the volume of bullpen use is team-specific
  (tendency term, weak); who-gets-called weights are shared by all teams.
- The reported probability is mostly carried by the direct model (`blend_weight_direct` 0.63
  vs `calib_slope` 0.44 on logit P_sim): the simulator adds a real but small amount. The
  game engine still lacks home/away and off-day effects that the direct model picks up.
- Still over-confident at the top: predictions ≥ 0.8 happen 61% of the time (310 test
  reliever-games), 0.7–0.8 → 67%.
- Blend and direct weights are fitted on 2025 only (the simulator's choice weights too, so
  its 2025 frequencies used to fit the calibration are partly in-sample). Refitting on
  2025 + 2026 before 2027 is advisable (the walk-forward shows a small gain from refits).
- Bullpen runs: "runs on the mound" charges inherited runners to the pitcher on the mound,
  not the one who put them on; no earned/unearned split, no FIP (the cached box scores have
  no per-pitcher H / BB / K / HR). Park, defence, opponent lineup and platoon are ignored.
  Individual ratings are heavily shrunk (300 pseudo-outs), and their bullpen sum is
  under-dispersed by about 2× (team-shared park / defence effects), hence `runs_scale`.
  The predictable part is small: sd of "vs average" ≈ 0.17 runs (scaled) against a per-game
  sd of 2.4 bullpen runs; R² of any pre-game bullpen predictor ≈ 2%.
- "Vs usual" (availability) is the weakest part: no effect in 2025 (+0.35 ± 1.10 raw slope)
  but a clear one in 2026 (+3.48 ± 0.90), when ratings rest on more history. Treat it as
  directional.
- Same-day roster moves must be reflected by the user (pool = today's roster or
  `active = false`); late scratches and "unavailable today" news are not known.

---

## Variants

- `variants/no_usage_history.toml`: `usage_weight = 0` (roles + situations + fatigue only;
  what you get when you have no usage history). Backtested in RESEARCH.md.
- `variants/no_situations.toml`: all `sit_*` = 0 (no leverage logic; usage + fatigue + base
  role only). Backtested in RESEARCH.md (v0.4.0 study).
- `variants/simulation_only.toml`: calibration, tendency and direct blends off — the raw
  simulated frequencies (the "2a. engine refit" row of RESEARCH.md).

---

## Data & backtest

`ballmonitor fetch mlb_bullpen` (MLB Stats API, stdlib) caches raw responses in `data/raw/`
(gitignored, ~40 MB gzipped; ~10k box/play-by-play requests plus ~11k active-roster and 60
transaction requests at 4 parallel, ~1 h first time) and builds:

- `data/games.csv.gz` — every 2025–2026 regular-season team-game from 2025-04-15 (9,230 rows, 30 teams);
- `data/decisions.csv.gz` — every bullpen call: inning, outs, bases, lead, next 3 batters'
  hands, who came in (30,332 rows);
- `data/pitcher_lines.csv.gz` — every pitcher appearance from 2025 opening day (41,672 rows):
  `seq` (game order), `game_pk`, `game_date`, `season`, `team`, `pitcher_id`, `name`,
  `started`, `outs` (box score), `bf` and `runs` (plate appearances pitched and runs scored
  during them, from play-by-play); used by `research_runs.py`;
- `data/backtest.csv` — every 8th 2026 team-game (608 rows, ~1.1 MB; the full test season is scored by research.py) for `ballmonitor backtest`.

Columns of `backtest.csv` / `games.csv.gz`: `game_pk`, `game_date`, `season`, `team`,
`opponent`, `is_home`, `off_day_tomorrow`, `starter_name`, `starter_hand`, `starter_stamina`
(mean pitches of his last 5 earlier starts; blank = none), `lineup`, `relievers_json` (the
pool: the box-score roster = the active roster at game time, minus today's starter and
rotation arms, with `pitches_days`, usage history, `new_arrival` = not on the previous
day's API active roster, and `ra_outs` / `ra_runs` = relief outs and runs on the mound in all
earlier games), pre-game `team_bp_outs` / `team_bp_runs` (the team's relievers, earlier games
this season) and `starter_prior_outs` / `starter_prior_runs` (today's starter, earlier starts
this season), `team_recent_games` / `team_recent_relievers` (last 80 team-games
on earlier dates) and `league_recent_relievers` (previous 30 days), and outcome / diagnostic
columns `actual_relievers_used` (in order), `first_reliever`, `n_relievers`,
`starter_pitches`, `starter_outs`, `runs_for`, `runs_against`, `pool_used`, `later_il`
(pool arms placed on the IL 1–3 days later), `off_roster_eod` (pool arms missing from the
API roster *for the game date*, which is an end-of-day state — post-game, never an input),
`roster_departed` (pitchers on yesterday's roster not on today's), `starter_runs`,
`bullpen_outs`, `bullpen_runs` (runs scored while the starter / the relievers were on the
mound; they add up to `runs_against`). Every input column is
known before first pitch (see `fetch.py`): same-day roster moves are announced before the
game, so the game-day roster is used as the pool.

Metrics (`score`): `brier` and `log_loss_appear` (appearance, averaged over the pool),
`top_pick_correct`, `top_3_recall`, `brier_first` and `log_loss` (which arm is first out of
the pen; skipped when that arm was not in the pool, e.g. a position player);
`bullpen_runs_sq_error` (actual − expected bullpen runs, squared; the interval coverage is
reported in RESEARCH_RUNS.md).

### Results (v0.5.0) — walk-forward, see RESEARCH.md

Everything fitted on the **2025** season (4,372 team-games); scored once on the **2026**
season (4,858 team-games, 30 teams). Paired differences ± naive s.e. (team-clustered s.e.).

| 2026 (out of sample) | Brier | Log loss appear | Top pick | First LL | Relievers / game |
|---|---|---|---|---|---|
| **v0.5.0 (blend, shipped)** | **0.2008** | **0.5782** | **62.9%** | **1.813** | 3.29 |
| direct model alone (no simulator) | 0.2017 | 0.5796 | 62.2% | 1.819 | 3.25 |
| simulator + calibration + engine refit + tendency | 0.2055 | 0.5926 | 61.4% | 1.863 | 3.33 |
| v0.4.0 | 0.2063 | 0.5955 | 61.3% | 1.865 | 3.43 |
| usage-frequency benchmark | 0.2096 | 0.6021 | 59.6% | 1.891 | |
| uniform benchmark | 0.2369 | 0.6667 | 39.0% | 2.134 | |

Actual: 3.24 pool relievers per team-game. v0.5.0 vs v0.4.0: appearance log loss −0.0173 ±
0.0011 (0.0022), Brier −0.0056 ± 0.0004 (0.0006), first-reliever log loss −0.052 ± 0.005
(0.007); vs usage-frequency: log loss −0.024 ± 0.001 (0.002), first-reliever −0.078 ± 0.006
(0.009). Better than v0.4.0 in every month of 2026. Monthly walk-forward refits (7 test
months) give the same picture (blend log loss 0.5774).

The four improvements, each on its own (log loss vs v0.4.0):

1. **Calibration** of logit P_sim (role intercepts, slope 0.92): −0.0023 ± 0.0003 (0.0007).
   A global slope barely changes the extreme bins (predicted ≥ 0.8: 0.88 → 0.59 actual);
   their over-confidence is specific to some games, not a uniform stretch. A first-reliever
   temperature fitted to ~1 (no gain). In the blend, calibration + direct model improve the
   low end (0.1–0.2: 0.15 predicted → 0.13 actual, was 0.11) and 0.7–0.8 (0.74 → 0.67,
   was 0.62), and only 310 reliever-games (was 949) are predicted ≥ 0.8 (0.87 → 0.61).
2. **Bullpen size.** The v0.4.0 gap (3.43 simulated vs 3.24 actual) was not league drift:
   the hook settings had been tuned on a sample that was 100% home teams (home teams use
   ~0.2 more relievers). (a) Re-tuning on a home/away-balanced 2025 sample
   (`pitches_per_pa` 3.75 → 3.65): −0.0019 ± 0.0004; (b) rolling team / league usage
   tendency (last 80 team-games shrunk with 40 pseudo-games): −0.0002 ± 0.0001 — weak.
3. **Active roster.** No effect possible on the backtest: the pool already is the game-day
   active roster (0 inactive arms). The API roster for a date turned out to be end-of-day
   (of 299 pool arms it misses, 297 pitched that day), so it must not be used as a pre-game
   filter. Same-day arrivals (`new_arrival`) are a small direct-model feature (−0.0002).
4. **Direct logistic model**: −0.0159 ± 0.0017 (0.0033) on its own — it beats the
   simulator. The **blend** beats the direct model by a further 0.0014 log loss (and
   0.006 on first-reliever log loss), with the simulator's weight clearly non-zero
   (0.44 ± 0.03; first-reliever 0.23 ± 0.04): the simulator adds a small amount of
   information (situational / leverage structure), so the blend is the default.

Promoted to defaults: all of the above that improved 2026 out of sample with numbers fitted
on 2025 only: engine refit, calibration + tendency + direct blend for P(appear), the
first-reliever blend, and `new_arrival`. The tendency term is kept (small, consistent sign,
s.e. large).

`research.py` needs numpy (`pip install -e '.[data]'`); the model itself is stdlib-only.

### Bullpen runs (v0.6.0) — see RESEARCH_RUNS.md

`research_runs.py` (numpy) fits the rating on 2025 and scores 2026 (4,858 team-games from
2,429 games; team-clustered s.e. in brackets, 30 clusters). Outcome A = runs scored while
the team's relievers were on the mound; B = all runs allowed. Linear models fitted on 2025;
ΔMSE = improvement in mean squared error on 2026 (positive = better).

| 2026 bullpen runs (A) | MSE | R² vs constant |
|---|---|---|
| league average (constant) | 5.568 | 0 |
| expected bullpen outs × league rate | 5.485 | 1.5% |
| naive: team season-to-date bullpen runs/out × expected outs | 5.472 | 1.7% |
| workload + **vs average** | 5.461 | 1.9% |
| naive + **vs average** | 5.456 | 2.0% |
| naive + **vs usual** (availability only) | 5.469 | 1.8% |

* Beyond the team's season-to-date bullpen quality: ΔMSE +0.017 ± 0.009 (0.011)
  season-forward, +0.018 (0.012) walk-forward; raw slope given the naive rate 1.39 ± 0.49
  (2025), 1.61 ± 0.43 (2026), pooled 1.44 ± 0.37 — distinguishable from zero.
* Calibration: raw slope given the workload 1.92 ± 0.53 (2025) and 1.93 ± 0.46 (2026), so
  the shipped `runs_scale` = 1.92 gives a 2026 slope of 1.01. Quintiles of the raw metric
  (2026): −0.14 → −0.21 actual, +0.12 → +0.29.
* Whole-game runs (B), on top of starter season-to-date rate, naive bullpen and opponent
  offense: ΔMSE +0.055 ± 0.020 (0.019) season-forward, +0.051 (0.020) walk-forward.
* Availability alone (vs usual): ΔMSE +0.003 (0.001) season-forward, +0.010 (0.004)
  walk-forward; on whole-game runs −0.008 (0.002) / +0.006 (0.005). Inconsistent across
  seasons (see weaknesses).
* Interval: 80% coverage 80.0% in 2025 (fit) and 80.0% in 2026.

---

## References

- MLB Stats API (statsapi.mlb.com): schedule, box scores, play-by-play, people.
- McFadden (1974), conditional logit analysis of qualitative choice behavior.
- Tango, Lichtman & Dolphin, *The Book* (2007): Leverage Index, times through the order.
- MLB Rule 9.19 (saves); 3-batter minimum (2020).

---

## Changelog

- **0.6.0** — Bullpen run prevention. New outcomes in group "Bullpen Runs": "Bullpen runs
  vs average", "Bullpen runs vs usual", "Expected bullpen runs" (80% range in the note);
  per-arm "RA9" in the appearance notes; `extras` adds `ratings`, `expected_outs`,
  `bullpen_runs`. New optional reliever inputs `ra_outs`, `ra_runs`; params `runs_prior_outs`,
  `runs_prior_rate`, `runs_league_rate`, `runs_outs_source`, `runs_default_outs_per_app`,
  `runs_scale`, `runs_interval_halfwidth`, `runs_interval_level`; formulas
  `reliever_rating`, `bullpen_runs_vs` (all fitted on 2025, RESEARCH_RUNS.md). Fetch:
  per-pitcher runs on the mound from play-by-play, `data/pitcher_lines.csv.gz`, reliever
  `ra_outs` / `ra_runs` (earlier relief outings only), game columns `team_bp_outs`,
  `team_bp_runs`, `starter_prior_outs`, `starter_prior_runs` (pre-game, season-to-date) and
  outcomes `starter_runs`, `bullpen_outs`, `bullpen_runs`. Scoring adds
  `bullpen_runs_sq_error`. Appearance probabilities and all
  v0.5.0 results are unchanged. New `research_runs.py` → `RESEARCH_RUNS.md`.

- **0.5.0** — P(appear) is now logistic(`appear_logit`): recalibrated simulation frequency
  (`calib_intercept_<role>`, `calib_slope`) + team bullpen-usage tendency (`tendency_weight`,
  `tendency_prior_games`, `bullpen_baseline_relievers`; new optional inputs
  `team_recent_relievers`, `team_recent_games`, `league_recent_relievers`) + a direct
  logistic model (`direct_*`, `blend_weight_direct`). P(first) blends ln P_sim(first) with a
  direct conditional logit (`first_weight_sim`, `first_weight_direct`, `first_direct_*`,
  `first_prior_rate`, `first_prior_games`). All fitted on 2025 (RESEARCH.md section 2).
  `pitches_per_pa` 3.75 → 3.65 after re-tuning the engine on a home/away-balanced 2025
  sample (v0.4.0 tuned on home teams only, so it over-used the bullpen). Roster: optional
  `active` / `new_arrival` reliever inputs; inactive arms are never picked, not even as
  emergency arms, and get probability 0. Fetch: active rosters and transactions from the
  MLB Stats API, new columns (tendency inputs, `new_arrival`, `pool_used`, diagnostics
  `later_il`, `off_roster_eod`, `roster_departed`). Outcome notes show the simulated and
  direct probabilities; `extras` adds `p_appear`, `p_first`, `p_sim_appear`, `p_direct`,
  `log_ratio`; scoring uses the reported probabilities. New variant `simulation_only`.
  2026 appearance log loss 0.5955 → 0.5782, first-reliever log loss 1.865 → 1.813.

- **0.4.0** — Data: `fetch.py` rebuilt for the full 2025 + 2026 regular seasons (box scores +
  play-by-play, cached gzipped in `data/raw/`); roles inferred from prior usage only (was a
  hand-made name list), usage history per reliever, starter stamina = last 5 starts (openers
  included), `off_day_tomorrow` from the schedule, every bullpen call with its game state.
  Model: new score = role base + `sit_<situation>_<role>` table + usage term + platoon −
  fatigue, all fitted by conditional logit on 2025 calls (replaces the hand-set
  save/fireman/home-tie/high-leverage/blowout ladder and `role_middle`, `li_high_threshold`,
  `li_blowout_threshold`, `middle_default_boost`, `early_exit_long_boost`, ...); role
  inference params; `max_consecutive_days` (replaces the fixed 3-day rule); hard-rule
  thresholds from the 2025 workload table (`max_pitches_3d` 55 → 70); `temperature` 1.2 → 1.
  Engine: pitches per PA, PA event rates and our run distribution moved to config and set so
  both sides score the 2025 average (v0.3 had our team out-scoring the opponent 4.6–3.5);
  `reliever_extend_prob` added; hook params re-set to match 2025 starter outs and relievers per
  game. Scoring adds appearance log loss and skips first-reliever metrics when that arm was
  not in the pool. Variants: removed the five manager variants (unbacked numbers that only
  changed `starter_stamina_default`, which inputs override); added `no_usage_history` and
  `no_situations` (ablations scored in RESEARCH.md). Default example is now a real 2026 game;
  the old hand-made one is `examples/manual_roles.toml`. Status `draft` → `calibrated`.
- **0.3.0** — Backtest data rebuilt: removed leak (`starter_stamina` was the actual pitch
  count of the game; now the mean of prior starts), fixed handedness and lineup order, summed
  doubleheader pitch counts. All hook/availability/situational constants moved into
  `config.toml`; added `seed`. Saves follow MLB Rule 9.19. Input validation. Status
  `calibrated` → `draft` (in-sample tuning on 48 games).
- **0.2.0** — Tuned `temperature`, `penalty_pitched_yesterday`, `save_situation_boost`,
  `high_leverage_setup_boost` on the 2024 backtest (v0.1 values: 0.7, 1.2, 3.5, 2.2).
