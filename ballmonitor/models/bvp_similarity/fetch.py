"""Data fetcher and builder for Batter vs. Pitcher similarity model.

Invoked via `ballmonitor fetch bvp_similarity`. Builds pitcher profiles, batter
profiles, matchup matrices, and backtest holdout sets from cached Statcast parquet data.
"""

from __future__ import annotations

from pathlib import Path

from ballmonitor.models.bvp_similarity.build import build_datasets


def fetch(model_dir: Path, offline: bool = False) -> list[str]:
    """Fetch/build datasets for bvp_similarity."""
    return build_datasets(model_dir)
