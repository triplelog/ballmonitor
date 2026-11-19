"""The progress tracker on the public page (web/static/apps/progress_tracker.js) must give the same
numbers as the progress_tracker model: it is a JavaScript copy of model.py, run in the visitor's
browser. Runs the script under node with the page's own data (site.py) and compares the plan,
adherence, predicted result and range, ahead/behind, the re-plan and the week-by-week table with
model.predict for several logs and plan shapes; plus the log import/export helpers and the
loading of an older v1 log."""

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ballmonitor.core import registry, views
from ballmonitor.models.progress_tracker import site

APP = Path(__file__).resolve().parent.parent / "ballmonitor" / "web" / "static" / "apps" / "progress_tracker.js"
NODE = shutil.which("node")
D0 = dt.date(2026, 1, 5)


def _series(values, every=7, start=D0):
    return [{"date": (start + dt.timedelta(days=every * i)).isoformat(), "value": v} for i, v in enumerate(values)]


def _end(entries, plus=0):
    return (dt.date.fromisoformat(entries[-1]["date"]) + dt.timedelta(days=plus)).isoformat()


LIFT = _series([60, 62.5, 62.5, 65, 67.5, 67.5, 70, 72.5])
CHESS = _series([1500, 1520, 1490, 1540, 1555, 1530, 1580, 1600, 1575, 1610], every=5)
PACE = _series([310, 305, 307, 300, 298, 301, 295])
BODY = _series([92.4, 91.8, 91.9, 91.1, 90.6, 90.8, 90.0, 89.7])
FAT = _series([24.0, 23.8, 23.9, 23.5, 23.6])
RACE = _series([3000, 2985, 2990, 2950], every=14)
PUSH = _series([20, 21, 21, 23, 22, 24, 25, 25], every=3)
DOWN = _series([100, 98, 95, 93])

CASES = [  # (measure settings, entries, today)
    ({"type": "lift", "shape": "faster_early", "goal_value": 100, "goal_date": "2026-09-01"}, LIFT, _end(LIFT)),
    ({"type": "lift", "shape": "even", "goal_value": 90, "goal_date": "2026-06-01", "start_date": "2026-01-19",
      "start_value": 61}, LIFT, _end(LIFT, 3)),
    ({"type": "lift", "shape": "faster_late", "goal_value": 120, "goal_date": "2027-01-01"}, LIFT, _end(LIFT)),
    ({"type": "chess_rating", "shape": "even", "goal_value": 1700, "goal_date": "2026-08-01"}, CHESS, _end(CHESS)),
    ({"type": "chess_rating", "shape": "faster_early", "goal_value": 1550, "goal_date": "2026-05-01"}, CHESS, _end(CHESS)),
    ({"type": "running_pace", "shape": "faster_late", "goal_value": 285, "goal_date": "2026-06-01"}, PACE, _end(PACE)),
    ({"type": "race_time", "shape": "even", "goal_value": 2880, "goal_date": "2026-12-01"}, RACE, _end(RACE)),
    ({"type": "body_weight", "shape": "even", "goal_value": 85, "goal_date": "2026-06-01"}, BODY, _end(BODY)),
    ({"type": "body_fat", "shape": "faster_early", "goal_value": 20, "goal_date": "2026-07-01"}, FAT, _end(FAT, 10)),
    ({"type": "custom", "scale": "log", "shape": "faster_early", "goal_value": 40, "goal_date": "2026-05-01"}, PUSH, _end(PUSH)),
    ({"type": "custom", "scale": "linear", "shape": "even", "goal_value": 10, "goal_date": "2026-05-01"}, PUSH, _end(PUSH)),
    ({"type": "lift", "shape": "even", "goal_value": 120, "goal_date": "2026-06-01"}, DOWN, _end(DOWN)),           # wrong way
    ({"type": "lift", "shape": "even", "goal_value": 120, "goal_date": "2026-06-01", "start_date": "2026-01-01",
      "start_value": 100}, [], "2026-01-10"),                                                                    # no entries
    # next week's goal: behind near the deadline (re-plan minimum), reached, past the goal date, on plan
    ({"type": "chess_rating", "shape": "even", "goal_value": 1700, "goal_date": "2026-02-20"}, CHESS, _end(CHESS)),
    ({"type": "chess_rating", "shape": "even", "goal_value": 1560, "goal_date": "2026-08-01"}, CHESS, _end(CHESS)),
    ({"type": "lift", "shape": "even", "goal_value": 100, "goal_date": "2026-02-01"}, LIFT, _end(LIFT)),
    ({"type": "body_weight", "shape": "even", "goal_value": 80, "goal_date": "2026-03-16", "start_date": "2026-01-05",
      "start_value": 90}, _series([90, 89, 88, 87, 86]), "2026-02-02"),
    # stale entries: today is weeks after the latest entry
    ({"type": "lift", "shape": "faster_early", "goal_value": 100, "goal_date": "2026-09-01"}, LIFT, _end(LIFT, 30)),
    ({"type": "running_pace", "shape": "even", "goal_value": 285, "goal_date": "2026-05-01"}, PACE, _end(PACE, 45)),
]


def _python(d, entries, today):
    inputs = {"metric": d["type"], "entries": entries, "today": today}
    for k in ("scale", "shape", "goal_value", "goal_date", "start_date", "start_value"):
        if k in d:
            inputs[k] = d[k]
    return registry.load_model("progress_tracker").predict(inputs)


def _node(script):
    return json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)


def _run_js(data, cases):
    js = [{"def": d, "entries": e, "today": t} for d, e, t in cases]
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const data = {json.dumps(data)};\n"
              f"const cases = {json.dumps(js)};\n"
              "console.log(JSON.stringify(cases.map((c) => { const r = app.compute(data, c.entries, c); "
              "if (r.error) return {error: r.error}; const { planAt, trackAt, ...rest } = r; return rest; })));")
    return _node(script)


def _close(a, b):
    if b is None:
        return a is None
    return a == pytest.approx(b, rel=1e-9, abs=1e-12)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_tool_matches_the_model():
    data = site.app_data(registry.load_model("progress_tracker"))
    out = _run_js(data, CASES)
    for case, js in zip(CASES, out):
        assert "error" not in js, (case[0], js)
        x = _python(*case).extras
        for k in ("f", "sxx", "sxy", "resid_var", "f_var", "predicted", "planned_today", "start_value", "plan_weeks"):
            assert _close(js[k], x[k]), (case[0], k, js[k], x[k])
        assert js["wrong_way"] == x["wrong_way"] and js["n"] == x["n"] and js["start_date"] == x["start_date"]
        assert (js["interval"] is None) == (x["interval"] is None)
        if x["interval"]:
            assert js["interval"] == pytest.approx(x["interval"], rel=1e-9)
        assert (js["track"] is None) == (x["track"] is None)
        if x["track"]:
            for k in ("planned", "gap", "gap_change"):
                assert _close(js["track"][k], x["track"][k]), (case[0], k)
            assert js["track"]["ahead"] == x["track"]["ahead"]
        assert (js["replan"] is None) == (x["replan"] is None)
        if x["replan"]:
            for k in ("per_week", "weeks"):
                assert _close(js["replan"][k], x["replan"][k]), (case[0], k)
            assert js["replan"]["done"] == x["replan"]["done"]
        assert (js["next_goal"] is None) == (x["next_goal"] is None), case[0]
        if x["next_goal"]:
            assert js["next_goal"]["reason"] == x["next_goal"]["reason"], (case[0], js["next_goal"], x["next_goal"])
            for k in ("value", "change", "gap", "step"):
                if k in x["next_goal"]:
                    assert _close(js["next_goal"][k], x["next_goal"][k]), (case[0], k)
            assert js["next_goal"].get("date") == x["next_goal"].get("date")
        assert len(js["weeks_table"]) == len(x["weeks_table"]), case[0]
        for a, b in zip(js["weeks_table"], x["weeks_table"]):
            assert a["date"] == b["date"] and a["week"] == b["week"]
            for k in ("plan", "replan", "track"):
                assert _close(a[k], b[k]), (case[0], k)
    assert any(o["wrong_way"] for o in out) and any(o["interval"] for o in out)
    reasons = {o["next_goal"]["reason"] for o in out if o["next_goal"]}
    assert {"minimum", "reached", "past_goal_date", "on_plan", "ahead", "catch_up"} <= reasons, reasons


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_tool_refuses_what_the_model_refuses():
    data = site.app_data(registry.load_model("progress_tracker"))
    bad = [
        ({"type": "lift", "shape": "even", "goal_value": 100, "goal_date": "2025-01-01"}, LIFT, _end(LIFT)),   # goal before start
        ({"type": "lift", "shape": "even", "goal_value": 60, "goal_date": "2026-06-01"}, LIFT, _end(LIFT)),    # goal = start
        ({"type": "lift", "shape": "even", "goal_value": 100, "goal_date": "2026-06-01"}, _series([60, 0]), "2026-01-12"),
        ({"type": "lift", "shape": "even", "goal_value": 100, "goal_date": "2036-06-01"}, LIFT, _end(LIFT)),   # too long
    ]
    out = _run_js(data, bad)
    for case, js in zip(bad, out):
        assert "error" in js, case
        with pytest.raises(ValueError):
            _python(*case)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_old_v1_settings_load():
    data = site.app_data(registry.load_model("progress_tracker"))
    old = {"model": "progress_tracker", "version": 1, "settings": {"selected": "Squat", "target_date": "2027-01-01",
           "measures": {"Squat": {"type": "lift", "unit": "kg", "direction": "higher", "window_weeks": 8,
                                  "goal_value": 140, "goal_date": "2026-09-01"}}},
           "entries": [{"date": "2026-01-05", "metric": "Squat", "value": 100}]}
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const data = {json.dumps(data)};\n"
              f"console.log(JSON.stringify(app.importJSON(data, {json.dumps(json.dumps(old))})));")
    got = _node(script)
    sq = got["settings"]["measures"]["Squat"]
    assert sq["goal_value"] == 140 and sq["goal_date"] == "2026-09-01" and sq["shape"] == "faster_early"
    assert "window_weeks" not in sq and "target_date" not in got["settings"] and got["settings"]["selected"] == "Squat"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_log_import_export_helpers():
    data = site.app_data(registry.load_model("progress_tracker"))
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const data = {json.dumps(data)};\n"
              "const csv = 'date,metric,value\\n2026-01-05,Squat,100\\n2026-01-12,Squat,102.5\\nnope,Squat,1\\n2026-01-12,Mile,6:05\\n';\n"
              "const got = app.importCSV(csv, null);\n"
              "const two = app.importCSV('Date,Value\\n2026-02-01,1500\\n', 'Chess');\n"
              "const back = app.importCSV(app.toCSV(got.entries), null);\n"
              "const m = app.merge(got.entries, [{date: '2026-01-12', metric: 'Squat', value: 105}, {date: '2026-01-19', metric: 'Squat', value: 106}]);\n"
              "const json = app.importJSON(data, JSON.stringify({model: 'progress_tracker', version: 1, settings: {selected: 'Squat', "
              "target_date: '2026-12-01', measures: {Squat: {type: 'lift', unit: 'kg', window_weeks: 6, goal_value: 140, goal_date: '2026-09-01'}, "
              "Bad: {type: 'nope'}}}, entries: [{date: '2026-01-05', metric: 'Squat', value: 100}, {date: 'x', metric: 'Squat', value: 1}]}));\n"
              "const other = app.importJSON(data, JSON.stringify({model: 'race_time', entries: []}));\n"
              "console.log(JSON.stringify({got, two, back, m, json, other, "
              "parse: ['5:00', '1:02:03', '12.5', '1e3', 'abc', '5:6:7:8', ''].map(app.parseValue)}));")
    out = _node(script)
    assert [e["value"] for e in out["got"]["entries"]] == [100, 102.5, 365]
    assert out["got"]["skipped"][0][0] == 4
    assert out["two"]["entries"] == [{"date": "2026-02-01", "metric": "Chess", "value": 1500}]
    assert out["back"]["entries"] == out["got"]["entries"]
    assert (out["m"]["added"], out["m"]["updated"], out["m"]["same"]) == (1, 1, 0)
    s = out["json"]["settings"]
    assert list(s["measures"]) == ["Squat"] and s["measures"]["Squat"]["goal_value"] == 140 and s["selected"] == "Squat"
    assert len(out["json"]["entries"]) == 1 and len(out["json"]["skipped"]) == 1
    assert out["other"]["entries"] == [] and "race_time" in out["other"]["skipped"][0][1]
    assert out["parse"] == [300, 3723, 12.5, 1000, None, None, None]


def test_page_has_the_tool_and_is_valid():
    page = site.page(registry.load_model("progress_tracker"))
    tool = next(v for v in page["views"] if v["kind"] == "app")
    assert tool["app"] == "progress_tracker" and views.check(views.clean(page)) == []
    data = tool["data"]
    assert data["storage_key"] == "bm.log.progress_tracker.v1"
    assert {p["key"] for p in data["presets"]} >= {"chess_rating", "lift", "running_pace", "race_time", "body_weight", "body_fat", "custom"}
    assert data["shapes"] == ["even", "faster_early", "faster_late"] and 0.5 < data["front_share"]["strength"] <= 1
