# cfbRec: Offer-Based College Football Recruiting Rankings

An objective, coach-driven college football recruiting evaluation model that ranks team recruiting classes based entirely on **scholarship offers** rather than subjective media/analyst star ratings.

---

## 1. The Core Thesis

Traditional recruiting services (Rivals, 247Sports, On3, ESPN) rely on subjective human evaluations that often suffer from:
1. **Analyst Bias & Regional Hype**: Perceptions of power conferences (SEC, Big Ten) often inflate player ratings.
2. **Reverse Causality / Offer Anchoring**: When Nick Saban or Kirby Smart offers an unheralded 3-star recruit, recruiting sites routinely bump that player to 4 or 5 stars, taking the coach's word as validation.
3. **Accountability Gap**: Media analysts face little consequence when overrated 5-stars bust. In contrast, **college football coaching staffs risk their careers and millions of dollars on talent evaluation**.

---

## 2. Mathematical Framework

`cfbRec` models each recruit's commitment as a **multi-competitor choice problem**:
- **Winner**: The school the recruit commits to ($c_i$).
- **Losers**: All other schools that extended an offer to that recruit ($S_i \setminus \{c_i\}$).

### A. Global Plackett-Luce Model (Convex MAP Estimation)
Unlike traditional sequential Elo updates (which are order-dependent and require arbitrary $K$-factors), `cfbRec` solves for the latent prestige parameter vector $\gamma \in \mathbb{R}^T$ across all programs simultaneously by minimizing the penalized negative log-likelihood:

$$\mathcal{L}(\gamma) = -\sum_{i=1}^N \left( \gamma_{c_i} - \ln \sum_{s \in S_i} e^{\gamma_s} \right) + \frac{\lambda}{2} \|\gamma\|^2$$

The gradient has a simple closed form:
$$\nabla_t \mathcal{L}(\gamma) = \lambda \gamma_t - \text{Commits}(t) + \sum_{i : t \in S_i} \frac{e^{\gamma_t}}{\sum_{s \in S_i} e^{\gamma_s}}$$

This objective is strictly convex, converging to a unique global optimum via L-BFGS-B in $<0.5$ seconds. The parameters $\gamma_t$ are then converted to the standard Elo scale:

$$\text{Elo}_t = 1500 + \frac{400}{\ln 10} \gamma_t$$

### B. Recruit Quality Valuation
A recruit's caliber is determined by the collective prestige of the programs they defeated:

$$q_i = \left( \sum_{s \in S_i \setminus \{c_i\}} e^{\gamma_s} \right)^p$$

where $p \approx 0.5$ provides diminishing marginal returns for additional offers.

### C. Class Score & Diminishing Marginal Returns
To prevent roster bloat from artificially inflating team class scores, a team's total score applies a rank decay factor $\delta = 0.95$ across the team's recruits sorted in descending order:

$$\text{Class Score} = \sum_{r=1}^M q_{(r)} \cdot \delta^{r-1}$$

---

## 3. Empirical Validation (FEI Backtest)

Backtested across **751 team-seasons** (2012–2017 recruiting cohorts evaluated against 4-year cumulative on-field Football Outsiders FEI ratings):

| Method / Framework | Linear $r$ | Linear $R^2$ | Log(rank) $r$ | Log $R^2$ |
|:---|:---:|:---:|:---:|:---:|
| **Plackett-Luce (Convex MAP)** | **-0.6610** | **0.4370** | **-0.6354** | **0.4037** |
| Sequential Elo (Legacy SGD) | -0.6544 | 0.4282 | -0.6295 | 0.3962 |
| Rivals Consensus (Human Scouts) | -0.6614 | 0.4375 | -0.6573 | 0.4320 |

**Note (v0.4.0):** this legacy study is in-sample (parameters chosen on the same 2012–2017 cohorts). The walk-forward study in RESEARCH.md finds the offer model slightly *below* the industry consensus ranking out of sample (Spearman 0.69 vs 0.71 over 6 test class years), on par with star averages.

---

## 4. Running the Model

```bash
# Run 2021 rankings with Rivals comparison and geographic footprint metrics
python run_model.py 2021 --top 15 --compare-rivals --geo

# Compare Plackett-Luce vs Sequential Elo vs Rivals across 2012-2017
python evaluate.py --start 2012 --end 2017

# Export full national rankings to CSV
python run_model.py 2021 --format csv --output rankings_2021.csv
```
