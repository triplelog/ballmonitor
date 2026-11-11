"""The race time calculator on the public page (web/static/apps/race_time.js) must give the same
numbers as the race_time model: it is a JavaScript copy of the default method, run in the
visitor's browser. Runs the script under node with the page's own data (site.py) and compares
every distance's 2.5-97.5% quantiles with model.predict for a range of runners."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ballmonitor.core import registry, views
from ballmonitor.core.units import parse_distance
from ballmonitor.models.race_time import site

APP = Path(__file__).resolve().parent.parent / "ballmonitor" / "web" / "static" / "apps" / "race_time.js"
NODE = shutil.which("node")
TARGET_YEAR = 2026

CASES = [   # (gender, [(distance, time, years before)])
    ("M", [("5k", "25:00", 0)]),
    ("F", [("5k", "25:00", 0)]),
    ("", [("10k", "48:10", 0)]),
    ("M", [("5k", "19:40", 0), ("half", "1:31:30", 1)]),
    ("F", [("mile", "6:55", 0), ("10k", "51:00", 0), ("marathon", "4:02:00", 2)]),
    ("M", [("5k", "31:00", 3), ("8k", "52:30", 3)]),
    ("F", [("half", "2:10:00", 0), ("half", "2:04:00", 1), ("10 mile", "1:35:00", 2), ("5k", "28:00", 0)]),
]


def _python(model, gender, races):
    inputs = {"target": "marathon", "target_year": TARGET_YEAR,
              "races": [{"distance": d, "time": t, "year": TARGET_YEAR - y} for d, t, y in races]}
    if gender:
        inputs["gender"] = gender
    return {b["label"]: [b[f"{k}_sec"] for k in ("p025", "p10", "p25", "p50", "p75", "p90", "p975")]
            for b in model.predict(inputs).extras["benchmarks"]}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_calculator_matches_the_model():
    model = registry.load_model("race_time")
    data = site.calculator_data(model)
    js_cases = [{"gender": g, "races": [{"d": parse_distance(d), "t": _seconds(t), "years": y} for d, t, y in races]}
                for g, races in CASES]
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const data = {json.dumps(data)};\n"
              f"const cases = {json.dumps(js_cases)};\n"
              "console.log(JSON.stringify(cases.map((c) => app.compute(data, c.gender, c.races).rows"
              ".map((r) => [r.meters, r.times]))));")
    out = json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)
    labels = {m: lbl for lbl, m, _ in site.BENCHMARKS}
    for (gender, races), rows in zip(CASES, out):
        expected = _python(model, gender, races)
        for meters, times in rows:
            want = expected[labels[meters]]
            for got, exp in zip(times, want):
                # the model rounds its benchmark times to 0.1 s
                assert got == pytest.approx(exp, abs=0.051), (gender, races, labels[meters])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_calculator_reads_times_and_describes_the_runners_own_curve():
    model = registry.load_model("race_time")
    data = site.calculator_data(model)
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const data = {json.dumps(data)};\n"
              "const one = app.compute(data, 'M', [{d: 5000, t: 1500, years: 0}]);\n"
              "const two = app.compute(data, 'M', [{d: 5000, t: 1500, years: 0}, {d: 10000, t: 3000, years: 0}]);\n"
              "console.log(JSON.stringify({parse: ['25:00', '1:52:30', '25', '2:5x', ''].map(app.parseTime),"
              " one: one.own, two: two.own}));")
    out = json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)
    assert out["parse"] == [1500, 6750, 1500, None, None]
    assert out["one"] is None                         # one distance: no curve of your own
    assert out["two"] == pytest.approx(1.0)           # 10K at exactly twice the 5K time: exponent 1


def test_calculator_view_is_on_the_page_and_valid():
    page = site.page(registry.load_model("race_time"))
    calc = next(v for v in page["views"] if v["kind"] == "app")
    assert calc["app"] == "race_time" and views.check(views.clean(page)) == []
    data = calc["data"]
    assert len(data["bands"]["coef"]) == 7 and all(len(c) == 4 for c in data["bands"]["coef"])
    assert data["typical"]["M"] > data["typical"]["F"]
    assert any(d["input"] for d in data["distances"]) and len(data["example"]) >= 1


def _seconds(t: str) -> float:
    parts = [float(x) for x in t.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]
