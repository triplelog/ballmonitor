"""Loading a model's config.toml and layering variants and command-line overrides on top.

Resolution order (later wins):
    1. models/<name>/config.toml        the documented defaults
    2. a variant file                   models/<name>/variants/<variant>.toml, or any path
    3. overrides                        e.g. --set fit_weight=0.8 --set formulas.predict="..."
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ballmonitor.core.params import ConfigError, FormulaSpec, Params, ParamSpec

STATUSES = ("stub", "draft", "calibrated")


@dataclass
class ModelConfig:
    name: str
    title: str
    version: str
    status: str
    question: str
    description: str
    assumptions: list[str]
    params: Params
    variant: str | None = None
    variant_description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)  # any other top-level tables, for model use


def read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None


def parse_value(raw: str) -> Any:
    """Parse a command-line value using TOML syntax; fall back to a plain string.

    `0.8` -> 0.8, `true` -> True, `[1, 2]` -> [1, 2], `"x"` -> "x", `nearest` -> "nearest".
    """
    try:
        return tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        return raw


def parse_assignments(items: list[str]) -> dict[str, Any]:
    result = {}
    for item in items:
        key, sep, raw = item.partition("=")
        if not sep:
            raise ConfigError(f"expected KEY=VALUE, got {item!r}")
        result[key.strip()] = parse_value(raw.strip())
    return result


def resolve_variant(model_dir: Path, variant: str | Path) -> Path:
    path = Path(variant)
    if path.suffix == ".toml" and path.exists():
        return path
    candidate = model_dir / "variants" / f"{variant}.toml"
    if candidate.exists():
        return candidate
    available = sorted(p.stem for p in (model_dir / "variants").glob("*.toml"))
    raise ConfigError(f"no variant '{variant}' for model '{model_dir.name}'. Available: {available or 'none'}")


def load_config(
    model_dir: Path,
    variant: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> ModelConfig:
    base = read_toml(model_dir / "config.toml")
    meta = base.get("meta", {})

    params = {name: _param_spec(name, raw) for name, raw in base.get("params", {}).items()}
    formulas = {name: _formula_spec(name, raw) for name, raw in base.get("formulas", {}).items()}

    variant_description = ""
    if variant is not None:
        path = resolve_variant(model_dir, variant)
        layer = read_toml(path)
        variant_description = layer.get("description", "")
        for name, value in layer.get("params", {}).items():
            _set_param(params, name, value, origin=str(path))
        for name, value in layer.get("formulas", {}).items():
            _set_formula(formulas, name, value, origin=str(path))

    for key, value in (overrides or {}).items():
        if key.startswith("formulas."):
            _set_formula(formulas, key.removeprefix("formulas."), value, origin="--set")
        else:
            _set_param(params, key.removeprefix("params."), value, origin="--set")

    resolved = Params(params, formulas)
    resolved.validate()

    status = meta.get("status", "draft")
    if status not in STATUSES:
        raise ConfigError(f"{model_dir.name}: meta.status must be one of {STATUSES}, got {status!r}")

    return ModelConfig(
        name=model_dir.name,
        title=meta.get("title", model_dir.name),
        version=meta.get("version", "0.0.0"),
        status=status,
        question=meta.get("question", ""),
        description=meta.get("description", ""),
        assumptions=list(meta.get("assumptions", [])),
        params=resolved,
        variant=Path(variant).stem if variant is not None else None,
        variant_description=variant_description,
        extra={k: v for k, v in base.items() if k not in ("meta", "params", "formulas")},
    )


def _param_spec(name: str, raw: Any) -> ParamSpec:
    if not isinstance(raw, dict):
        raw = {"value": raw}
    if "value" not in raw:
        raise ConfigError(f"param '{name}' is missing 'value'")
    rng = raw.get("range")
    return ParamSpec(
        name=name,
        value=raw["value"],
        description=raw.get("description", ""),
        unit=raw.get("unit", ""),
        source=raw.get("source", ""),
        range=tuple(rng) if rng is not None else None,
        choices=raw.get("choices"),
        default=raw["value"],
    )


def _formula_spec(name: str, raw: Any) -> FormulaSpec:
    if isinstance(raw, str):
        raw = {"expr": raw}
    if "expr" not in raw:
        raise ConfigError(f"formula '{name}' is missing 'expr'")
    return FormulaSpec(
        name=name,
        expr=raw["expr"],
        description=raw.get("description", ""),
        variables=list(raw.get("variables", [])),
        default=raw["expr"],
    )


def _set_param(params: dict[str, ParamSpec], name: str, value: Any, origin: str) -> None:
    if name not in params:
        raise ConfigError(f"{origin}: unknown parameter '{name}'. Known: {', '.join(sorted(params))}")
    spec = params[name]
    default = spec.default
    if isinstance(default, float) and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if default is not None and type(value) is not type(default):
        raise ConfigError(
            f"{origin}: parameter '{name}' expects {type(default).__name__}, got {value!r}"
        )
    spec.value = value


def _set_formula(formulas: dict[str, FormulaSpec], name: str, value: Any, origin: str) -> None:
    if name not in formulas:
        raise ConfigError(f"{origin}: unknown formula '{name}'. Known: {', '.join(sorted(formulas))}")
    if not isinstance(value, str):
        raise ConfigError(f"{origin}: formula '{name}' must be a string expression")
    formulas[name].expr = value
