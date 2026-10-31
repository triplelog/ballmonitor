"""Temporal fitness tracking, recency discounting, and cross-distance delta transfer.

Models how a runner's latent fitness evolves over time:
1. Discounting stale races based on half-life decay.
2. Cross-distance transfer: If a runner has an older target-distance race (e.g. Marathon in 2024)
   and companion race (e.g. 5K in 2024), and a recent faster 5K in 2026, the marathon expectation
   is updated by transferring the 5K velocity improvement with an aerobic damping factor.
3. Temporal variance inflation: Uncertainty expands proportionally to elapsed time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ballmonitor.core.units import distance_label, format_time


@dataclass
class EffectiveRace:
    distance: float
    time: float
    weight: float
    year: int | None = None
    original_time: float | None = None
    note: str = ""


@dataclass
class FitnessEvaluation:
    effective_races: list[EffectiveRace]
    temporal_sigma_pct: float
    steps: list[str] = field(default_factory=list)
    fitness_delta_pct: float = 0.0
    transferred_target_time: float | None = None


def evaluate_fitness_over_time(
    raw_races: list[dict[str, Any]],
    target_distance: float,
    target_year: int | None,
    params: Any,
    target_when: float | None = None,
) -> FitnessEvaluation:
    """Evaluate temporal fitness drift and cross-distance transfer across races.

    `params` is the model's resolved Params (all coefficients and the
    `transfer_improvement` formula come from config.toml).

    Races may carry `when` (fractional year from an exact date); elapsed time for the
    recency weight and drift uncertainty then uses it, otherwise whole years.
    `target_when` is the fractional target date (falls back to `target_year`).
    """
    p = params
    transfer_short_to_long = p.transfer_short_to_long
    transfer_long_to_short = p.transfer_long_to_short
    fitness_half_life_months = p.fitness_half_life_months
    annual_fitness_drift_pct = p.annual_fitness_drift_pct
    max_stale_years = p.max_stale_years
    match_tol = p.same_distance_tolerance_doublings
    steps: list[str] = []

    if not raw_races:
        return FitnessEvaluation(effective_races=[], temporal_sigma_pct=0.0)

    # Determine reference year
    years_present = [r["year"] for r in raw_races if r.get("year")]
    if target_year is None:
        # No dates at all: treat every race as current (no recency discount, no drift)
        target_year = max(years_present) if years_present else 0

    # Parse raw races into standard entries
    parsed: list[dict[str, Any]] = []
    for r in raw_races:
        yr = r.get("year")
        yr_val = int(yr) if yr else target_year
        when = r.get("when")
        parsed.append({
            "distance": float(r["distance"]),
            "time": float(r["time"]),
            "year": yr_val,
            "when": float(when) if when is not None else float(yr_val),
            "name": r.get("name", ""),
        })
    if target_when is None:
        # Only a target year (or nothing): "now" is the start of that year, but never
        # earlier than the latest race (so same-year races count as current).
        target_when = max([float(target_year)] + [r["when"] for r in parsed])

    # Group races by distance to check for repeated distances across time
    by_dist: dict[float, list[dict[str, Any]]] = {}
    for r in parsed:
        by_dist.setdefault(r["distance"], []).append(r)

    # Sort each distance group by year
    for dist, r_list in by_dist.items():
        r_list.sort(key=lambda x: x["year"])

    # Look for cross-distance transfer opportunity:
    # A. Runner has an older race at or near the target distance (e.g. Marathon from Year Y_old)
    # B. Runner has a companion race at distance D_comp from Year Y_old
    # C. Runner has a newer race at distance D_comp from Year Y_new (Y_new > Y_old)
    transferred_time: float | None = None
    transfer_delta_pct: float = 0.0
    transfer_applied = False

    # Check if target distance exists in history
    near_target_races = [
        r for r in parsed if abs(math.log2(target_distance / r["distance"])) < match_tol
    ]

    if near_target_races:
        oldest_target = min(near_target_races, key=lambda x: x["year"])
        y_old = oldest_target["year"]
        delta_years = max(0, target_year - y_old)

        if delta_years >= 1:
            # Look for companion distance that was run in y_old AND later
            for comp_dist, comp_races in by_dist.items():
                if abs(math.log2(target_distance / comp_dist)) < match_tol:
                    continue  # Same as target distance

                old_comp = [r for r in comp_races if abs(r["year"] - y_old) <= 1]
                recent_comp = [r for r in comp_races if r["year"] >= target_year - 1 and r["year"] > y_old]

                if old_comp and recent_comp:
                    best_old_comp = min(old_comp, key=lambda x: x["time"])
                    best_recent_comp = min(recent_comp, key=lambda x: x["time"])

                    # Compute velocity delta on companion distance
                    v_old = best_old_comp["distance"] / best_old_comp["time"]
                    v_new = best_recent_comp["distance"] / best_recent_comp["time"]
                    delta_v = (v_new - v_old) / v_old

                    # Transfer factor: short-to-long or long-to-short
                    if best_recent_comp["distance"] < target_distance:
                        transfer_factor = transfer_short_to_long
                        direction_str = "short-to-long"
                    else:
                        transfer_factor = transfer_long_to_short
                        direction_str = "long-to-short"

                    effective_delta = p.formula(
                        "transfer_improvement", delta_v=delta_v, transfer_factor=transfer_factor
                    )
                    transfer_delta_pct = effective_delta * 100.0

                    # Projected new target time based on transfer
                    transferred_time = oldest_target["time"] / (1.0 + effective_delta)
                    transfer_applied = True

                    steps.append(
                        f"Temporal fitness tracking: Detected {distance_label(best_recent_comp['distance'])} "
                        f"improvement from {format_time(best_old_comp['time'])} ({best_old_comp['year']}) to "
                        f"{format_time(best_recent_comp['time'])} ({best_recent_comp['year']}) "
                        f"({delta_v * 100:+.1f}% speed change)."
                    )
                    steps.append(
                        f"Transferred {direction_str} to {distance_label(target_distance)} at "
                        f"{transfer_factor:.0%} efficiency [{p.expr('transfer_improvement')}]: expected "
                        f"target speed changes by {effective_delta * 100:+.1f}%, adjusting {oldest_target['year']} baseline from "
                        f"{format_time(oldest_target['time'])} to {format_time(transferred_time)}."
                    )
                    break

    # Now build effective race set with recency weighting
    half_life_years = fitness_half_life_months / 12.0
    effective_races: list[EffectiveRace] = []
    temporal_sigmas: list[float] = []

    for r in parsed:
        delta_y = max(0.0, target_when - r["when"])
        weight = math.exp(-delta_y / half_life_years)

        # Stale penalty
        if delta_y > max_stale_years:
            weight *= p.stale_weight_factor

        # If this race was the older target race and transfer was applied, update its time
        r_time = r["time"]
        note = ""
        orig_time = None

        if transfer_applied and transferred_time is not None:
            if abs(math.log2(target_distance / r["distance"])) < match_tol and r["year"] < target_year:
                orig_time = r_time
                r_time = transferred_time
                note = f"Updated for {target_year} fitness ({transfer_delta_pct:+.1f}%)"

        effective_races.append(
            EffectiveRace(
                distance=r["distance"],
                time=r_time,
                weight=weight,
                year=r["year"],
                original_time=orig_time,
                note=note,
            )
        )

        # Temporal uncertainty grows with elapsed years
        temporal_sigmas.append(delta_y * annual_fitness_drift_pct)

    # Average or minimum temporal drift among best recent anchors
    if effective_races:
        # Weight-averaged temporal uncertainty
        total_w = sum(e.weight for e in effective_races)
        combined_temporal_sigma = (
            sum(e.weight * s for e, s in zip(effective_races, temporal_sigmas)) / total_w
            if total_w > 0
            else 0.0
        )
    else:
        combined_temporal_sigma = 0.0

    if combined_temporal_sigma > 0.5:
        steps.append(
            f"Temporal drift uncertainty: ±{combined_temporal_sigma:.1f}% based on elapsed time "
            f"from historical race entries."
        )

    return FitnessEvaluation(
        effective_races=effective_races,
        temporal_sigma_pct=round(combined_temporal_sigma, 2),
        steps=steps,
        fitness_delta_pct=round(transfer_delta_pct, 2),
        transferred_target_time=transferred_time,
    )
