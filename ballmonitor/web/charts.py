"""The baseball charts page's list (charts.toml): each chart is one of pyslots' templates
(ballmonitor/charts, copied by scripts/sync-charts.sh) with a name, an intro and starting formulas.
`public()` is what site.js shows (written into data/site.json by the build); `validate()` checks
every template is there and every formula fills one of its slots."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

CHARTS_FILE = Path(__file__).parent / "charts.toml"
TEMPLATES = Path(__file__).resolve().parent.parent / "charts" / "examples"
REQUIRED = ("id", "title", "intro", "template", "group")


def slots(template: str) -> list[str]:
    """A template's slot names (its `# mathzetta: name(...) = ...` lines)."""
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    return re.findall(r"^# mathzetta: (\w+)\(", text, re.M)


def validate(cfg: dict) -> list[str]:
    errs, ids = [], set()
    listed = {c["file"] for c in json.loads((TEMPLATES / "index.json").read_text(encoding="utf-8"))}
    for i, c in enumerate(cfg.get("chart", [])):
        at = c.get("id", f"chart {i + 1}")
        errs += [f"{at}: needs {k}" for k in REQUIRED if not c.get(k)]
        if not re.fullmatch(r"[a-z0-9-]+", c.get("id", "")):
            errs.append(f"{at}: id must be lowercase letters, digits and dashes (it is the address)")
        if c.get("id") in ids:
            errs.append(f"{at}: id used twice")
        ids.add(c.get("id"))
        if c.get("template") not in listed:
            errs.append(f"{at}: template {c.get('template')!r} is not in charts/examples/index.json")
            continue
        unknown = set(c.get("formulas", {})) - set(slots(c["template"]))
        if unknown:
            errs.append(f"{at}: {', '.join(sorted(unknown))} not a slot of {c['template']}")
    return errs


def load(path: Path = CHARTS_FILE) -> dict:
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    problems = validate(cfg)
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    return cfg


def public(cfg: dict | None = None) -> list[dict]:
    if not TEMPLATES.is_dir():
        return []
    cfg = cfg or load()
    return [{k: c[k] for k in ("id", "group", "title", "intro", "template")} | {"formulas": c.get("formulas", {})}
            for c in cfg.get("chart", [])]
