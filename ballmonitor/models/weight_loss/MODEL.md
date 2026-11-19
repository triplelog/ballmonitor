# Weight loss (`weight_loss`)

**Question:** Given a person's body today and a planned change of diet and/or activity, what
will they weigh on a chosen future date, and how wide is the realistic range?

**Status:** draft. **Not backtested.** The physiology is Hall et al.'s published, validated
model, but the *ranges* rest on DRAFT literature values and judgement: there is no open dataset
of individual dated weigh-ins to calibrate them against (see [Data that would calibrate
it](#data-that-would-calibrate-it)).

**Licensing note.** This is the model behind the NIH Body Weight Planner
(bwsimulator.niddk.nih.gov), which NIDDK lists as a licensable technology (NIH tech transfer
TAB-2436). This implementation is written from the equations published in the Lancet paper's
web appendix only, in our own code; no Planner code or data is used. Cite the papers below
when using it.

## Inputs

| input | meaning | example |
|---|---|---|
| `sex` | `M` or `F` (equations are sex-specific) | `"M"` |
| `age` | years (adults only, ≥ `min_age`) | `40` |
| `height_cm` or `height_in` | height | `180` |
| `units` | `kg` or `lb`, for `weight`, `goal_weight`, weigh-ins and the output | `"kg"` |
| `weight` | weight on `start_date` | `100` |
| `body_fat_pct` | optional measured body fat %; otherwise estimated (eq. 4) | `30` |
| `activity` or `pal` | `sedentary` / `active` / `vigorous`, or a physical activity level number | `"sedentary"` |
| `intake_change` | planned change of calories eaten, kcal/day (negative = eat less) | `-500` |
| `activity_change_pct` | planned % change of physical activity (scales delta, like the Planner) | `20` |
| `exercise_kcal` | planned extra exercise, kcal/day at today's weight | `150` |
| `carb_pct_after` | optional % of calories from carbohydrate after the change (default = `baseline_carb_fraction`) | `40` |
| `sodium_change_mg` | optional change of dietary sodium, mg/day (default 0) | `-500` |
| `start_date`, `target_date` | dates (YYYY-MM-DD); the change starts on `start_date` | `2026-01-05` |
| `goal_weight` | optional: also report the intake that reaches it by `target_date` | `92` |
| `[[weighins]]` | optional list of `date` + `weight`, on or after `start_date` | see `examples/with_weighins.toml` |

## Method

All energy is in kcal; the paper's kJ/MJ constants are divided by 4.184 (see each param's
`source`). Equation numbers are those of the web appendix ("Dynamic Mathematical Model of Body
Weight Change in Adults", supplement to Hall et al. 2011).

1. **Body today.** Fat mass F0 = `body_fat_pct` x weight, or formula `initial_fat` (eq. 4,
   from Jackson et al. 2002):
   F = BW/100 x [0.14 age + 37.31 ln(BW/H²) − 103.94] (men), [0.14 age + 39.96 ln(BW/H²) − 102.01] (women).
2. **Expenditure today.** RMR by formula `rmr` (Mifflin-St Jeor):
   9.99 W + 6.25 H(cm) − 4.92 age + 5 (men) / −161 (women). The person is assumed weight-stable,
   so baseline intake EI0 = expenditure = PAL x RMR. Activity coefficient (formula
   `activity_coefficient`, eq. 8): δ = [(1 − β_TEF) PAL − 1] RMR / BW.
3. **The plan.** New intake EI = EI0 + ΔEI. Activity: δ1 = δ (1 + `activity_change_pct`/100) +
   `exercise_kcal`/BW0. Carbohydrate intake CI = carb share x EI (baseline CI_b = `baseline_carb_fraction` x EI0).
4. **Dynamic model (`method = hall2011`)**, integrated with Runge-Kutta 4 (`steps_per_day`), states
   F, ΔL, G, ΔECF, AT:
   - glycogen (eq. 1): ρ_G dG/dt = CI − k_G G², k_G = CI_b / G_init²; each g carries
     `glycogen_water_ratio` g of water;
   - extracellular fluid (eq. 2): d ECF/dt = [ΔNa − ξ_Na ΔECF − ξ_CI (1 − CI/CI_b)] / [Na];
   - partitioning (eq. 3, formula `energy_partition`): p = C/(C + F), C = 10.4 kg x ρ_L/ρ_F;
     ρ_F dF/dt = (1 − p)(EI − EE − ρ_G dG/dt), ρ_L dL/dt = p(EI − EE − ρ_G dG/dt);
   - thermic effect (eq. 6) TEF = β_TEF ΔEI; adaptive thermogenesis (eq. 7)
     τ_AT dAT/dt = β_AT ΔEI − AT;
   - expenditure (eqs. 5 and 9, solved for EE):
     EE = [K + γ_F F + γ_L L + δ1 BW + TEF + AT + (EI − ρ_G dG/dt)(p η_L/ρ_L + (1−p) η_F/ρ_F)] / [1 + p η_L/ρ_L + (1−p) η_F/ρ_F],
     with K set so that EE = EI0 at the start (only changes of L enter, so initial lean mass
     and ECF never need to be known);
   - body weight BW = F + L + G (1 + hydration) + ECF.
5. **Linearised summary** (eqs. 10-17), reported with every run and used by the `linear`
   method: α = C/F0 (C = 10.4 kg), β = β_TEF + β_AT,
   τ = [η_F + ρ_F + α(η_L + ρ_L)] / [γ_F + δ1 + α(γ_L + δ1)],
   ΔBW_ss = [(1 − β) ΔEI − Δδ BW0] / [(γ_F + α γ_L)/(1 + α) + δ1] (eq. 17), and formula
   `linear_weight`: BW(t) = BW0 + ΔBW_ss (1 − e^(−t/τ)).
6. **Effective intake change and its uncertainty.** The one free quantity is the *effective*
   intake change ΔEI (what the person really achieves, energy-equivalent; activity not done
   shows up as extra intake). Planned energy change P = ΔEI_plan − Δδ BW0. Prior:
   ΔEI ~ Normal(m0, s0), m0 = `adherence_mean` x P + Δδ BW0,
   s0 = hypot(`adherence_sd` x P, `intake_sd_floor`).
7. **Weigh-ins (adherence fit).** With dated weigh-ins w_i at day t_i, ΔEI is the 1-D MAP
   estimate minimising Σ (w_i − BW(t_i; ΔEI))² / σ_w² + (ΔEI − m0)² / s0², σ_w = `weighin_sd_kg`,
   by Gauss-Newton (`fit_iterations`, sensitivity by finite difference `fit_step_kcal`). The
   posterior SD is 1/sqrt(1/s0² + Σ J_i²/σ_w²). Reported adherence = (ΔEI − Δδ BW0) / P.
   Weigh-ins below the planned path raise the estimated adherence and lower the projection.
8. **Bands.** Weight is monotone in ΔEI, so the model run at ΔEI = mean ± z x SD gives the
   exact quantiles of the *true* weight; the band of a *weigh-in* adds z x σ_w in quadrature on
   each side. Reported at 50/80/95% (80% is the headline interval) for the target date and each
   week of the trajectory table.
9. **Goal.** Secant search (`goal_iterations`, `goal_tolerance_kg`) for the constant intake that
   puts the median weight on `goal_weight` at `target_date` (with the planned activity), then the
   intake that holds it: eq. 5 at steady state, ΔEI_hold = [γ_F ΔF + γ_L ΔFFM + δ1 BW − δ BW0] / (1 − β).

## Assumptions and known weaknesses

- **Not backtested; bands are assumptions.** `adherence_sd` (CALERIE), `intake_sd_floor` and
  `weighin_sd_kg` are DRAFT values; the true spread of outcomes may be wider (especially over
  years, where regain is common) or narrower.
- **Constant adherence.** One effective intake change for the whole period. Real adherence fades
  (CALERIE: deeper restriction in the first 6 months than later), so long projections fitted to
  early weigh-ins are likely too optimistic. A time-varying intake would need a second parameter.
- **Weigh-in errors treated as independent.** Water/glycogen swings are correlated over days, so
  many close-together weigh-ins are given too much weight. The start weight is taken as exact.
- **Weight-stable at baseline.** If the person is already gaining or losing, the maintenance
  intake (and everything after) is off.
- **Population constants.** RMR from Mifflin-St Jeor has a person-level error of roughly ±10%;
  it barely affects the projected *change* (the intake change is what matters) but does affect
  the absolute calorie numbers (maintenance, goal intake).
- **Body fat from BMI** (Jackson) can be badly off for muscular or very lean people; enter a
  measured `body_fat_pct` when available.
- **Simplifications vs the Planner:** age is not advanced during the run; sodium change defaults
  to 0; the goal intake is one constant intake (the Planner's own phasing may differ); the
  maintenance-after-goal ignores glycogen/fluid re-equilibration (a few hundred grams).
- Adults only; not for pregnancy, growth, disease or medical advice.

## Variants

- `linear`: the appendix's closed-form approximation (eq. 14). No early glycogen/water drop,
  instant adaptive thermogenesis. Default example: 87.0 kg vs 86.4 kg (full) after one year.
- `trial_adherence`: `adherence_mean = 0.47`, the share of a 25% prescription achieved over two
  years in CALERIE 2 (DRAFT verify). Default example: 93.7 kg instead of 86.4 kg.

## Sanity checks (test_model.py)

Default placeholder person (man, 40 y, 180 cm, 100 kg, sedentary, −500 kcal/day):

| check | this model | Hall et al. 2011 |
|---|---|---|
| change after 8 years (≈ steady state) | −23.8 kg | ~10 kcal/day per lb → −22.7 kg ("average overweight adult", summary) |
| share of it reached at 1 year / 3 years | 57% / 94% | "about half in about 1 year, 95% in about 3 years" |
| linearised time constant τ | 518 days | ~1 year for typical adults |
| zero energy change | weight constant to 1e-6 kg over 3 years | — |

Also tested: hand calculations of Mifflin-St Jeor and eq. 4; more activity / bigger cut → more
loss; leaner start → smaller eventual change but shorter τ (eqs. 16-17); weigh-ins behind /
on / ahead of plan → adherence low / 1.0 / high; weigh-ins narrow the band; the goal search
hits the goal; lb/in inputs equal kg/cm; bad inputs raise clear `ValueError`s.

## Data that would calibrate it

No `data/backtest.csv` yet. A backtest would need individual dated weights with a known
prescription; columns would be: `sex, age, height_cm, weight, body_fat_pct, pal,
intake_change, activity_change_pct, start_date, target_date, actual_weight` (+ optional early
weigh-ins to test the adherence fit), scored on the target weight (error, band coverage).
Candidate sources (none are open downloads):

- **CALERIE 2** (2-year 25% calorie restriction, n = 218): individual data by registration at
  calerie.duke.edu.
- **Look AHEAD** and **Diabetes Prevention Program (DPP)**: NIDDK Central Repository, with a data
  use agreement.
- Consumer weigh-in logs (self-reported) if the site later collects them with consent.

## References

- Hall KD, Sacks G, Chandramohan D, et al. Quantification of the effect of energy imbalance on
  bodyweight. Lancet 2011;378:826-37; and its web appendix "Dynamic Mathematical Model of Body
  Weight Change in Adults" (niddk.nih.gov/-/media/Files/BWP/Hall_Lancet_Web_Appendix.pdf).
- Chow CC, Hall KD. The dynamics of human body weight change. PLoS Comput Biol 2008;4:e1000045.
- Hall KD. Predicting metabolic adaptation, body weight change, and energy intake in humans.
  Am J Physiol Endocrinol Metab 2010;298:E449-66.
- Hall KD, Jordan PN. Modeling weight-loss maintenance to help prevent body weight regain.
  Am J Clin Nutr 2008;88:1495-503.
- Forbes GB. Lean body mass-body fat interrelationships in humans. Nutr Rev 1987;45:225-31.
- Jackson AS, et al. The effect of sex, age and race on estimating percentage body fat from body
  mass index: the Heritage Family Study. Int J Obes 2002;26:789-96.
- Mifflin MD, St Jeor ST, et al. A new predictive equation for resting energy expenditure in
  healthy individuals. Am J Clin Nutr 1990;51:241-7.
- Nelson KM, et al. Prediction of resting energy expenditure from fat-free mass and fat mass.
  Am J Clin Nutr 1992;56:848-56.
- Ravussin E, et al. A 2-year randomized controlled trial of human caloric restriction
  (CALERIE). J Gerontol A Biol Sci Med Sci 2015;70:1097-104.
- FAO/WHO/UNU. Human energy requirements. Food and Nutrition Technical Report Series 1, 2004.
- Thomas DM, et al. (Pennington) simpler energy-balance models were considered; the appendix's
  own linearisation was chosen as the simple variant because it shares all constants with the
  full model.

## Public page

`/weight_loss/` (`site.py`, page words in `web/site/weight_loss/index.html`): an in-browser weigh-in
log and planner (`web/static/apps/weight_loss.js`, a line-by-line copy of this model's hall2011
method, fit, bands and goal search, checked against `model.predict` under node by
`tests/test_weight_loss_app.py`), plus a table of what a steady 250/500/750 kcal/day cut does for
two illustrative (made-up) adults. The log is kept only in the visitor's browser (localStorage
`bm.log.weight_loss.v1`, shared progress-log format: `settings` + `entries` of
`{date, weight, unit}`); weigh-ins before the start date are kept but not used. `site_*` params
are page-only input limits and the default horizon. The page says it is not medical advice and
not backtested.

## Changelog

- 0.1.1 — public page with an in-browser weigh-in log and planner (site.py, web/static/apps/weight_loss.js); page-only `site_*` params; no change to the model.
- 0.1.0 — initial version: Hall 2011 dynamic model, linear variant, adherence fit to weigh-ins,
  DRAFT uncertainty bands.
