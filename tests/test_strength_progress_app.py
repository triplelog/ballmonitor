"""The strength log tool on the public page (web/static/apps/strength_progress.js) must give the
same numbers as the strength_progress model: it is a JavaScript copy of the default method, run in
the visitor's browser. Runs the script under node with the page's own data (site.py) and compares
every lift's 2.5-97.5% quantiles with model.predict for several logs, plus the file imports."""

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ballmonitor.core import registry, views
from ballmonitor.models.strength_progress import site

APP = Path(__file__).resolve().parent.parent / "ballmonitor" / "web" / "static" / "apps" / "strength_progress.js"
NODE = shutil.which("node")
D0 = dt.date(2026, 1, 5)


def _weekly(n, weight, reps=None, seconds=None, exercise="Squat", every=7, step=0.0, start=D0):
    out = []
    for i in range(n):
        e = {"date": (start + dt.timedelta(days=every * i)).isoformat(), "exercise": exercise,
             "weight": weight + step * i, "unit": "kg"}
        e["reps" if reps is not None else "seconds"] = reps if reps is not None else seconds
        out.append(e)
    return out


CASES = [  # (entries, today, target, exercise, training_since)
    (_weekly(9, 100, reps=5), "2026-03-02", "2026-08-31", None, None),                        # beginner
    (_weekly(9, 100, reps=5), "2026-03-02", "2026-08-31", None, "2023-01-02"),                # veteran
    (_weekly(3, 60, reps=8, every=21), "2026-03-02", "2026-03-30", None, None),               # irregular, short
    (_weekly(12, 92, seconds=120, exercise="Leg press", step=1.5), "2026-04-13", "2027-04-12", None, None),
    (_weekly(9, 100, reps=5) + _weekly(9, 60, reps=8, exercise="Bench", step=1.25)
     + [{"date": "2026-03-02", "exercise": "Squat", "weight": 105, "unit": "kg", "reps": 3},   # several sets a day
        {"date": "2026-03-02", "exercise": "Squat", "weight": 90, "unit": "kg", "reps": 10}],
     "2026-04-20", "2026-07-13", "Bench", None),                                              # 7-week gap
    (_weekly(4, 100, reps=1), "2026-01-26", "2026-02-02", None, None),                       # one week ahead
    (_weekly(30, 40, reps=12, every=4), "2026-05-01", "2026-11-01", None, "2025-06-01"),       # twice a week
]


def _python(entries, today, target, exercise, since):
    log = [{("duration" if k == "seconds" else k): v for k, v in e.items() if k != "unit"} for e in entries]
    inputs = {"log": log, "today": today, "target_date": target}
    if exercise:
        inputs["exercise"] = exercise
    if since:
        inputs["training_since"] = since
    pred = registry.load_model("strength_progress").predict(inputs)
    return pred


def _node(script):
    return json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_tool_matches_the_model():
    data = site.app_data(registry.load_model("strength_progress"))
    js_cases = [{"entries": e, "today": t, "target_date": g, "exercise": x, "training_since": s}
                for e, t, g, x, s in CASES]
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const data = {json.dumps(data)};\n"
              f"const cases = {json.dumps(js_cases)};\n"
              "console.log(JSON.stringify(cases.map((c) => { const r = app.compute(data, c.entries, c); "
              "return r.error ? {error: r.error} : [r.primary, ...r.others].map((o) => "
              "({exercise: o.exercise, weights: o.weights, values: o.values, current: o.current, gain: o.gain})); })));")
    out = _node(script)
    for case, rows in zip(CASES, out):
        assert not isinstance(rows, dict), rows
        pred = _python(*case)
        ex = pred.extras["exercises"]
        assert [r["exercise"] for r in rows] == list(ex)
        assert pred.primary.estimate == pytest.approx(rows[0]["weights"][3], rel=1e-9)
        lo, hi = pred.primary.interval
        assert (lo, hi) == pytest.approx((rows[0]["weights"][1], rows[0]["weights"][5]), rel=1e-9)
        assert pred.extras["_quantiles"] == pytest.approx(rows[0]["weights"], rel=1e-9)
        for r in rows:
            e = ex[r["exercise"]]
            assert r["gain"] == pytest.approx(e["gain"], abs=1e-6)
            assert r["current"] == pytest.approx(e["current"], abs=1e-4)
            assert r["weights"][3] == pytest.approx(e["median_weight"], abs=1e-3)
            for lv, (a, b) in e["bands"].items():
                i = {"0.5": (2, 4), "0.8": (1, 5), "0.95": (0, 6)}[lv]
                assert (r["weights"][i[0]], r["weights"][i[1]]) == pytest.approx((a, b), abs=1e-3)
        if pred.extras["exercises"][rows[0]["exercise"]]["sessions"] and any("reps" in e for e in case[0]):
            one_rm = pred.outcome("Estimated one-rep max")
            assert one_rm.estimate == pytest.approx(rows[0]["values"][3], rel=1e-9)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_tool_refuses_what_the_model_refuses_and_converts_units():
    data = site.app_data(registry.load_model("strength_progress"))
    lb = [dict(e, weight=e["weight"] / data["kg_per_lb"], unit="lb") for e in _weekly(9, 100, reps=5)]
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const data = {json.dumps(data)};\n"
              f"const kg = {json.dumps(_weekly(9, 100, reps=5))}, lb = {json.dumps(lb)};\n"
              "const o = {today: '2026-03-02', target_date: '2026-08-31'};\n"
              "console.log(JSON.stringify({past: app.compute(data, kg, {...o, target_date: '2026-03-01'}).error || null,"
              " far: app.compute(data, kg, {...o, target_date: '2027-06-01'}).error || null,"
              " empty: app.compute(data, [], o).error || null,"
              " kg: app.compute(data, kg, o).primary.weights[3], lb: app.compute(data, lb, o).primary.weights[3],"
              " lbShown: app.compute(data, kg, {...o, unit: 'lb'}).primary.weights[3]}));")
    out = _node(script)
    assert out["past"] and out["far"] and out["empty"]
    assert out["lb"] == pytest.approx(out["kg"], rel=1e-9)
    assert out["lbShown"] == pytest.approx(out["kg"] / data["kg_per_lb"], rel=1e-9)


HEVY = """"title","start_time","end_time","description","exercise_title","superset_id","exercise_notes","set_index","set_type","weight_kg","reps","distance_km","duration_seconds","rpe"
"Leg day","26 Jan 2025, 10:31","26 Jan 2025, 11:30","","Squat (Barbell)",,"",0,"warmup",60,8,,,
"Leg day","26 Jan 2025, 10:31","26 Jan 2025, 11:30","","Squat (Barbell)",,"",1,"normal",100,5,,,8
"Leg day","26 Jan 2025, 10:31","26 Jan 2025, 11:30","","Plank",,"",0,"normal",,,,60,
"Leg day","26 Jan 2025, 10:31","26 Jan 2025, 11:30","","Wall sit",,"",0,"normal",10,,,45,
"""
STRONG = """Date;Workout Name;Duration;Exercise Name;Set Order;Weight;Reps;Distance;Seconds;Notes;Workout Notes;RPE
2023-01-15 08:30:00;Push;45m;Bench Press (Barbell);1;62,5;8;0;0;;;
2023-01-15 08:30:00;Push;45m;Bench Press (Barbell);Rest Timer;0;0;0;90;;;
2023-01-17 08:30:00;Push;45m;Bench Press (Barbell);1;65;6;0;0;;;
"""
GENERIC = """date,exercise,weight,unit,reps,seconds
2026-01-05,Squat,100,kg,5,
2026-01-12,"Squat, pause",90,lb,3,
2026-13-01,Squat,100,kg,5,
2026-01-19,Squat,abc,kg,5,
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_imports_and_exports():
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const files = {json.dumps({'hevy': HEVY, 'strong': STRONG, 'generic': GENERIC})};\n"
              "const h = app.importCSV(files.hevy, 'kg'), s = app.importCSV(files.strong, 'lb'), g = app.importCSV(files.generic, 'kg');\n"
              "const back = app.importCSV(app.toCSV(g.entries), 'kg');\n"
              "const j = app.importJSON(JSON.stringify({model: 'strength_progress', version: 1, settings: {target_date: '2026-06-01', unit: 'lb', evil: '<script>'}, entries: g.entries}), 'kg');\n"
              "const other = app.importJSON(JSON.stringify({model: 'weight_loss', entries: []}), 'kg');\n"
              "const m = app.merge(g.entries, back.entries.concat([{date: '2026-02-01', exercise: 'Squat', weight: 1, unit: 'kg', reps: 1}]));\n"
              "console.log(JSON.stringify({h, s, g, back: back.entries, j, other, m: [m.added, m.duplicates, m.entries.length]}));")
    out = _node(script)
    h, s, g = out["h"], out["s"], out["g"]
    assert h["format"] == "Hevy" and len(h["entries"]) == 3          # plank has no weight: skipped
    assert h["entries"][0] == {"date": "2025-01-26", "exercise": "Squat (Barbell)", "weight": 60, "unit": "kg", "reps": 8}
    assert h["entries"][2]["seconds"] == 45 and len(h["skipped"]) == 1
    assert s["format"] == "Strong" and len(s["entries"]) == 2          # rest timer row skipped
    assert s["entries"][0] == {"date": "2023-01-15", "exercise": "Bench Press (Barbell)", "weight": 62.5, "unit": "lb", "reps": 8}
    assert g["format"] == "spreadsheet" and len(g["entries"]) == 2 and len(g["skipped"]) == 2
    assert g["entries"][1]["exercise"] == "Squat, pause" and g["entries"][1]["unit"] == "lb"
    assert out["back"] == g["entries"]                                 # CSV export round-trips
    assert out["j"]["entries"] == g["entries"] and out["j"]["settings"] == {"target_date": "2026-06-01", "unit": "lb"}
    assert out["other"]["entries"] == [] and out["other"]["skipped"]
    assert out["m"] == [1, 2, 3]


def test_tool_view_is_on_the_page_and_valid():
    page = site.page(registry.load_model("strength_progress"))
    tool = next(v for v in page["views"] if v["kind"] == "app")
    assert tool["app"] == "strength_progress" and views.check(views.clean(page)) == []
    data = tool["data"]
    assert data["storage_key"] == "bm.log.strength_progress.v1"
    assert len(data["coef"]) == 7 and all(len(c) == 5 for c in data["coef"])
    assert "fit20" in page["how"]
