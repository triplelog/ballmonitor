"""The single output type every model returns. Renderers depend only on this."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ballmonitor.core.params import FormulaSpec, ParamSpec

# How an Outcome's numbers are displayed. Add new formats in render.format_value.
FORMATS = ("number", "int", "pct", "time", "currency", "points")


@dataclass
class Outcome:
    """One row of a prediction's result table.

    Use `estimate` (+ optional `interval`) for numeric predictions and
    `probability` for events. Both may be set (e.g. a team's projected wins
    and its chance of bowl eligibility belong in separate rows, but a seed
    line could carry both). `group` splits the table into sub-sections.
    """

    label: str
    estimate: float | None = None
    interval: tuple[float, float] | None = None
    probability: float | None = None
    fmt: str = "number"
    group: str = ""
    note: str = ""


@dataclass
class Table:
    """A small grid shown after the result table (e.g. a candidate x method matrix).

    Cells are display strings; the first column is the row label. Text output splits a wide
    table into blocks that each repeat the first column, so it stays within 78 columns.
    """

    title: str
    columns: list[str]
    rows: list[list[str]]
    note: str = ""


@dataclass
class Prediction:
    model: str
    version: str
    title: str
    question: str
    inputs: dict[str, str]  # display strings, in display order
    outcomes: list[Outcome]
    steps: list[str] = field(default_factory=list)  # "show your work", in order
    params: list[ParamSpec] = field(default_factory=list)
    formulas: list[FormulaSpec] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    interval_level: float | None = None
    tables: list[Table] = field(default_factory=list)
    status: str = "draft"
    variant: str | None = None
    doc: str = ""
    extras: dict[str, Any] = field(default_factory=dict)  # intermediates; keys starting "_" are internal (not serialised)

    @property
    def primary(self) -> Outcome:
        return self.outcomes[0]

    def outcome(self, label: str) -> Outcome:
        for o in self.outcomes:
            if o.label == label:
                return o
        raise KeyError(label)

    def to_dict(self) -> dict[str, Any]:
        internal = {k: v for k, v in self.extras.items() if k.startswith("_")}
        self.extras = {k: v for k, v in self.extras.items() if not k.startswith("_")}
        try:
            data = asdict(self)
        finally:
            self.extras.update(internal)
        data["params"] = {
            p.name: {"value": p.value, "default": p.default, "unit": p.unit, "overridden": p.overridden}
            for p in self.params
        }
        data["formulas"] = {
            f.name: {"expr": f.expr, "default": f.default, "overridden": f.overridden}
            for f in self.formulas
        }
        return data
