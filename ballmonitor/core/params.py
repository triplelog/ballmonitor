"""Parameter and formula specs, as declared in a model's config.toml."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ballmonitor.core import formula as formula_engine


class ConfigError(ValueError):
    pass


@dataclass
class ParamSpec:
    name: str
    value: Any
    description: str = ""
    unit: str = ""
    source: str = ""
    range: tuple[float, float] | None = None
    choices: list[Any] | None = None
    default: Any = None  # value in the model's base config.toml, before variants / --set

    @property
    def overridden(self) -> bool:
        return self.value != self.default

    def validate(self) -> None:
        is_number = isinstance(self.value, (int, float)) and not isinstance(self.value, bool)
        if self.range is not None and is_number:
            lo, hi = self.range
            if not lo <= self.value <= hi:
                raise ConfigError(f"param '{self.name}' = {self.value} is outside its range [{lo}, {hi}]")
        if self.choices is not None and self.value not in self.choices:
            raise ConfigError(f"param '{self.name}' = {self.value!r} must be one of {self.choices}")


@dataclass
class FormulaSpec:
    name: str
    expr: str
    description: str = ""
    variables: list[str] = field(default_factory=list)  # names the model supplies at call time
    default: str = ""

    @property
    def overridden(self) -> bool:
        return self.expr != self.default


class Params:
    """Resolved parameters for one model run.

    Read a parameter with attribute access (`params.fit_weight`) and evaluate a
    config formula with `params.formula("predict", t=..., d=...)`. Every numeric
    parameter is automatically available inside every formula by name.
    """

    def __init__(self, specs: dict[str, ParamSpec], formulas: dict[str, FormulaSpec]):
        self._specs = specs
        self._formulas = formulas

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._specs[name].value
        except KeyError:
            raise AttributeError(
                f"unknown parameter '{name}' (declare it under [params] in config.toml)"
            ) from None

    def __getitem__(self, name: str) -> Any:
        return getattr(self, name)

    @property
    def specs(self) -> dict[str, ParamSpec]:
        return self._specs

    @property
    def formulas(self) -> dict[str, FormulaSpec]:
        return self._formulas

    def numeric_values(self) -> dict[str, float]:
        return {
            n: s.value
            for n, s in self._specs.items()
            if isinstance(s.value, (int, float)) and not isinstance(s.value, bool)
        }

    def formula(self, name: str, **variables: float) -> float:
        try:
            spec = self._formulas[name]
        except KeyError:
            raise ConfigError(f"unknown formula '{name}' (declare it under [formulas] in config.toml)") from None
        return formula_engine.evaluate(spec.expr, {**self.numeric_values(), **variables})

    def expr(self, name: str) -> str:
        return self._formulas[name].expr

    def validate(self) -> None:
        for spec in self._specs.values():
            spec.validate()
        allowed = set(self.numeric_values())
        for spec in self._formulas.values():
            try:
                formula_engine.check(spec.expr, allowed | set(spec.variables))
            except formula_engine.FormulaError as exc:
                raise ConfigError(f"formula '{spec.name}': {exc}") from None
