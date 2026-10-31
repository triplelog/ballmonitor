import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from .models import RankingResult


def calculate_correlations(
    x_vals: List[float], y_vals: List[float]
) -> Dict[str, float]:
    """Calculate Pearson, logarithmic, and Spearman rank correlations."""
    if len(x_vals) < 3 or len(y_vals) < 3:
        return {"r": 0.0, "r2": 0.0, "log_r": 0.0, "log_r2": 0.0}

    x = np.array(x_vals, dtype=float)
    y = np.array(y_vals, dtype=float)

    # Linear correlation
    lin_r = float(np.corrcoef(x, y)[0, 1]) if np.std(x) > 0 and np.std(y) > 0 else 0.0

    # Logarithmic correlation (x > 0 required)
    mask = x > 0
    if np.sum(mask) >= 3 and np.std(y[mask]) > 0 and np.std(np.log(x[mask])) > 0:
        log_r = float(np.corrcoef(np.log(x[mask]), y[mask])[0, 1])
    else:
        log_r = 0.0

    return {
        "r": lin_r,
        "r2": lin_r ** 2,
        "log_r": log_r,
        "log_r2": log_r ** 2,
    }


class Evaluator:
    """Evaluates offer-based rankings against recruiting consensus and on-field metrics."""

    @staticmethod
    def compare_with_rivals(
        result: RankingResult, rivals_map: Dict[str, Tuple[int, float]], top_n: int = 50
    ) -> Dict[str, any]:
        """Compare model class rank against Rivals class rank."""
        paired: List[Dict[str, any]] = []
        my_ranks: List[float] = []
        rivals_ranks: List[float] = []

        for team in result.teams[:top_n]:
            name = team.name
            rivals_info = rivals_map.get(name)
            if rivals_info:
                r_rank, r_pts = rivals_info
                diff = r_rank - team.rank  # positive = model ranked them higher than Rivals
                paired.append({
                    "team": name,
                    "model_rank": team.rank,
                    "rivals_rank": r_rank,
                    "diff": diff,
                    "model_score": team.total_score,
                    "rivals_points": r_pts,
                })
                my_ranks.append(team.rank)
                rivals_ranks.append(r_rank)

        corrs = calculate_correlations(my_ranks, rivals_ranks)
        return {
            "paired_teams": paired,
            "correlations": corrs,
            "sample_size": len(paired),
        }

    @staticmethod
    def evaluate_future_fei(
        result: RankingResult,
        fei_by_year: Dict[int, Dict[str, float]],
        years_out: int = 4,
        top_n: int = 100,
    ) -> Dict[str, any]:
        """Correlate recruit class rank against cumulative post-commitment FEI ratings."""
        base_year = result.year
        valid_ranks: List[float] = []
        cumulative_feis: List[float] = []
        rows: List[Dict[str, any]] = []

        for team in result.teams[:top_n]:
            name = team.name
            feis = []
            has_all = True
            for offset in range(years_out):
                yr = base_year + offset
                val = fei_by_year.get(yr, {}).get(name)
                if val is None:
                    has_all = False
                    break
                feis.append(val)

            if has_all and feis:
                cum_fei = sum(feis)
                valid_ranks.append(team.rank)
                cumulative_feis.append(cum_fei)
                rows.append({
                    "team": name,
                    "rank": team.rank,
                    "cumulative_fei": cum_fei,
                    "annual_feis": feis,
                })

        corrs = calculate_correlations(valid_ranks, cumulative_feis)
        return {
            "teams": rows,
            "correlations": corrs,
            "sample_size": len(rows),
        }
