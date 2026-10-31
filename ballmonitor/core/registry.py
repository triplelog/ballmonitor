"""Discovering, loading and scaffolding models under ballmonitor/models/."""

from __future__ import annotations

import datetime
import importlib
import inspect
import re
import shutil
from pathlib import Path
from typing import Any

from ballmonitor.core.config import ModelConfig, load_config, read_toml
from ballmonitor.core.model import BaseModel

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
TEMPLATE = "_template"


class ModelNotReady(RuntimeError):
    pass


def model_names() -> list[str]:
    return sorted(
        p.name
        for p in MODELS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "config.toml").exists()
    )


def model_dir(name: str) -> Path:
    path = MODELS_DIR / name
    if name.startswith("_") or not (path / "config.toml").exists():
        raise KeyError(f"no model named '{name}'. Available: {', '.join(model_names())}")
    return path


def config_for(name: str, variant: str | None = None, overrides: dict[str, Any] | None = None) -> ModelConfig:
    return load_config(model_dir(name), variant, overrides)


def load_model(name: str, variant: str | None = None, overrides: dict[str, Any] | None = None) -> BaseModel:
    directory = model_dir(name)
    config = load_config(directory, variant, overrides)
    if config.status == "stub":
        raise ModelNotReady(
            f"model '{name}' is a stub (meta.status = \"stub\"). See {directory / 'MODEL.md'} for the plan."
        )
    module = importlib.import_module(f"ballmonitor.models.{name}.model")
    classes = [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, BaseModel) and obj is not BaseModel and obj.__module__ == module.__name__
    ]
    if len(classes) != 1:
        raise RuntimeError(f"{module.__name__} must define exactly one BaseModel subclass, found {len(classes)}")
    return classes[0](config, directory)


def fetch_due(name: str, today: datetime.date | None = None) -> tuple[bool, str]:
    """Should `update-and-build` (the scheduled CI build) run this model's fetch.py today?

    Only models whose config.toml has `[fetch] auto = true` are fetched automatically, and
    only inside `season = ["MM-DD", "MM-DD"]` (inclusive; may wrap the new year). Everything
    else is fetched by hand with `ballmonitor fetch <name>`. Returns (due, reason)."""
    directory = model_dir(name)
    if not (directory / "fetch.py").exists():
        return False, "no fetch.py"
    policy = config_for(name).extra.get("fetch", {})
    if not policy.get("auto", False):
        return False, "fetched by hand (no [fetch] auto = true)"
    season = policy.get("season")
    if not season:
        return True, "auto, all year"
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    start, end = (tuple(int(x) for x in s.split("-")) for s in season)
    now = (today.month, today.day)
    inside = start <= now <= end if start <= end else (now >= start or now <= end)
    window = f"{season[0]} to {season[1]}"
    return (True, f"auto, in season ({window})") if inside else (False, f"out of season ({window})")


def example_names(name: str) -> list[str]:
    return sorted(p.stem for p in (model_dir(name) / "examples").glob("*.toml"))


def load_example(name: str, example: str) -> dict[str, Any]:
    path = model_dir(name) / "examples" / f"{example}.toml"
    if not path.exists():
        raise KeyError(f"no example '{example}' for model '{name}'. Available: {example_names(name)}")
    return read_toml(path)


def variant_names(name: str) -> list[str]:
    return sorted(p.stem for p in (model_dir(name) / "variants").glob("*.toml"))


def scaffold(name: str, title: str | None = None) -> Path:
    """Copy the template to models/<name>/ and rename its placeholders."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("model names must be lowercase snake_case, e.g. 'nfl_win_totals'")
    target = MODELS_DIR / name
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    shutil.copytree(MODELS_DIR / TEMPLATE, target, ignore=shutil.ignore_patterns("__pycache__"))
    class_name = "".join(part.title() for part in name.split("_")) + "Model"
    title = title or name.replace("_", " ").title()
    for path in target.rglob("*"):
        if path.is_file() and path.suffix in (".py", ".toml", ".md"):
            text = path.read_text()
            text = text.replace("TemplateModel", class_name).replace("Template Model", title)
            text = text.replace(TEMPLATE, name)
            path.write_text(text)
    (target / "variants").mkdir(exist_ok=True)
    (target / "data").mkdir(exist_ok=True)
    return target
