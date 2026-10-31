# College Recruiting Strength (`ncaaf_recruiting`)

**Question:** How strong is a program's recruiting class (football, men's or women's
basketball) judged by the scholarship offers each recruit received and turned down,
and how well does that track later on-field performance?

## Inputs

| input | meaning | default |
|---|---|---|
| `sport` | `ncaaf`, `mbb` or `wbb` | `ncaaf` |
| `year` | class year (signing year) | `2024` |
| `team` | program name as it appears in the data (case-insensitive; close matches are suggested on error) | `Georgia` |
| `method` | `plackett_luce` (default) or `sequential_elo` (legacy ablation) | `plackett_luce` |

## Data

Rebuild / extend with `ballmonitor fetch ncaaf_recruiting` (`fetch.py`; raw JSON cached in
`data/raw/`, gitignored). `data/recruits/manifest.csv` lists every file with its source,
status (`complete` / `in_progress`), row and commit counts and offer coverage.

| sport | files | years | notes |
|---|---|---|---|
| ncaaf | `data/recruits/football{year}done.csv` | 2012–2027 | 2012–21 legacy Rivals/On3 profile scrapes (~3,500 recruits, 65–86% of commits list competing offers); 2022–27 On3 recruit-database API (On3-ranked recruits only, 83–96%). **2027 is in progress** (fetched 2026-10-26; uncommitted recruits have an empty school). |
| mbb | `data/recruits/recruits_mbb_{year}.csv` | 2014–2027 | On3 recruit-database API, On3-ranked recruits only (250–410 a class; **2021 only 138**). 2014–2023 added in v0.5.0 by `fetch.py`; 2024–2025 are the older `ingest_class.py` files (same source, same commits). 2027 in progress (158 commits). Commits to the G League / Overtime Elite / "Professional" are ignored (`NON_COLLEGE` in `src/data_loader.py`). |
| wbb | `data/recruits/recruits_wbb_{year}.csv` | 2024–2027 | 2025–27 On3 (top 74–102). **2024 is an ESPN scrape**: school names are now de-mascotted ("South Carolina Gamecocks" → "South Carolina"), but ESPN lists only the commit and a few finalists (4% of commits have a competing school) and On3 has no WBB rankings before 2025 (its API answers "Ranking does not exist"), so no offer source exists and the model still refuses the file (`min_offer_coverage`). WBB 2027 (37% coverage so far) is refused for the same reason until more offers are listed. |

Row format: `url, year, name, position, hometown, stars, committed_school, offer_1, offer_2, ...`
("offers" = every school On3 lists as a target other than the committed one).

Evaluation data (men's basketball, v0.5.0, read by `research_mbb.py`):
`data/recruits/mbb_recruit_ratings.csv` (one row per On3-ranked MBB recruit 2014–2027:
On3 key, name, position, height, hometown, industry rating and national rank, consensus
stars, committed school and its On3 status, number of other schools listed),
`data/outcomes/mbb_team_seasons.csv` (barttorvik end-of-season adjusted offensive /
defensive efficiency and adj. EM = adj_oe − adj_de for every D-I team, seasons 2014–2026,
season = spring year) and `data/outcomes/mbb_player_seasons.csv` (63,122 barttorvik
player-seasons 2014–2026: games, Min%, ORtg, usage, TS%, class, height, PORPAG,
persistent player id, hometown, barttorvik recruit rating, NBA draft pick, BPM / OBPM /
DBPM, minutes, rebounds, assists and points per game). The column mapping of
barttorvik's header-less CSV is in `fetch.py` (`BART_PLAYER_COLS`) and was checked on
Zion Williamson 2019 (22.6 pts, pick 1), Ja Morant 2019 (24.5 pts, 9.9 ast, pick 2) and
Cade Cunningham 2021 (20.2 pts). On3 school names are matched to barttorvik names by
`src/mbb_names.py` (99.2% of commits; the rest are G League / pro / non-D-I schools).

Evaluation data (football): `data/outcomes/fbs_games.csv` (12,075 completed games
involving FBS teams, 2012–2025, ESPN scoreboard API) and
`data/benchmarks/consensus_team_rankings.csv` (On3 industry-consensus team class ranks,
football 2012–2027, MBB 2014–2027; blends On3, 247Sports, Rivals and ESPN; pre-2021
classes were compiled by On3 after the fact). Rivals top-100
team ranks for 2012–2022 are in `data/teams/`. Team names are normalised across sources
in `src/data_loader.py` (`SCHOOL_ALIASES`, e.g. USF → South Florida, FIU, UTSA).

## Method

Instead of relying on subjective human recruiting analysts who may have regional biases or award stars retroactively based on Alabama/Georgia offers, `ncaaf_recruiting` models college football coaches as the primary talent scouts.

1. **Multi-Competitor Plackett-Luce Choice Model:**
   Every recruit commitment is treated as a multi-competitor game where the committing school "wins" ($c_i$) over all other programs that offered scholarships ($S_i \setminus \{c_i\}$).
   The latent prestige parameter vector $\gamma \in \mathbb{R}^T$ across all programs is solved via convex Maximum A Posteriori (MAP) estimation:
   $$\mathcal{L}(\gamma) = -\sum_{i=1}^N \left( \gamma_{c_i} - \ln \sum_{s \in S_i} e^{\gamma_s} \right) + \frac{\lambda}{2} \|\gamma\|^2$$
   Parameters are mapped to the standard Elo scale: $\text{Elo}_t = 1500 + \frac{400}{\ln 10} \gamma_t$.

2. **Recruit Quality Valuation:**
   A recruit's caliber $q_i$ is determined by the collective prestige of the programs they defeated:
   $$q_i = \left( \sum_{s \in S_i \setminus \{c_i\}} e^{\gamma_s} \right)^p$$
   where $p$ is `quality_power` (football, 0.5) or `bball_quality_power` (basketball, 0.6),
   capturing diminishing marginal utility for additional offers. A recruit with no
   competing offers scores 0 (football) or 1 (basketball).

3. **Class Score & Rank Decay:**
   Recruits are sorted by score and summed through config formula **`recruit_points`**
   (`rating * (decay ** (rank - 1))`), with decay $\delta$ = `rank_decay` (football, 0.95)
   or `rotation_decay` (basketball, 0.75):
   $$\text{Class Score} = \sum_{r=1}^M q_{(r)} \cdot \delta^{r-1}$$
   Basketball classes are then multiplied by
   $(\overline{q}_{\text{top 2}} / \text{median}(q))^{\text{cornerstone\_weight}}$.
   The L2 prior is `l2_reg` (football) or `bball_l2_reg` (basketball).

4. **Geographic Footprint** (standalone `run_model.py --geo` only; not in `ballmonitor run`):
   Calculates average recruit distance from campus and national recruit share (% commits $>500$ miles away) using geolocated recruit hometowns and campus coordinates.

5. **Positional Allocation & Run/Pass Sub-Phases:**
   Decomposes recruiting classes into Offense vs. Defense and Run vs. Pass:
   $$\text{Run Offense} = \sum_{r \in \text{Off}} q_r \cdot w_{\text{run}}(pos_r), \quad \text{Pass Offense} = \sum_{r \in \text{Off}} q_r \cdot w_{\text{pass}}(pos_r)$$
   $$\text{Run Defense} = \sum_{r \in \text{Def}} q_r \cdot w_{\text{run}}(pos_r), \quad \text{Pass Defense} = \sum_{r \in \text{Def}} q_r \cdot w_{\text{pass}}(pos_r)$$
   Positions are weighted by functional contribution (e.g., RB: 80% run / 20% pass, WR: 10% run / 90% pass, DT: 75% run / 25% pass, EDGE: 30% run / 70% pass).
   These are **undiscounted** sums (no rank decay), so offense + defense exceeds the class
   score. The weight table lives in `src/position_model.py` (judgement, not in config).

6. **Projected team strength (football):** config formula **`projected_srs`**
   (`proj_intercept + proj_slope * log(rank)`) turns the national class rank into the
   expected mean SRS (points per game vs an average FBS team) over the class's four
   seasons, with a `projection_level` range of ± z · `projection_sd`. The line was fitted
   on 2012–2018 classes in `research.py`. `prestige_years` > 1 also fits prestige on the
   previous classes' offer battles (known at signing); only this class is scored.

7. **Signing Day Forecasting & What-If Scenario Overrides:**
   (Standalone `forecast.py` only; not in `ballmonitor run`.) Prior to signing day, predicts the destination of uncommitted prospects and forecasts final class standings:
   - **Commitment Utility:** Blends latent program prestige $\gamma_s$ with distance decay:
     $$P(i \to s) = \frac{\exp\left( \gamma_s - \beta \ln(1 + d(i, s)/d_0) \right)}{\sum_{k \in O_i} \exp\left( \gamma_k - \beta \ln(1 + d(i, k)/d_0) \right)}$$
   - **Monte Carlo Simulation:** Simulates $N$ stochastic realizations of National Signing Day to produce median finish, confidence intervals, and Top-1/Top-5 probabilities.
   - **Interactive Overrides:** Supports user-defined commitment overrides (e.g. `--override "Recruit=Team"`) to quantify exact rank and score deltas.

---

## Backtest

What is predicted: the program's **mean SRS over seasons Y..Y+3** for class Y (simple
opponent-adjusted margin rating from ESPN scores, margins capped at ±28, computed in
`research.py`). Full study, every number generated: **RESEARCH.md**
(`python -m ballmonitor.models.ncaaf_recruiting.research`).

`data/backtest.csv` (columns `year, team, future_srs, consensus_rank, prior_srs`; the
model reads `year`, `team`, `future_srs`) holds the 513 FBS program-classes of the
**holdout classes 2019–2022**. No default and no projection coefficient was chosen with
them. `ballmonitor backtest ncaaf_recruiting` scores the projected SRS (`score()` is
overridden): MAE 4.84 points/game (per year 5.06 / 4.84 / 4.43 / 5.05), bias −0.1,
80% range covers 84%. Benchmarks on the same rows (RESEARCH.md): industry consensus rank
4.69, mean commit stars 5.41, no-information mean 6.68.

Ranking agreement (Spearman ρ within each class year, vs 4-season SRS; walk-forward
where params for class Y are chosen on classes ≤ Y−4; test classes 2017–2022 =
**6 independent class years**, overlapping targets):

| ranking | mean ρ (2017–22) | after removing prior-season SRS |
|---|---:|---:|
| offer model, walk-forward params | 0.693 ± 0.025 | 0.373 |
| offer model, defaults | 0.696 | 0.374 |
| On3 industry consensus | 0.714 ± 0.021 | 0.377 |
| Rivals top 100 | 0.672 | 0.341 |
| mean commit stars | 0.687 | 0.356 |
| prior-season SRS (not recruiting) | 0.616 | – |

Honest summary: offers alone rank programs about as well as star averages and better
than Rivals' top-100 list, but **below the industry consensus in all 6 test years** (by
~0.02 ρ, about one standard error). The parameter surface is flat: no grid point beat
the v0.3.0 defaults by the 0.01 ρ adoption margin on the development classes, so they
were kept. The old `evaluate.py` FEI study (in-sample, r = −0.661 on 2012–2017) is
superseded. Men's basketball is evaluated separately (below and RESEARCH_MBB.md).

## Men's basketball evaluation (v0.5.0)

Full study, every number generated: **RESEARCH_MBB.md**
(`python -m ballmonitor.models.ncaaf_recruiting.research_mbb`). Is there enough data?
For ranking programs, yes to tell the model from the consensus: 12 class years
(2014–2025, ~115 programs with an On3-ranked commit each), 9 walk-forward test years
for the freshman-season target and 7 for the two-season target; the model-vs-consensus
gap (0.105 ρ, 0 of 9 years won) is about five standard errors of the paired
year-by-year difference. It is not enough to
tune the basketball parameters: every tested setting is within ~0.01 ρ. For players,
3,322 recruits of classes 2014–2025 were linked to barttorvik at a 90.9% rate (5-star
92%, 4-star 96%, 3-star 87%; the misses are mostly players who never played D-I —
G League, overseas, injured / ineligible — or went unrecorded under another name).

**Team level.** Spearman ρ within a class year between the class ranking and the
program's barttorvik adjusted efficiency margin, walk-forward test years:

| ranking | freshman season Y+1 (2017–25) | mean of Y+1, Y+2 (2018–24) |
|---|---:|---:|
| offer model, walk-forward params | 0.425 ± 0.039 | 0.467 ± 0.033 |
| offer model, defaults | 0.432 | 0.471 |
| On3 consensus team rank | **0.530** | **0.573** |
| sum of commits' industry ratings | 0.425 | 0.461 |
| mean industry rating of commits | 0.435 | 0.460 |
| mean commit stars | 0.289 | 0.255 |
| prior-season adj. EM (not recruiting) | 0.729 | 0.736 |

The offer model ranks programs about as well as a plain sum of the commits' industry
ratings, but below the consensus team rank in every test year, and last season's
strength predicts next season far better than any recruiting measure. Beyond prior EM
and the consensus the model adds ρ ≈ +0.01; the mean industry rating of the commits
adds ≈ +0.08 (the consensus rewards volume). Defaults were chosen on classes 2014–2019:
the best grid point (`rotation_decay` 0.95, `bball_quality_power` 1.0, `bball_l2_reg`
0.01, `cornerstone_weight` 0) gained only +0.005 ρ (< 0.01 required), so the v0.4.0
basketball defaults are kept; the holdout classes 2020–2025 did not influence this.

**Player level.** Recruit signals (within-class percentiles) vs barttorvik outcomes,
Spearman ρ with bootstrap 95% intervals (career / draft: classes 2014–2021):

| outcome | stars | industry rating | offers listed | offer-model score |
|---|---:|---:|---:|---:|
| freshman Min% | +0.27 | **+0.38** [0.34, 0.41] | +0.14 | +0.17 [0.14, 0.21] |
| freshman pts/g | +0.33 | **+0.44** [0.40, 0.47] | +0.16 | +0.20 [0.17, 0.24] |
| freshman BPM | +0.34 | **+0.46** [0.43, 0.49] | +0.18 | +0.21 [0.18, 0.25] |
| best-season BPM | +0.29 | **+0.36** [0.32, 0.40] | +0.08 | +0.11 [0.07, 0.16] |
| NBA draft (earlier pick) | +0.39 | **+0.41** [0.37, 0.45] | +0.12 | +0.19 [0.15, 0.23] |

The industry rating is the best signal for every production outcome. The offer-based
recruit score adds **no** information beyond it: partial ρ given the industry rating is
−0.01 for freshman Min%, pts and BPM, −0.08 for best-season BPM and −0.02 for the
draft, with R² gains ≤ 0.006. (Stars add a little for the draft: partial ρ +0.11.) The offer score is mostly an offer count
(ρ 0.90 with the number of schools listed).

**Verdict.** MBB is now *evaluated* walk-forward but not validated as a good
predictor: use the class score as an offer-network description, not as a forecast of
team strength. There is no basketball projection outcome and no MBB rows in
`data/backtest.csv` (`backtest_case` / `score()` score the football SRS projection).

**Two-year windows and prior-season models** (`research_mbb_combo.py` →
RESEARCH_MBB_COMBO.md; all D-I teams, walk-forward). Adding the previous class (y−1)
to class y raises every metric's within-year ρ with next-season adj. EM (e.g. On3
consensus 0.633 → 0.669, offer model 0.603 → 0.645). The prior season alone is far
stronger (ρ 0.81, RMSE 6.81 adj. EM points); recruiting is an increment on top of it:
prior + two-year consensus rank cuts next-season RMSE by 0.27 (to 6.55) and the
two-season RMSE by 0.43, the best single addition; adding all five metrics gains
little more. In-sample, last year's class carries more weight than this year's, and
last year's top-50 recruits count *against* next season once the consensus rank is
known (one-and-done departures).

**Seeding with on-court results** (`research_mbb_seed.py` → RESEARCH_MBB_SEED.md;
options `bball_seed_beta`, `bball_commit_weight`, `bball_aggregate`, all off by default).
Program strengths can start from each program's barttorvik adj. EM over the two seasons
before the class's junior year, instead of all starting equal; the offer battles then
move them. Chosen on 2014-2019 classes, tested on 2020-2025:
- *Team level:* the seeded class score ranks next-season adj. EM much better (ρ 0.61 vs
  0.48) but mostly by echoing past program strength — beyond prior-season adj. EM and the
  consensus it adds ρ +0.05 (current +0.02). A "seed frozen" version that ignores offers
  does as well, so the offer battles add little on top of the seed.
- *Recruit level:* gains appear only for freshman BPM, which partly measures the team
  (the committed school's seed alone, with no player information, has ρ 0.37 with BPM but
  ≈0.05 with points/minutes). Chosen on player-driven outcomes, the best seeded settings
  match the current model (pts 0.196 vs 0.190, minutes 0.178 vs 0.174, draft 0.284 vs
  0.264 — noise) and add nothing beyond the industry rating (ρ 0.41-0.46).
- 195 of 1,544 test commits list no other school, so the original score gives them 0
  (e.g. Anthony Edwards, #1 in 2019); `bball_commit_weight` > 0 fixes that.
Not adopted as defaults: the evidence supports it for team class rankings but not for
judging individual recruits.

**Offer quality from rivals, and ratings + offers** (`research_mbb_offerq.py` →
RESEARCH_MBB_OFFERQ.md). Valuing a recruit by the prior-season adj. EM of the schools he
turned down (never the committed school's own) gives class rankings no better than the
current model (ρ with next-season adj. EM 0.466 vs 0.476; beyond prior + consensus
+0.022 vs +0.018). A top-heavy industry-rating class sum does better (0.485, +0.060);
mixing in offer quality changes it by noise (0.493, +0.058). None improves a
walk-forward prior-season + consensus model (ΔRMSE ≈ 0). Per recruit, offer quality adds
nothing beyond the industry rating for points/minutes (partial ρ ≈ −0.02) and ≈ +0.03
for BPM/draft. No defaults changed.

## Women's basketball evaluation

`research_wbb.py` → RESEARCH_WBB.md. Data: ESPN classes 2012-2025 (top 300 per class,
`data/recruits/wbb_espn_classes.csv`, built by `fetch.py build_wbb_espn`) with ESPN grade,
rank, commitment and the other schools still on each recruit's list; outcome: per-season
margin ratings from `ballmonitor/models/dad/data/team_ratings.csv` (2016-2026); 10 class
years (2016-2025). ESPN lists other schools for only 24-30% of commits (2016-2021) and
almost none after, so 70-96% of commits get an offer-model score of 0 and the model has
~35-80 battles per class; On3 women's offer data starts in 2025 (one completed season).
- An ESPN-grade class score beats the offer model in **all 10** class years: ρ with
  next-season rating 0.55 vs 0.39 (gap −0.16 [−0.23, −0.10]); beyond the prior season
  +0.18 vs +0.06 (gap −0.12 [−0.19, −0.05]). Even in the classes with school lists
  (2016-2021) the grade score leads (0.60 vs 0.49).
- Recruiting matters more in WBB than MBB: the grade class adds ρ +0.18 (next season) to
  +0.24 (two seasons) beyond the prior season's rating (MBB ≈ +0.06).
WBB therefore stays unvalidated for the offer model; use ESPN grades for class strength.

## Assumptions & known weaknesses

- Offers are treated as equal-intent; committable vs. courtesy offers are not separated.
- Offer lists are scraped and incomplete, especially for lower-ranked recruits.
- Static within a class year: decommitments and transfers are ignored.
- Basketball: files hold On3-ranked recruits only (2021: 138), so programs that sign
  unranked players look empty. MBB defaults are tested but the score is weaker than
  the On3 consensus (RESEARCH_MBB.md); WBB is untested. `status = calibrated` refers to
  football only.
- Basketball history comes from On3 as it is today: offer lists may have been filled in
  later and the commit is where the player enrolled (Enrolled > Signed > Committed),
  which was not always known on signing day. Transfer-portal era (2021+ classes) and
  the COVID 2020-21 season weaken the link between a class and team strength.
- The projection uses only the class rank; it ignores the existing roster, transfers
  and coaching, and the 2022+ files (On3-ranked recruits only) may shift ranks of
  programs that sign many unranked players (service academies).
- The sequential Elo method ignores `rank_decay`, `quality_power` and `recruit_points`
  and has its own hard-coded k-factor / benchmark tiers (`src/elo_engine.py`).

## Variants

None yet (RESEARCH.md shows no tested setting is better out of sample). Try `--set rank_decay=0.9` or `--set 'formulas.recruit_points=rating'` (no decay).

## CLI Usage

From within `ballmonitor/models/ncaaf_recruiting/`:

```bash
# Compute class rankings for 2024 with Rivals comparison and geographic footprint
python run_model.py 2024 --top 15 --compare-rivals --geo

# Compute positional breakdown (Offense vs Defense & Run vs Pass)
python run_model.py 2024 --breakdown --top 15

# Rank specifically by Offensive recruiting or Run Defense recruiting
python run_model.py 2024 --unit offense --top 10
python run_model.py 2024 --unit run_def --top 10

# Predict commitment probabilities for an uncommitted recruit
python forecast.py 2026 --predict-recruit "Jontavius Wyman"

# Forecast final signing day standings with Monte Carlo simulations
python forecast.py 2026 --top 15

# Simulate a what-if scenario with recruit commitment overrides
python forecast.py 2026 --override "JONTAVIUS WYMAN=Ole Miss" --compare

# Legacy in-sample FEI study (superseded by research.py / RESEARCH.md)
python evaluate.py --start 2012 --end 2017
```

## References

- Plackett (1975), Luce (1959) choice models; Hunter (2004), MM algorithms for generalized Bradley-Terry models.
- Football Outsiders FEI ratings (2009–2020 files in `data/analysis/`; legacy study only).
- ESPN scoreboard API (game scores); On3 recruit database API (recruits, offers,
  industry-consensus team rankings).
- Rivals team rankings (`data/teams/football{year}.csv`, 2012–2022).

## Changelog

- 0.6.0 (later addition, no default changes) — Women's basketball evaluation:
  `fetch.py build_wbb_espn` (ESPN classes 2012-2025) and `research_wbb.py` → RESEARCH_WBB.md.

- 0.6.0 (later addition, no default changes) — `research_mbb_offerq.py` →
  RESEARCH_MBB_OFFERQ.md: rivals' on-court strength as offer quality; ratings + offers.

- 0.6.0 — New basketball options `bball_seed_beta` (start program strengths from recent
  on-court adj. EM), `bball_commit_weight` (count the committed school) and
  `bball_aggregate` (sum | max), all off by default; study `research_mbb_seed.py` →
  RESEARCH_MBB_SEED.md. Engine: `prior_gamma`, `commit_weight`, `aggregate`.

- 0.5.0 — (later addition, no default changes) `research_mbb_combo.py` → RESEARCH_MBB_COMBO.md: two-year recruiting windows and prior-season + recruiting models for MBB.
- 0.5.0 — Men's basketball evaluation: new study `research_mbb.py` → RESEARCH_MBB.md
  (team adj. EM, 12 class years, walk-forward; recruit → barttorvik player linkage).
  Basketball defaults unchanged (no grid point beat them by 0.01 ρ on 2014–2019); their
  `source`s cite the study instead of "DRAFT". Data: MBB classes 2014–2023 from On3;
  `mbb_recruit_ratings.csv`, barttorvik `mbb_team_seasons.csv` / `mbb_player_seasons.csv`;
  MBB consensus team ranks back to 2014; `src/mbb_names.py` (On3 ↔ barttorvik names).
  Fixes: `fetch.py` drops players repeated across On3 pages (MBB 2026 had 4 duplicated
  recruits, which double-counted commits) and picks the commit Enrolled > Signed >
  Committed; G League / Overtime Elite / "Professional" destinations are no longer
  ranked as programs; "Long Island University" merged with "Long Island".

- 0.4.0 — Status `draft` → `calibrated` (football): new walk-forward study
  `research.py` → RESEARCH.md and `data/backtest.csv` (holdout classes 2019–2022).
  New outcome "Projected 4-season SRS" (formula `projected_srs`, params
  `proj_intercept`, `proj_slope`, `projection_sd`, `projection_level`) and new param
  `prestige_years` (default 1 = old behaviour). Default `rank_decay`, `quality_power`,
  `l2_reg` unchanged (the study could not beat them out of sample); their `source`s now
  cite the study. Data: added football 2027 (in progress), MBB 2026 and 2027, WBB 2027
  via `fetch.py`; WBB 2024 school names de-mascotted (still refused: no offer lists);
  `manifest.csv`; ESPN FBS scores 2012–2025 and On3 consensus team rankings. Team-name
  aliases added (USF/South Florida, FIU, UTSA, San José State, UMass, App State), which
  merges previously split programs. Engine: `fit_recruits` for multi-year prestige fits,
  vectorised recruit scoring. In-progress classes are flagged in the steps.

- 0.3.0 — Status `calibrated` → `draft` (no backtest.csv; FEI study is in-sample).
  Basketball `quality_power` 0.60 and `l2_reg` 0.05 were hard-coded and are now params
  (`bball_quality_power`, `bball_l2_reg`); football params no longer leak into basketball
  runs. Config formula `recruit_points` now computes the class score (was evaluated and
  discarded). Unknown team / sport / method / year now raise a clear error instead of
  silently showing the #1 team; added `min_offer_coverage` so the offer-less WBB 2024
  file is refused. Fixed `DataLoader.load_rivals_rankings` / `load_fei_ratings` /
  `load_conferences`, which were unreachable (nested after a `return`), breaking
  `evaluate.py` and `run_model.py --compare-rivals`. `forecast.py` uses a local NumPy RNG.
- 0.2.0 — Initial ballmonitor integration.
