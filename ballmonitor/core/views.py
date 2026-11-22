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
        bracket("bracket", "Projected bracket", [round_("Final", [match(team("A", 1, 0.6), team("B", 2, 0.4))])]),
    ])
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

FORMATS = ("text", "int", "number", "pct", "time", "signed")
KINDS = ("table", "bar", "line", "picker", "app", "bracket")
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
    The page's source file (web/site/<address>/index.html, edited in Claude UI) overrides
    title/summary/how; `fill` holds the values its data-fill spans show (e.g. {"races": 85}). `headline`: the one answer a fan
    wants first, from the numbers (e.g. "Miami (FL) and Ohio State are the title favorites, 22%
    each"); shown in bold under the summary."""
    return {"title": title, "summary": summary, "sport": sport, "updated": updated, "how": how,
            "order": order, "views": views, "fill": fill or {}, "headline": headline}


TEXT_KEYS = ("title", "summary", "how")


def apply_text(p: dict, text: dict[str, str]) -> dict:
    """Override the page's title/summary/how with its source file's words (web/pages.read_text),
    filling {placeholders} from p["fill"] (an unknown placeholder is left as written so the check
    below reports it)."""
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
        sticky: bool = False, hidden: bool = False, sep: str | None = None) -> dict:
    """A table column. `bar`: draw a small bar behind a pct/number cell (scaled to the column max).
    `heat`: shade the cell by its value (0 to the largest value in any heat column of the table).
    `link`: id of a picker on the same page; the cell links to the option whose slug matches the
    cell text (e.g. a team name opens that team's view). `low_first`: clicking the header sorts
    smallest first (ranks: No. 1 at the top). `sticky`: this column stays put when the table
    scrolls sideways (default: the first linked column, else the first text column). `hidden`:
    starts hidden; every table has a Columns menu where the reader can show or hide columns.
    A text cell may hold a list of strings (several teams in one cell): they are shown joined by
    `sep` (default ", "), and with `link` each one that names an option of the picker is its own
    link (a part that names no option, like "at" in ["Texas", "at", "Georgia"] with sep=" ", stays text).
    With `link`, a cell (or part) is only linked when the picker has an option with its slug."""
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
    if sep is not None:
        c["sep"] = sep
    return c


def table(id: str, title: str, columns: list[dict], rows: list[dict], subtitle: str = "", note: str = "",
          search: bool = False, page_size: int = 0, sort: str | None = None, sort_desc: bool = True,
          quick_filters: tuple[str, list[str]] | None = None) -> dict:
    """`page_size`: show this many rows, then a "Show all" button (0 = all). `sort`: default
    sort column key (rows are shown in the given order when omitted). `quick_filters`:
    (column key, [values]): a row of buttons above the table, "All" then one per value, each
    showing only the rows whose cell is exactly that value (works together with the search box)."""
    v = {"kind": "table", "id": id, "title": title, "subtitle": subtitle, "note": note,
         "columns": columns, "rows": rows, "search": search, "page_size": page_size}
    if sort:
        v["sort"], v["sort_desc"] = sort, sort_desc
    if quick_filters:
        key, values = quick_filters
        v["quick_filters"] = {"key": key, "values": [str(x) for x in values]}
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
         y_min: float | None = None, y_max: float | None = None, x_ticks: list[tuple[float, str]] | None = None,
         y_reverse: bool = False) -> dict:
    """A line chart. `markers`: [{"x", "y", "label"}] dots with a short label (e.g. key plays).
    `x_ticks`: [(x, "Q2"), ...] named x-axis ticks instead of numbers. `y_reverse`: smallest y at
    the top (ranks: No. 1 highest)."""
    v = {"kind": "line", "id": id, "title": title, "subtitle": subtitle, "note": note, "series": lines,
         "x_label": x_label, "y_label": y_label, "x_fmt": x_fmt, "y_fmt": y_fmt, "markers": markers or []}
    if x_ticks:
        v["x_ticks"] = [[x, str(label)] for x, label in x_ticks]
    if y_min is not None:
        v["y_min"] = y_min
    if y_max is not None:
        v["y_max"] = y_max
    if y_reverse:
        v["y_reverse"] = True
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


def team(name: str, seed: int | None = None, p: float | None = None) -> dict:
    """One side of a bracket game: the name (linked like a table cell when the bracket has
    `link`), an optional seed and its chance to win this game (0-1)."""
    t: dict = {"name": name}
    if seed is not None:
        t["seed"] = seed
    if p is not None:
        t["p"] = p
    return t


def match(a: dict, b: dict | None = None, where: str = "", winner: int | None = None) -> dict:
    """A bracket game between team() a and b (b None: a's opponent isn't known yet). `winner`:
    0 or 1, the side shown going through (e.g. the favorite); `where`: a short place line."""
    g: dict = {"teams": [a] if b is None else [a, b]}
    if where:
        g["where"] = where
    if winner is not None:
        g["winner"] = winner
    return g


def round_(name: str, games: list[dict]) -> dict:
    """A bracket column ("First round"): its games top to bottom, in bracket order (so a game
    sits level with the one it feeds in the next round)."""
    return {"name": name, "games": games}


def bracket(id: str, title: str, rounds: list[dict], subtitle: str = "", note: str = "",
            link: str | None = None, champion: str = "") -> dict:
    """A knockout bracket drawn as one column per round (they scroll sideways on a phone).
    `link`: a picker id; team names that are its options link there. `champion`: the name shown
    at the end."""
    v = {"kind": "bracket", "id": id, "title": title, "subtitle": subtitle, "note": note, "rounds": rounds}
    if link:
        v["link"] = link
    if champion:
        v["champion"] = champion
    return v


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
            errs.append(f"{key}: unknown placeholder(s) {left} (data-fill spans in the page's web/site file); known: {sorted(p.get('fill') or {})}")
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
                for c in cols:
                    if any(isinstance(r.get(c.get("key")), list) and not all(isinstance(x, str) for x in r[c["key"]])
                           for r in rows[:MAX_ROWS]):
                        errs.append(f"{at}: column {c.get('key')}: a list cell may only hold strings")
                qf = v.get("quick_filters")
                if qf is not None:
                    if not isinstance(qf, dict) or qf.get("key") not in keys:
                        errs.append(f"{at}: quick_filters key {(qf or {}).get('key')!r} is not a column")
                    elif not qf.get("values") or not all(isinstance(x, str) and x for x in qf["values"]):
                        errs.append(f"{at}: quick_filters needs a list of values")
            elif kind == "bracket":
                rounds = v.get("rounds") or []
                if not rounds:
                    errs.append(f"{at}: no rounds")
                for rd in rounds:
                    games = rd.get("games") or []
                    if not rd.get("name") or not games:
                        errs.append(f"{at}: every round needs a name and games")
                        break
                    for g in games:
                        ts = g.get("teams") or []
                        if not 1 <= len(ts) <= 2 or not all(isinstance(t, dict) and t.get("name") for t in ts):
                            errs.append(f"{at}: {rd['name']}: every game needs one or two teams with a name")
                            break
                        if any(t.get("p") is not None and not (isinstance(t["p"], (int, float)) and 0 <= t["p"] <= 1)
                               for t in ts):
                            errs.append(f"{at}: {rd['name']}: a team's chance must be between 0 and 1")
                            break
                        if g.get("winner") is not None and g["winner"] not in range(len(ts)):
                            errs.append(f"{at}: {rd['name']}: winner must be 0 or 1")
                            break
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
            if opt_views.get("kind") == "bracket" and opt_views.get("link") and opt_views["link"] not in pickers:
                errs.append(f"{opt_views.get('id')}: bracket links to {opt_views['link']!r}, not a top-level picker")
    for pid, pk in pickers.items():
        slugs = [o.get("slug") for o in pk.get("options", [])]
        if len(slugs) != len(set(slugs)):
            errs.append(f"{pid}: option labels must give unique slugs")
    try:
        json.dumps(p, allow_nan=False)
    except (TypeError, ValueError) as exc:
        errs.append(f"not JSON-serialisable: {exc} (wrap rows with views.clean)")
    return errs
