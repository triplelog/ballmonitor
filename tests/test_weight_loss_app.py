"""The weight loss planner on the public page (web/static/apps/weight_loss.js) must give the same
numbers as the weight_loss model: it is a JavaScript copy of the daily simulation, the adherence
fit, the bands and the goal search, run in the visitor's browser. Runs the script under node with
the page's own data (site.py) and compares with model.predict, plus the log's import/export
helpers."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ballmonitor.core import registry, views
from ballmonitor.models.weight_loss import site

APP = Path(__file__).resolve().parent.parent / "ballmonitor" / "web" / "static" / "apps" / "weight_loss.js"
NODE = shutil.which("node")

BASE = {"sex": "M", "age": 40, "height_cm": 180, "weight": 100, "units": "kg", "activity": "sedentary",
        "intake_change": -500, "start_date": "2026-01-05", "target_date": "2027-01-04"}
CASES = [
    BASE,
    {**BASE, "intake_change": 0, "target_date": "2029-01-05"},
    {**BASE, "sex": "F", "age": 55, "height_cm": None, "height_in": 64, "weight": 190, "units": "lb",
     "activity": "active", "intake_change": -300, "activity_change_pct": 25, "goal_weight": 170},
    {**BASE, "body_fat_pct": 18, "activity": "vigorous", "intake_change": 400, "target_date": "2026-03-01"},
    {**BASE, "goal_weight": 90, "weighins": [{"date": "2026-01-05", "weight": 100},
                                             {"date": "2026-02-02", "weight": 98.9},
                                             {"date": "2026-03-02", "weight": 98.1},
                                             {"date": "2026-04-06", "weight": 97.0}]},
    {**BASE, "sex": "F", "age": 30, "height_cm": 160, "weight": 150, "units": "lb", "intake_change": -750,
     "exercise_kcal": 150, "carb_pct_after": 30, "sodium_change_mg": -500, "target_date": "2028-06-01",
     "weighins": [{"date": "2026-01-20", "weight": 147.0}, {"date": "2026-03-01", "weight": 142.5},
                  {"date": "2026-12-01", "weight": 139.0}]},
    {**BASE, "intake_change": -500, "weighins": [{"date": "2026-02-01", "weight": 99.5},
                                                 {"date": "2027-06-01", "weight": 95.0}]},  # after target
]
BAD = [
    {**BASE, "sex": "X"},
    {**BASE, "age": 12},
    {**BASE, "weight": -5},
    {**BASE, "target_date": "2025-12-01"},
    {**BASE, "target_date": "2045-01-01"},
    {**BASE, "start_date": "soon"},
    {**BASE, "activity": "couch"},
    {**BASE, "intake_change": -5000},
    {**BASE, "body_fat_pct": 120},
    {**BASE, "weighins": [{"date": "2025-12-25", "weight": 101}]},
]
KEYS = ("weight_kg", "fat_kg", "maintenance_kcal", "effective_change_kcal", "effective_change_sd",
        "prior_change_kcal", "tau_days", "eventual_change_kg", "fat0_kg")


def _node(script: str):
    return json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)


def _js(data, cases):
    return _node(f"const app = require({json.dumps(str(APP))});\n"
                 f"const data = {json.dumps(data)};\n"
                 f"const cases = {json.dumps(cases)};\n"
                 "console.log(JSON.stringify(cases.map((c) => app.compute(data, c))));")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_planner_matches_the_model():
    model = registry.load_model("weight_loss")
    data = site.app_data(model)
    for case, got in zip(CASES, _js(data, CASES)):
        assert "error" not in got, (case, got)
        want = model.predict({k: v for k, v in case.items() if v is not None}).extras
        for key in KEYS:
            assert got[key] == pytest.approx(want[key], rel=1e-9, abs=1e-7), (key, case)
        for level, (lo, hi) in want["bands_kg"].items():
            assert got["bands_kg"][level] == pytest.approx([lo, hi], rel=1e-9), (level, case)
        assert got["trajectory_kg"] == pytest.approx(want["trajectory_kg"], rel=1e-9)
        if want["adherence"] is None:
            assert got["adherence"] is None
        else:
            assert got["adherence"] == pytest.approx(want["adherence"], rel=1e-9)
        for key in ("goal_intake", "goal_maintenance_intake", "goal_reached_kg"):
            if key in want:
                assert got[key] == pytest.approx(want[key], rel=1e-9), (key, case)
            else:
                assert key not in got


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_planner_rejects_what_the_model_rejects():
    model = registry.load_model("weight_loss")
    for case, got in zip(BAD, _js(site.app_data(model), BAD)):
        with pytest.raises(ValueError):
            model.predict(case)
        assert got.get("error"), case


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_log_import_export():
    data = site.app_data(registry.load_model("weight_loss"))
    log = {"model": "weight_loss", "version": 1, "updated": "2026-11-19T10:00:00Z",
           "settings": {"units": "lb", "sex": "F", "age": 40, "height_cm": 165, "start_weight": 180,
                        "activity": "sedentary", "intake_change": -500, "start_date": "2026-01-05",
                        "target_date": "2026-07-06", "goal_weight": 165, "evil": "<script>"},
           "entries": [{"date": "2026-01-12", "weight": 178.5, "unit": "lb"},
                       {"date": "2026-01-19", "weight": "abc", "unit": "lb"},
                       {"date": "2026-13-40", "weight": 177, "unit": "lb"}]}
    csv = ("Date,Weight (kg),Note\n2026-01-26,80.5,ok\n\"2026-02-02 07:30\",80.1,\"a, b\"\n"
           "2/9/2026,79.8,\n2026-02-16,9999,typo\n")
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const data = {json.dumps(data)};\n"
              f"const a = app.parseImport(data, {json.dumps(json.dumps(log))}, 'kg');\n"
              f"const b = app.parseImport(data, {json.dumps(csv)}, 'lb');\n"
              "const c = app.parseImport(data, 'date;weight;unit\\n2026-03-01;81,2;kg\\n', 'lb');\n"
              "const other = app.parseImport(data, JSON.stringify({model: 'race_time', entries: []}), 'kg');\n"
              "const bad = app.parseImport(data, '{not json', 'kg');\n"
              "const merged = app.mergeEntries(a.entries, [...b.entries, {date: '2026-01-12', weight: 81, unit: 'kg'}]);\n"
              "const back = app.parseImport(data, app.toCSV(merged), 'kg');\n"
              "const inputs = app.inputsFrom(data, a.settings, merged);\n"
              "console.log(JSON.stringify({a, b, c, other, bad, merged, back, inputs}));")
    out = _node(script)
    a, b = out["a"], out["b"]
    assert a["entries"] == [{"date": "2026-01-12", "weight": 178.5, "unit": "lb"}]
    assert len(a["errors"]) == 2 and "evil" not in a["settings"] and a["settings"]["goal_weight"] == 165
    assert [e["date"] for e in b["entries"]] == ["2026-01-26", "2026-02-02", "2026-02-09"]
    assert all(e["unit"] == "kg" for e in b["entries"])          # unit from the "Weight (kg)" header
    assert len(b["errors"]) == 1 and "out of range" in b["errors"][0]
    assert out["c"]["entries"] == [{"date": "2026-03-01", "weight": 81.2, "unit": "kg"}]
    assert out["other"]["errors"] and out["bad"]["errors"]
    merged = out["merged"]
    assert [e["date"] for e in merged] == sorted(e["date"] for e in merged)
    assert next(e for e in merged if e["date"] == "2026-01-12")["unit"] == "kg"   # same date: imported row wins
    assert out["back"]["entries"] == merged and not out["back"]["errors"]
    # model inputs: every weigh-in in the settings' unit (lb)
    w = {x["date"]: x["weight"] for x in out["inputs"]["weighins"]}
    assert w["2026-01-26"] == pytest.approx(80.5 / 0.45359237)


def test_planner_view_is_on_the_page_and_valid():
    page = site.page(registry.load_model("weight_loss"))
    app = next(v for v in page["views"] if v["kind"] == "app")
    assert app["app"] == "weight_loss" and views.check(views.clean(page)) == []
    assert app["data"]["storage_key"] == "bm.log.weight_loss.v1"
    assert "not medical advice" in page["how"].lower() and "not been tested" in page["how"].lower()


def test_page_refuses_a_changed_formula():
    model = registry.load_model("weight_loss", None, {"formulas.rmr": "10 * weight + 6.25 * height_cm - 5 * age + 5"})
    with pytest.raises(ValueError, match="weight_loss.js"):
        site.app_data(model)
