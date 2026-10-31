#!/usr/bin/env python3
"""
CLI runner for National Signing Day forecasting and 'what-if' recruit commitment scenarios.

Usage:
    # Run baseline forecast for 2026
    python forecast.py 2026 --top 15

    # Inspect commitment probabilities for a specific unsigned recruit
    python forecast.py 2026 --predict-recruit "Jontavius Wyman"

    # Simulate what happens to rankings if specific recruits commit to specific schools
    python forecast.py 2026 --override "JONTAVIUS WYMAN=Ole Miss" --override "AIDEN KNOX=Georgia" --compare
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_loader import DataLoader
from src.elo_engine import EloEngine
from src.geocoding import get_campus_coords, haversine_miles
from src.models import RankingMethod
from src.forecasting import CommitmentPredictor, SigningDayForecaster


def parse_args():
    parser = argparse.ArgumentParser(
        description="Forecast final recruiting class rankings and simulate what-if scenarios."
    )
    parser.add_argument(
        "pos_year",
        nargs="?",
        type=int,
        default=None,
        help="Recruiting class year (default: 2026).",
    )
    parser.add_argument(
        "--year",
        "-y",
        type=int,
        default=None,
        help="Recruiting class year (default: 2026).",
    )
    parser.add_argument(
        "--simulations",
        "-s",
        type=int,
        default=500,
        help="Number of Monte Carlo simulations (default: 500).",
    )
    parser.add_argument(
        "--top",
        "-n",
        type=int,
        default=20,
        help="Number of teams to display (default: 20).",
    )
    parser.add_argument(
        "--predict-recruit",
        "-p",
        type=str,
        default=None,
        help="Display commitment probabilities for a specific recruit.",
    )
    parser.add_argument(
        "--override",
        "-o",
        action="append",
        default=[],
        help="Override a recruit's commitment: 'Recruit Name=Team'. Can be passed multiple times.",
    )
    parser.add_argument(
        "--compare",
        "-c",
        action="store_true",
        help="Compare overridden scenario against baseline forecast.",
    )
    return parser.parse_args()


def parse_overrides(override_args: List[str]) -> Dict[str, str]:
    overrides: Dict[str, str] = {}
    for item in override_args:
        if "=" in item:
            k, v = item.split("=", 1)
            overrides[k.strip().upper()] = v.strip()
    return overrides


def render_forecast_table(fc_result, top_n: int = 20) -> str:
    lines = [
        "=" * 102,
        f"     CLASS OF {fc_result.year} NATIONAL SIGNING DAY FORECAST ({fc_result.n_simulations} SIMULATIONS)",
        f"     Unsigned Recruits Modeled: {fc_result.unsigned_count} | Active Overrides: {len(fc_result.overrides)}",
        "=" * 102,
        f"{'Proj#':<6} {'Team':<20} {'Curr#':<6} {'Curr Score':<11} | {'Proj Score (±std)':<18} {'Median Proj':<12} | {'P(Top 1)':<9} {'P(Top 5)':<9} {'P(Top 10)'}",
        "-" * 102,
    ]
    for idx, t in enumerate(fc_result.teams[:top_n], 1):
        score_str = f"{t.projected_score_mean:5.2f} (±{t.projected_score_std:4.2f})"
        rank_ci = f"#{t.projected_rank_median} (#{t.projected_rank_p10}-#{t.projected_rank_p90})"
        curr_rank_str = f"#{t.current_rank}" if t.current_rank > 0 else "Unranked"
        lines.append(
            f"{idx:<6} {t.name:<20} {curr_rank_str:<6} {t.current_score:<11.2f} | "
            f"{score_str:<18} {rank_ci:<12} | {t.prob_top1*100:>6.1f}%  {t.prob_top5*100:>6.1f}%  {t.prob_top10*100:>6.1f}%"
        )
    lines.append("=" * 102)
    return "\n".join(lines)


def render_comparison_table(comparison, max_rows: int = 20) -> str:
    lines = [
        "=" * 88,
        f"     WHAT-IF SCENARIO IMPACT COMPARISON (CLASS OF {comparison.year})",
        "=" * 88,
        "Overrides Applied:",
    ]
    recipient_schools = set(comparison.overrides.values())
    for rec, team in comparison.overrides.items():
        lines.append(f"  • {rec} -> {team}")
    lines.append("-" * 88)
    lines.append(f"{'Team':<22} {'Base Rank':<11} {'New Rank':<11} {'Rank Delta':<12} {'Score Delta'}")
    lines.append("-" * 88)

    # Prioritize recipient schools first, then top-ranked schools with changes
    recipients = [d for d in comparison.deltas if d.team in recipient_schools]
    others = [
        d for d in comparison.notable_movers
        if d.team not in recipient_schools and (d.scenario_rank <= 50 or abs(d.score_delta) >= 0.20)
    ]
    display_deltas = recipients + others[:max_rows - len(recipients)]

    for d in display_deltas:
        sign = "+" if d.rank_delta > 0 else ""
        delta_str = f"{sign}{d.rank_delta} ranks" if d.rank_delta != 0 else "0 (Held)"
        score_sign = "+" if d.score_delta > 0 else ""
        is_recip = " *" if d.team in recipient_schools else ""
        lines.append(
            f"{d.team + is_recip:<22} #{d.baseline_rank:<10} #{d.scenario_rank:<10} {delta_str:<12} {score_sign}{d.score_delta:.2f} pts"
        )
    lines.append("=" * 88)
    if any(d.team in recipient_schools for d in display_deltas):
        lines.append("(* = direct commit recipient)")
    return "\n".join(lines)


def main():
    args = parse_args()
    year = args.pos_year or args.year or 2026
    loader = DataLoader(PROJECT_ROOT / "data")
    recruits = loader.load_recruits(year, geolocate=True, include_uncommitted=True)

    overrides = parse_overrides(args.override)
    forecaster = SigningDayForecaster()

    # Predict single recruit if requested
    if args.predict_recruit:
        query = args.predict_recruit.strip().upper()
        matches = [r for r in recruits if query in r.name.strip().upper()]
        if not matches:
            print(f"Recruit matching '{args.predict_recruit}' not found in {year} dataset.")
            sys.exit(1)
        target_r = matches[0]

        # Fit prestige on commits
        engine = EloEngine()
        res = engine.run(year, [r for r in recruits if r.committed_team and r.committed_team != "0"])
        predictor = CommitmentPredictor(team_ratings={t.name: t for t in res.teams})
        probs = predictor.predict_probabilities(target_r)

        print("\n" + "=" * 70)
        print(f"COMMITMENT PREDICTION: {target_r.name} ({target_r.position}, {target_r.stars}★)")
        print(f"Hometown: {target_r.hometown} | Current Commit Status: {target_r.committed_team or 'Uncommitted'}")
        print("=" * 70)
        print(f"{'School':<25} {'Commit Prob':<14} {'Offers & Distance'}")
        print("-" * 70)
        for school, p in sorted(probs.items(), key=lambda x: x[1], reverse=True):
            campus = get_campus_coords(school)
            dist_str = ""
            if campus and (target_r.latitude != 0 or target_r.longitude != 0):
                dist = haversine_miles((target_r.latitude, target_r.longitude), campus)
                dist_str = f"{dist:.0f} miles"
            print(f"{school:<25} {p*100:>6.1f}%        {dist_str}")
        print("=" * 70 + "\n")
        return

    # Scenario comparison
    if args.compare and overrides:
        comparison = forecaster.compare_scenarios(
            year=year,
            recruits=recruits,
            scenario_overrides=overrides,
            n_simulations=args.simulations,
        )
        print(render_comparison_table(comparison))
        return

    # Standard forecast run
    fc_result = forecaster.forecast(
        year=year,
        recruits=recruits,
        overrides=overrides,
        n_simulations=args.simulations,
    )
    print(render_forecast_table(fc_result, top_n=args.top))


if __name__ == "__main__":
    main()
