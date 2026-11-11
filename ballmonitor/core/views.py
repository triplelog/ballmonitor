"""Pre-generated pages for the public site (models/<name>/site.py -> data/views/<name>.json).

A model's optional `site.py` defines `page(model) -> dict`, built with the helpers below.
The site only displays these numbers: it never runs a model in the browser. Values stay raw
(seconds, 0-1 probabilities) with a `fmt`; the page formats them. Keep every label in plain
words for a fan, not an analyst.

    page(title=..., summary=..., sport=..., updated=..., views=[
        table("teams", "Every FBS team", [col("team", "Team"), col("p_cfp", "Playoff", "pct", bar=True)],
              rows, search=True, page_size=25),
        bar("title_odds", "Title chances", [{"label": "Georgia", "value": 0.21}], fmt="pct"),
        line("curve", "Marathon vs 5K", [series("Men", [(900, 10500), ...])], x_label=..., x_fmt="time"),
        picker("by_race", "Award times by race", "Race", [option("Cherry Blossom", [table(...)]), ...]),
    ])
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

FORMATS = ("text", "int", "number", "pct", "time", "signed")
KINDS = ("table", "bar", "line", "picker", "app")
APPS_DIR = Path(__file__).resolve().parent.parent / "web" / "static" / "apps"
SPORTS = ("College football", "Baseball", "College baseball & softball", "Running", "Polls & awards", "More sports")
# Shioh cell colour per sport (site.html's .ss-p1-5): the pages, their pre-written HTML and site.js
# all use this map (site.js reads it from data/site.json). The data tables add their own sports.
SPORT_CELL = {"College football": "ss-p1", "Baseball": "ss-p4", "College baseball & softball": "ss-p2",
              "Running": "ss-p3", "Polls & awards": "ss-p5", "More sports": "ss-p1", "Pro football": "ss-p1",
              "Basketball": "ss-p3"}


def cell_class(sport: str) -> str:
    return SPORT_CELL.get(sport, "ss-p1")
MAX_ROWS = 2500  # per table; keeps pages light enough for a phone


def page(title: str, summary: str, sport: str, views: list[dict], updated: str = "",
         how: str = "", order: int = 50, fill: dict | None = None, headline: str = "") -> dict:
    """`summary`: one plain sentence. `updated`: what the numbers are as of (e.g. "ESPN data
    through Oct 30, 2026"). `how`: two or three plain sentences on how the numbers are made.
    The model's site.md (edited in Claude UI) overrides title/summary/how; `fill` holds the
    values its {placeholders} can use (e.g. {"races": 85}). `headline`: the one answer a fan
    wants first, from the numbers (e.g. "Miami (FL) and Ohio State are the title favorites, 22%
    each"); shown in bold under the summary."""
    return {"title": title, "summary": summary, "sport": sport, "updated": updated, "how": how,
            "order": order, "views": views, "fill": fill or {}, "headline": headline}


TEXT_KEYS = ("title", "summary", "how")
_REGION = re.compile(r"<!--\s*claude-ui:begin\s+([a-z0-9-]+)\s*-->\n?(.*?)\n?\s*<!--\s*claude-ui:end\s+\1\s*-->", re.S)


def read_text_file(path) -> dict[str, str]:
    """Sections of a model's site.md: {"title": ..., "summary": ..., "how": ...} (whitespace
    collapsed to single spaces; empty sections are left out)."""
    from pathlib import Path

    path = Path(path)
    if not path.exists():
        return {}
    out = {}
    for key, body in _REGION.findall(path.read_text(encoding="utf-8")):
        text = " ".join(body.split())
        if text:
            out[key] = text
    return out


def apply_text(p: dict, text: dict[str, str]) -> dict:
    """Override the page's title/summary/how with site.md text, filling {placeholders} from
    p["fill"] (an unknown placeholder is left as written so the check below reports it)."""
    fill = p.get("fill") or {}
    for key in TEXT_KEYS:
        if key in text:
            p[key] = re.sub(r"\{(\w+)\}", lambda m: str(fill.get(m.group(1), m.group(0))), text[key])
    return p


def slug(text: str) -> str:
    """URL-safe name for a picker option ("Miami (FL)" -> "miami-fl"); site.js uses the same rule."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def col(key: str, label: str, fmt: str = "text", decimals: int | None = None, bar: bool = False,
        align: str | None = None, heat: bool = False, link: str | None = None, low_first: bool = False,
        sticky: bool = False, hidden: bool = False) -> dict:
    """A table column. `bar`: draw a small bar behind a pct/number cell (scaled to the column max).
    `heat`: shade the cell by its value (0 to the largest value in any heat column of the table).
    `link`: id of a picker on the same page; the cell links to the option whose slug matches the
    cell text (e.g. a team name opens that team's view). `low_first`: clicking the header sorts
    smallest first (ranks: No. 1 at the top). `sticky`: this column stays put when the table
    scrolls sideways (default: the first linked column, else the first text column). `hidden`:
    starts hidden; every table has a Columns menu where the reader can show or hide columns."""
    c = {"key": key, "label": label, "fmt": fmt}
    if decimals is not None:
        c["decimals"] = decimals
    if bar:
        c["bar"] = True
    if heat:
        c["heat"] = True
    if link:
        c["link"] = link
    if low_first:
        c["low_first"] = True
    if sticky:
        c["sticky"] = True
    if align:
        c["align"] = align
    if hidden:
        c["hidden"] = True
    return c


def table(id: str, title: str, columns: list[dict], rows: list[dict], subtitle: str = "", note: str = "",
          search: bool = False, page_size: int = 0, sort: str | None = None, sort_desc: bool = True) -> dict:
    """`page_size`: show this many rows, then a "Show all" button (0 = all). `sort`: default
    sort column key (rows are shown in the given order when omitted)."""
    v = {"kind": "table", "id": id, "title": title, "subtitle": subtitle, "note": note,
         "columns": columns, "rows": rows, "search": search, "page_size": page_size}
    if sort:
        v["sort"], v["sort_desc"] = sort, sort_desc
    return v


def bar(id: str, title: str, items: list[dict], fmt: str = "pct", subtitle: str = "", note: str = "",
        decimals: int | None = None) -> dict:
    """Horizontal bars, one per item: {"label", "value", optional "sub" (small text after the label)}."""
    v = {"kind": "bar", "id": id, "title": title, "subtitle": subtitle, "note": note, "fmt": fmt, "items": items}
    if decimals is not None:
        v["decimals"] = decimals
    return v


def series(name: str, points: list[tuple[float, float]], band: list[tuple[float, float, float]] | None = None) -> dict:
    """One line: points (x, y); optional shaded band (x, low, high)."""
    s = {"name": name, "points": [[x, y] for x, y in points]}
    if band:
        s["band"] = [[x, lo, hi] for x, lo, hi in band]
    return s


def line(id: str, title: str, lines: list[dict], x_label: str = "", y_label: str = "", x_fmt: str = "number",
         y_fmt: str = "number", subtitle: str = "", note: str = "", markers: list[dict] | None = None,
         y_min: float | None = None, y_max: float | None = None, x_ticks: list[tuple[float, str]] | None = None) -> dict:
    """A line chart. `markers`: [{"x", "y", "label"}] dots with a short label (e.g. key plays).
    `x_ticks`: [(x, "Q2"), ...] named x-axis ticks instead of numbers."""
    v = {"kind": "line", "id": id, "title": title, "subtitle": subtitle, "note": note, "series": lines,
         "x_label": x_label, "y_label": y_label, "x_fmt": x_fmt, "y_fmt": y_fmt, "markers": markers or []}
    if x_ticks:
        v["x_ticks"] = [[x, str(label)] for x, label in x_ticks]
    if y_min is not None:
        v["y_min"] = y_min
    if y_max is not None:
        v["y_max"] = y_max
    return v


def option(label: str, views: list[dict], intro: str = "") -> dict:
    """One choice in a picker; it gets its own address /<model>/<picker id>/<slug(label)>/.
    `intro`: a short line shown above its views (e.g. a team's record and conference)."""
    o = {"label": label, "slug": slug(label), "views": views}
    if intro:
        o["intro"] = intro
    return o


def app(id: str, title: str, name: str, data: dict, subtitle: str = "", note: str = "") -> dict:
    """An interactive tool: web/static/apps/<name>.js draws it from `data` (everything it needs,
    written at build time). Keep it lightweight (no large data or models shipped to the browser);
    an app that copies a model's formulas must be checked against the Python model by a test
    (e.g. tests/test_race_calc.py)."""
    return {"kind": "app", "id": id, "title": title, "subtitle": subtitle, "note": note, "app": name, "data": data}


def picker(id: str, title: str, label: str, options: list[dict], subtitle: str = "", note: str = "",
           default: int = 0) -> dict:
    """A dropdown ("Race", "Team", "League") that swaps between groups of views."""
    return {"kind": "picker", "id": id, "title": title, "subtitle": subtitle, "note": note, "label": label,
            "options": options, "default": default}


def clean(value: Any) -> Any:
    """JSON-safe copy: NaN/inf -> None, tuples -> lists, numpy scalars -> Python numbers."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):  # numpy scalar
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def check(p: dict) -> list[str]:
    """Problems with a page (empty list = fine). Used by the build and the contract tests."""
    errs: list[str] = []
    for key in ("title", "summary", "sport", "views"):
        if not p.get(key):
            errs.append(f"page needs '{key}'")
    for key in TEXT_KEYS:
        left = re.findall(r"\{\w+\}", str(p.get(key) or ""))
        if left:
            errs.append(f"{key}: unknown placeholder(s) {left} (site.md); known: {sorted(p.get('fill') or {})}")
    if p.get("sport") and p["sport"] not in SPORTS:
        errs.append(f"sport must be one of {SPORTS}, got {p['sport']!r}")
    ids: set[str] = set()

    def walk(views: list[dict], where: str) -> None:
        for v in views:
            at = f"{where}/{v.get('id', '?')}"
            kind = v.get("kind")
            if kind not in KINDS:
                errs.append(f"{at}: kind must be one of {KINDS}")
                continue
            if not v.get("id") or not v.get("title"):
                errs.append(f"{at}: needs id and title")
            if where == "" and v.get("id") in ids:
                errs.append(f"{at}: duplicate id")
            ids.add(v.get("id"))
            if kind == "table":
                cols = v.get("columns") or []
                keys = [c.get("key") for c in cols]
                if not cols:
                    errs.append(f"{at}: no columns")
                for c in cols:
                    if c.get("fmt") not in FORMATS:
                        errs.append(f"{at}: column {c.get('key')} fmt {c.get('fmt')!r} not in {FORMATS}")
                rows = v.get("rows") or []
                if not rows:
                    errs.append(f"{at}: no rows")
                if len(rows) > MAX_ROWS:
                    errs.append(f"{at}: {len(rows)} rows (max {MAX_ROWS})")
                for i, r in enumerate(rows[:MAX_ROWS]):
                    missing = [k for k in keys if k not in r]
                    if missing:
                        errs.append(f"{at}: row {i} missing {missing}")
                        break
                if v.get("sort") and v["sort"] not in keys:
                    errs.append(f"{at}: sort key {v['sort']!r} is not a column")
            elif kind == "app":
                name = str(v.get("app") or "")
                if not re.fullmatch(r"[a-z0-9_]+", name) or not (APPS_DIR / f"{name}.js").is_file():
                    errs.append(f"{at}: app {name!r} has no web/static/apps/{name}.js")
                if not isinstance(v.get("data"), dict):
                    errs.append(f"{at}: app data must be a dict")
            elif kind == "bar":
                if not v.get("items"):
                    errs.append(f"{at}: no items")
                if v.get("fmt") not in FORMATS:
                    errs.append(f"{at}: fmt {v.get('fmt')!r} not in {FORMATS}")
                for it in v.get("items", []):
                    if "label" not in it or not isinstance(it.get("value"), (int, float)):
                        errs.append(f"{at}: every item needs label and a numeric value")
                        break
            elif kind == "line":
                if not v.get("series") or not all(s.get("points") for s in v["series"]):
                    errs.append(f"{at}: every series needs points")
                for f in ("x_fmt", "y_fmt"):
                    if v.get(f) not in FORMATS:
                        errs.append(f"{at}: {f} {v.get(f)!r} not in {FORMATS}")
            elif kind == "picker":
                opts = v.get("options") or []
                if not opts:
                    errs.append(f"{at}: no options")
                for o in opts:
                    if not o.get("label") or not o.get("views"):
                        errs.append(f"{at}: every option needs a label and views")
                        break
                    walk(o["views"], at)

    walk(p.get("views") or [], "")
    pickers = {v["id"]: v for v in p.get("views") or [] if v.get("kind") == "picker"}
    for v in p.get("views") or []:
        for opt_views in ([v] if v.get("kind") != "picker" else [w for o in v.get("options", []) for w in o.get("views", [])]):
            for c in opt_views.get("columns", []) if opt_views.get("kind") == "table" else []:
                if c.get("link") and c["link"] not in pickers:
                    errs.append(f"{v.get('id')}: column {c['key']} links to {c['link']!r}, not a top-level picker")
    for pid, pk in pickers.items():
        slugs = [o.get("slug") for o in pk.get("options", [])]
        if len(slugs) != len(set(slugs)):
            errs.append(f"{pid}: option labels must give unique slugs")
    try:
        json.dumps(p, allow_nan=False)
    except (TypeError, ValueError) as exc:
        errs.append(f"not JSON-serialisable: {exc} (wrap rows with views.clean)")
    return errs
