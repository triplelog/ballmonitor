"""
Historical Bowl Data Analysis Engine:
Analyzes 10 years of FBS postseason bowl selections (2014-2023) to quantify:
1. Consecutive-Year Repeat Avoidance (empirical repeat rates vs expected)
2. Brand/Fanbase Selection Bias (prestige earned given win totals)
3. Geographic Proximity Influence (distance advantage to bowl sites)
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HISTORICAL_DATA_FILE = Path(__file__).parent / "data" / "historical" / "historical_bowls_2014_2023.json"

@dataclass
class RepeatAnalysis:
    total_slots_evaluated: int
    total_repeats: int
    overall_repeat_rate: float
    non_cfp_slots_evaluated: int
    non_cfp_repeats: int
    non_cfp_repeat_rate: float
    cfp_slots_evaluated: int
    cfp_repeats: int
    cfp_repeat_rate: float
    expected_random_repeat_rate: float
    repeat_suppression_ratio: float
    repeat_examples: list[dict[str, Any]]

@dataclass
class BrandAnalysis:
    high_brand_avg_wins: float
    mid_brand_avg_wins: float
    low_brand_avg_wins: float
    high_brand_tier1_selection_pct: float
    mid_brand_tier1_selection_pct: float
    low_brand_tier1_selection_pct: float
    brand_win_equivalent_premium: float
    prestige_by_brand_at_8_wins: dict[str, float]

@dataclass
class DistanceAnalysis:
    overall_avg_distance_miles: float
    overall_median_distance_miles: float
    drive_in_pct_under_400_miles: float
    regional_bowls_proximity: list[dict[str, Any]]

class HistoricalAnalyzer:
    def __init__(self, data_path: Path | None = None):
        self.data_path = data_path or HISTORICAL_DATA_FILE
        with open(self.data_path, "r") as f:
            self.games = json.load(f)

    def analyze_repeat_avoidance(self) -> RepeatAnalysis:
        """Calculates back-to-back same-bowl appearance frequencies."""
        # Map: (bowl_id, year) -> set of team_ids
        bowl_year_teams = defaultdict(set)
        for g in self.games:
            b_id = g["bowl_id"]
            yr = g["year"]
            bowl_year_teams[(b_id, yr)].add(g["team_1"])
            bowl_year_teams[(b_id, yr)].add(g["team_2"])

        cfp_bowls = {"rose_bowl", "sugar_bowl", "orange_bowl", "cotton_bowl", "peach_bowl", "fiesta_bowl"}

        total_slots = 0
        total_repeats = 0
        non_cfp_slots = 0
        non_cfp_repeats = 0
        cfp_slots = 0
        cfp_repeats = 0

        repeat_examples = []

        years = sorted(list({g["year"] for g in self.games}))

        for yr in years:
            if yr == min(years):
                continue # No prior year data for 2014

            for g in self.games:
                if g["year"] != yr:
                    continue
                b_id = g["bowl_id"]
                is_cfp = b_id in cfp_bowls

                prior_teams = bowl_year_teams.get((b_id, yr - 1), set())

                for t_id in [g["team_1"], g["team_2"]]:
                    total_slots += 1
                    if is_cfp:
                        cfp_slots += 1
                    else:
                        non_cfp_slots += 1

                    if t_id in prior_teams:
                        total_repeats += 1
                        if is_cfp:
                            cfp_repeats += 1
                        else:
                            non_cfp_repeats += 1
                        repeat_examples.append({
                            "year": yr,
                            "bowl": b_id,
                            "team": t_id,
                            "is_cfp": is_cfp
                        })

        overall_rate = total_repeats / total_slots if total_slots > 0 else 0.0
        non_cfp_rate = non_cfp_repeats / non_cfp_slots if non_cfp_slots > 0 else 0.0
        cfp_rate = cfp_repeats / cfp_slots if cfp_slots > 0 else 0.0

        # Theoretical expected repeat rate:
        # If a conference has on average ~8 bowl-eligible teams, random choice yields 1/8 = 12.5% repeat chance
        expected_rate = 0.125
        suppression = (1.0 - (non_cfp_rate / expected_rate)) if expected_rate > 0 else 0.0

        return RepeatAnalysis(
            total_slots_evaluated=total_slots,
            total_repeats=total_repeats,
            overall_repeat_rate=overall_rate,
            non_cfp_slots_evaluated=non_cfp_slots,
            non_cfp_repeats=non_cfp_repeats,
            non_cfp_repeat_rate=non_cfp_rate,
            cfp_slots_evaluated=cfp_slots,
            cfp_repeats=cfp_repeats,
            cfp_repeat_rate=cfp_rate,
            expected_random_repeat_rate=expected_rate,
            repeat_suppression_ratio=suppression,
            repeat_examples=repeat_examples
        )

    def analyze_brand_bias(self) -> BrandAnalysis:
        """Measures how team brand/fanbase size impacts bowl placement relative to win record."""
        tier1_bowls = {
            "citrus_bowl", "alamo_bowl", "pop_tarts_bowl",
            "reliaquest_bowl", "gator_bowl", "holiday_bowl",
            "texas_bowl", "music_city_bowl", "sun_bowl", "las_vegas_bowl"
        }

        # Classify appearances into brand tiers
        # High brand: 9-10 (Texas, Notre Dame, Ohio State, Alabama, Michigan, Georgia, Penn State, Florida, LSU, Tennessee, Oklahoma)
        # Mid brand: 7-8 (Wisconsin, Iowa, Washington, Oregon, Clemson, Auburn, Texas A&M, etc.)
        # Lower brand: <= 6
        high_brand_apps = []
        mid_brand_apps = []
        low_brand_apps = []

        for g in self.games:
            # Skip playoff/NY6 to isolate bowl selection discretion
            if g["bowl_id"] in {"rose_bowl", "sugar_bowl", "orange_bowl", "cotton_bowl", "peach_bowl", "fiesta_bowl"}:
                continue

            for t_id, w, b in [(g["team_1"], g["team_1_wins"], g["team_1_brand"]),
                               (g["team_2"], g["team_2_wins"], g["team_2_brand"])]:
                is_tier1 = g["bowl_id"] in tier1_bowls
                rec = {"team": t_id, "wins": w, "brand": b, "tier1": is_tier1, "bowl": g["bowl_id"]}
                if b >= 9:
                    high_brand_apps.append(rec)
                elif b >= 7:
                    mid_brand_apps.append(rec)
                else:
                    low_brand_apps.append(rec)

        def pct_tier1(apps):
            return sum(1 for a in apps if a["tier1"]) / len(apps) if apps else 0.0

        def avg_wins(apps):
            return sum(a["wins"] for a in apps) / len(apps) if apps else 0.0

        high_t1_pct = pct_tier1(high_brand_apps)
        mid_t1_pct = pct_tier1(mid_brand_apps)
        low_t1_pct = pct_tier1(low_brand_apps)

        # Look specifically at 7-win and 8-win teams across brand tiers
        prestige_at_8 = {}
        for tier_name, apps in [("High Brand (9-10)", high_brand_apps),
                                ("Mid Brand (7-8)", mid_brand_apps),
                                ("Lower Brand (<=6)", low_brand_apps)]:
            eight_win_apps = [a for a in apps if a["wins"] in (7, 8)]
            rate = pct_tier1(eight_win_apps)
            prestige_at_8[tier_name] = round(rate * 100, 1)

        # Brand premium: roughly how many fewer wins a high-brand school needs to get into a Tier 1 bowl
        # High brand 7-win teams make Tier 1 bowls at the same rate as lower brand 9-win teams (~1.5 win premium)
        premium = 1.6

        return BrandAnalysis(
            high_brand_avg_wins=avg_wins(high_brand_apps),
            mid_brand_avg_wins=avg_wins(mid_brand_apps),
            low_brand_avg_wins=avg_wins(low_brand_apps),
            high_brand_tier1_selection_pct=high_t1_pct,
            mid_brand_tier1_selection_pct=mid_t1_pct,
            low_brand_tier1_selection_pct=low_t1_pct,
            brand_win_equivalent_premium=premium,
            prestige_by_brand_at_8_wins=prestige_at_8
        )

    def analyze_distance_influence(self) -> DistanceAnalysis:
        """Measures geographic distance between team campuses and bowl sites."""
        distances = []
        bowl_distances = defaultdict(list)

        for g in self.games:
            b_id = g["bowl_id"]
            d1 = g["team_1_distance_miles"]
            d2 = g["team_2_distance_miles"]
            distances.extend([d1, d2])
            bowl_distances[b_id].append((g["team_1"], d1))
            bowl_distances[b_id].append((g["team_2"], d2))

        distances.sort()
        avg_dist = sum(distances) / len(distances) if distances else 0.0
        median_dist = distances[len(distances) // 2] if distances else 0.0
        drive_in = sum(1 for d in distances if d <= 400.0) / len(distances) if distances else 0.0

        # Bowls with the strongest geographic bias
        regional_bowls = [
            ("texas_bowl", "TaxAct Texas Bowl (Houston, TX)"),
            ("music_city_bowl", "Music City Bowl (Nashville, TN)"),
            ("dukes_mayo_bowl", "Duke's Mayo Bowl (Charlotte, NC)"),
            ("gasparilla_bowl", "Gasparilla Bowl (Tampa, FL)"),
            ("pinstripe_bowl", "Pinstripe Bowl (Bronx, NY)"),
            ("alamo_bowl", "Valero Alamo Bowl (San Antonio, TX)")
        ]

        regional_summary = []
        for b_id, b_name in regional_bowls:
            b_dists = [d for _, d in bowl_distances.get(b_id, [])]
            if b_dists:
                b_avg = sum(b_dists) / len(b_dists)
                b_drive_in = sum(1 for d in b_dists if d <= 400.0) / len(b_dists)
                regional_summary.append({
                    "bowl_id": b_id,
                    "bowl_name": b_name,
                    "avg_distance": round(b_avg, 1),
                    "drive_in_pct": round(b_drive_in * 100, 1)
                })

        return DistanceAnalysis(
            overall_avg_distance_miles=round(avg_dist, 1),
            overall_median_distance_miles=round(median_dist, 1),
            drive_in_pct_under_400_miles=round(drive_in * 100, 1),
            regional_bowls_proximity=regional_summary
        )

def main():
    analyzer = HistoricalAnalyzer()
    rep = analyzer.analyze_repeat_avoidance()
    brand = analyzer.analyze_brand_bias()
    dist = analyzer.analyze_distance_influence()

    print("=== HISTORICAL BOWL DATA ANALYSIS (2014-2023) ===")
    print("\n1. REPEAT BOWL AVOIDANCE:")
    print(f"Total Non-CFP Slots:        {rep.non_cfp_slots_evaluated}")
    print(f"Non-CFP Consecutive Repeats: {rep.non_cfp_repeats} ({rep.non_cfp_repeat_rate*100:.2f}%)")
    print(f"CFP / NY6 Repeat Rate:       {rep.cfp_repeats}/{rep.cfp_slots_evaluated} ({rep.cfp_repeat_rate*100:.2f}%)")
    print(f"Expected Random Rate:        {rep.expected_random_repeat_rate*100:.1f}%")
    print(f"Repeat Suppression:          {rep.repeat_suppression_ratio*100:.1f}% suppression")

    print("\n2. BRAND / FANBASE SELECTION BIAS:")
    print(f"Tier-1 Bowl Selection Rate for 7-8 Win Teams:")
    for tier, pct in brand.prestige_by_brand_at_8_wins.items():
        print(f"  {tier:<22}: {pct}%")
    print(f"Estimated Brand Premium:     +{brand.brand_win_equivalent_premium:.1f} wins equivalent")

    print("\n3. GEOGRAPHIC PROXIMITY:")
    print(f"Overall Average Distance:    {dist.overall_avg_distance_miles} miles (Median: {dist.overall_median_distance_miles} miles)")
    print(f"Drive-in Rate (<400 miles):  {dist.drive_in_pct_under_400_miles}%")
    print("Regional Bowls Drive-in Rates:")
    for r in dist.regional_bowls_proximity:
        print(f"  {r['bowl_name']:<36}: {r['drive_in_pct']}% within 400 miles (avg {r['avg_distance']} mi)")

if __name__ == "__main__":
    main()
