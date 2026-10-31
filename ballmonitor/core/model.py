"""Base class every model subclasses."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ballmonitor.core.config import ModelConfig
from ballmonitor.core.prediction import Outcome, Prediction

REPO_ROOT = Path(__file__).resolve().parents[2]


class BaseModel:
    """Subclass this in models/<name>/model.py.

    Required:  predict(inputs) -> Prediction   (build the result with self.prediction(...))
    Optional:  backtest_case(row) -> (inputs, actual)   to enable `ballmonitor backtest`
               score(prediction, actual) -> dict[str, float]   to customise backtest metrics
               backtest_group(row) -> str | None   to report metrics per group (e.g. per horizon)

    Rules: read every tunable number from self.params (never hard-code it) and
    append a human-readable line to `steps` for each meaningful calculation.
    """

    def __init__(self, config: ModelConfig, model_dir: Path):
        self.config = config
        self.params = config.params
        self.dir = model_dir

    @property
    def name(self) -> str:
        return self.config.name

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        raise NotImplementedError(f"model '{self.name}' has no predict() yet")

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], Any]:
        raise NotImplementedError(f"model '{self.name}' does not implement backtest_case()")

    def backtest_group(self, row: dict[str, str]) -> str | None:
        return None

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        """Per-case metrics; the backtest reports their mean.

        Numeric actual -> scored against the primary outcome's estimate.
        String actual  -> treated as the label of the outcome that happened, scored
                          against the probabilities of all outcomes.
        """
        if isinstance(actual, str):
            probs = {o.label: o.probability or 0.0 for o in prediction.outcomes}
            if actual not in probs:
                raise ValueError(f"actual outcome {actual!r} is not one of the predicted outcomes")
            top = max(probs, key=probs.get)
            return {
                "brier": sum((p - (label == actual)) ** 2 for label, p in probs.items()),
                "log_loss": -math.log(max(probs[actual], 1e-12)),
                "top_pick_correct": float(top == actual),
            }
        primary = prediction.primary
        error = primary.estimate - actual
        metrics = {
            "abs_error": abs(error),
            "bias": error,
            "abs_pct_error": abs(error) / abs(actual) * 100 if actual else math.nan,
        }
        if primary.interval is not None:
            lo, hi = primary.interval
            metrics["in_interval"] = float(lo <= actual <= hi)
        return metrics

    def prediction(
        self,
        *,
        inputs: dict[str, Any],
        outcomes: list[Outcome],
        steps: list[str] | None = None,
        interval_level: float | None = None,
        extras: dict[str, Any] | None = None,
        tables: list | None = None,
    ) -> Prediction:
        """Wrap results in the standard Prediction, filling in all metadata from config."""
        cfg = self.config
        try:
            doc = str((self.dir / "MODEL.md").relative_to(REPO_ROOT))
        except ValueError:
            doc = str(self.dir / "MODEL.md")
        return Prediction(
            model=cfg.name,
            version=cfg.version,
            title=cfg.title,
            question=cfg.question,
            inputs={k: str(v) for k, v in inputs.items()},
            outcomes=outcomes,
            steps=list(steps or []),
            params=list(self.params.specs.values()),
            formulas=list(self.params.formulas.values()),
            assumptions=cfg.assumptions,
            interval_level=interval_level,
            tables=list(tables or []),
            status=cfg.status,
            variant=cfg.variant,
            doc=doc,
            extras=dict(extras or {}),
        )
