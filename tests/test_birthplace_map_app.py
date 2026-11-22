"""The birthplace map on the public page (web/static/apps/birthplace_map.js) must give the same
numbers as the baseball_birthplaces model: it is a JavaScript copy of the projection, the
birthplace-disk overlap, the per-cell sums and the formula rules (core/formula.py). Runs the script
under node on the page's own files (site.files) and compares with engine.cell_values."""

import json
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from ballmonitor.core import registry
from ballmonitor.core.formula import evaluate as py_evaluate
from ballmonitor.models.baseball_birthplaces import engine as E
from ballmonitor.models.baseball_birthplaces import site

APP = Path(__file__).resolve().parent.parent / "ballmonitor" / "web" / "static" / "apps" / "birthplace_map.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

FORMULAS = [   # (include, value): plain names = the shown decade; _<decade> = another decade's circle
    ("1", "players"),
    ("1", "HR"),
    ("AB >= 1000", "H / AB"),
    ("G >= 500 or GS >= 150", "players"),
    ("HOF", "AS / players"),
    ("not (W > 0)", "round(SB / (players + 1), 1)"),
    ("born >= 1985 and seasons >= 3", "max(HR, K) if players > 2 else -1"),
    ("1", "players_1980 / players_1910"),
    ("G >= 100", "HR_1990 - HR + players_1950"),
]
EXPRESSIONS = ["round(2.675, 2)", "round(0.125, 2)", "round(-2.5)", "1 + 2 * 3 ** 2", "-2 ** 2", "7 // 2 + 7 % 3", "-7 // 2", "-7 % 3", "1 < 2 < 3", "3 > 2 > 2",
               "1 and 0", "0 or 5", "not 0", "2 if 1 > 0 else 3", "round(2.5) + round(3.5) + round(2.675, 2)",
               "min(3, 1, 2) + max(1, 4)", "abs(-3) + sqrt(16) + log(e) + log10(100) + log2(8)",
               "clamp(5, 0, 3) + floor(2.7) + ceil(2.1)", "logistic(0)", "pi * 2", "1e3 / 4", ".5 + 1"]


def run_node(script: str):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:   # too long for a command line
        fh.write(script)
    try:
        out = subprocess.run([NODE, fh.name], capture_output=True, text=True, timeout=300)
    finally:
        Path(fh.name).unlink()
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_formula_rules_match_python():
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const ex = {json.dumps(EXPRESSIONS)};\n"
              "console.log(JSON.stringify(ex.map((s) => +app.evaluate(app.parse(s, []), {}))));")
    js = run_node(script)
    for expr, got in zip(EXPRESSIONS, js):
        assert got == pytest.approx(float(py_evaluate(expr, {})), rel=1e-12), expr


def test_map_values_match_the_model():
    model = registry.load_model("baseball_birthplaces")
    files = site.files(model)
    meta = E.grid_meta(model.dir / "data")
    rng = random.Random(7)
    decades = sorted({1910, 1950, 1980, 1990, 1920, 2000})
    players = {d: json.loads(files[f"players/{d}.json"]) for d in decades}
    rows = {d: [{"lat": la, "lon": lo, "spread": s, **{k: pl[k][n] for k in E.STATS}}
                for n, (la, lo, s) in enumerate(zip(pl["lat"], pl["lon"], pl["spread"]))] for d, pl in players.items()}
    cases = []
    for decade, fname in ((1980, "main"), (1920, "main"), (2000, "alaska"), (1990, "hawaii")):
        frame = next(f for f in meta["frames"] if f["name"] == fname)
        grids = {d: (E.read_png(files[f"grid/{d}_{fname}.png"]), E.read_png(files[f"grid/{d}_{fname}_people.png"]))
                 for d in decades}
        code = grids[decade][0]
        land = [(i, j) for j in range(frame["ny"]) for i in range(frame["nx"]) if code[j][i] not in (E.OCEAN, E.NONE_WITHIN)]
        cells = rng.sample(land, min(30, len(land))) if land else []
        cases.append((decade, frame, grids, cells))
    js_input = [{"decade": decade, "frame": fr, "cells": [[i, j] for i, j in cells],
                 "grids": {str(d): {"code": [c for row in g[0] for c in row], "people": [c for row in g[1] for c in row]}
                           for d, g in grids.items()}} for decade, fr, grids, cells in cases]
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const cases = {json.dumps(js_input)};\n"
              f"const players = {json.dumps({str(d): v for d, v in players.items()})};\n"
              f"const formulas = {json.dumps(FORMULAS)};\n"
              f"const stats = {json.dumps(list(E.STATS))};\n"
              f"const target = {int(model.params.people)}, unit = {E.PEOPLE_UNIT};\n"
              "console.log(JSON.stringify(cases.map((c) => formulas.map(([inc, val]) => {\n"
              "  const decades = {};\n"
              "  for (const d of Object.keys(c.grids)) decades[+d] = { players: players[d], code: Uint16Array.from(c.grids[d].code), people: Uint16Array.from(c.grids[d].people) };\n"
              "  const v = app.compute(decades, c.frame, app.parse(inc, stats), app.parse(val), stats, c.decade, target, unit);\n"
              "  return c.cells.map(([i, j]) => { const x = v[j * c.frame.nx + i]; return Number.isNaN(x) ? null : x; });\n"
              "}))));")
    js = run_node(script)
    checked = 0
    for (decade, frame, grids, cells), js_case in zip(cases, js):
        for (inc, val), js_vals in zip(FORMULAS, js_case):
            m = registry.load_model("baseball_birthplaces", None, {"formulas.include": inc, "formulas.value": val})
            py = E.cell_values(rows, grids, frame, m.params, decade, cells=cells)
            for (i, j), got in zip(cells, js_vals):
                want = py.get((i, j))
                if want is None:
                    assert got is None, (decade, frame["name"], i, j, inc, val)
                else:
                    assert got == pytest.approx(want, rel=1e-9, abs=1e-9), (decade, frame["name"], i, j, inc, val)
                checked += 1
    assert checked > 500


REGIONS = [   # (frame, corners [lat, lon]) drawn the way a visitor would
    ("main", [[19.95, -71.70], [19.85, -69.90], [19.20, -68.30], [18.40, -68.30], [17.60, -71.40], [18.60, -71.75]]),
    ("main", [[34.80, -119.30], [34.60, -116.80], [32.60, -116.80], [32.55, -117.30], [33.70, -118.60], [34.10, -119.30]]),
    ("main", [[42.5, -91.5], [42.5, -87.0], [37.0, -87.0], [37.0, -91.5]]),
    ("hawaii", [[22.4, -160.4], [22.4, -154.6], [18.8, -154.6], [18.8, -160.4]]),
]
REGION_FORMULAS = [("1", "players"), ("G >= 500", "HR / players"), ("1", "players_1980 / players_1920"), ("HOF", "AS")]


def test_region_stats_match_the_model():
    model = registry.load_model("baseball_birthplaces")
    files = site.files(model)
    meta = E.grid_meta(model.dir / "data")
    decades = meta["decades"]
    players = {d: json.loads(files[f"players/{d}.json"]) for d in decades}
    rows = {d: [{"lat": la, "lon": lo, "spread": s, **{k: pl[k][n] for k in E.STATS}}
                for n, (la, lo, s) in enumerate(zip(pl["lat"], pl["lon"], pl["spread"]))] for d, pl in players.items()}
    cases = []
    for fname, corners in REGIONS:
        frame = next(f for f in meta["frames"] if f["name"] == fname)
        poly = [list(E.laea(a, b, frame["lat0"], frame["lon0"])) for a, b in corners]
        pops = {d: E.read_png(files[f"grid/{d}_{fname}_pop.png"]) for d in decades}
        cases.append((frame, poly, pops))
    js_input = [{"frame": fr, "poly": poly, "pops": {str(d): [c for row in g for c in row] for d, g in pops.items()}}
                for fr, poly, pops in cases]
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const cases = {json.dumps(js_input)};\n"
              f"const players = {json.dumps({str(d): v for d, v in players.items()})};\n"
              f"const formulas = {json.dumps(REGION_FORMULAS)};\n"
              f"const stats = {json.dumps(list(E.STATS))};\n"
              "console.log(JSON.stringify(cases.map((c) => formulas.map(([inc, val]) => {\n"
              "  const by = {};\n"
              "  for (const d of Object.keys(c.pops)) by[+d] = { players: players[d], pop: Uint16Array.from(c.pops[d]) };\n"
              f"  const r = app.regionStats(by, c.frame, c.poly, app.parse(inc, stats), app.parse(val), stats, {int(model.params.people)});\n"
              "  return { total: [r.total.people, r.total.players, r.total.value],\n"
              "    decades: Object.fromEntries(Object.entries(r.decades).map(([d, x]) => [d, [x.people, x.players, x.value]])) };\n"
              "}))));")
    js = run_node(script)
    for (frame, poly, pops), js_case in zip(cases, js):
        for (inc, val), got in zip(REGION_FORMULAS, js_case):
            m = registry.load_model("baseball_birthplaces", None, {"formulas.include": inc, "formulas.value": val})
            py = E.region_stats(rows, pops, frame, [tuple(q) for q in poly], m.params)
            want = [py["total"]["people"], py["total"]["players"], py["total"]["value"]]
            for a, b in zip(got["total"], want):
                assert (a is None) == (b is None) and (a is None or a == pytest.approx(b, rel=1e-9, abs=1e-9)), (frame["name"], inc, val)
            for d, x in py["decades"].items():
                g = got["decades"][str(d)]
                for a, b in zip(g, [x["people"], x["players"], x["value"]]):
                    assert (a is None) == (b is None) and (a is None or a == pytest.approx(b, rel=1e-9, abs=1e-9)), (frame["name"], d, inc, val)
