# College Football Bowl & Playoff Simulator (`bowls/`)

A probabilistic Monte Carlo simulation and bowl selection engine that models the rest of the college football season, projects the **12-team College Football Playoff (CFP)** field and seed lines, and executes conference **bowl picking hierarchies and selection rules** to forecast postseason destinations, predicted opponents, and game win odds.

---

## 1. How the Model Works

The simulation runs thousands of iterations through an end-to-end pipeline:

```
[ Active Ratings: SP+ / FPI / Elo / Custom ] + [ Remaining Schedule ]
                          │
                          ▼
        1. Rest-of-Season Simulation (Monte Carlo)
        - Supports What-If Scenarios (--win-out, --lose-out, --scenario)
        - Normal CDF Win Probability: Φ((RatingDiff + HomeAdv) / MarginSD)
        - Standings & Conference Tiebreakers
        - Neutral-Site Conference Championship Games
                          │
                          ▼
        2. 12-Team College Football Playoff (CFP)
        - Committee Resume Score Ranking (Wins, Power, Conf Title, SOS)
        - Top 5 Conf Champions Auto-Bids (Top 4 get 1st-Round Byes)
        - 7 At-Large Bids (Seeds 5–12 on campus: 5v12, 6v11, 7v10, 8v9)
        - Full Playoff Bracket Simulation (1st round -> QF in NY6 -> Semis -> Natty)
        - Eliminates the 12 Playoff Teams from Non-CFP Bowl Pool
                          │
                          ▼
        3. Bowl Selection Pecking Order & Postseason Simulation
        - Bowl Eligibility Check (6+ wins; 5–7 APR tiebreaker if needed)
        - Contracted conference slots from data/bowls.json, in each conference's pick order
        - Notre Dame / ACC rule, Big Ten conference-win + anti-repeat rules, SEC anti-repeat
        - Pac-12 legacy slots (2026 agreement) and new-Pac-12 slots
        - Pooled Group-of-6 slots, then at-large fill
        - Bowl Game Simulation to Project Game Winners and Matchups
                          │
                          ▼
[ Postseason Odds, Opponent Breakdown & Bowl Win Probabilities ]
```

---

## 2. Advanced Features

### A. Power Rankings Swapping (`--ratings`)
Easily swap power rating sets:
- Built-in options: `default` / `fpi` (ESPN FPI), `results` (results-only fit from this season's scores)
- Custom files: path to any `.csv` with `team,rating` or `.json` mapping `{"team_id": rating}`
- Blending: programmatic support to blend multiple rating sets (e.g., 50% FPI + 50% results)

### B. What-If & Scenario Analysis (`--win-out`, `--lose-out`, `--scenario`)
Evaluate the exact impact of hypothetical late-season outcomes:
- `"team:win_out"`: Forces a team to win all remaining regular-season games.
- `"team:lose_out"`: Forces a team to drop all remaining games.
- `"team_a>team_b"`: Forces the outcome of a specific upcoming rivalry matchup.
- Example: `python3 -m bowls.cli team "Michigan" --win-out "Michigan"` demonstrates how winning out catapults their Citrus Bowl odds from 33.7% to 83.7% and opens CFP possibilities.

### C. Postseason Opponents (Overall & Per Game)
- **Overall Opponents**: Across all potential postseason games (bowls, CFP first round, quarterfinals), see which specific teams a school is most likely to encounter, along with the expected head-to-head win rate.
- **Per-Bowl Opponents**: If a school is selected for a particular bowl (e.g. Pop-Tarts Bowl), see the distribution of who they will face in that exact game.

### D. Bowl Win Probabilities
- **$P(\text{Win Game} \mid \text{in Bowl})$**: Conditional probability of winning that bowl, integrated across the distribution of projected opponents and power rating margins.
- **$P(\text{Reach \& Win})$**: Unconditional joint probability of being selected for and winning that bowl.
- **Overall Postseason Win Prob**: Total probability of winning at least one postseason bowl / CFP game.

### E. Historical Backtesting (`bowls.backtest` / `cli backtest`)
- Backtest against past seasons (e.g. 2023 season snapshot before conference championship week).
- Evaluates:
  - **Top-1 Bowl Accuracy**: % of teams whose actual bowl was the #1 prediction.
  - **Top-3 Bowl Accuracy**: % of teams whose actual bowl was in the Top 3 predictions.
  - **Top-5 Bowl Accuracy**: % of teams whose actual bowl was in the Top 5 predictions.
  - **Multinomial Brier Score**: Probabilistic calibration score across all bowl slots.

---

## 3. Directory Layout

```
bowls/
├── README.md              # Complete model documentation and rules
├── __init__.py            # Module exports
├── config.py              # Tunable parameters and weights
├── models.py              # Team, Bowl, Game, TeamSimState dataclasses
├── ratings.py             # RatingManager for loading and blending power ratings
├── scenarios.py           # What-If scenario engine (win-out, lose-out, forced games)
├── simulator.py           # Rest-of-season Monte Carlo simulation engine
├── cfp.py                 # 12-team CFP selection, seeding, and playoff game simulation
├── selection.py           # Bowl picking order and conference tie-in engine
├── engine.py              # Master orchestration and statistical aggregator
├── backtest.py            # Historical backtesting engine and scorecards
├── cli.py                 # Interactive command-line interface
├── data/
│   ├── teams.json         # 138 FBS teams (built by fetch.py from ESPN)
│   ├── bowls.json         # 2026-27: 6 CFP + 35 FBS bowls with tie-in slots
│   ├── schedule.json      # Every remaining regular-season game (built by fetch.py)
│   ├── results.json       # Completed games (built by fetch.py)
│   ├── ratings_fpi.csv    # ESPN FPI ratings
│   ├── ratings_results.csv# Results-only ridge rating
│   ├── team_profiles.csv  # Campus location, brand, APR (hand-maintained)
│   ├── meta.json          # Snapshot time and sources
│   └── historical/
│       └── 2023/          # 2023 season snapshot and ground truth assignments
└── tests/
    ├── test_backtest.py       # Tests for historical backtesting scorecard
    ├── test_ratings.py        # Tests for loading and blending ratings
    ├── test_scenarios.py      # Tests for What-If scenario overrides
    ├── test_simulation.py     # Tests for win probabilities and schedules
    ├── test_cfp.py            # Tests for 12-team CFP rules and byes
    ├── test_bowl_selection.py # Tests for tie-in enforcement and pick order
    └── test_end_to_end.py     # Full integration test
```

---

## 4. CLI Usage Examples

### 1. Show 12-Team CFP Projections with Different Ratings
```bash
# Default ratings
python3 -m bowls.cli cfp --sims 2000

# Using the results-only rating
python3 -m bowls.cli cfp --ratings results --sims 2000

# Using ESPN FPI ratings
python3 -m bowls.cli cfp --ratings fpi --sims 2000
```

### 2. Inspect a Team's Opponents, Win Odds & Bowl Outlook
```bash
python3 -m bowls.cli team "Texas Tech"
```
```text
============================================================================
 TEXAS TECH (Big 12) | Power Rating: +9.5
============================================================================
 Projected Record:                 7.0 - 3.0
 Bowl Eligible Probability:        >99%
 Conf Champion Probability:        0.0%
 12-Team CFP Probability:          0.0% (Quarterfinal Bye: 0.0%)
 OVERALL PROBABILITY OF WINNING A BOWL / CFP GAME: 43.3%
----------------------------------------------------------------------------
 MOST LIKELY POSTSEASON OPPONENTS (OVERALL):
   vs Washington State           47.0% chance  (Win Rate vs Washington State: 52.5%)
   vs LSU                        31.0% chance  (Win Rate vs LSU: 30.1%)
   vs Texas A&M                   9.3% chance  (Win Rate vs Texas A&M: 39.3%)
----------------------------------------------------------------------------
 PROJECTED BOWL DESTINATIONS & GAME WIN PROBABILITIES:

   ➤ Valero Alamo Bowl                49.7%  ████████████
     P(Win Game | in bowl): 53.7%   | P(Reach & Win): 26.7%
     Projected Opponents: Washington State (94.6%, 52.5% win%), Washington (2.7%, 75.0% win%)

   ➤ TaxAct Texas Bowl                47.7%  ███████████
     P(Win Game | in bowl): 30.8%   | P(Reach & Win): 14.7%
     Projected Opponents: LSU (64.3%, 30.4% win%), Texas A&M (19.6%, 39.3% win%)
============================================================================
```

### 3. "What-If" Analysis: What Happens if a Team Wins Out?
```bash
# What if Michigan wins out?
python3 -m bowls.cli team "Michigan" --win-out "Michigan"

# What if Iowa State wins out?
python3 -m bowls.cli team "Iowa State" --win-out "Iowa State"

# Custom scenario with game forcing
python3 -m bowls.cli run --scenario "texas_am>lsu,ohio_state>michigan"
```

### 4. Backtest the Model Against Past Seasons
```bash
python3 -m bowls.cli backtest --season 2023 --sims 1500
```
```text
======================================================================
 HISTORICAL BACKTEST EVALUATION: 2023 SEASON
======================================================================
 Teams Evaluated:            42
 Top-1 Bowl Accuracy:        26.2%
 Top-3 Bowl Accuracy:        61.9%
 Top-5 Bowl Accuracy:        71.4%
 Multinomial Brier Score:    1.0981  (lower is better)
----------------------------------------------------------------------
 Team               Actual Bowl              Top Predicted Bowl     Prob  
----------------------------------------------------------------------
 ✓ Michigan         Rose Bowl Game           Rose Bowl Game         20.8% 
 ~ Alabama          Rose Bowl Game           Allstate Sugar Bowl    50.6% 
 ~ Washington       Allstate Sugar Bowl      Vrbo Fiesta Bowl       19.8% 
   Texas            Allstate Sugar Bowl      Vrbo Fiesta Bowl       85.8% 
 ✓ Tennessee        Cheez-It Citrus Bowl     Cheez-It Citrus Bowl   48.4% 
 ✓ Iowa             Cheez-It Citrus Bowl     Cheez-It Citrus Bowl   82.0% 
 ✓ LSU              ReliaQuest Bowl          ReliaQuest Bowl        54.4% 
======================================================================
```

### 5. Inspect a Specific Bowl Game
```bash
python3 -m bowls.cli bowl "Pop-Tarts Bowl"
python3 -m bowls.cli bowl "Citrus Bowl"
```

### 6. Conference Pecking Order Odds (Non-Playoff Bowl-Eligible Teams)
```bash
python3 -m bowls.cli pecking-order --conf SEC
python3 -m bowls.cli pecking-order --conf "Big 12"
python3 -m bowls.cli pecking-order --conf "Big Ten"
```

### 7. Historical Bowl Selection Empirical Analysis (2014–2023)
```bash
python3 -m bowls.cli history
```
Outputs empirical data on:
- Consecutive-year repeat avoidance frequencies (and repeat suppression ratios).
- Brand / fanbase selection bias and the +1.6 win equivalent brand premium.
- Campus-to-bowl geographic proximity and drive-in attendance rates.

---

## 5. Running Tests

```bash
.venv/bin/pytest bowls/tests
```
All 12 unit and integration tests verify win probabilities, CFP rules, bowl tie-ins, What-If overrides, ratings providers, backtest scorecards, and conference pecking order distributions.
