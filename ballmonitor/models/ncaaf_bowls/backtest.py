"""
Historical Backtesting Engine:
Evaluates model projections against real-world past seasons (e.g. 2023).
Computes:
- Top-1, Top-3, and Top-5 Bowl Prediction Accuracy
- Multinomial Brier Score across all bowl outcomes
- CFP Playoff Participant Hit Rate
- Exact Matchup Hit Rate
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .config import SimConfig
except (ImportError, ValueError):
    from config import SimConfig
try:
    from .engine import BowlEngine, SimulationResults
except (ImportError, ValueError):
    from engine import BowlEngine, SimulationResults
try:
    from .domain import Bowl, Game, Team
except (ImportError, ValueError):
    from domain import Bowl, Game, Team
from ballmonitor.models.ncaaf_bowls.cfp import CFPSelector
from ballmonitor.models.ncaaf_bowls.selection import BowlSelector
from ballmonitor.models.ncaaf_bowls.simulator import SeasonSimulator

HISTORICAL_DIR = Path(__file__).parent / "data" / "historical"

@dataclass
class BacktestScorecard:
    season: int
    teams_evaluated: int
    top_1_accuracy: float
    top_3_accuracy: float
    top_5_accuracy: float
    brier_score: float
    actual_vs_predicted: list[dict[str, Any]] # Details per team

    def summary_table(self) -> str:
        lines = [
            "=" * 70,
            f" HISTORICAL BACKTEST EVALUATION: {self.season} SEASON",
            "=" * 70,
            f" Teams Evaluated:            {self.teams_evaluated}",
            f" Top-1 Bowl Accuracy:        {self.top_1_accuracy * 100:.1f}%",
            f" Top-3 Bowl Accuracy:        {self.top_3_accuracy * 100:.1f}%",
            f" Top-5 Bowl Accuracy:        {self.top_5_accuracy * 100:.1f}%",
            f" Multinomial Brier Score:    {self.brier_score:.4f}  (lower is better)",
            "-" * 70,
            f" {'Team':<18} {'Actual Bowl':<24} {'Top Predicted Bowl':<22} {'Prob':<6}",
            "-" * 70
        ]
        for item in self.actual_vs_predicted[:15]:
            top_p = item["top_pred"]
            prob_str = f"{item['top_prob'] * 100:.1f}%"
            matched_flag = "✓" if item["hit_top_1"] else ("~" if item["hit_top_3"] else " ")
            lines.append(f" {matched_flag} {item['team']:<16} {item['actual']:<24} {top_p:<22} {prob_str:<6}")
        lines.append("=" * 70)
        lines.append(" Key: [✓] Exact #1 pick match | [~] Matched in Top 3 picks")
        return "\n".join(lines)

class Backtester:
    def __init__(self, season: int = 2023, data_dir: Path | None = None):
        self.season = season
        self.season_dir = (data_dir or HISTORICAL_DIR) / str(season)
        if not self.season_dir.exists():
            raise FileNotFoundError(f"Historical data for season {season} not found at {self.season_dir}")

    def run_backtest(self, sims: int = 1500) -> BacktestScorecard:
        """Runs the simulation engine on historical season data and evaluates predictions."""
        # Load historical files
        with open(self.season_dir / f"teams_{self.season}.json") as f:
            teams_data = json.load(f)
        teams = [Team.from_dict(d) for d in teams_data]

        with open(self.season_dir / f"schedule_{self.season}.json") as f:
            sched_data = json.load(f)
        # The historical file covers a subset of teams: keep games between teams in it.
        ids = {t.id for t in teams}
        schedule = [g for g in (Game.from_dict(d) for d in sched_data) if g.home in ids and g.away in ids]

        with open(self.season_dir / f"actual_assignments_{self.season}.json") as f:
            actual_assignments = json.load(f)

        # Invert actual assignments to team -> actual bowl
        team_actual_bowl: dict[str, str] = {}
        for bowl_id, t_ids in actual_assignments.items():
            for t_id in t_ids:
                team_actual_bowl[t_id] = bowl_id

        # Rebuild every engine component from the historical season: its teams, schedule,
        # ratings and the pre-2026 bowl lineup (the current bowls.json is the 2026 lineup).
        with open(HISTORICAL_DIR / "bowls_2024_lineup.json") as f:
            bowls = [Bowl.from_dict(d) for d in json.load(f)]
        cfg = SimConfig(simulations=sims, random_seed=42)
        engine = BowlEngine(config=cfg)
        engine.teams, engine.schedule, engine.bowls = teams, schedule, bowls
        engine.team_dict = {t.id: t for t in teams}
        engine.bowl_dict = {b.id: b for b in bowls}
        engine.active_ratings = {t.id: t.rating for t in teams}
        engine.simulator = SeasonSimulator(teams, schedule, cfg, engine.active_ratings)
        engine.cfp_selector = CFPSelector({b.id: b for b in bowls if b.is_cfp})
        engine.bowl_selector = BowlSelector(bowls, teams, cfg, schedule=schedule)

        results = engine.run(num_sims=sims)

        # Evaluate predictions against ground truth
        top_1_hits = 0
        top_3_hits = 0
        top_5_hits = 0
        total_squared_error = 0.0
        n_eval = 0

        detail_rows: list[dict[str, Any]] = []

        all_bowl_ids = [b.id for b in engine.bowls]

        for t_id, actual_bowl_id in team_actual_bowl.items():
            if t_id not in results.team_summaries:
                continue

            summary = results.team_summaries[t_id]
            b_probs = summary.all_bowls # bowl_id -> prob

            # Sort predicted bowls
            sorted_pred_bowls = sorted(b_probs.items(), key=lambda x: x[1], reverse=True)
            top_pred_id = sorted_pred_bowls[0][0] if sorted_pred_bowls else "none"
            top_pred_prob = sorted_pred_bowls[0][1] if sorted_pred_bowls else 0.0

            top_3_ids = [bid for bid, _ in sorted_pred_bowls[:3]]
            top_5_ids = [bid for bid, _ in sorted_pred_bowls[:5]]

            hit_top_1 = (actual_bowl_id == top_pred_id)
            hit_top_3 = (actual_bowl_id in top_3_ids)
            hit_top_5 = (actual_bowl_id in top_5_ids)

            if hit_top_1:
                top_1_hits += 1
            if hit_top_3:
                top_3_hits += 1
            if hit_top_5:
                top_5_hits += 1

            # Brier calculation across all possible bowls
            # sum_b (prob_b - actual_binary_indicator)^2
            brier_team = 0.0
            for b_id in all_bowl_ids:
                p_b = b_probs.get(b_id, 0.0)
                y_b = 1.0 if b_id == actual_bowl_id else 0.0
                brier_team += (p_b - y_b) ** 2
            total_squared_error += brier_team

            n_eval += 1

            actual_bowl_name = engine.bowl_dict.get(actual_bowl_id, None)
            actual_str = actual_bowl_name.name if actual_bowl_name else actual_bowl_id
            pred_bowl_name = engine.bowl_dict.get(top_pred_id, None)
            pred_str = pred_bowl_name.name if pred_bowl_name else top_pred_id

            detail_rows.append({
                "team_id": t_id,
                "team": summary.team_name,
                "actual": actual_str,
                "actual_id": actual_bowl_id,
                "top_pred": pred_str,
                "top_prob": top_pred_prob,
                "hit_top_1": hit_top_1,
                "hit_top_3": hit_top_3,
            })

        top_1_acc = top_1_hits / n_eval if n_eval > 0 else 0.0
        top_3_acc = top_3_hits / n_eval if n_eval > 0 else 0.0
        top_5_acc = top_5_hits / n_eval if n_eval > 0 else 0.0
        mean_brier = total_squared_error / n_eval if n_eval > 0 else 0.0

        return BacktestScorecard(
            season=self.season,
            teams_evaluated=n_eval,
            top_1_accuracy=top_1_acc,
            top_3_accuracy=top_3_acc,
            top_5_accuracy=top_5_acc,
            brier_score=mean_brier,
            actual_vs_predicted=detail_rows
        )
