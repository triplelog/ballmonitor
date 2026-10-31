"""Scoring a model (or a variant of it) against historical cases in models/<name>/data/backtest.csv."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

from ballmonitor.core.model import BaseModel

BACKTEST_FILE = Path("data") / "backtest.csv"

# Shown in reports; lower is better unless listed in HIGHER_IS_BETTER or CLOSER_TO_ZERO.
METRIC_NOTES = {
    "abs_error": "mean absolute error",
    "bias": "mean error, + = over-predicts",
    "abs_pct_error": "mean absolute % error",
    "in_interval": "share of actuals inside the interval",
    "brier": "Brier score",
    "log_loss": "log loss",
    "top_pick_correct": "share where the favourite happened",
    "in_50": "share inside the 50% range (target 0.50)",
    "in_80": "share inside the 80% range (target 0.80)",
    "in_95": "share inside the 95% range (target 0.95)",
    "log_score": "log score (−log density of actual)",
    "abs_log_error_annual": "mean |annualised log error|",
    "bias_annual": "mean annualised log error, + = over-predicts",
    "top_3_recall": "recall among top 3 picks",
    "brier_first": "first reliever Brier score",
    "log_loss_appear": "appearance log loss",
}
HIGHER_IS_BETTER = {"in_interval", "top_pick_correct", "top_3_recall"}
CLOSER_TO_ZERO = {"bias", "bias_annual"}
TARGETS = {"in_50": 0.5, "in_80": 0.8, "in_95": 0.95}


@dataclass
class BacktestResult:
    model: str
    variant: str | None
    n: int
    metrics: dict[str, float]
    interval_level: float | None = None
    failures: list[str] = field(default_factory=list)
    groups: dict[str, dict[str, float]] = field(default_factory=dict)  # group -> metrics
    group_n: dict[str, int] = field(default_factory=dict)


def load_rows(path: Path) -> list[dict[str, str]]:
    with open(path, newline="") as fh:
        return [row for row in csv.DictReader(fh) if any(v.strip() for v in row.values() if v)]


def default_data_path(model: BaseModel) -> Path:
    return model.dir / BACKTEST_FILE


def run_backtest(model: BaseModel, rows: list[dict[str, str]]) -> BacktestResult:
    totals: dict[str, list[float]] = {}
    by_group: dict[str, dict[str, list[float]]] = {}
    group_n: dict[str, int] = {}
    failures = []
    level = None
    for i, row in enumerate(rows, start=2):  # row 1 is the CSV header
        try:
            inputs, actual = model.backtest_case(row)
            prediction = model.predict(inputs)
            level = prediction.interval_level
            scores = model.score(prediction, actual)
        except (ValueError, KeyError) as exc:
            failures.append(f"row {i}: {exc}")
            continue
        group = model.backtest_group(row)
        if group is not None:
            group_n[group] = group_n.get(group, 0) + 1
        for metric, value in scores.items():
            if not math.isnan(value):
                totals.setdefault(metric, []).append(value)
                if group is not None:
                    by_group.setdefault(group, {}).setdefault(metric, []).append(value)
    mean = lambda d: {m: sum(v) / len(v) for m, v in d.items() if v}
    groups = {g: mean(d) for g, d in by_group.items()}
    n = len(rows) - len(failures)
    return BacktestResult(model.name, model.config.variant, n, mean(totals), level, failures, groups, group_n)
