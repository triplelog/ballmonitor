"""Build pipeline for Batter vs. Pitcher similarity model.

Processes raw Statcast parquet files across multiple seasons, extracts pitcher
and batter feature profiles, builds the historical matchup matrix, and generates
an out-of-sample backtest dataset.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ballmonitor.models.bvp_similarity import features as F

ALL_SEASONS = [2021, 2022, 2023, 2024, 2025, 2026]
DEFAULT_BACKTEST_SEASON = 2026
SAMPLE_BACKTEST_CASES = 2000
BACKTEST_SEED = 42
BACKTEST_COLS = [
    "pitcher", "pitcher_name", "batter", "batter_name", "pa",
    "observed_xwoba", "observed_k_pct", "observed_bb_pct",
    "k", "bb", "h", "hr", "delta_re",
]


def season_cases(test_df: pd.DataFrame, pitchers_df: pd.DataFrame, batters_df: pd.DataFrame) -> pd.DataFrame:
    """Every pitcher-batter pair of a later season whose two players both have training profiles."""
    test_pa = test_df[test_df["is_pa"] == 1]
    test_pa = test_pa[test_pa["pitcher"].isin(set(pitchers_df.index)) & test_pa["batter"].isin(set(batters_df.index))]
    cases = test_pa.groupby(["pitcher", "batter"]).agg(
        pa=("events", "count"),
        k=("is_k", "sum"),
        bb=("is_bb", "sum"),
        h=("is_h", "sum"),
        hr=("is_hr", "sum"),
        xwoba_sum=("xwoba_val", "sum"),
        delta_re=("delta_run_exp", "sum"),
    ).reset_index()
    cases["pitcher_name"] = pitchers_df.loc[cases["pitcher"], "name"].to_numpy()
    cases["batter_name"] = batters_df.loc[cases["batter"], "name"].to_numpy()
    cases["observed_xwoba"] = (cases["xwoba_sum"] / cases["pa"]).round(4)
    cases["observed_k_pct"] = (cases["k"] / cases["pa"]).round(4)
    cases["observed_bb_pct"] = (cases["bb"] / cases["pa"]).round(4)
    cases["delta_re"] = cases["delta_re"].round(3)
    return cases


def build_datasets(
    model_dir: Path,
    seasons: list[int] | None = None,
    backtest_season: int = DEFAULT_BACKTEST_SEASON,
    min_pitcher_pitches: int = 150,
    min_batter_pa: int = 40,
    n_backtest: int = SAMPLE_BACKTEST_CASES,
) -> list[str]:
    """Execute the full data build and save artifacts to model data directory."""
    if seasons is None:
        seasons = ALL_SEASONS

    data_dir = model_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log = []

    pitches_dir = F.find_pitches_dir(model_dir)
    people = F.load_people(model_dir)
    log.append(f"Using pitch files from: {pitches_dir}")

    # 1. Load historical training data (all seasons up to backtest_season)
    train_seasons = [s for s in seasons if s < backtest_season]
    if not train_seasons:
        train_seasons = seasons

    log.append(f"Loading training data for seasons: {train_seasons}")
    train_df = F.load_pitches(pitches_dir, seasons=train_seasons)
    log.append(f"Loaded {len(train_df):,} training pitches.")

    # 2. Extract feature tables
    pitchers_df = F.extract_pitcher_features(train_df, people=people, min_pitches=min_pitcher_pitches)
    batters_df = F.extract_batter_features(train_df, people=people, min_pa=min_batter_pa)
    matchups_df = F.extract_matchups(train_df)

    log.append(f"Extracted {len(pitchers_df)} pitchers (>= {min_pitcher_pitches} pitches).")
    log.append(f"Extracted {len(batters_df)} batters (>= {min_batter_pa} PAs).")
    log.append(f"Extracted {len(matchups_df):,} unique historical BvP pairs.")

    # Save training tables
    pitchers_df.to_parquet(data_dir / "pitchers.parquet")
    pitchers_df.reset_index().to_csv(data_dir / "pitchers.csv", index=False)

    batters_df.to_parquet(data_dir / "batters.parquet")
    batters_df.reset_index().to_csv(data_dir / "batters.csv", index=False)

    matchups_df.to_parquet(data_dir / "matchups.parquet")

    # 3. Build holdout backtest dataset from backtest_season (strict out-of-sample)
    if backtest_season in seasons:
        log.append(f"Building out-of-sample backtest cases from season {backtest_season}...")
        test_df = F.load_pitches(pitches_dir, seasons=[backtest_season])
        cases = season_cases(test_df, pitchers_df, batters_df)
        # a uniform random sample of pairs, so PA-weighted metrics estimate the whole season
        if len(cases) > n_backtest:
            cases = cases.sample(n=n_backtest, random_state=BACKTEST_SEED)
        cases = cases.sort_values(["pa", "pitcher", "batter"], ascending=[False, True, True])
        cases[BACKTEST_COLS].to_csv(data_dir / "backtest.csv", index=False)
        log.append(f"Saved {len(cases)} backtest cases (random sample of pairs, seed "
                   f"{BACKTEST_SEED}) to {data_dir / 'backtest.csv'}")

    # 4. Save metadata
    meta = {
        "train_seasons": train_seasons,
        "backtest_season": backtest_season,
        "n_pitchers": len(pitchers_df),
        "n_batters": len(batters_df),
        "n_matchup_pairs": len(matchups_df),
        "pitcher_features": F.PITCHER_SIM_COLS,
        "batter_features": F.BATTER_SIM_COLS,
        "league_defaults": F.LEAGUE_DEFAULTS,
    }
    with open(data_dir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    log.append("Data build completed successfully.")
    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build BvP similarity datasets.")
    parser.add_argument("--model-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--backtest-season", type=int, default=DEFAULT_BACKTEST_SEASON)
    args = parser.parse_args()

    logs = build_datasets(args.model_dir, backtest_season=args.backtest_season)
    for line in logs:
        print(line)
