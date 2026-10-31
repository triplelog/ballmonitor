"""Template Model. See MODEL.md."""

from __future__ import annotations

from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction


class TemplateModel(BaseModel):
    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        score = float(inputs["score"])
        prob = p.formula("probability", score=score)
        steps = [f"P(event) = {prob:.3f} [{p.expr('probability')}] with score = {score:g}."]
        return self.prediction(
            inputs={"score": f"{score:g}"},
            outcomes=[Outcome("Event happens", probability=prob), Outcome("Event does not happen", probability=1 - prob)],
            steps=steps,
        )

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], Any]:
        # data/backtest.csv columns: score,happened   (happened = yes/no)
        happened = row["happened"].strip().lower() in ("1", "yes", "true")
        return {"score": float(row["score"])}, "Event happens" if happened else "Event does not happen"
